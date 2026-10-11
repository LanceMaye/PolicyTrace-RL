"""Full Retail audit and private canonical dialogue evidence, no model calls."""
from collections import Counter, defaultdict
import json
from pathlib import Path

from policytrace.data.manifests import ROOT, RULE_VERSION, canonical, digest, file_hash, quantiles, read_json, write_json, write_jsonl, verify_sources
from policytrace.data.provenance import (actions_from_messages, business_labels, extract_entities,
    mutation_signature, normalize_text, overlap_candidates, same_source_groups, within_source_candidates)
from policytrace.data.sft_format import normalize_messages, semantic_messages, tool_validators, validate_calls
from policytrace.stage0.task_loader import iter_retail_records, load_retail_task
from policytrace.stage0.db_adapter import load_retail_db, make_retail_env
from tau2.domains.retail.environment import get_environment


def length_bucket(n, short, medium):
    return 'short' if n <= short else 'medium' if n <= medium else 'long'


def observed_initial_snapshots(messages, dbs):
    """Compare full observed entities before the first mutation; unknown stays unknown."""
    observations, wrote, queue = [], False, []
    for m in messages:
        for c in m.get('tool_calls', []):
            fn = c['function']
            if fn['name'] in {'modify_user_address', 'modify_pending_order_address', 'cancel_pending_order',
                'return_delivered_order_items', 'exchange_delivered_order_items', 'modify_pending_order_items', 'modify_pending_order_payment'}:
                wrote = True
            queue.append((fn['name'], fn['arguments'], wrote))
        if m['role'] != 'tool': continue
        j = next((j for j, item in enumerate(queue) if item[0] == m.get('name')), None)
        if j is None: continue
        name, args, after_write = queue.pop(j)
        if after_write or name not in {'get_user_details', 'get_order_details', 'get_product_details'}: continue
        try: result = json.loads(m['content'])
        except json.JSONDecodeError: continue
        if not isinstance(result, dict) or 'error' in result: continue
        table, key = {'get_user_details': ('users', 'user_id'), 'get_order_details': ('orders', 'order_id'),
                      'get_product_details': ('products', 'product_id')}[name]
        entity_id = args.get(key)
        if entity_id:
            observations.append((table, entity_id, digest(result)))
    if not observations: return [], []
    matches = [name for name, db in dbs.items() if all(
        eid in db[table] and digest(db[table][eid]) == h for table, eid, h in observations)]
    return sorted(matches), observations


def historical_exposure(root, valid_ids):
    """Scan source/tests/docs and historical reports/evidence; exclude Stage 2 itself."""
    import re
    hits = defaultdict(set)
    search = [root / p for p in ('scripts', 'tests/stage0', 'tests/stage1', 'docs',
                                'reports/stage0', 'reports/stage1', 'data/private/stage0', 'data/private/stage1')]
    for base in search:
        for path in base.rglob('*'):
            if not path.is_file() or path.suffix not in {'.py', '.md', '.json', '.jsonl', '.log', '.txt'}: continue
            if path.name.startswith('stage2_') or path.name in {'data_audit.md', 'cross_source_overlap.md',
                'data_split_protocol.md', 'rl_cost_filter.md', 'sft_preprocess.md', 'external_eval_audit.md'}: continue
            try: text = path.read_text(encoding='utf-8')
            except (UnicodeError, OSError): continue
            for tid in set(re.findall(r'\bretail_\d+\b', text)) & valid_ids:
                hits[tid].add(path.relative_to(root).as_posix())
    # Reproduce algorithmically selected fixture IDs, even if no literal whitelist exists.
    from policytrace.stage0.reference_check import select_tasks
    records = [load_retail_task(r, i) for i, r in iter_retail_records(root/'data/raw')]
    for r in select_tasks(records): hits[r.task.id].add('stage0.select_tasks(seed=42,limit=8)')
    return {k: sorted(v) for k, v in sorted(hits.items())}


