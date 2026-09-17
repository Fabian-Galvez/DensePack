#!/bin/sh
# Tell the user how to get Python on Linux and macOS when the machine has none,
# so the plugin's hooks can run. SessionStart only.
#
# Every other script in this folder is Python, so none of them can speak on a
# machine with no Python: the hook would never start. /bin/sh is on every Linux
# and macOS, so this one runs where they cannot.
#
# It installs nothing. Session start waits for this hook, and every install
# route takes minutes: brew builds, and apt, dnf and pacman need sudo, which
# cannot ask for a password inside a hook. So the script names the command
# for this machine instead of failing silently.
#
# On macOS the plain "is python3 there" test is wrong. /usr/bin/python3 is a
# stub that belongs to the Xcode Command Line Tools, and running it with those
# tools absent opens a window asking to install them. usable_python() below
# tests for the tools with xcode-select -p, which opens nothing, and looks in
# both Homebrew prefixes by path because a hook's PATH holds neither.
#
# It writes nothing except one marker file, changes no setting and blocks
# nothing. On a machine that already has Python it prints nothing at all.
#
# Claude Code reads a hook's stdout as JSON, so the only output here is one
# JSON object carrying systemMessage, the field Claude Code shows the user.

say() {
    # printf, not echo, because echo mangles a backslash on some shells and the
    # output has to stay valid JSON.
    printf '{"systemMessage":"%s"}' "$1"
}

OS=$(uname -s 2>/dev/null || echo unknown)

probe() {
    # Bounded, like run_hook.sh's own: a python3 that never returns would
    # hold session start until Claude Code's hook timeout. macOS ships no
    # timeout(1), so a background job and a watchdog do the work.
    "$@" >/dev/null 2>&1 &
    probe_pid=$!
    # The kill waits on the sleep SUCCEEDING, so a PATH with no sleep on it
    # leaves the probe unbounded rather than killing every candidate.
    ( sleep 10 || /bin/sleep 10 ) >/dev/null 2>&1 \
        && kill -9 "$probe_pid" >/dev/null 2>&1 &
    probe_watch=$!
    wait "$probe_pid" 2>/dev/null
    probe_rc=$?
    kill "$probe_watch" >/dev/null 2>&1
    wait "$probe_watch" 2>/dev/null
    return "$probe_rc"
}


find_python() {
    # The one Python search every hook uses. run_hook.sh in find mode walks
    # the same PATH folders a hook walks, refuses a relative entry, skips the
    # macOS placeholder at /usr/bin/python3 without the Xcode tools, prefers
    # a Homebrew Python over it, and prints the first Python 3.10 or newer.
    # command -v is not used: under bash it turns a relative PATH entry into
    # an absolute path, so a python3 planted in the project folder would run.
    sh_bin=/bin/sh
    [ -x "$sh_bin" ] || sh_bin=sh
    # This script's folder, from a path with / or, under Git Bash, \.
    here=${0%/*}
    [ "$here" != "$0" ] || here=${0%\\*}
    [ "$here" != "$0" ] || here=.
    DENSEPACK_FIND_PYTHON=1 "$sh_bin" "$here/run_hook.sh" 2>/dev/null
}

usable_python() {
    # True when the search finds a Python 3.10 or newer. Pillow 12, which the
    # plugin installs, has no wheel for an older one, and the Xcode tools'
    # Python is 3.9. The path is saved under the home folder, where a project
    # cannot write, and every hook starts that Python first, so an old Python
    # earlier on PATH never runs a hook.
    FOUND=$(find_python)
    [ -n "$FOUND" ] || return 1
    # A virtual environment's Python is not saved: every later hook would
    # start it after that environment has left PATH.
    if [ -n "${HOME:-}" ] \
            && probe "$FOUND" -c 'import sys; sys.exit(sys.prefix != sys.base_prefix)'; then
        # Written to a file of its own, then moved into place, so a hook never
        # reads a half-written path.
        state="$HOME/.claude/densepack-state"
        ( mkdir -p "$state" \
            && printf '%s\n' "$FOUND" > "$state/python-path.$$" \
            && mv -f "$state/python-path.$$" "$state/python-path" ) 2>/dev/null
    fi
    return 0
}

# On Windows, Claude Code runs this through Git Bash, and ensure_python.ps1
# does the install with winget. One sh entry then serves every system, and a
# Linux or macOS machine never needs a powershell command.
case "$OS" in
    MINGW*|MSYS*|CYGWIN*)
        if command -v powershell >/dev/null 2>&1; then
            exec powershell -NoProfile -ExecutionPolicy Bypass -File "$(dirname "$0")/ensure_python.ps1"
        fi
        # No PowerShell to hand off to: say only when no Python starts here.
        usable_python && exit 0
        say "DensePack needs Python 3.10 or newer on Windows. Install it from python.org, tick Add python.exe to PATH, then restart Claude Code."
        exit 0
        ;;
esac

if usable_python; then
    exit 0
fi

# One attempt per machine. Delete this file to let it try again.
#
# Both writes run inside a subshell with stderr closed. A redirect that fails,
# because the folder is not there or is read only, is reported by the SHELL and
# not by the command, so 2>/dev/null on the command itself does not silence it
# and "cannot create" reaches stderr. Claude Code reads a hook's stderr, so
# that line would surface as a hook error on a machine this script is trying to
# help. Failing to write the marker only means the next session tries again.
DATA="${CLAUDE_PLUGIN_DATA:-$HOME/.densepack}"
( mkdir -p "$DATA" ) 2>/dev/null
TRIED="$DATA/python-install-tried"
if [ -f "$TRIED" ]; then
    say "DensePack found no Python 3.10 or newer, so none of its hooks run and reports arrive as plain text. It already tried once on this machine. Install Python 3.10 or newer, then restart Claude Code."
    exit 0
fi
( printf 'tried' > "$TRIED" ) 2>/dev/null

# No install runs here, on any platform. brew takes minutes and session start
# waits for this hook, so the message below names the command to run instead.

# What to tell the user to run. macOS gets its own answer, because apt, dnf and
# pacman are Linux package managers and a Mac carries none of them. The two
# routes named here need no administrator password: Homebrew and the uv
# installer both write inside the user's own directories.
#
# No double quote and no backslash may appear in CMD. say() drops it straight
# into a JSON string with printf and escapes nothing, so either character
# would produce JSON that Claude Code cannot parse.
if [ "$OS" = "Darwin" ]; then
    CMD="brew install python , after installing Homebrew from https://brew.sh , or curl -LsSf https://astral.sh/uv/install.sh | sh and then uv python install"
elif command -v apt >/dev/null 2>&1; then
    CMD="sudo apt install python3"
elif command -v dnf >/dev/null 2>&1; then
    CMD="sudo dnf install python3"
elif command -v pacman >/dev/null 2>&1; then
    CMD="sudo pacman -S python"
else
    say "DensePack needs Python 3.10 or newer and this machine has no such Python, so none of its hooks run and reports arrive as plain text. Install Python 3.10 or newer with your package manager, then restart Claude Code."
    exit 0
fi

say "DensePack needs Python 3.10 or newer and this machine has no such Python, so none of its hooks run and reports arrive as plain text. Run: $CMD , then restart Claude Code."
exit 0
