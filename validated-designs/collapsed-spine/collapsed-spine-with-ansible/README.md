# Collapsed Spine NVD with Ansible

Ansible-managed deployment of the collapsed-spine Nokia Validated Design using
Containerlab, SR Linux, and Linux endpoint containers.

![Collapsed spine topology](/static/images/collapsed-spine-lld.png)

## What This Variant Does

This lab uses the same topology and service intent as the non-EDA collapsed
spine variant, but Ansible owns the deployment lifecycle.

| Area | Owner | Notes |
| --- | --- | --- |
| SR Linux fabric | `nokia.srlinux` | One config transaction per SR Linux node |
| Linux endpoints | `community.docker` | VLANs, bonds, addresses, routes, and ping checks |
| Topology | Containerlab | No endpoint startup `exec` blocks |
| Intent | Ansible vars | Inventory and `host_vars/` are the source of truth; add `group_vars/` only when shared values are consumed |

Covered connectivity cases:

- Layer 2 untagged server connectivity.
- Layer 2 tagged server connectivity.
- Layer 3 server connectivity.
- All-active EVPN Ethernet Segment LAG multihoming.
- Single-active EVPN Ethernet Segment multihoming with LACP standby signaling.
- IPv4 and IPv6 validation across the endpoint use cases.

## The Short Path

Run from this directory:

```bash
cd /Users/md/git/network/nokia/nokia-validated-designs/validated-designs/collapsed-spine/collapsed-spine-with-ansible

uv sync
uv run ansible-galaxy collection install -r requirements.yml

containerlab deploy -t 2-way-collapsed-spine.clab.yaml
containerlab inspect -t 2-way-collapsed-spine.clab.yaml

uv run ansible-playbook playbooks/deploy.yml
uv run ansible-playbook playbooks/validate.yml
uv run ansible-playbook playbooks/deploy.yml
```

The last deploy is the idempotency check. A healthy final recap has
`changed=0` and `failed=0` for every host.

Do not run the playbooks with only `uvx --from ansible-core ...`; that misses
the Python libraries required by `community.docker`. Use `uv run ...` from this
directory.

## Requirements

| Requirement | Why |
| --- | --- |
| Docker | Runs SR Linux and endpoint containers |
| Containerlab | Builds the lab topology |
| `uv` | Provides the pinned Ansible runtime |
| GHCR access | Pulls `ghcr.io/nokia/srlinux:25.3.2` |

Tested components:

| Component | Version |
| --- | --- |
| SR Linux image | `25.3.2` |
| `ansible-core` | `2.21.0` |
| `ansible-lint` | `26.4.0` |
| `nokia.srlinux` collection | `1.1.0` |
| `community.docker` collection | `3.13.4` |

## Lab Inventory

| Node | Type | Management |
| --- | --- | --- |
| `spine1` | SR Linux spine | `172.21.21.101` |
| `spine2` | SR Linux spine | `172.21.21.102` |
| `tor1` | SR Linux ToR | `172.21.21.11` |
| `tor2` | SR Linux ToR | `172.21.21.12` |
| `tor3` | SR Linux ToR | `172.21.21.13` |
| `s1`..`s6` | Linux endpoints | Docker container names |

SR Linux credentials:

```text
username: admin
password: NokiaSrl1!
```

The topology uses `prefix: ""`, so the Linux containers are named `s1`, `s2`,
`s3`, `s4`, `s5`, and `s6`. If the topology prefix changes, update
`ansible/inventory.yml` before running the endpoint play.

## Project Layout

```text
collapsed-spine-with-ansible/
  2-way-collapsed-spine.clab.yaml
  ansible.cfg
  pyproject.toml
  requirements.yml
  ansible/
    inventory.yml
    host_vars/
    filter_plugins/srl_payload.py
    roles/
      srl_config/
      linux_endpoint/
      srl_validate/
  playbooks/
    deploy.yml
    validate.yml
  tests/
    test_srl_payload.py
```

Read-only fidelity oracles:

```text
../collapsed-spine-without-eda/configs/*.cli
../collapsed-spine-without-eda/base-configs/*.sh
```

## Runbook

Prepare the Python runtime and Ansible collections:

```bash
uv sync
uv run ansible-galaxy collection install -r requirements.yml
```

Start or refresh the topology:

