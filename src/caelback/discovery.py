"""Dynamic discovery of everything Caelestia-related on the live system.

Only a small set of well-known roots are hardcoded (Caelestia's own config/
state dirs, LiveWall since it's tightly coupled). Everything else -- themed
third-party apps, browser extensions, whatever shows up next -- is found by
a fuzzy scan for "caelestia" in path names under ~/.config, ~/.local/share,
and ~/.local/state, so a new app Caelestia starts theming doesn't require
updating this file.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()

NAMED_CONFIG_DIRS = ["hypr", "caelestia", "livewall"]

NAMED_STATE_DIRS = [
    HOME / ".local/share/caelestia-aw",
    HOME / ".local/state/caelestia",
    HOME / ".local/share/livewall",
]

FUZZY_SCAN_ROOTS = [
    HOME / ".config",
    HOME / ".local/share",
    HOME / ".local/state",
]

FUZZY_SKIP_DIRNAMES = {".git", "node_modules", "__pycache__", ".cache"}
FUZZY_MATCH_TERM = "caelestia"

PACKAGE_NAME_PATTERNS = ["caelestia", "quickshell"]

SYSTEMD_USER_DIR = HOME / ".config/systemd/user"
SYSTEMD_UNIT_PATTERNS = ["caelestia", "livewall"]

SDDM_SESSIONS_DIR = Path("/usr/share/wayland-sessions")
SDDM_SESSION_PATTERN = "hyprland"

_ROOT_TAGS = {
    HOME / ".config": "config",
    HOME / ".local/share": "local-share",
    HOME / ".local/state": "local-state",
}


@dataclass
class DiscoveredPath:
    src: Path
    label: str  # dest subpath inside the snapshot, also the manifest key


@dataclass
class Discovery:
    config_dirs: list[DiscoveredPath] = field(default_factory=list)
    state_dirs: list[DiscoveredPath] = field(default_factory=list)
    extra_matches: list[DiscoveredPath] = field(default_factory=list)
    systemd_units: list[str] = field(default_factory=list)
    sddm_sessions: list[str] = field(default_factory=list)

    def all_paths(self) -> list[DiscoveredPath]:
        return self.config_dirs + self.state_dirs + self.extra_matches


def discover_config_dirs() -> list[DiscoveredPath]:
    found = []
    for name in NAMED_CONFIG_DIRS:
        p = HOME / ".config" / name
        if p.exists():
            found.append(DiscoveredPath(p, f"config/{name}"))
    return found


def discover_state_dirs() -> list[DiscoveredPath]:
    found = []
    for p in NAMED_STATE_DIRS:
        if p.exists():
            found.append(DiscoveredPath(p, f"state/{_state_label(p)}"))
    return found


def _state_label(p: Path) -> str:
    parts = p.parts
    idx = parts.index(".local")
    kind = parts[idx + 1]  # share|state
    return f"{kind}-{p.name}"


def discover_extra_matches(already_captured: list[Path]) -> list[DiscoveredPath]:
    excluded_roots = {p.resolve() for p in already_captured if p.exists()}
    found: list[DiscoveredPath] = []
    seen: set[Path] = set()

    for root in FUZZY_SCAN_ROOTS:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            dirnames[:] = [d for d in dirnames if d not in FUZZY_SKIP_DIRNAMES]

            keep = []
            for d in dirnames:
                candidate = current / d
                if _is_excluded(candidate, excluded_roots):
                    continue  # already captured as a named dir, don't double-copy
                if FUZZY_MATCH_TERM in d.lower():
                    _add(found, seen, candidate, root)
                    continue  # whole dir captured as one unit, don't descend further
                keep.append(d)
            dirnames[:] = keep

            for f in filenames:
                if FUZZY_MATCH_TERM in f.lower():
                    _add(found, seen, current / f, root)

    return found


def _is_excluded(path: Path, excluded_roots: set[Path]) -> bool:
    try:
        rp = path.resolve()
    except OSError:
        rp = path
    return rp in excluded_roots


def _add(found: list[DiscoveredPath], seen: set[Path], match: Path, scan_root: Path) -> None:
    if match in seen:
        return
    seen.add(match)
    rel = match.relative_to(scan_root)
    tag = _ROOT_TAGS.get(scan_root, scan_root.name)
    found.append(DiscoveredPath(match, f"extra/{tag}/{rel}"))


def discover_systemd_units() -> list[str]:
    if not SYSTEMD_USER_DIR.exists():
        return []
    return sorted(
        p.name
        for p in SYSTEMD_USER_DIR.iterdir()
        if p.is_file() and any(term in p.name.lower() for term in SYSTEMD_UNIT_PATTERNS)
    )


def discover_sddm_sessions() -> list[str]:
    if not SDDM_SESSIONS_DIR.exists():
        return []
    return sorted(
        p.name
        for p in SDDM_SESSIONS_DIR.iterdir()
        if p.suffix == ".desktop" and SDDM_SESSION_PATTERN in p.name.lower()
    )


def is_caelestia_present() -> bool:
    """Whether Caelestia itself is actually installed/configured right now.

    Deliberately checks only for "caelestia", not the broader
    PACKAGE_NAME_PATTERNS (which also matches "quickshell") -- quickshell is a
    generic Wayland shell toolkit that other things on this machine (e.g. a
    separate from-scratch shell project) can depend on independently of
    Caelestia, so its presence alone would be a false positive. Used to gate
    the periodic snapshot timer so it doesn't keep taking -- and pruning
    away -- snapshots after Caelestia has actually been removed.
    """
    if (HOME / ".config/caelestia").exists():
        return True
    result = subprocess.run(["pacman", "-Q"], text=True, capture_output=True)
    for line in result.stdout.splitlines():
        name = line.split(maxsplit=1)[0] if line else ""
        if "caelestia" in name.lower():
            return True
    return False


def discover() -> Discovery:
    config_dirs = discover_config_dirs()
    state_dirs = discover_state_dirs()
    already = [d.src for d in config_dirs] + [d.src for d in state_dirs]
    extra_matches = discover_extra_matches(already)
    return Discovery(
        config_dirs=config_dirs,
        state_dirs=state_dirs,
        extra_matches=extra_matches,
        systemd_units=discover_systemd_units(),
        sddm_sessions=discover_sddm_sessions(),
    )
