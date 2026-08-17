# Bash completion for caelback.
# Install: source this file from ~/.bashrc, or copy to
# /usr/share/bash-completion/completions/caelback (or ~/.local/share/bash-completion/completions/).

_caelback_completions() {
    local cur prev commands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    commands="snapshot list show restore undo prune star unstar doctor reclaim cache-missing install-timer uninstall-timer preview diff"

    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=($(compgen -W "$commands" -- "$cur"))
        return
    fi

    case "${COMP_WORDS[1]}" in
        show|restore|doctor|star|diff)
            local names
            names=$(caelback list 2>/dev/null | awk '{print $1}')
            COMPREPLY=($(compgen -W "$names" -- "$cur"))
            ;;
    esac
}

complete -F _caelback_completions caelback
