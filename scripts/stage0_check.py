"""Run CPU checks and preserve genuine process exit codes and UTF-8 logs on all OSes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main() -> None:
    report_dir = Path('reports/stage0')
    private = Path('data/private/stage0')
    private.mkdir(parents=True,exist_ok=True)
    report_dir.mkdir(parents=True,exist_ok=True)
    commands = [
        ('audit', ['scripts/stage0_audit.py']),
        ('pytest', ['-m','pytest','-q','--junitxml=reports/stage0/pytest.xml']),
        ('smoke', ['scripts/stage0_smoke.py']),
        ('user_sim', ['scripts/stage0_user_sim_smoke.py']),
    ]
    results = []
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', LOGURU_LEVEL='ERROR')
    for name, args in commands:
        start = time.perf_counter()
        # Upstream debug/exception output can include private task data.
        log = private/f'{name}-output.txt'
        with log.open('w',encoding='utf-8') as stream:
            result = subprocess.run([sys.executable,'-X','utf8',*args],stdout=stream,stderr=subprocess.STDOUT,env=env)
        entry = {'name':name, 'command':'python '+' '.join(args), 'exit_code':result.returncode,
                 'duration_seconds':round(time.perf_counter()-start,3), 'private_log':log.as_posix()}
        results.append(entry)
        print(json.dumps(entry),flush=True)
    (report_dir/'check_results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    raise SystemExit(int(any(r['exit_code'] for r in results)))


if __name__ == '__main__':
    main()
