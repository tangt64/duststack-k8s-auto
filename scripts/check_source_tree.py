"""Reject executable artifacts; allow only named, validated documentation screenshots."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.tools', '.venv', 'artifacts', '__pycache__', '.pytest_cache', 'node_modules'}
REMOVED_EXECUTABLES = (
    'roles/extension/kubevirt/files/virtctl-v0.54.0',
    'roles/kubernetes/k8s-ocm/hub/files/clusteradm',
    'roles/kubernetes/k8s-ocm/spoke/files/clusteradm',
)
APPROVED_SCREENSHOTS = {
    'docs/screenshots/' + name for name in (
        '01-lab-vms.jpg', '02-controller-ready.jpg', '03-source-validation.jpg',
        '04-cilium-connectivity.jpg', '05-nfs-pvc-io.jpg', '06-rook-pvc-io.jpg',
        '07-gitea-actions.jpg', '08-ha-vip-failover.jpg', '09-kam-live-cluster.jpg',
        '10-ha-vm-power-loss.jpg', '11-etcd-quorum.jpg', '12-kam-fast-handover.jpg',
    )
}


def valid_documentation_jpeg(data):
    """Check JPEG framing, bounded size and an actual frame-size marker."""
    if not (data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9')) or len(data) > 2 * 1024 * 1024:
        return False
    position = 2
    while position + 4 < len(data):
        if data[position] != 0xff:
            return False
        while position < len(data) and data[position] == 0xff:
            position += 1
        if position >= len(data):
            return False
        marker = data[position]
        position += 1
        if marker in (0xda, 0xd9):
            return False
        if marker == 0x01 or 0xd0 <= marker <= 0xd7:
            continue
        length = int.from_bytes(data[position:position + 2], 'big')
        if length < 2 or position + length > len(data):
            return False
        if marker in (0xc0, 0xc1, 0xc2):
            if length < 8:
                return False
            height = int.from_bytes(data[position + 3:position + 5], 'big')
            width = int.from_bytes(data[position + 5:position + 7], 'big')
            return 100 <= width <= 4096 and 100 <= height <= 4096
        position += length
    return False


def check(root=ROOT):
    errors = []
    files = []
    def walk(directory):
        for path in sorted(directory.iterdir()):
            if path.name in EXCLUDED or path.is_symlink():
                continue
            if path.is_dir():
                walk(path)
            elif path.is_file():
                files.append(path)
    walk(root)
    # Ignored local artifacts are allowed; force-added artifacts must fail in CI.
    if (root / '.git').exists():
        tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--cached', '-z'])
        for raw in tracked.split(b'\0'):
            if not raw:
                continue
            name = raw.decode('utf-8')
            if any(part in EXCLUDED for part in Path(name).parts):
                errors.append(f'Cache/artifact file committed as source: {name}')
    for name in REMOVED_EXECUTABLES:
        if (root / name).exists():
            errors.append(f'Removed bundled executable is present: {name}')
    for path in files:
        data = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        if relative in APPROVED_SCREENSHOTS:
            if not valid_documentation_jpeg(data):
                errors.append(f'Invalid or oversized documentation screenshot: {relative}')
            continue
        try:
            if b'\0' in data:
                raise ValueError('NUL byte')
            text = data.decode('utf-8')
        except (UnicodeDecodeError, ValueError):
            errors.append(f'Binary payload in source tree: {path.relative_to(root)}')
            continue
        if path.suffix.lower() != '.md':
            continue
        text = re.sub(r'```.*?```', '', text, flags=re.S)
        for target in re.findall(r'\]\(([^)]+)\)', text):
            target = target.strip().split(' "', 1)[0].strip('<>')
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('#'):
                continue
            target = target.split('#', 1)[0]
            if target and not (path.parent / target).exists():
                errors.append(f'Broken Markdown link in {path.relative_to(root)}: {target}')
    return errors, len(files)


if __name__ == '__main__':
    errors, count = check()
    for error in errors:
        print(error, file=sys.stderr)
    print(f'Checked {count} source files: {len(errors)} binary/link errors')
    raise SystemExit(bool(errors))
