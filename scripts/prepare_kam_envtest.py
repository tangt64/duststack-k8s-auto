"""Fetch a fixed official envtest bundle into the ignored local test cache."""
import hashlib
import os
from pathlib import Path
import tempfile
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SHA256 = 'f03faedfc68d2a78cee5cb02618bb44e7f67044f4c5fc957f72d3307fda61a9c'
URL = 'https://github.com/kubernetes-sigs/controller-tools/releases/download/envtest-v1.37.0/envtest-v1.37.0-linux-amd64.tar.gz'



def extract_verified(bundle, cache):
    # Do not truncate executables that another local API test is running.
    # Compare against the already verified official archive; replace changed files atomically.
    for name in ['etcd', 'kube-apiserver', 'kubectl']:
        member = bundle.getmember('controller-tools/envtest/' + name)
        if not member.isfile() or member.size > 150 * 1024 * 1024:
            raise ValueError('Invalid envtest member')
        data = bundle.extractfile(member).read()
        target = cache / member.name
        if target.is_symlink():
            raise ValueError('Refusing symlink envtest executable')
        if target.is_file() and hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(data).digest():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
                temporary.chmod(0o755)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)


def main():
    cache = ROOT / '.tools/envtest'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / 'envtest.tar.gz'
    if not archive.exists():
        with urlopen(URL, timeout=120) as response:
            content = response.read(100 * 1024 * 1024 + 1)
        if len(content) > 100 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != SHA256:
            raise ValueError('envtest download size/checksum mismatch')
        archive.write_bytes(content)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Cached envtest checksum mismatch; refusing to execute')
    with tarfile.open(archive) as bundle:
        extract_verified(bundle, cache)
    print('Verified official envtest v1.37.0 SHA-256')


if __name__ == '__main__':
    main()
