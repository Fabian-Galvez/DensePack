#!/bin/sh
# Start one DensePack hook script with the first working Python on this machine.
#
# Claude Code runs hooks through sh on every system, with Git Bash on Windows.
# One sh entry per hook replaces a python3 entry and a python entry. A machine
# that lacks one of those names then shows no hook error for it. Ubuntu has no
# python, and many Windows machines have no python3.
#
# Three kinds of PATH entry are not trusted:
#  - A relative entry, such as "." or "bin", resolves inside the project
#    folder, so a cloned repository could put its own python3 there.
#  - The Windows Store folder, WindowsApps, holds python.exe and python3.exe
#    stubs that run no script. Those entries are tried last, and only after a
#    test run succeeds, so a real Store Python still works.
#  - On macOS, /usr/bin/python3 is a stub when the Xcode Command Line Tools
#    are absent, and running it opens an install window.
# The Homebrew folders are searched after PATH, because a hook's PATH often
# lacks them. With no Python at all this exits 0 and prints nothing; the
# SessionStart check in ensure_python.sh tells the user what to install.

set -f
saved_ifs=$IFS

# Every probe below is bounded. A python3 that never returns would otherwise
# hold the hook until Claude Code's own timeout, which is 1800 seconds on two
# entries. The probe runs in the background and a watchdog kills it after ten
# seconds. timeout(1) is not used, because macOS does not ship it.
probe() {
    "$@" >/dev/null 2>&1 &
    probe_pid=$!
    # The kill waits on the sleep SUCCEEDING. With no sleep on PATH the
    # watchdog would otherwise return at once and kill every candidate, and
    # the machine would look as if it had no Python at all.
    ( sleep 10 || /bin/sleep 10 ) >/dev/null 2>&1 \
        && kill -9 "$probe_pid" >/dev/null 2>&1 &
    probe_watch=$!
    wait "$probe_pid" 2>/dev/null
    probe_rc=$?
    kill "$probe_watch" >/dev/null 2>&1
    wait "$probe_watch" 2>/dev/null
    return "$probe_rc"
}

# The Python ensure_python.sh chose at session start: the first Python 3.10
# or newer this same search finds. It is read with the read builtin, so a
# hook starts no extra process, and an old Python first on PATH is never
# started when a newer one sits later. The file is under the home folder, so
# a project cannot write it. A stale entry falls through to the search below.
# DENSEPACK_FIND_PYTHON=1 is the mode ensure_python.sh calls: it prints the
# first Python 3.10 or newer instead of running a script.
if [ -z "${DENSEPACK_FIND_PYTHON:-}" ] && [ -n "${HOME:-}" ] \
        && [ -f "$HOME/.claude/densepack-state/python-path" ]; then
    IFS= read -r cached < "$HOME/.claude/densepack-state/python-path"
    # A file written on Windows can end in CR; a case pattern drops it
    # without starting a process.
    case "$cached" in
        *[[:cntrl:]]) cached=${cached%?} ;;
    esac
    case "$cached" in
        /*) [ -f "$cached" ] && [ -s "$cached" ] && [ -x "$cached" ] && exec "$cached" "$@" ;;
    esac
fi
for pass in plain store; do
    for name in python3 python py; do
        IFS=:
        # One variable, so the split on ":" reaches the Homebrew folders too.
        # A literal after $PATH stays joined to PATH's last entry.
        search="$PATH:/opt/homebrew/bin:/usr/local/bin"
        for dir in $search; do
            IFS=$saved_ifs
            case "$dir" in
                /*) ;;
                *) continue ;;
            esac
            case "$dir" in
                *WindowsApps*) [ "$pass" = store ] || continue ;;
                *) [ "$pass" = plain ] || continue ;;
            esac
            for candidate in "$dir/$name" "$dir/$name.exe"; do
                [ -f "$candidate" ] && [ -x "$candidate" ] || continue
                # On macOS, /usr/bin/python3 is the Xcode tools' Python 3.9, or
                # a stub that opens an install window without those tools. A
                # Homebrew Python wins over it. -ef compares the file, so
                # /usr/bin//python3 is caught too.
                if [ "$candidate" -ef /usr/bin/python3 ] && [ "$(uname -s 2>/dev/null)" = Darwin ]; then
                    for brew in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
                        [ -x "$brew" ] || continue
                        probe "$brew" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
                            || continue
                        if [ -n "${DENSEPACK_FIND_PYTHON:-}" ]; then
                            real=$("$brew" -c 'import sys; print(sys.executable)' 2>/dev/null)
                            case "$real" in /*) ;; *) real=$brew ;; esac
                            printf '%s\n' "$real"
                            exit 0
                        fi
                        exec "$brew" "$@"
                    done
                    xcode-select -p >/dev/null 2>&1 || continue
                fi
                if [ "$pass" = store ] && ! probe "$candidate" -c ""; then
                    continue
                fi
                # Only a Python 3.10 or newer runs a hook. This test starts one
                # extra process, and only when the saved path above is missing
                # or stale, so an old Python first on PATH is skipped then too.
                probe "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
                    || continue
                if [ -n "${DENSEPACK_FIND_PYTHON:-}" ]; then
                    # The interpreter's own path, not the candidate's: a pyenv
                    # shim picks its Python from the project folder, and a
                    # saved shim would follow every project's .python-version.
                    real=$("$candidate" -c 'import sys; print(sys.executable)' 2>/dev/null)
                    # Only a / path is saved: a Windows Python reports C:\...,
                    # which the saved-path reader above never starts.
                    case "$real" in /*) ;; *) real=$candidate ;; esac
                    printf '%s\n' "$real"
                    exit 0
                fi
                exec "$candidate" "$@"
            done
        done
        IFS=$saved_ifs
    done
done
exit 0
