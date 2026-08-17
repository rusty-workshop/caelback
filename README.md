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
  name ahead of time. Deliberately excludes anything containing
  `.pre-restore-` — caelback's own leftover backups from a previous restore
  matched this scan too before that exclusion existed, so an old snapshot
  could otherwise resurrect stale clutter that had already been cleaned up
  (the same exclusion is also applied when *reading* an old snapshot's
  manifest, so an already-taken snapshot with this baked in is harmless too).
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

# Kill leftover processes still drawing a Hyprland layer (bar, wallpaper
# daemon, etc.) that don't look like they belong to Caelestia -- also
# runs automatically as the last step of `restore`
caelback reclaim
caelback reclaim --dry-run

# If a restore turns out to be wrong, revert just its path changes
# (config/state -- not packages or sddm entries)
caelback undo

# Try another dotfiles repo temporarily -- guaranteed to revert to your
# starred snapshot the moment this terminal exits (Ctrl-C, closing it,
# or normal completion)
caelback preview https://github.com/someone/their-dots
caelback preview          # prompts for the URL instead
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

- **Pre-flight check first**: before touching anything live, verifies the
  snapshot's own content matches what its manifest claims (paths present,
  cached package tarballs non-empty, unit/session files present) and that
  `manifest.json` itself actually parses. Refuses to restore from a
  snapshot that fails this, with a clear reason, rather than partially
  restoring from something broken. `--force` restores anyway (missing
  items are still individually skipped, same as always).
- **Won't silently default to an unvetted "most recent"**: if you don't
  pass a name and nothing's starred, it prints a loud warning naming the
  snapshot it's about to use and suggesting `caelback star` — see
  "Starring a snapshot" below for why this matters.
- Reinstalls the exact cached package versions via `pacman -U` (one sudo
  prompt) — **but only for packages that wouldn't be a downgrade**. If a
  package has been legitimately updated since the snapshot was taken (via
  `vercmp` against what's currently installed), it's skipped rather than
  silently rolled back to the older cached version. Anything that wasn't
  cached at snapshot time is also skipped, with a warning.
- Anything already at a destination path is moved aside as
  `<path>.pre-restore-<timestamp>` rather than deleted, so a restore is
  never destructive to whatever you were trying instead. (Collision-safe:
  if that exact name is somehow already taken — e.g. `caelback undo`
  moving aside what a restore just wrote, moments later — a numeric
  suffix is added instead of silently overwriting the existing backup.)
- systemd units are copied in, `daemon-reload`d, and re-enabled if they were
  enabled at snapshot time.
- sddm session entries are copied into `/usr/share/wayland-sessions/` (one
  sudo prompt).
- Checks `hyprctl layers` for anything holding a background/bar/overlay
  layer surface that doesn't look like Caelestia's own (see "Leftover
  processes" below) and offers to kill it.
- Runs `hyprctl reload` automatically so config-level changes (keybinds,
  window rules) take effect immediately, without waiting for you to
  remember to do it.
- **Verifies itself afterward**: re-checks the *live* system against the
  manifest — every path present, every attempted package actually
  installed, enabled systemd units actually enabled, sddm entries present,
  the Caelestia shell process actually running, and (if `livewall` is on
  `PATH`) `livewall doctor`'s own healthy/unhealthy verdict. Prints a
  pass/fail report instead of just trusting that each step exited 0 — a
  step can "succeed" while the live system still isn't right (a service
  needing the reload above, for instance).
- Every restore is logged (`last-restore.json` at the backup root) so
  `caelback undo` can cleanly revert just its path changes if something's
  wrong — see below.
- Nothing outside of what's listed in the snapshot's manifest is touched.

## Undo

`caelback undo` reverts the path changes (config/state — not packages or
sddm entries) from the *most recent* restore, using the log that restore
writes. Whatever the restore had just written is preserved alongside as
`<path>.pre-restore-<timestamp>`, not deleted, so undo is itself
non-destructive. There's no multi-level undo history — it only knows about
the one most recent restore.

## Preview

`caelback preview <repo-url>` tries another dotfiles repo temporarily,
guaranteed to revert to your starred snapshot the moment the terminal it's
running in exits — Ctrl-C, closing the terminal, or normal completion.
Under the hood, ending a preview just calls the same hardened
`caelback restore` as everything above, so it inherits all of it: pre-flight
checks, downgrade-safe packages, `reclaim` killing whatever bar/wallpaper
daemon the previewed dots spawned, the reload, and the post-restore
verification report.

What it actually does:

1. Makes sure a starred snapshot exists (offers to take and star one if not
   — preview refuses to run without a known-good state to guarantee
   returning to).
2. Clones the repo into `~/.cache/caelback/preview/<timestamp>-<name>/`.
3. Looks for a common installer (`install.sh`, `setup.sh`, `bootstrap.sh`)
   and, if found, asks before running it. If nothing's found, or you say
   no, the repo is just sitting there cloned — run whatever it needs
   yourself; the revert-on-exit below still applies for as long as this
   terminal stays open.
4. Arms Ctrl-C/terminal-close/normal-exit to trigger the restore, then
   waits.

**What this can't promise**, stated plainly because "the dots disappear"
undersells the real limits:

- There's no universal format for dotfiles installers, so caelback can't
  correctly apply *any* arbitrary repo — it looks for a few common
  entrypoint names and otherwise leaves running it up to you.
- Running a third-party install script means running arbitrary code —
  caelback always asks before doing that, never silently. Only preview
  repos you actually trust.
- The auto-revert only undoes what caelback tracks (config, state,
  packages it manages, systemd units, sddm entries). It can't undo
  arbitrary side effects an installer might cause outside of that.
- `kill -9` on the preview process can't be caught by anything, ever —
  no cleanup runs. The starred snapshot is still there for a manual
  `caelback restore` in that case.

## Leftover processes from whatever you hopped to

Restoring config files doesn't stop a process another desktop environment's
autostart already spawned — a bar or wallpaper daemon can keep drawing over
Caelestia's own layers even after everything on disk is back to normal,
since Hyprland doesn't re-run `exec-once` or kill existing processes on a
config reload. `caelback` checks `hyprctl layers` (Wayland layer-shell
surfaces — bars, wallpaper daemons, overlays; distinct from regular app
windows) for anything whose owning process doesn't match Caelestia's own
ecosystem, and offers to kill it. This runs automatically at the end of
`restore`, or standalone via `caelback reclaim`.

The actual safety check is deny-by-default and pattern-based, not a
hardcoded list of "known bad" rice names — anything holding a layer that
doesn't mention `caelestia`/`quickshell`/`mpvpaper`/`livewall` (or `dunst`,
this machine's own standing notification daemon) gets flagged, whatever
it's called, so it catches whatever you hop to *next* too. On top of that,
a separate, purely cosmetic lookup recognizes common tools by name — Waybar,
HyprPanel, Ironbar, Polybar, AGS/Astal, eww, Fabric-based bars, swaybg,
swww, hyprpaper, wpaperd, hyprlock, swaylock, gtklock, wlogout, rofi, wofi,
fuzzel, mako, SwayNC, and the specific `mewline`/`awww` pair from the
incident that prompted this — so the confirmation prompt names what it
found instead of showing a bare command line. Anything not on that list
still gets flagged and killable, just without a friendly name.

For a fully clean slate, logging out and back in through a Hyprland session
works too — it just requires actually doing that instead of staying in the
current session.

## License

AGPL-3.0-or-later.
