"""Unit tests for the srl_payload filter plugin.

These lock in the YAML -> native nokia.srlinux.config payload transformation:
keyed-list path rendering, leaf-value encoding, and the
set/replace/delete -> update/replace/delete operation mapping.
"""

import pytest

from srl_payload import (
    path_from_tokens,
    payload_from_config,
    srl_list_keys_version,
    srl_payload,
    srl_payload_delta,
    srl_payload_has_ops,
    srl_payload_read_commands,
    srl_payload_read_plan,
    srl_release_version,
    srl_version_newer_than,
    srl_version_tuple,
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


# --- Ansible-host delta pruning ---------------------------------------------


def test_srl_payload_read_plan_uses_running_datastore():
    payload = {
        "update": [{"path": "/system/name/host-name", "value": "tor1"}],
        "replace": [],
        "delete": [{"path": "/system/aaa/authentication/admin-user/ssh-key"}],
    }
    plan = srl_payload_read_plan(payload)

    assert plan == [
        {
            "section": "update",
            "index": 0,
            "path": "/system/name/host-name",
            "read_path": "/system/name/host-name",
            "mode": "exact-value",
        },
        {
            "section": "delete",
            "index": 0,
            "path": "/system/aaa/authentication/admin-user/ssh-key",
            "read_path": "/system/aaa/authentication/admin-user",
            "mode": "parent-exists",
        },
    ]
    assert srl_payload_read_commands(plan) == [
        {"path": "/system/name/host-name", "datastore": "running"},
        {"path": "/system/aaa/authentication/admin-user", "datastore": "running"},
    ]


def test_srl_payload_read_plan_handles_slashes_inside_selectors():
    payload = {
        "update": [
            {
                "path": "/routing-policy/prefix-set[name=ps1]/"
                "prefix[ip-prefix=192.0.2.0/24][mask-length-range=32..32]",
                "value": {},
            },
            {
                "path": "/interface[name=ethernet-1/51]/description",
                "value": "uplink",
            },
        ],
        "replace": [],
        "delete": [],
    }

    plan = srl_payload_read_plan(payload)

    assert plan[0]["read_path"] == "/routing-policy/prefix-set[name=ps1]"
    assert plan[1]["read_path"] == "/interface[name=ethernet-1/51]/description"


def test_srl_payload_delta_prunes_unchanged_scalar_and_keeps_changed_scalar():
    payload = {
        "update": [
            {"path": "/system/name/host-name", "value": "tor1"},
            {"path": "/interface[name=ethernet-1/51]/admin-state", "value": "enable"},
        ],
        "replace": [],
        "delete": [],
    }
    plan = srl_payload_read_plan(payload)

    delta = srl_payload_delta(payload, plan, ["tor1", "disable"])

    assert delta == {
        "update": [
            {"path": "/interface[name=ethernet-1/51]/admin-state", "value": "enable"},
        ],
        "replace": [],
        "delete": [],
    }


def test_srl_payload_delta_compares_numeric_strings_to_running_numbers():
    payload = {
        "update": [{"path": "/interface[name=ethernet-1/1]/subinterface[index=0]/index",
                    "value": "0"}],
        "replace": [],
        "delete": [],
    }
    plan = srl_payload_read_plan(payload)

    assert srl_payload_delta(payload, plan, [0]) == {
        "update": [],
        "replace": [],
        "delete": [],
    }


def test_srl_payload_delta_compares_unprefixed_identity_to_running_identityref():
    payload = {
        "update": [{"path": "/network-instance[name=v50]/type", "value": "mac-vrf"}],
        "replace": [],
        "delete": [],
    }
    plan = srl_payload_read_plan(payload)

    assert srl_payload_delta(payload, plan, ["srl_nokia-network-instance:mac-vrf"]) == {
        "update": [],
        "replace": [],
        "delete": [],
    }


def test_srl_payload_delta_compares_presence_leaf_to_running_null_list():
    payload = {
        "update": [
            {
                "path": "/interface[name=irb0]/subinterface[index=4]/"
                "ipv4/address[ip-prefix=172.16.10.254/24]/primary",
                "value": "",
            }
        ],
        "replace": [],
        "delete": [],
    }
    plan = srl_payload_read_plan(payload)

    assert srl_payload_delta(payload, plan, [[None]]) == {
        "update": [],
        "replace": [],
        "delete": [],
    }


def test_srl_payload_delta_compares_scalar_lists_recursively():
    payload = {
        "update": [
            {
                "path": "/network-instance[name=default]/protocols/bgp/"
                "dynamic-neighbors/interface[interface-name=ethernet-1/31.0]/"
                "allowed-peer-as",
                "value": [65502],
            }
        ],
        "replace": [],
        "delete": [],
    }
    plan = srl_payload_read_plan(payload)

    assert srl_payload_delta(payload, plan, [["65502"]]) == {
        "update": [],
        "replace": [],
        "delete": [],
    }


def test_srl_payload_delta_prunes_existing_presence_list_entry():
    payload = {
        "update": [
            {
                "path": "/network-instance[name=v50]/interface[name=lag1.50]",
                "value": {},
            }
        ],
        "replace": [],
        "delete": [],
    }
    plan = srl_payload_read_plan(payload)

    delta = srl_payload_delta(payload, plan, [{"interface": [{"name": "lag1.50"}]}])

    assert delta == {"update": [], "replace": [], "delete": []}


def test_srl_payload_delta_keeps_missing_presence_list_entry():
    payload = {
        "update": [
            {
                "path": "/network-instance[name=v50]/interface[name=lag1.50]",
                "value": {},
            }
        ],
        "replace": [],
        "delete": [],
    }
    plan = srl_payload_read_plan(payload)

    delta = srl_payload_delta(payload, plan, [{"interface": [{"name": "other"}]}])

    assert delta == payload


def test_srl_payload_delta_prunes_absent_delete_and_keeps_existing_delete():
    payload = {
        "update": [],
        "replace": [],
        "delete": [{"path": "/system/aaa/authentication/admin-user/ssh-key"}],
    }
    plan = srl_payload_read_plan(payload)

    assert srl_payload_delta(payload, plan, [{}]) == {
        "update": [],
        "replace": [],
        "delete": [],
    }
    assert srl_payload_delta(payload, plan, [{"ssh-key": ["ssh-rsa abc"]}]) == payload


def test_srl_payload_delta_rejects_result_count_mismatch():
    payload = {"update": [{"path": "/system/name/host-name", "value": "tor1"}],
               "replace": [], "delete": []}
    plan = srl_payload_read_plan(payload)

    with pytest.raises(ValueError, match="running result count"):
        srl_payload_delta(payload, plan, [])


def test_srl_payload_has_ops_detects_empty_delta():
    assert srl_payload_has_ops({"update": [], "replace": [], "delete": []}) is False
    assert srl_payload_has_ops({"update": [{"path": "/system/name/host-name"}]}) is True


# --- SR Linux catalog/version guard helpers -------------------------------


def test_srl_list_keys_version_comes_from_generated_metadata():
    assert srl_list_keys_version() == "v25.3.2"


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("v25.3.2-123-gabcdef", "v25.3.2"),
        ("25.3.2", "v25.3.2"),
        ("SR Linux v26.3.1-42-g123456", "v26.3.1"),
        ("v25.7", "v25.7.0"),
    ],
)
def test_srl_release_version_normalizes_device_versions(raw, want):
    assert srl_release_version(raw) == want


def test_srl_version_tuple_is_numeric_not_lexicographic():
    assert srl_version_tuple("v25.10.1") > srl_version_tuple("v25.3.99")


def test_srl_version_newer_than_detects_newer_live_release():
    assert srl_version_newer_than("v26.3.1-1-gabc", "v25.3.2")
    assert srl_version_newer_than("v25.3.2", "v25.3.2") is False
    assert srl_version_newer_than("v25.3.1", "v25.3.2") is False


def test_srl_release_version_rejects_unparseable_values():
    with pytest.raises(ValueError, match="could not parse SR Linux version"):
        srl_release_version("not-a-version")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
