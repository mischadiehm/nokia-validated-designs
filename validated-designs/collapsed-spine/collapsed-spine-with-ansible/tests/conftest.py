"""Pytest configuration: make the Ansible filter plugin importable."""

import sys
from pathlib import Path

FILTER_PLUGINS = Path(__file__).resolve().parents[1] / "ansible" / "filter_plugins"
sys.path.insert(0, str(FILTER_PLUGINS))
