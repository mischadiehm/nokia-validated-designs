#!/usr/bin/env bash
# Full gate matrix for two-stripe-rail-optimized-with-ansible (34 nodes).
# Run ON the debian-clab VM. RAM preflight: 22 SR Linux containers need
# roughly 50 GB; the script refuses to deploy without it.
set -euo pipefail

echo "== 0. sizing preflight =="
avail_gb=$(free -g | awk '/^Mem:/{print $7}')
if [ "${avail_gb}" -lt 50 ]; then
  echo "Only ${avail_gb} GB available; this lab needs ~50 GB."
  echo "Render gates (pytest/syntax/lint) still apply; run the lab on a bigger host."
  RENDER_ONLY=1
else
  RENDER_ONLY=0
fi

echo "== 1. runtime =="
uv sync
uv run ansible-galaxy collection install -r requirements.yml -p ./.collections --force-with-deps

echo "== 2. unit tests (render invariants, 22 nodes) =="
uv run pytest

echo "== 3. syntax + lint =="
uv run ansible-playbook playbooks/deploy.yml --syntax-check
uv run ansible-playbook playbooks/validate.yml --syntax-check
uv run ansible-lint playbooks/deploy.yml playbooks/validate.yml

[ "$RENDER_ONLY" = "1" ] && { echo "RENDER GATES GREEN (lab run skipped: RAM)"; exit 0; }

echo "== 4. fresh lab =="
sudo containerlab destroy -t two-stripe-rail-optimized-nvidia-with-ansible.clab.yaml --cleanup 2>/dev/null || true
sudo containerlab deploy -t two-stripe-rail-optimized-nvidia-with-ansible.clab.yaml   # expect 26 nodes

echo "== 5. preview / deploy / validate / idempotency =="
uv run ansible-playbook playbooks/deploy.yml --check --diff
uv run ansible-playbook playbooks/deploy.yml
sleep 30
uv run ansible-playbook playbooks/validate.yml
uv run ansible-playbook playbooks/deploy.yml | tee /tmp/two-stripe-nvidia-idem.log
grep -E "changed=0.*failed=0" /tmp/two-stripe-nvidia-idem.log | wc -l | grep -q 26 || {
  echo "idempotency gate FAILED"; exit 1; }

echo "ALL GATES GREEN"
