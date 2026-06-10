# Lenovo-AMD-Nokia AI Fabric NVD - Ansible Variant

> **Status: implemented, render-validated; intent is derived.** Unlike the
> 3-stage and collapsed-spine variants there is no CLI oracle - the EDA
> manifests in [`../lenovo-amd-nokia-ai-fabric/`](../lenovo-amd-nokia-ai-fabric/)
> are the only config source. Every derivation rule is pinned by a pytest
> invariant and the live acceptance checks in `playbooks/validate.yml`
> (run `./run-gates-vm.sh` on the lab VM).

Ansible-driven build of the Lenovo-Nokia AI fabric: 2 backend leaves
(IXR-H4, RoCEv2 rails), 2 frontend leaves (IXR-D3L) and 2 storage leaves
(IXR-D5), with 2 GPU servers, a frontend server and a storage server. No EDA,
no Kubernetes - readable YAML intent rendered by the `nokia.srlinux`
collection engine (md fork tag `v1.2.0-md.1`).

## Derivation rules (each one is a pytest invariant)

1. **Per-port /96 rail subnets.** The gpu scripts pin the server side
   (`fd00:100:<leaf>:1:0:<port>:0:1`, with gpu1 eth1 using `:0:2` - an
   upstream quirk mirrored as-is). The leaf gateway takes the complement
   address of each /96.
2. **Rails are leaf-local ip-vrfs.** `gpuIsolationGroups` rail1..rail8 select
   port pairs (P, P+4): leaf1 owns rail1..rail4, leaf2 owns rail5..rail8.
   Same-rail gpu-to-gpu traffic routes through the leaf inside the rail vrf;
   cross-rail traffic must fail - both are asserted live in validate.yml.
   (The upstream gpu scripts set no routes at all, so same-rail reachability
   was untestable in the with-eda twin; this variant adds per-rail peer
   routes on the GPUs to make the acceptance check real.)
3. **gpuVlan 100 maps to subinterface index 100**, port-routed without vlan
   encap, because the gpu scripts address the raw interface (untagged).
4. **RoCEv2 QoS from the Backend resource**, on paths verified against the
   SR Linux v25.10.1 release path catalog: WRED/ECN slopes 5..80 percent
   (max-drop 100), pfc-queue maximum-burst-size 52110640,
   PFC deadlock detection/recovery 750 ms, linecard pfc-buffer-reservation
   10, per-rail-port `output/buffer-allocation-profile` binding. Containerlab
   proves config acceptance only - PFC/ECN behavior needs hardware.
5. **Frontend and storage are SIMPLE bridge domains** (mac-vrf, no EVPN):
   frontend spans both leaves over a two-link LACP LAG (e1-2/e1-3, admin-key
   11 - chosen, no oracle); storage is leaf-local (the storage server bridges
   both leaves, the gpu storage bonds are active-backup primary eth10).
6. **No fabric protocol.** The spineless backend renders no BGP/EVPN; the
   ASN/system-IP pools from the manifests only inform system0 addressing
   (192.0.2.1/.2 by leaf index). A render invariant asserts no
   `/protocols/bgp` path exists, which also keeps the srl_validate role's
   BGP/ES checks auto-skipped.

## Where things are

```text
ansible/
  inventory.yml                       # backend/frontend/storage leaves + endpoints
  group_vars/srl/connection.yml       # JSON-RPC, lab creds
  group_vars/srl/srl_config.yml       # layer merge (fabrics share nothing)
  group_vars/backend_leaves/          # RoCEv2 QoS profiles (catalog-verified paths)
  group_vars/frontend_leaves/         # SIMPLE BD + inter-leaf LACP LAG
  group_vars/storage_leaves/          # SIMPLE BD, leaf-local
  host_vars/backend-leaf{1,2}.yml     # rails: per-port /96 gateways + rail vrfs + QoS binding
  host_vars/{gpu1,gpu2}.yml           # rail IPv6 + peer routes, bonds, pings (+ must-fail)
  host_vars/{frontend-server,storage}.yml
  roles/linux_endpoint/               # + bridge support (storage br0)
playbooks/{deploy,validate,render}.yml
tests/test_render_invariants.py       # derivation rules pinned
lenovo-nokia-ai-fabric-with-ansible.clab.yaml  # no exec scripts; image per version policy
run-gates-vm.sh                       # full live gate matrix
```

## Try it

On the lab VM, from this directory (one validated-design lab at a time):

```bash
./run-gates-vm.sh
```

SR Linux image `25.10.1` (repo version policy; upstream variant was tested on
`25.3.2` with EDA 25.4.2). Login `admin` / `NokiaSrl1!`.

## Pointers

- Plan, version policy, derivation worksheet:
  `/docs/plans/ansible-all-validated-designs-plan.md`
- EDA intent source: `../lenovo-amd-nokia-ai-fabric/eda-manifests/`
- Endpoint truth: `../lenovo-amd-nokia-ai-fabric/base-configs/*.sh`
