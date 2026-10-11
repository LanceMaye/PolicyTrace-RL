"""Immutable input inventories and fail-closed offline execution."""
from contextlib import contextmanager
from pathlib import Path
import socket
import subprocess
import inspect

from policytrace.data.manifests import ROOT, file_hash, read_json, write_json
from policytrace.evaluation.schema import ENVIRONMENT_SHA
from policytrace.policy import verify_fork


def fork_state():
    return verify_fork(ROOT)


def inventory():
    roots = ['src/policytrace/stage0', 'src/policytrace/evaluation', 'src/policytrace/rewards',
             'src/policytrace/data', 'src/policytrace/compatibility', 'tests/stage0', 'tests/stage1',
             'tests/stage2', 'tests/multi_tool_compatibility', 'reports/stage0', 'reports/stage1',
             'reports/stage2', 'configs/data', 'configs/evaluation', 'data/raw', 'data/tokenizers',
             'data/processed/stage2', 'data/splits/stage2', 'data/private/stage0',
             'data/private/stage1', 'data/private/stage2']
    paths = {p for name in roots for p in (ROOT/name).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts}
    paths.update(ROOT/n for n in ('.gitignore', 'pyproject.toml', 'requirements-stage0.lock'))
    tracked = subprocess.check_output(['git', '-C', str(ROOT/'external/tau2-bench'), 'ls-files'],
                                      text=True, encoding='utf-8').splitlines()
    paths.update(ROOT/'external/tau2-bench'/n for n in tracked)
    return {p.relative_to(ROOT).as_posix(): file_hash(p) for p in sorted(paths)}


def freeze(path):
    path = Path(path)
    if path.exists():
        raise FileExistsError('Do not overwrite the starting inventory')
    write_json(path, {'fork': fork_state(), 'files': inventory()})


def verify_frozen(path):
    before = read_json(path)
    after = inventory()
    differences = sorted(n for n in set(before['files']) | set(after)
                         if before['files'].get(n) != after.get(n))
    return {'file_count': len(after), 'changed': differences, 'fork': fork_state(),
            'inventory_sha256': file_hash(path)}


@contextmanager
def offline_guard():
    """Block Python socket connections/binds; no real client belongs in this driver.

    This is a process-local test guard, not an OS sandbox against malicious code.
    """
    names = [(socket.socket, 'connect'), (socket.socket, 'connect_ex'),
             (socket.socket, 'bind'), (socket, 'create_connection'),
             (socket, 'getaddrinfo')]
    originals = [(obj, name, getattr(obj, name)) for obj, name in names]
    attempts = []
    def gate(original):
        def denied(*args, **kwargs):
            # Windows asyncio uses socket.py's loopback socketpair solely for
            # event-loop wakeup. Permit that exact stdlib call chain, never an
            # arbitrary loopback model/API connection or DNS request.
            caller = inspect.currentframe().f_back
            pair = wakeup = False
            while caller is not None:
                module = caller.f_globals.get('__name__','')
                pair |= module=='socket' and caller.f_code.co_name=='_fallback_socketpair'
                wakeup |= module.startswith('asyncio.') and caller.f_code.co_name=='_make_self_pipe'
                caller = caller.f_back
            address = args[1] if len(args)>1 else None
            if pair and wakeup and isinstance(address,tuple) and address[0] in ('127.0.0.1','::1'):
                return original(*args,**kwargs)
            attempts.append('blocked_socket_operation')
            raise RuntimeError('Stage 3_0 network disabled')
        return denied
    try:
        for obj, name, original in originals:
            setattr(obj, name, gate(original))
        yield attempts
    finally:
        for obj, name, original in originals:
            setattr(obj, name, original)
