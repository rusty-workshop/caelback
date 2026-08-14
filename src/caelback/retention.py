"""Snapshot listing, starring, and retention (keep-last-N pruning)."""

from __future__ import annotations

import shutil
from pathlib import Path

from .snapshot import DEFAULT_BACKUP_ROOT

DEFAULT_KEEP = 5
STARRED_FILE = ".starred"


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


def get_starred(backup_root: Path = DEFAULT_BACKUP_ROOT) -> str | None:
    f = backup_root / STARRED_FILE
    if not f.exists():
        return None
    name = f.read_text().strip()
    return name or None


def set_starred(backup_root: Path, name: str) -> None:
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / STARRED_FILE).write_text(name + "\n")


def clear_starred(backup_root: Path = DEFAULT_BACKUP_ROOT) -> None:
    f = backup_root / STARRED_FILE
    if f.exists():
        f.unlink()


def resolve_snapshot(name: str | None, backup_root: Path = DEFAULT_BACKUP_ROOT) -> Path:
    """Resolve a snapshot name to a path. With no name: prefer the starred
    snapshot if one is set and still exists, otherwise the most recent."""
    if name is None:
        starred = get_starred(backup_root)
        if starred is not None:
            snap = backup_root / starred
            if (snap / "manifest.json").exists():
                return snap
            # Starred snapshot no longer exists (e.g. manually deleted) -- fall through.
        snap = latest_snapshot(backup_root)
        if snap is None:
            raise FileNotFoundError(f"No snapshots found under {backup_root}")
        return snap
    snap = backup_root / name
    if not (snap / "manifest.json").exists():
        raise FileNotFoundError(f"No snapshot named {name!r} under {backup_root}")
    return snap


def prune(backup_root: Path = DEFAULT_BACKUP_ROOT, keep: int = DEFAULT_KEEP) -> list[Path]:
    """Keep the last N snapshots. The starred snapshot (if any) is always
    exempt, regardless of age -- that's the whole point of starring one."""
    snaps = list_snapshots(backup_root)
    starred = get_starred(backup_root)
    starred_path = (backup_root / starred) if starred else None

    prunable = [s for s in snaps if s != starred_path]
    to_remove = prunable[:-keep] if keep > 0 else prunable
    for snap in to_remove:
        shutil.rmtree(snap)
    return to_remove
