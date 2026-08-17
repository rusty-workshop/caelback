"""caelback preview: temporarily try another dotfiles repo on top of the
current Caelestia setup, guaranteed to revert to a known-good starred
snapshot as soon as this terminal exits (Ctrl-C, closing it, or normal
completion).

There is no universal format for dotfiles installers, so this doesn't try
to guarantee correctly applying *any* repo -- instead it recognizes the
major conventions in priority order (chezmoi's naming scheme, GNU Stow's
own config files, a Makefile with an install target, common installer
script names, or a plain top-level .config/ to mirror), always confirms
before running or copying anything, and falls back to showing the repo's
README/file listing so a human can decide when nothing is recognized.

Cleanup has two parts: restore_snapshot() reverts anything that overlaps
what caelback already tracks (config/state/packages/systemd/sddm) -- but a
newly-applied repo can also create paths caelback never tracked at all
(a brand-new app config directory, say), which restore_snapshot alone
can't know to remove. A before/after top-level snapshot of the same roots
discovery.py already scans catches those and moves them out of the way too
(not deleted -- consistent with everything else in this tool).

Note on guarantees: SIGINT/SIGTERM/SIGHUP (Ctrl-C, closing a terminal,
`kill`) are caught and trigger cleanup. SIGKILL (`kill -9`) cannot be
caught by any process, ever -- if that happens, the starred snapshot is
still there for a manual `caelback restore`, but nothing runs automatically.
Anything a package manager installs during an installer run also isn't
tracked or reverted by this -- that's a real limit, not something a
before/after directory listing can fix.
"""

from __future__ import annotations

import atexit
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import discovery, retention
from .restore import restore_snapshot
from .snapshot import DEFAULT_BACKUP_ROOT, take_snapshot
from .util import confirm, copy_path, eprint, move_aside

PREVIEW_CACHE_DIR = Path.home() / ".cache/caelback/preview"

# Plain executable scripts to look for, in rough likelihood order. Covers
# common ad-hoc installers plus a couple of dotfile-manager conventions
# (dotbot's "install", yadm's "bootstrap").
SCRIPT_CANDIDATES = [
    "install.sh", "Install.sh", "setup.sh", "Setup.sh", "bootstrap.sh",
    "bootstrap", "install", "dotfiles.sh", "deploy.sh", "run.sh",
]

CHEZMOI_PREFIXES = ("dot_", "private_dot_", "executable_dot_", "private_executable_dot_")


def _repo_dest(url: str) -> Path:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return PREVIEW_CACHE_DIR / f"{ts}-{name or 'repo'}"


# --- Detection: recognized conventions, most specific/reliable first -------


def _detect_chezmoi(repo_dir: Path) -> bool:
    markers = (".chezmoiroot", ".chezmoi.toml.tmpl", ".chezmoi.yaml.tmpl", ".chezmoi.json.tmpl")
    if any((repo_dir / m).exists() for m in markers):
        return True
    search_dirs = [repo_dir]
    home = repo_dir / "home"
    if home.is_dir():
        search_dirs.append(home)
    for d in search_dirs:
        for p in d.iterdir():
            if p.name.startswith(CHEZMOI_PREFIXES):
                return True
    return False


def _detect_stow(repo_dir: Path) -> bool:
    return (repo_dir / "Stowfile").exists() or (repo_dir / ".stowrc").exists()


def _detect_make_install(repo_dir: Path) -> Path | None:
    for name in ("Makefile", "makefile"):
        p = repo_dir / name
        if p.is_file():
            try:
                if re.search(r"(?m)^install\s*:", p.read_text(errors="replace")):
                    return p
            except OSError:
                pass
    return None


def find_installer(repo_dir: Path) -> Path | None:
    for name in SCRIPT_CANDIDATES:
        candidate = repo_dir / name
        if candidate.is_file():
            return candidate
    return None


def _find_mirror_root(repo_dir: Path) -> Path | None:
    candidate = repo_dir / ".config"
    return candidate if candidate.is_dir() else None


# --- Applying ----------------------------------------------------------------


