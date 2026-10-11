"""Immutable-revision safetensors download and offline verification, no forward."""
import argparse
import json
import re
import shutil
import struct
from pathlib import Path

from policytrace.data.manifests import ROOT, digest, file_hash, read_json
from policytrace.data.sft_tokenize import EXPECTED_FILES, TOKENIZER_REVISION
from .assets import exclusive_json

MODEL = 'Qwen/Qwen2.5-3B-Instruct'
RECEIPT = 'policytrace_model_receipt.json'


def revision(value):
    if not re.fullmatch('[0-9a-f]{40}', value or ''):
        raise ValueError('An immutable 40-character weight revision is required; main is not accepted')
    return value


def tensor_header(path):
    """Verify header, tensor offsets, shapes and payload lengths without loading tensors."""
    sizes = {'BF16': 2, 'F16': 2, 'F32': 4, 'F64': 8, 'I64': 8, 'I32': 4, 'I16': 2, 'I8': 1, 'U8': 1, 'BOOL': 1}
    with Path(path).open('rb') as stream:
        prefix = stream.read(8)
        if len(prefix) != 8:
            raise ValueError('Truncated safetensors header')
        n = struct.unpack('<Q', prefix)[0]
        if not 2 <= n <= 100_000_000:
            raise ValueError('Unsafe safetensors header length')
        header = json.loads(stream.read(n))
    entries, total = [], 0
    for key, tensor in header.items():
        if key == '__metadata__':
            continue
        shape, dtype = tensor['shape'], tensor['dtype']
        if dtype not in sizes or not isinstance(shape, list) or any(type(s) is not int or s < 0 for s in shape):
            raise ValueError('Unsupported tensor header')
        elements = 1
        for dim in shape:
            elements *= dim
        start, end = tensor['data_offsets']
        if type(start) is not int or type(end) is not int or start < 0 or end-start != elements*sizes[dtype]:
            raise ValueError('Tensor offsets disagree with shape/dtype')
        entries.append((start, end, key)); total += end-start
    cursor = 0
    for start, end, _ in sorted(entries):
        if start != cursor:
            raise ValueError('Overlapping or missing tensor payload')
        cursor = end
    if not entries or Path(path).stat().st_size != 8+n+cursor:
        raise ValueError('Truncated or extra safetensors payload')
    return {key for _, _, key in entries}, total


def inspect_model(directory):
    directory = Path(directory)
    for name, sha in EXPECTED_FILES.items():
        if file_hash(directory/name) != sha:
            raise ValueError('Downloaded tokenizer/template differs from the frozen Stage 2 tokenizer')
    config = read_json(directory/'config.json')
    expected = {'model_type':'qwen2', 'hidden_size':2048, 'num_hidden_layers':36,
                'num_attention_heads':16, 'num_key_value_heads':2, 'vocab_size':151936, 'eos_token_id':151645}
    if any(config.get(k) != v for k,v in expected.items()):
        raise ValueError('Wrong Student architecture or EOS')
    generation = read_json(directory/'generation_config.json')
    eos = generation.get('eos_token_id')
    if eos != 151645 and (not isinstance(eos, list) or 151645 not in eos):
        raise ValueError('Generation config EOS does not contain im_end')
    index = read_json(directory/'model.safetensors.index.json')
    weight_map = index['weight_map']
    shards = sorted(set(weight_map.values()))
    if not shards or any(Path(s).name != s or not s.endswith('.safetensors') for s in shards):
        raise ValueError('Unsafe shard index')
    if sorted(p.name for p in directory.glob('*.safetensors')) != shards:
        raise ValueError('Incomplete or extra model shards')
    if list(directory.glob('*.bin')) or list(directory.glob('*.pt')):
        raise ValueError('Pickle weights are not accepted')
    total, seen = 0, set()
    for shard in shards:
        keys, size = tensor_header(directory/shard)
        if seen & keys or keys != {k for k,v in weight_map.items() if v == shard}:
            raise ValueError('Shard tensors disagree with weight index')
        seen |= keys; total += size
    if index.get('metadata', {}).get('total_size') != total:
        raise ValueError('Weight payload size disagrees with index')
    names = ['config.json','generation_config.json','tokenizer.json','tokenizer_config.json','model.safetensors.index.json']+shards
    return {'files':{name:{'sha256':file_hash(directory/name),'bytes':(directory/name).stat().st_size} for name in names},
            'tensor_count':len(seen), 'tensor_payload_bytes':total}


def verify_model(directory, expected_revision=None):
    directory = Path(directory)
    receipt = read_json(directory/RECEIPT)
    revision(receipt['weight_revision'])
    if receipt['model_id'] != MODEL or receipt['tokenizer_revision'] != TOKENIZER_REVISION:
        raise ValueError('Model receipt provenance mismatch')
    if expected_revision and receipt['weight_revision'] != revision(expected_revision):
        raise ValueError('Weight revision mismatch')
    actual = inspect_model(directory)
    if actual != receipt['integrity']:
        raise ValueError('Model files changed after download verification')
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description='User-only download; default help/dry-run never downloads')
    parser.add_argument('--local-dir', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--source', choices=['hf'], default='hf')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args(argv)
    rev = revision(args.revision)
    directory = Path(args.local_dir).resolve()
    if directory.is_relative_to(ROOT) and not directory.is_relative_to(ROOT/'data/private'):
        raise ValueError('Use a cloud data directory or ignored data/private; never put weights in publishable code')
    if args.verify_only:
        verify_model(directory, rev)
        print(json.dumps({'status':'VERIFIED_OFFLINE','weight_revision':rev,'weights_loaded':False}))
        return
    if args.dry_run:
        print(json.dumps({'status':'DRY_RUN','model':MODEL,'weight_revision':rev,'source':'hf',
                          'download_executed':False,'weights_loaded':False,'required_free_bytes':10_000_000_000}))
        return
    # User must deliberately run this command later. No automatic invocation from checks.
    parent = next(p for p in (directory, *directory.parents) if p.exists())
    if shutil.disk_usage(parent).free < 10_000_000_000:
        raise ValueError('Insufficient disk space: require 10 GB free before download')
    if (directory/RECEIPT).exists():
        verify_model(directory, rev)
        print('{"status":"ALREADY_VERIFIED"}')
        return
    if directory.exists() and any(directory.iterdir()):
        raise ValueError('Nonempty directory without receipt; preserve interrupted download and use a new directory')
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL, revision=rev, local_dir=str(directory),
        allow_patterns=['config.json','generation_config.json','tokenizer.json','tokenizer_config.json',
                        'model.safetensors.index.json','*.safetensors'])
    integrity = inspect_model(directory)
    exclusive_json(directory/RECEIPT, {'model_id':MODEL,'weight_revision':rev,'tokenizer_revision':TOKENIZER_REVISION,
        'source':'huggingface_snapshot_download','integrity':integrity})
    print(json.dumps({'status':'DOWNLOADED_VERIFIED','weight_revision':rev,'weights_loaded':False}))


if __name__ == '__main__':
    main()
