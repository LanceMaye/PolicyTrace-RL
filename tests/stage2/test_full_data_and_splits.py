import gzip
import json
from collections import Counter
import pytest

from policytrace.data.manifests import ROOT, digest, file_hash, read_json, read_jsonl, verify_sources
from policytrace.data.split import provenance_groups, assign_rl_groups, assign_sft_groups, select_pass4, validate_isolation
from policytrace.data.sft_tokenize import validate_labels
from policytrace.data.eval_plan import resolve_plan, REQUIRED
from policytrace.evaluation.schema import EvaluationPlan, task_set_hash
from policytrace.evaluation.metrics import aggregate


def test_pinned_sources_full_counts_and_no_schema_error(prepared):
    assert verify_sources()==prepared['audit']['sources']
    assert len(prepared['rl'])==563 and sum(d['turn_count'] for d in prepared['dialogs'])==11395 and len(prepared['dialogs'])==1000
    assert prepared['audit']['rl']['schema_errors']==[]
    assert prepared['audit']['sft']['format_error_rows']=={}
    assert prepared['audit']['sft']['exact_sample_duplicate_groups']==0
    assert prepared['audit']['rl']['exact_instance_duplicate_groups']==0


def test_actual_overlap_claims_are_conservative(prepared):
    assert Counter(e['classification'] for e in prepared['overlap'])==Counter(prepared['audit']['overlap']['classification_counts'])
    assert not any(e['classification']=='confirmed_same_instance' for e in prepared['overlap'])
    assert all(e['missing_evidence'] for e in prepared['overlap'])


def test_full_group_isolation_and_exposed_tasks(prepared):
    a=prepared['assignments']; exposed=read_json(ROOT/'data/private/stage2/known_exposed.json')
    validate_isolation(a['groups'],a['rl'],a['sft'],exposed)
    assert set(a['rl'])=={r['id'] for r in prepared['rl']}
    assert set(a['sft'])=={d['id'] for d in prepared['dialogs']}
    assert all(a['rl'][tid]=='dev' for tid in exposed)
    row_groups={}
    for s in ('train','val','quality_excluded','heldout_from_sft'):
        m=read_json(ROOT/f'data/splits/stage2/sft_{s}.json')
        for d in m['source_dialog_ids']:
            assert d not in row_groups; row_groups[d]=s
    assert row_groups==a['sft']


def test_seeded_global_assignment_reproduces_manifests(prepared):
    p=ROOT/'data/private/stage2'; cfg=prepared['split']['config']
    g=provenance_groups(prepared['rl'],prepared['dialogs'],read_json(p/'duplicate_groups.json'),prepared['overlap'])
    ra,decisions,targets=assign_rl_groups(g,prepared['rl'],prepared['dialogs'],read_json(p/'known_exposed.json'),cfg['seed'],cfg['rl_target_ratios'])
    sa=assign_sft_groups(g,prepared['dialogs'],ra,cfg['seed'],cfg['sft_val_fraction'])
    assert {'rl':ra,'sft':sa,'groups':g,'config_sha256':digest(cfg)}==prepared['assignments']
    subset=select_pass4([r for r in prepared['rl'] if ra[r['id']]=='test'],cfg['pass4_task_target'],cfg['seed']+2)
    assert subset==read_json(ROOT/'data/splits/stage2/pass4_subset.json')['task_ids']
    for name,s in [('rl_train_full','train'),('rl_dev','dev'),('rl_test_frozen','test')]:
        m=read_json(ROOT/f'data/splits/stage2/{name}.json')
        assert m['task_ids']==sorted(t for t,v in ra.items() if v==s)
        assert m['task_set_sha256']==task_set_hash(m['task_ids'])


def test_sft_quality_filter_does_not_reduce_experts_for_rl_effect(prepared):
    a=prepared['assignments']['sft']
    bad=[d for d in prepared['dialogs'] if a[d['id']]=='quality_excluded']
    assert len(bad)==8 and sum(d['turn_count'] for d in bad)==108
    assert all('source_quality_failed' in d['issues'] for d in bad)
    assert all(a[d['id']] in {'train','val'} for d in prepared['dialogs'] if not d['issues'])
    assert all(a[d['id']]!='quality_excluded' for d in prepared['dialogs'] if d['warnings'] and not d['issues'])


def test_real_cost_view_is_identical_and_restorable():
    p=ROOT/'data/splits/stage2'
    full=read_json(p/'rl_train_full.json'); pruned=read_json(p/'rl_train_cost_pruned.json')
    assert full['task_ids']==pruned['task_ids'] and full['task_set_sha256']==pruned['task_set_sha256']
    assert read_json(p/'rl_cost_exclusions.json')['exclusions']==[]


def test_all_exported_token_labels_and_untruncated_oversize(tokenizer):
    report=read_json(ROOT/'reports/stage2/quality_report.json')
    counts=Counter(); sample_ids=set()
    for s in ('train','val'):
        for kind,suffix in [('tokens','tokenized'),('oversize','oversize.tokenized')]:
            with gzip.open(ROOT/f'data/processed/stage2/sft_{s}.{suffix}.jsonl.gz','rt',encoding='utf-8') as f:
                for line in f:
                    r=json.loads(line); validate_labels(r,tokenizer.eos)
                    sid=r['provenance']['sample_id']; assert sid not in sample_ids; sample_ids.add(sid)
                    n=len(r['input_ids']); assert (n<=report['config']['max_length']) == (kind=='tokens')
                    counts[f'{s}_{kind}']+=1
    assert len(sample_ids)==11287
    for key,n in counts.items(): assert n==report['counts'][key]
    for name,entry in report['artifacts'].items(): assert file_hash(ROOT/'data/processed/stage2'/name)==entry['sha256']


@pytest.mark.parametrize('trials',[1,4])
def test_unexecuted_plans_resolve_to_stage1_schema_and_no_fake_scores(trials):
    template=read_json(ROOT/f'data/splits/stage2/pass{trials}_plan_template.json')
    assert template['status']=='NOT_RUN_UNRESOLVED'
    with pytest.raises(ValueError,match='Unresolved'): resolve_plan(template,{})
    config={k:None for k in REQUIRED}
    config.update(run_id='synthetic-schema-check-not-executed',model_id='synthetic-model',simulator_model='synthetic-user',
        simulator_config_id='synthetic-user-config',harness_version='synthetic-schema-test',max_steps=1,max_errors=1,
        model_sampling={'temperature':0},simulator_sampling={'temperature':0},purpose='diagnostic')
    plan=resolve_plan(template,config)
    assert EvaluationPlan.model_validate_json(plan.model_dump_json())==plan
    assert plan.trials_per_task==trials and len(plan.trial_ids)==trials
    summary=aggregate(plan,[])
    assert summary['status']=='incomplete' and summary['pass1']['value'] is None and summary['pass4']['value'] is None


def test_actual_external_candidate_count_and_honest_status():
    base=ROOT/'external/tau2-bench/data/tau2/domains/retail'
    source=read_json(base/'split_tasks.json'); report=read_json(ROOT/'reports/stage2/external_eval_audit.json')
    assert report['actual_test_count']==len(source['test'])
    assert report['episodes_run']==0 and 'UNPROVEN' in read_json(ROOT/'data/private/stage2/external_test_candidate.json')['independence']
    m=read_json(ROOT/'data/private/stage2/external_test_candidate.json')
    assert m['task_set_sha256']==task_set_hash(m['task_ids'])
