"""Fetch only pinned public Stage 0 inputs; no model weights or API calls."""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "86971dc03da6e7c1a7933295e05b84aab8215386"


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def main() -> None:
    raw = ROOT / "data/raw"
    reports = ROOT / "reports/stage0"
    raw.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    base = "https://huggingface.co/datasets/inclusionAI/AReaL-tau2-data"
    tree = json.loads(get(f"https://huggingface.co/api/datasets/inclusionAI/AReaL-tau2-data/tree/{REVISION}?recursive=true"))
    (reports / "dataset_files.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")
    names = ["README.md", "tau2_rl_train.jsonl"]
    names += [f"tau2_rl_database/tau2_retail_new_db_{i}.json" for i in range(1, 5)]
    names += ["tau2_sft_train.jsonl"]
    manifest = {}
    for name in names:
        target = raw / name
        target.parent.mkdir(parents=True, exist_ok=True)
        entry = next(x for x in tree if x['path'] == name)
        expected = entry.get('lfs', {}).get('oid')
        if not target.exists() or target.stat().st_size != entry['size']:
            print(f"Downloading {name}: {entry['size']} bytes", flush=True)
            tmp = target.with_suffix(target.suffix + '.part')
            offset = tmp.stat().st_size if tmp.exists() else 0
            if offset != entry['size']:
                headers = {'Range':f'bytes={offset}-'} if offset else {}
                request = urllib.request.Request(f"{base}/resolve/{REVISION}/{name}", headers=headers)
                with urllib.request.urlopen(request, timeout=120) as response:
                    if response.status == 206 and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):
                        raise ValueError(f"Unexpected resume range: {name}")
                    mode = 'ab' if offset and response.status == 206 else 'wb'
                    with tmp.open(mode) as out:
                        while chunk := response.read(1024 * 1024):
                            out.write(chunk)
            if tmp.stat().st_size != entry['size']:
                raise ValueError(f"Incomplete download: {name}")
            tmp.replace(target)
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if expected and digest != expected:
            raise ValueError(f"SHA256 mismatch: {name}")
        manifest[name] = {'size_bytes': target.stat().st_size, 'sha256': digest, 'upstream_sha256': expected}
        (reports / 'data_manifest.json').write_text(json.dumps({'revision': REVISION, 'files': manifest}, indent=2), encoding='utf-8')
        print(f"Verified {name}", flush=True)


if __name__ == '__main__':
    main()
