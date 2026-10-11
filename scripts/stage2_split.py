import json
from collections import Counter
import yaml

from policytrace.data.manifests import ROOT, digest, file_hash, read_json, read_jsonl, task_manifest, write_json
from policytrace.data.split import provenance_groups, assign_rl_groups, assign_sft_groups, select_pass4, validate_isolation, marginals
from policytrace.data.cost_filter import cost_pruned_view
from policytrace.data.eval_plan import plan_template


def main():
    p = ROOT/'data/private/stage2'; out = ROOT/'data/splits/stage2'
    audit = read_json(ROOT/'reports/stage2/source_audit.json')
    for name, expected in audit['private_artifacts'].items():
        if file_hash(p/name) != expected: raise ValueError('Stale/incomplete audit artifact: '+name)
    cfg = yaml.safe_load((ROOT/'configs/data/split_config.yaml').read_text(encoding='utf-8'))
    rl, dialogs = list(read_jsonl(p/'rl_features.jsonl')), list(read_jsonl(p/'dialog_features.jsonl'))
    candidates = list(read_jsonl(p/'overlap_candidates.jsonl'))
    exposed = read_json(p/'known_exposed.json')
    groups = provenance_groups(rl, dialogs, read_json(p/'duplicate_groups.json'), candidates)
    ra, decisions, targets = assign_rl_groups(groups, rl, dialogs, exposed, seed=cfg['seed'], ratios=cfg['rl_target_ratios'])
    sa = assign_sft_groups(groups, dialogs, ra, seed=cfg['seed'], val_fraction=cfg['sft_val_fraction'])
    validate_isolation(groups, ra, sa, exposed)
    write_json(p/'group_decisions.json', decisions)
    write_json(p/'assignments.json', {'rl': ra, 'sft': sa, 'groups': groups, 'config_sha256': digest(cfg)})
    allowed = ('id','source_line','db_path','snapshot_sha256','task_payload_sha256','primary_type','labels',
               'mutates','communicate_nonempty','reference_action_count','reference_length_proxy','instance_fingerprint')
    public_features = [{k:r[k] for k in allowed} for r in rl]
    manifests = {}
    for split, name in [('train','rl_train_full'),('dev','rl_dev'),('test','rl_test_frozen')]:
        manifests[name] = task_manifest(name, [f for f in public_features if ra[f['id']] == split])
    pruned, exclusions = cost_pruned_view(manifests['rl_train_full']['task_ids'], [d for d,s in sa.items() if s=='train'], candidates)
    manifests['rl_train_cost_pruned'] = task_manifest('rl_train_cost_pruned', [f for f in public_features if f['id'] in pruned])
    subset = select_pass4([r for r in rl if ra[r['id']]=='test'], cfg['pass4_task_target'], cfg['seed']+2)
    manifests['pass4_subset'] = task_manifest('pass4_subset', [f for f in public_features if f['id'] in subset])
    for name, manifest in manifests.items(): write_json(out/f'{name}.json', manifest)
    write_json(out/'rl_cost_exclusions.json', {'rule_version':'policytrace-overlap-v1', 'default_view':'rl_train_full',
        'exclusions':exclusions,'rollback':'Select rl_train_full.json; originals are unchanged.'})
    for split in ('train','val','quality_excluded','heldout_from_sft'):
        ds = sorted(d for d,s in sa.items() if s==split)
        write_json(out/f'sft_{split}.json', {'name':f'sft_{split}', 'source_dialog_ids':ds,
            'source_dialog_set_sha256': digest(ds), 'sample_ids':sorted(sid for d in dialogs if d['id'] in ds for sid in d['row_ids'])})
    write_json(out/'pass1_plan_template.json', plan_template(manifests['rl_test_frozen'],1))
    write_json(out/'pass4_plan_template.json', plan_template(manifests['pass4_subset'],4))
    stats = {'config':cfg,'config_sha256':digest(cfg),'actual_execution':'deterministic_full_source_group_assignment',
        'rl_target_counts':targets, 'rl_counts':dict(Counter(ra.values())),
        'rl_marginals':{s:dict(marginals([r for r in rl if ra[r['id']]==s])) for s in ('train','dev','test')},
        'sft':{s:{'dialogues':sum(v==s for v in sa.values()), 'turns':sum(d['turn_count'] for d in dialogs if sa[d['id']]==s),
            'primary_types':dict(Counter(d['primary_type'] for d in dialogs if sa[d['id']]==s)),
            'length_buckets':dict(Counter(d['length_bucket'] for d in dialogs if sa[d['id']]==s))} for s in ('train','val','quality_excluded','heldout_from_sft')},
        'global_groups':{'count':len(groups),'max_nodes':max(map(len,groups)),
            'nontrivial':sum(len(g)>1 for g in groups),'cross_source':sum(any(n.startswith('rl:') for n in g) and any(n.startswith('sft:') for n in g) for g in groups)},
        'known_exposed':{'count':len(exposed),'all_in_dev':all(ra[t]=='dev' for t in exposed)},
        'isolation':{'rl_intersections':0,'sft_dialogue_intersections':0,'provenance_group_crossings':0,
            'sft_train_rl_dev_collisions':0,'sft_model_use_rl_test_collisions':0,'strategy':'conservative same-entity grouping, not a claim every grouped pair is a duplicate'},
        'cost_filter':{'full':len(manifests['rl_train_full']['task_ids']),'pruned':len(pruned),'exclusions':len(exclusions),'default':'rl_train_full','savings_measured':False},
        'manifests':{name:{'count':len(m['task_ids']),'task_set_sha256':m['task_set_sha256']} for name,m in manifests.items()},
        'evaluation_budget':{'status':'PLAN_ONLY_NO_EPISODES','checkpoints':5,'pass1_tasks':len(manifests['rl_test_frozen']['task_ids']),
            'pass4_tasks':len(subset),'episodes_per_checkpoint':len(manifests['rl_test_frozen']['task_ids'])+3*len(subset),
            'episodes_five_checkpoints':5*(len(manifests['rl_test_frozen']['task_ids'])+3*len(subset))}}
    write_json(ROOT/'reports/stage2/split_statistics.json', stats)
    print(json.dumps({k:stats[k] for k in ('rl_counts','sft','global_groups','cost_filter','evaluation_budget')},ensure_ascii=False))


if __name__ == '__main__': main()
