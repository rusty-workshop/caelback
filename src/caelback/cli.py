"""caelback CLI: snapshot, list, show, restore, prune, doctor, timer install."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import discovery, layers, packages, retention, undo
from .diff import diff_manifests, render_diff
from .manifest import Manifest
from .notify import notify
from .preview import run_preview
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
    prev_snap = retention.latest_snapshot(backup_root)  # capture before this run adds a new one
    prev_manifest = Manifest.load(prev_snap) if prev_snap is not None else None

    print(f"Scanning system and taking snapshot into {backup_root} ...")
    snap_dir = take_snapshot(backup_root)
    m = Manifest.load(snap_dir)
    print(f"Snapshot {m.name} complete ({human_size(m.total_size_bytes())}, {len(m.packages)} package(s)).")
    print(f"  {snap_dir}")

    if prev_manifest is not None:
        d = diff_manifests(prev_manifest, m)
        if not d.is_empty():
            print(f"\n⚠ Changed since {prev_manifest.name}:")
            print(render_diff(d))
            print(
                "  (Not blocking this snapshot -- could be a legitimate update. But if this "
                "wasn't expected (e.g. mid dotfile-hop), run `caelback star <a known-good "
                "snapshot>` so restore/show/doctor won't default to this one.)"
            )
            # The snapshot timer runs unattended -- this is the one case where a printed
            # warning alone could go completely unseen, so also surface it as a notification.
            notify(
                f"caelback: {m.name} changed unexpectedly",
                f"Differs from {prev_manifest.name} -- review with `caelback show`, "
                "star a known-good snapshot if this wasn't expected.",
                urgency="critical",
            )

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
    starred = retention.get_starred(backup_root)
    for snap in snaps:
        m = Manifest.load(snap)
        marker = "  ★" if snap.name == starred else ""
        print(f"{m.name}  {human_size(m.total_size_bytes()):>10}  {len(m.packages)} pkgs  {snap}{marker}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    snaps = retention.list_snapshots(backup_root)

    try:
        if args.snap1 and args.snap2:
            a = retention.resolve_snapshot(args.snap1, backup_root)
            b = retention.resolve_snapshot(args.snap2, backup_root)
        elif args.snap1:
            a = retention.resolve_snapshot(args.snap1, backup_root)
            b = _resolve_and_announce(None, backup_root)  # starred if set, else most recent
        else:
            if len(snaps) < 2:
                print("Need at least 2 snapshots to diff.", file=sys.stderr)
                return 1
            a, b = snaps[-2], snaps[-1]
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    ma = Manifest.load(a)
    mb = Manifest.load(b)
    print(f"Comparing {ma.name} -> {mb.name}:")
    d = diff_manifests(ma, mb)
    if d.is_empty():
        print("No differences.")
    else:
        print(render_diff(d))
    return 0


def _resolve_and_announce(name: str | None, backup_root: Path) -> Path:
    """Resolve a snapshot name, printing which one was picked and why when
    the caller didn't specify one explicitly (starred vs. most recent).

    Deliberately loud about the un-starred fallback -- restoring whatever
    happens to be "most recent" without anyone having vetted it is exactly
    how a mid-dotfile-hop snapshot silently became "latest" and got
    restored in the incident this behavior is designed to prevent.
    """
    snap = retention.resolve_snapshot(name, backup_root)
    if name is None:
        starred = retention.get_starred(backup_root)
        if starred == snap.name:
            print(f"(using starred snapshot: {snap.name})")
        else:
            print(f"⚠ No snapshot is starred — defaulting to the most recent one: {snap.name}")
            print("  This may not be your last known-good state if anything's been snapshotted since.")
            print(f"  Run `caelback star {snap.name}` (or another name) to pin one explicitly.")
    return snap


def cmd_show(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    try:
        snap = _resolve_and_announce(args.name, backup_root)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    print((snap / "MANIFEST.md").read_text())
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    return run_preview(args.repo, backup_root=backup_root, yes=args.yes)


def cmd_restore(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    try:
        snap = _resolve_and_announce(args.name, backup_root)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    ok = restore_snapshot(snap, yes=args.yes, dry_run=args.dry_run, force=args.force)
    return 0 if ok else 1


def cmd_undo(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    ok = undo.undo_last_restore(backup_root, yes=args.yes)
    return 0 if ok else 1


def cmd_prune(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    removed = retention.prune(backup_root, keep=args.keep)
    if removed:
        print(f"Removed {len(removed)} snapshot(s): {', '.join(p.name for p in removed)}")
    else:
        print("Nothing to prune.")
    return 0


def cmd_star(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    if args.name is not None:
        try:
            snap = retention.resolve_snapshot(args.name, backup_root)
        except FileNotFoundError as exc:
            print(exc, file=sys.stderr)
            return 1
    else:
        snap = retention.latest_snapshot(backup_root)
        if snap is None:
            print(f"No snapshots found under {backup_root}", file=sys.stderr)
            return 1
    retention.set_starred(backup_root, snap.name)
    print(
        f"★ Starred {snap.name} — now preferred by default for restore/show/doctor "
        "(instead of 'most recent'), and exempt from auto-pruning."
    )
    return 0


def cmd_unstar(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)
    if retention.get_starred(backup_root) is None:
        print("Nothing is starred.")
        return 0
    retention.clear_starred(backup_root)
    print("Unstarred. restore/show/doctor will default to the most recent snapshot again.")
    return 0


def _check_snapshot(snap: Path) -> list[str]:
    """Integrity issues for one snapshot, as plain strings. Empty = healthy."""
    m = Manifest.load(snap)
    issues = []

    for e in m.all_path_entries():
        if not (snap / e.label).exists():
            issues.append(f"MISSING: {e.label} (expected content for {e.src})")

    for pkg in m.packages:
        if pkg.cached:
            p = snap / pkg.cached_pkg
            if not p.exists() or p.stat().st_size == 0:
                issues.append(f"MISSING/EMPTY cached package: {pkg.name} {pkg.version}")

    for u in m.systemd_units:
        if not (snap / "systemd" / u.name).exists():
            issues.append(f"MISSING systemd unit: {u.name}")

    for s in m.sddm_sessions:
        if not (snap / "sddm-sessions" / s).exists():
            issues.append(f"MISSING sddm session: {s}")

    return issues


def cmd_doctor(args: argparse.Namespace) -> int:
    backup_root = Path(args.backup_root)

    if args.all:
        snaps = retention.list_snapshots(backup_root)
        if not snaps:
            print(f"No snapshots found under {backup_root}")
            return 0
        starred = retention.get_starred(backup_root)
        ok = True
        for snap in snaps:
            issues = _check_snapshot(snap)
            marker = "  ★" if snap.name == starred else ""
            if issues:
                ok = False
                print(f"{snap.name}: {len(issues)} issue(s){marker}")
                for issue in issues:
                    print(f"  {issue}")
            else:
                print(f"{snap.name}: OK{marker}")
        print()
        print(f"{len(snaps)} snapshot(s) checked." if ok else f"{len(snaps)} snapshot(s) checked, some had issues.")
        return 0 if ok else 1

    try:
        snap = _resolve_and_announce(args.name, backup_root)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    issues = _check_snapshot(snap)
    for issue in issues:
        print(issue)
    m = Manifest.load(snap)
    if not issues:
        print(f"{snap.name}: OK — all {len(m.all_path_entries())} path(s), {len(m.packages)} package(s) present.")
    return 0 if not issues else 1


def cmd_reclaim(args: argparse.Namespace) -> int:
    unexpected = layers.find_unexpected_layer_owners()
    if not unexpected:
        print("No unexpected processes found drawing a Hyprland layer.")
        return 0

    print(f"{len(unexpected)} process(es) drawing a Hyprland layer that don't look like Caelestia's own:")
    for o in unexpected:
        print(f"  - {layers.format_owner(o)}")

    if args.dry_run:
        print("(dry run — not killing anything)")
        return 0

    if not args.yes and not confirm("\nKill these?"):
        print("Skipped.")
        return 0

    layers.kill_owners(unexpected)
    print(f"Killed {len(unexpected)} process(es).")
    return 0


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

    p_preview = sub.add_parser(
        "preview",
        parents=[common],
        help="Temporarily try another dotfiles repo, auto-reverting to Caelestia when this terminal exits",
    )
    p_preview.add_argument("repo", nargs="?", default=None, help="Repo URL to clone (prompted if omitted)")
    p_preview.add_argument(
        "--yes", "-y", action="store_true", help="Don't ask before taking/starring a safety snapshot if none exists"
    )
    p_preview.set_defaults(func=cmd_preview)

    p_restore = sub.add_parser("restore", parents=[common], help="Restore a snapshot (one-click revert to Caelestia)")
    p_restore.add_argument("name", nargs="?", default=None, help="Snapshot name (default: latest)")
    p_restore.add_argument("--yes", "-y", action="store_true", help="Don't ask for confirmation")
    p_restore.add_argument("--dry-run", action="store_true", help="Print the restore plan without changing anything")
    p_restore.add_argument(
        "--force", action="store_true", help="Restore even if the snapshot fails its own integrity check"
    )
    p_restore.set_defaults(func=cmd_restore)

    p_undo = sub.add_parser(
        "undo", parents=[common], help="Revert the path changes from the most recent restore"
    )
    p_undo.add_argument("--yes", "-y", action="store_true", help="Don't ask for confirmation")
    p_undo.set_defaults(func=cmd_undo)

    p_prune = sub.add_parser("prune", parents=[common], help="Delete old snapshots, keeping the last N")
    p_prune.add_argument("--keep", type=int, default=retention.DEFAULT_KEEP)
    p_prune.set_defaults(func=cmd_prune)

    p_star = sub.add_parser(
        "star",
        parents=[common],
        help="Mark a snapshot as the preferred default for restore/show/doctor, exempt from auto-pruning",
    )
    p_star.add_argument("name", nargs="?", default=None, help="Snapshot name (default: the current latest)")
    p_star.set_defaults(func=cmd_star)

    p_unstar = sub.add_parser(
        "unstar", parents=[common], help="Remove the star, reverting to 'most recent' as the default"
    )
    p_unstar.set_defaults(func=cmd_unstar)

    p_doctor = sub.add_parser("doctor", parents=[common], help="Verify a snapshot's integrity")
    p_doctor.add_argument("name", nargs="?", default=None, help="Snapshot name (default: latest)")
    p_doctor.add_argument("--all", action="store_true", help="Check every snapshot instead of just one")
    p_doctor.set_defaults(func=cmd_doctor)

    p_diff = sub.add_parser(
        "diff", parents=[common], help="Compare two snapshots (defaults to the last two taken)"
    )
    p_diff.add_argument("snap1", nargs="?", default=None, help="First snapshot (default: second-to-last taken)")
    p_diff.add_argument(
        "snap2", nargs="?", default=None, help="Second snapshot (default: starred if set, else most recent)"
    )
    p_diff.set_defaults(func=cmd_diff)

    p_reclaim = sub.add_parser(
        "reclaim",
        help="Kill leftover processes drawing a Hyprland layer that don't look like Caelestia's own",
    )
    p_reclaim.add_argument("--yes", "-y", action="store_true", help="Don't ask for confirmation")
    p_reclaim.add_argument("--dry-run", action="store_true", help="List what would be killed without killing it")
    p_reclaim.set_defaults(func=cmd_reclaim)

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
