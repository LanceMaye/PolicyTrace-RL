"""Dev-only offline driver: native Orchestrator, Stage 0 DBs, Stage 1 records/R0."""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from copy import deepcopy
from collections import Counter
import json
import re
import time
import asyncio

from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolMessage, UserMessage
from tau2.data_model.simulation import SimulationRun
from tau2.orchestrator.orchestrator import Orchestrator
from tau2.user.user_simulator import UserSimulator
from tau2.utils.utils import get_now

from policytrace.data.manifests import ROOT, canonical, digest, file_hash, read_json, write_json, write_jsonl
from policytrace.data.sft_tokenize import QwenTokenizer
from policytrace.data.task_pool import RLTaskPool
from policytrace.stage0.task_loader import load_retail_task
from policytrace.stage0.db_adapter import make_retail_env
from policytrace.evaluation.schema import (RunContext, EvaluationPlan, EpisodeRecord, SamplingSettings,
    ResourceUsage, TokenUsage, ToolStatistics, ArtifactReference, ENVIRONMENT_SHA, DATASET_REVISION, task_set_hash)
from policytrace.rewards.official import evaluate_r0
from . import VERSION
from .agent_adapter import StudentAgentAdapter
from .context import HarnessError
from .model_client import DeterministicMock
from .verification import offline_guard, fork_state

EXPOSED_DEV = frozenset({'retail_131', 'retail_152'})


class SelectedRecords:
    """Read only a selected Dev task body; other raw lines are inspected for root ID only."""
    def __init__(self, root):
        self.root = root
        self.loaded_ids = []
    def __getitem__(self, task_id):
        if task_id not in EXPOSED_DEV:
            raise ValueError('Only already exposed Dev fixtures are allowed')
        with (self.root/'data/raw/tau2_rl_train.jsonl').open('rb') as stream:
            for index, line in enumerate(stream, 1):
                match = re.match(rb'\s*\{\s*"id"\s*:\s*"([^"]+)"', line)
                if match is None:
                    raise ValueError('Unexpected raw ID envelope; do not parse nonselected Task bodies')
                if match[1].decode('utf-8') == task_id:
                    self.loaded_ids.append(task_id)
                    return load_retail_task(json.loads(line), index)
        raise ValueError('Selected Dev Task missing')


class DevTaskPool(RLTaskPool):
    def __init__(self, manifest_path=None):
        expected = ROOT/'data/splits/stage2/rl_dev.json'
        supplied = Path(manifest_path or expected).resolve()
        if supplied != expected.resolve():
            raise ValueError('Stage 3_0 accepts only the frozen Dev manifest; Test/external/Train rejected')
        baseline = read_json(ROOT/'data/private/stage3_0/immutable_inputs.json')['files']
        if file_hash(supplied) != baseline['data/splits/stage2/rl_dev.json']:
            raise ValueError('Frozen Dev manifest changed')
        super().__init__(supplied)
        if self.manifest['name'] != 'rl_dev' or not EXPOSED_DEV <= set(self.entries):
            raise ValueError('Exposed fixtures must be in frozen Dev')
        self._selected_records = SelectedRecords(ROOT)

    @property
    def records(self):
        return self._selected_records

    def load(self, task_id):
        if task_id not in EXPOSED_DEV:
            raise ValueError('Only already exposed Dev fixtures are allowed')
        return super().load(task_id)


@dataclass(frozen=True)
class OfflineConfig:
    mode: str = 'offline'
    split: str = 'dev'
    seed: int = 42
    max_steps: int = 40
    max_errors: int = 3
    max_context_tokens: int = 16384
    reserved_generation_tokens: int = 512
    validate_communication: bool = True
    asynchronous: bool = False

    def __post_init__(self):
        if self.mode != 'offline' or self.split != 'dev':
            raise ValueError('Stage 3_0 is offline and Dev-only')
        if any(type(x) is not int or x <= 0 for x in (self.max_steps, self.max_errors,
                self.max_context_tokens, self.reserved_generation_tokens)):
            raise ValueError('Budgets must be positive integers')


