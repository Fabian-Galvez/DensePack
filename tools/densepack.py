"""Pack text into the smallest image Fable can still read.

A port of the browser app in the folder above, so a script, a right-click or an
agent can do the same job with no browser. Same constants, same layout, same
color coding, same downscale check.

    python densepack.py report.md
    python densepack.py report.md --size 12
    python densepack.py report.md --pick
    python densepack.py report.md --out packed
    some-command | python densepack.py - --out packed

Writes packed-1.png and so on, prints one line per file, and prints the token
comparison so the saving is a number rather than a claim.
"""

import argparse
import math
import re
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:                       # pragma: no cover
    import sys
    # The PLUGIN installs Pillow into a private folder of its own. This
    # tool is standalone and runs in a plain terminal, where nothing has
    # done that, so it says which command fixes it instead of showing a
    # traceback.
    sys.exit('DensePack needs Pillow to draw an image, and it is not installed.\n'
             'Install it with:  python -m pip install pillow')

# Fable's real limits, taken from the app. The app follows the resize rule
# Anthropic publishes rather than guessing at it; this file holds only the
# constants that rule produces, not an implementation of it.
# Fable accepts 2576 px on the long edge for a single image, but a request
# holding more than 20 images gets a stricter limit: any dimension over
# 2000 px is shrunk, and shrinking destroys 8 px text. A busy session can
# queue more than 20 packed reports, so every image is built under 2000 on
# both sides. 1988 is 71 patches of 28 px, the largest patch-aligned edge
# under that limit. This rule was set; recorded here 16 August 2026.
EDGE = 1988        # longest side this packer will produce
MAX_TOK = 4784     # most patches Fable accepts per image
CAP_W = 1932       # largest guaranteed-no-downscale canvas
CAP_H = 1932
RATIO = 1.0        # a square uses the token budget best
RISKY = 8          # below this, digits misread even in color. 6px returned "#2___5" for a 5 digit number

# The three measured reading floors, each the smallest size at which that model
# read a packed image with every answer exact. The plugin holds the same three
# numbers in plugin/scripts/common.py as READER_SIZES.
#
#    8 px  Two cold Fable 5 readers, 10 of 10 on 14 August 2026. Opus 5 read
#          1 of 10 here, so it is a Fable 5 choice only. Smallest image.
#   10 px  Two cold Opus 5 readers, 10 of 10 and 12 of 12 on 18 August 2026.
#          Fable 5 reads it too. Sonnet 5 dropped a word at this size.
#   12 px  Sonnet 5, every answer exact on two cold readers. Opus 5 and Fable 5
#          read it more easily than the sizes they were scored at. Largest image.
#
# 9 px and 11 px are not offered. They sit between two floors and neither model
# read either one with every answer exact.
READER_SIZES = (
    (8, "Fable 5, 8 px, smallest image"),
    (10, "Opus 5, 10 px, read by Opus 5 and Fable 5"),
    (12, "Sonnet 5, 12 px, read by all three"),
)

# The size a run with no size chosen falls back to. Opus 5 and Fable 5 both read
# it exactly, so it is the safest single answer when the reader is unknown.
DEFAULT_SIZE = 10

PATCH = 28         # one visual token is one 28 by 28 patch
PAD = 2
# Characters per token. This file is a standalone port and cannot plainly
# import the plugin's densepack.py, because that is its own module name, so
# it reads the number straight out of that file's text instead. It is never
# typed here: a second copy of the literal is what went stale before, and a
# quiet fallback value would be that same second copy under another name.
# The measurement behind the number is recorded beside it in the plugin file:
# 31 August 2026, Anthropic's count_tokens endpoint, 92 archived packed
# source texts, 860,637 characters against 357,951 counted tokens.
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

# Color coding. A misread character is worse than a missing one, so the classes
# that look alike at small sizes are pulled apart by color.
PALETTE = {"num": (0, 51, 204), "sym": (176, 0, 32), "nl": (0, 122, 47), "punct": (122, 0, 184)}

# Shape-confusion pairs. Each of these would otherwise share one color with the
# character it is most often mistaken for.
CONFUSION = {":": "nl", ",": "punct", "`": "punct", "'": "num", "|": "num"}

NL_MARK = "\u00b6"

REGULAR = [r"C:\Windows\Fonts\consola.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
BOLD = [r"C:\Windows\Fonts\consolab.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"]



# What has to survive character for character. A token of 8 or more that mixes
# letters with digits, optionally joined by hyphen, underscore, dot or slash,
# or a number written in comma groups. That is an agent id, a hash, a commit, a
# session id, a file name and a token count.
#
# A plain English word never mixes letters with digits, so prose is untouched.
# Measured 25 August 2026 over 42 real agent reports, 362,319 characters: this
# marks 0.96 per cent of them, and the image grows 1.20 per cent.
IDENT_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-_./][A-Za-z0-9]+)*")
IDENT_NUMBER = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+")

