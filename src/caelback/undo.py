"""Reverts the path changes made by the most recent `caelback restore`,
using the log restore.py writes to <backup_root>/last-restore.json. Scoped
to paths only (config/state) -- packages and sddm entries aren't tracked
for undo, since "revert a package install" isn't something a cached
tarball from the *old* state necessarily lets you do safely.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .restore import RESTORE_LOG_FILE
from .util import confirm, move_aside


def load_log(backup_root: Path) -> dict | None:
    log_path = backup_root / RESTORE_LOG_FILE
    if not log_path.exists():
        return None
    try:
        return json.loads(log_path.read_text())
    except json.JSONDecodeError:
        return None


def undo_last_restore(backup_root: Path, *, yes: bool = False) -> bool:
    data = load_log(backup_root)
    if data is None:
        print("No recorded restore to undo (or its log is unreadable).")
        return False

    paths = data.get("paths", [])
    print(f"Undoing the restore from {data.get('restored_from', '?')} (done {data.get('restored_at', '?')}):")
    for entry in paths:
        dest = entry["dest"]
        if entry["pre_restore_backup"]:
            print(f"  - {dest}  (will bring back its pre-restore content)")
        else:
            print(f"  - {dest}  (had nothing before the restore -- will just be removed)")
    print("This only reverts the config/state paths from that restore -- not packages or sddm entries.")

    if not yes and not confirm("\nProceed?"):
        print("Aborted.")
        return False

    for entry in paths:
        dest = Path(entry["dest"])
        pre = entry["pre_restore_backup"]
        if dest.exists() or dest.is_symlink():
            move_aside(dest)
        if pre and Path(pre).exists():
            shutil.move(pre, dest)

    (backup_root / RESTORE_LOG_FILE).unlink(missing_ok=True)
    print("Undo complete. What was just restored is preserved alongside as <path>.pre-restore-<timestamp>.")
    return True
