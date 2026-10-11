import pytest

from policytrace.evaluation.metrics import aggregate
from policytrace.evaluation.schema import (CostObservation, ResourceUsage, TokenUsage, ToolStatistics)


def test_pass1_and_explicit_denominator(make_plan, make_episode):
    p = make_plan()
    records = [make_episode(p, task=p.task_ids[0], reward=0), make_episode(p, task=p.task_ids[1], reward=1)]
    s = aggregate(p, records)
    assert s['pass1']['value'] == .5 and s['pass1']['denominator'] == 2
    assert s['pass4']['status'] == 'not_requested' and s['pass4']['value'] is None


def test_pass4_is_all_success_not_pass_at_four(make_plan, make_episode):
    p = make_plan(trials=4)
    records = [make_episode(p, task=task, trial=t, reward=int(task == p.task_ids[0] or t != '2'))
               for task in p.task_ids for t in p.trial_ids]
    s = aggregate(p, records)
    assert s['pass1']['value'] == 1
    assert s['pass4']['value'] == .5
    assert all(any(t['success'] for t in task['trials']) for task in s['tasks'])  # Pass@4 = 1.


@pytest.mark.parametrize('trials', [1, 4])
def test_missing_trial_is_incomplete_without_smaller_denominator(trials, make_plan, make_episode):
    p = make_plan(trials=trials)
    records = [make_episode(p, task=task, trial=t) for task in p.task_ids for t in p.trial_ids][:-1]
    s = aggregate(p, records)
    assert s['status'] == 'incomplete'
    assert s['pass1']['value'] is None and s['pass4']['value'] is None
    assert s['pass1']['denominator'] == 2
    assert len(s['coverage']['missing_or_not_run']) == 1


def test_not_run_is_incomplete(make_plan, make_episode):
    p = make_plan(task_ids=('synthetic_a',))
    e = make_episode(p, reward=None, execution_status='not_run', termination_reason='not_run', scoring_status='not_available')
    s = aggregate(p, [e])
    assert s['status'] == 'incomplete' and s['coverage']['started_trials'] == 0
    assert s['abnormal_termination']['rate'] is None


def test_empty_collection(make_plan):
    s = aggregate(make_plan(task_ids=()), [])
    assert s['status'] == 'empty' and s['pass1']['value'] is None
    assert s['tokens']['student']['prompt_tokens']['total'] is None


@pytest.mark.parametrize('kind', ['duplicate', 'unexpected_task', 'unexpected_trial'])
def test_invalid_identity_rejected(kind, make_plan, make_episode):
    p = make_plan()
    if kind == 'duplicate':
        e = make_episode(p)
        records = [e, e]
    else:
        records = [make_episode(p, task='outside' if kind == 'unexpected_task' else p.task_ids[0],
                                trial='outside' if kind == 'unexpected_trial' else '0')]
    with pytest.raises(ValueError):
        aggregate(p, records)


@pytest.mark.parametrize('field,value', [
    ('model_id', 'other-model'), ('simulator_config_id', 'other-user'),
    ('environment_sha', 'f'*40), ('dataset_revision', 'f'*40), ('max_steps', 99), ('run_id', 'other-run')])
def test_mixed_configuration_rejected(field, value, make_plan, make_episode):
    p = make_plan(trials=4)
    e = make_episode(p, context=p.context.model_copy(update={field: value}))
    with pytest.raises(ValueError, match='configuration mismatch'):
        aggregate(p, [e])


def test_same_task_wrong_snapshot_rejected(make_plan, make_episode):
    p = make_plan(task_ids=('synthetic_a',), trials=4)
    with pytest.raises(ValueError, match='snapshot changed'):
        aggregate(p, [make_episode(p), make_episode(p, trial='1', db_snapshot_sha256='b'*64)])


def test_one_saved_episode_cannot_be_four_trials(make_plan, make_episode):
    p = make_plan(task_ids=('synthetic_a',), trials=4)
    with pytest.raises(ValueError, match='independent trial'):
        aggregate(p, [make_episode(p), make_episode(p, trial='1', episode_id='synthetic-synthetic_a-0')])


def test_seed_variation_allowed_but_source_mixing_rejected(make_plan, make_episode):
    p = make_plan(task_ids=('synthetic_a',), trials=4)
    records = [make_episode(p, trial=t, seed=int(t)) for t in p.trial_ids]
    assert aggregate(p, records)['pass4']['value'] == 1
    with pytest.raises(ValueError, match='mix real'):
        aggregate(p, [make_episode(p, provenance='saved_real_episode')])


