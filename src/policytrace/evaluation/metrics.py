"""Pure aggregation over a declared plan; missing trials never shrink denominators."""
from collections import Counter, defaultdict
from statistics import mean, median

from .schema import EpisodeRecord, EvaluationPlan, FutureTrainingDiagnostics


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def numeric_summary(values: list[int | float | None]) -> dict:
    observed = [x for x in values if x is not None]
    complete = bool(values) and len(observed) == len(values)
    return {'count': len(values), 'recorded': len(observed), 'missing': len(values) - len(observed),
            'total': sum(observed) if complete else None,
            'mean': mean(observed) if complete else None,
            'median': median(observed) if complete else None,
            'observed_subtotal': sum(observed) if observed else None}


def aggregate(plan: EvaluationPlan, episodes: list[EpisodeRecord]) -> dict:
    by_key = {}
    snapshots = {}
    episode_ids = set()
    for record in episodes:
        key = (record.task_id, record.trial_id)
        if key in by_key:
            raise ValueError(f'Duplicate task/trial: {key}')
        if record.episode_id in episode_ids:
            raise ValueError('A saved episode cannot be reused as another independent trial')
        episode_ids.add(record.episode_id)
        if record.task_id not in plan.task_ids or record.trial_id not in plan.trial_ids:
            raise ValueError(f'Unexpected task/trial outside plan: {key}')
        if record.context != plan.context:
            raise ValueError(f'Run/model/simulator/environment configuration mismatch for {key}')
        if record.provenance != plan.provenance:
            raise ValueError('Do not mix real, synthetic, mock or reference evidence')
        snapshot = (record.db_snapshot_id, record.db_snapshot_sha256)
        if record.task_id in snapshots and snapshots[record.task_id] != snapshot:
            raise ValueError(f'DB snapshot changed between trials of {record.task_id}')
        snapshots[record.task_id] = snapshot
        by_key[key] = record
    missing = [{'task_id': task, 'trial_id': trial, 'reason': 'missing' if (task, trial) not in by_key else 'not_run'}
               for task in plan.task_ids for trial in plan.trial_ids
               if (task, trial) not in by_key or not by_key[task, trial].started]
    status = 'empty' if not plan.task_ids else 'incomplete' if missing else 'complete'
    pass1_numerator = sum(by_key.get((task, plan.trial_ids[0])) is not None
                          and by_key[task, plan.trial_ids[0]].success is True for task in plan.task_ids)
    pass4_numerator = sum(all(by_key.get((task, trial)) is not None
                              and by_key[task, trial].success is True for trial in plan.trial_ids)
                          for task in plan.task_ids) if plan.trials_per_task == 4 else None
    tasks = []
    for task in plan.task_ids:
        trials = []
        for trial in plan.trial_ids:
            record = by_key.get((task, trial))
            trials.append({'trial_id': trial, 'status': 'missing' if record is None else record.execution_status,
                           'scoring_status': record.scoring_status if record else None,
                           'termination_reason': record.termination_reason if record else None,
                           'official_reward': record.official_reward if record else None,
                           'success': record.success if record else None,
                           'counted_success': record.success is True if record and record.started else None,
                           'diagnostic_codes': list(record.diagnostic_codes) if record else []})
        tasks.append({'task_id': task, 'task_type': next((by_key[task, t].task_type for t in plan.trial_ids if (task, t) in by_key), None),
                      'trials': trials})
    started = [r for r in episodes if r.started]
    tool_records = [r for r in started if r.tools is not None]
    all_tool_counts = len(tool_records) == len(started) and bool(started)
    all_attempt_scope = all(r.tools.attempt_scope == 'all_attempts' for r in tool_records)
    all_errors = all_tool_counts and all_attempt_scope and all(
        all(x is not None for x in (r.tools.parse_errors, r.tools.execution_errors, r.tools.framework_errors))
        for r in tool_records)
    attempts = sum(r.tools.attempted for r in tool_records)
    failures = sum(r.tools.parse_errors + r.tools.execution_errors + r.tools.framework_errors for r in tool_records) if all_errors else None
    parsed_attempts = []
    for r in tool_records:
        parsed_attempts.append(r.tools.attempted if r.tools.attempt_scope == 'parsed_calls' else
                               r.tools.attempted - r.tools.parse_errors if r.tools.parse_errors is not None else None)
    execution_known = all_tool_counts and all(x is not None for x in parsed_attempts) and all(r.tools.execution_errors is not None for r in tool_records)
    execution_denominator = sum(parsed_attempts) if execution_known else None
    execution_failures = sum(r.tools.execution_errors for r in tool_records) if execution_known else None
    tool_distribution = []
    for r in started:
        tool = r.tools
        error_counts = (tool.parse_errors, tool.execution_errors, tool.framework_errors) if tool else ()
        rate = _ratio(sum(error_counts), tool.attempted) if tool and tool.attempt_scope == 'all_attempts' and all(x is not None for x in error_counts) else None
        tool_distribution.append({'task_id': r.task_id, 'trial_id': r.trial_id,
                                  'counts': tool.model_dump(mode='json') if tool else None,
                                  'tool_call_error_rate': rate})
    scopes = {r.tools.attempt_scope for r in tool_records}
    count_values = [r.tools.attempted if r.tools is not None else None for r in started]
    if len(scopes) > 1:
        count_values = [None for _ in started]  # Counts with different scopes are not comparable.
    costs = defaultdict(list)
    for r in started:
        for cost in r.resources.api_costs or ():
            costs[(cost.role, cost.currency, cost.kind)].append(cost.amount)
    missing_costs = sum(r.resources.api_costs is None for r in started)
    cost_groups = [{'role': role, 'currency': currency, 'kind': kind,
                    'observed_subtotal': sum(values), 'total': sum(values) if not missing_costs else None}
                   for (role, currency, kind), values in sorted(costs.items())]
    token_usage = {role: {field: numeric_summary([getattr(getattr(r.resources, role), field) for r in started])
                          for field in ('prompt_tokens', 'completion_tokens')}
                   for role in ('student', 'user', 'teacher')}
    abnormal = sum(r.abnormal_termination for r in started)
    scored = [r for r in started if r.official_score is not None]
    resources = {field: numeric_summary([getattr(r.resources, field) for r in started])
                 for field in ('gpu_seconds', 'teacher_inference_seconds', 'training_tokens')}
    tokens, gpu = resources['training_tokens']['total'], resources['gpu_seconds']['total']
    return {
        'protocol_version': plan.context.protocol_version, 'status': status,
        'provenance': plan.provenance, 'context': plan.context.model_dump(mode='json'),
        'evidence_scope': 'offline diagnostic aggregation; not a formal model benchmark' if plan.context.purpose == 'diagnostic' else 'benchmark aggregation under the declared protocol',
        'coverage': {'planned_tasks': len(plan.task_ids), 'planned_trials': len(plan.task_ids) * plan.trials_per_task,
                     'recorded_trials': len(episodes), 'started_trials': len(started), 'scored_trials': len(scored),
                     'missing_or_not_run': missing},
        'pass1': {'value': _ratio(pass1_numerator, len(plan.task_ids)) if status == 'complete' else None,
                  'numerator': pass1_numerator if status == 'complete' else None,
                  'denominator': len(plan.task_ids), 'trial_id': plan.trial_ids[0], 'status': status},
        'pass4': {'value': _ratio(pass4_numerator, len(plan.task_ids)) if status == 'complete' and plan.trials_per_task == 4 else None,
                  'numerator': pass4_numerator if status == 'complete' and plan.trials_per_task == 4 else None,
                  'denominator': len(plan.task_ids), 'status': status if plan.trials_per_task == 4 else 'not_requested'},
        'outcomes': {'execution_status': dict(Counter(r.execution_status for r in episodes)),
                     'scoring_status': dict(Counter(r.scoring_status for r in episodes)),
                     'termination_reason': dict(Counter(r.termination_reason for r in episodes)),
                     'official_reward_distribution': dict(Counter(str(r.official_reward) for r in scored)),
                     'unscored_started_trials': len(started) - len(scored)},
        'abnormal_termination': {'numerator': abnormal, 'denominator': len(started), 'rate': _ratio(abnormal, len(started))},
        'tools': {'complete_attempts': attempts if all_tool_counts and all_attempt_scope else None,
                  'observed_attempts': attempts if tool_records else None,
                  'error_count': failures, 'error_rate': _ratio(failures, attempts) if all_errors else None,
                  'execution_error_count': execution_failures, 'parsed_attempts': execution_denominator,
                  'execution_error_rate': _ratio(execution_failures, execution_denominator) if execution_known else None,
                  'attempt_scopes': sorted(scopes), 'call_count': numeric_summary(count_values),
                  'missing_episodes': len(started) - len(tool_records), 'per_episode': tool_distribution},
        'duration_seconds': numeric_summary([r.duration_seconds for r in started]),
        'by_success': {label: {'count': len(group), 'duration_seconds': numeric_summary([r.duration_seconds for r in group]),
                               'tool_calls': numeric_summary([r.tools.attempted if r.tools else None for r in group])}
                       for label, group in [('success', [r for r in started if r.success is True]),
                                            ('failure_or_unscored', [r for r in started if r.success is not True])]},
        'tokens': token_usage, 'api_costs': {'groups': cost_groups, 'missing_episodes': missing_costs},
        'training_resources': resources,
        'training_tokens_per_gpu_second': tokens / gpu if tokens is not None and gpu is not None and gpu > 0 else None,
        'training_diagnostics': FutureTrainingDiagnostics().model_dump(mode='json'), 'tasks': tasks,
    }
