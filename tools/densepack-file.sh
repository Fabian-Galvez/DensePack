#!/bin/sh
# ---------------------------------------------------------------------
#  DensePack on a right-click, for Linux.
#
#  This is the Linux twin of the Windows right-click entry. The Windows
#  installer writes a registry command that runs densepack.py on the file
#  you clicked. Linux has no registry, so the same job needs a small
#  script that a file manager can run, and this is that script.
#
#  install-densepack.sh puts a copy of this file in the file manager's
#  scripts folder under the name "DensePack it", and points
#  densepack.desktop at the same copy. Both routes end here, so the menu
#  and the Open With entry can never disagree.
#
#  The menu holds one item, DensePack it. It runs densepack.py with no size,
#  so the packer draws the plugin's one page: 17 px unless DENSEPACK_CODE_PX
#  names another number.
#
#  Each image lands beside the file it came from, named
#  <file>.densepack-1.png. That is the name the Windows entry writes too.
#
#  To remove this by hand, delete this file and
#  ~/.local/share/applications/densepack.desktop.
# ---------------------------------------------------------------------
set -eu

# install-densepack.sh rewrites the next line with the full path of
# densepack.py. The placeholder is not a file, so an unsubstituted copy falls
# through to the packer beside it and this file runs straight from a checkout.
# The same fallback covers an installed copy whose repo has since moved.
# The placeholder is written once on purpose: the installer replaces the first
# match on every line it reads, so a second copy of it would be rewritten too.
PACKER='@PACKER@'
[ -f "$PACKER" ] || PACKER="$(dirname "$0")/densepack.py"

# A file manager gives the script no terminal, so a message has to reach the
# desktop's own notification tray. echo is the fallback for a run from a
# terminal, which is how the tests run it.
say() {
  if [ -n "${DENSEPACK_NO_NOTIFY:-}" ] || ! command -v notify-send >/dev/null 2>&1; then
    echo "$1"
  else
    notify-send "DensePack" "$1"
  fi
}

# Nautilus, Nemo and Caja pass nothing on the command line. Each one puts the
# selected paths in its own variable, one path per line. A desktop entry
# passes the paths as arguments instead, which is the "$#" case below.
if [ "$#" -eq 0 ]; then
  paths="${NAUTILUS_SCRIPT_SELECTED_FILE_PATHS:-}"
  [ -n "$paths" ] || paths="${NEMO_SCRIPT_SELECTED_FILE_PATHS:-}"
  [ -n "$paths" ] || paths="${CAJA_SCRIPT_SELECTED_FILE_PATHS:-}"
  oldifs=$IFS
  IFS='
'
  set -f          # a path holding * must not turn into a list of files
  set -- $paths
  set +f
  IFS=$oldifs
fi

if [ "$#" -eq 0 ]; then
  say "Select a file first. DensePack packs the files you have selected."
  exit 1
fi

# Ubuntu 24.04 and later carry python3 and no python at all.
py=python3
command -v python3 >/dev/null 2>&1 || py=python
if ! command -v "$py" >/dev/null 2>&1; then
  say "Python is not on your PATH. Install Python 3, then try again."
  exit 1
fi

if [ ! -f "$PACKER" ]; then
  say "Cannot find densepack.py at $PACKER. Run install-densepack.sh again."
  exit 1
fi

# The packer prints the image paths on stdout and its own summary, the
# character count and the saving, on stderr. Both go into the notification,
# because the summary is the part worth reading.
packed=0
report=""
for f do
  if [ ! -f "$f" ]; then
    continue
  fi
  out=$("$py" "$PACKER" "$f" --out "$f.densepack" 2>&1) || {
    say "Packing $f failed. $out"
    exit 1
  }
  packed=$((packed + 1))
  report="$report$out
"
done

if [ "$packed" -eq 0 ]; then
  say "Nothing was packed. DensePack reads files, not folders."
  exit 1
fi

say "$packed packed.
$report"
