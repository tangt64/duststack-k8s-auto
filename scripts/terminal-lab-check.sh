#!/usr/bin/env bash
# Run from a Terminal Lab web terminal after setup-k8s.sh deps.
# This script validates sources and artifacts; it does not install Kubernetes.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ -d .venv/bin ]]; then export PATH="$PWD/.venv/bin:$PATH"; fi
export RUN_CLI_INTEGRATION=1
export RUN_CHART_VALIDATION=1
bash scripts/validate.sh
python - <<'PY'
import json, platform, subprocess
from pathlib import Path
memory = next(line for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:'))
report = {
    'status': 'passed',
    'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'kernel': platform.release(),
    'python': platform.python_version(),
    'memory': memory,
    'checks': ['source-policy', 'markdown-links', 'ansible-syntax', 'regression-tests', 'cli-acquisition', 'official-chart-lint-render'],
    'cluster_deployment_performed': False,
    'pvc_io_performed': False,
}
Path('.tools/terminal-lab-validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('TERMINAL_LAB_VALIDATION=PASS')
print(json.dumps(report))
PY
