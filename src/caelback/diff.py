"""Compares two snapshot manifests and summarizes what changed.

Surfaces a snapshot taken mid-dotfile-hop (or otherwise unexpected) loudly
at the moment it's taken, instead of it silently becoming "latest" and
poisoning a restore weeks later.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .manifest import Manifest

SIZE_CHANGE_THRESHOLD = 0.15  # 15%


@dataclass
class ManifestDiff:
    added_paths: list[str] = field(default_factory=list)
    removed_paths: list[str] = field(default_factory=list)
    resized_paths: list[tuple[str, int, int]] = field(default_factory=list)  # label, old, new
    package_changes: list[tuple[str, str, str]] = field(default_factory=list)  # name, old, new
    added_packages: list[str] = field(default_factory=list)
    removed_packages: list[str] = field(default_factory=list)
    added_units: list[str] = field(default_factory=list)
    removed_units: list[str] = field(default_factory=list)
    added_sessions: list[str] = field(default_factory=list)
    removed_sessions: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return self.total_changes() == 0

    def total_changes(self) -> int:
        return (
            len(self.added_paths)
            + len(self.removed_paths)
            + len(self.resized_paths)
            + len(self.package_changes)
            + len(self.added_packages)
            + len(self.removed_packages)
            + len(self.added_units)
            + len(self.removed_units)
            + len(self.added_sessions)
            + len(self.removed_sessions)
        )


def diff_manifests(old: Manifest, new: Manifest) -> ManifestDiff:
    old_paths = {e.label: e.size_bytes for e in old.all_path_entries()}
    new_paths = {e.label: e.size_bytes for e in new.all_path_entries()}

    added_paths = sorted(set(new_paths) - set(old_paths))
    removed_paths = sorted(set(old_paths) - set(new_paths))
    resized_paths = []
    for label in sorted(set(old_paths) & set(new_paths)):
        old_size, new_size = old_paths[label], new_paths[label]
        if old_size == 0:
            continue
        if abs(new_size - old_size) / old_size >= SIZE_CHANGE_THRESHOLD:
            resized_paths.append((label, old_size, new_size))

    old_pkgs = {p.name: p.version for p in old.packages}
    new_pkgs = {p.name: p.version for p in new.packages}
    added_packages = sorted(set(new_pkgs) - set(old_pkgs))
    removed_packages = sorted(set(old_pkgs) - set(new_pkgs))
    package_changes = [
        (name, old_pkgs[name], new_pkgs[name])
        for name in sorted(set(old_pkgs) & set(new_pkgs))
        if old_pkgs[name] != new_pkgs[name]
    ]

    old_units = {u.name for u in old.systemd_units}
    new_units = {u.name for u in new.systemd_units}
    old_sessions = set(old.sddm_sessions)
    new_sessions = set(new.sddm_sessions)

    return ManifestDiff(
        added_paths=added_paths,
        removed_paths=removed_paths,
        resized_paths=resized_paths,
        package_changes=package_changes,
        added_packages=added_packages,
        removed_packages=removed_packages,
        added_units=sorted(new_units - old_units),
        removed_units=sorted(old_units - new_units),
        added_sessions=sorted(new_sessions - old_sessions),
        removed_sessions=sorted(old_sessions - new_sessions),
    )


def _truncated(items: list[str], limit: int = 8) -> str:
    shown = ", ".join(items[:limit])
    return shown + (" ..." if len(items) > limit else "")


def render_diff(diff: ManifestDiff) -> str:
    lines = []
    if diff.added_paths:
        lines.append(f"  + {len(diff.added_paths)} new path(s): {_truncated(diff.added_paths)}")
    if diff.removed_paths:
        lines.append(f"  - {len(diff.removed_paths)} path(s) gone: {_truncated(diff.removed_paths)}")
    for label, old_size, new_size in diff.resized_paths:
        pct = (new_size - old_size) / old_size * 100
        lines.append(f"  ~ {label}: {old_size:,}B -> {new_size:,}B ({pct:+.0f}%)")
    for name, old_v, new_v in diff.package_changes:
        lines.append(f"  ~ package {name}: {old_v} -> {new_v}")
    if diff.added_packages:
        lines.append(f"  + new package(s): {_truncated(diff.added_packages)}")
    if diff.removed_packages:
        lines.append(f"  - package(s) gone: {_truncated(diff.removed_packages)}")
    if diff.added_units:
        lines.append(f"  + new systemd unit(s): {_truncated(diff.added_units)}")
    if diff.removed_units:
        lines.append(f"  - systemd unit(s) gone: {_truncated(diff.removed_units)}")
    if diff.added_sessions:
        lines.append(f"  + new sddm session(s): {_truncated(diff.added_sessions)}")
    if diff.removed_sessions:
        lines.append(f"  - sddm session(s) gone: {_truncated(diff.removed_sessions)}")
    return "\n".join(lines)
