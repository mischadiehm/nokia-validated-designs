"""Render invariants for the derived two-stripe NVIDIA digital-twin intent.

No CLI oracle exists for ai-dc; these tests pin the derivation rules:
configlet-verbatim DLB/QoS/multipath, per-port /96 rail gateways, the pinned
ASN/system-IP mapping, and the frontend EVPN storage vnet with twelve
all-active ESI-LAGs. Live acceptance runs via run-gates-vm.sh (needs ~50 GB
RAM; the script checks first).
"""

import json

import pytest

from conftest import render_all_nodes

LEAVES = [f"stripe{s}-leaf{l}" for s in (1, 2) for l in range(1, 9)]
NODES = LEAVES + ["spine1", "spine2",
                   "frontend-spine1", "frontend-spine2",
                   "frontend-leaf1", "frontend-leaf2"]


@pytest.fixture(scope="session")
def rendered(tmp_path_factory):
    out = render_all_nodes(tmp_path_factory.mktemp("render"))
    return {n: json.loads((out / f"{n}.json").read_text()) for n in NODES}


def _paths(ops):
    return {item["path"]: item.get("value") for item in ops["update"]}


def test_dlb_configlet_rendered_verbatim_on_every_stripe_leaf(rendered):
    for leaf in LEAVES:
        paths = _paths(rendered[leaf])
        assert paths.get("/system/load-balancing/dynamic/flowset-size") == "256"
        assert paths.get("/system/load-balancing/dynamic/inactivity-timer") == 50
        assert paths.get("/system/load-balancing/dynamic/mode") == "flow-dynamic"
        assert paths.get("/system/load-balancing/dynamic/weighting-factor/port-utilization") == 70
        assert (
            "/network-instance[name=default]/ip-load-balancing/dynamic-load-balancing/"
            "prefix[ip-prefix=::/0]" in paths
        )


def test_ipv6_multipath_matches_configlet(rendered):
    paths = _paths(rendered["stripe1-leaf1"])
    base = "/network-instance[name=default]/protocols/bgp/afi-safi[afi-safi-name=ipv6-unicast]/multipath"
    assert paths.get(f"{base}/allow-multiple-as") == "true"
    assert paths.get(f"{base}/ebgp/maximum-paths") == 2


def test_qos_configlets_rendered_verbatim(rendered):
    paths = _paths(rendered["spine1"])
    assert paths.get(
        "/qos/buffer-management/buffer-allocation-profile[name=egress-backend-dc1-backend]/"
        "queues/queue[queue-name=unicast-0]/maximum-burst-size"
    ) == 5211064
    wred = (
        "/qos/buffer-management/queue-management-profile[name=egress-backend-dc1-backend-2]/"
        "wred/wred-slope[traffic-type=all][drop-probability=all][enable-ecn=true]"
    )
    assert paths.get(f"{wred}/min-threshold-percent") == 30
    assert paths.get(f"{wred}/max-threshold-percent") == 85
    assert paths.get(
        "/qos/linecard[slot=1]/forwarding-complex[name=0]/input/pfc-buffer-reservation"
    ) == 10
    sched = "/qos/scheduler-policies/scheduler-policy[name=egress-backend-dc1-backend]"
    assert paths.get(f"{sched}/scheduler[sequence=0]/input[id=unicast-6]/peak-rate-percent") == 80
    assert paths.get(f"{sched}/scheduler[sequence=1]/input[id=unicast-0]/weight") == 10


def test_rail_gateways_and_asn_mapping(rendered):
    for s, stripe_id in ((1, 100), (2, 200)):
        for l in range(1, 9):
            leafindex = l + (0 if s == 1 else 8)
            paths = _paths(rendered[f"stripe{s}-leaf{l}"])
            assert paths.get(
                "/network-instance[name=default]/protocols/bgp/autonomous-system"
            ) == 100 + leafindex
            for port in (3, 4):
                assert (
                    f"/interface[name=ethernet-1/{port}]/subinterface[index=100]/ipv6/"
                    f"address[ip-prefix=fd00:{stripe_id}:{l}:1:0:{port}:0:1/96]" in paths
                )


def test_spines_accept_all_sixteen_leaf_asns(rendered):
    paths = _paths(rendered["spine1"])
    for port in range(1, 17):
        assert paths.get(
            "/network-instance[name=default]/protocols/bgp/dynamic-neighbors/"
            f"interface[interface-name=ethernet-1/{port}.0]/allowed-peer-as"
        ) == [100 + port]


def test_frontend_storage_vnet_with_four_esi_lags(rendered):
    paths = _paths(rendered["frontend-leaf1"])
    assert paths.get("/network-instance[name=mac-vrf-storage]/protocols/bgp-evpn/bgp-instance[id=1]/evi") == 100
    assert paths.get("/tunnel-interface[name=vxlan0]/vxlan-interface[index=100]/ingress/vni") == 100
    es_paths = [p for p in paths if "/ethernet-segment[name=" in p and p.endswith("/esi")]
    assert len(es_paths) == 4
    lag_members = [p for p in paths if p.startswith("/network-instance[name=mac-vrf-storage]/interface[name=lag")]
    assert len(lag_members) == 4
    proxy = "/network-instance[name=mac-vrf-storage]/bridge-table/proxy-arp"
    assert paths.get(f"{proxy}/dynamic-learning/age-time") == 2000
    assert paths.get(f"{proxy}/ip-duplication/num-moves") == 4
