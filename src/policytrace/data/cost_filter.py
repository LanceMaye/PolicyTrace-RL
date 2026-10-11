"""Views only. Unconfirmed candidates NEVER remove training tasks."""


def cost_pruned_view(rl_train_ids, sft_train_dialogs, candidates):
    train, sft = set(rl_train_ids), set(sft_train_dialogs)
    exclusions = {}
    for evidence in candidates:
        if (evidence['task_id'] in train and evidence['source_dialog_id'] in sft
                and evidence['classification'] == 'confirmed_same_instance'
                and evidence['confidence'] == 'confirmed'
                and not evidence['missing_evidence']):
            if not evidence.get('evidence_sha256'): raise ValueError('Missing exclusion proof')
            exclusions.setdefault(evidence['task_id'], []).append(evidence)
    rows = [{'task_id': tid, 'classification': 'confirmed_same_instance',
             'reason': 'confirmed instance already in SFT Train; reversible cost hypothesis',
             'source_dialog_ids': sorted({e['source_dialog_id'] for e in es}),
             'evidence_sha256': sorted({e['evidence_sha256'] for e in es}),
             'rule_ids': sorted({e['rule_id'] for e in es})} for tid, es in sorted(exclusions.items())]
    return sorted(train-set(exclusions)), rows
