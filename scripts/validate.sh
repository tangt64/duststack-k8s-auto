#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
mkdir -p .tools/ansible-tmp
export ANSIBLE_LOCAL_TEMP="$PWD/.tools/ansible-tmp"
python scripts/check_source_tree.py
bash -n deploy-k8s.sh remove-k8s.sh provin-k8s.sh
ansible-playbook playbooks/k8s-install.yaml --syntax-check
ansible-playbook playbooks/k8s-uninstall.yaml --syntax-check
ansible-playbook playbooks/k8s-kubevirt-install.yaml --syntax-check
ansible-playbook playbooks/k8s-tools.yaml --syntax-check
ansible-playbook tests/roles.yaml --syntax-check
ansible-playbook -i localhost, tests/cli-tools.yaml --syntax-check
python -m unittest discover -s tests -v
if [[ "${RUN_CLI_INTEGRATION:-0}" == "1" ]]; then
  python tests/run_cli_integration.py
fi
