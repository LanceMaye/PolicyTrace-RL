"""Run Stage 1 CPU checks and relevant Stage 0 regression; no model APIs."""
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version, distributions
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    public, private = Path('reports/stage1'), Path('data/private/stage1')
    public.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)
    ledger = Path('data/private/stage0/deepseek/cost_ledger.json')
    ledger_before = sha(ledger)
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', LOGURU_LEVEL='ERROR')
    commands = [
        ('stage1_pytest', ['-m', 'pytest', 'tests/stage1', '-q', '--junitxml=reports/stage1/pytest.xml']),
        ('stage0_regression', ['-m', 'pytest', 'tests/stage0/test_db_isolation.py', 'tests/stage0/test_evaluator_integration.py', '-q', '--junitxml=reports/stage1/stage0_regression.xml']),
        ('real_replay', ['scripts/stage1_replay_evidence.py']),
        ('real_aggregation', ['scripts/stage1_eval_offline.py', '--input', 'data/private/stage1/episodes.jsonl',
                             '--plan', 'data/private/stage1/plan.json', '--output', 'reports/stage1/replayed_summary.json']),
        ('synthetic_aggregation', ['scripts/stage1_eval_offline.py', '--input', 'tests/stage1/fixtures/pass4_synthetic.json',
                                  '--output', 'reports/stage1/synthetic_summary.json']),
    ]
    results = []
    for name, args in commands:
        log = private / (name + '.log')
        start = time.perf_counter()
        with log.open('w', encoding='utf-8') as stream:
            proc = subprocess.run([sys.executable, '-X', 'utf8', *args], env=env, stdout=stream, stderr=subprocess.STDOUT)
        entry = {'name': name, 'command': [sys.executable, '-X', 'utf8', *args],
                 'exit_code': proc.returncode, 'duration_seconds': round(time.perf_counter()-start, 3),
                 'private_log': log.as_posix()}
        results.append(entry)
        print(json.dumps(entry), flush=True)
        if proc.returncode:
            break
    test_counts = {}
    for name in ('pytest', 'stage0_regression'):
        path = public / (name + '.xml')
        if path.exists():
            suites = ET.parse(path).getroot().iter('testsuite')
            test_counts[name] = {field: 0 for field in ('tests', 'failures', 'errors', 'skipped')}
            for suite in suites:
                for field in test_counts[name]:
                    test_counts[name][field] += int(suite.attrib.get(field, 0))
    fork_sha = subprocess.check_output(['git', '-C', 'external/tau2-bench', 'rev-parse', 'HEAD'], text=True).strip()
    fork_clean = not subprocess.check_output(['git', '-C', 'external/tau2-bench', 'status', '--porcelain'], text=True).strip()
    ledger_same = ledger_before == sha(ledger)
    status = 'PASS' if len(results) == len(commands) and all(x['exit_code'] == 0 for x in results) and ledger_same and fork_clean and fork_sha == 'e33e9511e4f51e5cfa16e12b02d0e4ab327b5887' else 'FAIL'
    files = [Path('pyproject.toml'), Path('requirements-stage0.lock'), Path('.agents/skills/policytrace-stage1/stage1.md')]
    for folder in ('src/policytrace/evaluation', 'src/policytrace/rewards', 'tests/stage1', 'configs/evaluation'):
        files.extend(p for p in Path(folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    files.extend(Path('scripts').glob('stage1_*.py'))
    files.extend(Path('docs') / name for name in ('evaluation_protocol.md', 'reward_analysis.md', 'reward_backlog.md'))
    report = {'status': status, 'checked_at': datetime.now(timezone.utc).isoformat(), 'commands': results,
              'tests': test_counts, 'environment': {'os': platform.platform(), 'python': sys.version,
                'executable': sys.executable, 'packages': {n: version(n) for n in ('tau2', 'pydantic', 'pytest')}},
              'environment_sha': fork_sha, 'upstream_working_tree_clean': fork_clean,
              'dataset_revision': '86971dc03da6e7c1a7933295e05b84aab8215386',
              'stage0_cost_ledger_unchanged': ledger_same, 'stage0_cost_ledger_sha256': ledger_before,
              'new_model_api_calls': 0, 'new_model_api_cost': 0,
              'not_run': ['new real rollouts', 'real four-trial benchmark', 'GPU/training', 'formal dataset split', 'R1'],
              'source_sha256': {p.as_posix(): sha(p) for p in sorted(set(files))}}
    packages = sorted((d.metadata['Name'], d.version) for d in distributions() if d.metadata.get('Name'))
    (public/'packages.json').write_text(json.dumps(packages, indent=2)+'\n', encoding='utf-8')
    (public/'check_results.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': status, 'tests': test_counts, 'stage0_cost_ledger_unchanged': ledger_same}), flush=True)
    raise SystemExit(int(status != 'PASS'))


if __name__ == '__main__':
    main()
