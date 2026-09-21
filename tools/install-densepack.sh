#!/bin/sh
# ---------------------------------------------------------------------
#  Install the DensePack right-click menu on Linux.
#
#    sh install-densepack.sh
#
#  What it does, in order:
#
#    1  finds a Python 3 and makes sure Pillow is there, because Pillow
#       draws the image
#    2  copies densepack-file.sh to ~/.local/share/densepack/, with the
#       full path of densepack.py written into it
#    3  copies that same file into the scripts folder of every file
#       manager it finds, under the name "DensePack it"
#    4  writes densepack.desktop into ~/.local/share/applications/, which
#       gives the Open With entry, one item, no size
#    5  prints every path it wrote and what each one shows
#
#  It writes nothing outside your home folder and asks for no password.
#  To remove it, delete the paths the last block prints.
#
#  The Windows twin of this file is install-densepack.ps1.
# ---------------------------------------------------------------------
set -eu

# CDPATH is cleared, or cd could pick a folder of the same name elsewhere
# and install from that copy.
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
packer="$here/densepack.py"
src_script="$here/densepack-file.sh"
src_desktop="$here/densepack.desktop"
icon="$here/../icon/DensePack-icon.svg"
if [ -f "$icon" ]; then
  icon=$(cd "$here/../icon" && pwd)/DensePack-icon.svg
else
  icon="text-x-generic"
fi

for f in "$packer" "$src_script" "$src_desktop"; do
  if [ ! -f "$f" ]; then
    echo "Missing $f. Run this script from the repo's tools folder."
    exit 1
  fi
done

# The paths go into the copies through sed, and sed needs one character that
# the paths do not contain. | is that character everywhere except a path that
# holds one, which is why this stops rather than writing a broken file.
case "$here$icon" in
  *'|'*|*"'"*|*'
'*)
    echo "This folder's path holds a | or ' character or a line break, which the installer cannot"
    echo "write into a script. Move the repo somewhere without one."
    exit 1
    ;;
esac

# ---------------------------------------------------------------- python
# Ubuntu 24.04 and later carry python3 and no python at all.
py=python3
command -v python3 >/dev/null 2>&1 || py=python
if ! command -v "$py" >/dev/null 2>&1; then
  echo "Python is not on your PATH. Install Python 3, then run this again."
  exit 1
fi
echo "using $("$py" -c 'import sys; sys.stdout.write(sys.executable)')"

have_pillow() {
  "$py" -c 'import importlib.util,sys; sys.stdout.write("yes" if importlib.util.find_spec("PIL") else "no")'
}
if [ "$(have_pillow)" != "yes" ]; then
  echo "installing Pillow"
  # --user fails on Debian and Ubuntu with a PEP 668 error, so a failure here
  # is expected on those and the message below names the two routes that work.
  "$py" -m pip install --quiet --user --only-binary :all: "pillow>=12" >/dev/null 2>&1 || true
fi
if [ "$(have_pillow)" != "yes" ]; then
  echo "Pillow did not install. Your distribution blocks pip from writing"
  echo "into the system Python. Run one of these, then run this again:"
  echo "    sudo apt install python3-pil"
  echo "    $py -m pip install --break-system-packages pillow"
  exit 1
fi
echo "Pillow ready"

# freetype-py draws the glyphs. Without it the image falls back to Pillow and
# differs from the plugin's image.
have_freetype() {
  "$py" -c 'import importlib.util,sys; sys.stdout.write("yes" if importlib.util.find_spec("freetype") else "no")'
}
if [ "$(have_freetype)" != "yes" ]; then
  echo "installing freetype-py"
  "$py" -m pip install --quiet --user --only-binary :all: "freetype-py>=2" >/dev/null 2>&1 || true
fi
if [ "$(have_freetype)" != "yes" ]; then
  echo "freetype-py did not install. Run this, then run this again:"
  echo "    $py -m pip install --break-system-packages freetype-py"
  exit 1
fi
echo "freetype-py ready"

