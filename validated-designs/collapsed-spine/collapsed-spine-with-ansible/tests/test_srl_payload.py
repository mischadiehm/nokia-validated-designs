"""Unit tests for the srl_payload filter plugin.

These lock in the YAML -> native nokia.srlinux.config payload transformation:
keyed-list path rendering, leaf-value encoding, and the
set/replace/delete -> update/replace/delete operation mapping.
"""

import pytest

from srl_payload import (
    path_from_tokens,
    payload_from_config,
    srl_payload,
)


# --- path / keyed-list rendering ------------------------------------------


def test_plain_container_path_has_no_keys():
    assert path_from_tokens(["system", "name", "host-name"]) == "/system/name/host-name"


def test_keyed_list_renders_bracket_selector():
    tokens = ["interface", "ethernet-1/51", "description"]
    assert path_from_tokens(tokens) == "/interface[name=ethernet-1/51]/description"


def test_nested_keyed_lists():
    tokens = ["network-instance", "v50-simple", "interface", "lag1.50"]
    assert (
        path_from_tokens(tokens)
        == "/network-instance[name=v50-simple]/interface[name=lag1.50]"
    )


def test_subinterface_uses_index_key():
    tokens = ["interface", "ethernet-1/55", "subinterface", "50"]
    assert (
        path_from_tokens(tokens)
        == "/interface[name=ethernet-1/55]/subinterface[index=50]"
    )


def test_system_network_instance_is_not_keyed():
    # /system/network-instance is a container, not the top-level keyed list.
    assert path_from_tokens(["system", "network-instance"]) == "/system/network-instance"


def test_network_instance_vxlan_interface_uses_name_key():
    tokens = ["network-instance", "macvrf-v50", "vxlan-interface", "vxlan0.502"]
    assert (
        path_from_tokens(tokens)
        == "/network-instance[name=macvrf-v50]/vxlan-interface[name=vxlan0.502]"
    )


def test_tunnel_vxlan_interface_uses_index_key():
    tokens = ["tunnel-interface", "vxlan0", "vxlan-interface", "502"]
    assert (
        path_from_tokens(tokens)
        == "/tunnel-interface[name=vxlan0]/vxlan-interface[index=502]"
    )


def test_composite_prefix_list_keys_render_together():
    tokens = [
        "routing-policy",
        "prefix-set",
        "prefixset-dc1-collapsed-spine",
        "prefix",
        "192.0.2.0/24",
        "mask-length-range",
        "32..32",
    ]
    assert (
        path_from_tokens(tokens)
        == "/routing-policy/prefix-set[name=prefixset-dc1-collapsed-spine]/"
        "prefix[ip-prefix=192.0.2.0/24][mask-length-range=32..32]"
    )


def test_ethernet_segment_interface_uses_ethernet_interface_key():
    tokens = ["system", "network-instance", "protocols", "evpn", "ethernet-segments",
              "bgp-instance", "1", "ethernet-segment", "es-1", "interface", "lag1"]
    rendered = path_from_tokens(tokens)
    assert "ethernet-segment[name=es-1]" in rendered
    assert "interface[ethernet-interface=lag1]" in rendered


# --- operation mapping ----------------------------------------------------


def test_set_maps_to_update():
    cfg = {"set": {"system": {"name": {"host-name": "tor1"}}}}
    payload = payload_from_config(cfg)
    assert payload["update"] == [
        {"path": "/system/name/host-name", "value": "tor1"}
    ]
    assert payload["replace"] == []
    assert payload["delete"] == []


def test_replace_maps_to_replace():
    cfg = {"replace": {"interface": {"ethernet-1/55": {"admin-state": "enable"}}}}
    payload = payload_from_config(cfg)
    assert payload["replace"] == [
        {"path": "/interface[name=ethernet-1/55]/admin-state", "value": "enable"}
    ]
    assert payload["update"] == []


def test_replace_non_empty_tree_is_leaf_scoped():
    cfg = {
        "replace": {
            "interface": {
                "ethernet-1/55": {
                    "admin-state": "enable",
                    "description": "server uplink",
                }
            }
        }
    }
    payload = payload_from_config(cfg)
    assert payload["replace"] == [
        {"path": "/interface[name=ethernet-1/55]/admin-state", "value": "enable"},
        {"path": "/interface[name=ethernet-1/55]/description", "value": "server uplink"},
    ]
    assert {"path": "/interface[name=ethernet-1/55]", "value": {}} not in payload["replace"]


def test_replace_empty_dict_targets_exact_path():
    cfg = {"replace": {"interface": {"ethernet-1/55": {}}}}
    payload = payload_from_config(cfg)
    assert payload["replace"] == [
        {"path": "/interface[name=ethernet-1/55]", "value": {}}
    ]


