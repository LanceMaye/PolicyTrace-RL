"""Private Stage 0 oracle fixtures, NOT a student rollout implementation."""
import random
from datetime import datetime, timezone

from tau2.data_model.message import AssistantMessage, UserMessage, ToolCall
from tau2.data_model.simulation import SimulationRun, TerminationReason

from .task_loader import RetailTask
from .db_adapter import RetailSnapshot, make_retail_env

MUTATIONS = {'modify_pending_order_address', 'modify_user_address', 'return_delivered_order_items',
             'cancel_pending_order', 'modify_pending_order_items', 'exchange_delivered_order_items', 'modify_pending_order_payment'}


def select_tasks(records: list[RetailTask], seed: int = 42, limit: int = 8) -> list[RetailTask]:
    """Sort IDs before seeded shuffling; cover snapshots and read-only/mutating tasks."""
    if limit < 1:
        raise ValueError('limit must be positive')
    ordered = sorted(records, key=lambda r:r.task.id)
    rng = random.Random(seed)
    rng.shuffle(ordered)
    chosen = []
    for path in sorted({r.db_path for r in ordered}):
        for mutation in (True, False):
            candidates = [r for r in ordered if r.db_path == path and
                          bool({a.name for a in r.task.evaluation_criteria.actions or []} & MUTATIONS) == mutation]
            if candidates:
                chosen.append(candidates[0])
    chosen_ids = {r.task.id for r in chosen}
    chosen.extend(r for r in ordered if r.task.id not in chosen_ids)
    return chosen[:limit]


def reference_fixture(record: RetailTask, snapshot: RetailSnapshot, *, seed: int = 42) -> tuple[SimulationRun, dict]:
    """Execute reference actions through upstream get_response; record every failure.

    This is evaluator test data with privileged access, never a real user episode.
    Communication targets are intentionally NOT injected into the assistant response.
    """
    started = datetime.now(timezone.utc)
    env = make_retail_env(record, snapshot)
    initial_hash = env.get_db_hash()
    state = record.task.initial_state
    messages = list(state.message_history or []) if state else []
    calls = []
    for i, action in enumerate(record.task.evaluation_criteria.actions or []):
        call = ToolCall(id=f'stage0_{i}', name=action.name, arguments=action.arguments, requestor=action.requestor)
        message_cls = AssistantMessage if action.requestor == 'assistant' else UserMessage
        messages.append(message_cls(role=action.requestor, tool_calls=[call]))
        response = env.get_response(call)
        messages.append(response)
        calls.append({'name': action.name, 'error': response.error, 'response': response.content})
    ended = datetime.now(timezone.utc)
    simulation = SimulationRun(id=f'reference-{record.task.id}', task_id=record.task.id,
        start_time=started.isoformat(), end_time=ended.isoformat(), duration=(ended-started).total_seconds(),
        termination_reason=TerminationReason.AGENT_STOP, messages=messages, seed=seed)
    return simulation, {'initial_hash':initial_hash, 'final_hash':env.get_db_hash(), 'calls':calls,
                         'termination_provenance':'synthetic fixture boundary, not an Agent stop decision'}
