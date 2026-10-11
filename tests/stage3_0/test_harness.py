from copy import deepcopy
from dataclasses import replace
import json
import socket

import pytest
from tau2.data_model.message import AssistantMessage, UserMessage, ToolMessage, MultiToolMessage
from tau2.data_model.simulation import SimulationRun
from tau2.orchestrator.orchestrator import Orchestrator

from policytrace.data.manifests import ROOT, read_json, digest, file_hash
from policytrace.data.manifests import read_jsonl
from policytrace.compatibility.multi_tool import parse_completion
from policytrace.harness.context import ContextBuilder
from policytrace.evaluation.metrics import aggregate
from policytrace.stage0.db_adapter import make_retail_env
from policytrace.harness.agent_adapter import StudentAgentAdapter
from policytrace.harness.context import HarnessError
from policytrace.harness.fixtures import call
from policytrace.harness.model_client import DeterministicMock
from policytrace.harness.runner import DevTaskPool, OfflineConfig, ScriptedUser


def test_native_orchestrator_is_execution_kernel(run,scripts,monkeypatch):
    actual = Orchestrator.run
    calls = []
    def spy(self):
        calls.append(self)
        return actual(self)
    monkeypatch.setattr(Orchestrator,'run',spy)
    result = run(*scripts['readonly'])
    assert len(calls)==1 and result.simulation.termination_reason.value=='user_stop'
    assert isinstance(calls[0].user,ScriptedUser)
    assert result.record.context.purpose=='diagnostic' and result.record.provenance=='mock'
    assert result.record.official_reward==1


def test_context_exact_observation_order_and_token_boundary(episodes,tokenizer):
    result = episodes['readonly',True]
    first,second = result.agent.decisions
    obs = result.environment.events[0]
    visible = second['context']['context_messages']
    tool = next(m for m in visible if m['role']=='tool')
    assert tool['content']==obs['observation']['content']
    assert tool['tool_call_id']==obs['call']['id']==obs['observation']['id']
    assert obs['raw_sha256']==obs['model_sha256']==digest(tool['content'])
    assert result.agent.domain_policy in second['context']['prompt_text']
    for decision in result.agent.decisions:
        context,generation = decision['context'],decision['generation']
        assert tokenizer.tokenizer.decode(context['prompt_token_ids'],skip_special_tokens=False)==context['prompt_text']
        assert tokenizer.tokenizer.decode(generation['generated_token_ids'],skip_special_tokens=False)==generation['text']
        assert generation['token_provenance']=='mock_encoded' and generation['provider_usage'] is None
        p,n = len(context['prompt_token_ids']),len(generation['generated_token_ids'])
        assert decision['student_action_token_spans']==[{'completion_start':0,'completion_end':n,'combined_start':p,'combined_end':p+n}]
        assert decision['role_mask']['condition_value']==0 and decision['role_mask']['student_action_value']==1
        assert all(s['current_student_action'] is False for s in context['condition_token_spans'])
        spans = context['condition_token_spans']
        assert spans[0]['token_start']==0 and spans[-1]['token_end']==p
        assert all(a['token_end']==b['token_start'] for a,b in zip(spans,spans[1:]))
        assert decision['logprobs'] is None
        index = decision['native_trajectory_index']
        assert result.simulation.messages[index]==AssistantMessage.model_validate(decision['native_message'])
    assert second['context']['prompt_tokens']>first['context']['prompt_tokens']


def test_write_state_is_isolated_and_full_native_replay_matches(episodes):
    result = episodes['write',True]
    readonly = episodes['readonly',True]
    assert result.summary['initial_db_hash']==readonly.summary['initial_db_hash']
    assert result.summary['final_db_hash']!=result.summary['initial_db_hash']
    assert readonly.summary['final_db_hash']==readonly.summary['initial_db_hash']
    record,snapshot = DevTaskPool().load('retail_152')
    env = make_retail_env(record,snapshot,initialize=False)
    simulation = SimulationRun.model_validate_json((result.output_dir/'simulation_run.json').read_text(encoding='utf8'))
    env.set_state(None,None,simulation.messages)
    assert env.get_db_hash()==result.summary['final_db_hash']
    assert file_hash(ROOT/'data/raw'/snapshot.db_path)==snapshot.file_sha256
    assert make_retail_env(record,snapshot).get_db_hash()==result.summary['initial_db_hash']
    assert result.record.official_reward==0  # unrelated synthetic write is NOT the task's reference goal


