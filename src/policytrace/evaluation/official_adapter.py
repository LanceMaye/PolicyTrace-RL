"""Wrap the unchanged Stage 0 evaluator; keep raw private evidence out of public data."""
from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from policytrace.stage0.db_adapter import RetailSnapshot
from policytrace.stage0.task_loader import RetailTask
from policytrace.stage0.evaluator_adapter import evaluate_with_correct_initial_state
from tau2.data_model.simulation import RewardInfo, SimulationRun

from .schema import ArtifactReference, OfficialScore


@dataclass(frozen=True)
class OfficialEvaluation:
    score: OfficialScore
    raw_reward_json: str = field(repr=False)

    def reward_info(self) -> RewardInfo:
        """Return an independent copy of the original full official result."""
        return RewardInfo.model_validate_json(self.raw_reward_json)


def evaluate_official(record: RetailTask, snapshot: RetailSnapshot, simulation: SimulationRun,
                      *, private_reward_path: Path | None = None) -> OfficialEvaluation:
    raw = evaluate_with_correct_initial_state(record, snapshot, simulation)
    payload = raw.model_dump_json(indent=2)
    artifact = None
    if private_reward_path is not None:
        private_reward_path.parent.mkdir(parents=True, exist_ok=True)
        private_reward_path.write_text(payload, encoding='utf-8')
        artifact = ArtifactReference(path=private_reward_path.as_posix(),
                                     sha256=hashlib.sha256(payload.encode('utf-8')).hexdigest())
    score = OfficialScore(official_reward=raw.reward, success=raw.reward == 1.0,
                          reward_components=raw.model_dump(mode='json')['reward_breakdown'],
                          reward_basis=tuple(x.value for x in raw.reward_basis) if raw.reward_basis is not None else None,
                          db_match=raw.db_check.db_match if raw.db_check is not None else None,
                          raw_reward=artifact)
    return OfficialEvaluation(score=score, raw_reward_json=payload)
