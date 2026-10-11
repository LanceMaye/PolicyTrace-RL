"""Thin native Orchestrator assembly; append-only attempts, no automatic resume/retry."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import time

from tau2.orchestrator.orchestrator import Orchestrator
from tau2.data_model.simulation import SimulationRun

from policytrace.data.manifests import ROOT, digest, file_hash, write_json, write_jsonl
from policytrace.evaluation.schema import (EvaluationPlan, RunContext, SamplingSettings, EpisodeRecord,
    ResourceUsage, TokenUsage, ToolStatistics, ArtifactReference, CostObservation, ENVIRONMENT_SHA, DATASET_REVISION, task_set_hash)
from policytrace.harness.agent_adapter import StudentAgentAdapter
from policytrace.harness.runner import ObservedEnvironment
from policytrace.stage0.db_adapter import make_retail_env
from policytrace.rewards.official import evaluate_r0
from .assets import private_path, exclusive_json
from . import VERSION


def make_plan(config, protocol, ids, run_id, *, mode, source='real'):
    if mode == 'e0-test' and source != 'real':
        raise ValueError('Mock cannot be benchmark evidence')
    context = RunContext(purpose='benchmark' if mode == 'e0-test' else 'diagnostic', run_id=run_id,
        task_set_id='frozen-test-85' if mode == 'e0-test' else 'fixed-dev-smoke-3',
        task_set_sha256=task_set_hash(ids), environment_sha=ENVIRONMENT_SHA, dataset_revision=DATASET_REVISION,
        model_id=protocol['model_id'] if source == 'real' else 'mock:offline-stage3_1',
        model_checkpoint=protocol['weight_receipt_sha256'], model_version=protocol['weight_revision'],
        model_sampling=SamplingSettings(temperature=config.temperature,top_p=config.top_p,
            max_output_tokens=config.reserved_generation_tokens,thinking='unspecified',provider_seed_supported=True),
        simulator_model=config.user.model if source == 'real' else 'mock:user-stub',
        simulator_version='provider-version-not-pinned',simulator_config_id=digest(config.user.model_dump()),
        simulator_sampling=SamplingSettings(temperature=config.user.temperature,max_output_tokens=config.user.max_output_tokens,
            thinking='disabled',provider_seed_supported=False),harness_version=VERSION+'_'+protocol['code_sha256'][:16],
        max_steps=config.max_steps,max_errors=config.max_errors,max_context_tokens=config.max_context_tokens,
        unrecorded_fields=('provider_model_weights','student_logprobs','actual_provider_bill','GPU_idle_time'))
    return EvaluationPlan(context=context,task_ids=tuple(ids),trial_ids=('trial_0',),trials_per_task=1,
                          provenance='saved_real_episode' if source == 'real' else 'mock')


def run_episode(pool, task_id, directory, plan, config, tokenizer, client, user_factory):
    """Caller owns run-wide budget/provider. Exclusive directory is the attempt ledger."""
    directory = private_path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    entry = pool.entries[task_id]
    episode_id = 'ep_'+digest([plan.context.run_id,task_id,'trial_0'])[:24]
    exclusive_json(directory/'started.json', {'episode_id':episode_id,'task_id':task_id,'trial_id':'trial_0',
        'started_at':datetime.now(timezone.utc).isoformat(),'snapshot_id':entry['db_path'],
        'snapshot_sha256':entry['snapshot_sha256']})
    start = time.perf_counter()
    agent = user = observed = orchestrator = snapshot = None
    simulation = official = failure = None
    interrupted = False
    scoring_status = 'not_available'
    initial_hash = None
    provider_start = 0
    try:
        record, snapshot = pool.load(task_id)
        env = make_retail_env(record,snapshot,initialize=False)
        initial_hash = env.get_db_hash()
        metadata = {'purpose':plan.context.purpose,'run_id':plan.context.run_id,'task_id':task_id,'trial_id':'trial_0',
            'environment_sha':ENVIRONMENT_SHA,'dataset_revision':DATASET_REVISION,
            'policy_version':'areal-retail-sft-v1','policy_file_sha256':file_hash(ROOT/'configs/policy/retail.sft_v1.md'),
            'snapshot_id':snapshot.db_path,'snapshot_sha256':snapshot.file_sha256,
            'user_simulator_fidelity':'unknown_not_measured','model_config_sha256':client.config_hash}
        if plan.provenance == 'saved_real_episode' and client.source != 'real':
            raise ValueError('Mock Student cannot enter a real plan')
        agent = StudentAgentAdapter(env.get_tools(),env.get_policy(),tokenizer,client,episode_id,metadata,
            max_tokens=config.max_context_tokens,reserved_tokens=config.reserved_generation_tokens)
        user = user_factory(record.task.user_scenario.instructions)
        if plan.provenance == 'saved_real_episode' and (not hasattr(user,'provider') or user.provider.mock):
            raise ValueError('Mock User cannot enter a real plan')
        provider_start = len(user.provider.ledger['requests']) if hasattr(user,'provider') else 0
        observed = ObservedEnvironment(env,agent,tokenizer)
        orchestrator = Orchestrator(domain='retail',agent=agent,user=user,environment=observed,task=record.task,
            max_steps=config.max_steps,max_errors=config.max_errors,seed=config.seed,validate_communication=True)
        simulation = orchestrator.run()  # The only interaction loop is the fixed Fork's.
        path = directory/'simulation_run.json'
        exclusive_json(path,simulation.model_dump(mode='json'))
        simulation = SimulationRun.model_validate_json(path.read_text(encoding='utf-8'))
        try:
            official = evaluate_r0(record,snapshot,simulation,private_reward_path=directory/'reward_info.json')
            scoring_status = 'scored'
        except Exception as exc:
            scoring_status = 'error'; failure = {'code':'scoring_error','type':type(exc).__name__}
    except BaseException as exc:
        interrupted = isinstance(exc,KeyboardInterrupt)
        failure = {'code':getattr(exc,'code','framework_error'),'type':type(exc).__name__}
    decisions = agent.decisions if agent else []
    events = observed.events if observed else []
    for decision in decisions:
        for attempt in decision['tool_attempts']:
            if attempt['status'] in ('validated_not_executed','pending_validation'):
                attempt.update(status='framework_error',reason='not_executed_after_failure')
        decision['tool_events'] = [e for e in events if any(a.get('call_id')==e['call']['id'] for a in decision['tool_attempts'])]
        decision['native_simulation_id'] = simulation.id if simulation else None
    attempts = [a for d in decisions for a in d['tool_attempts']]
    counts = Counter(a['status'] for a in attempts)
    known = all(d.get('attempt_count_known',True) for d in decisions)
    stats = ToolStatistics(attempted=len(attempts),parse_errors=counts['parse_error'],execution_errors=counts['execution_error'],
        framework_errors=counts['framework_error'] if known else None,missing_reason=None if known else 'Ambiguous delimiter: lower-bound attempt count')
    write_jsonl(directory/'decision_trace.jsonl',decisions)
    write_jsonl(directory/'tool_trace.jsonl',events)
    write_jsonl(directory/'user_trace.jsonl',user.events if user else [])
    if simulation is None:
        exclusive_json(directory/'partial_native_trace.json',{'complete':False,'failure':failure,
            'messages':[m.model_dump(mode='json') for m in orchestrator.trajectory] if orchestrator else []})
    generated = [d['generation'] for d in decisions if d.get('generation')]
    prompts = [d['context']['prompt_tokens'] for d in decisions if d.get('model_invocation_started')]
    api_entries = user.provider.ledger['requests'][provider_start:] if user and hasattr(user,'provider') else []
    usage_complete = bool(api_entries) and all(e.get('usage') for e in api_entries)
    api_complete = bool(api_entries) and all(e['status']=='completed' for e in api_entries)
    gpu_times = [(g.get('telemetry') or {}).get('gpu_generation_seconds') for g in generated]
    resource = ResourceUsage(student=TokenUsage(prompt_tokens=sum(prompts),
        completion_tokens=sum(len(g['generated_token_ids']) for g in generated) if len(prompts)==len(generated) else None,
        source='instrumented',missing_reason='Prompt IDs instrumented; failed generation output may be unknown'),
        user=TokenUsage(prompt_tokens=sum(e['usage']['prompt_tokens'] for e in api_entries) if usage_complete else None,
            completion_tokens=sum(e['usage']['completion_tokens'] for e in api_entries) if usage_complete else None,
            source='provider_usage' if usage_complete else 'not_available',missing_reason=None if usage_complete else 'Provider usage unavailable'),
        api_costs=(CostObservation(role='user',amount=sum(e['accounted_upper_cny'] for e in api_entries),currency='CNY',
            kind='upper_bound_estimate',source='user_verified_conservative_rates'),) if api_complete else None,
        gpu_seconds=sum(gpu_times) if gpu_times and all(t is not None for t in gpu_times) else None,
        missing_reason='No teacher/training; API bill and GPU idle time unknown')
    artifact = directory/('simulation_run.json' if simulation else 'partial_native_trace.json')
    episode = EpisodeRecord(context=plan.context,episode_id=episode_id,task_id=task_id,trial_id='trial_0',provenance=plan.provenance,
        db_snapshot_id=entry['db_path'],db_snapshot_sha256=entry['snapshot_sha256'],seed=config.seed,
        evaluated_at=datetime.now(timezone.utc),termination_reason=simulation.termination_reason.value if simulation else 'framework_error',
        execution_status='completed' if simulation else 'framework_error',scoring_status=scoring_status,
        official_score=official.score if official else None,tools=stats,duration_seconds=time.perf_counter()-start,resources=resource,
        trajectory=ArtifactReference(path=artifact.relative_to(ROOT).as_posix(),sha256=file_hash(artifact)),
        error_code=failure['code'] if failure else None,diagnostic_codes=('policy_semantics_not_scored',))
    exclusive_json(directory/'episode_record.json',episode.model_dump(mode='json'))
    exclusive_json(directory/'episode_metadata.json', {'failure':failure,'native_serialization_verified':simulation is not None,
        'source':'real' if plan.provenance=='saved_real_episode' else 'mock',
        'initial_db_hash':initial_hash,'final_db_hash':observed.get_db_hash() if observed else None,
        'raw_snapshot_unchanged':file_hash(ROOT/'data/raw'/entry['db_path'])==entry['snapshot_sha256'],
        'interrupted':interrupted,'projection':'identity-v0','validate_communication':True})
    return episode, interrupted
