import json

import pytest

from policytrace.stage0.user_sim_check import run_mock_episode, PRIVATE_USER, PRIVATE_EVAL
from tau2.data_model.simulation import TerminationReason
from tau2.user.user_simulator import UserSimulator
from tau2.data_model.message import UserMessage


def test_official_mock_routing_and_private_fields(selected, snapshots):
    record = selected[1]
    sim, calls = run_mock_episode(record, snapshots[record.db_path])
    assert sim.termination_reason == TerminationReason.USER_STOP
    assert len(calls['agent']) == 2 and len(calls['user']) == 2
    assert PRIVATE_USER in json.dumps(calls['user'])
    assert PRIVATE_USER not in json.dumps(calls['agent'])
    assert PRIVATE_EVAL not in json.dumps(calls)
    assert calls['agent'][0]['seed'] == calls['user'][0]['seed'] == 42
    assert calls['agent'][0]['temperature'] == calls['user'][0]['temperature'] == 0
    assert calls['agent'][0]['tools'] and not calls['user'][0]['tools']
    assert any(m['role']=='tool' for m in calls['agent'][1]['messages'])
    assert all(m['role']!='tool' for c in calls['user'] for m in c['messages'])
    assert any(m.role=='tool' and not m.error for m in sim.messages)


@pytest.mark.parametrize('token', ['###STOP###','###TRANSFER###','###OUT-OF-SCOPE###'])
def test_user_termination_tokens(token):
    # Tokens are checked against upstream constants below to avoid inventing protocol.
    from tau2.user.base import STOP, TRANSFER, OUT_OF_SCOPE
    actual = {'###STOP###':STOP, '###TRANSFER###':TRANSFER, '###OUT-OF-SCOPE###':OUT_OF_SCOPE}[token]
    assert UserSimulator.is_stop(UserMessage(role='user',content=actual))
