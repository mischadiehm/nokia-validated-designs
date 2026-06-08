"""Unit tests for the Containerlab network tester."""

import importlib.util
import sys
from io import StringIO
from importlib.machinery import SourceFileLoader
from pathlib import Path

from rich.console import Console


PROJECT = Path(__file__).resolve().parents[1]
TOOL = PROJECT / "tools" / "clab-network-tester"
CONFIG = PROJECT / "network-tests" / "2-way-collapsed-spine.yml"
TOPOLOGY = PROJECT / "2-way-collapsed-spine.clab.yaml"

loader = SourceFileLoader("clab_network_tester", str(TOOL))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
clab_network_tester = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = clab_network_tester
loader.exec_module(clab_network_tester)


def load_config():
    return clab_network_tester.load_network_test_config(CONFIG, None)


def load_addresses():
    config = load_config()
    return clab_network_tester.load_endpoint_addresses(config.path, config.endpoints)


def test_topology_name_maps_to_network_test_config():
    config, topology = clab_network_tester.resolve_runtime_paths(
        config=None,
        topology=TOPOLOGY,
        cwd=PROJECT,
    )

    assert topology == TOPOLOGY
    assert config == CONFIG


def test_config_loads_topology_and_named_flows():
    config = load_config()

    assert config.topology == TOPOLOGY
    assert config.defaults.test == clab_network_tester.TestMode.all
    assert config.defaults.families == {"ipv4", "ipv6"}
    assert config.defaults.sweep_interval == 30
    assert config.defaults.flow_interval == 1
    assert "s1-to-s4" in config.flows


def test_load_endpoint_addresses_uses_data_plane_intent_only():
    addresses = load_addresses()

    assert len(addresses) == 22
    assert {address.family for address in addresses} == {"ipv4", "ipv6"}
    assert not any(address.ip.startswith("172.21.21.") for address in addresses)
    assert any(
        address.host == "s1"
        and address.interface == "eth1.20"
        and address.ip == "172.16.20.1"
        and address.gateway == "172.16.20.254"
        for address in addresses
    )


def test_generated_cases_cover_gateways_and_endpoint_mesh():
    addresses = load_addresses()
    cases = clab_network_tester.build_cases(
        addresses,
        mode=clab_network_tester.TestMode.all,
        families={"ipv4", "ipv6"},
    )

    gateway_cases = [case for case in cases if case.kind == "gateway"]
    host_cases = [case for case in cases if case.kind != "gateway"]

    assert len(cases) == 214
    assert len(gateway_cases) == 22
    assert len(host_cases) == 192
    assert any(
        case.kind == "same-segment"
        and case.source_host == "s1"
        and case.target_host == "s2"
        and case.source_ip == "172.16.10.1"
        and case.target_ip == "172.16.10.2"
        for case in cases
    )
    assert any(
        case.kind == "routed"
        and case.source_host == "s1"
        and case.target_host == "s4"
        and case.source_ip == "172.16.20.1"
        and case.target_ip == "172.16.50.4"
        for case in cases
    )


def test_named_flow_builds_source_bound_ping_command():
    config = load_config()
    addresses = load_addresses()
    case = clab_network_tester.parse_ping_case(
        clab_network_tester.flow_spec("s1-to-s4", config.flows),
        addresses,
    )

    command = clab_network_tester.ping_command(case, count=3, timeout=2, interval=1)

    assert case.kind == "routed"
    assert command == [
        "docker",
        "exec",
        "s1",
        "ping",
        "-n",
        "-4",
        "-c",
        "3",
        "-W",
        "2",
        "-I",
        "172.16.20.1",
        "172.16.50.4",
    ]


