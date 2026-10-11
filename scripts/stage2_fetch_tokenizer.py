"""Download ONLY the two pinned tokenizer files; never resolve model weights."""
import hashlib
import json
from pathlib import Path
import urllib.request

MODEL = 'Qwen/Qwen2.5-3B-Instruct'
REVISION = 'aa8e72537993ba99e69dfaafa59ed015b17504d1'
FILES = ('tokenizer.json', 'tokenizer_config.json')


def main():
    root = Path('data/tokenizers/qwen2.5-3b-instruct')
    root.mkdir(parents=True, exist_ok=True)
    entries = {}
    for name in FILES:
        path = root / name
        if not path.exists():
            url = f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}'
            request = urllib.request.Request(url, headers={'User-Agent': 'PolicyTrace-Stage2-tokenizer-only'})
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read(16 * 1024 * 1024 + 1)
            if len(payload) > 16 * 1024 * 1024:
                raise ValueError('Tokenizer file exceeds the explicit size limit')
            json.loads(payload)
            path.write_bytes(payload)
        payload = path.read_bytes()
        entries[name] = {'sha256': hashlib.sha256(payload).hexdigest(), 'size_bytes': len(payload)}
    manifest = {'model': MODEL, 'revision': REVISION, 'files': entries, 'weights_downloaded': False}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
