"""Record versions, host facts and source hashes without reading any credentials."""
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import subprocess
import sys

import psutil

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    out = ROOT/'reports/stage0'
    versions = json.loads((out/'versions.json').read_text(encoding='utf-8'))
    linux_status = 'NOT_RUN; no Linux verification has been executed'
    wsl_report = out/'wsl_install.json'
    if platform.system()=='Windows' and wsl_report.exists():
        wsl = json.loads(wsl_report.read_text(encoding='utf-8'))
        linux_status = f"NOT_RUN; WSL installation state: {wsl['status']}"
    versions['linux_validation'] = linux_status
    versions.update(python=sys.version,platform=platform.platform(),
        dependencies={d.metadata['Name'].lower():d.version for d in importlib.metadata.distributions()})
    versions['tau2']['working_tree_clean'] = not subprocess.check_output(
        ['git','-C',str(ROOT/'external/tau2-bench'),'status','--porcelain'],text=True).strip()
    files = sorted([*ROOT.glob('src/**/*.py'),*ROOT.glob('tests/**/*.py'),*ROOT.glob('scripts/*.py'),*ROOT.glob('scripts/*.ps1'),
                    ROOT/'pyproject.toml',ROOT/'requirements-stage0.lock'])
    versions['project_file_sha256'] = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    versions['upstream_assets_sha256'] = {p.relative_to(ROOT/'external/tau2-bench').as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'external/tau2-bench/data/tau2').rglob('*') if p.is_file() and ('retail' in p.parts or 'user_simulator' in p.parts)}
    (out/'versions.json').write_text(json.dumps(versions,indent=2),encoding='utf-8')
    host = {'os':platform.platform(),'python':sys.version,'logical_cpus':psutil.cpu_count(),
            'memory_total_bytes':psutil.virtual_memory().total,'disk_free_bytes':psutil.disk_usage(str(ROOT)).free,
            'git':subprocess.check_output(['git','--version'],text=True).strip(),'workdir':str(ROOT),
            'linux_validation':linux_status,
            'gpu_used':False,'paid_cloud_resources_started':False}
    (out/'environment.json').write_text(json.dumps(host,indent=2),encoding='utf-8')
    print('Saved source hashes, versions and environment metadata; no credentials accessed.')


if __name__ == '__main__':
    main()
