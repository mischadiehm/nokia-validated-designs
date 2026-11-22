# Two-Stripe Rail-Optimized NVIDIA Digital Twin - Ansible Variant

> **Status: render-validated, not yet run against a live lab.**

Same 22-node fabric as
[`../two-stripe-rail-optimized-with-ansible/`](../two-stripe-rail-optimized-with-ansible/)
- the upstream NVIDIA variant shares node names, stripe cabling and
configlets - with two deltas:

- **Four ESI-LAGs instead of twelve** on the frontend (s1..s4 bonds only;
  no weka nodes).
- **26-node topology** (22 SR Linux + 4 servers), from the upstream NVIDIA
  clab file with exec scripts removed.

Everything else (rail gateways, pinned ASN/system-IP map, DLB, ipv6
multipath, QoS configlets, the EVPN storage vnet) is identical and pinned by
the same `tests/test_render_invariants.py`.

## Try it

From this directory, on a host with ~45 GB free RAM (one validated-design
lab at a time):

```bash
uv sync
uv run ansible-galaxy collection install -r requirements.yml -p ./.collections
uv run pytest

sudo containerlab deploy -t two-stripe-rail-optimized-nvidia-with-ansible.clab.yaml  # 26 nodes

uv run ansible-playbook playbooks/deploy.yml --check --diff
uv run ansible-playbook playbooks/deploy.yml
sleep 30
uv run ansible-playbook playbooks/validate.yml
uv run ansible-playbook playbooks/deploy.yml                 # idempotency: changed=0
```

SR Linux `25.10.1`, login `admin` / `NokiaSrl1!`.

Tests, syntax check and lint pass with `narrowin.srlinux_intent` `0.1.0`, and
the offline upgrade check to `26.7.2` reports no breaking entries. The 22 SR
Linux nodes need about 44 GB, more than the lab VM has. One node of each group
(`stripe1-leaf1`, `spine1`, `frontend-leaf1`, `frontend-spine1`) was deployed
with `containerlab deploy --node-filter` and `--limit` on SR Linux `25.10.1`
and `26.7.2`. The devices accepted every operation, and a second run reported
no change. BGP state and traffic need the whole fabric and are not tested.

SR Linux 26.3 changed how `local-preference` is written.
`ansible/group_vars/<group>/srl_release_patches.yml` holds the new form, and
the `srl_config` role applies it only on 26.3 and newer, so one inventory
serves both releases.

Pointers: plan `/docs/plans/ansible-all-validated-designs-plan.md`; manifests
`../two-stripe-rail-optimized-nvidia/eda-manifests/`.
