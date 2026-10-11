"""Offline probes on the unmodified Fork; scripted completions are not model evaluations."""
from copy import deepcopy
import asyncio
import json

import policytrace.stage0
from litellm import ModelResponse
from tau2.agent.llm_agent import LLMAgent
from tau2.data_model.message import ToolMessage, MultiToolMessage
from tau2.data_model.simulation import SimulationRun
from tau2.orchestrator.orchestrator import Orchestrator, Role
from tau2.user.user_simulator import UserSimulator
from tau2.utils import get_pydantic_hash

from policytrace.data.manifests import ROOT
from policytrace.stage0.db_adapter import load_retail_db, make_retail_env
from policytrace.stage0.task_loader import iter_retail_records, load_retail_task
from policytrace.stage0.evaluator_adapter import evaluate_with_correct_initial_state


def baseline():
    # Previously exposed read-only task; never touch a frozen Test task.
    index, raw = next((i, r) for i, r in iter_retail_records(ROOT/'data/raw') if r['id'] == 'retail_152')
    record = load_retail_task(raw, index)
    return record, load_retail_db(record.db_path, ROOT/'data/raw')


def native_probe(message, *, strict=True, max_errors=10, async_batch=False, evaluate=False):
    record, snapshot = baseline()
    env = make_retail_env(record, snapshot, initialize=False)
    other = make_retail_env(record, snapshot)
    captured = {'agent': [], 'user': []}

    def completion(role, **kwargs):
        captured[role].append(deepcopy(kwargs))
        if role == 'user':
            output = {'role':'assistant', 'content': 'Please execute the isolated protocol fixture; I confirm its listed changes.'
                      if len(captured[role])==1 else '###STOP###'}
        elif len(captured[role]) == 1:
            output = {'role':'assistant', 'content': message.content, 'tool_calls': [
                {'id': c.id, 'type': 'function', 'function': {'name':c.name, 'arguments':json.dumps(c.arguments)}}
                for c in message.tool_calls]}
        else:
            # Ordinary LLMAgent inherits BaseAgent.is_stop=False. End through
            # UserSimulator's actual stop protocol, not the solo-agent token.
            output = {'role':'assistant', 'content':'The isolated protocol fixture has completed.'}
        return ModelResponse(model='gpt-4.1-mini-2025-04-14', choices=[{
            'index':0, 'finish_reason':'tool_calls' if output.get('tool_calls') else 'stop', 'message':output}],
            usage={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0})

    agent = LLMAgent(tools=env.get_tools(),domain_policy=env.get_policy(),llm='gpt-4.1-mini-2025-04-14',
        llm_args={'num_retries':0},completion_fn=lambda **kw:completion('agent',**kw))
    user = UserSimulator(instructions='Scripted protocol fixture, no model.',llm='gpt-4.1-mini-2025-04-14',
        llm_args={'num_retries':0},completion_fn=lambda **kw:completion('user',**kw))
    orch = Orchestrator(domain='retail',agent=agent,user=user,environment=env,task=record.task,
        max_steps=8,max_errors=max_errors,validate_communication=strict)
    if async_batch:
        orch.initialize()
        orch.step()  # Greeting -> scripted user.
        orch.step()  # User -> ONE assistant batch.
        assert orch.to_role == Role.ENV and not orch.done
        asyncio.run(orch.astep())  # Real Fork async batch branch (sequential tool execution).
        assert isinstance(orch.message, MultiToolMessage)
        orch.step()  # MultiToolMessage -> real LLMAgent flattening.
        orch.step()  # Scripted user stop through native UserSimulator.
        assert orch.done
        trajectory = orch.get_trajectory()
        simulation = None
    else:
        simulation = orch.run()
        # Verify native JSON save/load, without flattening or splitting expert actions.
        simulation = SimulationRun.model_validate_json(simulation.model_dump_json())
        trajectory = simulation.messages
    observations = [m for m in trajectory if isinstance(m, ToolMessage)]
    tool_context = [m for m in captured['agent'][-1]['messages'] if m['role']=='tool']
    replay_equal = None
    if len(observations) == len(message.tool_calls):
        replay = make_retail_env(record,snapshot)
        replay.set_state(initialization_data=None, initialization_actions=None, message_history=trajectory)
        assert get_pydantic_hash(replay.tools.db)==get_pydantic_hash(env.tools.db)
        replay_equal = True
    else:
        assert not observations and get_pydantic_hash(env.tools.db)==snapshot.content_hash
    assert get_pydantic_hash(other.tools.db)==snapshot.content_hash==get_pydantic_hash(snapshot.db)
    reward = evaluate_with_correct_initial_state(record,snapshot,simulation) if evaluate else None
    return {'simulation':simulation,'trajectory':trajectory,'observations':observations,
            'captured':captured,'tool_context':tool_context,'environment':env,
            'summary':{'strict':strict,'async_batch':async_batch,'calls':len(message.tool_calls),
                       'observations':len(observations),'errors':sum(m.error for m in observations),
                       'termination':orch.termination_reason.value if orch.termination_reason else None,
                       'next_generation_observations':len(tool_context),'num_errors':orch.num_errors,
                       'replay_db_equal':replay_equal,'isolation_passed':True,
                       'official_evaluator_invoked':reward is not None,
                       'reward_info':reward.model_dump(mode='json') if reward else None}}
