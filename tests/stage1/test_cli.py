import json
from pathlib import Path
import subprocess
import sys


def test_jsonl_cli_and_incomplete_exit(make_plan, make_episode, tmp_path):
    p = make_plan()
    plan_file, records_file, output = (tmp_path/n for n in ('plan.json', 'episodes.jsonl', 'summary.json'))
    plan_file.write_text(p.model_dump_json(), encoding='utf-8')
    records_file.write_text(make_episode(p).model_dump_json()+'\n', encoding='utf-8')
    command = [sys.executable, 'scripts/stage1_eval_offline.py', '--input', str(records_file), '--plan', str(plan_file), '--output', str(output)]
    proc = subprocess.run(command, capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2])
    assert proc.returncode == 3
    assert json.loads(output.read_text())['pass1']['value'] is None
    records_file.write_text('\n'.join(make_episode(p, task=t).model_dump_json() for t in p.task_ids)+'\n', encoding='utf-8')
    proc = subprocess.run(command, capture_output=True, text=True)
    assert proc.returncode == 0
    assert json.loads(output.read_text())['pass1']['value'] == 1


def test_cli_rejects_duplicate_without_writing_summary(make_plan, make_episode, tmp_path):
    p = make_plan(task_ids=('synthetic_a',))
    input_path, output = tmp_path/'bundle.json', tmp_path/'summary.json'
    e = make_episode(p).model_dump(mode='json')
    input_path.write_text(json.dumps({'plan': p.model_dump(mode='json'), 'episodes': [e, e]}), encoding='utf-8')
    proc = subprocess.run([sys.executable, 'scripts/stage1_eval_offline.py', '--input', str(input_path), '--output', str(output)], capture_output=True, text=True)
    assert proc.returncode == 2 and not output.exists()
    assert 'no summary written' in proc.stderr
