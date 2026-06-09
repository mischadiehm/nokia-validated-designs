"""SR Linux payload filters for the collapsed-spine Ansible variant.

This filter turns the readable ``srl_config`` tree authored in ``host_vars``
into the native operation lists consumed by ``nokia.srlinux.config``
(``update`` / ``replace`` / ``delete``). Keeping this transformation in a
Python filter plugin (rather than Jinja2 templates) follows the Ansible good
practice that structured-data transformation belongs in a plugin, not a
template.
"""

import importlib.util
from pathlib import Path
from typing import Any

RESOURCE_KEYS = ("update", "replace", "delete")


def _load_list_key_paths() -> dict[tuple[str, ...], tuple[str, ...]]:
    list_keys_path = Path(__file__).resolve().parents[1] / "srl_list_keys.py"
    spec = importlib.util.spec_from_file_location("srl_list_keys", list_keys_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {list_keys_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LIST_KEY_PATHS


LIST_KEY_PATHS = _load_list_key_paths()


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
    payload: dict[str, list] = {key: [] for key in RESOURCE_KEYS}
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
        return {"srl_payload": srl_payload}
