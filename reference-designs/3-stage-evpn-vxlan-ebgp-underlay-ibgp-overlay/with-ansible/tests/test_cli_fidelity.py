"""CLI fidelity: rendered intent must equal the without-eda configs.

The without-eda `configs/*.cli` files are the fidelity oracle for this
variant. Each `set /` line is parsed into the same readable tree shape an
author would write, rendered through the collection renderer, and normalized
into leaf (path, value) pairs. The Ansible-rendered operations for every node
are normalized the same way. The two sets must match exactly, both ways.

This is a test-only helper per the repo guardrails: it never generates
deployment vars and lives entirely in tests/.
"""

import json
import shlex
from pathlib import Path

import pytest

from conftest import LAB_ROOT, render_all_nodes

from ansible_collections.nokia.srlinux.plugins.module_utils.to_config_operations.renderer import (
    operations_from_config,
)

ORACLE_DIR = LAB_ROOT.parent / "configs"
NODES = ["spine1", "spine2", "leaf1", "leaf2", "leaf3", "leaf4", "leaf5", "leaf6"]

# CLI lines that end on a presence flag (no value token follows).
PRESENCE_FLAGS = {"interface-standby-signaling-on-non-df"}

# Documented, reviewed deviations from the oracle. Upstream leaf6.cli omits
# advertise-arp-nd-only-with-mac-table-entry on macvrf-v50 only (same
# omission as the validated 3-stage design); the intent keeps the service
# catalog uniform across leaves.
ALLOWED_EXTRA = {
    "leaf6": {
        (
            "/network-instance[name=macvrf-v50]/protocols/bgp-evpn/"
            "bgp-instance[id=1]/routes/bridge-table/mac-ip/"
            "advertise-arp-nd-only-with-mac-table-entry",
            "true",
        ),
    },
}


def _coerce(token: str):
    if token.lstrip("-").isdigit():
        return int(token)
    return token


def _parse_cli_line(line: str):
    """Return the readable tree for one `set /` line."""
    body = line[len("set / "):]
    tokens = shlex.split(body)

    # Bracket list values: [ a b c ] -> list
    if "[" in tokens:
        start = tokens.index("[")
        assert tokens[-1] == "]", f"unterminated bracket list: {line}"
        value = [_coerce(t) for t in tokens[start + 1:-1]]
        path_tokens = tokens[:start]
    elif tokens[-1] in PRESENCE_FLAGS:
        value = True
        path_tokens = tokens
    else:
        value = _coerce(tokens[-1])
        path_tokens = tokens[:-1]

    tree = value
    for token in reversed(path_tokens):
        tree = {token: tree}
    return tree


def _normalize_value(value):
    if value == "":
        # JSON-RPC encodes empty leaves (e.g. address `primary`) as "".
        return "__presence__"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_value(v) for v in value)
    if isinstance(value, dict):
        raise AssertionError("dict values must be expanded before normalize")
    return str(value)


def _expand(path: str, value, out: set):
    if value == {}:
        out.add((path, "__presence__"))
    elif isinstance(value, dict):
        for key, sub in value.items():
            _expand(f"{path}/{key}", sub, out)
    else:
        out.add((path, _normalize_value(value)))


def _operations_to_pairs(operations) -> set:
    assert operations["replace"] == [], "fidelity model expects update-only intent"
    pairs: set = set()
    for item in operations["update"]:
        _expand(item["path"], item["value"], pairs)
    return pairs


def _rendered_delete_paths(operations) -> set:
    return {item["path"] for item in operations["delete"]}


def _cli_pairs(node: str) -> tuple[set, set]:
    # Render every line independently and union the pairs: repeated presence
    # entries under the same parent (e.g. network-instance interfaces) would
    # otherwise clobber each other in a naive tree merge. The reference
    # design oracles also carry `delete /` lines (ssh-key removal).
    update_pairs: set = set()
    delete_paths: set = set()
    for line in (ORACLE_DIR / f"{node}.cli").read_text().splitlines():
        line = line.strip()
        if line.startswith("set / "):
            operations = operations_from_config({"update": _parse_cli_line(line)})
            update_pairs |= _operations_to_pairs(operations)
        elif line.startswith("delete / "):
            tokens = line[len("delete / "):].split()
            tree = {}
            node_ref = tree
            for token in tokens[:-1]:
                node_ref = node_ref.setdefault(token, {})
            node_ref[tokens[-1]] = {}
            operations = operations_from_config({"delete": tree})
            delete_paths |= {item["path"] for item in operations["delete"]}
    return update_pairs, delete_paths


@pytest.fixture(scope="session")
def rendered_dir(tmp_path_factory):
    return render_all_nodes(tmp_path_factory.mktemp("render"))


@pytest.mark.parametrize("node", NODES)
def test_rendered_intent_matches_cli_oracle(node, rendered_dir):
    rendered = json.loads((rendered_dir / f"{node}.json").read_text())
    rendered_pairs = _operations_to_pairs(rendered)
    rendered_deletes = _rendered_delete_paths(rendered)
    oracle_pairs, oracle_deletes = _cli_pairs(node)

    missing = sorted(oracle_pairs - rendered_pairs)
    extra = sorted(rendered_pairs - oracle_pairs - ALLOWED_EXTRA.get(node, set()))
    missing += sorted(("delete", p) for p in oracle_deletes - rendered_deletes)
    extra += sorted(("delete", p) for p in rendered_deletes - oracle_deletes)
    detail = ""
    if missing:
        detail += "\nMISSING (in oracle, not rendered):\n  " + "\n  ".join(map(str, missing[:40]))
    if extra:
        detail += "\nEXTRA (rendered, not in oracle):\n  " + "\n  ".join(map(str, extra[:40]))
    assert not missing and not extra, f"{node} fidelity mismatch:{detail}"
