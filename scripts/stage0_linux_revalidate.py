"""Small Linux CPU revalidation; no model calls, downloads or training."""
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone


def main() -> None:
    if sys.platform != 'linux':
        raise SystemExit('Run with the Linux virtual environment from the project root')
    private = Path('data/private/stage0/linux')
    private.mkdir(parents=True, exist_ok=True)
    report = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'Two reference fixtures, two DB isolation tests and one mock routing test',
        'python': sys.version, 'executable': sys.executable,
        'kernel': platform.release(), 'os_release': platform.freedesktop_os_release(),
        'tau2_sha': subprocess.check_output(['git', '-C', 'external/tau2-bench', 'rev-parse', 'HEAD'], text=True).strip(),
        'lock_sha256': hashlib.sha256(Path('requirements-stage0.lock').read_bytes()).hexdigest(),
        'api_calls': 0, 'actual_api_cost': 0, 'autodl_validation': 'NOT_RUN',
        'commands': [],
    }
    if Path('/tmp/policytrace-linux-bootstrap.log').exists():
        shutil.copyfile('/tmp/policytrace-linux-bootstrap.log', private / 'bootstrap.log')
    env = dict(os.environ, PYTHONUTF8='1', LOGURU_LEVEL='ERROR')
    checks = [
        ('isolation_and_mock', ['-m', 'pytest', '-q',
            'tests/stage0/test_db_isolation.py::test_isolation_reset_and_source_unchanged[0]',
            'tests/stage0/test_db_isolation.py::test_isolation_reset_and_source_unchanged[1]',
            'tests/stage0/test_user_simulator.py::test_official_mock_routing_and_private_fields',
            '--junitxml=reports/stage0/linux_pytest.xml']),
        ('smoke', ['scripts/stage0_smoke.py', '--seed', '42',
            '--task-id', 'retail_245', '--task-id', 'retail_8',
            '--output', 'reports/stage0/linux_smoke_results.json', '--private-dir', str(private)]),
    ]
    for name, args in checks:
        start = time.perf_counter()
        log = private / (name + '.log')
        with log.open('w', encoding='utf-8') as stream:
            proc = subprocess.run([sys.executable, *args], env=env, stdout=stream, stderr=subprocess.STDOUT)
        entry = {'name': name, 'argv': [sys.executable, *args], 'exit_code': proc.returncode,
                 'duration_seconds': round(time.perf_counter() - start, 3), 'private_log': str(log)}
        report['commands'].append(entry)
        print(json.dumps(entry), flush=True)
    report['status'] = 'PASS' if all(c['exit_code'] == 0 for c in report['commands']) else 'FAIL'
    report['linux_validation'] = report['status']
    Path('reports/stage0/linux_revalidation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    packages = subprocess.check_output(['uv', 'pip', 'freeze', '--python', sys.executable], text=True)
    Path('reports/stage0/linux_packages.txt').write_text(packages, encoding='utf-8')
    raise SystemExit(int(report['status'] != 'PASS'))


if __name__ == '__main__':
    main()
