import pytest

from policytrace.data.manifests import ROOT, read_json, write_json
from policytrace.data.task_pool import RLTaskPool
from policytrace.stage0.reference_check import reference_fixture
from policytrace.rewards.official import evaluate_r0


@pytest.mark.parametrize('pool_name',['rl_train_full','rl_dev'])
def test_train_dev_initialization_isolation_and_official_scoring(pool_name):
    pool=RLTaskPool(ROOT/f'data/splits/stage2/{pool_name}.json')
    selected=next(e['id'] for e in pool.manifest['entries'] if e['primary_type']=='account_address' and e['reference_action_count']>0)
    r,s=pool.load(selected); env=pool.new_environment(selected); untouched=pool.new_environment(selected)
    initial=env.get_db_hash()
    sim,evidence=reference_fixture(r,s)
    result=evaluate_r0(r,s,sim)
    assert result.score.db_match is True and result.score.official_reward==1
    assert not any(c['error'] for c in evidence['calls'])
    assert untouched.get_db_hash()==initial and env.get_db_hash()==initial
    context=pool.student_context(selected)
    assert set(context)=={'policy','tools'}
    assert 'user_scenario' not in context and 'evaluation_criteria' not in context and 'actions' not in context


def test_out_of_pool_and_changed_snapshot_are_rejected(tmp_path):
    m=read_json(ROOT/'data/splits/stage2/rl_train_full.json')
    pool=RLTaskPool(ROOT/'data/splits/stage2/rl_train_full.json')
    with pytest.raises(ValueError,match='outside'):pool.load('synthetic-outside')
    m['entries'][0]['snapshot_sha256']='0'*64
    path=tmp_path/'synthetic-corrupted-manifest.json';write_json(path,m)
    with pytest.raises(ValueError,match='Snapshot mismatch'):RLTaskPool(path).load(m['entries'][0]['id'])