# NumPy blends each glyph into the image.
have_numpy() {
  "$py" -c 'import importlib.util,sys; sys.stdout.write("yes" if importlib.util.find_spec("numpy") else "no")'
}
if [ "$(have_numpy)" != "yes" ]; then
  echo "installing numpy"
  "$py" -m pip install --quiet --user --only-binary :all: "numpy>=2" >/dev/null 2>&1 || true
fi
if [ "$(have_numpy)" != "yes" ]; then
  echo "numpy did not install. Run this, then run this again:"
  echo "    $py -m pip install --break-system-packages numpy"
  exit 1
fi
echo "numpy ready"

# ---------------------------------------------------------------- the script
data="${XDG_DATA_HOME:-$HOME/.local/share}"
case "$data" in
  *'
'*)
    echo "The data folder path holds a line break, which a desktop entry cannot hold."
    exit 1
    ;;
esac
home_dir="$data/densepack"
mkdir -p "$home_dir"
script="$home_dir/densepack-file.sh"
# sed reads & and | in a replacement as commands, so a path holding either is escaped.
sed_escape() { printf '%s' "$1" | sed -e 's/[&|\\]/\\&/g'; }
sed "s|@PACKER@|$(sed_escape "$packer")|" "$src_script" >"$script"
chmod 755 "$script"
echo "packer            $packer"
echo "script            $script"

# ---------------------------------------------------------------- the menus
# Nautilus, Nemo and Caja all read a scripts folder and show one menu item per
# file in it, named after the file. Each looks in its own folder. Thunar,
# Dolphin and PCManFM read the desktop entry below instead.
menus=0
for pair in \
  "nautilus:$data/nautilus/scripts" \
  "nemo:$data/nemo/scripts" \
  "caja:${XDG_CONFIG_HOME:-$HOME/.config}/caja/scripts"
do
  manager=${pair%%:*}
  folder=${pair#*:}
  if ! command -v "$manager" >/dev/null 2>&1; then
    echo "$manager            not installed, skipped"
    continue
  fi
  mkdir -p "$folder"
  cp "$script" "$folder/DensePack it"
  chmod 755 "$folder/DensePack it"
  echo "$manager            right-click a file, Scripts, DensePack it -> $folder/DensePack it"
  menus=$((menus + 1))
done

# ---------------------------------------------------------------- Open With
apps="$data/applications"
mkdir -p "$apps"
desktop="$apps/densepack.desktop"
# The Desktop Entry format reads % as a field code, so a % in the path doubles.
# Inside the quoted Exec argument a \ " ` or $ takes a backslash, and the file
# format then doubles every backslash once more.
exec_path=$(printf '%s' "$script" | sed -e 's/\\/\\\\\\\\/g' -e 's/["`$]/\\\\&/g' -e 's/%/%%/g')
# Icon is a plain string value, where only the backslash takes an escape.
icon_path=$(printf '%s' "$icon" | sed -e 's/\\/\\\\/g')
sed -e "s|@SCRIPT@|$(sed_escape "$exec_path")|g" -e "s|@ICON@|$(sed_escape "$icon_path")|g" "$src_desktop" >"$desktop"
chmod 644 "$desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$apps" >/dev/null 2>&1 || true
fi
echo "desktop entry     $desktop"
echo "                  right-click a file, Open With, DensePack it. The"
echo "                  one item; the plugin draws one size for every model."

if [ "$menus" -eq 0 ]; then
  echo
  echo "No file manager with a scripts folder is installed here, so the"
  echo "desktop entry is the only menu written. It is the one Thunar,"
  echo "Dolphin and PCManFM read, and it is enough on its own."
fi

echo
echo "Done. Nautilus and Nemo read their scripts folder again after"
echo "'nautilus -q' or 'nemo -q', or after you log out and back in."
echo
echo "To remove all of it, run: sh \"$here/uninstall-densepack.sh\""
echo "It deletes these:"
echo "    $home_dir"
echo "    $desktop"
for pair in \
  "nautilus:$data/nautilus/scripts" \
  "nemo:$data/nemo/scripts" \
  "caja:${XDG_CONFIG_HOME:-$HOME/.config}/caja/scripts"
do
  folder=${pair#*:}
  if [ -f "$folder/DensePack it" ]; then
    echo "    $folder/DensePack it"
  fi
done
