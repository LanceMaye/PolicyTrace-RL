"""At most two real official Retail episodes under the user's cumulative 5 CNY cap."""
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from policytrace.stage0.task_loader import iter_retail_records, load_retail_task
from policytrace.stage0.db_adapter import load_retail_db, make_retail_env
from policytrace.stage0.evaluator_adapter import evaluate_with_correct_initial_state
from policytrace.stage0.deepseek_client import BudgetedDeepSeek, MODEL
from tau2.agent.llm_agent import LLMAgent
from tau2.user.user_simulator import UserSimulator
from tau2.orchestrator.orchestrator import Orchestrator
from tau2.data_model.simulation import TerminationReason

TASK_IDS = ['retail_131', 'retail_152']


def main() -> None:
    load_dotenv('.env',override=False)
    key = os.getenv('DEEPSEEK_API_KEY','').strip()
    if not key:
        print('BLOCKED: fill DEEPSEEK_API_KEY in the local .env file. No API request sent.')
        raise SystemExit(2)
    if os.getenv('DEEPSEEK_MODEL',MODEL) != MODEL or os.getenv('DEEPSEEK_BASE_URL','https://api.deepseek.com').rstrip('/') != 'https://api.deepseek.com':
        raise ValueError('This budget approval covers the official endpoint and deepseek-v4-pro only')
    private = Path('data/private/stage0/deepseek')
    private.mkdir(parents=True,exist_ok=True)
    report_path = Path('reports/stage0/deepseek_results.json')
    # Never rerun paid episodes automatically, including after a failed run.
    if report_path.exists():
        print('Existing real-run report found; inspect it before authorizing any rerun. No API request sent.')
        raise SystemExit(2)
    lock = private/'run.lock'
    try:
        fd = os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        print('Run lock exists. Check for an interrupted/concurrent run before retrying.')
        raise SystemExit(2)
    os.close(fd)
    client = None
    report = {'status':'NOT_RUN','provider':'DeepSeek official', 'model':MODEL,
              'documented_version_on_2026_10_09':'DeepSeek-V4-Pro-0813 (alias, not immutable endpoint)',
              'seed':42, 'provider_seed_supported':False,'temperature':0, 'thinking':'disabled',
              'max_output_tokens':512, 'max_steps_per_episode':16, 'max_episodes':2,
              'max_retries':0, 'user_cost_limit_cny':5, 'internal_cost_limit_cny':4, 'episodes':[]}
    try:
        logger.remove()
        logger.add(private/'execution.log',level='INFO')
        client = BudgetedDeepSeek(key,private/'cost_ledger.json')
        records = {r.task.id:r for i,raw in iter_retail_records(Path('data/raw')) if (r:=load_retail_task(raw,i)).task.id in TASK_IDS}
        for task_id in TASK_IDS:
            record = records[task_id]
            snapshot = load_retail_db(record.db_path,Path('data/raw'))
            env = make_retail_env(record,snapshot,initialize=False)
            agent = LLMAgent(tools=env.get_tools(),domain_policy=env.get_policy(),llm=MODEL,
                llm_args={'temperature':0,'num_retries':0},completion_fn=lambda **kw:client.complete('agent',**kw))
            user = UserSimulator(instructions=str(record.task.user_scenario),llm=MODEL,
                llm_args={'temperature':0,'num_retries':0},completion_fn=lambda **kw:client.complete('user',**kw))
            # Store actual official prompt locally and only its hash in the public report.
            (private/f'{task_id}-user-prompt.txt').write_text(user.system_prompt,encoding='utf-8')
            orchestrator = Orchestrator(domain='retail',agent=agent,user=user,environment=env,task=record.task,
                max_steps=16,max_errors=1,seed=42,solo_mode=False,validate_communication=True)
            simulation = orchestrator.run()
            (private/f'{task_id}-episode.json').write_text(simulation.model_dump_json(indent=2),encoding='utf-8')
            reward = evaluate_with_correct_initial_state(record,snapshot,simulation)
            (private/f'{task_id}-reward.json').write_text(reward.model_dump_json(indent=2),encoding='utf-8')
            entry = {'task_id':task_id, 'snapshot_sha256':snapshot.file_sha256,
                     'user_prompt_sha256':hashlib.sha256(user.system_prompt.encode()).hexdigest(),
                     'termination':simulation.termination_reason.value,'official_reward':reward.reward,
                     'tool_calls':sum(len(getattr(m,'tool_calls',None) or []) for m in simulation.messages),
                     'tool_errors':sum(bool(getattr(m,'error',False)) for m in simulation.messages),
                     'duration_seconds':simulation.duration, 'simulator_quality_review':'PENDING manual transcript review'}
            report['episodes'].append(entry)
            print(json.dumps(entry),flush=True)
            if simulation.termination_reason not in (TerminationReason.USER_STOP,TerminationReason.AGENT_STOP):
                report['status'] = 'FAIL'
                break
        else:
            report['status'] = 'EXECUTED_PENDING_QUALITY_REVIEW'
    except Exception as exc:
        report.update(status='FAIL',error_type=type(exc).__name__)
        # All API failure messages from the adapter are sanitized; avoid other exception data.
        print(f'Real episode stopped: {type(exc).__name__}. No automatic retry.',flush=True)
    finally:
        if client:
            report['requests'] = len(client.ledger['requests'])
            report['estimated_peak_cost_upper_cny'] = client.charged_upper_cny
            client.close()
        report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        lock.unlink()
    if report['status'] != 'EXECUTED_PENDING_QUALITY_REVIEW':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
