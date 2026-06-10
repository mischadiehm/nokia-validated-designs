# Ansible Lab Validation Record

Date: 2026-06-10

This record tracks the Ansible-managed Nokia SR Linux lab validation run from
the `debian-clab` OrbStack environment. Commands were run with `uv run`; live
Containerlab and Ansible runtime actions were run inside `debian-clab`.

## Live Green

- collapsed-spine: pytest, syntax, lint, preview, deploy, validate,
  idempotency `changed=0 failed=0`, and dataplane `214/214`.
- ai-dc lenovo: offline gates, preview, deploy, validate including rail
  isolation, and idempotency `changed=0 failed=0`. Dataplane coverage is in
  `validate.yml`; this lab has no separate network-tests flow file.
- 3-stage validated: offline gates, preview, deploy, validate, idempotency
  `changed=0 failed=0`, and dataplane `10/10`.
- reference 3-stage eBGP/iBGP: offline gates, preview, deploy, validate,
  idempotency `changed=0 failed=0`, and dataplane `10/10`.
- reference 3-stage OSPF/iBGP: offline gates, preview, deploy, validate,
  idempotency `changed=0 failed=0`, and dataplane `10/10`.
- reference 4-way collapsed eBGP/iBGP: offline gates, preview, deploy,
  validate, idempotency `changed=0 failed=0`, and dataplane `5/5`.
- reference 4-way collapsed OSPF/iBGP: offline gates, preview, deploy,
  validate, idempotency `changed=0 failed=0`, and dataplane `5/5`.

## Offline Green, Live Deferred

- ai-dc nvidia twin: pytest, deploy syntax-check, and ansible-lint passed.
- ai-dc two-stripe: pytest, deploy syntax-check, and ansible-lint passed.

Live boot for the two remaining AI labs is deferred because the `debian-clab`
VM reports 31 GB total RAM and each remaining AI topology defines 22 SR Linux
nodes plus Linux endpoints.

## Runtime Notes

- The local `nokia.srlinux` collection was rebuilt and installed into each lab
  `.collections` path before validation.
- The local collection unit tests passed: `98 passed`.
- The top-level working-session plan remains in
  `/Users/md/git/network/nokia/docs/plans/2026-06-10-lab-validation-execution.md`;
  that directory is not inside a git repository.

## Open Work

- Live boot, deploy, validate, idempotency, and dataplane checks remain open for
  the two large AI labs:
  - `validated-designs/ai-dc/two-stripe-rail-optimized-nvidia-with-ansible`
  - `validated-designs/ai-dc/two-stripe-rail-optimized-with-ansible`
- Both large AI labs passed offline gates on 2026-06-10: `uv sync`, local
  collection install, `uv run pytest`, deploy syntax-check, and ansible-lint.
- No lab topology is intentionally left running from this validation pass.

## Search Terms

- `2026-06-10 lab validation execution`
- `Ansible Lab Validation Record`
- `collapsed-spine live green 214/214`
- `ai-dc two-stripe offline green live deferred`

## Collapsed-Spine Runbook

Run these commands inside `debian-clab`. They start the validated-design
collapsed-spine Ansible lab, configure it, validate it, and leave it ready for
use.

```bash
cd /Users/md/git/network/nokia/nokia-srlinux-ansible-collection-md-fork
uv run ansible-galaxy collection build --output-path /tmp --force

cd /Users/md/git/network/nokia/nokia-validated-designs-md-fork/validated-designs/collapsed-spine/collapsed-spine-with-ansible
uv sync
uv run ansible-galaxy collection install -r requirements.yml
uv run ansible-galaxy collection install /tmp/nokia-srlinux-1.2.0.tar.gz -p ./.collections --force

uv run pytest
uv run ansible-playbook playbooks/deploy.yml --syntax-check
uv run ansible-lint playbooks/deploy.yml playbooks/validate.yml

containerlab deploy -t 2-way-collapsed-spine.clab.yaml
uv run ansible-playbook playbooks/deploy.yml --check --diff
uv run ansible-playbook playbooks/deploy.yml
sleep 30
uv run ansible-playbook playbooks/validate.yml
uv run ansible-playbook playbooks/deploy.yml
uv run tools/clab-network-tester --config network-tests/2-way-collapsed-spine.yml --once
```

Expected healthy results:

- `containerlab deploy` creates 11 nodes.
- `uv run ansible-playbook playbooks/validate.yml` finishes with `failed=0`.
- The second `uv run ansible-playbook playbooks/deploy.yml` finishes with
  `changed=0 failed=0`.
- The network tester reports `Summary: passed=214 failed=0 total=214`.

Optional cleanup after testing:

```bash
containerlab destroy -t 2-way-collapsed-spine.clab.yaml --cleanup
```
