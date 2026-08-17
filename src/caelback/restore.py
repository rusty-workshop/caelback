"""One-click restore from a snapshot, driven entirely by its manifest.json."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from . import discovery, layers, packages, verify
from .manifest import Manifest, ManifestPackage
from .notify import notify
from .util import confirm, copy_path, eprint, move_aside, run

RESTORE_LOG_FILE = "last-restore.json"


class SnapshotBroken(Exception):
    """Raised when a snapshot can't be safely restored from -- corrupted
    manifest, or content missing that the manifest claims should be there."""


def load_manifest_safe(snap_dir: Path) -> Manifest:
    try:
        return Manifest.load(snap_dir)
    except (json.JSONDecodeError, FileNotFoundError, KeyError, TypeError) as exc:
        raise SnapshotBroken(f"{snap_dir.name}'s manifest.json is missing or corrupted: {exc}") from exc


def preflight_issues(m: Manifest, snap_dir: Path) -> list[str]:
    """Sanity-check the snapshot's own content against what its manifest
    claims, before touching anything on the live system."""
    issues = []
    for e in m.all_path_entries():
        if not (snap_dir / e.label).exists():
            issues.append(f"missing content for {e.src} (expected at {e.label})")
    for pkg in m.packages:
        if pkg.cached:
            p = snap_dir / pkg.cached_pkg
            if not p.exists() or p.stat().st_size == 0:
                issues.append(f"cached package tarball missing/empty: {pkg.name} {pkg.version}")
    for u in m.systemd_units:
        if not (snap_dir / "systemd" / u.name).exists():
            issues.append(f"missing systemd unit file: {u.name}")
    for s in m.sddm_sessions:
        if not (snap_dir / "sddm-sessions" / s).exists():
            issues.append(f"missing sddm session file: {s}")
    return issues


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
        installed = packages.installed_version(p.name)
        if installed is not None and packages.would_downgrade(installed, p.version):
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

    unexpected = layers.find_unexpected_layer_owners()
    if unexpected:
        print(f"Leftover processes currently drawing a Hyprland layer, not part of Caelestia ({len(unexpected)}):")
        for o in unexpected:
            print(f"  - {layers.format_owner(o)}")
        print("  These will be offered for killing after the restore, so they stop drawing over Caelestia.")
        print()

    print("Anything currently at a destination path is moved aside as <path>.pre-restore-<timestamp>, not deleted.")


def restore_snapshot(snap_dir: Path, *, yes: bool = False, dry_run: bool = False, force: bool = False) -> bool:
    """Returns True if the restore (or dry run) completed without hard failure."""
    try:
        m = load_manifest_safe(snap_dir)
    except SnapshotBroken as exc:
        eprint(f"Refusing to restore: {exc}")
        eprint("Try a different snapshot (`caelback list`), or `caelback doctor <name>` for details.")
        return False

    issues = preflight_issues(m, snap_dir)
    if issues:
        eprint(f"This snapshot has {len(issues)} integrity problem(s):")
        for issue in issues:
            eprint(f"  - {issue}")
        if not force:
            eprint("Refusing to restore from a snapshot that fails its own integrity check.")
            eprint("Pass --force to restore anyway (missing items are skipped either way), or pick another snapshot.")
            return False
        eprint("--force given: proceeding despite the above.")

    print_plan(m)

    if dry_run:
        print("\n(dry run — nothing was changed)")
        return True

    if not yes and not confirm("\nProceed with restore?"):
        print("Aborted.")
        return False

    _restore_packages(m, snap_dir)
    path_records = _restore_paths(m, snap_dir)
    _restore_systemd_units(m, snap_dir)
    _restore_sddm_sessions(m, snap_dir)
    _reclaim_layers(yes=yes)
    _write_restore_log(snap_dir.parent, m.name, path_records)
    _reload_hyprland()

    print()
    print("Restore complete. For a fully clean state (nothing left running from wherever you")
    print("hopped to), log out and back in through a Hyprland session at the sddm login screen")
    print("rather than staying in the current one.")
    print("Anything that existed at a destination before restore was preserved alongside it")
    print("with a .pre-restore-<timestamp> suffix, not deleted. `caelback undo` reverts the")
    print("path changes from this restore if something's wrong.")

    report = verify.verify_restore(m)
    print(verify.render_report(report))
    if not report.ok:
        print("Some checks failed above — the restore ran, but the live system doesn't fully")
        print("match the snapshot yet. This can be normal right after a restore (e.g. a service")
        print("that needs the reload/relogin above); recheck with `caelback doctor` if it persists.")
        failed = ", ".join(c.name for c in report.failures[:5])
        notify(
            "caelback restore: some checks failed",
            f"{len(report.failures)} check(s) failed after restoring {m.name}: {failed}",
            urgency="critical",
        )

    return report.ok


def _reload_hyprland() -> None:
    result = subprocess.run(["hyprctl", "reload"], capture_output=True, text=True)
    if result.returncode != 0:
        eprint("(hyprctl reload failed or Hyprland isn't the active session — skipping, harmless if so)")


def _write_restore_log(backup_root: Path, snapshot_name: str, path_records: list[dict]) -> None:
    data = {
        "restored_from": snapshot_name,
        "restored_at": datetime.now().isoformat(timespec="seconds"),
        "paths": path_records,
    }
    (backup_root / RESTORE_LOG_FILE).write_text(json.dumps(data, indent=2) + "\n")


def _reclaim_layers(*, yes: bool) -> None:
    unexpected = layers.find_unexpected_layer_owners()
    if not unexpected:
        return

    print(f"\n== {len(unexpected)} leftover process(es) still drawing a Hyprland layer ==")
    for o in unexpected:
        print(f"  - {layers.format_owner(o)}")

    if not yes and not confirm("Kill these? (they're likely autostart leftovers from whatever was hopped to)"):
        print("Left running. Kill manually, or a full log out/in will clear them too.")
        return

    layers.kill_owners(unexpected)
    print(f"Killed {len(unexpected)} process(es).")


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


def _restore_paths(m: Manifest, snap_dir: Path) -> list[dict]:
    entries = m.all_path_entries()
    print(f"\n== Restoring {len(entries)} path(s) ==")
    records = []
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
        records.append({"dest": str(dest), "pre_restore_backup": str(backup) if backup else None})
    return records


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
