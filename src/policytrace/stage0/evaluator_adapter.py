"""Inject the snapshot through the public registry; keep official reward semantics."""
from threading import Lock

from tau2.data_model.simulation import RewardInfo, SimulationRun
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.registry import registry

from .db_adapter import RetailSnapshot, snapshot_constructor
from .task_loader import RetailTask

_REGISTRATION_LOCK = Lock()
_REGISTERED: dict[str, object] = {}


def evaluate_with_correct_initial_state(
    record: RetailTask,
    initial_db: RetailSnapshot,
    simulation: SimulationRun,
) -> RewardInfo:
    """Evaluate ALL official components, including normal termination and communication.

    The official evaluator constructs both predicted and gold environments via this
    snapshot-bound domain. No global retail entry is replaced and no scoring code is patched.
    """
    if simulation.task_id != record.task.id:
        raise ValueError("Simulation task ID does not match the evaluation task")
    constructor = snapshot_constructor(record, initial_db)
    name = f"policytrace_stage0_retail_{initial_db.content_hash}"
    with _REGISTRATION_LOCK:
        if name not in _REGISTERED:
            registry.register_domain(constructor, name)
            _REGISTERED[name] = constructor
        elif registry.get_env_constructor(name) is not _REGISTERED[name]:
            raise RuntimeError("Snapshot-bound evaluator registration was replaced")
    return evaluate_simulation(
        simulation=simulation, task=record.task, evaluation_type=EvaluationType.ALL,
        solo_mode=False, domain=name,
    )