def apply_repo(repo_dir: Path) -> bool:
    """Try the most specific/reliable recognized convention first. Always
    confirms before running or copying anything. Returns True if something
    was actually applied."""

    if _detect_chezmoi(repo_dir):
        print("\nThis looks like a chezmoi-managed repo (chezmoi naming convention detected).")
        if shutil.which("chezmoi") is None:
            print("chezmoi isn't installed -- install it (e.g. `yay -S chezmoi`) or apply this repo yourself.")
        elif confirm(f"Run `chezmoi init --apply {repo_dir}` now?"):
            print(f"\n== Running chezmoi init --apply {repo_dir} ==")
            subprocess.run(["chezmoi", "init", "--apply", str(repo_dir)])
            return True

    if _detect_stow(repo_dir):
        print("\nThis looks like a GNU Stow repo (Stowfile/.stowrc present).")
        if shutil.which("stow") is None:
            print("`stow` isn't installed -- install it (e.g. `sudo pacman -S stow`) or apply this repo yourself.")
        else:
            packages = sorted(p.name for p in repo_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
            print(f"Candidate packages (top-level directories): {', '.join(packages) or '(none found)'}")
            try:
                choice = input("Stow which package(s)? (comma-separated names, blank to skip): ").strip()
            except EOFError:
                choice = ""
            names = [n.strip() for n in choice.split(",") if n.strip()]
            if names:
                print(f"\n== Running stow -d {repo_dir} -t {Path.home()} {' '.join(names)} ==")
                subprocess.run(["stow", "-d", str(repo_dir), "-t", str(Path.home()), *names])
                return True

    make_target = _detect_make_install(repo_dir)
    if make_target is not None:
        print(f"\nFound a Makefile with an install target: {make_target}")
        if confirm("Run `make install` now?"):
            print("\n== Running make install ==")
            subprocess.run(["make", "install"], cwd=repo_dir)
            return True

    installer = find_installer(repo_dir)
    if installer is not None:
        print(f"\nFound a likely installer: {installer}")
        if confirm(f"Run {installer.name} now?"):
            print(f"\n== Running {installer} ==")
            try:
                installer.chmod(installer.stat().st_mode | 0o111)
            except OSError:
                pass
            subprocess.run([str(installer)], cwd=repo_dir)
            return True

    mirror_root = _find_mirror_root(repo_dir)
    if mirror_root is not None:
        print("\nNo recognized installer, but this repo has a .config/ directory at its root.")
        if confirm("Mirror its contents into ~/.config now? (existing content is moved aside, not deleted)"):
            for entry in mirror_root.iterdir():
                dest = Path.home() / ".config" / entry.name
                backup = move_aside(dest)
                if backup is not None:
                    print(f"  - ~/.config/{entry.name}  (existing moved to {backup.name})")
                else:
                    print(f"  - ~/.config/{entry.name}")
                copy_path(entry, dest)
            return True

    print("\nNo recognized installer convention found.")
    readme = next(
        (repo_dir / n for n in ("README.md", "README", "readme.md", "Readme.md") if (repo_dir / n).is_file()), None
    )
    if readme is not None:
        try:
            lines = readme.read_text(errors="replace").splitlines()
        except OSError:
            lines = []
        print(f"--- {readme.name} (first 60 lines) ---")
        print("\n".join(lines[:60]))
        print("--- end excerpt ---")
    try:
        listing = ", ".join(sorted(p.name for p in repo_dir.iterdir()))
    except OSError:
        listing = "(couldn't list)"
    print(f"Top-level contents: {listing}")
    print(f"The repo is at {repo_dir} -- apply it yourself; the revert-on-exit still applies.")
    return False


# --- Safety net: catch new top-level paths restore_snapshot wouldn't know about


def _snapshot_top_level() -> dict[Path, set[str]]:
    snap: dict[Path, set[str]] = {}
    for root in discovery.FUZZY_SCAN_ROOTS:
        snap[root] = {p.name for p in root.iterdir()} if root.exists() else set()
    return snap


def _sweep_new_entries(before: dict[Path, set[str]], leftovers_dir: Path) -> list[str]:
    moved = []
    for root, before_names in before.items():
        if not root.exists():
            continue
        after_names = {p.name for p in root.iterdir()}
        for name in sorted(after_names - before_names):
            src = root / name
            dest = leftovers_dir / root.name / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(src), str(dest))
                moved.append(str(dest))
            except OSError as exc:
                eprint(f"Could not move leftover {src}: {exc}")
    return moved


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


def _cleanup(snap: Path, before: dict[Path, set[str]], leftovers_dir: Path) -> None:
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    print("\n\n== Ending preview: restoring Caelestia ==")
    restore_snapshot(snap, yes=True)
    moved = _sweep_new_entries(before, leftovers_dir)
    if moved:
        print(f"\nAlso found {len(moved)} new top-level item(s) under ~/.config, ~/.local/share,")
        print("or ~/.local/state that weren't there before the preview and aren't part of what")
        print("caelback tracks -- moved out of the way rather than left live:")
        for m in moved:
            print(f"  - {m}")


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
    print("⚠ This clones -- and may run an install script or dotfile-manager command")
    print(f"  from -- an ARBITRARY repository ({repo_url}). That can do anything a shell")
    print("  command can: install packages, modify files outside what caelback tracks, etc.")
    print(f"  When this terminal exits (Ctrl-C, closing it, or normal completion),")
    print(f"  caelback restores {snap.name} automatically and sweeps away any brand-new")
    print("  config paths the preview created -- but package installs and anything else")
    print("  outside caelback's tracked paths aren't covered. A hard `kill -9` on this")
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

    before = _snapshot_top_level()
    leftovers_dir = dest.parent / f"{dest.name}-leftovers"

    if not apply_repo(dest):
        print("\n(Nothing applied automatically. Preview is still armed -- if you apply")
        print("something manually now, it'll still be swept up and reverted on exit.)")

    def _handler(signum, frame):
        _cleanup(snap, before, leftovers_dir)
        sys.exit(1)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _handler)
    atexit.register(_cleanup, snap, before, leftovers_dir)

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
