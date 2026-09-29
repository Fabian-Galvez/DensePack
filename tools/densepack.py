"""Pack a text file into the DensePack plugin's page, from the shell.

The script reads text and writes PNG pages. It uses the plugin's renderer,
plugin/scripts/codepack.py, at the plugin's one size. The Windows right-click
entry, the hotkeys, the Linux menu and the macOS Quick Action all run this
file. The script writes page N to <out>-N.png. The stem is "packed" in the
working folder unless --out names another stem.

    python densepack.py report.md
    python densepack.py report.md --out packed
    some-command | python densepack.py - --out packed

The page is the same for all models. The glyph size is common.CODE_PX. It is
17 unless DENSEPACK_CODE_PX names another number. DENSEPACK_STYLE names a JSON
file of style overrides. The plugin reads the two variables the same way.
--size N sets DENSEPACK_CODE_PX for one run.
"""

import argparse
import os
import re
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:                       # pragma: no cover
    # The plugin installs Pillow into its own private folder. This tool runs
    # in a plain terminal, where no step installs Pillow. The tool prints the
    # install command in place of a traceback.
    sys.exit('DensePack needs Pillow to make an image. Pillow is not installed.\n'
             'Install it with:  python -m pip install pillow')

PATCH = 28         # one visual token is one 28 by 28 patch

# Characters per token. This file cannot import the plugin's densepack.py,
# because this file has the same module name. The code reads the number
# from the text of that file. The number is not typed here, and for that
# reason no second copy can differ from the plugin's value.
_SOURCE = Path(__file__).resolve().parent.parent / "plugin" / "scripts" / "densepack.py"
try:
    _match = re.search(r"(?m)^CHARS_PER_TOKEN = ([0-9.]+)$",
                       _SOURCE.read_text(encoding="utf-8"))
except OSError:
    _match = None
if not _match:
    raise SystemExit(
        "densepack.py cannot read CHARS_PER_TOKEN from %s. That file holds the "
        "one copy of the divisor. This tool does not guess it." % _SOURCE)
CHARS_PER_TOKEN = float(_match.group(1))


def patches(width, height):
    return -(-width // PATCH) * -(-height // PATCH)


def code_renderer():
    """Return the plugin's renderer and its shared helpers. One renderer packs
    all pages for the plugin, the right-click menu and the command line.

    The function imports them here and not at the top, because common.py
    reads DENSEPACK_CODE_PX at import and --size sets it first."""
    scripts = Path(__file__).resolve().parent.parent / "plugin" / "scripts"
    if not (scripts / "codepack.py").is_file():
        sys.exit("The plugin scripts are missing beside this tool: %s" % scripts)
    sys.path.insert(0, str(scripts))
    import codepack
    import common
    return codepack, common


def main():
    ap = argparse.ArgumentParser(
        description="Pack text into the page that the DensePack plugin makes. "
                    "The size is the same for all models.")
    ap.add_argument("input", help="text file to pack, or - for stdin")
    ap.add_argument("--size", type=int, default=None,
                    help="glyph size in px. Sets DENSEPACK_CODE_PX for this run. "
                         "Without it, the tool uses the plugin's one size, "
                         "which is DENSEPACK_CODE_PX or 17")
    # Older menu entries pass --pick. The page has one size, and --pick
    # changes nothing. The parser accepts it to prevent an error in those
    # entries.
    ap.add_argument("--pick", action="store_true",
                    help="changes nothing. Older menu entries pass it")
    ap.add_argument("--out", default="packed", help="output name stem")
    ap.add_argument("--quiet", action="store_true", help="print only the image paths")
    args = ap.parse_args()

    if args.size is not None:
        os.environ["DENSEPACK_CODE_PX"] = str(args.size)

    raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(
        encoding="utf-8", errors="replace")
    if not raw.strip():
        raise SystemExit("Nothing to pack.")

    codepack, common = code_renderer()
    import freetype_glyph
    if freetype_glyph.freetype is None:
        # Without freetype-py, Pillow renders the glyphs and the image is
        # larger, for example 784 by 1260 in place of 784 by 896.
        print("freetype-py is not installed. This image is larger than the plugin's.\n"
              "Install it with:  python3 -m pip install --user freetype-py\n"
              "(on Debian and Ubuntu, add --break-system-packages)", file=sys.stderr)
    size = common.code_size()
    suffix = Path(args.input).suffix.lower() if args.input != "-" else ""
    title = Path(args.input).name if args.input != "-" else "stdin"
    try:
        written, _target, _line_h = codepack.pack_code(
            raw, size, args.out, python=suffix == ".py", legend=None,
            reader=None, title=title)
    except codepack.FontCannotDraw:
        raise SystemExit("The font has no glyphs for most of this file's characters, such as "
                         "Chinese, Japanese or Korean text. Read it as text.")

    # The tool reads the size from the file on disk, because the model gets
    # that file.
    pages = []
    for path, _w, _h in written:
        with Image.open(path) as im:
            pages.append((str(path), im.width, im.height))

    for path, _w, _h in pages:
        print(path)

    if args.quiet:
        return

    text_tokens = len(raw) / CHARS_PER_TOKEN
    image_tokens = sum(patches(w, h) for _p, w, h in pages)
    if args.size is not None:
        origin = "from --size"
    elif os.environ.get("DENSEPACK_CODE_PX"):
        origin = "from DENSEPACK_CODE_PX"
    else:
        origin = "the plugin's default"
    saving = (1 - image_tokens / text_tokens) * 100 if text_tokens else 0
    out = sys.stderr
    print("", file=out)
    print("characters   %d" % len(raw), file=out)
    print("glyph        %d px, %s" % (size, origin), file=out)
    print("pages        %d, %s" % (len(pages), ", ".join(
        "%d by %d" % (w, h) for _p, w, h in pages)), file=out)
    print("as text      %d tokens" % round(text_tokens), file=out)
    print("as image     %d tokens" % image_tokens, file=out)
    if saving > 0:
        print("saving       %.0f percent" % saving, file=out)
    else:
        print("WORSE by     %.0f percent. Send the text instead." % -saving, file=out)


if __name__ == "__main__":
    main()
