#!/usr/bin/env bash
# Full gate matrix for the 3-stage-evpn-vxlan-clab-with-ansible lab.
# Run ON the debian-clab VM from this directory. Only one validated-design lab
# can run at a time (shared eda_mgmt subnet) - destroy any other lab first.
set -euo pipefail

echo "== 0. runtime =="
uv sync
uv run ansible-galaxy collection install -r requirements.yml -p ./.collections --force-with-deps

echo "== 1. unit tests (fidelity vs without-eda oracle) =="
uv run pytest

echo "== 2. syntax + lint =="
uv run ansible-playbook playbooks/deploy.yml --syntax-check
uv run ansible-playbook playbooks/validate.yml --syntax-check
uv run ansible-lint playbooks/deploy.yml playbooks/validate.yml

echo "== 3. fresh lab =="
sudo containerlab destroy -t 3-stage-with-ansible.clab.yaml --cleanup 2>/dev/null || true
sudo containerlab deploy -t 3-stage-with-ansible.clab.yaml   # expect 17 nodes

echo "== 4. preview =="
uv run ansible-playbook playbooks/deploy.yml --check --diff

echo "== 5. deploy =="
uv run ansible-playbook playbooks/deploy.yml

echo "== 6. converge + validate =="
sleep 30   # LACP / ES / BGP convergence
uv run ansible-playbook playbooks/validate.yml

echo "== 7. idempotency =="
uv run ansible-playbook playbooks/deploy.yml | tee /tmp/3stage-idem.log
[ "$(grep -cE 'changed=0.*unreachable=0.*failed=0' /tmp/3stage-idem.log)" -eq 17 ] || {
  echo "idempotency gate FAILED"; exit 1; }

echo "== 8. data plane =="
uv run tools/clab-network-tester --config network-tests/3-stage-with-ansible.yml

echo "ALL GATES GREEN"
