"""Package discovery: installed versions + locating cached tarballs for offline restore."""

from __future__ import annotations

import fnmatch
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


def find_cached_tarball(
    name: str, version: str, *, _full_scan_cache: dict[Path, list[Path]] | None = None
) -> Path | None:
    """Package filenames are <name>-<version>-<arch>.pkg.tar.<ext>; version already
    includes the pkgrel (e.g. "2.2.0-1"), so a glob on that prefix is exact enough.

    yay/paru lay their cache out as <root>/<pkgname>/... (a git clone per AUR
    package) -- scoping the search to just that subdirectory when it exists
    avoids walking every *other* package's cache too. On this machine
    ~/.cache/yay alone has ~590k entries across ~90 packages; scoped to one
    package's own subdirectory that drops to under 1000.

    Split packages (multiple pkgnames built from one PKGBUILD, e.g. a "-debug"
    package) share their base package's subdirectory instead of having their
    own, so their exact-name directory doesn't exist -- same for a package
    that was never cached at all. Both cases fall back to a full scan of the
    root, which on a large AUR-helper cache is exactly the slow walk this
    function exists to avoid; _full_scan_cache lets resolve_packages() run
    that fallback at most once per root and reuse it, instead of once per
    package that needs it (this machine currently has two: one genuinely
    uncached package, one split package -- without sharing the cache,
    `caelback status` still took ~7s despite the exact-dir fast path above).
    """
    if _full_scan_cache is None:
        _full_scan_cache = {}
    pattern = f"{name}-{version}-*.pkg.tar.*"
    for root in CACHE_SEARCH_ROOTS:
        if not root.exists():
            continue
        exact_dir = root / name
        if exact_dir.is_dir():
            matches = sorted(exact_dir.rglob(pattern))
            if matches:
                return matches[0]
            continue
        if root not in _full_scan_cache:
            _full_scan_cache[root] = sorted(root.rglob("*.pkg.tar.*"))
        matches = sorted(p for p in _full_scan_cache[root] if fnmatch.fnmatch(p.name, pattern))
        if matches:
            return matches[0]
    return None


def resolve_packages() -> list[PackageInfo]:
    pkgs = installed_packages()
    full_scan_cache: dict[Path, list[Path]] = {}
    for pkg in pkgs:
        pkg.cached_file = find_cached_tarball(pkg.name, pkg.version, _full_scan_cache=full_scan_cache)
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
