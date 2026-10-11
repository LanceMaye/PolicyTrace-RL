"""No R1 formula: future trusted plugins see numeric signals, not hidden tasks."""
from typing import Protocol

from pydantic import Field

from policytrace.evaluation.schema import EpisodeRecord, FrozenModel, Identifier, Termination, ToolStatistics


class RewardSignals(FrozenModel):
    official_reward: float
    termination_reason: Termination
    tools: ToolStatistics | None
    duration_seconds: float | None


class TrainingReward(FrozenModel):
    name: Identifier
    version: Identifier
    value: float
    components: dict[str, float] = Field(default_factory=dict)


class TrainingRewardPlugin(Protocol):
    def evaluate(self, signals: RewardSignals) -> TrainingReward: ...


class RewardOutput(FrozenModel):
    official_reward: float
    training_reward: TrainingReward


def select_training_reward(episode: EpisodeRecord, plugin: TrainingRewardPlugin | None = None) -> RewardOutput:
    if episode.official_score is None:
        raise ValueError('Cannot invent training R0 for an unscored episode')
    value = episode.official_score.official_reward
    if plugin is None:
        training = TrainingReward(name='R0', version='official-v1', value=value,
                                  components={'official': value})
    else:
        signals = RewardSignals(official_reward=value, termination_reason=episode.termination_reason,
                                tools=episode.tools, duration_seconds=episode.duration_seconds)
        training = TrainingReward.model_validate(plugin.evaluate(signals))
    return RewardOutput(official_reward=value, training_reward=training)
