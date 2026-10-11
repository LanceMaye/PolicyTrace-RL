"""Full RL schema/path audit and SFT structural spot check, never data cleaning."""
import argparse
from collections import Counter, defaultdict
import json
import hashlib
from pathlib import Path

from policytrace.stage0.task_loader import load_retail_task
from policytrace.stage0.db_adapter import load_retail_db, resolve_db_path
from tau2.domains.retail.environment import get_environment
from jsonschema import Draft202012Validator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', type=Path, default=Path('data/raw'))
    args = parser.parse_args()
    root = args.data_root
    report = {'rl': {}, 'sft': {}, 'snapshots': {}, 'errors': []}
    environment = get_environment()
    schemas = {tool.name:tool.openai_schema['function']['parameters'] for tool in environment.get_tools()}
    validators = {name:Draft202012Validator(schema) for name,schema in schemas.items()}
    report['upstream_interface'] = {'tool_count':len(schemas), 'tool_names':sorted(schemas),
        'tool_schema_sha256':hashlib.sha256(json.dumps(schemas,sort_keys=True).encode()).hexdigest(),
        'policy_text_sha256':hashlib.sha256(environment.get_policy().encode()).hexdigest()}
    domains, paths, ids = Counter(), Counter(), Counter()
    fields = defaultdict(Counter)
    action_types, reward_basis = Counter(), Counter()
    raw_count = 0
    retail_count = 0
    for index, line in enumerate((root/'tau2_rl_train.jsonl').open(encoding='utf-8'), 1):
        raw = json.loads(line)
        raw_count += 1
        domain = raw['id'].split('_')[0]
        domains[domain] += 1
        if domain != 'retail':
            continue
        retail_count += 1
        ids[raw['id']] += 1
        for key, value in raw.items():
            fields[key][type(value).__name__] += 1
        try:
            record = load_retail_task(raw, index)
            resolve_db_path(record.db_path, root)
            paths[record.db_path] += 1
            action_types.update(a.name for a in record.task.evaluation_criteria.actions or [])
            for action in record.task.evaluation_criteria.actions or []:
                if action.name not in validators or not validators[action.name].is_valid(action.arguments):
                    report['errors'].append({'line':index, 'task_id':raw['id'], 'error_type':'ToolSchemaMismatch', 'tool':action.name})
            reward_basis.update(x.value for x in record.task.evaluation_criteria.reward_basis)
        except Exception as exc:
            report['errors'].append({'line': index, 'task_id': raw['id'], 'error_type': type(exc).__name__})
    for path in sorted(paths):
        snapshot = load_retail_db(path, root)
        report['snapshots'][path] = {'sha256': snapshot.file_sha256, 'content_hash': snapshot.content_hash, **snapshot.db.get_statistics()}
    report['rl'] = {'total': raw_count, 'domains': dict(domains), 'retail': retail_count, 'unique_retail_ids': len(ids),
                    'duplicates': {k:v for k,v in ids.items() if v>1}, 'db_paths': dict(paths),
                    'field_types': dict(fields), 'action_names': dict(action_types), 'reward_basis': dict(reward_basis)}
    domains, dialogs, fields = Counter(), set(), defaultdict(Counter)
    sample_indices, shapes = [], []
    for index, line in enumerate((root/'tau2_sft_train.jsonl').open(encoding='utf-8'), 1):
        raw = json.loads(line)
        dialog = raw.get('metadata', {}).get('source_dialog_id', '')
        domain = dialog.split('_')[0] if dialog.startswith(('retail_', 'airline_', 'telecom_')) else 'unprefixed_other'
        domains[domain] += 1
        if domain != 'retail':
            continue
        dialogs.add(dialog)
        if len(sample_indices) >= 100:
            continue
        sample_indices.append(index)
        for key, value in raw.items():
            fields[key][type(value).__name__] += 1
        valid = isinstance(raw.get('messages'), list) and isinstance(raw.get('answer'), dict) and isinstance(raw.get('metadata'), dict)
        valid = valid and raw['answer'].get('role') == 'assistant' and all(isinstance(m,dict) and 'role' in m for m in raw['messages'])
        if not valid:
            report['errors'].append({'split':'sft', 'line':index, 'error_type':'InvalidStructure'})
        if len(shapes) < 3:
            shapes.append({'line':index, 'messages_count':len(raw['messages']), 'message_roles':dict(Counter(m['role'] for m in raw['messages'])),
                           'answer_fields':{k:type(v).__name__ for k,v in raw['answer'].items()},
                           'metadata_fields':{k:type(v).__name__ for k,v in raw['metadata'].items()}})
    report['sft'] = {'total':sum(domains.values()), 'domains':dict(domains), 'retail_unique_source_dialogs':len(dialogs),
                     'sample_policy':'first 100 Retail rows in original file order; full-file counts only',
                     'sample_indices':sample_indices,'field_types':dict(fields), 'example_shapes':shapes}
    report['status'] = 'PASS' if not report['errors'] and not report['rl']['duplicates'] else 'FAIL'
    out = Path('reports/stage0/data_audit.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'status':report['status'], 'rl':report['rl']['domains'], 'sft':report['sft']['domains'], 'errors':len(report['errors'])}))
    if report['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