def test_one_turn_two_calls_native_multi_return_and_policy_flag(episodes):
    result = episodes['multi_read',True]
    messages = [m for m in result.simulation.messages if isinstance(m,AssistantMessage) and m.tool_calls]
    assert len(messages)==1 and len(messages[0].tool_calls)==2
    observations = [m for m in result.simulation.messages if isinstance(m,ToolMessage)]
    assert [c.id for c in messages[0].tool_calls]==[m.id for m in observations]
    context = result.agent.decisions[1]['context']
    assert [m['tool_call_id'] for m in context['context_messages'] if m['role']=='tool']==[m.id for m in observations]
    assert context['prompt_text'].count('<tool_response>')==2
    assert result.summary['policy_flag_counts']['multiple_tool_calls']==0
    assert result.agent.decisions[0]['protocol_features']['multiple_tool_calls'] is True
    assert result.record.tools.attempted==2


@pytest.mark.parametrize('strict',[True,False])
def test_mixed_strict_rejects_or_native_nonstrict_hides_text(episodes,strict):
    result = episodes['mixed',strict]
    assert result.record.termination_reason==('agent_error' if strict else 'user_stop')
    assert len(result.environment.events)==(0 if strict else 1)
    seen = json.dumps([e['received'] for e in result.user.events])
    assert 'Synthetic mixed content' not in seen
    assert result.summary['policy_flag_counts']['text_and_tool_calls']==1
    if strict:
        assert result.record.tools.framework_errors==1


def test_partial_execution_error_does_not_rollback_or_skip_later_call(episodes):
    result = episodes['partial_write_error',True]
    events = result.environment.events
    assert [e['observation']['error'] for e in events]==[False,True,False]
    assert events[0]['db_after']!=events[0]['db_before']
    assert events[1]['db_before']==events[1]['db_after']==events[0]['db_after']
    assert json.loads(events[2]['observation']['content'])['address']['zip']=='00000'
    assert result.record.tools.attempted==3 and result.record.tools.execution_errors==1
    assert len([m for m in result.agent.decisions[1]['context']['context_messages'] if m['role']=='tool'])==3


def test_error_budget_is_checked_after_entire_batch(run,scripts):
    result = run(*scripts['partial_write_error'],config=OfflineConfig(max_errors=1))
    assert result.record.termination_reason=='too_many_errors'
    assert len(result.environment.events)==3 and len(result.agent.decisions)==1
    assert result.record.official_reward==0 and result.record.scoring_status=='scored'


def test_native_max_steps_finishes_queued_environment_batch(run,scripts):
    result = run(*scripts['readonly'],config=OfflineConfig(max_steps=2))
    assert result.record.termination_reason=='max_steps'
    assert len(result.environment.events)==1
    assert len(result.agent.decisions)==1 and result.record.official_reward==0


@pytest.mark.parametrize('body,attempts',[
    ('<tool_call>{broken}</tool_call>',1),
    (call('synthetic_unknown',{}),1),
    (call('get_product_details',{'product_id':7}),1),
    ('<tool_call>{"name":"get_product_details","arguments":{}}',1),
    ('<tool_call>{"name":"get_product_details","arguments":{},"extra":1}</tool_call>',1),
    ('',0)])
def test_parser_failures_preserve_started_trial_and_attempts(run,body,attempts):
    result = run([body],['Synthetic protocol input.','###STOP###'])
    assert result.record.execution_status=='framework_error' and result.record.error_code=='parser_error'
    assert result.record.official_reward is None and result.record.scoring_status=='not_available'
    assert result.record.tools.attempted==attempts and result.record.tools.parse_errors==attempts
    assert not result.environment.events and result.simulation is None
    assert (result.output_dir/'partial_native_trace.json').exists()
    assert result.agent.decisions[0]['generation']['generated_token_ids']


def test_entire_batch_schema_validation_precedes_any_write(run,scripts):
    write = scripts['write'][0][2]
    body = write+'\n'+call('get_order_details',{'order_id':123})
    result = run([body],['Synthetic atomic parser validation diagnostic.'])
    assert result.record.tools.attempted==2 and result.record.tools.parse_errors==2
    assert result.summary['initial_db_hash']==result.summary['final_db_hash']
    assert not result.environment.events


def test_ambiguous_nested_attempts_keep_rate_unknown(run):
    result = run(['<tool_call><tool_call>{}</tool_call></tool_call>'],['Synthetic nested-tag diagnostic.'])
    assert result.record.tools.missing_reason
    assert aggregate(result.plan,[result.record])['tools']['error_rate'] is None


