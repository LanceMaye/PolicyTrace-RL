"""User-triggered private asset transfer archive; exact allowlist, no overwrites."""
import argparse
import json
from pathlib import Path
import hashlib
import zipfile

from policytrace.data.manifests import ROOT, read_json
from .assets import LOCK, verify_assets


def archive_path(path, root=ROOT):
    path = Path(path).resolve()
    if path.is_relative_to(root) and not path.is_relative_to(root/'data/private/stage3_1'):
        raise ValueError('Archive must be private; never use a tracked output directory')
    return path


def pack(path, root=ROOT):
    path = archive_path(path,root)
    if verify_assets(root)['status']!='PASS': raise ValueError('BLOCKED_DATA')
    path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in read_json(root/LOCK)['files']:
            archive.write(root/entry['path'],entry['path'])


def unpack(path, root=ROOT):
    lock = read_json(root/LOCK)
    allowed = {e['path']:e for e in lock['files']}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names)!=len(set(names)) or set(names)!=set(allowed):
            raise ValueError('Archive does not match exact frozen allowlist')
        contents = {}
        for name in names:
            target = (root/name).resolve()
            info = archive.getinfo(name)
            if not target.is_relative_to(root.resolve()) or target.relative_to(root.resolve()).as_posix()!=name or not name.startswith(('data/raw/','data/splits/stage2/','data/tokenizers/')):
                raise ValueError('Unsafe archive destination')
            if info.file_size!=allowed[name]['bytes'] or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe archive entry')
            value = archive.read(name)
            if hashlib.sha256(value).hexdigest()!=allowed[name]['sha256']:
                raise ValueError('Archive hash mismatch')
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=allowed[name]['sha256']:
                raise ValueError('Existing destination differs; refusing overwrite')
            contents[target] = value
        # Validate every entry and destination before any write; never extractall.
        for target, value in contents.items():
            if not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True)
                with target.open('xb') as stream: stream.write(value)
    if verify_assets(root)['status']!='PASS': raise ValueError('BLOCKED_DATA after extraction')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only inventory; pack/unpack only by explicit user command')
    parser.add_argument('--pack');parser.add_argument('--unpack')
    args = parser.parse_args(argv)
    if args.pack and args.unpack: parser.error('Choose one operation')
    if args.pack: pack(args.pack)
    if args.unpack: unpack(args.unpack)
    result = verify_assets()
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='PASS' else 2