```bash
containerlab deploy -t 2-way-collapsed-spine.clab.yaml
containerlab inspect -t 2-way-collapsed-spine.clab.yaml
```

Expected lab size:

```text
11 nodes: spine1 spine2 tor1 tor2 tor3 s1 s2 s3 s4 s5 s6
```

Run static checks:

```bash
uv run ansible-playbook playbooks/deploy.yml --syntax-check
uv run ansible-lint playbooks/deploy.yml playbooks/validate.yml
```

Preview config changes:

```bash
uv run ansible-playbook playbooks/deploy.yml --check --diff
```

Deploy:

```bash
uv run ansible-playbook playbooks/deploy.yml
```

Validate:

```bash
uv run ansible-playbook playbooks/validate.yml
```

Check idempotency:

```bash
uv run ansible-playbook playbooks/deploy.yml
```

## Expected Results

| Gate | Good result |
| --- | --- |
| Collection install | `Nothing to do` or successful install |
| Containerlab inspect | 11 nodes shown as running |
| Syntax check | `playbook: playbooks/deploy.yml` |
| Lint | `Passed: 0 failure(s), 0 warning(s)` |
| Deploy | `failed=0` |
| Validate | `failed=0` |
| Idempotency | `changed=0 failed=0` |

Validation checks include BGP neighbors, Ethernet Segments, LAG health,
network-instance presence, same-VLAN pings, routed pings, VLAN 10 across
spine1 untagged and spine2 tagged access, and the `s3` bond.

Single-active non-DF LAG state may show `standby-signaling`. That is expected
for this design and is treated as healthy by validation.

## Common Operations

Limit deployment to one SR Linux node:

```bash
uv run ansible-playbook playbooks/deploy.yml --limit spine1
```

Validate only spines:

```bash
uv run ansible-playbook playbooks/validate.yml --limit collapsed_spines
```

Run with more detail:

```bash
uv run ansible-playbook playbooks/deploy.yml --limit spine1 -vvv
```

Use an SR Linux confirmed commit timeout:

```bash
uv run ansible-playbook playbooks/deploy.yml -e srl_confirm_timeout=300
```

Override save behavior:

```bash
uv run ansible-playbook playbooks/deploy.yml -e srl_save_when=always
```

Tear down the lab:

```bash
containerlab destroy -t 2-way-collapsed-spine.clab.yaml --cleanup
```

## Manual Checks

Open an SR Linux CLI:

```bash
ssh admin@172.21.21.101
```

Run an SR Linux command through Ansible:

```bash
uv run ansible all --limit srl \
  -m nokia.srlinux.cli \
  -a '{"commands":["show system information"]}'
```

Inspect endpoint state:

```bash
docker exec s3 ip -br link
docker exec s3 cat /proc/net/bonding/bond0
docker exec s1 ip route
docker exec s1 ip rule
```

Run endpoint pings by hand:

