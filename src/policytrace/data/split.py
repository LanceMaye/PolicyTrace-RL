"""Global provenance grouping before deterministic marginal stratification."""
from collections import Counter, defaultdict
import random

from policytrace.data.manifests import digest
from policytrace.data.provenance import entity_keys


class UnionFind:
    def __init__(self, keys): self.parent = {key: key for key in keys}

    def find(self, key):
        while key != self.parent[key]:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def union(self, left, right):
        left, right = self.find(left), self.find(right)
        if left != right: self.parent[max(left, right)] = min(left, right)


def provenance_groups(rl, dialogs, duplicate_groups, overlap):
    nodes = ['rl:' + r['id'] for r in rl] + ['sft:' + d['id'] for d in dialogs]
    union = UnionFind(nodes)
    # Conservative grouping is a leakage guard, NOT a duplicate declaration.
    # Shared customer/order cases remain grouped even when goals differ.
    index = defaultdict(list)
    for prefix, records in [('rl:', rl), ('sft:', dialogs)]:
        for f in records:
            for key in entity_keys(f): index[key].append(prefix + f['id'])
    for ids in index.values():
        for nid in ids[1:]: union.union(ids[0], nid)
    for key, prefix in [('rl_tasks', 'rl:'), ('sft_dialogues', 'sft:')]:
        for ids in duplicate_groups[key]:
            for nid in ids[1:]: union.union(prefix + ids[0], prefix + nid)
    for e in overlap:
        if e['classification'] in {'confirmed_same_instance', 'probable_same_instance'}:
            union.union('rl:' + e['task_id'], 'sft:' + e['source_dialog_id'])
    groups = defaultdict(list)
    for node in sorted(nodes): groups[union.find(node)].append(node)
    return sorted(groups.values(), key=lambda g: g[0])


def marginals(features):
    out = Counter()
    for r in features:
        for field in ('primary_type', 'db_path', 'reference_length_proxy', 'mutates', 'communicate_nonempty'):
            out[f'{field}={r[field]}'] += 1
    return out


def assign_rl_groups(groups, rl, dialogs, exposed, seed=42, ratios=(.70, .15, .15)):
    by_rl = {r['id']: r for r in rl}
    by_sft = {d['id']: d for d in dialogs}
    n = len(rl)
    targets = {'train': round(n*ratios[0]), 'dev': round(n*ratios[1])}
    targets['test'] = n-targets['train']-targets['dev']
    totals = marginals(rl)
    counts = Counter(); cells = {s: Counter() for s in targets}
    assignment, records = {}, []
    rng = random.Random(seed)
    ordered = []
    for group in groups:
        ids = [node[3:] for node in group if node.startswith('rl:')]
        if not ids: continue
        ds = [node[4:] for node in group if node.startswith('sft:')]
        forced = 'dev' if set(ids) & set(exposed) else None
        # Preserve usable SFT and keep unresolved cross-source cases out of Test.
        if forced is None and any(not by_sft[d]['issues'] for d in ds): forced = 'train'
        group_features = [by_rl[tid] for tid in ids]
        ordered.append((forced, rng.random(), group, group_features, ds))
    ordered.sort(key=lambda item: (item[0] is None, -len(item[3]), item[1]))
    ratio_by_split = dict(zip(('train', 'dev', 'test'), ratios))
    for forced, tie, group, features, ds in ordered:
        group_cells = marginals(features)
        def score(split):
            # Delta in squared deviation for total count and each marginal.
            # No high-dimensional cross-product strata; sparse classes stay visible.
            old = counts[split]-targets[split]
            value = 8 * ((old+len(features))**2-old**2) / max(1, targets[split])
            for key, amount in group_cells.items():
                target = totals[key]*ratio_by_split[split]
                old = cells[split][key]-target
                value += ((old+amount)**2-old**2)/max(1, target)
            return value
        split = forced or min(targets, key=lambda s: (score(s), s))
        counts[split] += len(features); cells[split].update(group_cells)
        for r in features: assignment[r['id']] = split
        records.append({'group_id': digest(group), 'nodes': group, 'rl_split': split,
                        'forced_reason': 'known_exposed' if forced == 'dev' else 'preserve_sft_and_isolate_cross_source' if forced else None})
    return assignment, records, targets


