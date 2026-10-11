"""Official bidirectional Orchestrator check with explicit local completion stubs."""
from copy import deepcopy
from typing import Any

from litellm import ModelResponse
from tau2.agent.llm_agent import LLMAgent
from tau2.user.user_simulator import UserSimulator
from tau2.orchestrator.orchestrator import Orchestrator

from .db_adapter import RetailSnapshot, make_retail_env
from .task_loader import RetailTask

PRIVATE_USER = 'STAGE0_USER_PRIVATE_SENTINEL'
PRIVATE_EVAL = 'STAGE0_EVAL_PRIVATE_SENTINEL'


def run_mock_episode(record: RetailTask, snapshot: RetailSnapshot, seed: int = 42) -> tuple[Any, dict]:
    """No network. Exercise the real model-message conversion and official state machine."""
    local_record = deepcopy(record)
    local_record.task.user_scenario.instructions = PRIVATE_USER
    local_record.task.evaluation_criteria.communicate_info = [PRIVATE_EVAL]
    env = make_retail_env(local_record, snapshot, initialize=False)
    captured: dict[str, list[dict]] = {'agent': [], 'user': []}

    def completion(role: str, **kwargs: Any) -> ModelResponse:
        captured[role].append(deepcopy(kwargs))
        turn = len(captured[role])
        if role == 'user':
            message = {'role':'assistant', 'content':'What product types do you sell?' if turn == 1 else '###STOP###'}
        elif turn == 1:
            message = {'role':'assistant', 'content':None, 'tool_calls':[{
                'id':'mock-list', 'type':'function', 'function':{'name':'list_all_product_types','arguments':'{}'}}]}
        else:
            message = {'role':'assistant', 'content':'The catalog contains several product types.'}
        return ModelResponse(model='gpt-4.1-mini-2025-04-14', choices=[{
            'index':0, 'finish_reason':'tool_calls' if message.get('tool_calls') else 'stop', 'message':message}],
            usage={'prompt_tokens':0, 'completion_tokens':0, 'total_tokens':0})

    agent = LLMAgent(tools=env.get_tools(), domain_policy=env.get_policy(), llm='gpt-4.1-mini-2025-04-14',
                     llm_args={'temperature':0, 'num_retries':0}, completion_fn=lambda **kw:completion('agent', **kw))
    user = UserSimulator(instructions=local_record.task.user_scenario.instructions, llm='gpt-4.1-mini-2025-04-14',
                         llm_args={'temperature':0, 'num_retries':0}, completion_fn=lambda **kw:completion('user', **kw))
    orchestrator = Orchestrator(domain='retail', agent=agent, user=user, environment=env,
        task=local_record.task, max_steps=12, max_errors=1, seed=seed, solo_mode=False, validate_communication=True)
    simulation = orchestrator.run()
    return simulation, captured
