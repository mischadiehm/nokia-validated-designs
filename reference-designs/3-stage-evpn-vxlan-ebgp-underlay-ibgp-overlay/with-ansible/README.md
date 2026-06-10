# 3-Stage EVPN-VXLAN (eBGP Underlay / iBGP Overlay) - Ansible Variant

> **Status: render-validated, not yet run against a live lab.** Poke holes.

Ansible-driven build of this reference design: the same 2-spine / 6-leaf /
9-endpoint topology as the validated 3-stage NVD, but with a split control
plane - an eBGP ipv4 underlay (group `underlay`) and an iBGP EVPN overlay
(group `overlay`, AS 65500) where the spines are route reflectors
(cluster-id 1) and peering runs between system0 loopbacks with multihop and
BFD on `system0.0`. Intent is readable YAML rendered by the nokia.srlinux
collection (md fork tag `v1.2.0-md.1`); the `../configs/*.cli` files are the
fidelity oracle, proven by `uv run pytest` for all 8 nodes (including the
oracle's `delete /` lines).

Mirrored upstream quirks (documented, not fixed): the spine configs carry no
host-name and no LLDP, the leaves keep two legacy accept-all dc1 policy
shells, and leaf6 omits one macvrf-v50 leaf the other leaves have (accepted
exception in the fidelity test).

## Where things are

```text
ansible/
  inventory.yml                    # spines, leaves, linux_clients (s1..s9)
  group_vars/srl/                  # connection + layer merge + shared intent
  group_vars/spines/               # ISLs, RR overlay (cluster-id 1, neighbors)
  group_vars/leaves/               # ISLs, service catalog, overlay neighbors
  host_vars/<node>.yml             # ASN, system0, overlay local-address, access
  roles/linux_endpoint/
playbooks/{deploy,validate,render}.yml
tests/test_cli_fidelity.py         # rendered intent == ../configs/*.cli
network-tests/3-stage-ebgp-ibgp-with-ansible.yml
tools/clab-network-tester
3-stage-ebgp-ibgp-with-ansible.clab.yaml
```

## Try it

From this directory, on the lab host (one lab at a time - all labs share
mgmt subnet 172.21.21.0/24):

```bash
uv sync
uv run ansible-galaxy collection install -r requirements.yml -p ./.collections
uv run pytest                                                # fidelity oracle gate

sudo containerlab deploy -t 3-stage-ebgp-ibgp-with-ansible.clab.yaml   # 17 nodes

uv run ansible-playbook playbooks/deploy.yml --check --diff
uv run ansible-playbook playbooks/deploy.yml
sleep 30
uv run ansible-playbook playbooks/validate.yml
uv run ansible-playbook playbooks/deploy.yml                 # idempotency: changed=0
uv run tools/clab-network-tester --config network-tests/3-stage-ebgp-ibgp-with-ansible.yml
```

SR Linux image `25.10.1` (repo version policy; the oracle was authored on
`25.3.2`). Login `admin` / `NokiaSrl1!`.

## Pointers

- Plan: `/docs/plans/ansible-reference-designs-plan.md`
- Oracle: `../configs/*.cli`; endpoints `../base-configs/*.sh`
- Services/topology details: identical to the validated 3-stage variant
  (`/validated-designs/3-stage-evpn-vxlan/3-stage-evpn-vxlan-clab-with-ansible/`);
  only the underlay/overlay control plane differs.
