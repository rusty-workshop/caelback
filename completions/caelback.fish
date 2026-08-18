# Fish completion for caelback.
# Install: cp completions/caelback.fish ~/.config/fish/completions/caelback.fish

set -l __caelback_commands snapshot list show restore undo prune star unstar doctor verify-live status reclaim cache-missing install-timer uninstall-timer preview diff export import

function __caelback_snapshot_names
    caelback list 2>/dev/null | string replace -rf '^(\S+).*' '$1'
end

# No file completion by default; subcommands opt back in where useful (repo
# paths for preview, if ever run against a local clone).
complete -c caelback -f

# Subcommands, only before one has been chosen.
complete -c caelback -n "not __fish_seen_subcommand_from $__caelback_commands" -a "$__caelback_commands"

complete -c caelback -n "__fish_seen_subcommand_from snapshot" -a snapshot -d "Take a new snapshot"
complete -c caelback -n "__fish_seen_subcommand_from list" -a list -d "List snapshots"
complete -c caelback -n "__fish_seen_subcommand_from show" -a show -d "Print a snapshot's manifest"
complete -c caelback -n "__fish_seen_subcommand_from restore" -a restore -d "Restore a snapshot"
complete -c caelback -n "__fish_seen_subcommand_from undo" -a undo -d "Revert the last restore's path changes"
complete -c caelback -n "__fish_seen_subcommand_from prune" -a prune -d "Delete old snapshots"
complete -c caelback -n "__fish_seen_subcommand_from star" -a star -d "Pin a snapshot as the default"
complete -c caelback -n "__fish_seen_subcommand_from unstar" -a unstar -d "Remove the star"
complete -c caelback -n "__fish_seen_subcommand_from doctor" -a doctor -d "Verify snapshot integrity"
complete -c caelback -n "__fish_seen_subcommand_from verify-live" -a verify-live -d "Compare the live system against a snapshot"
complete -c caelback -n "__fish_seen_subcommand_from status" -a status -d "Quick overview: snapshots, live drift, timer"
complete -c caelback -n "__fish_seen_subcommand_from reclaim" -a reclaim -d "Kill leftover layer-drawing processes"
complete -c caelback -n "__fish_seen_subcommand_from cache-missing" -a cache-missing -d "Cache uncached package tarballs"
complete -c caelback -n "__fish_seen_subcommand_from install-timer" -a install-timer -d "Install the periodic snapshot timer"
complete -c caelback -n "__fish_seen_subcommand_from uninstall-timer" -a uninstall-timer -d "Remove the periodic snapshot timer"
complete -c caelback -n "__fish_seen_subcommand_from preview" -a preview -d "Temporarily try another dotfiles repo"
complete -c caelback -n "__fish_seen_subcommand_from diff" -a diff -d "Compare two snapshots"
complete -c caelback -n "__fish_seen_subcommand_from export" -a export -d "Bundle a snapshot into a portable .tar.gz"
complete -c caelback -n "__fish_seen_subcommand_from import" -a import -d "Import a .tar.gz created by export"

# Snapshot-name completion for commands that take one.
complete -c caelback -n "__fish_seen_subcommand_from show restore doctor verify-live star diff export" -a "(__caelback_snapshot_names)" -d "snapshot"

# Flags, scoped to the subcommand(s) that actually accept them.
complete -c caelback -l backup-root -d "Where snapshots live" -x

complete -c caelback -n "__fish_seen_subcommand_from list" -l json -d "Machine-readable JSON output"

complete -c caelback -n "__fish_seen_subcommand_from snapshot" -l keep -d "Keep only the last N snapshots" -x
complete -c caelback -n "__fish_seen_subcommand_from snapshot" -l force -d "Snapshot even if Caelestia isn't installed"

complete -c caelback -n "__fish_seen_subcommand_from restore" -l yes -s y -d "Don't ask for confirmation"
complete -c caelback -n "__fish_seen_subcommand_from restore" -l dry-run -d "Preview the restore without changing anything"
complete -c caelback -n "__fish_seen_subcommand_from restore" -l force -d "Restore even if the integrity check fails"

complete -c caelback -n "__fish_seen_subcommand_from undo" -l yes -s y -d "Don't ask for confirmation"

complete -c caelback -n "__fish_seen_subcommand_from prune" -l keep -d "Keep only the last N snapshots" -x

complete -c caelback -n "__fish_seen_subcommand_from doctor" -l all -d "Check every snapshot instead of just one"

complete -c caelback -n "__fish_seen_subcommand_from reclaim" -l yes -s y -d "Don't ask for confirmation"
complete -c caelback -n "__fish_seen_subcommand_from reclaim" -l dry-run -d "List without killing anything"

complete -c caelback -n "__fish_seen_subcommand_from cache-missing" -l yes -s y -d "Don't ask for confirmation"

complete -c caelback -n "__fish_seen_subcommand_from install-timer" -l interval-days -d "Days between automatic snapshots" -x

complete -c caelback -n "__fish_seen_subcommand_from preview" -l yes -s y -d "Don't ask before taking/starring a safety snapshot"
complete -c caelback -n "__fish_seen_subcommand_from preview" -l list -d "Show past preview sessions instead of starting one"

complete -c caelback -n "__fish_seen_subcommand_from export" -l output -s o -d "Output path or directory" -r
complete -c caelback -n "__fish_seen_subcommand_from import" -l name -d "Store under this name instead of the one in the archive" -x
