# 3-Stage EVPN-VXLAN NVD - Ansible Variant

> **Status: render-validated, not yet run against a live lab.** Poke holes.

An Ansible-driven build of the 3-stage EVPN-VXLAN fabric (2 spines, 6 leaves,
9 Linux endpoints) on [Containerlab](https://containerlab.dev) with Nokia
SR Linux. Each node's intent lives as readable YAML; the nokia.srlinux
collection renders it into native SR Linux operations and applies them in one
validated transaction per node.

Sibling variants build the same topology with other tooling:
[`with-eda`](../3-stage-evpn-vxlan-clab-with-eda/) (EDA-orchestrated) and
[`without-eda`](../3-stage-evpn-vxlan-clab-without-eda/) (static CLI).

## The ideas

- **Intent is readable YAML, layered by role.** `srl_common` (every node) ->
  `srl_spine_common` / `srl_leaf_common` -> `srl_host`. The leaf layer carries
  the full service catalog (six anycast-IRB mac-vrfs, vrf1/vrf2, the vxlan
  map); host vars carry only the per-node remainder (ASN, system0, access
  ports, LAGs/ESIs, event-handler).
- **The engine lives in the collection.** `requirements.yml` pins the
  nokia.srlinux md fork (`v1.2.0-md.1`): renderer, schema-catalog guard,
  pruning filters, and the `srl_config`/`srl_validate` roles. No lab-local
  filter plugins.
- **The without-eda configs are the oracle.** `uv run pytest` renders every
  node and asserts equality with `../3-stage-evpn-vxlan-clab-without-eda/configs/*.cli`,
  both directions (one upstream omission on leaf6 is documented in the test).
- **`update:` + targeted `delete:`, not `replace:`** - same contract as the
  collapsed-spine variant.

## Where things are

```text
ansible/
  inventory.yml                   # spines, leaves, linux_clients (s1..s9)
  group_vars/srl/connection.yml   # JSON-RPC connection, lab creds
  group_vars/srl/srl_config.yml   # layer merge + srl_common
  group_vars/spines/srl_config.yml
  group_vars/leaves/srl_config.yml
  host_vars/<node>.yml            # per-node remainder; endpoint intent for s1..s9
  roles/linux_endpoint/           # bonds, VLANs, dummies, VRF devices, routes
playbooks/
  deploy.yml                      # nokia.srlinux.srl_config + linux_endpoint
  validate.yml                    # nokia.srlinux.srl_validate + endpoint pings
  render.yml                      # test helper for the fidelity pytest
tests/test_cli_fidelity.py        # rendered intent == without-eda configs
network-tests/3-stage-with-ansible.yml  # data-plane flow matrix
tools/clab-network-tester         # flow runner
3-stage-with-ansible.clab.yaml    # topology (no startup configs / exec scripts;
                                  # keeps the node-isolation.py bind)
```

## Try it

From this directory, on the lab host. All validated-design labs share mgmt
subnet 172.21.21.0/24 - run one lab at a time.

```bash
uv sync
uv run ansible-galaxy collection install -r requirements.yml -p ./.collections
uv run pytest                                                # fidelity oracle gate

sudo containerlab deploy -t 3-stage-with-ansible.clab.yaml   # expect 17 nodes

uv run ansible-playbook playbooks/deploy.yml --check --diff
uv run ansible-playbook playbooks/deploy.yml
sleep 30                                                     # LACP / ES / BGP convergence
uv run ansible-playbook playbooks/validate.yml
uv run ansible-playbook playbooks/deploy.yml                 # idempotency: changed=0
uv run tools/clab-network-tester --config network-tests/3-stage-with-ansible.yml
```

SR Linux image `25.10.1` (repo version policy; the upstream NVD was authored
on `24.10.2`). Login `admin` / `NokiaSrl1!`.

> **Note:** endpoint config is ephemeral - a containerlab redeploy wipes it,
> so re-run `deploy.yml` (or `--limit linux_clients`) after one. SR Linux
> config persists across redeploys.

## The design

eBGP underlay on IPv6-unnumbered ISLs (dynamic neighbors, BFD 1s x3) carrying
the EVPN overlay in the same sessions. Spines share AS 65500; leaf1..leaf6
use 65411..65416 with system0 192.0.2.11..16 (spines .101/.102).

| Service | EVI/VNI | IRB (anycast .254/24) | Attachments |
|---|---|---|---|
| macvrf-v10 | 10 / 10010 | irb0.0, vrf1 | s1 (leaf1 e1-3, **tagged**), s2 (leaf2+3, active-backup bond) |
| macvrf-v20 | 20 / 10020 | irb0.1, vrf1 | s3 (leaf4 e1-3) |
| macvrf-v30 | 30 / 10030 | irb0.5, vrf1 | s4 (lag1: leaf4+5, all-active), s6 (lag3: leaf5+6, **single-active**, DF pref 800/500, LACP standby signaling) |
| macvrf-v40 | 40 / 10040 | irb0.2, vrf2 | s7 (leaf1 e1-5) |
| macvrf-v50 | 50 / 10050 | irb0.3, vrf2 | s8 (lag2: leaf2-5, 4-way all-active) |
| macvrf-v60 | 60 / 10060 | irb0.4, vrf2 | s9 (leaf6 e1-6) |
| vrf1 / vrf2 | 500/10500, 501/10501 | - | L3 EVIs; vrf1 also carries the s5 routed access (leaf1 e1-4.4097, 172.16.100.0/31) and type-5 statics 172.16.92-95.0/24 |

Node-isolation event-handler runs on leaf2..leaf5: the topology bind-mounts
`node-isolation.py` (file distribution is a clab concern); the event-handler
config is intent, with per-leaf `down-links`.

Validation: `validate.yml` asserts intent-derived state per node (BGP
established, LAG oper-state with standby tolerance, ethernet-segments up,
network-instances present) plus endpoint pings, including s5 VRF-sourced
pings and bond state on every bonded endpoint. The network-tests matrix
covers intra-VLAN over every ESI-LAG, cross-VLAN through both ip-vrfs, and
EVPN type-5 to the s5 loopbacks.

## Pointers

- Plan and decision history: `/docs/plans/ansible-all-validated-designs-plan.md`
- Engine: nokia.srlinux md fork, tag `v1.2.0-md.1`
- Oracle: `../3-stage-evpn-vxlan-clab-without-eda/configs/*.cli`
