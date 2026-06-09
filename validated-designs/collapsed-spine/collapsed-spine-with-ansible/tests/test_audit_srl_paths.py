"""Unit tests for the SR Linux path audit tool."""

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
TOOL = PROJECT / "tools" / "audit-srl-paths"

loader = SourceFileLoader("audit_srl_paths", str(TOOL))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
audit_srl_paths = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit_srl_paths
loader.exec_module(audit_srl_paths)


CATALOG = {
    "/interface[name=*]": {"path": "/interface[name=*]", "type": "[list]"},
    "/interface[name=*]/admin-state": {
        "path": "/interface[name=*]/admin-state",
        "type": "admin-state",
    },
    "/interface[name=*]/subinterface[index=*]": {
        "path": "/interface[name=*]/subinterface[index=*]",
        "type": "[list]",
    },
    "/network-instance[name=*]": {
        "path": "/network-instance[name=*]",
        "type": "[list]",
    },
    "/network-instance[name=*]/vxlan-interface[name=*]": {
        "path": "/network-instance[name=*]/vxlan-interface[name=*]",
        "type": "[list]",
    },
    "/tunnel-interface[name=*]": {
        "path": "/tunnel-interface[name=*]",
        "type": "[list]",
    },
    "/tunnel-interface[name=*]/vxlan-interface[index=*]": {
        "path": "/tunnel-interface[name=*]/vxlan-interface[index=*]",
        "type": "[list]",
    },
    "/routing-policy/prefix-set[name=*]/prefix[ip-prefix=*][mask-length-range=*]": {
        "path": "/routing-policy/prefix-set[name=*]/prefix[ip-prefix=*][mask-length-range=*]",
        "type": "[list]",
    },
    "/interface[name=*]/subinterface[index=*]/ipv4/address[ip-prefix=*]/primary": {
        "path": "/interface[name=*]/subinterface[index=*]/ipv4/address[ip-prefix=*]/primary",
        "type": "empty",
    },
}


def test_list_key_paths_are_extracted_from_catalog():
    assert audit_srl_paths.list_key_paths_from_catalog(CATALOG) == {
        ("interface",): ("name",),
        ("interface", "subinterface"): ("index",),
        ("network-instance",): ("name",),
        ("network-instance", "vxlan-interface"): ("name",),
        ("tunnel-interface",): ("name",),
        ("tunnel-interface", "vxlan-interface"): ("index",),
        ("routing-policy", "prefix-set", "prefix"): (
            "ip-prefix",
            "mask-length-range",
        ),
    }


def test_list_key_audit_compares_runtime_map_to_catalog():
    results = audit_srl_paths.audit_list_keys(
        {
            ("network-instance", "vxlan-interface"): ("name",),
            ("tunnel-interface", "vxlan-interface"): ("index",),
        },
        CATALOG,
    )

    assert results == [
        audit_srl_paths.CheckResult(
            "list network-instance/vxlan-interface",
            True,
            "catalog keys match /network-instance[name=*]/vxlan-interface[name=*]",
        ),
        audit_srl_paths.CheckResult(
            "list tunnel-interface/vxlan-interface",
            True,
            "catalog keys match /tunnel-interface[name=*]/vxlan-interface[index=*]",
        ),
    ]


def test_list_key_audit_reports_wrong_key():
    results = audit_srl_paths.audit_list_keys(
        {("network-instance", "vxlan-interface"): ("index",)},
        CATALOG,
    )

    assert len(results) == 1
    assert not results[0].ok
    assert "expected" in results[0].detail


def test_list_key_module_render_is_deterministic():
    rendered = audit_srl_paths.render_list_keys_module(
        "v25.3.2",
        {
            ("tunnel-interface", "vxlan-interface"): ("index",),
            ("network-instance", "vxlan-interface"): ("name",),
        },
    )

    assert 'SRL_LIST_KEYS_VERSION = "v25.3.2"' in rendered
    assert (
        "    ('network-instance', 'vxlan-interface'): ('name',),\n"
        "    ('tunnel-interface', 'vxlan-interface'): ('index',),"
    ) in rendered


def test_catalog_audit_finds_expected_path_and_type():
    results = audit_srl_paths.audit_catalog(
        [
            audit_srl_paths.PathCheck(
                "interface",
                "/interface[name=*]",
                "[list]",
            )
        ],
        CATALOG,
    )

    assert results == [
        audit_srl_paths.CheckResult("interface", True, "catalog path found")
    ]


def test_catalog_audit_reports_wrong_type():
    results = audit_srl_paths.audit_catalog(
        [
            audit_srl_paths.PathCheck(
                "interface",
                "/interface[name=*]",
                "[container]",
            )
        ],
        CATALOG,
    )

    assert len(results) == 1
    assert not results[0].ok
    assert "expected" in results[0].detail
