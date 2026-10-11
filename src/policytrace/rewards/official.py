"""R0 is the original official reward, without weights or business normalization."""
from pathlib import Path

from policytrace.evaluation.official_adapter import OfficialEvaluation, evaluate_official
from policytrace.stage0.db_adapter import RetailSnapshot
from policytrace.stage0.task_loader import RetailTask
from tau2.data_model.simulation import SimulationRun


def evaluate_r0(record: RetailTask, snapshot: RetailSnapshot, simulation: SimulationRun,
                *, private_reward_path: Path | None = None) -> OfficialEvaluation:
    return evaluate_official(record, snapshot, simulation, private_reward_path=private_reward_path)
