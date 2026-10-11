"""Conservative instance evidence. Missing evidence is never equality."""
from collections import defaultdict
import re
import unicodedata

from policytrace.data.manifests import digest
from policytrace.stage0.reference_check import MUTATIONS

BUSINESS_TOOLS = {
    'modify_user_address': 'account_address', 'modify_pending_order_address': 'order_address',
    'cancel_pending_order': 'cancel', 'return_delivered_order_items': 'return',
    'exchange_delivered_order_items': 'exchange', 'modify_pending_order_items': 'items',
    'modify_pending_order_payment': 'payment', 'transfer_to_human_agents': 'human_transfer',
}


def normalize_text(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def tokens(text):
    return set(re.findall(r'[a-z0-9_@]+', normalize_text(text)))


def actions_from_messages(messages):
    return [c['function'] for m in messages for c in m.get('tool_calls', [])]


def business_labels(actions, reason=''):
    labels = sorted({BUSINESS_TOOLS[a['name']] for a in actions if a['name'] in BUSINESS_TOOLS})
    if not labels:
        text = normalize_text(reason)
        labels = ['policy_refusal'] if any(w in text for w in ('cannot', 'not allowed', 'ineligible', 'refuse')) else ['readonly_query']
    return labels


def extract_entities(actions, text=''):
    """Only customers/emails/orders are retrieval keys; shared product IDs are not."""
    users, orders, emails = set(), set(), set()
    for action in actions:
        args = action['arguments']
        if isinstance(args.get('user_id'), str): users.add(args['user_id'])
        if isinstance(args.get('order_id'), str): orders.add(args['order_id'].lstrip('#'))
        if isinstance(args.get('email'), str): emails.add(args['email'].casefold())
    users.update(value for value in re.findall(r'\b[a-z]+_[a-z]+_\d+\b', text.casefold())
                 if not value.startswith(('gift_card_', 'credit_card_')))
    orders.update(re.findall(r'#(\d{5,})\b', text))
    emails.update(re.findall(r'\b[a-z0-9_.+-]+@[a-z0-9.-]+\.[a-z]{2,}\b', text.casefold()))
    return {'users': sorted(users), 'orders': sorted(orders), 'emails': sorted(emails)}


def entity_keys(feature):
    return {f'{kind}:{value}' for kind, values in feature['entities'].items() for value in values}


def mutation_signature(actions):
    # Preserve order and multiplicity, exact parameters and country spellings.
    return [a for a in actions if a['name'] in MUTATIONS]


def classify_pair(left, right):
    """Generic strict classifier, also exercised on synthetic complete evidence."""
    shared = entity_keys(left) & entity_keys(right)
    required = ('identity_hash', 'objects_hash', 'goal_hash', 'constraints_hash',
                'completion_hash', 'initial_state_hash')
    def known_hash(value):
        return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None
    if all(known_hash(left.get(k)) and known_hash(right.get(k)) for k in required):
        if all(left[k] == right[k] for k in required):
            return 'confirmed_same_instance', 'complete_multidimensional_equality'
        if left['identity_hash'] != right['identity_hash'] or left['objects_hash'] != right['objects_hash']:
            return ('same_business_pattern_only' if set(left['labels']) & set(right['labels']) else 'distinct_or_unknown',
                    'different_entities')
        return 'distinct_or_unknown', 'conflicting_complete_evidence'
    compatible_initial = bool(set(left.get('compatible_snapshots', [])) & set(right.get('compatible_snapshots', [])))
    exact_goal = bool(left.get('mutation_actions')) and left.get('mutation_actions') == right.get('mutation_actions')
    if shared and exact_goal and compatible_initial:
        return 'probable_same_instance', 'same_entities_mutation_parameters_observed_initial_state_missing_private_constraints'
    if left.get('reason_hash') == right.get('reason_hash') and shared:
        return 'probable_same_instance', 'same_reason_and_entity_missing_goal_or_constraints'
    # Same IDs alone do not prove a shared goal, including across DB snapshots.
    if shared:
        return 'distinct_or_unknown', 'unknown_shared_entity_incomplete_or_different_goal'
    if set(left['labels']) & set(right['labels']):
        return 'same_business_pattern_only', 'business_only_no_same_entity_evidence'
    return 'distinct_or_unknown', 'distinct_business_and_no_shared_entity'


def overlap_candidates(rl, dialogs):
    index, reasons, word_index = defaultdict(set), defaultdict(set), defaultdict(set)
    words = {}
    for d in dialogs:
        for key in entity_keys(d): index[key].add(d['id'])
        reasons[d['reason_hash']].add(d['id'])
        words[d['id']] = tokens(d['reason'])
        for word in words[d['id']]: word_index[word].add(d['id'])
    by_id = {d['id']: d for d in dialogs}
    evidence = []
    for task in rl:
        candidates = set(reasons[task['reason_hash']])
        for key in entity_keys(task): candidates.update(index[key])
        query = tokens(task['reason'])
        nearby = set()
        for w in query:
            if len(word_index[w]) <= 100: nearby.update(word_index[w])
        ranked = sorted(((len(query & words[d]) / max(1, len(query | words[d])), d) for d in nearby), reverse=True)
        candidates.update(d for score, d in ranked[:3] if score >= .50)
        for did in sorted(candidates):
            dialog = by_id[did]
            cls, rule = classify_pair(task, dialog)
            shared = sorted(entity_keys(task) & entity_keys(dialog))
            missing = [k for k in ('constraints_hash', 'completion_hash', 'initial_state_hash') if dialog.get(k) is None]
            proof = {'left': task, 'right': dialog, 'shared_entity_keys': shared}
            evidence.append({'task_id': task['id'], 'source_dialog_id': did, 'classification': cls,
                             'rule_id': rule, 'rule_version': 'policytrace-overlap-v1',
                             'confidence': 'confirmed' if cls == 'confirmed_same_instance' else 'unconfirmed',
                             'missing_evidence': missing, 'shared_entity_count': len(shared),
                             'same_reason': task['reason_hash'] == dialog['reason_hash'],
                             'exact_mutation_parameters': bool(task['mutation_actions']) and task['mutation_actions'] == dialog['mutation_actions'],
                             'compatible_initial_snapshots': sorted(set(task['compatible_snapshots']) & set(dialog['compatible_snapshots'])),
                             'evidence_sha256': digest(proof)})
    return evidence


def same_source_groups(features, field):
    groups = defaultdict(list)
    for f in features: groups[f[field]].append(f['id'])
    return [sorted(ids) for ids in groups.values() if len(ids) > 1]


def within_source_candidates(features):
    from itertools import combinations
    index = defaultdict(set)
    by_id = {f['id']:f for f in features}
    for f in features:
        for key in entity_keys(f): index[key].add(f['id'])
        index['reason:'+f['reason_hash']].add(f['id'])
    pairs = set()
    for ids in index.values(): pairs.update(combinations(sorted(ids),2))
    rows = []
    for left,right in sorted(pairs):
        cls,rule = classify_pair(by_id[left],by_id[right])
        rows.append({'left_id':left,'right_id':right,'classification':cls,'rule_id':rule,
                     'evidence_sha256':digest([by_id[left],by_id[right]])})
    return rows
