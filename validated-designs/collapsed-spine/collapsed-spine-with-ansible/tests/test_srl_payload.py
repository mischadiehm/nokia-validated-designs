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


def test_ipv4_address_becomes_keyed_list():
    cfg = {"set": {"interface": {"ethernet-1/1": {"subinterface": {"0": {
        "ipv4": {"address": "10.0.0.1/31"}}}}}}}
    payload = payload_from_config(cfg)
    item = payload["update"][0]
    assert item["path"].endswith("/ipv4")
    assert item["value"] == {"address": [{"ip-prefix": "10.0.0.1/31"}]}


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
