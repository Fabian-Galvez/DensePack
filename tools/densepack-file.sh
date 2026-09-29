#!/bin/sh
# ---------------------------------------------------------------------
#  DensePack on a right-click, for Linux.
#
#  This is the Linux version of the Windows right-click entry. The Windows
#  installer writes a registry command that runs densepack.py on the file
#  you clicked. Linux has no registry. On Linux, a file manager runs this
#  small script to do the same job.
#
#  install-densepack.sh puts a copy of this file in the file manager's
#  scripts folder under the name "DensePack it". It writes the path of the
#  same copy into densepack.desktop. The menu and the Open With entry run
#  the same file and give the same result.
#
#  The menu holds one item, DensePack it. It runs densepack.py with no size.
#  The packer makes the plugin's one page at 17 px unless DENSEPACK_CODE_PX
#  names another number.
#
#  The packer writes each image beside its source file, with the name
#  <file>.densepack-1.png. The Windows entry writes the same name.
#
#  To remove this by hand, delete this file and
#  ~/.local/share/applications/densepack.desktop.
# ---------------------------------------------------------------------
set -eu

# install-densepack.sh rewrites the next line with the full path of
# densepack.py. An unchanged copy keeps the placeholder, which is not a file,
# and then uses the packer beside it. That rule covers a run from a checkout
# and an installed copy whose repo moved after the install. The placeholder
# appears only on the next line, because the installer replaces it on each
# line where it appears.
PACKER='@PACKER@'
[ -f "$PACKER" ] || PACKER="$(dirname "$0")/densepack.py"

# A file manager gives the script no terminal. The script sends each message
# to the desktop notification tray. It uses echo when DENSEPACK_NO_NOTIFY is
# set or notify-send is missing.
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
  set -f          # a path with * must not become a list of files
  set -- $paths
  set +f
  IFS=$oldifs
fi

if [ "$#" -eq 0 ]; then
  say "Select a file first. DensePack packs the selected files."
  exit 1
fi

# Ubuntu 24.04 and later include python3 and no python command.
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
# character count and the saving, on stderr. The script puts the two into the
# notification, because the summary holds the useful facts.
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
  say "DensePack packed nothing. It reads files, not folders."
  exit 1
fi

say "$packed packed.
$report"
