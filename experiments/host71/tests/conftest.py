"""Isolated offline host tests; no provider transports or external sockets."""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
importlib.import_module("bootstrap_v3").initialize(offline=True)
