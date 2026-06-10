# Two-Stripe Rail-Optimized NVIDIA Digital Twin - Ansible Variant

> **Status: implemented, render-validated; derived from the two-stripe
> variant.** Same 22-node fabric, NVIDIA digital-twin endpoints.

The upstream NVIDIA variant (`../two-stripe-rail-optimized-nvidia/`) shares
the two-stripe fabric exactly - same node names, same stripe cabling for the
four servers (8 rail NICs each + frontend bond), same configlets - and drops
the eight weka nodes. This Ansible variant therefore derives from
[`../two-stripe-rail-optimized-with-ansible/`](../two-stripe-rail-optimized-with-ansible/)
with two deltas:

1. **Frontend: four ESI-LAGs instead of twelve** (s1..s4 bonds only; ports
   e1-7..e1-14 and the weka host vars are gone).
2. **Topology/inventory: 26 nodes** (22 SR Linux + 4 servers), from the
   upstream NVIDIA clab file with exec scripts removed.

Everything else - rail gateways, pinned ASN/system-IP mapping, DLB, ipv6
multipath, QoS configlets, the EVPN storage vnet - is identical and pinned by
the same pytest invariants (`uv run pytest`, all green).

```bash
./run-gates-vm.sh    # sizing preflight (~45+ GB) -> render gates -> lab gates
```

SR Linux `25.10.1`, login `admin` / `NokiaSrl1!`.

Pointers: plan `/docs/plans/ansible-all-validated-designs-plan.md`; manifests
`../two-stripe-rail-optimized-nvidia/eda-manifests/`.
