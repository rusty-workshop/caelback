"""One-click restore from a snapshot, driven entirely by its manifest.json."""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import discovery
from .manifest import Manifest
from .util import confirm, copy_path, eprint, move_aside, run


def print_plan(m: Manifest) -> None:
    print(f"Snapshot: {m.name}  (taken {m.created_at} on {m.hostname})")
    print()

    cached = [p for p in m.packages if p.cached]
    uncached = [p for p in m.packages if not p.cached]
    if cached:
        print(f"Packages to reinstall from cached tarballs ({len(cached)}):")
        for p in cached:
            print(f"  - {p.name} {p.version}")
    if uncached:
        print(f"Packages NOT cached — will be skipped, reinstall manually if needed ({len(uncached)}):")
        for p in uncached:
            print(f"  - {p.name} {p.version}")
    print()

    entries = m.all_path_entries()
    print(f"Paths to restore ({len(entries)}):")
    for e in entries:
        print(f"  - {e.src}")
    print()

    if m.systemd_units:
        print(f"systemd --user units to restore ({len(m.systemd_units)}):")
        for u in m.systemd_units:
            print(f"  - {u.name} ({'will enable --now' if u.enabled else 'copied only, not enabled'})")
        print()

    if m.sddm_sessions:
        print(f"sddm session entries to restore (needs sudo): {', '.join(m.sddm_sessions)}")
        print()

    print("Anything currently at a destination path is moved aside as <path>.pre-restore-<timestamp>, not deleted.")


def restore_snapshot(snap_dir: Path, *, yes: bool = False, dry_run: bool = False) -> None:
    m = Manifest.load(snap_dir)
    print_plan(m)

    if dry_run:
        print("\n(dry run — nothing was changed)")
        return

    if not yes and not confirm("\nProceed with restore?"):
        print("Aborted.")
        return

    _restore_packages(m, snap_dir)
    _restore_paths(m, snap_dir)
    _restore_systemd_units(m, snap_dir)
    _restore_sddm_sessions(m, snap_dir)

    print()
    print("Restore complete. Log out and select a Hyprland session at the sddm login screen.")
    print("Anything that existed at a destination before restore was preserved alongside it")
    print("with a .pre-restore-<timestamp> suffix, not deleted.")


def _restore_packages(m: Manifest, snap_dir: Path) -> None:
    cached = [p for p in m.packages if p.cached and p.cached_pkg]
    uncached = [p for p in m.packages if not p.cached]

    if cached:
        print(f"\n== Reinstalling {len(cached)} package(s) from cached tarballs ==")
        paths = [str(snap_dir / p.cached_pkg) for p in cached]
        try:
            run(["pacman", "-U", "--needed", *paths], sudo=True)
        except subprocess.CalledProcessError as exc:
            eprint(f"pacman -U failed: {exc}")

    if uncached:
        print("\nThe following packages were not cached at snapshot time and were skipped:")
        for p in uncached:
            print(f"  - {p.name} {p.version}  (try: yay -S {p.name})")


def _restore_paths(m: Manifest, snap_dir: Path) -> None:
    entries = m.all_path_entries()
    print(f"\n== Restoring {len(entries)} path(s) ==")
    for e in entries:
        dest = Path(e.src)
        src_in_snapshot = snap_dir / e.label
        if not src_in_snapshot.exists():
            eprint(f"  ! missing in snapshot, skipping: {src_in_snapshot}")
            continue
        backup = move_aside(dest)
        if backup is not None:
            print(f"  - {dest}  (existing moved to {backup.name})")
        else:
            print(f"  - {dest}")
        copy_path(src_in_snapshot, dest)


def _restore_systemd_units(m: Manifest, snap_dir: Path) -> None:
    if not m.systemd_units:
        return
    print(f"\n== Restoring {len(m.systemd_units)} systemd --user unit(s) ==")
    dest_dir = discovery.SYSTEMD_USER_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    for u in m.systemd_units:
        copy_path(snap_dir / "systemd" / u.name, dest_dir / u.name)
    run(["systemctl", "--user", "daemon-reload"])
    for u in m.systemd_units:
        if u.enabled:
            try:
                run(["systemctl", "--user", "enable", "--now", u.name])
            except subprocess.CalledProcessError as exc:
                eprint(f"Could not enable {u.name}: {exc}")


def _restore_sddm_sessions(m: Manifest, snap_dir: Path) -> None:
    if not m.sddm_sessions:
        return
    print(f"\n== Restoring {len(m.sddm_sessions)} sddm session entr{'y' if len(m.sddm_sessions) == 1 else 'ies'} (sudo) ==")
    for name in m.sddm_sessions:
        try:
            run(["cp", str(snap_dir / "sddm-sessions" / name), f"{discovery.SDDM_SESSIONS_DIR}/{name}"], sudo=True)
        except subprocess.CalledProcessError as exc:
            eprint(f"Could not restore sddm session {name}: {exc}")