def assign_sft_groups(groups, dialogs, rl_assignment, seed=42, val_fraction=.10):
    by_id = {d['id']: d for d in dialogs}
    assignment, forced_val, free = {}, [], []
    rng = random.Random(seed+1)
    for group in groups:
        ds = [node[4:] for node in group if node.startswith('sft:')]
        if not ds: continue
        rs = {rl_assignment[node[3:]] for node in group if node.startswith('rl:')}
        if len(rs) > 1: raise ValueError('A provenance group spans RL splits')
        valid = [did for did in ds if not by_id[did]['issues']]
        for did in ds:
            if by_id[did]['issues']: assignment[did] = 'quality_excluded'
        if not valid: continue
        if rs == {'test'}:
            for did in valid: assignment[did] = 'heldout_from_sft'
        elif rs == {'train'}:
            for did in valid: assignment[did] = 'train'
        elif rs == {'dev'}:
            forced_val.append(valid)
        else:
            free.append((rng.random(), valid))
    for ids in forced_val:
        for did in ids: assignment[did] = 'val'
    target = round(sum(not d['issues'] for d in dialogs)*val_fraction)
    val_counts = Counter()
    total_types = Counter(d['primary_type'] for d in dialogs if not d['issues'])
    total_lengths = Counter(d['length_bucket'] for d in dialogs if not d['issues'])
    for did, split in assignment.items():
        if split == 'val':
            val_counts['total'] += 1
            val_counts['type:'+by_id[did]['primary_type']] += 1
            val_counts['length:'+by_id[did]['length_bucket']] += 1
    for tie, ids in sorted(free, key=lambda pair: (-len(pair[1]), pair[0])):
        def increment_score():
            cell = Counter({'total': len(ids)})
            cell.update('type:'+by_id[d]['primary_type'] for d in ids)
            cell.update('length:'+by_id[d]['length_bucket'] for d in ids)
            targets = {'total': target} | {'type:'+k:v*val_fraction for k,v in total_types.items()} | {'length:'+k:v*val_fraction for k,v in total_lengths.items()}
            return sum((8 if k == 'total' else 1)*((val_counts[k]+v-targets[k])**2-(val_counts[k]-targets[k])**2)/max(1,targets[k]) for k,v in cell.items())
        selected = increment_score() < 0
        for did in ids: assignment[did] = 'val' if selected else 'train'
        if selected:
            val_counts['total'] += len(ids)
            val_counts.update('type:'+by_id[d]['primary_type'] for d in ids)
            val_counts.update('length:'+by_id[d]['length_bucket'] for d in ids)
    return assignment


def select_pass4(test_features, limit=50, seed=44):
    """Stratified deterministic marginal subset without inspecting any model result."""
    n = min(limit, len(test_features))
    totals = marginals(test_features); cells = Counter()
    rng = random.Random(seed)
    ordered = sorted(test_features, key=lambda r: r['id']); rng.shuffle(ordered)
    chosen = []
    while len(chosen) < n:
        def score(r):
            c = marginals([r])
            return sum(((cells[k]+v-totals[k]*n/max(1,len(test_features)))**2-(cells[k]-totals[k]*n/max(1,len(test_features)))**2)/max(1, totals[k]*n/max(1,len(test_features))) for k,v in c.items())
        best = min(ordered, key=score)
        chosen.append(best); cells.update(marginals([best])); ordered.remove(best)
    return sorted(r['id'] for r in chosen)


def validate_isolation(groups, rl_assignment, sft_assignment, exposed):
    if any(rl_assignment[tid] == 'test' for tid in exposed): raise ValueError('Historical exposure in Test')
    for group in groups:
        rs = {rl_assignment[n[3:]] for n in group if n.startswith('rl:')}
        ss = {sft_assignment[n[4:]] for n in group if n.startswith('sft:')} - {'quality_excluded', 'heldout_from_sft'}
        if len(rs) > 1 or len(ss) > 1: raise ValueError('Group leakage')
        if 'test' in rs and ss: raise ValueError('SFT model-use/Test collision')
        if 'dev' in rs and 'train' in ss: raise ValueError('SFT gradient/Dev collision')
        if 'train' in rs and 'val' in ss: raise ValueError('SFT Val/RL Train collision')
