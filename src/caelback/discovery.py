"""Dynamic discovery of everything Caelestia-related on the live system.

A small set of well-known roots are hardcoded (Caelestia's own config/state
dirs, LiveWall since it's tightly coupled, and the desktop-theming apps
listed below). Everything else -- themed third-party apps, browser
extensions, whatever shows up next -- is found by a fuzzy scan for
"caelestia" in path names under ~/.config, ~/.local/share, and
~/.local/state, so a new app Caelestia starts theming doesn't require
updating this file.

The fuzzy scan only catches apps whose *path name* contains "caelestia" --
it can never find one that doesn't, no matter how thoroughly Caelestia
themes it. THEMED_APP_DIRS below exists because of exactly that gap: on
2026-08-18, restoring after a dotfile-hop correctly reverted ~/.config/hypr
but left qt5ct/qt6ct, swaync, kitty, rofi, waybar, starship, yazi, btop,
cava, and fastfetch silently on the other repo's (KoolDots) theming --
notifications and Qt apps stayed in a light Catppuccin-Latte scheme, and
the terminal fetch banner kept KoolDots' own branding, invisibly, until
someone noticed. None of those paths contain "caelestia" by name, so no
fuzzy scan could ever have caught them. This list is grounded in exactly
the apps the user had *already* judged worth manually backing up before
that hop -- not a guess at "anything themeable."
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()

# Desktop-theming apps Caelestia customizes but that don't have "caelestia"
# anywhere in their own config path -- see the module docstring for why this
# list exists. Only captured if actually present (discover_config_dirs
# checks existence per-entry), so this is safe even on a machine that
# doesn't have all of them installed.
THEMED_APP_DIRS = [
    "kitty", "rofi", "waybar", "starship", "yazi", "btop", "cava",
    "fastfetch", "swaync", "qt5ct", "qt6ct", "quickshell",
]

NAMED_CONFIG_DIRS = ["hypr", "caelestia", "livewall"] + THEMED_APP_DIRS

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

# caelback's own move-aside suffix (see util.move_aside). Never treat one of
# these as real content to back up -- it's a byproduct of a *previous*
# restore, not current Caelestia state, and re-capturing it would let a
# stale one get silently resurrected by a future restore.
CAELBACK_ARTIFACT_MARKER = ".pre-restore-"

PACKAGE_NAME_PATTERNS = ["caelestia", "quickshell"]

SYSTEMD_USER_DIR = HOME / ".config/systemd/user"
SYSTEMD_UNIT_PATTERNS = ["caelestia", "livewall"]

SDDM_SESSIONS_DIR = Path("/usr/share/wayland-sessions")
SDDM_SESSION_PATTERN = "hyprland"

SDDM_THEMES_DIR = Path("/usr/share/sddm/themes")
SDDM_CONFIG_FILE = Path("/etc/sddm.conf")

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
    sddm_theme: str | None = None

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
                if _is_excluded(candidate, excluded_roots) or CAELBACK_ARTIFACT_MARKER in d:
                    continue  # already captured as a named dir, or it's caelback's own leftover -- skip either way
                if FUZZY_MATCH_TERM in d.lower():
                    _add(found, seen, candidate, root)
                    continue  # whole dir captured as one unit, don't descend further
                keep.append(d)
            dirnames[:] = keep

            for f in filenames:
                if CAELBACK_ARTIFACT_MARKER in f:
                    continue
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


def discover_sddm_theme() -> str | None:
    """Which theme sddm is *actually* using -- not which config file claims
    to set it.

    /etc/sddm.conf and /etc/sddm.conf.d/*.conf can disagree about the
    `Current` theme (found live on 2026-08-22: sddm.conf said one theme,
    a conf.d override claimed a different one predating it, and only the
    sddm log itself said which had actually been loaded at the last real
    login -- the assumed "conf.d overrides the base file" precedence
    didn't hold here, or something else about the local setup broke it).
    Reimplementing sddm's own config-merge logic well enough to trust it
    isn't worth it when sddm already logs the ground truth: query the
    current boot's journal for the theme it reported loading, and use
    that. Falls back to reading sddm.conf's [Theme] Current directly if
    the journal has nothing (e.g. sddm hasn't logged that line on this
    sddm version, or the journal's been cleared) -- a best-effort second
    opinion, not a claim it's authoritative.
    """
    result = subprocess.run(
        ["journalctl", "-u", "sddm", "-b", "--no-pager", "-g", "Loading theme configuration"],
        text=True,
        capture_output=True,
    )
    lines = [line for line in result.stdout.splitlines() if "Loading theme configuration" in line]
    if lines:
        m = re.search(r"themes/([^/\"]+)/theme\.conf", lines[-1])
        if m:
            return m.group(1)

    if SDDM_CONFIG_FILE.exists():
        try:
            for line in SDDM_CONFIG_FILE.read_text().splitlines():
                if line.strip().startswith("Current="):
                    return line.split("=", 1)[1].strip() or None
        except OSError:
            pass
    return None


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
        sddm_theme=discover_sddm_theme(),
    )
