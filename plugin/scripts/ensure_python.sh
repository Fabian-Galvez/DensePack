#!/bin/sh
# Tell the user how to get Python on Linux and macOS when the machine has none,
# so the plugin's hooks can run. SessionStart only.
#
# Every other script in this folder is Python, so none of them can speak on a
# machine with no Python: the hook would never start. /bin/sh is on every Linux
# and macOS, so this one runs where they cannot.
#
# It installs Python itself only through Homebrew, which needs no
# administrator rights. apt, dnf and pacman all need sudo, and sudo cannot ask
# for a password inside a hook, so on those the script prints the install
# command instead of failing silently.
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

# The Homebrew prefixes. Apple silicon installs under /opt/homebrew, Intel
# under /usr/local. A hook does not run in a login shell, so its PATH holds
# neither one on many Macs, and command -v would miss a Python that is there.
BREW_PY_ARM="/opt/homebrew/bin/python3"
BREW_PY_INTEL="/usr/local/bin/python3"

usable_python() {
    # True when this machine has a Python that actually starts.
    #
    # On macOS, /usr/bin/python3 is not a Python. Apple ships it as a
    # placeholder file that belongs to the Xcode Command Line Tools and holds
    # no interpreter. Run it while those tools are absent and it opens the
    # "Install the command line developer tools" window. Both
    # command -v python3 and [ -x /usr/bin/python3 ] succeed against that
    # placeholder, so the check that works on Linux reports a Python that
    # cannot run a hook, and the user gets a window nobody asked for.
    #
    # xcode-select -p prints the developer directory and exits non-zero when
    # the tools are absent. It never opens a window, so it is safe to call.
    if [ -x "$BREW_PY_ARM" ] || [ -x "$BREW_PY_INTEL" ]; then
        return 0
    fi
    if [ "$OS" = "Darwin" ]; then
        FOUND=$(command -v python3 2>/dev/null)
        if [ -n "$FOUND" ] && [ "$FOUND" != "/usr/bin/python3" ]; then
            return 0
        fi
        if [ -n "$FOUND" ] && xcode-select -p >/dev/null 2>&1; then
            return 0
        fi
        return 1
    fi
    if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

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
    say "DensePack found no Python, so none of its hooks run and reports arrive as plain text. It already tried once on this machine. Install Python 3.8 or newer, then restart Claude Code."
    exit 0
fi
( printf 'tried' > "$TRIED" ) 2>/dev/null

if command -v brew >/dev/null 2>&1; then
    brew install python >/dev/null 2>&1
    # The Homebrew prefix is checked by path as well as through PATH. brew
    # writes python3 into its own bin directory, and this shell's PATH was
    # fixed before that directory held anything.
    if usable_python; then
        # This session's other hooks already started without an interpreter, so
        # they cannot be rescued now. The next session picks the new Python up.
        say "DensePack installed Python through Homebrew, which its hooks need. Restart Claude Code and packing starts working. Nothing was packed this session."
        exit 0
    fi
fi

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
    CMD="your package manager's python3 package"
fi

say "DensePack needs Python 3.8 or newer and this machine has none, so none of its hooks run and reports arrive as plain text. Run: $CMD , then restart Claude Code."
exit 0
