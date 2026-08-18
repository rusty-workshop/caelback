"""Builds an in-memory Manifest of the *live* system, without writing
anything to disk -- for comparing what's actually there right now against
a real snapshot, so drift shows up before it becomes a restore surprise.

Deliberately mirrors snapshot.py's take_snapshot() structure (same
discovery, same package resolution, same manifest shape) but skips every
copy_path() call -- sizes are measured directly on the live paths instead
of on copies, and package/unit/session presence is read live rather than
captured. Nothing here is destructive or even side-effecting beyond the
read-only subprocess calls discovery/packages already make.
"""

from __future__ import annotations

import socket
from datetime import datetime

from . import discovery, packages
from .discovery import DiscoveredPath
from .manifest import Manifest, ManifestEntry, ManifestPackage, ManifestUnit
from .util import dir_size, unit_enabled


def _live_group(entries: list[DiscoveredPath]) -> list[ManifestEntry]:
    return [ManifestEntry(label=e.label, src=str(e.src), size_bytes=dir_size(e.src)) for e in entries]


def scan_live() -> Manifest:
    disc = discovery.discover()
    pkgs = packages.resolve_packages()

    pkg_entries = [
        ManifestPackage(name=p.name, version=p.version, cached=p.cached_file is not None, cached_pkg=None)
        for p in pkgs
    ]
    unit_entries = [ManifestUnit(name=name, enabled=unit_enabled(name)) for name in disc.systemd_units]

    return Manifest(
        name="live",
        created_at=datetime.now().isoformat(timespec="seconds"),
        hostname=socket.gethostname(),
        config_dirs=_live_group(disc.config_dirs),
        state_dirs=_live_group(disc.state_dirs),
        extra_matches=_live_group(disc.extra_matches),
        systemd_units=unit_entries,
        sddm_sessions=disc.sddm_sessions,
        packages=pkg_entries,
    )