class ScriptedUser(UserSimulator):
    """Reuse native scenario prompt/history/stop contract, replace generation only."""
    def __init__(self, instructions, responses, tokenizer):
        super().__init__(instructions=instructions, llm=None)
        self.responses, self.tokenizer = tuple(responses), tokenizer
        self.cursor = 0
        self.events = []
    def set_seed(self, seed):
        self.seed = seed
    def _generate_next_message(self, message, state):
        start = time.perf_counter()
        state.messages.extend(deepcopy(message.tool_messages if isinstance(message,MultiToolMessage) else [message]))
        if self.cursor >= len(self.responses):
            raise HarnessError('scripted_user_exhausted')
        content = self.responses[self.cursor]
        self.cursor += 1
        response = UserMessage(role='user', content=content)
        self.events.append({'source': 'mock', 'purpose': 'diagnostic', 'index': self.cursor-1,
            'received': message.model_dump(mode='json'), 'sent': response.model_dump(mode='json'),
            'output_content_tokens': len(self.tokenizer.encode(content).ids),
            'token_provenance': 'mock_encoded_content_only', 'provider_usage': None,
            'duration_seconds': time.perf_counter()-start})
        state.messages.append(response)
        return response, state
    async def _agenerate_next_message(self, message, state):
        return self._generate_next_message(message, state)


class ObservedEnvironment:
    """Instance composition: before/after each native get_response, never a second loop."""
    def __init__(self, environment, agent, tokenizer):
        self.environment, self.agent, self.tokenizer = environment, agent, tokenizer
        self.events = []
    def __getattr__(self, name):
        return getattr(self.environment, name)
    def get_response(self, call):
        attempt = next((a for d in self.agent.decisions for a in d['tool_attempts'] if a.get('call_id')==call.id), None)
        if attempt is None:
            raise HarnessError('unregistered_tool_call')
        event = {'call': call.model_dump(mode='json'), 'started_at_unix': time.time(),
                 'db_before': self.environment.get_db_hash()}
        self.events.append(event)
        start = time.perf_counter()
        try:
            observation = self.environment.get_response(call)
            event.update(observation=observation.model_dump(mode='json'),
                raw_sha256=digest(observation.content), model_sha256=digest(observation.content),
                projection='identity-v0', content_tokens=len(self.tokenizer.encode(observation.content or '').ids),
                db_after=self.environment.get_db_hash())
            attempt.update(status='execution_error' if observation.error else 'executed', observation_id=observation.id)
            return observation
        except Exception as exc:
            attempt.update(status='framework_error', error_type=type(exc).__name__)
            event.update(error_type=type(exc).__name__)
            raise
        finally:
            event['duration_seconds'] = time.perf_counter()-start
            event['ended_at_unix'] = time.time()


@dataclass
class EpisodeArtifacts:
    record: EpisodeRecord
    plan: EvaluationPlan
    simulation: SimulationRun | None
    agent: StudentAgentAdapter
    user: ScriptedUser
    environment: ObservedEnvironment
    summary: dict
    output_dir: Path


