"""Pytest configuration: import the installed nokia.srlinux collection and
make the lab tooling importable."""

import subprocess
import sys
import types
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
COLLECTION_ROOT = LAB_ROOT / ".collections" / "ansible_collections" / "nokia" / "srlinux"
sys.path.insert(0, str(LAB_ROOT / "tools"))


def _install_collection_namespace() -> None:
    packages = {
        "ansible_collections": [],
        "ansible_collections.nokia": [],
        "ansible_collections.nokia.srlinux": [str(COLLECTION_ROOT)],
    }
    for name, paths in packages.items():
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            module.__path__ = paths
            sys.modules[name] = module
        else:
            existing = list(getattr(module, "__path__", []))
            module.__path__ = existing + [p for p in paths if p not in existing]
    sys.modules["ansible_collections"].nokia = sys.modules["ansible_collections.nokia"]
    sys.modules["ansible_collections.nokia"].srlinux = sys.modules[
        "ansible_collections.nokia.srlinux"
    ]


_install_collection_namespace()


def render_all_nodes(tmp_dir: Path) -> Path:
    """Render every SR Linux node's operations via the real Ansible stack."""
    result = subprocess.run(
        [
            "ansible-playbook",
            "playbooks/render.yml",
            "-e",
            f"render_dir={tmp_dir}",
        ],
        cwd=LAB_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"render playbook failed:\n{result.stdout}\n{result.stderr}")
    return tmp_dir
