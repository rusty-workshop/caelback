"""One-click restore from a snapshot, driven entirely by its manifest.json."""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import discovery
from .manifest import Manifest, ManifestPackage
from .util import confirm, copy_path, eprint, move_aside, run


def _installed_version(name: str) -> str | None:
    result = subprocess.run(["pacman", "-Q", name], text=True, capture_output=True)
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split(maxsplit=1)
    return parts[1] if len(parts) == 2 else None


def _would_downgrade(installed: str, snapshot_version: str) -> bool:
    """True if installing snapshot_version over installed would be a downgrade."""
    result = subprocess.run(["vercmp", snapshot_version, installed], text=True, capture_output=True)
    try:
        return int(result.stdout.strip()) < 0
    except ValueError:
        return False  # can't tell -- don't block on an unparseable result


def categorize_packages(
    m: Manifest,
) -> tuple[list[ManifestPackage], list[tuple[ManifestPackage, str]], list[ManifestPackage]]:
    """Split a manifest's packages into (to_install, skipped_would_downgrade, uncached).

    Shared by print_plan and _restore_packages so --dry-run's preview always
    matches what a real restore will actually do.
    """
    cached = [p for p in m.packages if p.cached and p.cached_pkg]
    uncached = [p for p in m.packages if not p.cached]

    to_install = []
    skipped_newer = []
    for p in cached:
        installed = _installed_version(p.name)
        if installed is not None and _would_downgrade(installed, p.version):
            skipped_newer.append((p, installed))
        else:
            to_install.append(p)
    return to_install, skipped_newer, uncached


def print_plan(m: Manifest) -> None:
    print(f"Snapshot: {m.name}  (taken {m.created_at} on {m.hostname})")
    print()

    to_install, skipped_newer, uncached = categorize_packages(m)
    if to_install:
        print(f"Packages to reinstall from cached tarballs ({len(to_install)}):")
        for p in to_install:
            print(f"  - {p.name} {p.version}")
    if skipped_newer:
        print(f"Packages skipped — currently installed is newer, won't downgrade ({len(skipped_newer)}):")
        for p, installed in skipped_newer:
            print(f"  - {p.name}: installed {installed}, snapshot has {p.version}")
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
    to_install, skipped_newer, uncached = categorize_packages(m)

    if to_install:
        print(f"\n== Reinstalling {len(to_install)} package(s) from cached tarballs ==")
        paths = [str(snap_dir / p.cached_pkg) for p in to_install]
        try:
            run(["pacman", "-U", "--needed", *paths], sudo=True)
        except subprocess.CalledProcessError as exc:
            eprint(f"pacman -U failed: {exc}")

    if skipped_newer:
        print("\nSkipped — currently installed version is newer than the snapshot's, not downgrading:")
        for p, installed in skipped_newer:
            print(f"  - {p.name}: installed {installed}, snapshot has {p.version}")

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
