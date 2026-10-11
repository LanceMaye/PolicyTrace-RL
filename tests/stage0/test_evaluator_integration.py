from copy import deepcopy

import pytest

from policytrace.stage0.db_adapter import snapshot_constructor
from policytrace.stage0.evaluator_adapter import evaluate_with_correct_initial_state
from policytrace.stage0.reference_check import reference_fixture
from tau2.data_model.message import AssistantMessage
from tau2.data_model.simulation import TerminationReason
from tau2.evaluator.evaluator import evaluate_simulation, EvaluationType
from tau2.evaluator.evaluator_env import EnvironmentEvaluator


@pytest.mark.parametrize('index', range(8))
def test_official_reference_scoring(index, selected, snapshots):
    record = selected[index]
    snapshot = snapshots[record.db_path]
    simulation, detail = reference_fixture(record, snapshot)
    assert not any(x['error'] for x in detail['calls']), detail['calls']
    reward = evaluate_with_correct_initial_state(record, snapshot, simulation)
    assert reward.db_check.db_match is True
    assert reward.reward in (0.0, 1.0)  # Communication requirements remain independent.
    observed = []
    factory = snapshot_constructor(record, snapshot)

    def traced(solo_mode=False):
        env = factory(solo_mode=solo_mode)
        observed.append(env.get_db_hash())
        return env

    raw = EnvironmentEvaluator.calculate_reward(traced, record.task, simulation.messages)
    assert observed == [snapshot.content_hash, snapshot.content_hash]
    assert raw.db_check.db_match


@pytest.mark.parametrize('index', [0, 2])
def test_mutation_negative_control_and_wrong_initial_db(index, selected, snapshots):
    record = selected[index]
    snapshot = snapshots[record.db_path]
    sim, detail = reference_fixture(record, snapshot)
    assert detail['initial_hash'] != detail['final_hash']
    empty = sim.model_copy(update={'messages':[]}, deep=True)
    assert not evaluate_with_correct_initial_state(record, snapshot, empty).db_check.db_match
    # An actual trajectory from the custom snapshot cannot replay on the default DB.
    with pytest.raises(ValueError, match='Returned:'):
        evaluate_simulation(sim, record.task, EvaluationType.ALL, False, 'retail')
    wrong = next(s for p,s in snapshots.items() if p != record.db_path)
    with pytest.raises(ValueError, match='does not match'):
        evaluate_with_correct_initial_state(record, wrong, sim)


def test_official_communication_and_termination_preserved(selected, snapshots):
    record = deepcopy(selected[0])
    snapshot = snapshots[record.db_path]
    sim, _ = reference_fixture(record, snapshot)
    record.task.evaluation_criteria.communicate_info = ['STAGE0-COMMUNICATION-SENTINEL']
    assert evaluate_with_correct_initial_state(record, snapshot, sim).reward == 0
    sim.messages.append(AssistantMessage(role='assistant',content='STAGE0-COMMUNICATION-SENTINEL'))
    assert evaluate_with_correct_initial_state(record, snapshot, sim).reward == 1
    sim.termination_reason = TerminationReason.MAX_STEPS
    assert evaluate_with_correct_initial_state(record, snapshot, sim).reward == 0


def test_task_id_mismatch_rejected(selected, snapshots):
    record = selected[0]
    sim, _ = reference_fixture(record, snapshots[record.db_path])
    sim.task_id = 'retail_wrong'
    with pytest.raises(ValueError, match='task ID'):
        evaluate_with_correct_initial_state(record, snapshots[record.db_path], sim)
