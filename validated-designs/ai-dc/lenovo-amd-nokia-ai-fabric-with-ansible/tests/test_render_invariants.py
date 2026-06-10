"""Render invariants for the derived (EDA-manifest-based) lenovo intent.

There is no CLI oracle for ai-dc, so these tests pin the derivation rules
instead: per-port /96 gateways with the complement convention, leaf-local
rail ip-vrfs, catalog-verified QoS paths from the Backend resource, and the
SIMPLE bridge domains. Data-plane acceptance (same-rail ping works,
cross-rail ping fails) runs in playbooks/validate.yml on the lab VM.
"""

import json

import pytest

from conftest import render_all_nodes

NODES = [
    "backend-leaf1", "backend-leaf2",
    "frontend-leaf1", "frontend-leaf2",
    "storage-leaf1", "storage-leaf2",
]


@pytest.fixture(scope="session")
def rendered(tmp_path_factory):
    out = render_all_nodes(tmp_path_factory.mktemp("render"))
    return {n: json.loads((out / f"{n}.json").read_text()) for n in NODES}


def _paths(ops):
    return {item["path"]: item.get("value") for item in ops["update"]}


def test_backend_rail_gateways_follow_complement_rule(rendered):
    for leaf_num in (1, 2):
        paths = _paths(rendered[f"backend-leaf{leaf_num}"])
        for port in range(1, 9):
            x = 1 if (leaf_num == 1 and port == 1) else 2
            path = (
                f"/interface[name=ethernet-1/{port}]/subinterface[index=100]/"
                f"ipv6/address[ip-prefix=fd00:100:{leaf_num}:1:0:{port}:0:{x}/96]"
            )
            assert path in paths, f"missing rail gateway: {path}"


def test_backend_rails_are_leaf_local_ip_vrfs(rendered):
    for leaf_num, rail_base in ((1, 0), (2, 4)):
        paths = _paths(rendered[f"backend-leaf{leaf_num}"])
        for rail_offset in range(1, 5):
            rail = rail_base + rail_offset
            ni = f"/network-instance[name=rail{rail}]"
            assert paths.get(f"{ni}/type") == "ip-vrf"
            low, high = rail_offset, rail_offset + 4
            assert f"{ni}/interface[name=ethernet-1/{low}.100]" in paths
            assert f"{ni}/interface[name=ethernet-1/{high}.100]" in paths


def test_backend_qos_paths_match_v25_10_1_catalog(rendered):
    paths = _paths(rendered["backend-leaf1"])
    wred = (
        "/qos/buffer-management/queue-management-profile[name=rocev2-ecn]/wred/"
        "wred-slope[traffic-type=all][drop-probability=all][enable-ecn=true]"
    )
    assert paths.get(f"{wred}/min-threshold-percent") == 5
    assert paths.get(f"{wred}/max-threshold-percent") == 80
    assert paths.get(f"{wred}/max-drop-probability-percent") == 100
    assert paths.get(
        "/qos/buffer-management/buffer-allocation-profile[name=rocev2-burst]/"
        "queues/pfc-queue[pfc-queue-name=pfc-0]/maximum-burst-size"
    ) == 52110640
    assert paths.get(
        "/qos/pfc-mapping-profile[name=rocev2-pfc]/received-pfc-pause-frames/"
        "deadlock/detection-timer"
    ) == 750
    assert paths.get(
        "/qos/linecard[slot=1]/forwarding-complex[name=0]/input/pfc-buffer-reservation"
    ) == 10
    assert paths.get(
        "/qos/interfaces/interface[interface-id=ethernet-1/1]/output/buffer-allocation-profile"
    ) == "rocev2-burst"


def test_simple_bridge_domains(rendered):
    fe = _paths(rendered["frontend-leaf1"])
    assert fe.get("/network-instance[name=untagged-frontend]/type") == "mac-vrf"
    assert "/network-instance[name=untagged-frontend]/interface[name=lag1.4096]" in fe
    assert fe.get("/interface[name=lag1]/lag/lacp/admin-key") == 11
    st = _paths(rendered["storage-leaf1"])
    assert st.get("/network-instance[name=untagged-storage]/type") == "mac-vrf"
    for port in (1, 2, 3):
        assert (
            f"/network-instance[name=untagged-storage]/interface[name=ethernet-1/{port}.4096]"
            in st
        )


def test_no_bgp_and_no_evpn_anywhere(rendered):
    # The spineless lenovo design renders no fabric protocol; the validate
    # role must therefore skip BGP/ES checks on every node.
    for node in NODES:
        for path in _paths(rendered[node]):
            assert "/protocols/bgp" not in path
            assert "ethernet-segments" not in path
