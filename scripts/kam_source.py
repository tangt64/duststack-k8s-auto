"""Resolve independently maintained KAM source with a pinned archive and file hashes."""
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('deploy/controller.py', 'deploy/render.py', 'deploy/render_auth.py', 'deploy/legacy-kubectl-kam')


def lock():
    value = json.loads((ROOT / 'config/kam-source.json').read_text(encoding='utf-8'))
    if not re.fullmatch('[a-f0-9]{40}', value['revision']) or not re.fullmatch('[a-f0-9]{64}', value['archive_sha256']):
        raise ValueError('KAM source must have a fixed commit and SHA-256')
    if not all(name in value['files_sha256'] for name in REQUIRED):
        raise ValueError('Missing KAM source hashes')
    return value


def verify(directory, pin, all_files=False):
    names = pin['files_sha256'] if all_files else REQUIRED
    for name in names:
        path = directory / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != pin['files_sha256'][name]:
            raise ValueError('Missing or modified pinned KAM source: ' + name)
    return directory


def source_path():
    # Explicit development override is never persisted into inventories or pins.
    if override := os.environ.get('KAM_SOURCE_DIR'):
        path = Path(override).resolve()
        if not all((path / name).is_file() for name in REQUIRED):
            raise ValueError('KAM_SOURCE_DIR does not contain the independent source tree')
        return path
    pin = lock()
    return verify(ROOT / '.tools/kam-source' / pin['revision'], pin, all_files=True)


def prepare():
    if os.environ.get('KAM_SOURCE_DIR'):
        return source_path()
    pin = lock()
    cache = ROOT / '.tools/kam-source'
    target = cache / pin['revision']
    if target.exists():
        return verify(target, pin, all_files=True)
    supplied = ROOT / 'artifacts' / ('kiki-kam-' + pin['revision'] + '.tar.gz')
    if supplied.exists():
        data = supplied.read_bytes()
    else:
        url = 'https://codeload.github.com/tangt64/KAM/tar.gz/' + pin['revision']
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != pin['archive_sha256']:
        raise ValueError('KAM archive size/SHA-256 mismatch')
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='prepare-', dir=cache) as folder:
        tmp = Path(folder)
        archive = tmp / 'source.tar.gz'
        archive.write_bytes(data)
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                    raise ValueError('KAM archive contains unsupported entries')
                if not (tmp / member.name).resolve().is_relative_to(tmp.resolve()):
                    raise ValueError('KAM archive path escapes cache')
            tar.extractall(tmp, filter='data')
        roots = [path for path in tmp.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise ValueError('KAM archive must contain one source root')
        verify(roots[0], pin, all_files=True)
        roots[0].rename(target)
    return target
