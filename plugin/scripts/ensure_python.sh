#!/bin/sh
# Tells you how to get Python on Linux and macOS when the machine has none.
# The plugin hooks need Python to run. SessionStart only.
#
# Each other script in this folder is Python. On a machine with no Python,
# none of them can print a message, because the hook never starts. /bin/sh is
# on each Linux and macOS machine, and this script runs where they cannot.
#
# It installs nothing. Session start waits for this hook, and each install
# route takes minutes. brew builds, and apt, dnf and pacman need sudo, which
# cannot ask for a password inside a hook. The script names the install
# command for the system and never fails without a message.
#
# On macOS, the plain "is python3 there" test is wrong. /usr/bin/python3 is a
# stub that belongs to the Xcode Command Line Tools. A run of it without those
# tools opens a window that asks to install them. usable_python() below tests
# for the tools with xcode-select -p, which opens nothing. It looks in the two
# Homebrew prefixes by path, because the PATH of a hook holds neither.
#
# It writes only one marker file and the saved Python path, changes no
# setting and blocks nothing. On a machine that already has Python, it prints
# nothing.
#
# Claude Code reads the stdout of a hook as JSON. The only output here is one
# JSON object with systemMessage, the field that Claude Code shows on screen.

say() {
    # printf, not echo, because echo changes a backslash on some shells, and
    # the output must stay valid JSON.
    printf '{"systemMessage":"%s"}' "$1"
}

OS=$(uname -s 2>/dev/null || echo unknown)

probe() {
    # A time limit, the same as in run_hook.sh. A python3 that never returns
    # holds session start until the Claude Code hook timeout. macOS ships no
    # timeout(1). A background job and a watchdog do the work.
    "$@" >/dev/null 2>&1 &
    probe_pid=$!
    # The kill runs only when the sleep SUCCEEDS. A PATH with no sleep leaves
    # the probe with no time limit and does not kill each candidate.
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
    # The one Python search that each hook uses. run_hook.sh in find mode
    # walks the same PATH folders as a hook. It rejects a relative entry,
    # skips the macOS placeholder at /usr/bin/python3 without the Xcode
    # tools, prefers a Homebrew Python over it, and prints the first Python
    # 3.10 or newer. The script does not use command -v. Under bash, command
    # -v changes a relative PATH entry to an absolute path, and a python3 file
    # in the project folder can then run.
    sh_bin=/bin/sh
    [ -x "$sh_bin" ] || sh_bin=sh
    # The folder of this script, from a path with / or, under Git Bash, \.
    here=${0%/*}
    [ "$here" != "$0" ] || here=${0%\\*}
    [ "$here" != "$0" ] || here=.
    DENSEPACK_FIND_PYTHON=1 "$sh_bin" "$here/run_hook.sh" 2>/dev/null
}

usable_python() {
    # True when the search finds a Python 3.10 or newer. The plugin installs
    # Pillow 12, which has no wheel for an older one, and the Python of the
    # Xcode tools is 3.9. The function saves the path under the home folder,
    # where a project cannot write. Each hook starts that Python first, and
    # an old Python earlier on PATH never runs a hook.
    FOUND=$(find_python)
    [ -n "$FOUND" ] || return 1
    # The function does not save the Python of a virtual environment. A saved
    # one starts in each later hook, also after that environment leaves PATH.
    if [ -n "${HOME:-}" ] \
            && probe "$FOUND" -c 'import sys; sys.exit(sys.prefix != sys.base_prefix)'; then
        # The path goes to a file of its own and then moves into place. A
        # hook never reads a half-written path.
        state="$HOME/.claude/densepack-state"
        ( mkdir -p "$state" \
            && printf '%s\n' "$FOUND" > "$state/python-path.$$" \
            && mv -f "$state/python-path.$$" "$state/python-path" ) 2>/dev/null
    fi
    return 0
}

# On Windows, Claude Code runs this through Git Bash, and ensure_python.ps1
# does the install with winget. One sh entry then serves each system, and a
# Linux or macOS machine never needs a powershell command.
case "$OS" in
    MINGW*|MSYS*|CYGWIN*)
        if command -v powershell >/dev/null 2>&1; then
            exec powershell -NoProfile -ExecutionPolicy Bypass -File "$(dirname "$0")/ensure_python.ps1"
        fi
        # No PowerShell to pass the work to. The script prints a message only
        # when no Python starts here.
        usable_python && exit 0
        say "DensePack needs Python 3.10 or newer on Windows. Install it from python.org, select Add python.exe to PATH, then restart Claude Code."
        exit 0
        ;;
esac

if usable_python; then
    exit 0
fi

# The message with the install command shows once per machine. Delete this
# file to show it again.
#
# The two writes run inside a subshell with stderr closed. When a redirect
# fails, because the folder is missing or read only, the SHELL reports it,
# not the command. 2>/dev/null on the command does not hide it, and "cannot
# create" reaches stderr. Claude Code reads the stderr of a hook, and that
# line then shows as a hook error on a machine that this script tries to
# help. When the marker write fails, the next session tries again.
DATA="${CLAUDE_PLUGIN_DATA:-$HOME/.densepack}"
( mkdir -p "$DATA" ) 2>/dev/null
TRIED="$DATA/python-install-tried"
if [ -f "$TRIED" ]; then
    say "DensePack found no Python 3.10 or newer. None of its hooks run, and reports arrive as plain text. An earlier session showed the install command. Install Python 3.10 or newer, then restart Claude Code."
    exit 0
fi
( printf 'tried' > "$TRIED" ) 2>/dev/null

# No install runs here, on any platform. brew takes minutes, and session
# start waits for this hook. The message below names the command to run.

# The command to show on screen. macOS gets its own answer, because apt, dnf
# and pacman are Linux package managers and a Mac has none of them. The two
# routes named here need no administrator password. Homebrew and the uv
# installer write inside your own directories.
#
# CMD must hold no double quote and no backslash. say() puts it directly
# into a JSON string with printf and escapes nothing. Either character makes
# JSON that Claude Code cannot parse.
if [ "$OS" = "Darwin" ]; then
    CMD="brew install python , after installing Homebrew from https://brew.sh , or curl -LsSf https://astral.sh/uv/install.sh | sh and then uv python install --default"
elif command -v apt >/dev/null 2>&1; then
    CMD="sudo apt install python3 python3-pip"
elif command -v dnf >/dev/null 2>&1; then
    CMD="sudo dnf install python3 python3-pip"
elif command -v pacman >/dev/null 2>&1; then
    CMD="sudo pacman -S python python-pip"
else
    say "DensePack needs Python 3.10 or newer, and this computer has no such Python. None of its hooks run, and reports arrive as plain text. Install Python 3.10 or newer with your package manager, then restart Claude Code."
    exit 0
fi

say "DensePack needs Python 3.10 or newer, and this computer has no such Python. None of its hooks run, and reports arrive as plain text. Run: $CMD , then restart Claude Code."
exit 0