def test_context_overflow_reserves_generation_and_never_truncates(run,scripts):
    result = run(*scripts['readonly'],config=OfflineConfig(max_context_tokens=100))
    decision = result.agent.decisions[0]
    context = decision['context']
    assert result.record.error_code=='context_overflow' and not result.agent.client.requests
    assert context['window_budget']['required_tokens']==context['prompt_tokens']+512
    assert len(context['prompt_token_ids'])==context['prompt_tokens']
    assert len(context['prompt_text'])>100 and result.record.official_reward is None


def test_real_tool_observation_causes_overflow_and_is_saved_in_full(run,scripts,episodes):
    baseline = episodes['readonly',True].agent.decisions
    limit = baseline[0]['context']['prompt_tokens']+512+1
    result = run(*scripts['readonly'],config=OfflineConfig(max_context_tokens=limit))
    assert result.record.error_code=='context_overflow' and len(result.agent.client.requests)==1
    assert len(result.environment.events)==1
    raw = result.environment.events[0]['observation']['content']
    last_context = result.agent.decisions[-1]['context']
    assert next(m['content'] for m in last_context['context_messages'] if m['role']=='tool')==raw
    assert last_context['prompt_tokens']+512>limit
    partial = read_json(result.output_dir/'partial_native_trace.json')
    assert next(m['content'] for m in partial['messages'] if m['role']=='tool')==raw


def test_plain_agent_does_not_stop_from_stop_text_but_user_does(run):
    result = run(['###STOP###'],['Synthetic stop-contract diagnostic.','###STOP###'])
    assert not StudentAgentAdapter.is_stop(AssistantMessage(role='assistant',content='###STOP###'))
    assert result.record.termination_reason=='user_stop' and len(result.user.events)==2
    assert result.record.tools.attempted==0
    assert aggregate(result.plan,[result.record])['tools']['error_rate'] is None


def test_explicit_synthetic_agent_stop_uses_native_contract(run):
    class DiagnosticStopAgent(StudentAgentAdapter):
        @classmethod
        def is_stop(cls,message):
            return message.content=='SYNTHETIC_DIAGNOSTIC_STOP'
    result = run(['SYNTHETIC_DIAGNOSTIC_STOP'],['Synthetic agent-stop contract test.'],agent_type=DiagnosticStopAgent)
    assert result.record.termination_reason=='agent_stop' and len(result.user.events)==1


def test_scoring_exception_is_null_and_full_run_is_preserved(run,scripts):
    def fail(*args,**kwargs):
        raise RuntimeError('Synthetic scorer transport failure')
    result = run(*scripts['readonly'],scorer=fail)
    assert result.record.execution_status=='completed' and result.record.scoring_status=='error'
    assert result.record.official_reward is None and result.record.error_code=='scoring_error'
    assert result.simulation is not None and (result.output_dir/'simulation_run.json').exists()


def test_framework_failure_after_write_keeps_partial_trace(run,scripts,tokenizer):
    class BrokenMock(DeterministicMock):
        def generate(self,request):
            if self.cursor==1:
                self.requests.append(request)
                raise RuntimeError('Synthetic model client failure')
            return super().generate(request)
    write = scripts['write'][0][2]
    client = BrokenMock(tokenizer,[write,'Unused response'])
    result = run([write,'Unused response'],['Synthetic partial write diagnostic.'],client=client)
    assert result.record.execution_status=='framework_error' and result.record.official_reward is None
    assert result.summary['initial_db_hash']!=result.summary['final_db_hash']
    partial = read_json(result.output_dir/'partial_native_trace.json')
    assert len([m for m in partial['messages'] if m['role']=='tool'])==1
    assert result.record.resources.student.completion_tokens is None
    assert len(result.agent.decisions)==2 and len(client.requests)==2


def test_supplied_completion_ids_are_checked_without_reencoding(run,scripts,tokenizer):
    class WrongIDsMock(DeterministicMock):
        def generate(self,request):
            response = super().generate(request)
            return replace(response,generated_token_ids=(7,))
    result = run(*scripts['readonly'],client=WrongIDsMock(tokenizer,scripts['readonly'][0]))
    assert result.record.error_code=='completion_token_text_mismatch'
    assert result.agent.decisions[0]['generation']['generated_token_ids']==[7]
    assert not result.environment.events


