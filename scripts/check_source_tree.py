"""Reject binary payloads and broken local Markdown links in project sources."""
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
