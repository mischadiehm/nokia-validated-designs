# Lenovo-AMD-Nokia AI Fabric NVD - Ansible Variant

> **Status: render-validated, not yet run against a live lab.** The intent is
> derived from the EDA manifests (ai-dc has no CLI reference) - poke holes at
> the derivation rules below.

An Ansible-driven build of the Lenovo-Nokia AI fabric: 2 backend leaves
(IXR-H4, RoCEv2 rails), 2 frontend leaves (IXR-D3L), 2 storage leaves
(IXR-D5), 2 GPU servers, a frontend server and a storage server. No EDA, no
Kubernetes - readable YAML intent rendered by the nokia.srlinux collection
(md fork tag `v1.2.0-md.1`).

## The design (derivation rules)

The EDA manifests in [`../lenovo-amd-nokia-ai-fabric/`](../lenovo-amd-nokia-ai-fabric/)
are the source; each rule below is pinned by `tests/test_render_invariants.py`.

- **Rails are leaf-local routed /96s.** Every (leaf, port) pair is its own
  IPv6 /96; the gpu scripts pin the server side, the leaf gateway takes the
  complement address. `gpuVlan 100` maps to subinterface index 100
  (port-routed, untagged - the gpu scripts address the raw interface).
- **Rail isolation = ip-vrf per rail.** `gpuIsolationGroups` rail1..rail8
  select port pairs (P, P+4): leaf1 owns rail1..4, leaf2 owns rail5..8.
  Same-rail gpu-to-gpu traffic routes inside the rail vrf; cross-rail traffic
  must fail - `validate.yml` asserts both live.
- **RoCEv2 QoS from the Backend resource:** WRED/ECN slopes 5..80 percent
  (max-drop 100), SR Linux `pfc0` queue burst 52110640, PFC deadlock 750 ms, linecard
  pfc-buffer-reservation 10, per-rail-port buffer-allocation binding.
  Containerlab accepts the config; PFC/ECN behavior needs hardware.
- **Frontend and storage are SIMPLE bridge domains** (mac-vrf, no EVPN):
  frontend spans both leaves over a two-link LACP LAG; storage is leaf-local
  (the storage server bridges both leaves, gpu storage bonds are
  active-backup).
- **No fabric protocol.** The spineless backend renders no BGP/EVPN; the
  manifests' pools only inform system0 addressing (192.0.2.1/.2).

GPU endpoints carry per-rail peer routes (the upstream scripts set none) so
the same-rail acceptance ping is actually testable; upstream quirks like the
gpu1-eth1 `:0:2` address are mirrored as-is and commented in the host vars.

## Where things are

```text
ansible/
  inventory.yml                     # backend/frontend/storage leaves + endpoints
  group_vars/srl/                   # connection + layer merge
  group_vars/backend_leaves/        # RoCEv2 QoS profiles
  group_vars/frontend_leaves/       # SIMPLE BD + inter-leaf LACP LAG
  group_vars/storage_leaves/        # SIMPLE BD, leaf-local
  host_vars/backend-leaf{1,2}.yml   # rail gateways + rail vrfs + QoS binding
  host_vars/{gpu1,gpu2,frontend-server,storage}.yml
  roles/linux_endpoint/             # bonds, bridges, rail IPv6, routes
playbooks/{deploy,validate,render}.yml
tests/test_render_invariants.py
lenovo-nokia-ai-fabric-with-ansible.clab.yaml
```

## Try it

From this directory, on the lab host (one validated-design lab at a time):

```bash
uv sync
uv run ansible-galaxy collection install -r requirements.yml -p ./.collections
uv run pytest                                                # derivation-rule gate

sudo containerlab deploy -t lenovo-nokia-ai-fabric-with-ansible.clab.yaml  # 10 nodes

uv run ansible-playbook playbooks/deploy.yml --check --diff
uv run ansible-playbook playbooks/deploy.yml
sleep 20
uv run ansible-playbook playbooks/validate.yml               # incl. cross-rail must-fail
uv run ansible-playbook playbooks/deploy.yml                 # idempotency: changed=0
```

SR Linux image `25.10.1` (repo version policy; upstream was tested on
`25.3.2` with EDA 25.4.2). Login `admin` / `NokiaSrl1!`.

## Pointers

- Plan, version policy, derivation worksheet:
  `/docs/plans/ansible-all-validated-designs-plan.md`
- EDA intent source: `../lenovo-amd-nokia-ai-fabric/eda-manifests/`
- Endpoint truth: `../lenovo-amd-nokia-ai-fabric/base-configs/*.sh`
