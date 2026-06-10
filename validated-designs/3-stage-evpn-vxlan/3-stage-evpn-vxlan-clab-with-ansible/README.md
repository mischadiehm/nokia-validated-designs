# 3-Stage EVPN-VXLAN NVD - Ansible Variant

> **Status: implemented, render-validated against the without-eda oracle.**
> The full live gate matrix runs on the lab VM via `./run-gates-vm.sh`.

An Ansible-driven build of the 3-stage EVPN-VXLAN fabric (2 spines, 6 leaves,
9 Linux endpoints) on [Containerlab](https://containerlab.dev) with Nokia
SR Linux. Each node's intent lives as readable YAML; the
`nokia.srlinux.to_config_operations` filter renders it into native SR Linux
operations applied in one validated transaction per node.

Sibling variants build the same topology with other tooling:
[`with-eda`](../3-stage-evpn-vxlan-clab-with-eda/) (EDA-orchestrated) and
[`without-eda`](../3-stage-evpn-vxlan-clab-without-eda/) (static CLI). The
without-eda `configs/*.cli` files are this variant's **fidelity oracle**: a
pytest gate proves the rendered operations match them leaf-path for leaf-path.

## The ideas

- **Intent is readable YAML, not raw gNMI.** Layered with deep-merge:
  `srl_common` (every node) -> `srl_spine_common` / `srl_leaf_common` (role)
  -> `srl_host` (per node). The leaf layer carries the full service catalog
  (six anycast-IRB mac-vrfs, vrf1/vrf2, the vxlan tunnel map); host vars carry
  only the per-leaf remainder (ASN, system0, access ports, LAGs/ESIs,
  event-handler).
- **The engine lives in the collection.** `requirements.yml` pins the
  nokia.srlinux md fork (`v1.2.0-md.1`): renderer, schema-catalog guard,
  pruning filters, and the `srl_config`/`srl_validate` roles. No lab-local
  filter plugins.
- **Fidelity is a test, not a hope.** `tests/test_cli_fidelity.py` parses
  every oracle `.cli` line through the same renderer and asserts rendered ==
  oracle for all 8 nodes, both directions. One reviewed exception is
  documented in the test (upstream leaf6.cli omits
  `advertise-arp-nd-only-with-mac-table-entry` on macvrf-v50 only; the
  Ansible catalog stays uniform).
- **`update:` + targeted `delete:`, not `replace:`** - same contract as the
  collapsed-spine variant.

## Where things are

```text
ansible/
  inventory.yml                   # spines, leaves, linux_clients (s1..s9)
  group_vars/srl/connection.yml   # JSON-RPC connection, lab creds
  group_vars/srl/srl_config.yml   # layer merge + srl_common
  group_vars/spines/srl_config.yml# ISL fan-out, dynamic neighbors 65411-65416
  group_vars/leaves/srl_config.yml# ISLs, IRBs, service catalog, vxlan map
  host_vars/<node>.yml            # per-node remainder; endpoint intent for s1..s9
  roles/linux_endpoint/           # bonds (incl. active-backup primary), VLANs,
                                  # dummies, VRF devices, prefix routes
playbooks/
  deploy.yml                      # nokia.srlinux.srl_config + linux_endpoint
  validate.yml                    # nokia.srlinux.srl_validate + endpoint pings
  render.yml                      # test helper: render ops for fidelity pytest
tests/test_cli_fidelity.py        # rendered intent == without-eda configs
network-tests/3-stage-with-ansible.yml  # data-plane flow matrix
tools/clab-network-tester         # flow runner (unit-tested in collapsed lab)
3-stage-with-ansible.clab.yaml    # topology (no startup configs, no exec scripts;
                                  # keeps the node-isolation.py bind)
run-gates-vm.sh                   # full gate matrix, run on the lab VM
```

## Try it

From this directory, on the lab VM (only one validated-design lab at a time -
all labs share mgmt subnet 172.21.21.0/24):

```bash
./run-gates-vm.sh
```

or step by step:

```bash
uv sync
uv run ansible-galaxy collection install -r requirements.yml -p ./.collections
uv run pytest                                                # fidelity oracle gate
sudo containerlab deploy -t 3-stage-with-ansible.clab.yaml   # expect 17 nodes
uv run ansible-playbook playbooks/deploy.yml --check --diff
uv run ansible-playbook playbooks/deploy.yml
sleep 30
uv run ansible-playbook playbooks/validate.yml
uv run ansible-playbook playbooks/deploy.yml                 # idempotency: changed=0
uv run tools/clab-network-tester --config network-tests/3-stage-with-ansible.yml
```

SR Linux image: `25.10.1` (repo version policy: newest release with a
published yang-browser catalog; the upstream NVD was authored and tested on
`24.10.2` - see `docs/plans/ansible-all-validated-designs-plan.md`).
Login `admin` / `NokiaSrl1!`.

## The design

eBGP underlay on IPv6-unnumbered ISLs (dynamic neighbors, BFD 1s x3) carrying
an EVPN overlay in the same sessions. Spines share AS 65500; leaf1..leaf6 use
65411..65416 with system0 192.0.2.11..16 (spines .101/.102).

| Service | EVI/VNI | IRB (anycast .254/24) | Attachments |
|---|---|---|---|
| macvrf-v10 | 10 / 10010 | irb0.0, vrf1 | s1 (leaf1 e1-3, **tagged**), s2 (leaf2+3, active-backup bond) |
| macvrf-v20 | 20 / 10020 | irb0.1, vrf1 | s3 (leaf4 e1-3, untagged) |
| macvrf-v30 | 30 / 10030 | irb0.5, vrf1 | s4 (lag1: leaf4+5, all-active), s6 (lag3: leaf5+6, **single-active**, DF pref 800/500, LACP standby signaling) |
| macvrf-v40 | 40 / 10040 | irb0.2, vrf2 | s7 (leaf1 e1-5) |
| macvrf-v50 | 50 / 10050 | irb0.3, vrf2 | s8 (lag2: leaf2-5, 4-way all-active) |
| macvrf-v60 | 60 / 10060 | irb0.4, vrf2 | s9 (leaf6 e1-6) |
| vrf1 / vrf2 | 500/10500, 501/10501 | - | L3 EVIs; vrf1 also carries the s5 routed access (leaf1 e1-4.4097, 172.16.100.0/31) and type-5 statics 172.16.92-95.0/24 |

Node-isolation event-handler (leaf2..leaf5 only): `node-isolation.py` is
bind-mounted by the topology (file distribution stays a clab concern); the
event-handler *config* is Ansible intent, per-leaf `down-links` exactly as the
oracle defines them.

Endpoint quirk mirrored on purpose: upstream `s5.sh` puts 172.16.93.5/24 on
both lo2 and lo3 and never assigns anything from 172.16.95.0/24 even though
leaf1 static-routes it. The intent mirrors the scripts; the quirk is noted
here and in `host_vars/s5.yml`.

## Validation

- `uv run pytest` - CLI fidelity for all 8 SR Linux nodes (plus the render
  harness itself).
- `playbooks/validate.yml` - intent-derived state assertions per node (BGP
  established, LAG oper-state with standby tolerance, ethernet-segments up,
  network-instances present) + endpoint pings, including s5 VRF-sourced pings
  and `/proc/net/bonding` checks on every bonded endpoint.
- `network-tests/3-stage-with-ansible.yml` - data-plane flows: intra-VLAN over
  every ESI-LAG, cross-VLAN through both ip-vrfs, EVPN type-5 to the s5
  loopbacks.

## Pointers

- Plan and decisions: `/docs/plans/ansible-all-validated-designs-plan.md`
- Engine: nokia.srlinux md fork, tag `v1.2.0-md.1`
- Oracle: `../3-stage-evpn-vxlan-clab-without-eda/configs/*.cli`
