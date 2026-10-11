from datetime import datetime

from pydantic import ValidationError
import pytest

from policytrace.evaluation.schema import EpisodeRecord, EvaluationPlan, OfficialScore, TokenUsage, ToolStatistics
from policytrace.rewards.interface import TrainingReward, select_training_reward


def test_json_roundtrip_and_immutable_score(make_plan, make_episode):
    e = make_episode(make_plan())
    assert EpisodeRecord.model_validate_json(e.model_dump_json()) == e
    with pytest.raises(ValidationError):
        e.official_score.official_reward = 0


@pytest.mark.parametrize('value', [.5, float('nan'), float('inf')])
def test_unsupported_official_reward_rejected(value):
    with pytest.raises(ValidationError):
        OfficialScore(official_reward=value, success=False)


def test_success_must_match_score():
    with pytest.raises(ValidationError):
        OfficialScore(official_reward=0, success=True)


def test_synthetic_plan_cannot_be_named_formal_benchmark(make_plan):
    data = make_plan().model_dump(mode='json')
    data['context']['purpose'] = 'benchmark'
    with pytest.raises(ValidationError, match='benchmark evidence'):
        EvaluationPlan.model_validate(data)


@pytest.mark.parametrize('change', ['duplicate_task', 'duplicate_trial', 'wrong_hash', 'wrong_count'])
def test_bad_plan_rejected(change, make_plan):
    data = make_plan().model_dump(mode='json')
    if change == 'duplicate_task': data['task_ids'] = ['a', 'a']
    elif change == 'duplicate_trial': data['trial_ids'] = ['0', '0', '1', '2']; data['trials_per_task'] = 4
    elif change == 'wrong_hash': data['context']['task_set_sha256'] = '0'*64
    else: data['trial_ids'] = ['0', '1']
    with pytest.raises(ValidationError):
        EvaluationPlan.model_validate(data)


def test_invalid_telemetry_rejected():
    with pytest.raises(ValidationError):
        ToolStatistics(attempted=1, parse_errors=1, execution_errors=1, framework_errors=0)
    with pytest.raises(ValidationError):
        ToolStatistics(attempted=-1, parse_errors=0, execution_errors=0, framework_errors=0)
    with pytest.raises(ValidationError):
        TokenUsage(prompt_tokens=0)  # Default is not_available; never imply a real zero.


def test_timezone_and_scoring_status_checked(make_plan, make_episode):
    p = make_plan()
    with pytest.raises(ValidationError):
        make_episode(p, evaluated_at=datetime(2026, 10, 10))
    with pytest.raises(ValidationError):
        make_episode(p, reward=None, scoring_status='scored')
    with pytest.raises(ValidationError):
        make_episode(p, termination_reason='max_steps', reward=1)


def test_default_training_is_r0(make_plan, make_episode):
    e = make_episode(make_plan(), reward=0)
    out = select_training_reward(e)
    assert out.official_reward == out.training_reward.value == 0
    assert out.training_reward.name == 'R0'


def test_test_plugin_separate_from_official_and_no_hidden_inputs(make_plan, make_episode):
    e = make_episode(make_plan(), reward=0)
    before = e.model_dump_json()
    class TestPlugin:
        def evaluate(self, signals):
            assert set(type(signals).model_fields) == {'official_reward', 'termination_reason', 'tools', 'duration_seconds'}
            assert not hasattr(signals, 'task') and not hasattr(signals, 'trajectory')
            with pytest.raises(ValidationError):
                signals.official_reward = 1
            return TrainingReward(name='TEST_DOUBLE_ONLY', version='test-v1', value=.7, components={'test': .7})
    out = select_training_reward(e, TestPlugin())
    assert out.official_reward == 0 and out.training_reward.value == .7
    assert e.model_dump_json() == before


def test_unscored_cannot_invent_training_r0(make_plan, make_episode):
    with pytest.raises(ValueError, match='unscored'):
        select_training_reward(make_episode(make_plan(), reward=None))
