"""Pack a text file into the page the DensePack plugin draws, from the shell.

The job: text in, PNG out, through the plugin's own renderer,
plugin/scripts/codepack.py, at the plugin's one size. The Windows right-click
entry, the hotkeys, the Linux menu and the macOS Quick Action all run this
file. Each page lands at <out>-1.png and up, in the working folder unless
--out names another stem.

    python densepack.py report.md
    python densepack.py report.md --out packed
    some-command | python densepack.py - --out packed

The page is the same page for every model. The glyph size is common.CODE_PX,
17 unless DENSEPACK_CODE_PX names another number, and DENSEPACK_STYLE names a
JSON file of style overrides. The plugin reads both the same way. --size N
sets DENSEPACK_CODE_PX for one run.
"""

import argparse
import os
import re
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:                       # pragma: no cover
    # The PLUGIN installs Pillow into a private folder of its own. This
    # tool runs in a plain terminal, where nothing has done that, so it
    # says which command fixes it instead of showing a traceback.
    sys.exit('DensePack needs Pillow to draw an image, and it is not installed.\n'
             'Install it with:  python -m pip install pillow')

PATCH = 28         # one visual token is one 28 by 28 patch

# Characters per token. This file cannot plainly import the plugin's
# densepack.py, because that is its own module name, so it reads the number
# straight out of that file's text. It is never typed here, so a second
# copy of the literal cannot drift from the plugin.
_SOURCE = Path(__file__).resolve().parent.parent / "plugin" / "scripts" / "densepack.py"
try:
    _match = re.search(r"(?m)^CHARS_PER_TOKEN = ([0-9.]+)$",
                       _SOURCE.read_text(encoding="utf-8"))
except OSError:
    _match = None
if not _match:
    raise SystemExit(
        "densepack.py cannot read CHARS_PER_TOKEN from %s. That file is the "
        "one place the divisor is set; this tool will not guess it." % _SOURCE)
CHARS_PER_TOKEN = float(_match.group(1))


def patches(width, height):
    return -(-width // PATCH) * -(-height // PATCH)


def code_renderer():
    """The plugin's renderer and its shared helpers. One renderer draws every
    page for the plugin, the right-click menu and the command line.

    Imported here and not at the top, because common.py reads
    DENSEPACK_CODE_PX at import and --size sets it first."""
    scripts = Path(__file__).resolve().parent.parent / "plugin" / "scripts"
    if not (scripts / "codepack.py").is_file():
        sys.exit("The plugin scripts are missing beside this tool: %s" % scripts)
    sys.path.insert(0, str(scripts))
    import codepack
    import common
    return codepack, common


def main():
    ap = argparse.ArgumentParser(
        description="Pack text into the page the DensePack plugin draws. "
                    "One size for every model.")
    ap.add_argument("input", help="text file to pack, or - for stdin")
    ap.add_argument("--size", type=int, default=None,
                    help="glyph size in px. Sets DENSEPACK_CODE_PX for this run. "
                         "Without it the plugin's one size is used: "
                         "DENSEPACK_CODE_PX, or 17")
    # Older menu entries pass --pick. The page has one size, so --pick
    # changes nothing. It is accepted so those entries still run.
    ap.add_argument("--pick", action="store_true",
                    help="accepted for older menu entries and changes nothing")
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
        # Without freetype-py, Pillow draws the glyphs and the image grows:
        # 784 by 1260 instead of 784 by 896 on the bench file.
        print("freetype-py is not installed, so this image is larger than the plugin's.\n"
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
        raise SystemExit("The font cannot draw most of this file's characters, such as "
                         "Chinese, Japanese or Korean text. Read it as text.")

    # The size comes from the file on disk, because the file is what the
    # reader gets.
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