def test_generation_budget_overflow_is_explicit_and_not_truncated(run):
    result = run(['Synthetic long completion '*1000],['Synthetic generation budget test.'])
    assert result.record.error_code=='generation_overflow'
    assert len(result.agent.decisions[0]['generation']['generated_token_ids'])>512


def test_native_arun_with_mock_adapters_is_exercised(run,scripts):
    result = run(*scripts['readonly'],config=OfflineConfig(asynchronous=True))
    assert result.record.termination_reason=='user_stop' and result.record.official_reward==1
    assert len(result.environment.events)==1


def test_configuration_variants_cannot_be_mixed_by_stage1(episodes):
    strict,loose = episodes['mixed',True],episodes['mixed',False]
    assert strict.record.context.harness_version!=loose.record.context.harness_version
    with pytest.raises(ValueError,match='configuration mismatch'):
        aggregate(strict.plan,[loose.record.model_copy(update={'trial_id':strict.record.trial_id})])


def test_seeded_run_reproduces_context_tokens_calls_observations_db_and_score(run,scripts):
    first,second = run(*scripts['readonly']),run(*scripts['readonly'])
    assert first.record.episode_id==second.record.episode_id
    def stable(result):
        return {'decisions':[{'context':d['context'],
            'ids':d['generation']['generated_token_ids'], 'flags':d['policy_flags'],
            'message':{'content':d['native_message']['content'],'calls':d['native_message']['tool_calls']}}
            for d in result.agent.decisions],
            'tools':[{'call':e['call'],'observation':{k:e['observation'][k] for k in ('id','content','requestor','error')}}
                for e in result.environment.events],
            'db':result.summary['final_db_hash'],'reward':result.record.official_reward}
    assert stable(first)==stable(second)


def test_sensitive_fields_do_not_enter_student_requests_and_canary_fails_closed(episodes,run):
    result = episodes['readonly',True]
    for request in result.agent.client.requests:
        assert 'user_scenario' not in request.context_json and 'evaluation_criteria' not in request.context_json
        assert 'reference_actions' not in request.context_json
    canary = 'PRIVATE_CANARY_DO_NOT_LEAK_3_0'
    leaked = run(['Unused'],[canary],forbidden_markers=(canary,))
    assert leaked.record.error_code=='privacy_violation' and not leaked.agent.client.requests
    assert 'context' not in leaked.agent.decisions[0]


def test_hidden_raw_data_canary_is_whitelisted_away(episodes):
    result = episodes['readonly',True]
    message = UserMessage(role='user',content='Synthetic public input.',raw_data={
        'user_scenario':'PRIVATE_SCENARIO_CANARY','evaluation_criteria':'PRIVATE_EVALUATOR_CANARY'})
    builder = result.agent.builder
    context = builder.build([message])
    assert 'PRIVATE_' not in json.dumps(context)
    user = ScriptedUser('PRIVATE_SCENARIO_CANARY',['Synthetic reply.'],result.agent.tokenizer)
    state = user.get_init_state()
    assert 'PRIVATE_SCENARIO_CANARY' in state.system_messages[0].content
    assert 'PRIVATE_EVALUATOR_CANARY' not in state.system_messages[0].content


@pytest.mark.parametrize('tamper',['swap','missing','wrong_id','wrong_requestor'])
def test_context_rejects_unlinked_or_reordered_multi_results(episodes,tamper):
    result = episodes['multi_read',True]
    history = deepcopy(result.agent.get_init_state(result.simulation.messages[:-2]).messages)
    indexes = [i for i,m in enumerate(history) if isinstance(m,ToolMessage)]
    assert len(indexes)==2
    if tamper=='swap':
        history[indexes[0]],history[indexes[1]]=history[indexes[1]],history[indexes[0]]
    elif tamper=='missing':
        history.pop(indexes[-1])
    elif tamper=='wrong_id':
        history[indexes[0]].id='synthetic_wrong_id'
    else:
        history[indexes[0]].requestor='user'
    with pytest.raises((HarnessError,ValueError)):
        result.agent.builder.build(history)


def test_context_only_restoration_keeps_every_history_message(episodes):
    result = episodes['multi_read',True]
    history = result.simulation.messages[:-2]
    state = result.agent.get_init_state(history)
    restored = result.agent.builder.build(state.messages)
    assert restored['prompt_token_ids']==result.agent.decisions[1]['context']['prompt_token_ids']


@pytest.mark.parametrize('manifest',['rl_test_frozen.json','rl_train_full.json','pass4_subset.json'])
def test_nondev_manifest_is_rejected_before_task_loading(manifest):
    with pytest.raises(ValueError,match='Dev manifest'):
        DevTaskPool(ROOT/'data/splits/stage2'/manifest)


