"""Read fixed-fork Retail Test tasks and audit source risk; never run episodes."""
from collections import Counter
import json

from policytrace.data.manifests import ROOT, digest, file_hash, read_jsonl, write_json, write_jsonl
from policytrace.data.provenance import extract_entities, business_labels, mutation_signature, normalize_text, overlap_candidates
from policytrace.data.sft_format import tool_validators
from policytrace.stage0 import db_adapter  # sets upstream asset root before imports
from tau2.data_model.tasks import Task
from tau2.domains.retail.environment import get_environment


def main():
    base = ROOT/'external/tau2-bench/data/tau2/domains/retail'
    tasks = json.loads((base/'tasks.json').read_text(encoding='utf-8'))
    split = json.loads((base/'split_tasks.json').read_text(encoding='utf-8'))
    selected = set(split['test'])
    if len(selected) != len(split['test']): raise ValueError('Duplicate external test IDs')
    env = get_environment(); db = env.tools.db.model_dump(mode='json') if hasattr(env,'tools') else json.loads((base/'db.json').read_text())
    tools = [t.openai_schema for t in env.get_tools()]; validators = tool_validators(tools)
    features, schema_errors = [], []
    for raw in tasks:
        if raw['id'] not in selected: continue
        task = Task.model_validate(raw)
        actions = [{'name':a.name,'arguments':a.arguments} for a in task.evaluation_criteria.actions or []]
        for action in actions:
            if action['name'] not in validators or not validators[action['name']].is_valid(action['arguments']):
                schema_errors.append({'id':task.id,'code':'external_tool_schema_error'})
        scenario = task.user_scenario.model_dump(mode='json')
        entities = extract_entities(actions, json.dumps(scenario))
        related = {table:{eid:db[table].get(eid) for eid in entities[kind]} for table,kind in [('users','users'),('orders','orders')]}
        reason = task.user_scenario.instructions.reason_for_call
        criteria = task.evaluation_criteria.model_dump(mode='json')
        features.append({'id':'external_retail_'+task.id,'original_task_id':task.id,'entities':entities,
            'labels':business_labels(actions,reason),'reason':reason,'reason_hash':digest(normalize_text(reason)),
            'identity_hash':digest(entities['users'] or entities['emails']) if entities['users'] or entities['emails'] else None,
            'objects_hash':digest(entities['orders']) if entities['orders'] else None,
            'goal_hash':digest(mutation_signature(actions)) if mutation_signature(actions) else None,
            'constraints_hash':digest(scenario),'completion_hash':digest(criteria),
            'initial_state_hash':digest({'related':related,'initial_state':task.initial_state.model_dump(mode='json') if task.initial_state else None}),
            'compatible_snapshots':['fixed-fork-retail-default-db'], 'mutation_actions':mutation_signature(actions),
            'task_payload_sha256':digest(task.model_dump(mode='json'))})
    if {r['original_task_id'] for r in features} != selected: raise ValueError('External split IDs missing from tasks')
    private = ROOT/'data/private/stage2'
    rl, sft = list(read_jsonl(private/'rl_features.jsonl')), list(read_jsonl(private/'dialog_features.jsonl'))
    overlaps = overlap_candidates(features, rl+sft)
    write_jsonl(private/'external_overlap_candidates.jsonl', overlaps)
    write_json(private/'external_test_candidate.json', {'status':'EXTERNAL_EVAL_CANDIDATE_CONTAMINATION_RISK',
        'independence':'UNPROVEN_NO_SEED_TASK_LINEAGE', 'entries':[{'id':f['id'],'original_task_id':f['original_task_id'],
            'task_payload_sha256':f['task_payload_sha256'],'db_path':'external/tau2-bench/data/tau2/domains/retail/db.json',
            'snapshot_sha256':file_hash(base/'db.json')} for f in features],
            'task_ids':sorted(f['id'] for f in features), 'task_set_sha256':digest(sorted(f['id'] for f in features))})
    report = {'audit_status':'PASS', 'evaluation_status':'EXTERNAL_EVAL_CANDIDATE/CONTAMINATION_RISK',
        'formal_external_evaluation':'BLOCKED_PENDING_LINEAGE_AND_PROTOCOL_REVIEW',
        'actual_task_file_count':len(tasks),'actual_test_count':len(selected),'actual_train_count':len(split.get('train',[])),
        'sources':{name:file_hash(base/name) for name in ('tasks.json','split_tasks.json','db.json','policy.md')},
        'tool_schema_errors':schema_errors, 'candidate_pairs':len(overlaps),
        'classification_counts':dict(Counter(e['classification'] for e in overlaps)),
        'candidates_by_project_source':dict(Counter('RL' if e['source_dialog_id'].startswith('retail_') and not e['source_dialog_id'].startswith('retail_dialog_') else 'SFT' for e in overlaps)),
        'rule_counts':dict(Counter(e['rule_id'] for e in overlaps)), 'same_reason_pairs':sum(e['same_reason'] for e in overlaps),
        'shared_entity_pairs':sum(e['shared_entity_count']>0 for e in overlaps),
        'limitations':['AReaL metadata has no verified original seed-task lineage.',
            'Current fixed fork is the audited source, not proof of the latest official benchmark.',
            'Default DB/policy/User Simulator protocol require a separately versioned run.',
            'External scores must be separate from internal Pass1/Pass4; no leaderboard equivalence claim.'],
        'episodes_run':0,'manifest':'data/private/stage2/external_test_candidate.json'}
    write_json(ROOT/'reports/stage2/external_eval_audit.json',report)
    print(json.dumps({k:report[k] for k in ('audit_status','evaluation_status','actual_test_count','candidate_pairs','classification_counts','shared_entity_pairs')}))


if __name__ == '__main__': main()
