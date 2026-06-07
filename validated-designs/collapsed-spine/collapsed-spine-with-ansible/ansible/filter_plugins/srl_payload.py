"""SR Linux payload filters for the collapsed-spine Ansible variant.

This filter turns the readable ``srl_config`` tree authored in ``host_vars``
into the native operation lists consumed by ``nokia.srlinux.config``
(``update`` / ``replace`` / ``delete``). Keeping this transformation in a
Python filter plugin (rather than Jinja2 templates) follows the Ansible good
practice that structured-data transformation belongs in a plugin, not a
template.
"""

from typing import Any

RESOURCE_KEYS = ("update", "replace", "delete")

LIST_KEYS = {
    "afi-safi": "afi-safi-name",
    "bgp-instance": "id",
    "buffer": "buffer-name",
    "dynamic-neighbor": "peer-address",
    "ethernet-segment": "name",
    "group": "group-name",
    "interface": "name",
    "network-instance": "name",
    "policy": "name",
    "prefix": "ip-prefix",
    "prefix-set": "name",
    "statement": "name",
    "subinterface": "index",
    "subsystem": "subsystem-name",
    "tunnel-interface": "name",
    "vxlan-interface": "index",
    "address": "ip-prefix",
    "advertise": "route-type",
}


def _is_keyed(tokens: list[str], index: int) -> bool:
    """Return True when ``tokens[index]`` is a YANG keyed-list node.

    A keyed-list node means the following token is the list key value and the
    two must be rendered as ``node[key=value]`` rather than two path segments.
    """
    token = tokens[index]
    if token not in LIST_KEYS or index + 1 >= len(tokens):
        return False
    if token == "network-instance" and tokens[:index] == ["system"]:
        return False
    if token == "prefix":
        return index >= 2 and tokens[index - 2] == "prefix-set"
    if token == "address":
        return index >= 1 and tokens[index - 1] in ("ipv4", "ipv6")
    return True


def _key_name(tokens: list[str], index: int) -> str:
    """Return the YANG key-leaf name for the keyed-list node at ``index``."""
    if tokens[index] == "interface" and index >= 1 and tokens[index - 1] == "dynamic-neighbors":
        return "interface-name"
    if tokens[index] == "interface" and index >= 2 and tokens[index - 2] == "ethernet-segment":
        return "ethernet-interface"
    if tokens[index] == "subinterface" and tokens[:index] == ["bfd"]:
        return "id"
    return LIST_KEYS[tokens[index]]


def path_from_tokens(tokens: list[str]) -> str:
    """Render accumulated dict keys into a gNMI-style SR Linux path string."""
    parts = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _is_keyed(tokens, index):
            parts.append(f"{token}[{_key_name(tokens, index)}={tokens[index + 1]}]")
            index += 2
        else:
            parts.append(token)
            index += 1
    return "/" + "/".join(parts)


def _append_value(tokens: list[str], value: Any, output: list[dict]) -> None:
    """Encode a leaf ``value`` at ``tokens`` into a ``{path, value}`` entry.

    Handles the SR Linux leaf shapes that do not follow the simple
    ``path + scalar`` rule (keyed addresses, presence leaves, EVPN advertise
    route-types, boolean/zero coercion, etc.).
    """
    if len(tokens) >= 2 and tokens[-2:] == ["vlan", "encap"] and value == "untagged":
        output.append({"path": path_from_tokens(tokens + ["untagged"]), "value": {}})
    elif len(tokens) >= 3 and tokens[-3] == "prefix" and tokens[-1] == "mask-length-range":
        parent = path_from_tokens(tokens[:-3])
        output.append({"path": f"{parent}/prefix[ip-prefix={tokens[-2]}][mask-length-range={value}]", "value": {}})
    elif len(tokens) >= 2 and tokens[-1] == "address" and tokens[-2] in ("ipv4", "ipv6") and isinstance(value, str):
        output.append({"path": path_from_tokens(tokens[:-1]), "value": {"address": [{"ip-prefix": value}]}})
    elif tokens and tokens[-1] == "interface-standby-signaling-on-non-df":
        output.append({"path": path_from_tokens(tokens), "value": {}})
    elif tokens and tokens[-1] == "primary":
        output.append({"path": path_from_tokens(tokens), "value": ""})
    elif len(tokens) >= 2 and tokens[-2:] == ["evpn", "advertise"] and isinstance(value, str):
        output.append({"path": path_from_tokens(tokens + [value]), "value": {}})
    elif tokens and tokens[-1] == "activation-timer" and "ethernet-segment" in tokens:
        output.append({"path": path_from_tokens(tokens[:-1]), "value": {"activation-timer": int(value)}})
    elif tokens and tokens[-1] == "interface" and "ethernet-segment" in tokens and isinstance(value, str):
        output.append({"path": path_from_tokens(tokens + [value]), "value": {}})
    elif (
        len(tokens) == 3
        and tokens[0] == "network-instance"
        and tokens[-1] == "vxlan-interface"
        and isinstance(value, str)
    ):
        output.append({"path": path_from_tokens(tokens[:-1]), "value": {"vxlan-interface": [{"name": value}]}})
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
