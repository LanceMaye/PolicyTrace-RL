"""Public numeric records; private prompts, tasks and trajectories stay outside."""
import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

PROTOCOL_VERSION = 'policytrace-eval-v1'
ENVIRONMENT_SHA = 'e33e9511e4f51e5cfa16e12b02d0e4ab327b5887'
DATASET_REVISION = '86971dc03da6e7c1a7933295e05b84aab8215386'
Count = Annotated[StrictInt, Field(ge=0)]
PositiveCount = Annotated[StrictInt, Field(gt=0)]
Identifier = Annotated[str, Field(min_length=1)]
Hash256 = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Commit = Annotated[str, Field(pattern=r'^[0-9a-f]{40}$')]
Provenance = Literal['saved_real_episode', 'synthetic', 'reference_fixture', 'mock']
Termination = Literal['user_stop', 'agent_stop', 'max_steps', 'too_many_errors',
                      'agent_error', 'user_error', 'framework_error', 'network_error', 'not_run']


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', allow_inf_nan=False)


def task_set_hash(task_ids: tuple[str, ...] | list[str]) -> str:
    payload = json.dumps(sorted(task_ids), ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


class SamplingSettings(FrozenModel):
    temperature: float = Field(ge=0)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_output_tokens: PositiveCount | None = None
    thinking: Literal['disabled', 'enabled', 'unspecified'] = 'unspecified'
    provider_seed_supported: bool | None = None


class RunContext(FrozenModel):
    protocol_version: Literal['policytrace-eval-v1'] = PROTOCOL_VERSION
    purpose: Literal['diagnostic', 'benchmark'] = 'diagnostic'
    run_id: Identifier
    task_set_id: Identifier
    task_set_sha256: Hash256
    domain: Literal['retail'] = 'retail'
    environment_sha: Commit
    dataset_revision: Commit
    model_id: Identifier
    model_checkpoint: str | None = None
    model_version: str | None = None
    model_sampling: SamplingSettings
    simulator_model: Identifier
    simulator_version: str | None = None
    simulator_config_id: Identifier
    simulator_sampling: SamplingSettings
    harness_version: Identifier
    max_steps: PositiveCount
    max_errors: PositiveCount
    max_context_tokens: PositiveCount | None = None
    unrecorded_fields: tuple[str, ...] = ()


class EvaluationPlan(FrozenModel):
    context: RunContext
    task_ids: tuple[Identifier, ...]
    trial_ids: tuple[Identifier, ...]
    trials_per_task: Literal[1, 4]
    provenance: Provenance

    @model_validator(mode='after')
    def consistent_plan(self):
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError('Duplicate task ID in evaluation plan')
        if len(set(self.trial_ids)) != len(self.trial_ids):
            raise ValueError('Duplicate trial ID in evaluation plan')
        if len(self.trial_ids) != self.trials_per_task:
            raise ValueError('Plan must explicitly list exactly one or four trial IDs')
        if task_set_hash(self.task_ids) != self.context.task_set_sha256:
            raise ValueError('Task set hash does not match the declared task IDs')
        if self.context.purpose == 'benchmark' and self.provenance != 'saved_real_episode':
            raise ValueError('Synthetic, mock and reference fixtures cannot be benchmark evidence')
        return self


class ArtifactReference(FrozenModel):
    path: Identifier
    sha256: Hash256


class OfficialScore(FrozenModel):
    official_reward: float
    success: StrictBool
    reward_components: dict[str, float] | None = None
    reward_basis: tuple[str, ...] | None = None
    db_match: bool | None = None
    raw_reward: ArtifactReference | None = None

    @model_validator(mode='after')
    def official_binary_semantics(self):
        if self.official_reward not in (0.0, 1.0):
            raise ValueError('Unsupported nonbinary official reward; do not threshold or clip it')
        if self.success != (self.official_reward == 1.0):
            raise ValueError('Success must agree with the unchanged official reward')
        return self


class ToolStatistics(FrozenModel):
    attempted: Count
    attempt_scope: Literal['all_attempts', 'parsed_calls'] = 'all_attempts'
    parse_errors: Count | None = None
    execution_errors: Count | None = None
    framework_errors: Count | None = None
    missing_reason: str | None = None

    @model_validator(mode='after')
    def consistent_counts(self):
        values = (self.parse_errors, self.execution_errors, self.framework_errors)
        if sum(x for x in values if x is not None) > self.attempted:
            raise ValueError('Mutually exclusive tool errors cannot exceed attempts')
        if self.attempt_scope == 'parsed_calls' and self.parse_errors not in (None, 0):
            raise ValueError('Malformed attempts are outside parsed_calls denominator')
        if any(x is None for x in values) and not self.missing_reason:
            raise ValueError('Unknown error counts require a missing_reason')
        return self


class TokenUsage(FrozenModel):
    prompt_tokens: Count | None = None
    completion_tokens: Count | None = None
    source: Literal['provider_usage', 'instrumented', 'not_available'] = 'not_available'
    missing_reason: str | None = 'not recorded'

    @model_validator(mode='after')
    def honest_usage(self):
        if self.source == 'not_available' and (self.prompt_tokens is not None or self.completion_tokens is not None):
            raise ValueError('Unavailable usage must not contain fabricated token counts')
        if (self.prompt_tokens is None or self.completion_tokens is None) and not self.missing_reason:
            raise ValueError('Unknown token counts require a missing_reason')
        return self


class CostObservation(FrozenModel):
    role: Literal['student', 'user', 'teacher', 'shared']
    amount: float = Field(ge=0)
    currency: Annotated[str, Field(pattern=r'^[A-Z]{3}$')]
    kind: Literal['actual_bill', 'provider_estimate', 'upper_bound_estimate']
    source: Identifier


class ResourceUsage(FrozenModel):
    student: TokenUsage = Field(default_factory=TokenUsage)
    user: TokenUsage = Field(default_factory=TokenUsage)
    teacher: TokenUsage = Field(default_factory=TokenUsage)
    api_costs: tuple[CostObservation, ...] | None = None
    gpu_seconds: float | None = Field(default=None, ge=0)
    teacher_inference_seconds: float | None = Field(default=None, ge=0)
    training_tokens: Count | None = None
    missing_reason: str | None = 'No training/GPU telemetry recorded'


class FutureTrainingDiagnostics(FrozenModel):
    group_reward_mean: float | None = None
    group_reward_variance: float | None = Field(default=None, ge=0)
    all_zero_group_fraction: float | None = Field(default=None, ge=0, le=1)
    all_equal_group_fraction: float | None = Field(default=None, ge=0, le=1)
    effective_group_fraction: float | None = Field(default=None, ge=0, le=1)
    kl: float | None = None
    clip_fraction: float | None = Field(default=None, ge=0, le=1)
    missing_reason: str = 'Not measured in Stage 1; requires actual training logs'


class EpisodeRecord(FrozenModel):
    context: RunContext
    episode_id: Identifier
    task_id: Identifier
    trial_id: Identifier
    provenance: Provenance
    db_snapshot_id: Identifier
    db_snapshot_sha256: Hash256
    seed: StrictInt | None = None
    evaluated_at: datetime
    original_timestamp: str | None = None
    termination_reason: Termination
    execution_status: Literal['completed', 'framework_error', 'network_error', 'not_run']
    scoring_status: Literal['scored', 'error', 'not_available']
    official_score: OfficialScore | None = None
    tools: ToolStatistics | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    resources: ResourceUsage = Field(default_factory=ResourceUsage)
    trajectory: ArtifactReference | None = None
    error_code: str | None = None
    diagnostic_codes: tuple[str, ...] = ()
    task_type: str | None = None

    @model_validator(mode='after')
    def consistent_outcome(self):
        if self.evaluated_at.tzinfo is None:
            raise ValueError('Evaluation timestamp must include timezone')
        if (self.scoring_status == 'scored') != (self.official_score is not None):
            raise ValueError('Scored status requires official score; unscored status must preserve null')
        if self.execution_status == 'not_run':
            if self.termination_reason != 'not_run' or self.official_score is not None:
                raise ValueError('not_run cannot be presented as a scored episode')
        elif self.termination_reason == 'not_run':
            raise ValueError('Started episode cannot have not_run termination')
        if self.execution_status in ('network_error', 'framework_error'):
            if self.termination_reason != self.execution_status or self.official_score is not None:
                raise ValueError('Infrastructure errors are distinct from official scored failures')
        if self.official_score and self.termination_reason not in ('user_stop', 'agent_stop'):
            if self.official_score.official_reward != 0:
                raise ValueError('Official premature-termination reward must remain zero')
        return self

    @property
    def official_reward(self) -> float | None:
        return self.official_score.official_reward if self.official_score else None

    @property
    def success(self) -> bool | None:
        return self.official_score.success if self.official_score else None

    @property
    def started(self) -> bool:
        return self.execution_status != 'not_run'

    @property
    def abnormal_termination(self) -> bool:
        return self.started and self.termination_reason not in ('user_stop', 'agent_stop')
