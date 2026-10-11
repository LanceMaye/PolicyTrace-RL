"""Deterministic reference/official-evaluator checks; no model inference."""
import argparse
import json
import time
import traceback
from pathlib import Path

from policytrace.stage0.task_loader import iter_retail_records, load_retail_task
from policytrace.stage0.db_adapter import load_retail_db
from policytrace.stage0.evaluator_adapter import evaluate_with_correct_initial_state
from policytrace.stage0.reference_check import select_tasks, reference_fixture
from tau2.evaluator.evaluator import evaluate_simulation, EvaluationType


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', type=Path, default=Path('data/raw'))
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--limit', type=int, default=8)
    parser.add_argument('--task-id', action='append')
    parser.add_argument('--output', type=Path, default=Path('reports/stage0/smoke_results.json'))
    parser.add_argument('--private-dir', type=Path, default=Path('data/private/stage0'))
    args = parser.parse_args()
    records = [load_retail_task(raw, i) for i, raw in iter_retail_records(args.data_root)]
    if args.task_id:
        records = sorted([r for r in records if r.task.id in args.task_id], key=lambda r:r.task.id)
        if {r.task.id for r in records} != set(args.task_id):
            parser.error('Unknown Retail task ID')
    else:
        records = select_tasks(records, args.seed, args.limit)
    private = args.private_dir
    private.mkdir(parents=True, exist_ok=True)
    report = {'seed':args.seed, 'mode':'reference fixture, NOT benchmark or real episode', 'results':[]}
    for record in records:
        start = time.perf_counter()
        result = {'task_id':record.task.id, 'db_path':record.db_path, 'source_line':record.source_index,
                  'task_loaded':True, 'db_loaded':False, 'tool_executed':False, 'evaluator_invoked':False,
                  'evaluation_validated':False, 'task_success':None,
                  'reproduce':f'python scripts/stage0_smoke.py --seed {args.seed} --task-id {record.task.id} --output reports/stage0/single_smoke.json'}
        detail = {}
        try:
            snapshot = load_retail_db(record.db_path, args.data_root)
            result.update(db_loaded=True, snapshot_sha256=snapshot.file_sha256)
            sim, detail = reference_fixture(record, snapshot, seed=args.seed)
            result.update(tool_executed=bool(detail['calls']), tool_errors=sum(bool(x['error']) for x in detail['calls']),
                          action_names=[x['name'] for x in detail['calls']], initial_hash=detail['initial_hash'],
                          final_hash=detail['final_hash'], db_changed=detail['initial_hash'] != detail['final_hash'])
            result['evaluator_invoked'] = True
            reward = evaluate_with_correct_initial_state(record, snapshot, sim)
            detail['official_reward'] = reward.model_dump(mode='json')
            detail['simulation'] = sim.model_dump(mode='json')
            result.update(official_reward=reward.reward, db_match=reward.db_check.db_match if reward.db_check else None,
                          reward_breakdown=reward.model_dump(mode='json')['reward_breakdown'])
            result['evaluation_validated'] = result['tool_errors'] == 0 and result['db_match'] is True
            # Compare the exact same fixture against the unadapted default factory.
            try:
                wrong = evaluate_simulation(sim, record.task, EvaluationType.ALL, False, 'retail')
                detail['default_db_result'] = wrong.model_dump(mode='json')
                result['default_db_control'] = {'outcome':'returned', 'reward':wrong.reward}
            except Exception as exc:
                detail['default_db_exception'] = traceback.format_exc()
                result['default_db_control'] = {'outcome':'rejected', 'exception_type':type(exc).__name__}
            result['status'] = 'PASS' if result['evaluation_validated'] else 'FAIL'
        except Exception as exc:
            result.update(status='FAIL', exception_type=type(exc).__name__)
            detail['exception'] = traceback.format_exc()
        result['duration_seconds'] = round(time.perf_counter()-start, 3)
        detail_path = private/f'{record.task.id}.json'
        detail_path.write_text(json.dumps(detail, indent=2), encoding='utf-8')
        result['private_evidence'] = detail_path.as_posix()
        report['results'].append(result)
        print(json.dumps({k:result.get(k) for k in ['task_id','status','tool_errors','official_reward','db_match','duration_seconds']}), flush=True)
    report['status'] = 'PASS' if all(x['status']=='PASS' for x in report['results']) else 'FAIL'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    if report['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
