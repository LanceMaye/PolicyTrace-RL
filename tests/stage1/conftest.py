from datetime import datetime, timezone
import socket

import pytest

from policytrace.evaluation.schema import (EpisodeRecord, EvaluationPlan, OfficialScore, RunContext,
    SamplingSettings, ToolStatistics, ENVIRONMENT_SHA, DATASET_REVISION, task_set_hash)


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Stage 1 must not call networks or paid APIs')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


@pytest.fixture
def make_plan():
    def make(task_ids=('synthetic_a', 'synthetic_b'), trials=1):
        settings = SamplingSettings(temperature=0, max_output_tokens=128, provider_seed_supported=False)
        context = RunContext(run_id='synthetic-unit-test', task_set_id='synthetic-only', task_set_sha256=task_set_hash(task_ids),
            environment_sha=ENVIRONMENT_SHA, dataset_revision=DATASET_REVISION, model_id='synthetic-model',
            model_sampling=settings, simulator_model='synthetic-user', simulator_config_id='synthetic-user-v1',
            simulator_sampling=settings, harness_version='synthetic-fixture-v1', max_steps=10, max_errors=2)
        return EvaluationPlan(context=context, task_ids=task_ids, trial_ids=tuple(str(i) for i in range(trials)),
                              trials_per_task=trials, provenance='synthetic')
    return make


@pytest.fixture
def make_episode():
    def make(plan, task=None, trial='0', reward=1, **overrides):
        values = dict(context=plan.context, episode_id=f'synthetic-{task or plan.task_ids[0]}-{trial}', task_id=task or plan.task_ids[0], trial_id=trial,
            provenance='synthetic', db_snapshot_id='synthetic/snapshot.json', db_snapshot_sha256='a'*64,
            seed=42, evaluated_at=datetime(2026, 10, 10, tzinfo=timezone.utc), termination_reason='user_stop',
            execution_status='completed', scoring_status='scored' if reward is not None else 'error',
            official_score=OfficialScore(official_reward=reward, success=reward == 1) if reward is not None else None,
            tools=ToolStatistics(attempted=0, parse_errors=0, execution_errors=0, framework_errors=0))
        values.update(overrides)
        return EpisodeRecord(**values)
    return make
