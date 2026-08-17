"""Export a snapshot to a portable .tar.gz, and import one back in.

Existing --backup-root already lets caelback point at somewhere like an
external drive, but that still ties a snapshot to wherever it was taken.
This is for moving one snapshot to another machine, or off-site, without
copying the whole backup root.
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
from pathlib import Path

from .manifest import Manifest


class InvalidSnapshotArchive(Exception):
    """Raised when a .tar.gz doesn't look like a snapshot caelback made."""


def export_snapshot(snap_dir: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as tar:
        tar.add(snap_dir, arcname=snap_dir.name)
    return output


def import_snapshot(archive: Path, backup_root: Path, *, name: str | None = None) -> Path:
    """Extracts archive into backup_root as a new snapshot, returns its path.

    Raises InvalidSnapshotArchive if the archive doesn't contain exactly one
    top-level directory with a manifest.json, or FileExistsError if the
    target name is already taken (pass `name` to import under a different one).
    """
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        try:
            with tarfile.open(archive, "r:*") as tar:
                # "data" (the strictest built-in filter) rejects any symlink whose
                # target is an absolute path -- but caelback's own snapshots legitimately
                # contain those (e.g. a wallpaper "current" symlink pointing at the live
                # file's real location), so extraction would fail on totally normal
                # snapshots. "tar" still blocks the actual traversal risk (member names
                # with ".." or an absolute path can't write outside the destination) without
                # policing symlink targets -- same trust boundary as `caelback preview`:
                # only import archives you made or trust.
                tar.extractall(tmp, filter="tar")
        except tarfile.TarError as exc:
            raise InvalidSnapshotArchive(f"{archive} isn't a readable tar archive: {exc}") from exc

        entries = [p for p in tmp.iterdir() if p.is_dir()]
        if len(entries) != 1 or not (entries[0] / "manifest.json").exists():
            raise InvalidSnapshotArchive(
                f"{archive} doesn't look like a caelback snapshot -- expected a single "
                "top-level directory containing manifest.json."
            )
        extracted = entries[0]
        m = Manifest.load(extracted)  # raises on corrupt manifest, propagates as-is

        dest_name = name or m.name
        dest = backup_root / dest_name
        if dest.exists():
            raise FileExistsError(
                f"{dest_name!r} already exists under {backup_root} -- pass a different --name"
            )

        backup_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(extracted), str(dest))
        return dest
