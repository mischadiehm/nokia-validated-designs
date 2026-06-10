# Two-Stripe Rail-Optimized AI Fabric NVD - Ansible Variant

> **Status: render-validated, not yet run against a live lab.** The intent is
> derived from the EDA manifests (ai-dc has no CLI reference). 22 SR Linux
> nodes + 12 servers need roughly 50 GB RAM.

An Ansible-driven build of the rail-optimized AI fabric: two 8-leaf stripes
(IXR-H4 / IXR-H5-64D) joined by two stripe-connector spines, plus a frontend
fabric (2x IXR-H5-64O spines, 2x IXR-D5 leaves) carrying an EVPN-VXLAN
storage vnet for 4 storage servers and 8 weka nodes. No EDA - readable YAML
intent rendered by the nokia.srlinux collection (md fork tag `v1.2.0-md.1`).

## The design (derivation rules)

The manifests in [`../two-stripe-rail-optimized/`](../two-stripe-rail-optimized/)
are the source; each rule is pinned by `tests/test_render_invariants.py`.

- **Configlets verbatim.** DLB (flow-dynamic, flowset 256, weighting
  70/20/10, `::/0`), ipv6 eBGP multipath (max-paths 2) and the
  egress-backend QoS profiles (WRED/ECN 30..85, unicast-0 burst 5211064,
  scheduler weights, PFC headroom 10) reproduce
  `configlet-{dlb,ipv6-multipath,qos}.yaml` path-for-path on every leaf and
  spine in their endpointSelector.
- **Rails routed in the default NI.** The single `all-rails` isolation group
  means no per-rail vrfs. Per-port /96 rail gateways are `:0:1` (servers
  `:0:2`); eBGP over IPv6-unnumbered uplinks to both spines carries the rail
  subnets between stripes - the path DLB and multipath act on.
- **Pinned allocation** (EDA pool draws are not reproducible): backend leaf
  ASN = 100 + leafindex (101..116), spines 100, system0
  192.0.2.<leafindex>; frontend leaves 121/122 + .33/.34, spines 120 +
  .31/.32. Documented in `group_vars/srl/srl_config.yml`.
- **Frontend storage vnet:** EVPNVXLAN EVI/VNI 100 with proxy-ARP per
  `frontend-vnets.yaml`, and twelve all-active ESI-LAGs (4 storage + 8 weka
  bonds across both leaves; ESIs/admin-keys pinned in the group layer).
- **Endpoint routes added** (the upstream scripts configure only the
  frontend bonds): per-NIC sibling-rail routes plus a cross-stripe route via
  the leaf1 rail make same-stripe and cross-stripe reachability testable.

Containerlab accepts the H4/H5 QoS and DLB config; PFC/ECN/DLB behavior
needs hardware.

## Where things are

```text
ansible/
  inventory.yml                       # 22 SRL nodes + s1..s4 + weka1..weka8
  group_vars/srl/                     # connection + layer merge + pinned ASN map
  group_vars/backend_leaves/          # underlay + DLB + multipath + QoS
  group_vars/backend_spines/          # 16-port stripe connector + QoS
  group_vars/frontend_leaves/         # EVPN storage vnet + 12 ESI-LAGs
  group_vars/frontend_spines/
  host_vars/                          # per-node remainder + endpoint intent
  roles/linux_endpoint/
playbooks/{deploy,validate,render}.yml
tests/test_render_invariants.py
two-stripe-rail-optimized-with-ansible.clab.yaml
```

## Try it

From this directory, on a host with ~50 GB free RAM (one validated-design
lab at a time):

```bash
uv sync
uv run ansible-galaxy collection install -r requirements.yml -p ./.collections
uv run pytest                                                # derivation-rule gate

sudo containerlab deploy -t two-stripe-rail-optimized-with-ansible.clab.yaml  # 34 nodes

uv run ansible-playbook playbooks/deploy.yml --check --diff
uv run ansible-playbook playbooks/deploy.yml
sleep 30
uv run ansible-playbook playbooks/validate.yml
uv run ansible-playbook playbooks/deploy.yml                 # idempotency: changed=0
```

SR Linux image `25.10.1` (matches upstream). Login `admin` / `NokiaSrl1!`.

## Pointers

- Plan: `/docs/plans/ansible-all-validated-designs-plan.md`
- Derivation source: `../two-stripe-rail-optimized/eda-manifests/`
- NVIDIA digital-twin sibling: `../two-stripe-rail-optimized-nvidia-with-ansible/`
