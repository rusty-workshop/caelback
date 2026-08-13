"""Snapshot listing and retention (keep-last-N pruning)."""

from __future__ import annotations

import shutil
from pathlib import Path

from .snapshot import DEFAULT_BACKUP_ROOT

DEFAULT_KEEP = 5


def list_snapshots(backup_root: Path = DEFAULT_BACKUP_ROOT) -> list[Path]:
    if not backup_root.exists():
        return []
    return sorted(
        (p for p in backup_root.iterdir() if p.is_dir() and (p / "manifest.json").exists()),
        key=lambda p: p.name,
    )


def latest_snapshot(backup_root: Path = DEFAULT_BACKUP_ROOT) -> Path | None:
    snaps = list_snapshots(backup_root)
    return snaps[-1] if snaps else None


def resolve_snapshot(name: str | None, backup_root: Path = DEFAULT_BACKUP_ROOT) -> Path:
    if name is None:
        snap = latest_snapshot(backup_root)
        if snap is None:
            raise FileNotFoundError(f"No snapshots found under {backup_root}")
        return snap
    snap = backup_root / name
    if not (snap / "manifest.json").exists():
        raise FileNotFoundError(f"No snapshot named {name!r} under {backup_root}")
    return snap


def prune(backup_root: Path = DEFAULT_BACKUP_ROOT, keep: int = DEFAULT_KEEP) -> list[Path]:
    snaps = list_snapshots(backup_root)
    to_remove = snaps[:-keep] if keep > 0 else []
    for snap in to_remove:
        shutil.rmtree(snap)
    return to_remove