@pytest.mark.parametrize('reason,status', [('max_steps', 'completed'), ('network_error', 'network_error'), ('framework_error', 'framework_error')])
def test_started_errors_stay_in_denominator(reason, status, make_plan, make_episode):
    p = make_plan()
    failed = make_episode(p, reward=0 if reason == 'max_steps' else None,
                          execution_status=status, termination_reason=reason, error_code='TEST_ERROR')
    records = [failed, make_episode(p, task=p.task_ids[1])]
    s = aggregate(p, records)
    assert s['status'] == 'complete' and s['pass1']['value'] == .5
    assert s['abnormal_termination'] == {'numerator': 1, 'denominator': 2, 'rate': .5}
    assert s['tasks'][0]['trials'][0]['official_reward'] == (0 if reason == 'max_steps' else None)


def test_scoring_error_is_not_fabricated_official_zero(make_plan, make_episode):
    p = make_plan(task_ids=('synthetic_a',))
    s = aggregate(p, [make_episode(p, reward=None)])
    assert s['pass1']['value'] == 0 and s['coverage']['scored_trials'] == 0
    assert s['tasks'][0]['trials'][0]['official_reward'] is None
    assert s['abnormal_termination']['rate'] == 0


def test_weighted_tool_error_rate_and_distribution(make_plan, make_episode):
    p = make_plan()
    a = ToolStatistics(attempted=1, parse_errors=1, execution_errors=0, framework_errors=0)
    b = ToolStatistics(attempted=9, parse_errors=0, execution_errors=1, framework_errors=1)
    s = aggregate(p, [make_episode(p, tools=a), make_episode(p, task=p.task_ids[1], tools=b)])
    assert s['tools']['error_rate'] == .3  # 3/10, not average of episode rates.
    assert s['tools']['parsed_attempts'] == 9 and s['tools']['execution_error_rate'] == 1/9
    assert s['tools']['call_count']['mean'] == 5
    assert len(s['tools']['per_episode']) == 2


def test_zero_calls_and_unrecorded_usage_are_null(make_plan, make_episode):
    p = make_plan(task_ids=('synthetic_a',))
    s = aggregate(p, [make_episode(p)])
    assert s['tools']['complete_attempts'] == 0 and s['tools']['error_rate'] is None
    assert s['duration_seconds']['mean'] is None
    assert s['tokens']['student']['completion_tokens']['total'] is None
    assert s['training_resources']['gpu_seconds']['total'] is None
    assert s['training_diagnostics']['group_reward_variance'] is None


def test_partial_telemetry_cannot_be_presented_as_complete(make_plan, make_episode):
    p = make_plan()
    usage = ResourceUsage(student=TokenUsage(prompt_tokens=10, completion_tokens=5, source='provider_usage', missing_reason=None))
    s = aggregate(p, [make_episode(p, resources=usage, duration_seconds=1), make_episode(p, task=p.task_ids[1])])
    assert s['tokens']['student']['completion_tokens']['total'] is None
    assert s['tokens']['student']['completion_tokens']['observed_subtotal'] == 5
    assert s['duration_seconds']['mean'] is None


def test_parsed_calls_only_do_not_claim_complete_error_rate(make_plan, make_episode):
    p = make_plan(task_ids=('synthetic_a',))
    t = ToolStatistics(attempted=2, attempt_scope='parsed_calls', execution_errors=1, missing_reason='Not recorded')
    s = aggregate(p, [make_episode(p, tools=t)])
    assert s['tools']['error_rate'] is None and s['tools']['complete_attempts'] is None
    assert s['tools']['execution_error_rate'] == .5


def test_costs_not_mixed_across_currency_or_type(make_plan, make_episode):
    p = make_plan(task_ids=('synthetic_a',))
    values = [('CNY', 'upper_bound_estimate', 2), ('CNY', 'actual_bill', 1), ('USD', 'actual_bill', .2)]
    costs = tuple(CostObservation(role='student', currency=c, kind=k, amount=a, source='synthetic') for c,k,a in values)
    s = aggregate(p, [make_episode(p, resources=ResourceUsage(api_costs=costs))])
    assert len(s['api_costs']['groups']) == 3
    assert s['api_costs']['missing_episodes'] == 0
