"""Small shared helpers: shell-out, sizing, confirmation, safe copy/move."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return f"{size:.1f}TiB"


def dir_size(path: Path) -> int:
    if path.is_file() or path.is_symlink():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() or p.is_symlink():
                total += p.lstat().st_size
        except OSError:
            continue
    return total


def confirm(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        reply = input(prompt + suffix).strip().lower()
    except EOFError:
        return default
    if not reply:
        return default
    return reply in ("y", "yes")


def run(cmd: list[str], *, sudo: bool = False, check: bool = True, capture: bool = False):
    full_cmd = (["sudo"] + cmd) if sudo else cmd
    return subprocess.run(
        full_cmd,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def copy_path(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir() and not src.is_symlink():
        shutil.copytree(src, dest, symlinks=True)
    else:
        shutil.copy2(src, dest, follow_symlinks=False)


def move_aside(path: Path) -> Path | None:
    """If path exists, rename it to path.pre-restore-<timestamp> and return the new path."""
    if not path.exists() and not path.is_symlink():
        return None
    backup = path.with_name(f"{path.name}.pre-restore-{timestamp()}")
    shutil.move(str(path), str(backup))
    return backup


def eprint(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)
