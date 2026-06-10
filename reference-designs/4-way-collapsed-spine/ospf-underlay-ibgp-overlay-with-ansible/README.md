# 4-Way Collapsed Spine (OSPF Underlay / iBGP Overlay) - Ansible Variant

> **Status: render-validated, not yet run against a live lab.** Poke holes.

OSPF sibling of
[`../ebgp-underlay-ibgp-overlay-with-ansible/`](../ebgp-underlay-ibgp-overlay-with-ansible/):
same four collapsed spines, tors, ESI-LAGs, services and endpoints, with the
underlay swapped to OSPFv2 (area 0, ISLs with BFD, passive system0,
IPv4-unnumbered ISLs borrowing lo0 172.16.1.10x, per-spine OSPF router-id =
lo0) and the iBGP EVPN overlay running over a single shared AS 65500 with
BFD on system0.0. `../ospf-underlay-ibgp-overlay/configs/*.cli` is the
fidelity oracle, proven by `uv run pytest` for all 7 nodes.

Mirrored upstream quirks: no host-names at all, bare e1-7 admin-state on
spine1/spine2 (the otherwise dark s9 ports), a bare `ip-forwarding`
container on spine2, `local-as` kept on spine3/spine4 only, and the same
irb0.70/s8 gateway quirk as the eBGP sibling.

## Try it

```bash
uv sync
uv run ansible-galaxy collection install -r requirements.yml -p ./.collections
uv run pytest

sudo containerlab deploy -t 4-way-ospf-ibgp-with-ansible.clab.yaml   # 17 nodes

uv run ansible-playbook playbooks/deploy.yml --check --diff
uv run ansible-playbook playbooks/deploy.yml
sleep 30
uv run ansible-playbook playbooks/validate.yml
uv run ansible-playbook playbooks/deploy.yml                 # idempotency: changed=0
uv run tools/clab-network-tester --config network-tests/4-way-ospf-ibgp-with-ansible.yml
```

SR Linux image `25.10.1`; login `admin` / `NokiaSrl1!`. Layout, gates and
pointers match the eBGP sibling; plan:
`/docs/plans/ansible-reference-designs-plan.md`.
