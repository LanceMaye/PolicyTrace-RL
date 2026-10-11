"""Mock-only official User Simulator check. No live API is enabled by this script."""
import json
from pathlib import Path

from policytrace.stage0.task_loader import iter_retail_records, load_retail_task
from policytrace.stage0.db_adapter import load_retail_db
from policytrace.stage0.reference_check import select_tasks
from policytrace.stage0.user_sim_check import run_mock_episode, PRIVATE_USER, PRIVATE_EVAL


def main() -> None:
    root = Path('data/raw')
    records = [load_retail_task(raw, i) for i,raw in iter_retail_records(root)]
    record = select_tasks(records, 42, 8)[1]
    sim, captured = run_mock_episode(record, load_retail_db(record.db_path, root))
    checks = {'user_stop':sim.termination_reason.value=='user_stop',
              'private_user_only_in_user_prompt':PRIVATE_USER in json.dumps(captured['user']) and PRIVATE_USER not in json.dumps(captured['agent']),
              'evaluation_not_in_prompts':PRIVATE_EVAL not in json.dumps(captured),
              'tool_observation_routed':any(m['role']=='tool' for m in captured['agent'][1]['messages'])}
    report = {'mock_status':'PASS(mock)' if all(checks.values()) else 'FAIL',
              'real_status':'NOT_RUN_BY_THIS_MOCK_SCRIPT', 'real_results':'reports/stage0/deepseek_results.json', 'task_id':record.task.id,
              'fixture':'synthetic public catalog question; not the original task goal', 'seed':42,
              'termination':sim.termination_reason.value, 'checks':checks,
              'api_requests':0,'actual_api_cost':0,'actual_api_tokens':0}
    Path('reports/stage0/user_sim_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    private = Path('data/private/stage0')
    private.mkdir(parents=True,exist_ok=True)
    (private/'mock_episode.json').write_text(json.dumps({'simulation':sim.model_dump(mode='json'), 'captured':captured},indent=2),encoding='utf-8')
    print(json.dumps(report))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
