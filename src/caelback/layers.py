"""Finds Hyprland layer-shell surfaces (bars, wallpaper daemons, overlays --
distinct from regular app windows) that don't look like they belong to
Caelestia's own ecosystem, so leftover processes from whatever was
dotfile-hopped to can be cleaned up instead of drawing over Caelestia
after a restore.

Deliberately pattern-based, not a hardcoded list of "known bad" rice names --
the whole point is this should catch the *next* dotfile-hop target too, not
just the one that happened to be tried once.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

EXPECTED_PATTERNS = ["caelestia", "quickshell", "mpvpaper", "livewall"]


@dataclass
class LayerOwner:
    pid: int
    namespace: str
    cmdline: str


def _process_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode(errors="replace").strip()


def _is_expected(cmdline: str) -> bool:
    lower = cmdline.lower()
    return any(term in lower for term in EXPECTED_PATTERNS)


def find_unexpected_layer_owners() -> list[LayerOwner]:
    """Every distinct pid holding a Hyprland layer-shell surface whose own
    cmdline doesn't mention Caelestia/Quickshell/mpvpaper/LiveWall."""
    result = subprocess.run(["hyprctl", "layers", "-j"], text=True, capture_output=True)
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    seen_pids: set[int] = set()
    unexpected: list[LayerOwner] = []
    for monitor in data.values():
        for level in monitor.get("levels", {}).values():
            for surface in level:
                pid = surface.get("pid")
                if not pid or pid in seen_pids:
                    continue
                seen_pids.add(pid)
                cmdline = _process_cmdline(pid)
                if cmdline and not _is_expected(cmdline):
                    unexpected.append(LayerOwner(pid=pid, namespace=surface.get("namespace", ""), cmdline=cmdline))
    return unexpected


def kill_owners(owners: list[LayerOwner]) -> None:
    for o in owners:
        try:
            os.kill(o.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # already gone
