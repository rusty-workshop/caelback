"""caelback CLI: snapshot, list, show, restore, prune, doctor, timer install."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import discovery, packages, retention
from .manifest import Manifest
from .restore import restore_snapshot
from .snapshot import DEFAULT_BACKUP_ROOT, take_snapshot
from .util import confirm, eprint, human_size, run

TIMER_SERVICE_NAME = "caelback-snapshot.service"
TIMER_NAME = "caelback-snapshot.timer"


def cmd_snapshot(args: argparse.Namespace) -> int:
    if not args.force and not discovery.is_caelestia_present():
        print(
            "Caelestia doesn't appear to be installed on this machine (no "
            "~/.config/caelestia and no installed package matching \"caelestia\") -- "
            "skipping. This is deliberate: taking (and auto-pruning) snapshots after "
            "Caelestia is gone would eventually push out the last real snapshot you'd "
            "want to restore from. Pass --force to snapshot anyway."
        )
        return 0

    backup_root = Path(args.backup_root)
    print(f"Scanning system and taking snapshot into {backup_root} ...")
    snap_dir = take_snapshot(backup_root)
    m = Manifest.load(snap_dir)
    print(f"Snapshot {m.name} complete ({human_size(m.total_size_bytes())}, {len(m.packages)} package(s)).")
    print(f"  {snap_dir}")
    if args.keep > 0:
        removed = retention.prune(backup_root, keep=args.keep)
        if removed:
            print(f"Pruned {len(removed)} older snapshot(s): {', '.join(p.name for p in removed)}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    snaps = retention.list_snapshots(backup_root)
    if not snaps:
        print(f"No snapshots found under {backup_root}")
        return 0
    for snap in snaps:
        m = Manifest.load(snap)
        print(f"{m.name}  {human_size(m.total_size_bytes()):>10}  {len(m.packages)} pkgs  {snap}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    try:
        snap = retention.resolve_snapshot(args.name, backup_root)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    print((snap / "MANIFEST.md").read_text())
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    try:
        snap = retention.resolve_snapshot(args.name, backup_root)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    restore_snapshot(snap, yes=args.yes, dry_run=args.dry_run)
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    removed = retention.prune(backup_root, keep=args.keep)
    if removed:
        print(f"Removed {len(removed)} snapshot(s): {', '.join(p.name for p in removed)}")
    else:
        print("Nothing to prune.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    try:
        snap = retention.resolve_snapshot(args.name, backup_root)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    m = Manifest.load(snap)
    ok = True

    for e in m.all_path_entries():
        if not (snap / e.label).exists():
            print(f"MISSING: {e.label} (expected content for {e.src})")
            ok = False

    for pkg in m.packages:
        if pkg.cached:
            p = snap / pkg.cached_pkg
            if not p.exists() or p.stat().st_size == 0:
                print(f"MISSING/EMPTY cached package: {pkg.name} {pkg.version}")
                ok = False

    for u in m.systemd_units:
        if not (snap / "systemd" / u.name).exists():
            print(f"MISSING systemd unit: {u.name}")
            ok = False

    for s in m.sddm_sessions:
        if not (snap / "sddm-sessions" / s).exists():
            print(f"MISSING sddm session: {s}")
            ok = False

    if ok:
        print(f"{snap.name}: OK — all {len(m.all_path_entries())} path(s), {len(m.packages)} package(s) present.")
    return 0 if ok else 1


def cmd_cache_missing(args: argparse.Namespace) -> int:
    missing = [p for p in packages.resolve_packages() if p.cached_file is None]
    if not missing:
        print("Every caelestia/quickshell package already has a cached tarball.")
        return 0

    print(f"{len(missing)} package(s) have no cached tarball on disk — restore would skip them:")
    for p in missing:
        print(f"  - {p.name} {p.version}")

    if not args.yes and not confirm(
        "\nFetch/rebuild them now via `yay -Sw` (no install; may prompt for your sudo "
        "password if build deps are missing)?"
    ):
        print("\nSkipped. Run manually any time:")
        print("  yay -Sw " + " ".join(p.name for p in missing))
        return 0

    ok = True
    for p in missing:
        print(f"\n== yay -Sw {p.name} ==")
        result = subprocess.run(["yay", "-Sw", p.name])
        if result.returncode != 0:
            eprint(f"Failed to cache {p.name} (exit {result.returncode})")
            ok = False

    print("\nRun `caelback snapshot` again to capture the newly cached tarball(s).")
    return 0 if ok else 1


def _caelback_bin() -> Path:
    # LiveWall's installer learned this the hard way: shutil.which() can resolve to a
    # project-local .venv/bin when invoked via `uv run` from inside a repo checkout.
    # `uv tool install --editable` always symlinks the real entrypoint to this fixed path,
    # which is what a standalone systemd unit needs.
    return Path.home() / ".local/bin/caelback"


def cmd_install_timer(args: argparse.Namespace) -> int:
    bin_path = _caelback_bin()
    if not bin_path.exists():
        eprint(f"{bin_path} not found — install with `uv tool install --editable .` first.")
        return 1

    backup_root = Path(args.backup_root)
    exec_start = f"{bin_path} snapshot"
    if backup_root != DEFAULT_BACKUP_ROOT:
        exec_start += f" --backup-root {backup_root}"

    unit_dir = Path.home() / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)

    (unit_dir / TIMER_SERVICE_NAME).write_text(
        "[Unit]\n"
        "Description=caelback snapshot (Caelestia backup)\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={exec_start}\n"
    )
    (unit_dir / TIMER_NAME).write_text(
        "[Unit]\n"
        f"Description=Run caelback snapshot every {args.interval_days} day(s)\n"
        "\n"
        "[Timer]\n"
        "OnBootSec=10min\n"
        f"OnUnitActiveSec={args.interval_days}d\n"
        "Persistent=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )

    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "enable", "--now", TIMER_NAME])

    print(f"Installed and enabled {TIMER_NAME} — snapshots every {args.interval_days} day(s) from now on.")
    print("Persistent=true: if the machine is off when one is due, it runs shortly after the next boot instead of being skipped.")
    result = subprocess.run(
        ["systemctl", "--user", "list-timers", TIMER_NAME, "--no-pager"], text=True, capture_output=True
    )
    print(result.stdout)
    return 0


def cmd_uninstall_timer(args: argparse.Namespace) -> int:
    subprocess.run(["systemctl", "--user", "disable", "--now", TIMER_NAME], capture_output=True)
    unit_dir = Path.home() / ".config/systemd/user"
    for name in (TIMER_SERVICE_NAME, TIMER_NAME):
        p = unit_dir / name
        if p.exists():
            p.unlink()
    run(["systemctl", "--user", "daemon-reload"])
    print(f"Removed {TIMER_NAME} and {TIMER_SERVICE_NAME}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    # --backup-root lives only on the subparsers (via this parent), not on the top-level
    # parser too -- argparse subparsers write into the same namespace as the top-level
    # parser, so defining the same dest in both places lets the subparser's default
    # silently clobber a value the top-level parser already parsed from argv.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--backup-root",
        default=str(DEFAULT_BACKUP_ROOT),
        help=f"Where snapshots live (default: {DEFAULT_BACKUP_ROOT})",
    )

    parser = argparse.ArgumentParser(
        prog="caelback",
        description="Backup and one-click restore for a Caelestia setup, so you can dotfile-hop and come back.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_snap = sub.add_parser("snapshot", parents=[common], help="Take a new snapshot of everything Caelestia-related")
    p_snap.add_argument(
        "--keep",
        type=int,
        default=retention.DEFAULT_KEEP,
        help=f"Keep only the last N snapshots after this one (default: {retention.DEFAULT_KEEP}, 0 disables pruning)",
    )
    p_snap.add_argument(
        "--force",
        action="store_true",
        help="Take a snapshot even if Caelestia doesn't appear to be installed",
    )
    p_snap.set_defaults(func=cmd_snapshot)

    p_list = sub.add_parser("list", parents=[common], help="List existing snapshots")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", parents=[common], help="Print a snapshot's manifest")
    p_show.add_argument("name", nargs="?", default=None, help="Snapshot name (default: latest)")
    p_show.set_defaults(func=cmd_show)

    p_restore = sub.add_parser("restore", parents=[common], help="Restore a snapshot (one-click revert to Caelestia)")
    p_restore.add_argument("name", nargs="?", default=None, help="Snapshot name (default: latest)")
    p_restore.add_argument("--yes", "-y", action="store_true", help="Don't ask for confirmation")
    p_restore.add_argument("--dry-run", action="store_true", help="Print the restore plan without changing anything")
    p_restore.set_defaults(func=cmd_restore)

    p_prune = sub.add_parser("prune", parents=[common], help="Delete old snapshots, keeping the last N")
    p_prune.add_argument("--keep", type=int, default=retention.DEFAULT_KEEP)
    p_prune.set_defaults(func=cmd_prune)

    p_doctor = sub.add_parser("doctor", parents=[common], help="Verify a snapshot's integrity")
    p_doctor.add_argument("name", nargs="?", default=None, help="Snapshot name (default: latest)")
    p_doctor.set_defaults(func=cmd_doctor)

    p_cache = sub.add_parser(
        "cache-missing",
        help="Fetch/build tarballs for installed packages with no cached copy, so restore can use them offline",
    )
    p_cache.add_argument("--yes", "-y", action="store_true", help="Don't ask for confirmation")
    p_cache.set_defaults(func=cmd_cache_missing)

    p_install_timer = sub.add_parser(
        "install-timer", parents=[common], help="Install a systemd --user timer that runs `caelback snapshot` periodically"
    )
    p_install_timer.add_argument(
        "--interval-days", type=int, default=14, help="Days between automatic snapshots (default: 14)"
    )
    p_install_timer.set_defaults(func=cmd_install_timer)

    p_uninstall_timer = sub.add_parser("uninstall-timer", help="Remove the timer installed by install-timer")
    p_uninstall_timer.set_defaults(func=cmd_uninstall_timer)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
