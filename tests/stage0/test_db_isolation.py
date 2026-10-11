import hashlib

import pytest

from policytrace.stage0.db_adapter import make_retail_env, load_retail_db
from policytrace.stage0.reference_check import reference_fixture
from tau2.domains.retail.environment import get_environment
from tau2.data_model.message import ToolCall


@pytest.mark.parametrize('index', [0, 1, 2, 4])
def test_isolation_reset_and_source_unchanged(index, selected, snapshots, data_root):
    record = selected[index]
    snapshot = snapshots[record.db_path]
    disk = data_root / record.db_path
    before = hashlib.sha256(disk.read_bytes()).hexdigest()
    a, b = make_retail_env(record, snapshot), make_retail_env(record, snapshot)
    assert a.get_db_hash() == b.get_db_hash()
    user_id = next(iter(a.tools.db.users))
    response = a.get_response(ToolCall(id='isolation', name='modify_user_address', arguments={
        'user_id':user_id,'address1':'Stage0 test address','address2':'','city':'Test City',
        'state':'CA','country':'USA','zip':'99999'}))
    assert not response.error
    assert a.get_db_hash() != b.get_db_hash()
    for _ in range(3):
        assert make_retail_env(record, snapshot).get_db_hash() == b.get_db_hash()
    assert hashlib.sha256(disk.read_bytes()).hexdigest() == before == snapshot.file_sha256
    assert load_retail_db(record.db_path, data_root).content_hash == snapshot.content_hash


def test_default_and_custom_differ(selected, snapshots):
    default_hash = get_environment().get_db_hash()
    assert all(make_retail_env(r, snapshots[r.db_path]).get_db_hash() != default_hash for r in selected)


def test_wrong_snapshot_rejected(selected, snapshots):
    record = selected[0]
    wrong = next(s for p,s in snapshots.items() if p != record.db_path)
    with pytest.raises(ValueError, match='does not match'):
        make_retail_env(record, wrong)


def test_mutated_snapshot_rejected(selected, snapshots):
    from dataclasses import replace
    record = selected[0]
    original = snapshots[record.db_path]
    changed = original.db.model_copy(deep=True)
    next(iter(changed.users.values())).address.city = 'Changed'
    with pytest.raises(ValueError, match='mutated'):
        make_retail_env(record, replace(original, db=changed))


def test_illegal_tool_observation_and_solo_rejection(selected, snapshots):
    record = selected[0]
    env = make_retail_env(record, snapshots[record.db_path])
    for call in [ToolCall(id='1',name='nonexistent',arguments={}),
                 ToolCall(id='2',name='get_order_details',arguments={'order_id':'#missing'}),
                 ToolCall(id='3',name='get_user_details',arguments={})]:
        result = env.get_response(call)
        assert result.error and result.content and result.id == call.id
    with pytest.raises(ValueError, match='does not support solo'):
        get_environment(solo_mode=True)

