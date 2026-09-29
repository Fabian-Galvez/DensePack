#!/bin/sh
# ---------------------------------------------------------------------
#  Remove the DensePack right-click tool on Linux.
#
#  This script removes what install-densepack.sh wrote in your home folder,
#  which is the packer script, the file manager menu items and the Open
#  With entry.
#  Pillow, freetype-py and NumPy stay, because other programs can use them.
#  The DensePack folder you downloaded also stays.
# ---------------------------------------------------------------------
set -u

data="${XDG_DATA_HOME:-$HOME/.local/share}"
removed=0
for path in \
  "$data/densepack" \
  "$data/applications/densepack.desktop" \
  "$data/nautilus/scripts/DensePack it" \
  "$data/nemo/scripts/DensePack it" \
  "${XDG_CONFIG_HOME:-$HOME/.config}/caja/scripts/DensePack it"
do
  if [ -e "$path" ]; then
    rm -rf "$path"
    echo "removed           $path"
    removed=$((removed + 1))
  fi
done

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$data/applications" >/dev/null 2>&1 || true
fi

if [ "$removed" -eq 0 ]; then
  echo "Nothing to remove. The right-click tool is not installed in your home folder."
else
  echo
  echo "Done. Pillow, freetype-py and NumPy stay installed."
fi
