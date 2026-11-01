"""Fetch a fixed official envtest bundle into the ignored local test cache."""
import hashlib
from pathlib import Path
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SHA256 = 'f03faedfc68d2a78cee5cb02618bb44e7f67044f4c5fc957f72d3307fda61a9c'
URL = 'https://github.com/kubernetes-sigs/controller-tools/releases/download/envtest-v1.37.0/envtest-v1.37.0-linux-amd64.tar.gz'


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
        bundle.extractall(cache, filter='data')
    print('Verified official envtest v1.37.0 SHA-256')


if __name__ == '__main__':
    main()
