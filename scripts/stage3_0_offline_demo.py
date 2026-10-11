"""Reproducible CPU-only diagnostic, never a Base benchmark."""
import argparse
from datetime import datetime, timezone
from dataclasses import replace
import time
import uuid
import yaml
from loguru import logger

from policytrace.data.manifests import ROOT, write_json
from policytrace.harness.runner import OfflineConfig, run_episode
from policytrace.harness.fixtures import fixture_scripts
from policytrace.harness.verification import offline_guard


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['offline'], default='offline')
    parser.add_argument('--split', choices=['dev'], default='dev')
    parser.add_argument('--config',default='configs/harness/stage3_0_offline.example.yaml')
    parser.add_argument('--run-id',default=None)
    args = parser.parse_args()
    config = OfflineConfig(**yaml.safe_load((ROOT/args.config).read_text(encoding='utf-8')))
    if config.mode != args.mode or config.split != args.split:
        parser.error('CLI and config disagree')
    run_id = args.run_id or 'offline_'+uuid.uuid4().hex[:12]
    output = ROOT/'data/private/stage3_0'/run_id
    if output.exists():
        raise FileExistsError('Use a fresh run-id; evidence is never overwritten')
    output.mkdir(parents=True)
    logger.remove()
    logger.add(str(output/'execution.log'),level='DEBUG',encoding='utf-8')
    start = time.perf_counter()
    results = []
    with offline_guard() as network:
        for task_id, name, strict in [('retail_152','readonly',True),('retail_131','readonly',True),
            ('retail_152','write',True),('retail_152','partial_write_error',True),
            ('retail_152','mixed',True),('retail_152','mixed',False),('retail_152','multi_read',True)]:
            student,user = fixture_scripts(task_id)[name]
            label = f'{task_id}_{name}_{strict}'
            episode = run_episode(task_id,student,user,output/label,
                config=replace(config,validate_communication=strict),run_id=run_id,trial_id=label)
            results.append(episode.summary)
    expected = [1,0,0,0,0,1,1]
    passed = all(r['execution_status']=='completed' and r['scoring_status']=='scored' and
                 r['diagnostic_r0']==reward and r['raw_snapshot_unchanged'] for r,reward in zip(results,expected))
    report = {'status':'PASS_OFFLINE' if passed and not network else 'FAIL','source':'mock','purpose':'diagnostic',
        'run_id':run_id,'executed_at':datetime.now(timezone.utc).isoformat(),
        'seconds':round(time.perf_counter()-start,3),'episodes':results,'paid_api_calls':0,
        'network_attempts':len(network),'formal_pass1':None,'formal_pass4':None,'base_baseline_run':False}
    write_json(ROOT/'reports/stage3_0/offline_demo_results.json',report)
    print({'status':report['status'],'mock_episodes':len(results),'seconds':report['seconds']},flush=True)
    if report['status']!='PASS_OFFLINE':
        raise SystemExit(1)


if __name__=='__main__':
    main()
