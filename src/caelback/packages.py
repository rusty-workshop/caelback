"""Package discovery: installed versions + locating cached tarballs for offline restore."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .discovery import HOME, PACKAGE_NAME_PATTERNS

CACHE_SEARCH_ROOTS = [
    Path("/var/cache/pacman/pkg"),
    HOME / ".cache/yay",
    HOME / ".cache/paru/clone",
]


@dataclass
class PackageInfo:
    name: str
    version: str
    cached_file: Path | None = None


def installed_packages() -> list[PackageInfo]:
    result = subprocess.run(["pacman", "-Q"], check=True, text=True, capture_output=True)
    found = []
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        name, version = parts
        if any(term in name.lower() for term in PACKAGE_NAME_PATTERNS):
            found.append(PackageInfo(name=name, version=version))
    return found


def find_cached_tarball(name: str, version: str) -> Path | None:
    """Package filenames are <name>-<version>-<arch>.pkg.tar.<ext>; version already
    includes the pkgrel (e.g. "2.2.0-1"), so a glob on that prefix is exact enough."""
    pattern = f"{name}-{version}-*.pkg.tar.*"
    for root in CACHE_SEARCH_ROOTS:
        if not root.exists():
            continue
        matches = sorted(root.rglob(pattern))
        if matches:
            return matches[0]
    return None


def resolve_packages() -> list[PackageInfo]:
    pkgs = installed_packages()
    for pkg in pkgs:
        pkg.cached_file = find_cached_tarball(pkg.name, pkg.version)
    return pkgs


def installed_version(name: str) -> str | None:
    result = subprocess.run(["pacman", "-Q", name], text=True, capture_output=True)
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split(maxsplit=1)
    return parts[1] if len(parts) == 2 else None


def would_downgrade(installed: str, candidate_version: str) -> bool:
    """True if installing candidate_version over installed would be a downgrade."""
    result = subprocess.run(["vercmp", candidate_version, installed], text=True, capture_output=True)
    try:
        return int(result.stdout.strip()) < 0
    except ValueError:
        return False  # can't tell -- don't block on an unparseable result
