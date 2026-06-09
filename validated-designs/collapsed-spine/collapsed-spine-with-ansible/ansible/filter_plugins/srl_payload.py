"""SR Linux payload filters for the collapsed-spine Ansible variant.

This filter turns the readable ``srl_config`` tree authored in ``host_vars``
into the native operation lists consumed by ``nokia.srlinux.config``
(``update`` / ``replace`` / ``delete``). Keeping this transformation in a
Python filter plugin (rather than Jinja2 templates) follows the Ansible good
practice that structured-data transformation belongs in a plugin, not a
template.
"""

import importlib.util
import re
from pathlib import Path
from typing import Any

RESOURCE_KEYS = ("update", "replace", "delete")
SRL_RELEASE_RE = re.compile(r"v?(\d{1,3})\.(\d{1,2})(?:\.(\d{1,3}))?")
PATH_SEGMENT_RE = re.compile(r"(?P<name>[^\[\]]+)(?P<keys>(?:\[[^=\]]+=[^\]]+\])*)$")
PATH_KEY_RE = re.compile(r"\[([^=\]]+)=([^\]]+)\]")


def _load_list_key_metadata() -> tuple[str, dict[tuple[str, ...], tuple[str, ...]]]:
    list_keys_path = Path(__file__).resolve().parents[1] / "srl_list_keys.py"
    spec = importlib.util.spec_from_file_location("srl_list_keys", list_keys_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {list_keys_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SRL_LIST_KEYS_VERSION, module.LIST_KEY_PATHS


SRL_LIST_KEYS_VERSION, LIST_KEY_PATHS = _load_list_key_metadata()


def srl_list_keys_version(_: Any = None) -> str:
    """Return the SR Linux release catalog used by ``srl_list_keys.py``."""
    return SRL_LIST_KEYS_VERSION


def srl_release_version(value: Any) -> str:
    """Normalize an SR Linux version string to ``vMAJOR.MINOR.PATCH``."""
    match = SRL_RELEASE_RE.search(str(value or ""))
    if not match:
        raise ValueError(f"could not parse SR Linux version from {value!r}")

    major, minor, patch = match.groups()
    patch = patch or "0"
    return f"v{int(major)}.{int(minor)}.{int(patch)}"


def srl_version_tuple(value: Any) -> tuple[int, int, int]:
    """Return ``(major, minor, patch)`` from an SR Linux version string."""
    release = srl_release_version(value)
    return tuple(int(part) for part in release.removeprefix("v").split("."))


def srl_version_newer_than(value: Any, other: Any) -> bool:
    """Return True when ``value`` is a newer SR Linux release than ``other``."""
    return srl_version_tuple(value) > srl_version_tuple(other)


def _empty_payload() -> dict[str, list]:
    return {key: [] for key in RESOURCE_KEYS}


def _split_path(path: str) -> list[str]:
    segments = []
    start = 1
    depth = 0
    for index, char in enumerate(path[1:], start=1):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "/" and depth == 0:
            segments.append(path[start:index])
            start = index + 1
    segments.append(path[start:])
    return segments


def _parse_path(path: str) -> list[dict[str, Any]]:
    if not path.startswith("/"):
        raise ValueError(f"SR Linux path must start with /: {path}")

    segments = []
    for raw_segment in _split_path(path):
        match = PATH_SEGMENT_RE.match(raw_segment)
        if not match:
            raise ValueError(f"could not parse SR Linux path segment: {raw_segment}")
        segments.append({
            "name": match.group("name"),
            "keys": dict(PATH_KEY_RE.findall(match.group("keys"))),
        })
    return segments


def _render_segment(segment: dict[str, Any]) -> str:
    keys = "".join(f"[{name}={value}]" for name, value in segment["keys"].items())
    return f"{segment['name']}{keys}"


def _render_path(segments: list[dict[str, Any]]) -> str:
    return "/" + "/".join(_render_segment(segment) for segment in segments)


def _read_parent_path(path: str) -> str:
    segments = _parse_path(path)
    if len(segments) <= 1:
        return path
    return _render_path(segments[:-1])


def _read_mode(section: str, item: dict[str, Any]) -> str:
    if section == "delete" or item.get("value") == {}:
        return "parent-exists"
    return "exact-value"


def srl_payload_read_plan(payload: dict) -> list[dict[str, Any]]:
    """Return running datastore reads needed to compute a local payload delta."""
    plan = []
    for section in RESOURCE_KEYS:
        for index, item in enumerate(payload.get(section, [])):
            mode = _read_mode(section, item)
            path = item["path"]
            read_path = _read_parent_path(path) if mode == "parent-exists" else path
            plan.append({
                "section": section,
                "index": index,
                "path": path,
                "read_path": read_path,
                "mode": mode,
            })
    return plan


def srl_payload_read_commands(plan: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return nokia.srlinux.get commands for a local payload delta read plan."""
    return [
        {"path": item["read_path"], "datastore": "running"}
        for item in plan
    ]


def _equivalent_value(desired: Any, running: Any) -> bool:
    if desired == running:
        return True
    if desired == "" and running == [None]:
        return True
    if isinstance(desired, list) and isinstance(running, list):
        if len(desired) != len(running):
            return False
        pairs = zip(desired, running, strict=True)
        return all(_equivalent_value(left, right) for left, right in pairs)
    if isinstance(desired, str) and isinstance(running, str):
        return desired == running.split(":", 1)[-1]
    if isinstance(desired, str) and not isinstance(running, (dict, list)):
        return desired == str(running).lower()
    if isinstance(running, str) and not isinstance(desired, (dict, list)):
        return str(desired).lower() == running
    return False


def _segment_exists(parent_data: Any, target: dict[str, Any]) -> bool:
    if not isinstance(parent_data, dict) or target["name"] not in parent_data:
        return False

    value = parent_data[target["name"]]
    if not target["keys"]:
        return True

    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            if all(str(item.get(name)) == key for name, key in target["keys"].items()):
                return True
    if isinstance(value, dict):
        return all(str(value.get(name)) == key for name, key in target["keys"].items())

    return False


def _operation_changed(section: str, item: dict, plan_item: dict, running: Any) -> bool:
    if plan_item["mode"] == "exact-value":
        return not _equivalent_value(item["value"], running)

    target = _parse_path(plan_item["path"])[-1]
    exists = _segment_exists(running, target)
    if section == "delete":
        return exists
    return not exists


def srl_payload_delta(payload: dict, plan: list[dict], results: list[Any]) -> dict:
    """Prune already-matching operations using running values read from SR Linux."""
    if len(plan) != len(results):
        raise ValueError(
            f"running result count {len(results)} does not match read plan count {len(plan)}"
        )

    delta = _empty_payload()
    for plan_item, running in zip(plan, results, strict=True):
        section = plan_item["section"]
        item = payload[section][plan_item["index"]]
        if _operation_changed(section, item, plan_item, running):
            delta[section].append(item)
    return delta


def srl_payload_has_ops(payload: dict) -> bool:
    """Return True when a payload has at least one operation."""
    return any(payload.get(section) for section in RESOURCE_KEYS)


def _read_key_values(
    tokens: list[str],
    index: int,
    key_names: tuple[str, ...],
) -> tuple[list[str], int] | None:
    """Read key values after a YANG list node.

    Single-key lists use the readable form ``list-name: key-value``. Composite
    lists may either provide values directly or include the later key-leaf name.
    """
    cursor = index + 1
    key_values = []
    for key_index, key_name in enumerate(key_names):
        if cursor >= len(tokens):
            return None
        if key_index > 0 and tokens[cursor] == key_name:
            cursor += 1
            if cursor >= len(tokens):
                return None
        key_values.append(tokens[cursor])
        cursor += 1
    return key_values, cursor


def _key_selector(key_names: tuple[str, ...], key_values: list[str]) -> str:
    return "".join(
        f"[{key_name}={key_value}]"
        for key_name, key_value in zip(key_names, key_values, strict=True)
    )


def path_from_tokens(tokens: list[str]) -> str:
    """Render accumulated dict keys into a gNMI-style SR Linux path string."""
    parts = []
    index = 0
    node_path = []
    while index < len(tokens):
        token = tokens[index]
        node_path.append(token)
        key_names = LIST_KEY_PATHS.get(tuple(node_path))
        key_values = _read_key_values(tokens, index, key_names) if key_names else None
        if key_values:
            values, index = key_values
            parts.append(f"{token}{_key_selector(key_names, values)}")
        else:
            parts.append(token)
            index += 1
    return "/" + "/".join(parts)


def _node_path_from_tokens(tokens: list[str]) -> tuple[str, ...]:
    """Return only YANG node names from tokens, skipping list key values."""
    index = 0
    node_path = []
    while index < len(tokens):
        token = tokens[index]
        node_path.append(token)
        key_names = LIST_KEY_PATHS.get(tuple(node_path))
        key_values = _read_key_values(tokens, index, key_names) if key_names else None
        if key_values:
            _, index = key_values
        else:
            index += 1
    return tuple(node_path)


def _pending_composite_key(tokens: list[str]) -> bool:
    """Return True when tokens end at a later key leaf for a composite list."""
    index = 0
    node_path = []
    while index < len(tokens):
        token = tokens[index]
        node_path.append(token)
        key_names = LIST_KEY_PATHS.get(tuple(node_path))
        if not key_names:
            index += 1
            continue

        cursor = index + 1
        for key_index, key_name in enumerate(key_names):
            if cursor >= len(tokens):
                return False
            if key_index > 0 and tokens[cursor] == key_name:
                if cursor == len(tokens) - 1:
                    return True
                cursor += 1
                if cursor >= len(tokens):
                    return False
            cursor += 1
        index = cursor
    return False


def _append_value(tokens: list[str], value: Any, output: list[dict]) -> None:
    """Encode a leaf ``value`` at ``tokens`` into a ``{path, value}`` entry.

    Handles the SR Linux leaf shapes that do not follow the simple
    ``path + scalar`` rule (presence leaves, boolean/zero coercion, etc.).
    """
    key_names = LIST_KEY_PATHS.get(_node_path_from_tokens(tokens))
    if _pending_composite_key(tokens):
        output.append({"path": path_from_tokens(tokens + [value]), "value": {}})
    elif key_names and len(key_names) == 1:
        output.append({"path": path_from_tokens(tokens + [value]), "value": {}})
    elif len(tokens) >= 2 and tokens[-2:] == ["vlan", "encap"] and value == "untagged":
        output.append({"path": path_from_tokens(tokens + ["untagged"]), "value": {}})
    elif tokens and tokens[-1] == "interface-standby-signaling-on-non-df":
        output.append({"path": path_from_tokens(tokens), "value": {}})
    elif tokens and tokens[-1] == "primary":
        output.append({"path": path_from_tokens(tokens), "value": ""})
    elif tokens and tokens[-1] == "activation-timer" and "ethernet-segment" in tokens:
        output.append({"path": path_from_tokens(tokens[:-1]), "value": {"activation-timer": int(value)}})
    else:
        if type(value) is bool:
            value = str(value).lower()
        if type(value) is int and value == 0:
            value = "0"
        output.append({"path": path_from_tokens(tokens), "value": value})


def _walk_set(node: Any, tokens: list[str], output: list[dict]) -> None:
    """Recurse a ``set``/``replace`` subtree, emitting ``{path, value}`` entries."""
    if not isinstance(node, dict):
        _append_value(tokens, node, output)
        return
    if not node and tokens:
        output.append({"path": path_from_tokens(tokens), "value": {}})
        return
    for key, value in node.items():
        _walk_set(value, tokens + [key], output)


def _walk_delete(node: Any, tokens: list[str], output: list[dict]) -> None:
    """Recurse a ``delete`` subtree, emitting bare ``{path}`` entries."""
    if not isinstance(node, dict):
        return
    if not node and tokens:
        output.append({"path": path_from_tokens(tokens)})
        return
    for key, value in node.items():
        _walk_delete(value, tokens + [key], output)


def payload_from_config(config: dict) -> dict:
    """Convert a ``srl_config`` tree into update/replace/delete operation lists."""
    payload = _empty_payload()
    _walk_set(config.get("set", {}), [], payload["update"])
    _walk_set(config.get("replace", {}), [], payload["replace"])
    _walk_delete(config.get("delete", {}), [], payload["delete"])
    return payload


def srl_payload(hostvars: dict) -> dict:
    """Return native nokia.srlinux.config payload lists from readable node vars."""
    config = hostvars.get("srl_config") or {}
    payload = payload_from_config(config)

    for section, items in payload.items():
        if not isinstance(items, list):
            raise ValueError(f"{section} must be a list")
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"{section}[{index}] must be a dict")
            if not item.get("path"):
                raise ValueError(f"{section}[{index}] has no path")
            if section in ("update", "replace") and "value" not in item:
                raise ValueError(f"{section}[{index}] has no value")

    return payload


class FilterModule:
    def filters(self):
        return {
            "srl_payload": srl_payload,
            "srl_list_keys_version": srl_list_keys_version,
            "srl_release_version": srl_release_version,
            "srl_version_tuple": srl_version_tuple,
            "srl_version_newer_than": srl_version_newer_than,
            "srl_payload_read_plan": srl_payload_read_plan,
            "srl_payload_read_commands": srl_payload_read_commands,
            "srl_payload_delta": srl_payload_delta,
            "srl_payload_has_ops": srl_payload_has_ops,
        }
