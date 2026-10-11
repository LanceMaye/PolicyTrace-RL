"""Byte-only frozen asset checks, and explicitly selected runtime task loading."""
import json
import re
from pathlib import Path

from policytrace.data.manifests import ROOT, digest, file_hash, read_json
from policytrace.data.task_pool import RLTaskPool
from policytrace.stage0.task_loader import load_retail_task

LOCK = 'configs/harness/stage3_1_assets.lock.json'
SPLITS = {'dev': 'data/splits/stage2/rl_dev.json', 'test': 'data/splits/stage2/rl_test_frozen.json'}
SMOKE_IDS = ('retail_131', 'retail_152', 'retail_245')


def verify_assets(root=ROOT):
    root = Path(root)
    lock = read_json(root/LOCK)
    issues = []
    for entry in lock['files']:
        p = root/entry['path']
        if not p.is_file():
            issues.append({'code': 'missing', 'path': entry['path']})
        elif p.stat().st_size != entry['bytes'] or file_hash(p) != entry['sha256']:
            issues.append({'code': 'hash_mismatch', 'path': entry['path']})
    # Manifest contains IDs/hashes only; no scenario/reference task body is loaded.
    if not issues:
        for split, name in SPLITS.items():
            pool = RLTaskPool(root/name, root)
            expected = lock['splits'][split]
            if len(pool.entries) != expected['count'] or pool.manifest['task_set_sha256'] != expected['task_set_sha256']:
                issues.append({'code': 'split_mismatch', 'path': name})
            if split == 'dev' and not set(SMOKE_IDS) <= set(pool.entries):
                issues.append({'code': 'smoke_not_in_dev', 'path': name})
    return {'status': 'PASS' if not issues else 'BLOCKED_DATA', 'required_files': len(lock['files']),
            'required_bytes': sum(e['bytes'] for e in lock['files']), 'issues': issues,
            'lock_sha256': file_hash(root/LOCK), 'test_bodies_deserialized': 0,
            'categories': {
                'GIT_TRACKED_CODE': {'publication_list':'reports/stage3_1/git_safety_audit.json', 'meaning':'Git publication candidates; root repository may not be initialized'},
                'GIT_IGNORED_PRIVATE_REQUIRED_E0': {'files':len(lock['files']), 'bytes':sum(e['bytes'] for e in lock['files'])},
                'GIT_IGNORED_PRIVATE_OPTIONAL_STAGE4': {'required_for_e0':False, 'local_inventory':'data/private/stage3_1/optional_stage4_inventory.json'},
                'DOWNLOAD_ON_REMOTE_BY_USER': {'model_id':'Qwen/Qwen2.5-3B-Instruct','weights_downloaded_by_preparation':False},
                'RUNTIME_SECRET_MANUAL': {'environment_variable':'DEEPSEEK_API_KEY','value_in_inventory':False}}}


class SelectedRecords:
    def __init__(self, root, authorized_ids):
        self.root, self.authorized_ids = root, frozenset(authorized_ids)

    def __getitem__(self, task_id):
        if task_id not in self.authorized_ids:
            raise ValueError('Task body is outside the explicitly authorized plan')
        with (self.root/'data/raw/tau2_rl_train.jsonl').open('rb') as stream:
            for index, line in enumerate(stream, 1):
                match = re.match(rb'\s*\{\s*"id"\s*:\s*"([^"]+)"', line)
                if match is None:
                    raise ValueError('Unknown root ID envelope; refusing full-body fallback')
                if match[1].decode('utf-8') == task_id:
                    return load_retail_task(json.loads(line), index)
        raise ValueError('Authorized task not found')


class RuntimeTaskPool(RLTaskPool):
    def __init__(self, split, authorized_ids, *, confirmed_test=False, root=ROOT):
        if split not in SPLITS or (split == 'test' and not confirmed_test):
            raise ValueError('Frozen Test requires explicit runtime confirmation')
        check = verify_assets(root)
        if check['status'] != 'PASS':
            raise ValueError('BLOCKED_DATA')
        super().__init__(Path(root)/SPLITS[split], root)
        if not set(authorized_ids) <= set(self.entries):
            raise ValueError('Plan contains tasks outside the frozen split')
        self.selected = SelectedRecords(self.root, authorized_ids)

    @property
    def records(self):
        return self.selected


def private_path(path, *, root=ROOT):
    path = Path(path).resolve()
    if not path.is_relative_to((Path(root)/'data/private/stage3_1').resolve()):
        raise ValueError('Runtime output must be under data/private/stage3_1')
    return path


def exclusive_json(path, data):
    """Never overwrite a protocol, attempt or evidence file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
