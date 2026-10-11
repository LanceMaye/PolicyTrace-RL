"""Stage 1 denominators plus private token evidence; no task bodies in public output."""
from datetime import datetime, timezone
from collections import Counter

from policytrace.data.manifests import digest, file_hash, read_json, read_jsonl, quantiles
from policytrace.evaluation.schema import EvaluationPlan, EpisodeRecord
from policytrace.evaluation.metrics import aggregate
from .assets import private_path


def summarize(directory):
    directory = private_path(directory)
    manifest = read_json(directory/'run_manifest.json')
    plan = EvaluationPlan.model_validate(manifest['plan'])
    records, traces, metadata, evidence, user_events, growth = [], [], [], {}, [], []
    for path in sorted((directory/'episodes').glob('*')) if (directory/'episodes').exists() else []:
        if not path.is_dir(): continue
        marker = read_json(path/'started.json')
        record_path = path/'episode_record.json'
        if record_path.exists():
            episode = EpisodeRecord.model_validate(read_json(record_path))
            if episode.task_id != marker['task_id'] or episode.episode_id != marker['episode_id']:
                raise ValueError('Attempt ledger and saved episode disagree')
            if episode.trajectory:
                from policytrace.data.manifests import ROOT
                if file_hash(ROOT/episode.trajectory.path) != episode.trajectory.sha256:
                    raise ValueError('Trajectory integrity mismatch')
        else:
            # SIGKILL/power loss: started slot counts as failed, without fabricated observation/reward.
            episode = EpisodeRecord(context=plan.context,episode_id=marker['episode_id'],task_id=marker['task_id'],trial_id=marker['trial_id'],
                provenance=plan.provenance,db_snapshot_id=marker['snapshot_id'],db_snapshot_sha256=marker['snapshot_sha256'],
                evaluated_at=datetime.now(timezone.utc),termination_reason='framework_error',execution_status='framework_error',
                scoring_status='not_available',official_score=None,error_code='interrupted_attempt_without_final_record')
        records.append(episode)
        if (path/'decision_trace.jsonl').exists():
            episode_trace = list(read_jsonl(path/'decision_trace.jsonl'))
            traces.extend(episode_trace)
            lengths = [t['context']['prompt_tokens'] for t in episode_trace if t.get('context')]
            growth.extend(b-a for a,b in zip(lengths,lengths[1:]))
        if (path/'user_trace.jsonl').exists(): user_events.extend(read_jsonl(path/'user_trace.jsonl'))
        if (path/'episode_metadata.json').exists(): metadata.append(read_json(path/'episode_metadata.json'))
        for p in path.glob('*'):
            if p.is_file(): evidence[p.relative_to(directory).as_posix()] = file_hash(p)
    result = aggregate(plan, records)  # Rejects duplicate task/trial/context/provenance.
    result.pop('tasks')
    result['coverage']['missing_or_not_run_count'] = len(result['coverage'].pop('missing_or_not_run'))
    result['tools'].pop('per_episode')
    result['pass4'] = {'status':'not_measured','value':None}
    result['coverage']['completed_trials'] = sum(e.execution_status=='completed' for e in records)
    result['outcomes'] = {'reward_1':sum(e.official_reward==1 for e in records),'reward_0':sum(e.official_reward==0 for e in records),
                          'reward_null':sum(e.official_reward is None for e in records)}
    generated = [t['generation'] for t in traces if t.get('generation')]
    contexts = [t['context']['prompt_tokens'] for t in traces if t.get('context')]
    peaks = [(g.get('telemetry') or {}).get('gpu_peak_allocated_bytes') for g in generated]
    result['context_tokens'] = quantiles(contexts)
    result['context_growth_tokens'] = quantiles(growth)
    result['student_generation_seconds'] = quantiles([g['duration_seconds'] for g in generated])
    result['user_generation_seconds'] = quantiles([e['duration_seconds'] for e in user_events])
    result['terminations'] = dict(Counter(e.termination_reason for e in records))
    result['error_codes'] = dict(Counter(e.error_code for e in records if e.error_code))
    result['actual_student_completion_tokens'] = sum(len(g['generated_token_ids']) for g in generated if g['token_provenance']=='model_generated')
    result['protocol_features'] = {name:sum(t.get('protocol_features',{}).get(name) is True for t in traces)
                                  for name in ('multiple_tool_calls','text_and_tool_calls')}
    result['gpu_peak_allocated_bytes'] = max((x for x in peaks if x is not None),default=None)
    result['api_actual_bill_cny'] = None
    ledger = directory/'api_ledger.json'
    requests = read_json(ledger)['requests'] if ledger.exists() else None
    result['api_requests'] = {'reserved':len(requests),'started':sum(bool(r.get('request_started')) for r in requests),
        'completed':sum(r['status']=='completed' for r in requests),
        'failed_or_ambiguous':sum(r['status']!='completed' for r in requests),
        'accounted_upper_cny':sum(r['accounted_upper_cny'] for r in requests),
        'actual_bill_cny':None} if requests is not None else None
    if ledger.exists(): evidence['api_ledger.json'] = file_hash(ledger)
    result['integrity'] = {'all_real_tokens':bool(generated) and all(g['source']=='real' and g['token_provenance']=='model_generated' for g in generated),
        'all_real_users':bool(user_events) and all(e['source']=='real' and e.get('usage') and not e.get('error_code') for e in user_events),
        'native_serialization_verified':len(metadata)==len(records) and bool(records) and all(m['native_serialization_verified'] for m in metadata),
        'raw_snapshots_unchanged':len(metadata)==len(records) and bool(records) and all(m['raw_snapshot_unchanged'] for m in metadata),
        'evidence_sha256':digest(evidence)}
    if plan.context.purpose == 'diagnostic':
        result['diagnostic_pass1'] = result['pass1']; result['pass1'] = {'status':'diagnostic_not_formal','value':None,'denominator':len(plan.task_ids)}
    # Context fields are public configuration; remove local checkpoint paths if future implementations add them.
    result['context']['model_checkpoint'] = 'sha256:'+plan.context.model_checkpoint if plan.context.model_checkpoint else None
    return result
