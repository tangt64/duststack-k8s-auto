#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
if [[ -d .venv/bin ]]; then export PATH="$PWD/.venv/bin:$PATH"; fi
operation="${1:-help}"
if [[ $# -gt 0 ]]; then shift; fi
case "$operation" in
  deps)
    controller_python="${DUSTSTACK_PYTHON:-python3.12}"
    "$controller_python" -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
    exec .venv/bin/ansible-galaxy collection install -r requirements.yaml "$@"
    ;;
  configure) exec python scripts/configure.py "$@" ;;
  check) exec bash scripts/validate.sh "$@" ;;
  plan) exec ansible-playbook playbooks/k8s-install.yaml --check --diff "$@" ;;
  install) exec ansible-playbook playbooks/k8s-install.yaml "$@" ;;
  storage) exec ansible-playbook playbooks/k8s-storage.yaml "$@" ;;
  tools) exec ansible-playbook playbooks/k8s-tools.yaml "$@" ;;
  *)
    printf '%s\n' '사용법: bash setup-k8s.sh {deps|configure|check|plan|install|storage|tools} [옵션]'       'configure --help: 설치 인벤토리 생성 안내'       'plan/install/storage/tools: -i 인벤토리 및 Ansible 옵션 전달'
    ;;
esac