# The size an identifier is drawn at, when one is drawn at all. Zero means the
# prose size, which is what ships: lift_identifiers() takes every identifier
# out of the image and sends its value as text, so nothing is left to enlarge.
#
# Drawing them at 12 px was measured on 25 August 2026 and it works, partly. It
# took Fable 5 from 0-to-4 of 5 up to 4, 4, 4 of 5 and Opus 5 from 2-to-3 up to
# 4 of 5, for 4.54 per cent more pixels. Every failure that remained was the
# same string in the same place. Set this to 12 to turn that back on; the code
# that reads it is still here.
IDENT_PX = 0


def _is_identifier(token):
    body = re.sub(r"[-_./]", "", token)
    if len(body) < 8:
        return False
    return (any(c.isdigit() for c in body)
            and any(c.isalpha() for c in body))


def big_mask(text):
    """One flag per character: True where it belongs to an identifier."""
    big = [False] * len(text)
    for m in IDENT_TOKEN.finditer(text):
        if _is_identifier(m.group(0)):
            for i in range(m.start(), m.end()):
                big[i] = True
    for m in IDENT_NUMBER.finditer(text):
        for i in range(m.start(), m.end()):
            big[i] = True
    return big



def lift_identifiers(text, start=1):
    """Replace every identifier with a short tag and return the values.

    Returns (tagged_text, legend), where legend is a list of (tag, value).
    An identifier is what big_mask marks: 8 or more characters mixing letters
    with digits, joined by hyphen, underscore, dot or slash, or a number in
    comma groups. A value that never enters the image cannot be misread, which
    is the whole point: three Fable agents and one Opus agent read an enlarged
    identifier back wrong in the same place on 25 August 2026.

    The same value appearing twice takes the same tag, so a report naming one
    agent id ten times pays for it once.
    """
    mask = big_mask(text)
    out = []
    legend = []
    seen = {}
    i = 0
    n = start
    while i < len(text):
        if not mask[i]:
            out.append(text[i])
            i += 1
            continue
        j = i
        while j < len(text) and mask[j]:
            j += 1
        value = text[i:j]
        if value in seen:
            out.append(seen[value])
        else:
            tag = "[#%d]" % n
            seen[value] = tag
            legend.append((tag, value))
            out.append(tag)
            n += 1
        i = j
    return "".join(out), legend


def legend_text(legend):
    """The values, as one plain text block to send beside the image.

    Empty when nothing was lifted, so a report with no identifier carries no
    extra line at all.
    """
    if not legend:
        return ""
    rows = ["The image shows a tag where each of these values stands. The "
            "values are here as text because a long run of letters and digits "
            "does not survive being drawn small, and these have to be exact."]
    for tag, value in legend:
        rows.append("%s = %s" % (tag, value))
    return "\n".join(rows)


