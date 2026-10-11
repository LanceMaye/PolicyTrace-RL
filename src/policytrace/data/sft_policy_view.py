"""Reversible target filtering; never rewrite policies, messages, or token arrays."""
from collections import Counter
from contextlib import ExitStack
import gzip
import hashlib
import json
from itertools import zip_longest
from pathlib import Path

from policytrace.data.manifests import digest, file_hash
from policytrace.data.sft_tokenize import validate_labels

RULE_VERSION = 'policytrace-sft-target-policy-v1'


def target_reasons(answer, *, max_tool_calls=1):
    """Only supervised Target is gated; masked historical actions are annotated."""
    if answer.get('role') != 'assistant':
        raise ValueError('Expected assistant target')
    content = answer.get('content') or ''
    calls = answer.get('tool_calls') or []
    if not isinstance(content, str) or not isinstance(calls, list):
        raise ValueError('Invalid target structure')
    reasons = []
    if max_tool_calls is not None and len(calls) > max_tool_calls:
        reasons.append('multiple_tool_calls')
    if calls and content.strip():
        reasons.append('text_and_tool_calls')
    return reasons


def partition_split(source_rows, source_tokens, output_dir, split, eos, *,
                    max_tool_calls=1, rule_version=RULE_VERSION):
    """Pair by exact provenance, copy original UTF-8 lines, and validate every mask.

    A filtered target does not remove its dialog's other targets. No turn is
    moved across train/val. Quarantine contains the unchanged complete target.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    counts = Counter(); reasons = Counter(); ids = {'main': [], 'quarantine': []}
    dialogs = {'main': set(), 'quarantine': set()}; seen = set(); decisions = []
    tools = {view: Counter() for view in ids}
    paths = {view: {'rows': output_dir/f'sft_{split}_{view}.jsonl',
                    'tokens': output_dir/f'sft_{split}_{view}.tokenized.jsonl.gz'} for view in ids}
    with ExitStack() as stack:
        outputs = {}
        for view, entries in paths.items():
            outputs[(view,'rows')] = stack.enter_context(entries['rows'].open('wb'))
            binary = stack.enter_context(entries['tokens'].open('wb'))
            outputs[(view,'tokens')] = stack.enter_context(gzip.GzipFile(
                filename='', mode='wb', fileobj=binary, mtime=0, compresslevel=3))
        rows = stack.enter_context(Path(source_rows).open('rb'))
        tokens = stack.enter_context(gzip.open(source_tokens,'rb'))
        for row_line, token_line in zip_longest(rows, tokens):
            if row_line is None or token_line is None:
                raise ValueError('Source row/token counts differ')
            row, token = json.loads(row_line), json.loads(token_line)
            provenance = row['provenance']; sid = provenance['sample_id']
            if token['provenance'] != provenance or sid in seen:
                raise ValueError('Source token provenance mismatch or duplicate ID')
            seen.add(sid)
            validate_labels(token,eos)
            why = target_reasons(row['answer'], max_tool_calls=max_tool_calls)
            view = 'quarantine' if why else 'main'
            outputs[(view,'rows')].write(row_line)
            outputs[(view,'tokens')].write(token_line)
            ids[view].append(sid); dialogs[view].add(provenance['source_dialog_id'])
            counts[view] += 1
            counts[view+'_input_tokens'] += len(token['input_ids'])
            counts[view+'_supervised_tokens'] += token['supervised_tokens']
            calls = row['answer'].get('tool_calls') or []
            counts[view+'_text_targets'] += not bool(calls)
            counts[view+'_single_tool_targets'] += len(calls)==1
            tools[view].update(c['function']['name'] for c in calls)
            counts['multi_targets'] += len(calls)>1
            counts['mixed_targets'] += 'text_and_tool_calls' in why
            counts['both_reasons'] += len(calls)>1 and 'text_and_tool_calls' in why
            reasons.update(why)
            historical = [target_reasons(m,max_tool_calls=max_tool_calls) for m in row['messages'] if m['role']=='assistant']
            history_flags = sorted({r for flags in historical for r in flags})
            counts[view+'_history_rule_flags'] += bool(history_flags)
            decisions.append({'provenance':provenance, 'source_split':split, 'view':view,
                              'target_reasons':why,'history_flags':history_flags,
                              'row_line_sha256':hashlib.sha256(row_line).hexdigest(),
                              'token_line_sha256':hashlib.sha256(token_line).hexdigest()})
    if set(ids['main']) & set(ids['quarantine']) or len(seen)!=sum(len(v) for v in ids.values()):
        raise ValueError('Partition is not exhaustive and disjoint')
    artifacts = {view:{kind:{'path':str(p),'sha256':file_hash(p),'size_bytes':p.stat().st_size}
                      for kind,p in entries.items()} for view,entries in paths.items()}
    manifest = {'split':split, 'rule_version':rule_version, 'counts':dict(counts),
                'reason_counts':dict(reasons), 'sample_ids':ids,
                'sample_id_sha256':{view:digest(sids) for view,sids in ids.items()},
                'source_dialog_ids':{view:sorted(dids) for view,dids in dialogs.items()},
                'target_tool_call_counts':{view:dict(c) for view,c in tools.items()},
                'artifacts':artifacts,'token_strategy':'copy_original_decompressed_lines_without_retokenization',
                'mask_samples_checked':len(seen),'source_row_token_alignment':'PASS'}
    return manifest, decisions
