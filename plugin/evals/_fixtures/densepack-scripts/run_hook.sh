#!/bin/sh
# Start one DensePack hook script with the first working Python on this machine.
#
# Claude Code runs hooks through sh on each system, with Git Bash on Windows.
# One sh entry per hook replaces a python3 entry and a python entry. A machine
# that lacks one of those names then shows no hook error for it. Ubuntu has no
# python, and many Windows machines have no python3.
#
# The search treats three kinds of PATH entry as unsafe:
#  - A relative entry, such as "." or "bin", resolves inside the project
#    folder. A cloned repository can put its own python3 there.
#  - The Windows Store folder, WindowsApps, holds python.exe and python3.exe
#    stubs that run no script. The search tests those entries last, and uses
#    one only after a test run succeeds. A real Store Python still works.
#  - On macOS, /usr/bin/python3 is a stub when the Xcode Command Line Tools
#    are absent. A run of it opens an install window.
# The search covers the Homebrew folders after PATH, because the PATH of a
# hook often lacks them. With no Python, this script exits 0 and prints
# nothing. The SessionStart check in ensure_python.sh shows what to install.

set -f
saved_ifs=$IFS

# Each probe below has a time limit. Without it, a python3 that never
# returns holds the hook until the Claude Code timeout, which is 1800 seconds
# on two entries. The probe runs in the background, and a watchdog kills it
# after ten seconds. The script does not use timeout(1), because macOS does
# not ship it.
probe() {
    "$@" >/dev/null 2>&1 &
    probe_pid=$!
    # The kill runs only when the sleep SUCCEEDS. Without this, with no sleep
    # on PATH, the watchdog returns at once and kills each candidate. The
    # machine then looks as if it has no Python.
    ( sleep 10 || /bin/sleep 10 ) >/dev/null 2>&1 \
        && kill -9 "$probe_pid" >/dev/null 2>&1 &
    probe_watch=$!
    wait "$probe_pid" 2>/dev/null
    probe_rc=$?
    kill "$probe_watch" >/dev/null 2>&1
    wait "$probe_watch" 2>/dev/null
    return "$probe_rc"
}

# The Python that ensure_python.sh chose at session start, the first Python
# 3.10 or newer that this same search finds. The read builtin reads it, and
# a hook starts no extra process. An old Python first on PATH never starts
# when a newer one is later on PATH. The file is under the home folder, and
# a project cannot write it. With a stale entry, the search below runs.
# DENSEPACK_FIND_PYTHON=1 is the mode that ensure_python.sh calls. In that
# mode, the script prints the first Python 3.10 or newer and does not run a
# script.
if [ -z "${DENSEPACK_FIND_PYTHON:-}" ] && [ -n "${HOME:-}" ] \
        && [ -f "$HOME/.claude/densepack-state/python-path" ]; then
    IFS= read -r cached < "$HOME/.claude/densepack-state/python-path"
    # A file written on Windows can end in CR. A case pattern drops it
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
        # One variable. The split on ":" then reaches the Homebrew folders
        # too. A literal after $PATH stays joined to the last entry of PATH.
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
                # On macOS, /usr/bin/python3 is the Python 3.9 of the Xcode
                # tools, or a stub that opens an install window without those
                # tools. The script prefers a Homebrew Python. -ef compares
                # the file, and the test also matches /usr/bin//python3.
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
                # Only a Python 3.10 or newer runs a hook. This test starts
                # one extra process, only when the saved path above is
                # missing or stale. The search then skips an old Python first
                # on PATH too.
                probe "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
                    || continue
                if [ -n "${DENSEPACK_FIND_PYTHON:-}" ]; then
                    # The path of the interpreter, not of the candidate. A
                    # pyenv shim chooses its Python from the project folder,
                    # and a saved shim follows the .python-version of each
                    # project.
                    real=$("$candidate" -c 'import sys; print(sys.executable)' 2>/dev/null)
                    # The script saves only a / path. A Windows Python reports
                    # C:\..., which the saved-path reader above never starts.
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