def audit(root=ROOT):
    sources = verify_sources(root)
    private = root / 'data/private/stage2'
    private.mkdir(parents=True, exist_ok=True)
    env = get_environment()
    tools = [t.openai_schema for t in env.get_tools()]
    validators, cache = tool_validators(tools), {}
    write_json(private/'tools.json', tools)
    records = [load_retail_task(raw, i) for i, raw in iter_retail_records(root/'data/raw')]
    snapshots = {p: load_retail_db(p, root/'data/raw') for p in sorted({r.db_path for r in records})}
    dbs = {p: s.db.model_dump(mode='json') for p, s in snapshots.items()}
    rl, rl_errors = [], []
    action_counts, basis, init = Counter(), Counter(), Counter()
    for r in records:
        actions = [{'name': a.name, 'arguments': a.arguments} for a in r.task.evaluation_criteria.actions or []]
        errors = sorted({a['name'] for a in actions if a['name'] not in validators or not validators[a['name']].is_valid(a['arguments'])})
        if errors: rl_errors.append({'id': r.task.id, 'errors': ['tool_schema_error'], 'tools': errors})
        state = r.task.initial_state
        if state:
            # Reuse the actual environment initialization; do not emulate its state logic.
            make_retail_env(r, snapshots[r.db_path])
        init['present' if state else 'absent'] += 1
        instruction = r.task.user_scenario.instructions
        reason = instruction.reason_for_call
        text = canonical(r.task.user_scenario.model_dump(mode='json'))
        entities = extract_entities(actions, text)
        db = dbs[r.db_path]
        related = {table: {eid: db[table].get(eid) for eid in entities[kind]}
                   for table, kind in [('users', 'users'), ('orders', 'orders')]}
        criteria = r.task.evaluation_criteria.model_dump(mode='json')
        labels = business_labels(actions, reason)
        f = {'id': r.task.id, 'source_line': r.source_index, 'db_path': r.db_path,
             'snapshot_sha256': snapshots[r.db_path].file_sha256, 'reason': reason,
             'reason_hash': digest(normalize_text(reason)), 'entities': entities,
             'identity_hash': digest(entities['users'] or entities['emails']) if entities['users'] or entities['emails'] else None,
             'objects_hash': digest(entities['orders']) if entities['orders'] else None,
             'goal_hash': digest(mutation_signature(actions)) if mutation_signature(actions) else None,
             'constraints_hash': digest(r.task.user_scenario.model_dump(mode='json')),
             'completion_hash': digest(criteria), 'initial_state_hash': digest({'related': related, 'initial_state': state.model_dump(mode='json') if state else None}),
             'compatible_snapshots': [r.db_path], 'mutation_actions': mutation_signature(actions),
             'labels': labels, 'primary_type': labels[0], 'mutates': bool(mutation_signature(actions)),
             'communicate_nonempty': bool(r.task.evaluation_criteria.communicate_info),
             'reference_action_count': len(actions), 'reference_length_proxy': length_bucket(len(actions), 6, 9),
             'instance_fingerprint': digest({'scenario': r.task.user_scenario.model_dump(mode='json'),
                'criteria': criteria, 'initial_state': state.model_dump(mode='json') if state else None, 'related': related}),
             'task_payload_sha256': digest(r.task.model_dump(mode='json'))}
        rl.append(f); action_counts.update(a['name'] for a in actions)
        basis.update(x.value for x in r.task.evaluation_criteria.reward_basis)
    write_jsonl(private/'rl_features.jsonl', rl)

    domains, roles, answer_forms, metadata_types, qualities = Counter(), Counter(), Counter(), defaultdict(Counter), Counter()
    thinking = Counter(); tool_forms = Counter(); target_batches = Counter(); history_lengths, char_lengths, target_chars = [], [], []
    rows, dialogs, errors, duplicate_hashes = [], {}, [], defaultdict(list)
    row_schema_errors = Counter()
    total = 0
    with (private/'normalized_source.jsonl').open('w', encoding='utf-8', newline='\n') as output:
        with (root/'data/raw/tau2_sft_train.jsonl').open(encoding='utf-8') as stream:
            for line_no, line in enumerate(stream, 1):
                raw = json.loads(line); total += 1
                metadata = raw.get('metadata', {})
                did = metadata.get('source_dialog_id', '')
                domain = did.split('_')[0] if did.startswith(('retail_', 'airline_', 'telecom_')) else 'unprefixed_other'
                domains[domain] += 1
                if domain != 'retail': continue
                for k, v in metadata.items(): metadata_types[k][type(v).__name__] += 1
                qualities[str((metadata.get('correct'), metadata.get('reward')))] += 1
                for msg in raw['messages'] + [raw['answer']]:
                    roles[msg['role']] += 1
                    for k in ('thinking', 'reasoning'):
                        thinking[f'{k}_present'] += k in msg
                        thinking[f'{k}_nonempty'] += bool(msg.get(k))
                    for call in msg.get('tool_calls') or []: tool_forms[','.join(sorted(call))] += 1
                answer_forms['tool_call' if raw['answer'].get('tool_calls') else 'text'] += 1
                target_batches[str(len(raw['answer'].get('tool_calls') or []))] += 1
                sid = f'sft_line_{line_no}'
                issues = []
                try:
                    messages, answer, excluded = normalize_messages(raw['messages'], raw['answer'])
                    issues += validate_calls(messages + [answer], validators, cache)
                except ValueError as exc:
                    issues.append(str(exc)); messages, answer, excluded = [], None, []
                if not isinstance(metadata.get('turn_index'), int) or isinstance(metadata.get('turn_index'), bool): issues.append('invalid_turn_index')
                if metadata.get('correct') != 1 or metadata.get('reward') != 1.0: issues.append('source_quality_failed')
                record = {'sample_id': sid, 'source_line': line_no, 'source_dialog_id': did,
                    'turn_index': metadata.get('turn_index'), 'source_row_sha256': digest(raw),
                    'messages': messages, 'answer': answer, 'source_metadata': metadata,
                    'excluded_nonstudent_fields': excluded, 'issues': sorted(set(issues))}
                output.write(canonical(record) + '\n')
                semantic = semantic_messages(messages + [answer]) if answer is not None else []
                sample_hash = digest(semantic)
                duplicate_hashes[sample_hash].append(sid)
                c = sum(len(m['content']) + len(canonical(m.get('tool_calls', []))) for m in messages + ([answer] if answer else []))
                history_lengths.append(len(messages)); char_lengths.append(c)
                target_chars.append(len(answer['content']) if answer else 0)
                row = {k: record[k] for k in ('sample_id', 'source_line', 'source_dialog_id', 'turn_index', 'source_row_sha256', 'issues')}
                row.update(student_sample_hash=sample_hash, history_messages=len(messages), serialized_char_proxy=c)
                rows.append(row); row_schema_errors.update(x for x in issues if x != 'source_quality_failed')
                if issues: errors.append({'sample_id': sid, 'source_dialog_id': did, 'issues': issues})
                d = dialogs.setdefault(did, {'id': did, 'row_ids': [], 'turn_indices': [], 'issues': [],
                    'scenario_ids': set(), 'reasons': set(), 'quality_values': set(), 'prefixes': []})
                d['row_ids'].append(sid); d['turn_indices'].append(metadata.get('turn_index'))
                d['scenario_ids'].add(metadata.get('scenario_id')); d['reasons'].add(metadata.get('reason_for_call'))
                d['quality_values'].add((metadata.get('correct'), metadata.get('reward')))
                d['issues'].extend(issues); d['prefixes'].append((sid, semantic))
                if semantic and len(semantic) > len(d.get('canonical_dialogue', [])):
                    d['canonical_dialogue'] = semantic
                    d['messages'] = messages + [answer]
    dialog_features, consistency = [], Counter()
    for did, d in sorted(dialogs.items()):
        indices = d['turn_indices']; full = d.get('canonical_dialogue', [])
        issues = set(d['issues'])
        if len(indices) != len(set(indices)): issues.add('duplicate_turn_index')
        # Missing expert targets can occur in the source; do not discard valid
        # remaining turns or manufacture supervision for the absent turns.
        warnings = ['missing_turn_index'] if sorted(indices) != list(range(max(indices)+1)) else []
        if len(d['scenario_ids']) != 1 or len(d['reasons']) != 1 or len(d['quality_values']) != 1: issues.add('inconsistent_source_metadata')
        for sid, sequence in d['prefixes']:
            if sequence != full[:len(sequence)]: issues.add('history_prefix_mismatch')
        consistency.update(list(issues) + warnings)
        messages = d.get('messages', [])
        actions = actions_from_messages(messages)
        reason = sorted(x for x in d['reasons'] if isinstance(x, str))[0] if d['reasons'] else ''
        entities = extract_entities(actions, '\n'.join(m['content'] for m in messages if m['role'] != 'system'))
        compatible, observations = observed_initial_snapshots(messages, dbs)
        labels = business_labels(actions, reason)
        f = {'id': did, 'row_ids': sorted(d['row_ids']), 'turn_count': len(indices), 'issues': sorted(issues), 'warnings': warnings,
             'scenario_ids': sorted(d['scenario_ids']), 'reason': reason, 'reason_hash': digest(normalize_text(reason)),
             'entities': entities, 'identity_hash': digest(entities['users'] or entities['emails']) if entities['users'] or entities['emails'] else None,
             'objects_hash': digest(entities['orders']) if entities['orders'] else None,
             'goal_hash': digest(mutation_signature(actions)) if mutation_signature(actions) else None,
             'constraints_hash': None, 'completion_hash': None, 'initial_state_hash': None,
             'compatible_snapshots': compatible, 'observed_initial_entities': observations,
             'mutation_actions': mutation_signature(actions), 'labels': labels, 'primary_type': labels[0],
             'length_bucket': length_bucket(len(indices), 9, 13), 'tool_calls': len(actions),
             'student_dialogue_hash': digest(full), 'messages': messages,
             'quality': [list(x) for x in sorted(d['quality_values'])]}
        dialog_features.append(f)
    if len(records) != 563 or len(rows) != 11395 or len(dialogs) != 1000:
        raise ValueError('Unexpected raw counts: investigate before splitting')
    write_jsonl(private/'sft_rows.jsonl', rows)
    write_jsonl(private/'dialog_features.jsonl', dialog_features)
    write_jsonl(private/'quality_exclusions.jsonl', errors)
    overlap = overlap_candidates(rl, dialog_features)
    write_jsonl(private/'overlap_candidates.jsonl', overlap)
    within_rl, within_sft = within_source_candidates(rl), within_source_candidates(dialog_features)
    write_jsonl(private/'within_rl_candidates.jsonl',within_rl)
    write_jsonl(private/'within_sft_candidates.jsonl',within_sft)
    exposure = historical_exposure(root, {r['id'] for r in rl})
    write_json(private/'known_exposed.json', exposure)
    duplicate_rows = [ids for ids in duplicate_hashes.values() if len(ids) > 1]
    write_json(private/'duplicate_groups.json', {'sft_rows': duplicate_rows,
        'sft_dialogues': same_source_groups(dialog_features, 'student_dialogue_hash'),
        'rl_tasks': same_source_groups(rl, 'instance_fingerprint')})
    report = {'version': RULE_VERSION, 'status': 'PASS', 'execution': 'full_local_read_not_stage0_spotcheck', 'sources': sources,
        'private_artifacts': {name: file_hash(private/name) for name in ('rl_features.jsonl', 'sft_rows.jsonl',
            'dialog_features.jsonl', 'overlap_candidates.jsonl', 'known_exposed.json', 'duplicate_groups.json', 'normalized_source.jsonl','tools.json',
            'within_rl_candidates.jsonl','within_sft_candidates.jsonl')},
        'upstream': {'tool_schema_sha256': digest(tools), 'policy_sha256': digest(env.get_policy()), 'tool_count': len(tools)},
        'rl': {'retail': len(rl), 'unique_ids': len({r['id'] for r in rl}), 'schema_errors': rl_errors,
            'snapshot_counts': dict(Counter(r['db_path'] for r in rl)), 'primary_types': dict(Counter(r['primary_type'] for r in rl)),
            'mutates': dict(Counter(str(r['mutates']) for r in rl)), 'communicate_nonempty': dict(Counter(str(r['communicate_nonempty']) for r in rl)),
            'reference_action_count': quantiles([r['reference_action_count'] for r in rl]), 'length_proxy_buckets': dict(Counter(r['reference_length_proxy'] for r in rl)),
            'length_proxy_thresholds': {'short_max': 6, 'medium_max': 9, 'meaning': 'reference_action_count_NOT_episode_length'},
            'action_names': dict(action_counts), 'reward_basis': dict(basis), 'initial_state': dict(init),
            'exact_instance_duplicate_groups': len(same_source_groups(rl, 'instance_fingerprint'))},
        'sft': {'total_all_domains': total, 'domains': dict(domains), 'retail_turns': len(rows), 'source_dialogues': len(dialogs),
            'metadata_types': dict(metadata_types), 'quality_rows': dict(qualities), 'source_dialogues_quality_failed': sum('source_quality_failed' in d['issues'] for d in dialog_features),
            'role_counts_including_repeated_histories': dict(roles), 'answer_forms': dict(answer_forms), 'tool_call_forms': dict(tool_forms),
            'thinking_reasoning': dict(thinking), 'format_error_rows': dict(row_schema_errors), 'dialogue_consistency_issues': dict(consistency),
            'target_tool_batch_sizes':dict(target_batches),
            'targets_with_multiple_tool_calls':sum(v for k,v in target_batches.items() if int(k)>1),
            'source_policy_normalized_equal_current': normalize_text(dialog_features[0]['messages'][0]['content'].split('<policy>')[-1].split('</policy>')[0]) == normalize_text(env.get_policy()),
            'turn_count': quantiles([d['turn_count'] for d in dialog_features]), 'history_message_count': quantiles(history_lengths),
            'serialized_char_proxy': quantiles(char_lengths), 'target_text_chars': quantiles(target_chars),
            'length_buckets': dict(Counter(d['length_bucket'] for d in dialog_features)), 'length_thresholds': {'short_max_turns': 9, 'medium_max_turns': 13},
            'compatible_initial_snapshots': dict(Counter(str(len(d['compatible_snapshots'])) for d in dialog_features)),
            'exact_sample_duplicate_groups': len(duplicate_rows), 'exact_sample_duplicate_excess_rows': sum(len(x)-1 for x in duplicate_rows),
            'exact_dialogue_duplicate_groups': len(same_source_groups(dialog_features, 'student_dialogue_hash')),
            'primary_types': dict(Counter(d['primary_type'] for d in dialog_features))},
        'overlap': {'candidate_pairs': len(overlap), 'classification_counts': dict(Counter(e['classification'] for e in overlap)),
            'rule_counts': dict(Counter(e['rule_id'] for e in overlap)), 'rl_tasks_with_candidates': len({e['task_id'] for e in overlap}),
            'rl_tasks_probable': len({e['task_id'] for e in overlap if e['classification'] == 'probable_same_instance'}),
            'sft_dialogues_probable': len({e['source_dialog_id'] for e in overlap if e['classification'] == 'probable_same_instance'}),
            'all_pair_universe': len(rl)*len(dialog_features), 'retrieval': 'exact customer/email/order, normalized exact reason, top3 local word-Jaccard>=0.50; product ID alone excluded',
            'private_constraints_available_in_sft': False, 'independence_claim': 'not_proven_for_all_possible_paraphrases'},
        'within_source':{name:{'candidate_pairs':len(es),'classification_counts':dict(Counter(e['classification'] for e in es)),
            'rule_counts':dict(Counter(e['rule_id'] for e in es))} for name,es in [('rl',within_rl),('sft',within_sft)]},
        'known_exposed': {'count': len(exposure), 'task_ids': sorted(exposure), 'private_evidence': 'data/private/stage2/known_exposed.json'},
        'snapshots': {p: {'sha256': s.file_sha256, 'content_hash': s.content_hash, **s.db.get_statistics()} for p, s in snapshots.items()}}
    write_json(root/'reports/stage2/source_audit.json', report)
    return report
