import hashlib
import json
from pathlib import Path

from policytrace.evaluation.schema import DATASET_REVISION, ENVIRONMENT_SHA, task_set_hash

RULE_VERSION = 'policytrace-data-v1'
ROOT = Path(__file__).resolve().parents[3]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)


def write_jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        for record in records:
            stream.write(canonical(record) + '\n')


def verify_sources(root=ROOT):
    """Fail closed against the already pinned Stage 0 manifest, including all DBs."""
    manifest = read_json(root / 'reports/stage0/data_manifest.json')
    if manifest['revision'] != DATASET_REVISION:
        raise ValueError('Wrong dataset revision')
    checks = {}
    for name, entry in manifest['files'].items():
        path = root / 'data/raw' / name
        actual = file_hash(path)
        if actual != entry['sha256'] or path.stat().st_size != entry['size_bytes']:
            raise ValueError(f'Pinned source mismatch: {name}')
        checks[name] = {'sha256': actual, 'size_bytes': path.stat().st_size}
    return checks


def task_manifest(name, features):
    entries = sorted(features, key=lambda x: x['id'])
    ids = [x['id'] for x in entries]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate manifest ID')
    return {'version': RULE_VERSION, 'dataset_revision': DATASET_REVISION,
            'environment_sha': ENVIRONMENT_SHA, 'name': name, 'task_ids': ids,
            'task_set_sha256': task_set_hash(ids), 'entries': entries}


def quantiles(values):
    values = sorted(values)
    if not values:
        return None
    def q(f):
        # Explicit deterministic linear interpolation (same convention as numpy).
        p = (len(values) - 1) * f
        lower = int(p)
        return values[lower] + (values[min(lower + 1, len(values)-1)]-values[lower]) * (p-lower)
    return {'n': len(values), 'min': values[0], 'p50': q(.5), 'p90': q(.9),
            'p95': q(.95), 'p99': q(.99), 'max': values[-1], 'total': sum(values)}
