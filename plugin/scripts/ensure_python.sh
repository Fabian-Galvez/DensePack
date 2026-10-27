#!/bin/sh
# Gets Python on macOS, and tells you how to get it on Linux, when the
# machine has none. The plugin hooks need Python to run. SessionStart only.
#
# Each other script in this folder is Python. On a machine with no Python,
# none of them can print a message, because the hook never starts. /bin/sh is
# on each Linux and macOS machine, and this script runs where they cannot.
#
# On macOS, it starts install_python_uv.sh in the background, one time for
# each computer. That script puts a Python of DensePack's own in the data
# folder of the plugin with uv, which needs no administrator password. On
# Linux it installs nothing, because apt, dnf and pacman need sudo, which
# cannot ask for a password inside a hook. The script names the install
# command for the system and never fails without a message.
#
# On macOS, the plain "is python3 there" test is wrong. /usr/bin/python3 is a
# stub that belongs to the Xcode Command Line Tools. A run of it without those
# tools opens a window that asks to install them. usable_python() below tests
# for the tools with xcode-select -p, which opens nothing. It looks in the two
# Homebrew prefixes by path, because the PATH of a hook holds neither.
#
# It writes only the marker files and the saved Python path, changes no
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

private_python() {
    # The Python that install_python_uv.sh put in the data folder of the
    # plugin. The PATH search never finds it. That script saves its path, and
    # this finds it again when the saved path is gone. The folder of the minor
    # version, such as cpython-3.13-macos-x86_64-none, sorts before the folder
    # of its patch release and is tried first.
    [ "$OS" = Darwin ] && [ -n "${CLAUDE_PLUGIN_DATA:-}" ] || return 0
    for py in "$CLAUDE_PLUGIN_DATA"/python/cpython-3.*-macos-*-none/bin/python3; do
        [ -f "$py" ] && [ -x "$py" ] || continue
        probe "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || continue
        printf '%s\n' "$py"
        return 0
    done
}

usable_python() {
    # True when the search finds a Python 3.10 or newer. The plugin installs
    # Pillow 12, which has no wheel for an older one, and the Python of the
    # Xcode tools is 3.9. The function saves the path under the home folder,
    # where a project cannot write. Each hook starts that Python first, and
    # an old Python earlier on PATH never runs a hook.
    FOUND=$(find_python)
    [ -n "$FOUND" ] || FOUND=$(private_python)
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
            && mv -f "$state/python-path.$$" "$state/python-path" \
            || rm -f "$state/python-path.$$" ) 2>/dev/null
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

# On macOS, install_python_uv.sh installs Python 3.13 and the packages in its
# own process. The install took about 8 seconds on a home connection, but a slow
# one can take minutes, and session start waits for this hook. Hooks that
# start during the install wait for it in run_hook.sh, up to 45 seconds, so
# the first session packs once the install is done. The script runs only
# with the data folder of the plugin, because the plugin uninstall deletes
# that folder and the Python in it. The running marker is created with
# noclobber, so two sessions that start together run one install. Running
# markers older than 60 minutes come from installs that did not end, such
# as one cut by a shutdown, and the next session tries again.
if [ "$OS" = "Darwin" ] && [ -n "${CLAUDE_PLUGIN_DATA:-}" ]; then
    RUNNING="$DATA/python-install-running"
    if [ -f "$RUNNING" ] && [ -n "$(find "$RUNNING" -mmin +60 2>/dev/null)" ]; then
        rm -f "$RUNNING"
    fi
    # DensePack 2.0.4 and older wrote "tried" here after it showed the install
    # commands. That marker does not stop the first uv install.
    [ "$(cat "$TRIED" 2>/dev/null)" != tried ] || rm -f "$TRIED"
    if [ ! -f "$TRIED" ] && ( set -C; printf 'running' > "$RUNNING" ) 2>/dev/null; then
        here=${0%/*}
        [ "$here" != "$0" ] || here=.
        nohup /bin/sh "$here/install_python_uv.sh" "$DATA" </dev/null >/dev/null 2>&1 &
        say "DensePack is installing Python 3.13 in its own folder with uv, because its hooks need Python 3.10 or newer. It needs no password and takes under a minute. DensePack starts packing in this session when the install is done. Until then, reports arrive as plain text."
        exit 0
    fi
    if [ -f "$RUNNING" ]; then
        say "DensePack is still installing Python 3.13 in the background. DensePack starts packing in this session when the install is done. Until then, reports arrive as plain text."
        exit 0
    fi
    # The install ended and no Python works. The log names the step that
    # failed. The path goes into the JSON string only when it contains no
    # double quote and no backslash.
    LOGNOTE="The log is python-install.log in the data folder of the plugin."
    case "$DATA" in
        *\"*|*\\*) ;;
        *) LOGNOTE="The log is $DATA/python-install.log. To let DensePack try again, delete $TRIED ." ;;
    esac
    say "DensePack could not install Python with uv, and it found no Python 3.10 or newer. None of its hooks run, and reports arrive as plain text. $LOGNOTE Or run: brew install python , after installing Homebrew from https://brew.sh , then restart Claude Code."
    exit 0
fi

if [ -f "$TRIED" ]; then
    say "DensePack found no Python 3.10 or newer. None of its hooks run, and reports arrive as plain text. An earlier session showed the install command. Install Python 3.10 or newer, then restart Claude Code."
    exit 0
fi
( printf 'tried' > "$TRIED" ) 2>/dev/null

# No install runs here. On Linux the package managers need sudo. On macOS
# this point is reached only without the data folder of the plugin. The
# message below names the command to run.

# The command to show on screen. macOS gets its own answer, because apt, dnf
# and pacman are Linux package managers and a Mac has none of them. The uv
# route needs no administrator password. The Homebrew installer asks for
# one, and it installs the Xcode Command Line Tools too.
#
# CMD must hold no double quote and no backslash. say() puts it directly
# into a JSON string with printf and escapes nothing. Either character makes
# JSON that Claude Code cannot parse.
if [ "$OS" = "Darwin" ]; then
    CMD="brew install python , after installing Homebrew from https://brew.sh , or install uv from https://docs.astral.sh/uv and then run uv python install --default"
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
