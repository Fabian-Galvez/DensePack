#!/bin/sh
# Installs a Python of DensePack's own on macOS with uv. ensure_python.sh
# starts this script in the background when session start finds no Python
# 3.10 or newer. It is the macOS version of the winget install in
# ensure_python.ps1.
#
# All files go into the data folder of the plugin, the one argument. The
# script adds nothing to PATH, changes no setting and needs no administrator
# password. Your own Python, Homebrew and ~/.local/bin stay as they are. The
# plugin uninstall deletes the data folder, and this Python with it.
#
# The uv version is pinned. The script checks the uv download against the
# SHA-256 below before it runs uv. uv then checks the Python download against
# the hash that uv ships with.
#
# The steps go to python-install.log in the data folder. When the script
# ends, it writes the result to python-install-tried and removes
# python-install-running. On success, it saves the Python path where
# run_hook.sh reads it, so the hooks of the next session find it before
# ensure_python.sh runs.

DATA=$1
case "$DATA" in
    /*) [ -d "$DATA" ] || exit 1 ;;
    *) exit 1 ;;
esac

UV_VERSION=0.13.5
PY_VERSION=3.13
# One uv build for each Mac processor. The hashes are the .sha256 files of
# the uv release on GitHub. Macs with Apple silicon that run this shell
# under Rosetta report x86_64, and the Intel build runs there too.
case "$(uname -m 2>/dev/null)" in
    arm64|aarch64)
        TRIPLE=aarch64-apple-darwin
        SHA=743f85035a1996ecb350659e01cd9faea9709829be09b1b4b03c73eaf3c9cd73 ;;
    x86_64)
        TRIPLE=x86_64-apple-darwin
        SHA=b0f52b0e3945b4107d89024ea38e625683011fbfc05a0d98f9fa2d6dcee28c66 ;;
    *)
        TRIPLE= ;;
esac

LOG="$DATA/python-install.log"
TRIED="$DATA/python-install-tried"
RUNNING="$DATA/python-install-running"
UVDIR="$DATA/uv"

log() {
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null)" "$1" >> "$LOG"
}

# The result goes to the tried marker. ensure_python.sh shows the install
# command only after a failed result, and the log names the failed step.
finish() {
    log "$1"
    printf '%s\n' "$1" > "$TRIED"
    rm -rf "$UVDIR" "$DATA/uv-cache"
    rm -f "$RUNNING"
    exit 0
}

: > "$LOG"
[ -n "$TRIPLE" ] || finish "failed: uv has no build for $(uname -m)"

URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$TRIPLE.tar.gz"
TARBALL="$UVDIR/uv-$TRIPLE.tar.gz"
rm -rf "$UVDIR"
mkdir -p "$UVDIR" || finish "failed: cannot make $UVDIR"
log "download $URL"
# The full paths, because the PATH of a hook can lack /usr/bin. All of these
# tools ship with macOS and need no Xcode Command Line Tools.
/usr/bin/curl -fsSL --retry 2 --connect-timeout 30 --max-time 900 \
        -o "$TARBALL" "$URL" >> "$LOG" 2>&1 \
    || finish "failed: uv download"
got=$(/usr/bin/shasum -a 256 "$TARBALL" 2>> "$LOG")
got=${got%% *}
[ "$got" = "$SHA" ] || finish "failed: uv checksum $got"
/usr/bin/tar -xzf "$TARBALL" -C "$UVDIR" >> "$LOG" 2>&1 \
    || finish "failed: uv unpack"
UV="$UVDIR/uv-$TRIPLE/uv"
[ -x "$UV" ] || finish "failed: no uv in the download"

# --no-bin keeps uv out of ~/.local/bin. UV_NO_CONFIG skips a uv.toml in
# your home folder. The working folder is the data folder, so the
# .python-version file of a project never chooses the version.
log "uv python install $PY_VERSION"
( cd "$DATA" && UV_PYTHON_INSTALL_DIR="$DATA/python" UV_CACHE_DIR="$DATA/uv-cache" \
    UV_NO_CONFIG=1 "$UV" python install "$PY_VERSION" --no-bin ) >> "$LOG" 2>&1 \
    || finish "failed: uv python install"
# uv names the folder of the minor version, such as cpython-3.13-macos-
# x86_64-none, as a link to the newest patch release. The saved path then
# stays valid after a patch update.
PY=$(cd "$DATA" && UV_PYTHON_INSTALL_DIR="$DATA/python" UV_CACHE_DIR="$DATA/uv-cache" \
    UV_NO_CONFIG=1 "$UV" python find --managed-python "$PY_VERSION" 2>> "$LOG")
case "$PY" in
    /*) ;;
    *) finish "failed: uv found no Python $PY_VERSION after the install" ;;
esac
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >> "$LOG" 2>&1 \
    || finish "failed: $PY does not start"

# Pillow, freetype-py and NumPy go into pylibs now, with the same pip command
# and floors as install_pillow() in bootstrap.py. The hooks of this session
# then pack with them, and no restart is needed. pip runs from pylibs, where a
# project cannot plant a module. When this fails, bootstrap.py tries again at
# the next session start, so the Python path is still saved.
mkdir -p "$DATA/pylibs"
log "pip install pillow freetype-py numpy"
( cd "$DATA/pylibs" && "$PY" -m pip install --quiet --upgrade --only-binary :all: \
    --target "$DATA/pylibs" "pillow>=12" "freetype-py>=2" "numpy>=2" ) >> "$LOG" 2>&1 \
    || log "pip install failed, bootstrap.py tries again at the next session start"

if [ -n "${HOME:-}" ]; then
    state="$HOME/.claude/densepack-state"
    ( mkdir -p "$state" \
        && printf '%s\n' "$PY" > "$state/python-path.$$" \
        && mv -f "$state/python-path.$$" "$state/python-path" \
        || rm -f "$state/python-path.$$" ) 2>/dev/null
fi
finish "ok: $PY"