@pytest.mark.parametrize('changes',[{'split':'test'},{'mode':'online'},{'max_errors':0}])
def test_offline_driver_configuration_enforces_boundary(changes):
    with pytest.raises(ValueError):
        OfflineConfig(**changes)


def test_pool_parses_only_selected_exposed_dev_body():
    pool = DevTaskPool()
    pool.load('retail_152')
    assert pool.records.loaded_ids==['retail_152']
    with pytest.raises(ValueError,match='exposed Dev'):
        pool.load('synthetic_disallowed')


def test_real_clients_and_public_trajectory_paths_are_rejected(run,scripts):
    class RealClient:
        model_id = 'real:forbidden'
    with pytest.raises(ValueError,match='Real Student disabled'):
        run(*scripts['readonly'],client=RealClient())
    from policytrace.harness.runner import run_episode
    with pytest.raises(ValueError,match='private'):
        run_episode('retail_152',[],[],ROOT/'reports/stage3_0/forbidden_trajectory')


def test_network_is_fail_closed():
    with socket.socket() as channel:
        with pytest.raises(RuntimeError,match='network disabled'):
            channel.connect(('127.0.0.1',1))


def test_trial_evidence_is_never_overwritten(episodes,scripts):
    from policytrace.harness.runner import run_episode
    with pytest.raises(FileExistsError):
        run_episode('retail_152',*scripts['readonly'],episodes['readonly',True].output_dir)


def test_real_frozen_main_prompt_tokens_and_target_parser_match(tokenizer,episodes):
    import gzip
    config = read_json(ROOT/'configs/data/sft_main_view.json')
    manifest = read_json(ROOT/config['manifest'])
    source = ROOT/manifest['splits']['train']['artifacts']['main']['rows']['path']
    row = next(r for r in read_jsonl(source) if r['answer'].get('tool_calls'))
    history = []
    for message in row['messages'][1:]:
        if message['role']=='assistant':
            from tau2.data_model.message import ToolCall
            calls = [ToolCall(id=c['id'],name=c['function']['name'],arguments=c['function']['arguments'])
                     for c in message.get('tool_calls',[])]
            history.append(AssistantMessage(role='assistant',content=message['content'],tool_calls=calls or None))
        elif message['role']=='tool':
            history.append(ToolMessage(role='tool',id=message['tool_call_id'],content=message['content']))
        else:
            history.append(UserMessage(role='user',content=message['content']))
    baseline = episodes['readonly',True].agent
    system = row['messages'][0]['content']
    policy = system.rsplit('<policy>',1)[1].split('</policy>',1)[0]
    assert policy==baseline.domain_policy
    builder = ContextBuilder(tokenizer,baseline.domain_policy,baseline.builder.tools,baseline.builder.system_prompt)
    context = builder.build(history)
    with gzip.open(ROOT/config['train_tokens'],'rt',encoding='utf8') as stream:
        tokens = next(json.loads(line) for line in stream if json.loads(line)['provenance']['sample_id']==row['provenance']['sample_id'])
    assert context['prompt_token_ids']==tokens['input_ids'][:tokens['prompt_tokens']]
    target_ids = [label for label in tokens['labels'] if label!=-100]
    target = tokenizer.tokenizer.decode(target_ids,skip_special_tokens=False)
    parsed = parse_completion(target,baseline.validators,'synthetic_frozen_main_roundtrip')
    assert len(parsed.tool_calls)==len(row['answer']['tool_calls'])
    assert [{'name':c.name,'arguments':c.arguments} for c in parsed.tool_calls]==[c['function'] for c in row['answer']['tool_calls']]
    # Runtime and SFT use the same exact business policy and shared Qwen wrapper.


def test_tool_framework_exception_preserves_attempt_and_partial_native_state(run,scripts,monkeypatch):
    from tau2.environment.environment import Environment
    def failure(self,message):
        raise RuntimeError('Synthetic wrapper-level tool failure')
    monkeypatch.setattr(Environment,'get_response',failure)
    result = run(*scripts['readonly'])
    assert result.record.execution_status=='framework_error' and result.record.official_reward is None
    assert result.record.tools.attempted==1 and result.record.tools.framework_errors==1
    assert result.environment.events[0]['error_type']=='RuntimeError'
    assert result.agent.decisions[0]['tool_attempts'][0]['status']=='framework_error'
