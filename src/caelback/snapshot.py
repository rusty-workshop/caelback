"""Orchestrates taking a full snapshot of the live Caelestia-related state."""

from __future__ import annotations

import socket
from datetime import datetime
from pathlib import Path

from . import discovery, packages
from .discovery import HOME, DiscoveredPath
from .manifest import Manifest, ManifestEntry, ManifestPackage, ManifestUnit
from .util import copy_path, dir_size, timestamp, unit_enabled

DEFAULT_BACKUP_ROOT = HOME / "Backups" / "caelback"


def _copy_group(entries: list[DiscoveredPath], snap_dir: Path) -> list[ManifestEntry]:
    out = []
    for entry in entries:
        dest = snap_dir / entry.label
        copy_path(entry.src, dest)
        out.append(ManifestEntry(label=entry.label, src=str(entry.src), size_bytes=dir_size(dest)))
    return out


def take_snapshot(backup_root: Path = DEFAULT_BACKUP_ROOT) -> Path:
    disc = discovery.discover()
    pkgs = packages.resolve_packages()

    snap_name = timestamp()
    snap_dir = backup_root / snap_name
    snap_dir.mkdir(parents=True, exist_ok=False)

    config_entries = _copy_group(disc.config_dirs, snap_dir)
    state_entries = _copy_group(disc.state_dirs, snap_dir)
    extra_entries = _copy_group(disc.extra_matches, snap_dir)

    pkg_entries: list[ManifestPackage] = []
    for pkg in pkgs:
        cached_rel = None
        if pkg.cached_file is not None:
            cache_dir = snap_dir / "cached-pkgs"
            cache_dir.mkdir(parents=True, exist_ok=True)
            dest = cache_dir / pkg.cached_file.name
            copy_path(pkg.cached_file, dest)
            cached_rel = str(dest.relative_to(snap_dir))
        pkg_entries.append(
            ManifestPackage(
                name=pkg.name,
                version=pkg.version,
                cached=cached_rel is not None,
                cached_pkg=cached_rel,
            )
        )

    unit_entries: list[ManifestUnit] = []
    if disc.systemd_units:
        units_dir = snap_dir / "systemd"
        units_dir.mkdir(parents=True, exist_ok=True)
        for name in disc.systemd_units:
            copy_path(discovery.SYSTEMD_USER_DIR / name, units_dir / name)
            unit_entries.append(ManifestUnit(name=name, enabled=unit_enabled(name)))

    if disc.sddm_sessions:
        sessions_dir = snap_dir / "sddm-sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        for name in disc.sddm_sessions:
            copy_path(discovery.SDDM_SESSIONS_DIR / name, sessions_dir / name)

    manifest = Manifest(
        name=snap_name,
        created_at=datetime.now().isoformat(timespec="seconds"),
        hostname=socket.gethostname(),
        config_dirs=config_entries,
        state_dirs=state_entries,
        extra_matches=extra_entries,
        systemd_units=unit_entries,
        sddm_sessions=disc.sddm_sessions,
        packages=pkg_entries,
    )
    manifest.write(snap_dir)

    return snap_dir