def test_continuous_ping_command_omits_packet_count():
    config = load_config()
    addresses = load_addresses()
    case = clab_network_tester.parse_ping_case(
        clab_network_tester.flow_spec("s1-to-s4", config.flows),
        addresses,
    )

    command = clab_network_tester.ping_command(
        case,
        count=3,
        timeout=2,
        interval=0.2,
        continuous=True,
    )

    assert "-c" not in command
    assert command == [
        "docker",
        "exec",
        "s1",
        "ping",
        "-n",
        "-4",
        "-W",
        "2",
        "-i",
        "0.2",
        "-I",
        "172.16.20.1",
        "172.16.50.4",
    ]


def test_static_endpoint_config_is_supported(tmp_path):
    endpoint_config = {
        "hosts": {
            "h1": {
                "container": "h1-container",
                "interfaces": {
                    "eth1": {
                        "addresses": [
                            {
                                "prefix": "10.0.0.1/24",
                                "gateway": "10.0.0.254",
                                "table": "blue",
                            }
                        ],
                    }
                },
            }
        }
    }

    addresses = clab_network_tester.load_endpoint_addresses(
        tmp_path / "network-tests" / "test.yml",
        endpoint_config,
    )

    assert addresses == [
        clab_network_tester.EndpointAddress(
            host="h1",
            container="h1-container",
            interface="eth1",
            family="ipv4",
            ip="10.0.0.1",
            prefix="10.0.0.1/24",
            table="blue",
            gateway="10.0.0.254",
            vlan=None,
        )
    ]


def test_validate_run_options_rejects_ambiguous_flow_selection():
    assert (
        clab_network_tester.validate_run_options(
            manual_case="s1:172.16.20.1,s4:172.16.50.4",
            flow="s1-to-s4",
            once=False,
            duration=None,
            interval=1,
        )
        == "--case cannot be combined with --flow"
    )


def test_validate_run_options_accepts_continuous_mesh():
    assert (
        clab_network_tester.validate_run_options(
            manual_case=None,
            flow=None,
            once=False,
            duration=1,
            interval=1,
        )
        is None
    )


def test_continuous_loop_uses_live_dashboard_without_docker(monkeypatch):
    addresses = load_addresses()
    cases = clab_network_tester.build_cases(
        addresses,
        mode=clab_network_tester.TestMode.gateways,
        families={"ipv4"},
    )[:2]

    calls = 0
    ping_intervals = []

    def fake_execute_ping_case(case, count, timeout, interval):
        nonlocal calls
        calls += 1
        ping_intervals.append(interval)
        return True, "1 packets transmitted, 1 received, 0% packet loss"

    monkeypatch.setattr(
        clab_network_tester,
        "execute_ping_case",
        fake_execute_ping_case,
    )
    console = Console(
        file=StringIO(),
        force_terminal=False,
        highlight=False,
        width=140,
    )

    passed, failed = clab_network_tester.run_loop_cases(
        cases=cases,
        count=1,
        timeout=1,
        interval=0.01,
        duration=0.01,
        dry_run=False,
        verbose=True,
        console=console,
    )

    assert calls >= 1
    assert set(ping_intervals) == {1}
    assert passed >= 1
    assert failed == 0
    assert console.file.getvalue() == ""


def test_loop_dashboard_renders_aggregate_cadence():
    addresses = load_addresses()
    case = clab_network_tester.build_cases(
        addresses,
        mode=clab_network_tester.TestMode.gateways,
        families={"ipv4"},
    )[0]
    console = Console(
        file=StringIO(),
        force_terminal=False,
        highlight=False,
        width=140,
    )

    console.print(
        clab_network_tester.render_loop_dashboard(
            cases=[case],
            run_label="until interrupted",
            sweep_interval=30,
            started=0,
            deadline=None,
            cycle=1,
            cycle_completed=1,
            cycle_passed=0,
            cycle_failed=0,
            passed=0,
            failed=0,
            last_cycle="none yet",
            recent_failures=[],
            status="running",
        )
    )

    output = console.file.getvalue()
    assert "Data-plane sweep" in output
    assert "30s pause" in output
    assert "1/1 checks complete" in output
    assert "docker exec" not in output
