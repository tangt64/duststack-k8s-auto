"""Label only a dedicated Rook host directory; keep SELinux enforcing and disks intact."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def checked_path(value):
    if not re.fullmatch(r'/var/lib/rook(?:-[A-Za-z0-9_-]+)?', value):
        raise ValueError('Use /var/lib/rook or a dedicated /var/lib/rook-NAME directory')
    path = Path(value)
    if path.is_symlink() or path.resolve() != path or (path.exists() and not path.is_dir()):
        raise ValueError('Rook host directory must be a canonical directory without symlinks')
    return path


def prepare(value, run=subprocess.run):
    path = checked_path(value)
    created = not path.exists()
    path.mkdir(mode=0o755, exist_ok=True)
    env = dict(os.environ, LC_ALL='C')
    pattern = re.escape(str(path)) + '(/.*)?'
    result = run(['semanage', 'fcontext', '-l', '-C'], env=env, check=True, capture_output=True, text=True)
    records = [line.split() for line in result.stdout.splitlines() if line.split() and line.split()[0] == pattern]
    if len(records) > 1:
        raise ValueError('Ambiguous local SELinux records for the Rook directory; review manually')
    expected = 'system_u:object_r:container_file_t:s0'
    changed_rule = not records or records[0][-1] != expected
    if changed_rule:
        run(['semanage', 'fcontext', '-m' if records else '-a', '-t', 'container_file_t', '-r', 's0', pattern],
            env=env, check=True, capture_output=True, text=True)
    # No symlink traversal; -x also prevents crossing into other mounted filesystems.
    restored = run(['restorecon', '-RFvx', str(path)], env=env, check=True, capture_output=True, text=True)
    return {'directory': str(path), 'changed': created or changed_rule or bool(restored.stdout.strip())}


if __name__ == '__main__':
    print(json.dumps(prepare(sys.argv[1])))
