"""caelback preview: temporarily try another dotfiles repo on top of the
current Caelestia setup, guaranteed to revert to a known-good starred
snapshot as soon as this terminal exits (Ctrl-C, closing it, or normal
completion) -- reuses the already-hardened restore_snapshot() as the
revert mechanism, so cleanup gets pre-flight checks, downgrade-safe
packages, and leftover-process reclaim for free.

Deliberately does NOT try to fully automate "installing" an arbitrary
repo -- there's no universal format for dotfiles installers across
projects. It looks for a small set of common entrypoint scripts and
always asks before running one; if the user runs an installer themselves
in another terminal instead, the armed revert-on-exit still applies for
the lifetime of this process.

Note on guarantees: SIGINT/SIGTERM/SIGHUP (Ctrl-C, closing a terminal,
`kill`) are caught and trigger cleanup. SIGKILL (`kill -9`) cannot be
caught by any process, ever -- if that happens, the starred snapshot is
still there for a manual `caelback restore`, but nothing runs automatically.
"""

from __future__ import annotations

import atexit
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import retention
from .restore import restore_snapshot
from .snapshot import DEFAULT_BACKUP_ROOT, take_snapshot
from .util import confirm, eprint

PREVIEW_CACHE_DIR = Path.home() / ".cache/caelback/preview"
INSTALLER_CANDIDATES = ["install.sh", "setup.sh", "bootstrap.sh", "Install.sh", "install"]


def _repo_dest(url: str) -> Path:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return PREVIEW_CACHE_DIR / f"{ts}-{name or 'repo'}"


def find_installer(repo_dir: Path) -> Path | None:
    for name in INSTALLER_CANDIDATES:
        candidate = repo_dir / name
        if candidate.is_file():
            return candidate
    return None


def _ensure_starred(backup_root: Path, *, yes: bool) -> Path | None:
    starred = retention.get_starred(backup_root)
    if starred is not None:
        snap = backup_root / starred
        if (snap / "manifest.json").exists():
            return snap

    print(
        "No starred snapshot to fall back to -- preview needs a known-good "
        "state it can guarantee returning to."
    )
    if not yes and not confirm("Take one now and star it?", default=True):
        return None
    print("Scanning system and taking a safety snapshot...")
    snap = take_snapshot(backup_root)
    retention.set_starred(backup_root, snap.name)
    print(f"★ Starred {snap.name} as the state preview will always return to.")
    return snap


_cleanup_done = False


def _cleanup(snap: Path) -> None:
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    print("\n\n== Ending preview: restoring Caelestia ==")
    restore_snapshot(snap, yes=True)


def run_preview(repo_url: str | None, *, backup_root: Path = DEFAULT_BACKUP_ROOT, yes: bool = False) -> int:
    if not repo_url:
        try:
            repo_url = input("GitHub repo URL to preview: ").strip()
        except EOFError:
            repo_url = ""
    if not repo_url:
        eprint("No repo URL given.")
        return 1

    snap = _ensure_starred(backup_root, yes=yes)
    if snap is None:
        print("Aborted.")
        return 1

    print()
    print("⚠ This clones -- and may run an install script from -- an ARBITRARY")
    print(f"  repository ({repo_url}). That script can do anything a shell command")
    print("  can: install packages, modify files outside what caelback tracks, etc.")
    print(f"  When this terminal exits (Ctrl-C, closing it, or normal completion),")
    print(f"  caelback restores {snap.name} automatically -- but that only covers")
    print("  what caelback tracks (config/state/packages/systemd/sddm), not")
    print("  everything an untrusted script might do. A hard `kill -9` on this")
    print("  process can't be caught by anything and skips the auto-revert too.")
    print("  Only preview repos you trust.")
    if not confirm("\nContinue?"):
        print("Aborted.")
        return 1

    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = _repo_dest(repo_url)
    print(f"\nCloning {repo_url} into {dest} ...")
    try:
        subprocess.run(["git", "clone", "--depth", "1", repo_url, str(dest)], check=True)
    except subprocess.CalledProcessError as exc:
        eprint(f"git clone failed: {exc}")
        return 1
    except FileNotFoundError:
        eprint("git not found on PATH.")
        return 1

    installer = find_installer(dest)
    if installer is not None:
        print(f"\nFound a likely installer: {installer}")
        if confirm(f"Run {installer.name} now?"):
            print(f"\n== Running {installer} ==")
            subprocess.run(["bash", str(installer)], cwd=dest)
        else:
            print(f"Skipped. Repo is at {dest} if you want to run something yourself.")
    else:
        print(f"\nNo common installer script found in the repo root. It's at {dest} --")
        print("run whatever it needs yourself; the revert-on-exit below still applies")
        print("for as long as this terminal stays open.")

    def _handler(signum, frame):
        _cleanup(snap)
        sys.exit(1)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _handler)
    atexit.register(_cleanup, snap)

    print()
    print(f"Preview active (safety net: {snap.name}).")
    print("Press Ctrl-C, or close this terminal, to end the preview and restore Caelestia.")
    try:
        while True:
            signal.pause()
    except AttributeError:
        # signal.pause() isn't available on every platform; fall back to a sleep loop
        # (still interruptible by SIGINT/SIGTERM/SIGHUP via the handlers above).
        while True:
            time.sleep(3600)
    return 0
