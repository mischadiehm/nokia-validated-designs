#!/usr/bin/env bash
# Full gate matrix for the lenovo-amd-nokia-ai-fabric-with-ansible lab.
# Run ON the debian-clab VM from this directory. One lab at a time
# (shared eda_mgmt subnet) - destroy any other lab first.
set -euo pipefail

echo "== 0. runtime =="
uv sync
uv run ansible-galaxy collection install -r requirements.yml -p ./.collections --force-with-deps

echo "== 1. unit tests (render invariants) =="
uv run pytest

echo "== 2. syntax + lint =="
uv run ansible-playbook playbooks/deploy.yml --syntax-check
uv run ansible-playbook playbooks/validate.yml --syntax-check
uv run ansible-lint playbooks/deploy.yml playbooks/validate.yml

echo "== 3. fresh lab =="
sudo containerlab destroy -t lenovo-nokia-ai-fabric-with-ansible.clab.yaml --cleanup 2>/dev/null || true
sudo containerlab deploy -t lenovo-nokia-ai-fabric-with-ansible.clab.yaml   # expect 10 nodes

echo "== 4. preview =="
uv run ansible-playbook playbooks/deploy.yml --check --diff

echo "== 5. deploy =="
uv run ansible-playbook playbooks/deploy.yml

echo "== 6. converge + validate (incl. cross-rail isolation must-fail) =="
sleep 20
uv run ansible-playbook playbooks/validate.yml

echo "== 7. idempotency =="
uv run ansible-playbook playbooks/deploy.yml | tee /tmp/lenovo-idem.log
[ "$(grep -cE 'changed=0.*unreachable=0.*failed=0' /tmp/lenovo-idem.log)" -eq 10 ] || {
  echo "idempotency gate FAILED"; exit 1; }

echo "ALL GATES GREEN"