def patches(width, height):
    return -(-width // PATCH) * -(-height // PATCH)


def no_downscale(width, height):
    """True when Fable's API would leave the image at the size it was drawn."""
    return (-(-width // PATCH) * PATCH <= EDGE
            and -(-height // PATCH) * PATCH <= EDGE
            and patches(width, height) <= MAX_TOK)


def load(paths, size):
    for path in paths:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def flatten(raw, mark=NL_MARK):
    """Collapse the text to one flowing string, with line breaks kept as a marker.

    This is what makes the packing dense. Real line breaks leave ragged right edges,
    and the blank pixels beside a short line cost exactly as many tokens as inked
    ones. Marking the break instead lets every line fill the full width.
    """
    lines = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        piece = " ".join(line.split())
        if piece:
            lines.append(piece)
    return mark.join(lines)


def classify(ch, colors=True):
    """Color and weight for one character. Returns (rgb, bold)."""
    if not colors:
        return (0, 0, 0), False
    if ch == NL_MARK:
        return PALETTE["nl"], True
    if ch.isdigit():
        return PALETTE["num"], False
    if ch != " " and not ch.isalnum():
        alt = CONFUSION.get(ch)
        return PALETTE[alt] if alt else PALETTE["sym"], True
    return (0, 0, 0), False


def pack(text, size, out_stem, spacing=1.0, colors=True):
    # Flatten here, not in the caller. A line break the font cannot draw
    # vanishes, and the page then runs together with nothing marking where a
    # line ended. Two of the five callers did not flatten before 25 August
    # 2026, and one of them was the right-click tool, so every file a person
    # packed that way lost its line structure. flatten() on text that is
    # already flat finds no line break and changes nothing, so calling it
    # twice is safe and the callers that already do are left alone.
    text = flatten(text)
    big = big_mask(text)
    ident_px = max(size, IDENT_PX)
    regular = load(REGULAR, size)
    bold = load(BOLD, size)
    big_regular = load(REGULAR, ident_px)
    big_bold = load(BOLD, ident_px)
    line_h = max(1, round(size * spacing * 1.2))
    big_line_h = max(1, round(ident_px * spacing * 1.2))

    widths = {}

    def face(is_big, is_bold):
        if is_big:
            return big_bold if is_bold else big_regular
        return bold if is_bold else regular

    def char_w(ch, is_bold, is_big=False):
        key = (ch, is_bold, is_big)
        if key not in widths:
            widths[key] = face(is_big, is_bold).getlength(ch)
        return widths[key]

    def measure(pairs):
        """Width of a run of (character, big) pairs."""
        total = 0.0
        for ch, b in pairs:
            _c, bold_flag = classify(ch, colors)
            total += char_w(ch, bold_flag, b)
        return total

    def height_of(pairs):
        """A line takes the height of the tallest thing on it."""
        return big_line_h if any(b for _c, b in pairs) else line_h

    pairs = list(zip(text, big))

    # Aim for a square. A square spends the patch budget most efficiently.
    max_text_w = CAP_W - 2 * PAD
    total_w = measure(pairs)
    target = math.sqrt(total_w * line_h * RATIO) if total_w else 180
    target = min(max(target, 180), max_text_w)

    # The API pads every image up to whole 28 px patches and charges for the padding
    # either way, so widening to the next boundary is free room, never a cost.
    grid_w = (max_text_w + 2 * PAD) // PATCH * PATCH - 2 * PAD
    snapped = -(-int(target + 2 * PAD) // PATCH) * PATCH - 2 * PAD
    if snapped <= grid_w and snapped <= max_text_w:
        target = snapped

    # Greedy wrap on spaces, splitting any word too long to fit. A line is a
    # list of (character, big) pairs, not a string, because a string cannot
    # carry the flag that says which characters are drawn at the bigger size.
    words, word = [], []
    for pair in pairs:
        if pair[0] == " ":
            words.append(word)
            word = []
        else:
            word.append(pair)
    words.append(word)

    SPACE = [(" ", False)]
    lines, cur = [], []
    for word in words:
        while measure(word) > target:
            lo, hi, fit = 1, len(word), 1
            while lo <= hi:
                mid = (lo + hi) // 2
                if measure(word[:mid]) <= target:
                    fit, lo = mid, mid + 1
                else:
                    hi = mid - 1
            if cur:
                lines.append(cur)
                cur = []
            lines.append(word[:fit])
            word = word[fit:]
        if not word:
            continue
        cand = cur + SPACE + word if cur else word
        if measure(cand) <= target:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)

    # Fill a page until one more line would let the API downscale it.
    chunks, chunk, chunk_w = [], [], 0.0
    for line in lines:
        lw = measure(line)
        new_w = math.ceil(max(chunk_w, lw)) + PAD * 2
        new_h = sum(height_of(l) for l in chunk) + height_of(line) + PAD * 2
        if chunk and (new_h > CAP_H or new_w > CAP_W or not no_downscale(new_w, new_h)):
            chunks.append(chunk)
            chunk, chunk_w = [], 0.0
        chunk.append(line)
        chunk_w = max(chunk_w, lw)
    if chunk:
        chunks.append(chunk)

    written = []
    for number, page in enumerate(chunks, 1):
        width = math.ceil(max(measure(l) for l in page)) + PAD * 2
        height = sum(height_of(l) for l in page) + PAD * 2

        img = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        y = float(PAD)
        for line in page:
            x = float(PAD)
            row_h = height_of(line)
            for ch, is_big in line:
                color, is_bold = classify(ch, colors)
                # Every character sits on one baseline, so a bigger one grows
                # upward out of the line rather than shifting the rest down.
                top = y + row_h - (ident_px if is_big else size) - 1
                draw.text((x, top), ch, font=face(is_big, is_bold), fill=color)
                x += char_w(ch, is_bold, is_big)
            y += row_h

        path = Path("%s-%d.png" % (out_stem, number))
        img.save(path, optimize=True)
        written.append((path, width, height))

    return written, int(target), line_h


def tk_picker():
    """Show the size dialog. Returns (shown, size).

    shown is False when there is no Tk to draw with, which is the case on a
    machine with no tkinter and on a Linux box with no display. size is None
    when the dialog was shown and the person closed it without picking.
    """
    try:
        import tkinter as tk
    except ImportError:
        return False, None
    try:
        root = tk.Tk()
    except Exception:                         # no display to draw on
        return False, None

    picked = {"px": None}

    def take(px):
        picked["px"] = px
        root.destroy()

    root.title("DensePack size")
    root.resizable(False, False)
    tk.Label(root, text="Which model will read this image?").pack(padx=16, pady=(14, 8))
    for px, label in READER_SIZES:
        tk.Button(root, text=label, width=34,
                  command=lambda p=px: take(p)).pack(padx=16, pady=3)
    tk.Button(root, text="Cancel", width=34,
              command=root.destroy).pack(padx=16, pady=(10, 14))
    root.bind("<Escape>", lambda _e: root.destroy())

    # Explorer starts this behind the window that was clicked, so the dialog is
    # raised once. -topmost is dropped again, or every other window a person
    # opens afterwards sits under it.
    root.attributes("-topmost", True)
    root.update_idletasks()
    root.after(400, lambda: root.attributes("-topmost", False))
    root.mainloop()
    return True, picked["px"]


def text_picker():
    """Ask for a size on the terminal. Returns a size, or None when there is
    nobody at the keyboard to answer."""
    if not sys.stdin or not sys.stdin.isatty():
        return None
    out = sys.stderr
    print("Which model will read this image?", file=out)
    for number, (px, label) in enumerate(READER_SIZES, 1):
        print("  %d  %s" % (number, label), file=out)
    print("Type a number or a pixel size, or press Enter for %d px: " % DEFAULT_SIZE,
          end="", file=out)
    out.flush()
    try:
        answer = sys.stdin.readline().strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not answer:
        return DEFAULT_SIZE
    sizes = [px for px, _label in READER_SIZES]
    if answer.isdigit():
        value = int(answer)
        if 1 <= value <= len(sizes):
            return sizes[value - 1]
        if value in sizes:
            return value
    raise SystemExit("%s is not one of the sizes. Nothing was packed." % answer)


def choose_size(terminal_ok=True):
    """The size to draw at, asked for rather than assumed.

    terminal_ok is False when the text being packed arrives on stdin, because
    then a terminal question would swallow the text it is packing.
    """
    shown, px = tk_picker()
    if shown:
        if px is None:
            raise SystemExit("No size picked. Nothing was packed.")
        return px
    px = text_picker() if terminal_ok else None
    if px is None:
        print("No way to ask which size, so DensePack used %d px." % DEFAULT_SIZE,
              file=sys.stderr)
        return DEFAULT_SIZE
    return px


def main():
    ap = argparse.ArgumentParser(
        description="Pack text into a dense image. Fable 5 reads 8 px, "
                    "Opus 5 reads 10 px, Sonnet 5 reads 12 px.")
    ap.add_argument("input", help="text file to pack, or - for stdin")
    # No default here. A run that names no size falls back to DEFAULT_SIZE
    # below and says so, and --pick opens the dialog instead. The plugin picks
    # per reader from the model it is spawning; this tool cannot know who will
    # read the image, so it either asks or names the size it fell back to.
    ap.add_argument("--size", type=int, default=None,
                    help="font size in px. Fable 5 reads 8, Opus 5 reads 10, Sonnet 5 reads 12. Below 8 misreads digits. Default %d" % DEFAULT_SIZE)
    ap.add_argument("--pick", action="store_true",
                    help="ask which of the three reader sizes to draw at")
    ap.add_argument("--out", default="packed", help="output name stem")
    ap.add_argument("--spacing", type=float, default=1.0, help="line spacing, default 1.0")
    ap.add_argument("--no-color", action="store_true", help="black text only")
    ap.add_argument("--quiet", action="store_true", help="print only the image paths")
    args = ap.parse_args()

    if args.size is not None:
        size = args.size
        defaulted = False
    elif args.pick:
        size = choose_size(args.input != "-")
        defaulted = False
    else:
        size = DEFAULT_SIZE
        defaulted = True

    raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(
        encoding="utf-8", errors="replace")
    if not raw.strip():
        raise SystemExit("Nothing to pack.")

    text = flatten(raw)
    written, target, line_h = pack(text, size, args.out, args.spacing, not args.no_color)

    text_tokens = len(raw) / CHARS_PER_TOKEN
    image_tokens = sum(patches(w, h) for _p, w, h in written)

    for path, _w, _h in written:
        print(path)

    if args.quiet:
        return

    saving = (1 - image_tokens / text_tokens) * 100 if text_tokens else 0
    out = sys.stderr
    print("", file=out)
    print("characters   %d raw, %d flattened" % (len(raw), len(text)), file=out)
    print("layout       %d px wide, %d px line height, %d px font%s" % (
        target, line_h, size, ", the default" if defaulted else ""), file=out)
    print("images       %d, all checked against Fable's own resize rule" % len(written), file=out)
    print("as text      %d tokens" % round(text_tokens), file=out)
    print("as image     %d tokens" % image_tokens, file=out)
    if size < RISKY:
        print("WARNING      %d px misreads digits even in color. Verify a test image first." % size, file=out)
    if saving > 0:
        print("saving       %.0f percent" % saving, file=out)
    else:
        print("WORSE by     %.0f percent. Send the text instead." % -saving, file=out)


if __name__ == "__main__":
    main()