def run_episode(task_id, student_responses, user_responses, output_dir, *, config=None,
                run_id='stage3_0_diagnostic', trial_id='diagnostic_0', tokenizer=None,
                client=None, agent_type=StudentAgentAdapter, forbidden_markers=(), scorer=evaluate_r0):
    config = config or OfflineConfig()
    output_dir = Path(output_dir).resolve()
    if not output_dir.is_relative_to((ROOT/'data/private/stage3_0').resolve()):
        raise ValueError('Trajectories must be stored in data/private/stage3_0')
    if output_dir.exists():
        raise FileExistsError('Do not overwrite existing Trial evidence')
    runtime = fork_state()
    pool = DevTaskPool()
    record, snapshot = pool.load(task_id)
    tokenizer = tokenizer or QwenTokenizer()
    client = client or DeterministicMock(tokenizer, student_responses)
    if not isinstance(client, DeterministicMock):
        raise ValueError('Real Student disabled in Stage 3_0')
    config_hash = digest({'run':config.__dict__, 'policy_version':runtime['policy_version'],
                          'policy_sha256':runtime['policy_sha256']})
    episode_id = 'ep_' + digest([run_id, task_id, trial_id, config_hash, client.config_hash, list(user_responses)])[:24]
    context = RunContext(purpose='diagnostic', run_id=run_id, task_set_id='exposed-dev-offline',
        task_set_sha256=task_set_hash([task_id]), environment_sha=ENVIRONMENT_SHA, dataset_revision=DATASET_REVISION,
        model_id=client.model_id, model_version=client.config_hash,
        model_sampling=SamplingSettings(temperature=0,max_output_tokens=config.reserved_generation_tokens),
        simulator_model='mock:scripted-user-v1', simulator_version='scripted-user-v1',
        simulator_config_id=digest(list(user_responses)), simulator_sampling=SamplingSettings(temperature=0),
        harness_version=VERSION+'_'+config_hash[:16], max_steps=config.max_steps,max_errors=config.max_errors,
        max_context_tokens=config.max_context_tokens,
        unrecorded_fields=('real_checkpoint','provider_usage','gpu_telemetry'))
    plan = EvaluationPlan(context=context, task_ids=(task_id,),trial_ids=(trial_id,),trials_per_task=1,provenance='mock')
    metadata = {'run_id': run_id,'task_id': task_id,'trial_id': trial_id,'harness_version': VERSION,
        'environment_sha': ENVIRONMENT_SHA,'dataset_revision': DATASET_REVISION,'model_config_sha256': client.config_hash,
        'run_config_sha256': config_hash,'snapshot_id': snapshot.db_path,'snapshot_sha256': snapshot.file_sha256}
    metadata['policy_file_sha256'] = file_hash(ROOT/'external/tau2-bench/data/tau2/domains/retail/policy.md')
    metadata['policy_version'] = runtime['policy_version']
    env = make_retail_env(record, snapshot, initialize=False)
    initial_hash = env.get_db_hash()
    agent = agent_type(env.get_tools(), env.get_policy(), tokenizer, client, episode_id, metadata,
        max_tokens=config.max_context_tokens, reserved_tokens=config.reserved_generation_tokens,
        forbidden_markers=forbidden_markers)
    user = ScriptedUser(record.task.user_scenario.instructions, user_responses, tokenizer)
    observed = ObservedEnvironment(env, agent, tokenizer)
    orchestrator = Orchestrator(domain='retail',agent=agent,user=user,environment=observed,task=record.task,
        max_steps=config.max_steps,max_errors=config.max_errors,seed=config.seed,
        validate_communication=config.validate_communication)
    output_dir.mkdir(parents=True)
    write_json(output_dir/'plan.json',plan.model_dump(mode='json'))
    start, started_at = time.perf_counter(), get_now()
    simulation, failure, official = None, None, None
    scoring_status, execution_status = 'not_available', 'completed'
    with offline_guard() as network_attempts:
        try:
            simulation = asyncio.run(orchestrator.arun()) if config.asynchronous else orchestrator.run()
        except Exception as exc:
            failure = {'code': getattr(exc,'code','framework_error'), 'type': type(exc).__name__,
                       'native_termination': orchestrator.termination_reason.value if orchestrator.termination_reason else None,
                       'step_count': orchestrator.step_count, 'started_at': started_at,'ended_at': get_now()}
            execution_status = 'framework_error'
        if simulation is not None:
            simulation_path = output_dir/'simulation_run.json'
            simulation_path.write_text(simulation.model_dump_json(indent=2),encoding='utf-8')
            # Exercise the actual native serialization path before official scoring.
            simulation = SimulationRun.model_validate_json(simulation_path.read_text(encoding='utf-8'))
            try:
                official = scorer(record, snapshot, simulation, private_reward_path=output_dir/'reward_info.json')
                scoring_status = 'scored'
            except Exception as exc:
                scoring_status = 'error'
                failure = {'code': 'scoring_error','type': type(exc).__name__}
        else:
            write_json(output_dir/'partial_native_trace.json', {
                'complete': False, 'source': 'mock','purpose': 'diagnostic','episode_id':episode_id,
                'task_id':task_id, 'messages':[m.model_dump(mode='json') for m in orchestrator.trajectory],
                'tool_events': observed.events, 'failure':failure})
    # Native protocol rejection/early termination leaves validated attempts visible.
    trajectory_cursor = 0
    for decision in agent.decisions:
        decision['native_simulation_id'] = simulation.id if simulation is not None else None
        for attempt in decision['tool_attempts']:
            if attempt['status'] in ('validated_not_executed','pending_validation'):
                attempt.update(status='framework_error', reason='not_executed_after_rejection_or_interruption')
        observations = [e for e in observed.events if any(a.get('call_id')==e['call']['id'] for a in decision['tool_attempts'])]
        decision['tool_events'] = observations
        native = decision.get('native_message')
        index = next((i for i,m in enumerate(orchestrator.trajectory) if i>=trajectory_cursor and
            isinstance(m,AssistantMessage) and native and m==AssistantMessage.model_validate(native)),None)
        decision['native_trajectory_index'] = index
        if index is not None:
            trajectory_cursor = index+1
    attempts = [a for d in agent.decisions for a in d['tool_attempts']]
    count = Counter(a['status'] for a in attempts)
    known = all(d.get('attempt_count_known', True) for d in agent.decisions)
    stats = ToolStatistics(attempted=len(attempts), parse_errors=count['parse_error'],
        execution_errors=count['execution_error'], framework_errors=count['framework_error'] if known else None,
        missing_reason=None if known else 'Ambiguous tool delimiter; attempt count is a lower bound, rate unavailable')
    write_jsonl(output_dir/'decision_trace.jsonl',agent.decisions)
    write_jsonl(output_dir/'tool_trace.jsonl',observed.events)
    write_jsonl(output_dir/'user_trace.jsonl',user.events)
    write_json(output_dir/'episode_metadata.json',{
        **metadata,'episode_id':episode_id,'native_simulation_id':simulation.id if simulation is not None else None,
        'source':'mock','purpose':'diagnostic','complete_native_run':simulation is not None,
        'projection':'identity-v0','context_versions':agent.builder.versions,
        'run_config':config.__dict__,'failure':failure,'orchestrator_steps':orchestrator.step_count,
        'orchestrator_errors':orchestrator.num_errors})
    artifact_path = output_dir/('simulation_run.json' if simulation else 'partial_native_trace.json')
    prompt_counts = [d['context']['prompt_tokens'] for d in agent.decisions if d.get('model_invocation_started')]
    output_counts = [len(d['generation']['generated_token_ids']) for d in agent.decisions if 'generation' in d]
    episode = EpisodeRecord(context=context, episode_id=episode_id,task_id=task_id,trial_id=trial_id,provenance='mock',
        db_snapshot_id=snapshot.db_path,db_snapshot_sha256=snapshot.file_sha256,seed=config.seed,
        evaluated_at=datetime.now(timezone.utc),termination_reason=simulation.termination_reason.value if simulation else 'framework_error',
        execution_status=execution_status,scoring_status=scoring_status,official_score=official.score if official else None,
        tools=stats,duration_seconds=time.perf_counter()-start,
        resources=ResourceUsage(student=TokenUsage(prompt_tokens=sum(prompt_counts),
            completion_tokens=sum(output_counts) if len(output_counts)==len(prompt_counts) else None,
            source='instrumented',missing_reason='Mock encoded tokens; not provider billed usage'),
            user=TokenUsage(missing_reason='Scripted content tokens stored separately; no User model prompt or provider usage'),
            teacher=TokenUsage(missing_reason='No Teacher invoked'),missing_reason='Offline mock; no measured API bill, GPU or training'),
        trajectory=ArtifactReference(path=artifact_path.relative_to(ROOT).as_posix(),sha256=file_hash(artifact_path)),
        error_code=failure['code'] if failure else None,
        diagnostic_codes=('mock_not_benchmark','policy_semantics_not_evaluated')+((failure['code'],) if failure else ()))
    write_json(output_dir/'episode_record.json',episode.model_dump(mode='json'))
    # No scenario, arguments, customer bodies or reference actions in this public summary.
    summary = {'source':'mock','purpose':'diagnostic','fixture_kind':'scripted_actions_on_exposed_dev_snapshot',
        'policy_version':runtime['policy_version'],'policy_sha256':runtime['policy_sha256'],
        'episode_id':episode_id,'task_id':task_id,'trial_id':trial_id,'termination':episode.termination_reason,
        'execution_status':execution_status,'scoring_status':scoring_status,'diagnostic_r0':episode.official_reward,
        'error_code':episode.error_code,'decision_count':len(agent.decisions),'user_message_count':len(user.events),
        'native_message_roles':dict(Counter(m.role for m in orchestrator.trajectory)),
        'tool_statistics':stats.model_dump(mode='json'),'policy_flag_counts':{
            k:sum(d.get('policy_flags',{}).get(k) is True for d in agent.decisions)
            for k in ('multiple_tool_calls','text_and_tool_calls')},
        'prompt_tokens':prompt_counts,'completion_tokens':output_counts,
        'context_growth': [b-a for a,b in zip(prompt_counts,prompt_counts[1:])],
        'initial_db_hash':initial_hash,'final_db_hash':env.get_db_hash(),
        'raw_snapshot_sha256':file_hash(ROOT/'data/raw'/snapshot.db_path),
        'raw_snapshot_unchanged':file_hash(ROOT/'data/raw'/snapshot.db_path)==snapshot.file_sha256,
        'validate_communication':config.validate_communication,'config_sha256':config_hash,
        'actual_generated_model_ids':False,'network_operations_blocked':len(network_attempts),
        'provider_usage':None,'api_cost':None,'teacher_tokens':None,'gpu_seconds':None,
        'user_simulator_fidelity':'unknown','formal_pass1':None,'formal_pass4':None,
        'private_evidence':output_dir.relative_to(ROOT).as_posix(), 'trajectory_sha256':file_hash(artifact_path)}
    write_json(output_dir/'summary.json',summary)
    return EpisodeArtifacts(episode,plan,simulation,agent,user,observed,summary,output_dir)
