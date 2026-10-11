"""Recreate the pinned CPU environment using uv; never starts training or APIs."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

SHA = 'e33e9511e4f51e5cfa16e12b02d0e4ab327b5887'
ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--venv',type=Path,default=Path('.venv' if os.name=='nt' else '.venv-linux'),
                        help='Use a separate native virtual environment on each OS')
    args = parser.parse_args()
    venv = args.venv.expanduser().resolve()
    checkout = ROOT/'external/tau2-bench'
    if not checkout.exists():
        checkout.mkdir(parents=True)
        run('git','init','external/tau2-bench')
        run('git','-C','external/tau2-bench','remote','add','origin','https://github.com/dhh1995/tau2-bench.git')
        run('git','-C','external/tau2-bench','fetch','--depth','1','origin',SHA)
        run('git','-C','external/tau2-bench','checkout','--detach',SHA)
    actual = subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
    if actual != SHA:
        raise RuntimeError('Existing upstream checkout differs from the pinned commit')
    sys.path.insert(0,str(ROOT/'src'))
    from policytrace.policy import install_policy_patch
    install_policy_patch(ROOT)  # Validate/apply only the retained, user-approved policy patch.
    if not venv.exists():
        run('uv','venv','--python','3.11.15',str(venv))
    python = venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.is_file():
        raise RuntimeError('Selected virtual environment belongs to another OS or is incomplete; choose another --venv path')
    run('uv','pip','sync','--python',str(python),'requirements-stage0.lock')
    run('uv','pip','check','--python',str(python))


if __name__ == '__main__':
    main()
