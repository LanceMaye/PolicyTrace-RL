"""Versioned SFT business policy; allow only its explicit patch to the pinned Fork."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE_FORK_SHA = 'e33e9511e4f51e5cfa16e12b02d0e4ab327b5887'
POLICY_VERSION = 'areal-retail-sft-v1'
POLICY_SHA256 = 'efd7cc72d1a553e11fe5c76e9ae27c092f0bbb9f2541066f4e0bd2d6134af936'
ORIGINAL_FILE_SHA256 = '4313d3fef8acf919f555fa17fbce929cc3ed1cef2dd8f0d35ff5c8c3364de176'
POLICY_REL = 'data/tau2/domains/retail/policy.md'


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _git(root, *args):
    return subprocess.check_output(['git', '-C', str(root/'external/tau2-bench'), *args],stderr=subprocess.PIPE)


def policy_bundle(root=None):
    root = Path(root or ROOT)
    config = json.loads((root/'configs/policy/custom_retail_v1.json').read_text(encoding='utf-8'))
    if (config['version'], config['base_fork_commit'], config['policy_sha256']) != (
            POLICY_VERSION, BASE_FORK_SHA, POLICY_SHA256):
        raise ValueError('Unrecognized custom policy version or hash')
    if config['max_tool_calls_per_turn'] is not None or not config['forbid_text_with_tool_calls']:
        raise ValueError('Custom policy protocol drift')
    custom = root/config['policy_source']
    backup = root/config['original_backup']
    if _sha(custom.read_bytes()) != POLICY_SHA256:
        raise ValueError('Custom policy source changed')
    if _sha(backup.read_bytes()) != ORIGINAL_FILE_SHA256:
        raise ValueError('Original policy backup changed')
    return config


def verify_fork(root=None):
    """Reject changed tools/evaluators, staged changes, extra files or policy drift."""
    root = Path(root or ROOT)
    config = policy_bundle(root)
    commit = _git(root, 'rev-parse', 'HEAD').decode().strip()
    if commit != BASE_FORK_SHA:
        raise ValueError('Pinned Fork commit changed')
    changed = _git(root, 'diff', '--name-only', 'HEAD').decode().splitlines()
    extras = _git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines()
    staged = _git(root, 'diff', '--cached', '--name-only').decode().splitlines()
    if changed != [POLICY_REL] or extras or staged:
        raise ValueError('Fork changes exceed the authorized policy patch')
    installed = root/'external/tau2-bench'/POLICY_REL
    if _sha(installed.read_bytes()) != POLICY_SHA256:
        raise ValueError('Installed Retail policy differs from the SFT policy')
    committed = _git(root, 'show', f'{BASE_FORK_SHA}:{POLICY_REL}').decode('utf-8')
    backup = (root/config['original_backup']).read_text(encoding='utf-8')
    if committed.replace('\r\n', '\n') != backup:
        raise ValueError('Backup does not match the original committed policy')
    return {'commit': commit, 'status': _git(root, 'status', '--porcelain').decode().strip(),
            'upstream_working_tree_clean': False, 'authorized_policy_patch_only': True,
            'policy_version': POLICY_VERSION, 'policy_sha256': POLICY_SHA256,
            'patch_sha256': _sha(_git(root, 'diff', '--no-ext-diff', 'HEAD', '--', POLICY_REL))}


def install_policy_patch(root=None):
    """Apply the retained policy bundle to a fresh clean checkout, without fetching."""
    root = Path(root or ROOT)
    config = policy_bundle(root)
    if _git(root, 'rev-parse', 'HEAD').decode().strip() != BASE_FORK_SHA:
        raise ValueError('Wrong base Fork commit')
    status = _git(root, 'status', '--porcelain').decode().strip()
    if status:
        return verify_fork(root)
    installed = root/'external/tau2-bench'/POLICY_REL
    committed = _git(root, 'show', f'{BASE_FORK_SHA}:{POLICY_REL}').decode('utf-8')
    if installed.read_text(encoding='utf-8') != committed.replace('\r\n', '\n'):
        raise ValueError('Unexpected clean checkout policy')
    installed.write_bytes((root/config['policy_source']).read_bytes())
    return verify_fork(root)


def active_policy(root=None):
    root = Path(root or ROOT)
    config = policy_bundle(root)
    installed = root/'external/tau2-bench'/POLICY_REL
    if _sha(installed.read_bytes()) != POLICY_SHA256:
        raise ValueError('Installed Retail policy differs from the active bundle')
    return config


def student_system(policy):
    """Preserve the exact business policy span; the shared Qwen wrapper supplies instructions."""
    return '<policy>' + policy + '</policy>'
