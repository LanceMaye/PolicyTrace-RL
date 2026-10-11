import json
from pathlib import Path

import pytest

from policytrace.stage0.db_adapter import load_retail_db
from policytrace.stage0.task_loader import iter_retail_records, load_retail_task
from policytrace.stage0.reference_check import reference_fixture
from policytrace.stage0.evaluator_adapter import evaluate_with_correct_initial_state
from policytrace.rewards.official import evaluate_r0
from tau2.data_model.simulation import SimulationRun

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def cases():
    selected = {'retail_131', 'retail_152', 'retail_245'}
    records = {r['id']: load_retail_task(r, i) for i, r in iter_retail_records(ROOT/'data/raw') if r['id'] in selected}
    return {tid: (record, load_retail_db(record.db_path, ROOT/'data/raw')) for tid, record in records.items()}


@pytest.mark.parametrize('task_id,expected', [('retail_131', 0), ('retail_152', 1)])
def test_saved_real_scores_and_raw_info_unchanged(task_id, expected, cases, tmp_path):
    folder = ROOT/'data/private/stage0/deepseek'
    sim = SimulationRun.model_validate_json((folder/f'{task_id}-episode.json').read_text(encoding='utf-8'))
    record, snapshot = cases[task_id]
    result = evaluate_r0(record, snapshot, sim, private_reward_path=tmp_path/'private-reward.json')
    original = json.loads((folder/f'{task_id}-reward.json').read_text(encoding='utf-8'))
    assert result.score.official_reward == expected
    assert result.reward_info().model_dump(mode='json') == original
    assert result.score.raw_reward is not None
    # Numeric public result contains no reference action arguments or private prompt.
    public = result.score.model_dump(mode='json')
    assert 'actions' not in public and 'user_scenario' not in public


def test_r0_correct_and_wrong_final_db_and_wrong_snapshot(cases):
    record, snapshot = cases['retail_245']
    sim, _ = reference_fixture(record, snapshot)
    result = evaluate_r0(record, snapshot, sim)
    assert result.score.official_reward == 1 and result.score.db_match
    assert result.reward_info() == evaluate_with_correct_initial_state(record, snapshot, sim)
    empty = sim.model_copy(update={'messages': []}, deep=True)
    failed = evaluate_r0(record, snapshot, empty)
    assert failed.score.official_reward == 0 and not failed.score.db_match
    wrong = cases['retail_131'][1]
    with pytest.raises(ValueError, match='does not match'):
        evaluate_r0(record, wrong, sim)


def test_premature_termination_preserves_original_zero(cases):
    record, snapshot = cases['retail_245']
    sim, _ = reference_fixture(record, snapshot)
    from tau2.data_model.simulation import TerminationReason
    sim.termination_reason = TerminationReason.MAX_STEPS
    result = evaluate_r0(record, snapshot, sim)
    assert result.score.official_reward == 0 and result.score.reward_components is None
