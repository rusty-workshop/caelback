"""Finds Hyprland layer-shell surfaces (bars, wallpaper daemons, overlays --
distinct from regular app windows) that don't look like they belong to
Caelestia's own ecosystem, so leftover processes from whatever was
dotfile-hopped to can be cleaned up instead of drawing over Caelestia
after a restore.

The actual safety mechanism is deny-by-default: anything holding a layer
whose cmdline doesn't match EXPECTED_PATTERNS gets flagged, whatever it's
called -- so this catches the *next* dotfile-hop target too, not just one
that happened to be tried once. KNOWN_FOREIGN_TOOLS is purely cosmetic on
top of that (labels a flagged process by name when recognized); it does
not affect which processes get flagged.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Caelestia's own ecosystem, plus standing companion daemons that are a
# normal, wanted part of this machine's setup and not artifacts of any
# particular dotfile-hop target -- Caelestia's own shell doesn't handle
# notifications itself, see project_hyprland_de's Loom investigation. Both
# dunst and swaync are listed: a 2026-08-18 dotfile-hop incident confirmed
# swaync is this machine's actual notification daemon (a manual pre-hop
# backup of it existed, and it was the one actually running), correcting an
# earlier assumption that dunst was -- kept dunst too rather than swap one
# assumption for another, since either could legitimately be in use.
EXPECTED_PATTERNS = ["caelestia", "quickshell", "mpvpaper", "livewall", "dunst", "swaync"]

# Purely for labeling a flagged process in output -- "this looks like X."
# Not exhaustive by design (the deny-by-default check above already covers
# anything not on this list); just makes common cases easier to recognize
# at a glance instead of showing a bare cmdline. Longer/more specific
# patterns first so e.g. "hyprpaper" doesn't get shadowed by a shorter
# unrelated substring.
KNOWN_FOREIGN_TOOLS: list[tuple[str, str]] = [
    # Status bars / shells
    ("waybar", "Waybar (status bar)"),
    ("hyprpanel", "HyprPanel (status bar)"),
    ("ironbar", "Ironbar (status bar)"),
    ("polybar", "Polybar (status bar)"),
    ("yambar", "Yambar (status bar)"),
    ("ags", "AGS/Astal (widget shell)"),
    ("astal", "AGS/Astal (widget shell)"),
    ("eww", "eww (ElKowars wacky widgets)"),
    ("fabric", "Fabric (Python widget framework)"),
    ("mewline", "mewline (meowrch's bar)"),
    # Wallpaper daemons
    ("swaybg", "swaybg (static wallpaper)"),
    ("swww", "swww (wallpaper daemon)"),
    ("hyprpaper", "hyprpaper (wallpaper daemon)"),
    ("wpaperd", "wpaperd (wallpaper daemon)"),
    ("awww", "awww (meowrch's wallpaper daemon)"),
    ("mpvwallpaper", "mpv-based wallpaper tool"),
    # Lock screens / idle / power
    ("hyprlock", "hyprlock (lock screen)"),
    ("swaylock", "swaylock (lock screen)"),
    ("gtklock", "gtklock (lock screen)"),
    ("wlogout", "wlogout (power menu)"),
    ("swayidle", "swayidle (idle daemon)"),
    ("hypridle", "hypridle (idle daemon)"),
    # Launchers / notification centers (only relevant if one holds a layer)
    ("wofi", "wofi (launcher)"),
    ("rofi", "rofi (launcher)"),
    ("fuzzel", "fuzzel (launcher)"),
    ("mako", "mako (notification daemon)"),
    ("swaync", "SwayNC (notification center)"),
]


@dataclass
class LayerOwner:
    pid: int
    namespace: str
    cmdline: str
    label: str | None = None


def _process_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode(errors="replace").strip()


def _is_expected(cmdline: str) -> bool:
    lower = cmdline.lower()
    return any(term in lower for term in EXPECTED_PATTERNS)


def _identify(cmdline: str) -> str | None:
    lower = cmdline.lower()
    for term, label in KNOWN_FOREIGN_TOOLS:
        if term in lower:
            return label
    return None


def find_unexpected_layer_owners() -> list[LayerOwner]:
    """Every distinct pid holding a Hyprland layer-shell surface whose own
    cmdline doesn't match EXPECTED_PATTERNS."""
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
                    unexpected.append(
                        LayerOwner(
                            pid=pid,
                            namespace=surface.get("namespace", ""),
                            cmdline=cmdline,
                            label=_identify(cmdline),
                        )
                    )
    return unexpected


def format_owner(o: LayerOwner) -> str:
    if o.label:
        return f"pid {o.pid} ({o.namespace}): {o.label} — {o.cmdline}"
    return f"pid {o.pid} ({o.namespace}): {o.cmdline}"


def kill_owners(owners: list[LayerOwner]) -> None:
    for o in owners:
        try:
            os.kill(o.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # already gone