```bash
docker exec s1 ping -c 3 172.16.10.2
docker exec s1 ping -c 3 -I 172.16.20.1 172.16.50.4
docker exec s1 ping6 -c 3 -I 2001:db8:0:20::1 2001:db8:0:50::4
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `Failed to import the required Python library (requests)` | Playbook was run with `uvx --from ansible-core` instead of the project runtime | Run `uv sync`, then `uv run ansible-playbook playbooks/validate.yml` |
| `containerlab: command not found` | Containerlab is not installed or not in `PATH` | Install Containerlab and rerun the deploy command |
| SR Linux HTTPS connection fails | Node is not running, IP mismatch, or API not ready yet | Run `containerlab inspect -t 2-way-collapsed-spine.clab.yaml` and compare with `ansible/inventory.yml` |
| Fewer than 11 nodes in inspect output | Topology did not fully start | Check `docker ps -a`, destroy with `--cleanup`, and deploy again |
| `nokia.srlinux.validate` fails | Payload path/value shape does not match the SR Linux model | Re-run with `-vvv` and fix readable vars or `ansible/filter_plugins/srl_payload.py` |
| `ping: bind: Address not available` | Endpoint addresses are missing because endpoint deploy has not run against the current containers | Run `uv run ansible-playbook playbooks/deploy.yml --limit linux_clients` |
| Endpoint routed pings fail | Endpoint source policy/routing state is missing or stale | Re-run `uv run ansible-playbook playbooks/deploy.yml --limit linux_clients` |
| `s3` bond validation fails | Linux bond or connected SR Linux LAG/ES is down | Check `docker exec s3 cat /proc/net/bonding/bond0` and validate `s3:spine1:spine2` |
| Second deploy reports changes | Something is not round-tripping idempotently | Run `uv run ansible-playbook playbooks/deploy.yml --check --diff -vv` on the changed host |

Useful troubleshooting commands:

```bash
docker pull ghcr.io/nokia/srlinux:25.3.2
docker ps --format '{{.Names}}' | sort
rg -n '^prefix:|ansible_host: s[1-6]' 2-way-collapsed-spine.clab.yaml ansible/inventory.yml
uv run ansible-playbook playbooks/validate.yml --limit 's3:spine1:spine2'
```

## Intent Model: `set`, `replace`, `delete`

Node vars in `host_vars/` are written as a readable tree under `srl_config`.
The `srl_payload` filter (`ansible/filter_plugins/srl_payload.py`) turns that
tree into native `nokia.srlinux.config` operations, and the device applies them
in one transaction (deletes first, then replaces, then updates).

You author intent with three buckets:

| Bucket | Maps to | Meaning | "State module" equivalent |
| --- | --- | --- | --- |
| `set:` | `update` | Merge: add/modify only the leaves you list; undescribed config is left alone | `state: merged` |
| `replace:` | `replace` | Replace the exact generated path; non-empty trees walk to leaf paths, while `{}` marks a container/list path | `state: replaced` at that path |
| `delete:` | `delete` | Remove the targeted subtree (use `{}` to mark the point to prune) | `state: absent` |

The Nokia module has no `state:` keyword; these operations are the equivalent.
All three buckets are wired through the filter (`payload_from_config`) and the
role, so choosing between them is purely a vars-authoring decision. The
transformation is covered by unit tests in `tests/test_srl_payload.py`
(run `uv run pytest`).

How to think about it:

- Use `set:` for normal additive intent. It is safe and non-destructive.
- Use `delete:` to prune known config (for example the factory-default
  `ssh-key: {}` placeholders).
- Use `replace:` only when automation must be the single source of truth for a
  generated path and should purge any local config below that path.

Important: `replace` is **path-scoped**, not global. Replacing at
`/interface[name=ethernet-1/55]/admin-state` replaces only that leaf. A
non-empty readable tree such as `replace: {interface: {ethernet-1/55:
{admin-state: enable}}}` generates that leaf path, not a whole-interface replace.
Use `{}` only when the exact container/list path is the intended replace target,
for example `replace: {interface: {ethernet-1/55: {}}}` generates
`/interface[name=ethernet-1/55]` with an empty value. Replacing at the root would
force the entire running config to match your vars. Avoid root-level replace on a
live node — you must then declare every leaf the node needs (management
network-instance, AAA, TLS profiles), or you can lock yourself out
mid-transaction.

This design deliberately uses `set:` plus targeted `delete:` rather than
`replace:`. It keeps changes non-destructive on shared/lab nodes, prunes only
known defaults explicitly, and avoids the burden of enumerating every required
leaf. Reach for `replace:` only when the generated path is config this automation
fully owns.

## Design Rules

- The Ansible inventory and `host_vars/` are the deployable intent. Add
  `group_vars/` only for shared values that are actually consumed by roles.
- Do not add an `intent/` directory.
- Do not store rendered JSON, generated SR Linux payloads, `srl_resources`, or
  resource inventory sidecars.
- Use plain YAML scalars for leaf values and `{}` for presence-only leaves; no
  private marker keys in vars.
- Do not use `rpc_*` roles or Jinja-templated SR Linux JSON.
- Keep the two spines asymmetric where the design is asymmetric.
- Keep Linux endpoint setup in Ansible, not Containerlab `exec` startup blocks.

## References

- Containerlab deploy: https://containerlab.dev/cmd/deploy/
- Containerlab inspect: https://containerlab.dev/cmd/inspect/
- Ansible check and diff mode: https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_checkmode.html
- Ansible lint usage: https://docs.ansible.com/projects/lint/usage/
- Nokia SR Linux Ansible collection: https://learn.srlinux.dev/tutorials/programmability/ansible/using-nokia-srlinux-collection/