def test_delete_maps_to_delete_without_value():
    cfg = {"delete": {"system": {"aaa": {"authentication": {"admin-user": {"ssh-key": {}}}}}}}
    payload = payload_from_config(cfg)
    assert payload["delete"] == [
        {"path": "/system/aaa/authentication/admin-user/ssh-key"}
    ]
    assert payload["update"] == []


def test_all_three_buckets_together():
    cfg = {
        "set": {"system": {"name": {"host-name": "tor1"}}},
        "replace": {"interface": {"ethernet-1/55": {"admin-state": "enable"}}},
        "delete": {"system": {"lldp": {}}},
    }
    payload = payload_from_config(cfg)
    assert payload["update"] == [{"path": "/system/name/host-name", "value": "tor1"}]
    assert payload["replace"] == [
        {"path": "/interface[name=ethernet-1/55]/admin-state", "value": "enable"}
    ]
    assert payload["delete"] == [{"path": "/system/lldp"}]


# --- leaf-value encoding --------------------------------------------------


def test_boolean_is_lowercased_string():
    cfg = {"set": {"interface": {"ethernet-1/55": {"vlan-tagging": True}}}}
    payload = payload_from_config(cfg)
    assert payload["update"] == [
        {"path": "/interface[name=ethernet-1/55]/vlan-tagging", "value": "true"}
    ]


def test_integer_zero_is_stringified():
    cfg = {"set": {"interface": {"ethernet-1/1": {"subinterface": {"0": {"index": 0}}}}}}
    payload = payload_from_config(cfg)
    value = payload["update"][0]["value"]
    assert value == "0"


def test_empty_dict_set_is_presence_leaf():
    cfg = {"set": {"network-instance": {"v50": {"interface": {"lag1.50": {}}}}}}
    payload = payload_from_config(cfg)
    assert payload["update"] == [
        {"path": "/network-instance[name=v50]/interface[name=lag1.50]", "value": {}}
    ]


def test_explicit_network_instance_vxlan_interface_uses_name_key():
    cfg = {"set": {"network-instance": {"v50": {"vxlan-interface": {"vxlan0.502": {}}}}}}
    payload = payload_from_config(cfg)
    assert payload["update"] == [
        {
            "path": "/network-instance[name=v50]/vxlan-interface[name=vxlan0.502]",
            "value": {},
        }
    ]


def test_scalar_single_key_list_value_sets_key():
    cfg = {"set": {"network-instance": {"v50": {"vxlan-interface": "vxlan0.502"}}}}
    payload = payload_from_config(cfg)
    assert payload["update"] == [
        {
            "path": "/network-instance[name=v50]/vxlan-interface[name=vxlan0.502]",
            "value": {},
        }
    ]


def test_scalar_evpn_advertise_value_sets_route_type_key():
    cfg = {"set": {"interface": {"irb0": {"subinterface": {"1": {
        "ipv4": {"arp": {"evpn": {"advertise": "dynamic"}}}
    }}}}}}
    payload = payload_from_config(cfg)
    assert payload["update"] == [
        {
            "path": "/interface[name=irb0]/subinterface[index=1]/ipv4/"
            "arp/evpn/advertise[route-type=dynamic]",
            "value": {},
        }
    ]


def test_scalar_ipv4_address_value_sets_ip_prefix_key():
    cfg = {"set": {"interface": {"ethernet-1/1": {"subinterface": {"0": {
        "ipv4": {"address": "10.0.0.1/31"}}}}}}}
    payload = payload_from_config(cfg)
    assert payload["update"] == [
        {
            "path": "/interface[name=ethernet-1/1]/subinterface[index=0]/"
            "ipv4/address[ip-prefix=10.0.0.1/31]",
            "value": {},
        }
    ]


def test_scalar_composite_key_leaf_value_completes_list_key():
    cfg = {"set": {"routing-policy": {"prefix-set": {"ps1": {
        "prefix": {"192.0.2.0/24": {"mask-length-range": "32..32"}}
    }}}}}
    payload = payload_from_config(cfg)
    assert payload["update"] == [
        {
            "path": "/routing-policy/prefix-set[name=ps1]/"
            "prefix[ip-prefix=192.0.2.0/24][mask-length-range=32..32]",
            "value": {},
        }
    ]


# --- top-level filter + validation ----------------------------------------


def test_srl_payload_reads_srl_config_key():
    hostvars = {"srl_config": {"set": {"system": {"name": {"host-name": "tor1"}}}}}
    payload = srl_payload(hostvars)
    assert payload["update"] == [{"path": "/system/name/host-name", "value": "tor1"}]


def test_srl_payload_handles_missing_config():
    payload = srl_payload({})
    assert payload == {"update": [], "replace": [], "delete": []}


def test_srl_payload_returns_all_resource_keys():
    payload = srl_payload({"srl_config": {}})
    assert set(payload) == {"update", "replace", "delete"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
