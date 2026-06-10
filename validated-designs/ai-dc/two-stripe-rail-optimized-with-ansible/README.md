# Two-Stripe Rail-Optimized AI Fabric NVD - Ansible Variant

> **Status: implemented, render-validated; intent is derived.** 22 SR Linux
> nodes + 12 servers (~50 GB RAM): `./run-gates-vm.sh` checks sizing first and
> stops after the render gates on smaller hosts - the lab then runs unchanged
> on bigger hardware.

Ansible-driven build of the flagship rail-optimized AI fabric: two 8-leaf
stripes (IXR-H4 / IXR-H5-64D) joined by two stripe-connector spines, plus a
frontend fabric (2x IXR-H5-64O spines, 2x IXR-D5 leaves) carrying an
EVPN-VXLAN storage vnet for 4 storage servers and 8 weka nodes. No EDA - the
manifests in [`../two-stripe-rail-optimized/`](../two-stripe-rail-optimized/)
are the derivation source, rendered by the `nokia.srlinux` collection engine
(md fork tag `v1.2.0-md.1`).

## Derivation rules (each one is a pytest invariant)

1. **Configlets verbatim.** DLB (`flowset-size "256"`, inactivity 50,
   flow-dynamic, sampling 5, weighting 70/20/10, `::/0` in the default NI),
   ipv6 eBGP multipath (`allow-multiple-as`, `ebgp maximum-paths 2`), and the
   egress-backend QoS profiles (WRED/ECN 30..85 max-drop 100, unicast-0 burst
   5211064, scheduler weights 80/10+w10, PFC headroom 10) reproduce
   `configlet-{dlb,ipv6-multipath,qos}.yaml` path-for-path on every leaf and
   spine in the configlet endpointSelector.
2. **Rails routed in the default NI.** The single `all-rails` isolation group
   means no per-rail vrfs; per-port /96 rail gateways are `:0:1` (servers are
   `:0:2`, the exact template the upstream endpoint playbook uses). eBGP over
   IPv6-unnumbered uplinks to both spines carries the rail subnets between
   stripes - that path is what DLB and multipath act on.
3. **Pinned allocation.** EDA pool draws are not reproducible, so the mapping
   is explicit: backend leaf ASN = 100 + leafindex (101..116), spines 100;
   system0 192.0.2.<leafindex>; frontend leaves 121/122 + .33/.34, spines
   120 + .31/.32. Documented in `group_vars/srl/srl_config.yml`.
4. **Frontend storage vnet.** EVPNVXLAN bridge domain EVI/VNI 100 with
   proxy-ARP (dynamic learning age/refresh 2000 ms, ip-duplication 10/10/4,
   table-size 250), and **twelve all-active ESI-LAGs** (4 storage + 8 weka
   bonds across both leaves; ESIs/admin-keys pinned, EDA would draw them from
   lag-admin-key-pool).
5. **Endpoint routes added.** Per-NIC sibling-rail routes plus a cross-stripe
   route via the leaf1 rail make same-stripe and cross-stripe reachability
   testable (the upstream scripts configure only the frontend bonds; rail
   IPv6 came from the upstream endpoint playbook).

Containerlab proves config acceptance for the H4/H5 QoS and DLB subtrees;
PFC/ECN/DLB behavior needs hardware - documented limit, not a gap.

## Try it

```bash
./run-gates-vm.sh        # sizing preflight -> render gates -> full lab gates
```

SR Linux image `25.10.1` (matches upstream and the repo version policy).
Login `admin` / `NokiaSrl1!`. Validation: render invariants (pytest), state
assertions via `nokia.srlinux.srl_validate` (BGP established on all 22 nodes,
12 ESI-LAGs up on the frontend), endpoint pings incl. cross-stripe rails, and
idempotency `changed=0` across 34 nodes.

## Pointers

- Plan: `/docs/plans/ansible-all-validated-designs-plan.md`
- Derivation source: `../two-stripe-rail-optimized/eda-manifests/`
- NVIDIA digital-twin sibling: `../two-stripe-rail-optimized-nvidia-with-ansible/`
