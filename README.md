# caelback

*(pronounced like "callback")*

Snapshot and one-click restore for a [Caelestia](https://github.com/caelestia-dots/caelestia)
setup, so you can go dotfile-hopping and come back to exactly what you had.

Takes a full snapshot of everything Caelestia-related on the machine — config,
state, the exact installed package versions (cached locally, so restore works
offline), systemd units, sddm session entries, and every third-party app
Caelestia has themed — and can restore all of it back in one command.

## Why

Caelestia is deeply wired into a live setup: it themes a bunch of
third-party apps, ships systemd units, and pins exact package versions
(including AUR packages that move fast, like `quickshell-git`). Manually
tracking all of that before trying a different desktop environment is
tedious and easy to get wrong. `caelback` finds it automatically.

## What gets captured

Rather than a hardcoded list of apps Caelestia is known to theme, `caelback`
combines a few known roots with a fuzzy scan:

- **Named config dirs**: `~/.config/{hypr,caelestia,livewall}`
- **Named state dirs**: `~/.local/share/caelestia-aw`, `~/.local/state/caelestia`,
  `~/.local/share/livewall`
- **Fuzzy scan**: anything else under `~/.config`, `~/.local/share`, or
  `~/.local/state` whose name contains "caelestia" — this is what catches
  themed third-party apps (Discord clients, zed, btop, spicetify, qtengine,
  browser extensions, whatever else) without needing to know about them by
  name ahead of time.
- **Packages**: every installed package whose name contains "caelestia" or
  "quickshell", at their exact installed version. The actual `.pkg.tar.zst`
  is located in `/var/cache/pacman/pkg`, `~/.cache/yay`, or
  `~/.cache/paru/clone` and copied into the snapshot, so restore doesn't need
  network or AUR access — unless a package wasn't cached anywhere on disk at
  snapshot time, in which case it's flagged and skipped. Run
  `caelback cache-missing` to fetch/build a tarball for anything currently
  uncached (some AUR helpers don't retain build artifacts after install), then
  take a fresh snapshot.
- **systemd --user units** whose name contains "caelestia" or "livewall",
  along with whether each was enabled.
- **sddm session entries** whose name contains "hyprland" (i.e. the ones
  Caelestia's `~/.config/hypr` actually uses to log in).

## Install

Requires [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/rustyisacat/caelback.git
cd caelback
uv tool install --editable .
```

This puts `caelback` on your `PATH`.

## Usage

```bash
# Take a snapshot before switching to something else
caelback snapshot

# See what snapshots exist
caelback list

# Look at exactly what a snapshot contains
caelback show                # latest
caelback show 2026-08-12_193000

# Preview a restore without changing anything
caelback restore --dry-run

# Actually restore (defaults to the latest snapshot)
caelback restore

# Sanity-check a snapshot's contents are all present and non-empty
caelback doctor

# Manually prune old snapshots, keeping the last N (snapshot already
# does this automatically; default keep is 5)
caelback prune --keep 5

# Mark a snapshot as the one restore/show/doctor should default to,
# instead of "most recent" -- and exempt it from auto-pruning forever
caelback star                        # star the current latest
caelback star 2026-08-14_134602      # star a specific one
caelback unstar                      # back to defaulting on "most recent"

# Fetch/build a tarball for any installed package that isn't cached
# anywhere on disk yet, so the next snapshot can restore it offline too
caelback cache-missing

# Install a systemd --user timer that runs `caelback snapshot`
# automatically (default: every 14 days)
caelback install-timer
caelback install-timer --interval-days 7   # or any other cadence
caelback uninstall-timer                    # remove it again
```

Snapshots live under `~/Backups/caelback/<timestamp>/` by default. Pass
`--backup-root <path>` *after* the subcommand (e.g. `caelback snapshot
--backup-root /mnt/external/caelback`) to use somewhere else. Each snapshot
has a `manifest.json` (machine-readable) and `MANIFEST.md` (human-readable)
describing exactly what's inside.

## If Caelestia isn't installed

`caelback snapshot` checks first whether Caelestia actually looks
installed (`~/.config/caelestia` exists, or some installed package name
contains "caelestia" — deliberately *not* just "quickshell", since other
things can depend on that toolkit independently of Caelestia). If not, it
skips without creating anything and exits cleanly (`0`), rather than
snapshotting an empty setup and letting auto-pruning eventually push out
the one real snapshot you'd actually want to restore from. This is what
makes `install-timer` safe to leave running indefinitely, including after
you've moved on to something else. Pass `--force` to snapshot anyway.

## Starring a snapshot

If you dotfile-hop and something else gets snapshotted while you're mid-hop
(e.g. the `install-timer` timer fires, or you run `caelback snapshot`
without thinking), that snapshot becomes "latest" — and a bare
`caelback restore` afterward would restore *that*, not your last actually-good
Caelestia state. `caelback star <name>` pins a specific snapshot as the
default for `restore`/`show`/`doctor` instead of "most recent," and that
snapshot is permanently exempt from `--keep` auto-pruning regardless of its
age. `caelback unstar` reverts to defaulting on "most recent." `caelback
list` marks the starred one with `★`, and every command that resolved a
snapshot implicitly (no name given) prints which one it picked and why.

## Detecting an unexpected snapshot

Every `caelback snapshot` diffs itself against the *previous* snapshot and
prints a warning if anything changed substantially — new or disappeared
paths, a path's size changing by more than 15%, package version changes,
or systemd/sddm entries appearing or disappearing. It doesn't block the
snapshot (could be a legitimate Caelestia update) but it makes a
mid-dotfile-hop snapshot (or anything else unexpected) impossible to miss
in the terminal output, instead of silently becoming "latest" weeks later.
If you see this and it wasn't expected, `caelback star` your last known-good
snapshot right away.

## Restore behavior

- Reinstalls the exact cached package versions via `pacman -U` (one sudo
  prompt) — **but only for packages that wouldn't be a downgrade**. If a
  package has been legitimately updated since the snapshot was taken (via
  `vercmp` against what's currently installed), it's skipped rather than
  silently rolled back to the older cached version. Anything that wasn't
  cached at snapshot time is also skipped, with a warning.
- Anything already at a destination path is moved aside as
  `<path>.pre-restore-<timestamp>` rather than deleted, so a restore is
  never destructive to whatever you were trying instead.
- systemd units are copied in, `daemon-reload`d, and re-enabled if they were
  enabled at snapshot time.
- sddm session entries are copied into `/usr/share/wayland-sessions/` (one
  sudo prompt).
- Nothing outside of what's listed in the snapshot's manifest is touched.

## License

AGPL-3.0-or-later.
