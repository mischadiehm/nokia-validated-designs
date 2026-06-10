# 4-Way Collapsed Spine (eBGP Underlay / iBGP Overlay) - Ansible Variant

> **Status: render-validated, not yet run against a live lab.** Poke holes.

Ansible-driven build of this reference design: four collapsed spines in a
full-mesh eBGP underlay (per-spine AS 65501..65504, IPv6-unnumbered ISLs,
BFD) with an iBGP EVPN overlay (AS 65500, loopback peering, multihop), three
plain L2 tors behind ESI-LAGs (spine1+2 -> tor1, all four -> tor2, spine3+4
-> tor3) and ten endpoints. Intent is readable YAML rendered by the
nokia.srlinux collection (md fork tag `v1.2.0-md.1`);
`../ebgp-underlay-ibgp-overlay/configs/*.cli` is the fidelity oracle, proven
by `uv run pytest` for all 7 nodes (including the spine `delete /` lines).

Mirrored upstream quirks (documented, not fixed): BGP router-id 192.0.2.1<n>
differs from the system IP 192.0.2.10<n>; host-name only on spine1/spine3;
spine2 carries a stray bare lo0; irb0.70 reuses the v60 gateway address so
s8's gateway does not exist; spine1/spine2 leave the s9 bond ports entirely
unconfigured. s8/s9 therefore have no ping targets.

## Where things are

```text
ansible/
  inventory.yml                    # spines(4), tors(3), linux_clients (s1..s10)
  group_vars/srl/                  # connection + layer merge
  group_vars/spines/               # mesh underlay, overlay, services, lag2, IRBs
  group_vars/tors/                 # placeholder (tors are fully per-host)
  host_vars/<node>.yml             # per-spine services/lag1/IDs, tors, endpoints
  roles/linux_endpoint/
playbooks/{deploy,validate,render}.yml
tests/test_cli_fidelity.py         # rendered intent == oracle configs
network-tests/4-way-ebgp-ibgp-with-ansible.yml
tools/clab-network-tester
4-way-ebgp-ibgp-with-ansible.clab.yaml
```

## Try it

From this directory, on the lab host (one lab at a time - all labs share
mgmt subnet 172.21.21.0/24):

```bash
uv sync
uv run ansible-galaxy collection install -r requirements.yml -p ./.collections
uv run pytest                                                # fidelity oracle gate

sudo containerlab deploy -t 4-way-ebgp-ibgp-with-ansible.clab.yaml   # 17 nodes

uv run ansible-playbook playbooks/deploy.yml --check --diff
uv run ansible-playbook playbooks/deploy.yml
sleep 30
uv run ansible-playbook playbooks/validate.yml
uv run ansible-playbook playbooks/deploy.yml                 # idempotency: changed=0
uv run tools/clab-network-tester --config network-tests/4-way-ebgp-ibgp-with-ansible.yml
```

SR Linux image `25.10.1` (repo version policy; oracle authored on `25.3.2`).
Login `admin` / `NokiaSrl1!`.

## Pointers

- Plan: `/docs/plans/ansible-reference-designs-plan.md`
- Oracle: `../ebgp-underlay-ibgp-overlay/{configs,base-configs}/`
- OSPF sibling: `../ospf-underlay-ibgp-overlay-with-ansible/`
