"""Draw a code file as a banded condensed image.

What this file does, in plain words. A source file is turned into one long
stream of characters. Every source line gets its own background band, and the
band colour is the line's nesting depth. Each line opens with its line
number, and an indented line carries its exact indent as a count. The first
page carries a key row that names the bands and the marks, so the reader
needs nothing else.

Every character is drawn by FreeType through freetype_glyph.py, on every
platform. The Pillow path draws wherever FreeType cannot open the face.

The two functions a caller wants are pack_code(text, px, out_stem), which
draws one whole source file, and pack_fenced(fences, px, out_stem), which
draws the python-labelled blocks lifted out of a report or a brief. Both
return what densepack.pack returns: a list of (path, width, height), the wrap
target and the line height.
"""
import keyword
import math
import re
import sys
import tokenize
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import densepack as dp  # noqa: E402
# Pillow is the canvas, the rectangle drawing, the resampler, the palette
# quantiser and the PNG encoder. It does not decide the value of an ink pixel:
# every glyph is composited by paste_ink(), which blends in linear light the
# way MacType does. Dropping Pillow would mean writing a PNG encoder.
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
try:
    # numpy carries the linear-light blend. Without it paste_ink() falls back
    # to Pillow's sRGB compositing.
    #
    # ONE BLAS THREAD. numpy's OpenBLAS reserves a work buffer for every core
    # when the library loads, and the blend is elementwise, so no draw uses
    # one. On a machine with many cores that buffer commits hundreds of
    # megabytes a hook process before its first draw, and a burst of hooks
    # multiplies it. OpenBLAS reads the variable once, when it loads, so it is
    # set before the import, and a value already in the environment is kept.
    import os as _os  # noqa: E402
    _os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    import numpy as _np  # noqa: E402
except ImportError:
    _np = None
import style  # noqa: E402
import freetype_glyph  # noqa: E402

# Every number and colour below comes from style.load(), which reads the
# defaults in style.py and any style.json on disk.
_S = style.load()

BACKGROUND = _S["page.background"]
OUTLINE = _S["band.outline"]
OUTLINE_W = _S["band.outline_width"]
MARK_BOX_INK = tuple(_S.get("mark.box_ink") or (0, 0, 0))  # the box around a line break run
BOX_CLEAR = int(_S.get("mark.box_clear", 0) or 0)  # white between the box and the band after it, in layout pixels
# The box round a line number fits its own digits on all four sides, rather than
# taking its top and bottom from the band. See the draw loop.
BOX_FITS_INK = not bool(_S.get("mark.box_fits_band", False))
BOX_GAP = float(_S.get("mark.box_gap", 0) or 0)
SEAM_GAP = float(_S.get("mark.seam_gap", 0) or 0)  # white, rule, white between a line number and an indent count
DIVIDER = _S["page.divider"]
DIVIDER_W = _S["page.divider_width"]
WRAP_W = _S["code.wrap_width"]
# The text width of one page column, from the drawn page width. 580 px of page
# is 560 px of text: page.pad a side and the 8 px the draw loop adds. A4 is 794
# px of page.
PAGE_EXTRA = 8
PAGE_W = float(_S["page.width"] - 2 * _S["page.pad"] - PAGE_EXTRA)
# The page ends at its widest row; see style.py, page.trim.
PAGE_TRIM = bool(_S.get("page.trim", True))
# Source rows one page holds, or 0 to fill the page height.
PAGE_LINES = _S["page.lines"]
# Page columns on one sheet.
COLUMNS = _S["page.columns"]
# The spacing constants of this file are mapped in one block, above GAP.
# The page's own horizontal scale. Below 1.0 every glyph is condensed and its
# height is kept, so more characters fit a row at the same size. See face_for()
# in pack_code.
SCALE_X = float(_S.get("font.scale_x", 1.0) or 1.0)
LETTER_SPACE = _S["space.letter"]
PARA_GAP = _S["space.paragraph_gap"]
CLEAR = _S["space.clear"]
CLEAR_NARROW = _S["space.clear_narrow"]
NARROW_COLS = _S["space.narrow_cols"]
INK_FLOOR = _S["space.ink_floor"]
# A px offset a character group draws at, added to the page size.
GROUP_PX = _S["font.group_px"]
PILCROW_INK = _S["mark.pilcrow_ink"]
COUNT_INK = tuple(_S.get("mark.count_ink") or PILCROW_INK)  # the blank line count
# The count and the mark of a blank line run, in the order they draw.
BLANK_FORMAT = _S["mark.blank_format"]
CURVE_THRESHOLD = _S["curve.threshold"]
CURVE_RING = _S["curve.ring"]
CURVE_RING_WEIGHT = _S["curve.ring_weight"]
CURVE_GAMMA = _S["curve.gamma"]


# The suffixes a Read draws as banded code. One set, read by pointer.py, so
# the banded path is chosen in one place. Python is classified by its own
# tokenize module; every other suffix here goes through plain_class_map
# below. A suffix outside this set keeps the plain pack.
CODE_SUFFIXES = frozenset(_S["code.suffixes"]) | frozenset(
    _S["band.text_suffixes"] if _S["band.text_files"] else ())


# The colour table and the token classifier.

# Comment ink and string ink. They use different hues, so a reader can tell a
# comment from a string on a tint set that holds a green. Both are dark enough
# to read at small sizes.
MUTED = _S["code.ink.comment"]
# No page draws the gutter; the key stays so a saved style.json that names it
# still loads.
GUTTER = _S["code.ink.gutter"]
BROWN = _S["code.ink.string"]

INK_FOR = {name: _S["code.ink." + name] for name in
           ("comment", "string", "keyword", "number", "name", "op",
            "tag")}

# Reserved character inks. These two characters misread on shape alone, so each
# gets a colour no syntax class and no other reserved character uses, applied
# wherever the character appears in code:
#   backtick - a reader turns ` into a double quote whatever its shape;
#   orange is the plugin's own free ink, nearest ink lime at 225, nearest
#   band 409.
#   underscore - a reader turns _ into a space; plum is the one colour the
#   grid search found that clears 210 against all six anchor inks (black,
#   blue, green at 210, magenta 215, orange 275, lime 270) and every band
#   (nearest 504).
RESERVED = dict(_S["code.ink.reserved"])

# The ink scheme. "simple" draws every letter in the name ink, every digit in
# the number ink and everything else in the op ink, three inks a reader holds
# in one rule, and the look-alike, reserved, class and per-character inks above
# stay off. "lookalike" is the other scheme.
SCHEME = str(_S.get("ink.scheme") or "simple")


# The few marks a reader mixes up even in a good face keep their own ink under
# the simple scheme: the dot family . , : ; and the quote family " ` ' each
# draw in four and three inks of their own, so . and : never draw alike.
SIMPLE_PUNCT = {k: tuple(v) for k, v in (_S.get("ink.simple_punct") or {}).items()}
# the inks a run of underscores cycles through, red then blue
UNDER_RUN_INKS = [tuple(v) for v in (_S.get("ink.underscore_run") or [(150, 0, 0), (0, 30, 160)])]


# the second quote of a kind on a line draws as its closing character
QUOTE_CLOSERS = {'"': "”", "'": "’"}


# How much of a bracket's hang below the baseline is taken back. 1.0 lands its
# ink on the baseline, 0.0 leaves it where Inter draws it, on the mathematical
# axis. See baseline_lift().
BASELINE_LIFT = float(_S.get("mark.baseline_lift", 0.0) or 0.0)

# One size for one mark, when the whole set's size does not suit it. The pipe
# is the case this was added for: it is the tallest mark on the page and reads
# a size above everything around it.
MARK_PX_BY_CHAR = {k: float(v) for k, v
                   in (_S.get("font.mark_px_by_char") or {}).items()}

# ROWS ONE CHARACTER MOVES DOWN, negative to raise it. A closing double quote
# sits lower in its em than the opening one, so the two do not line up on a
# row. Nothing in the font can be asked to fix that; the glyph is drawn where
# its designer put it, so the page moves it.
DY_BY_CHAR = {k: int(v) for k, v
              in (_S.get("font.dy_by_char") or {}).items()}

# One character's own horizontal scale, which beats every group below it, so a
# single mark can be moved off its group's column without inventing another
# group for it.
SCALE_X_BY_CHAR = {k: float(v) for k, v
                   in (_S.get("font.scale_x_by_char") or {}).items()}

# The marks that draw at the PAGE's size and condense to their own share of it.
# They sit between the letters, which condense hardest, and the marks that keep
# their full width at a size of their own. scale_for checks this set FIRST, so
# a mark named here is not also given font.mark_px by face_for.
SCALED_MARKS = tuple(_S.get("font.scaled_marks") or ())
SCALED_MARK_SCALE = float(_S.get("font.scaled_mark_scale_x", 0) or 0)

# The width a DIGIT condenses to, as a share of its own. Zero means a
# digit keeps its full width. It is separate from font.scale_x because a
# digit has to stay legible against every other digit, and a line number
# is what the whole rebuild contract rests on.
DIGIT_SCALE_X = float(_S.get('font.digit_scale_x', 0) or 0)

# The marks that condense WITH the letters rather than keeping their own width:
# the opening quotes only. The second quote of a kind on a line draws as its
# closing form through QUOTE_CLOSERS, and those are not here, so an opener
# follows the letters and a closer keeps its width.
CONDENSED_MARKS = tuple(_S.get('font.condensed_marks') or ('"', "'"))

# THE SIZE THE FULL WIDTH MARKS DRAW AT. Zero means the page's own size. It
# sets the marks apart from the letters: the letters are asked for larger and
# condensed back to the column width, and these are asked for at their own size
# and left uncondensed.
MARK_PX = float(_S.get("font.mark_px", 0) or 0)

# The marks that are drawn EXACTLY as they are, neither condensed nor taller.
# They keep their width and do not take the extra height the larger size gives.
#
# HOW. font.scale_x is not applied to them, and face_for offsets their size
# back to space.row_px, so a mark drawn on a 13 px page at scale 0.769 comes
# out as a 10 px mark. A letter beside it is 13 px condensed to the same column
# width, so the letters gain height and the marks do not.
#
# THE DOT MARKS ARE NOT IN THIS SET. The period, comma, semicolon and colon
# draw a size LARGER, and font.bigger_chars carries them.
FULL_WIDTH = tuple(_S.get("font.full_width_chars")
                   or ("(", ")", "[", "]", "{", "}", "|", "\\", "/",
                       "%", "<", ">", "+", "=", "*", "&", "^", "$", "#",
                       "@", "!", "?", "~", "-"))


def scale_for(ch):
    """The horizontal scale one character draws at.

    font.scale_x raises the x-height by asking FreeType for a larger size and
    condensing the width back to the target, so a glyph gains rows and keeps
    its columns. FreeType takes the width and the height separately and hints
    at that aspect, so the stems are grid fitted at the width they land at and
    nothing is scaled afterwards.

    The checks run in this order.

    A scale named for one character in font.scale_x_by_char wins over every
    group.

    font.scaled_marks draw at the page's own size and condense to
    font.scaled_mark_scale_x, which sits between the letters and the marks
    that keep their width. They are checked before the other groups, so a
    mark named there is not also given font.mark_px by face_for.

    font.condensed_marks, the opening quotes, condense with the letters. The
    second quote of a kind on a line draws as its closing form through
    QUOTE_CLOSERS, and those are not in the set, so an opener follows the
    letters and a closer keeps its own width.

    A digit takes font.digit_scale_x. It condenses less than a letter does,
    because a digit has to stay legible against every other digit and a line
    number is what the whole rebuild contract rests on. Zero means the digits
    keep their full width.

    Every other mark keeps its full width, and font.mark_px decides what size
    it takes. A quote left uncondensed at the page's larger size draws
    narrower and denser than the letters beside it. On Inter SemiBold,
    hinting mode 2, snapped:

        10 px plain                 the quote is 5 columns, 40.0 per cent solid
        12 px condensed to 0.833    5 columns, 40.0 per cent solid, 1 row taller
        12 px NOT condensed         4 columns, 50.0 per cent solid

    A letter takes font.scale_x, because a letter has width to give up.
    """
    if ch in SCALE_X_BY_CHAR:
        return SCALE_X_BY_CHAR[ch]
    if ch in SCALED_MARKS:
        return SCALED_MARK_SCALE or 1.0
    if ch in CONDENSED_MARKS:
        return SCALE_X
    if ch.isdigit():
        return DIGIT_SCALE_X or 1.0
    if not ch.isalpha():
        return 1.0
    return SCALE_X


def simple_ink(ch):
    """The ink a character draws in under the simple scheme: one of three,
    or its own for a mark in ink.simple_punct."""
    if ch in SIMPLE_PUNCT:
        return SIMPLE_PUNCT[ch]
    if ch.isalpha():
        return INK_FOR["name"]
    if ch.isdigit():
        return INK_FOR["number"]
    return INK_FOR["op"]


def drawn(ch):
    """The glyph drawn for a source character: itself, or the glyph an
    override names, such as the curly double quote for the straight one. The
    tab mark and the underscore mark are private-use code points and draw as
    the arrow and the double dagger."""
    if ch == TAB_MARK:
        return "→"
    if ch == UND_MARK:
        return "‡"
    # The line-end and indent marks never draw, and their glyphs' widths are
    # part of every row measure, so they keep those glyphs here and the layout
    # does not move.
    if ch == NL_MARK:
        return "¶"
    if ch == INDENT_MARK:
        return "§"
    return char_over(ch, "glyph") or ch

# Metadata ink: the line-number gutter, the header, the footer and the
# open-bracket newline marker. Deliberately dimmer than every code ink so a
# reader never mistakes metadata for source.
#
# It is dark enough that a reader keeps the line count the gutter anchors;
# digits too dim make a reader skip or shift source lines. The dimmest code ink
# is magenta (195,0,140) at 430 on the sum of (255 - c) per channel; 118 gray
# sits at 411, the darkest even gray that stays under that bar with the check
# below still holding.


_TOKCLASS = {tokenize.COMMENT: "comment", tokenize.STRING: "string",
             tokenize.NUMBER: "number", tokenize.OP: "op"}
for _n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
    _t = getattr(tokenize, _n, None)
    if _t is not None:
        _TOKCLASS[_t] = "string"


def _tokens(raw):
    """tokenize's tokens, or as many as it read before it stopped.

    A block lifted out of a report is a fragment, not a whole module, and
    tokenize raises on a fragment: an unclosed bracket, a first line that is
    already indented, a stray quote. What tokenized is coloured; the rest
    keeps the default class and still draws.
    """
    out = []
    try:
        for tok in tokenize.generate_tokens(StringIO(raw).readline):
            out.append(tok)
    except (tokenize.TokenError, IndentationError, SyntaxError,
            ValueError):  # noqa: BLE001
        pass
    return out


def class_map(raw, lines):
    """One class per character, from tokenize's own token classes."""
    cls = [["name"] * len(line) for line in lines]
    for tok in _tokens(raw):
        if tok.type == tokenize.NAME:
            c = "keyword" if keyword.iskeyword(tok.string) else "name"
        else:
            c = _TOKCLASS.get(tok.type)
        if c is None:
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        for r in range(srow, min(erow, len(lines)) + 1):
            line = lines[r - 1]
            a = scol if r == srow else 0
            b = ecol if r == erow else len(line)
            for i in range(a, min(b, len(line))):
                cls[r - 1][i] = c
    return cls


# The classifier for every code suffix that is not python. tokenize reads
# python and nothing else, so a .gd, .js or .ps1 file is classified by shape:
# a comment runs from # or // to the end of the line, a string sits between
# quotes, digits are numbers, words are names, and every other character is
# punctuation. The alternatives are ordered, so a # inside quotes stays part
# of the string and a quote inside a comment stays part of the comment. The
# bands carry the line structure; the colours only have to be steady.
_PLAIN = re.compile(
    r'(?P<comment>#[^\n]*|//[^\n]*)'
    r'|(?P<string>"(?:\\.|[^"\\])*"?|\'(?:\\.|[^\'\\])*\'?)'
    r'|(?P<number>\d[\d.]*)'
    r'|(?P<name>[A-Za-z_]\w*)')


def plain_class_map(lines):
    """One class per character, for a file python's tokenize cannot read."""
    cls = [["op"] * len(line) for line in lines]
    for row, line in enumerate(lines):
        for hit in _PLAIN.finditer(line):
            for i in range(hit.start(), hit.end()):
                cls[row][i] = hit.lastgroup
    return cls


# The marks the flow carries.
NL_MARK = dp.NL_MARK
BLANK_MARK = _S["mark.blank"]   # the bullet, a run of blank lines
# The section sign. No page draws it, because the bands and the indent count
# carry the indent; the name stays for the callers that read it.
COUNT_MARK = _S["mark.count"]
# The band as a shape: grown or shrunk past the text by pad, moved by offset,
# in pixels. All zero in the shipped renderer.
BAND_PAD_X = int(_S.get("band.pad_x", 0) or 0)
BAND_PAD_Y = int(_S.get("band.pad_y", 0) or 0)
BAND_OFF_X = int(_S.get("band.offset_x", 0) or 0)
BAND_OFF_Y = int(_S.get("band.offset_y", 0) or 0)
BAND_INSET = int(_S.get("band.text_inset", 0) or 0)
# The rows of band kept clear above the tallest ink of a row and below the
# lowest, so no glyph sits on its band's edge. It grows the ROW, not the band:
# growing the band alone reaches into the row gap and merges neighbours.
BAND_TEXT_CLEAR = int(_S.get("band.text_clear", 1) or 0)
# The band centres itself on the row's real ink, so band.offset_y does not have
# to be measured by eye at every glyph size. See _pack_code.
CENTRE_TEXT = bool(_S.get("band.centre_text", True))
# Every pair carries the same distance from ink to ink, rather than space.clear
# acting only as a floor. See char_widths().
EXACT_INK_GAP = bool(_S.get("space.ink_gap_exact", True))
BAND_GROW = tuple(int(_S.get("band.grow_" + s, 0) or 0) for s in "lrtb")

# Objects placed by hand: "line:N", "band:N", "word:N:K". Empty in the shipped
# renderer. See style.py, layout.placements.
PLACEMENTS = {k: dict(v) for k, v in (_S.get("layout.placements") or {}).items()
              if isinstance(v, dict)}


def _placed(key, field):
    """One placement field, 0 when the object was never moved."""
    entry = PLACEMENTS.get(key)
    if not entry:
        return 0
    try:
        return int(entry.get(field, 0) or 0)
    except (TypeError, ValueError):
        return 0


def word_indices(pairs, ids):
    """The word number of every character inside its own source line, -1
    for a character that is not part of a word, so "word:N:K" names one
    run."""
    out = []
    k = -1
    last = None
    for j, p in enumerate(pairs):
        if ids[j] != last:
            k = -1
            last = ids[j]
        if word_char(p[0]) and (j == 0 or ids[j - 1] != ids[j]
                                or not word_char(pairs[j - 1][0])):
            k += 1
        out.append(k if word_char(p[0]) else -1)
    return out
INDENT_MARK = _S.get("mark.indent", "\u00a7")
EXT_BLACK = bool(_S.get("code.extension_black", False))
# a dot then one to six letters or digits, ended by a non word character
EXT_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,5}(?![A-Za-z0-9_])")
TAB_MARK = _S["mark.tab"]       # the right arrow, leading tabs
UND_MARK = _S["mark.underscore"]  # the double dagger, an underscore run

# The underscore run mark stays in the reserved set that build_flow refuses in
# a source. A run of underscores draws as the underscores themselves, in
# alternating inks, so no page draws this mark.

# The runs inside one line's leading whitespace, in the order they are written.
# build_flow counts a tab-indented line's columns with expandtabs(4), so the
# indent count is the column count.
_LEAD_RUN = re.compile(r" +|\t+")

# The two inks.
INDENT_INK = _S["code.ink.indent"]
BLANK_INK = _S["code.ink.blank"]

# The edge that says a source line runs on into the next row.
WRAP_INK = _S["code.ink.wrap"]
# Page pixels of paper the wrap mark keeps between its own stroke and the last
# character's INK on that row. See the note at the wx placement in the draw
# loop for why the advance sum is the wrong thing to measure from, and for the
# sweep that set this number.
WRAP_INK_CLEAR = float(_S.get("mark.wrap_ink_clear", 3) or 0)


# How many times wrap_edge() had to move a mark onto the text on this draw.
# It is a list so a nested draw can reset it and read it back.
CLAMP_HITS = [0]

# True while _fit_width() draws a widening trial. Such a trial is compared on
# its page sizes and its clamp count and no pixel of it is ever read, so its
# glyphs are not pasted; the bands and the wrap marks still draw, because the
# clamp count comes from the wrap mark. A trial that wins is drawn again with
# its glyphs.
_NO_GLYPHS = False

# The last file's character measurement, one entry: see _pack_code().
_CW_CACHE = {}
# The last file's flow, one entry: see _pack_code().
_FLOW_CACHE = {}
# A glyph's bounding box per face and character, for the mark box runs.
_BBOX_CACHE = {}


def wrap_edge(d, wx, y0, y1):
    """The run-on edge as one wavy line the row's own height: a sine curve
    in WRAP_INK that swings WRAP_W left and right of wx, three waves a row,
    so it is a shape no character has and does not run together with a
    | in the text. A straight bar reads as a pipe, and a zigzag reads square."""
    import math
    # the wave swings WRAP_W each side of wx; kept inside the page, because a
    # row that runs to the edge would clip the wave's right half
    canvas = getattr(d, "c", None)
    if canvas is not None and getattr(canvas, "ratio", None):
        limit = (canvas.width - 1) / canvas.ratio - WRAP_W * 1.5 - 2  # the swing plus half the stroke
        if wx > limit:
            # The mark does not fit. wrap_edge draws it at the limit, which
            # puts it on the text already drawn there. CLAMP_HITS counts that.
            # _fit_width() reads the count and refuses a layout that clamps.
            CLAMP_HITS[0] += 1
        wx = min(wx, limit)
    if _NO_GLYPHS:
        # A glyphless trial needs the count above and not the wave.
        return
    span = max(int(y1 - y0), 1)
    waves = 3
    pts = []
    for i in range(span + 1):
        t = i / span
        pts.append((wx + WRAP_W * math.sin(2 * math.pi * waves * t), y0 + i))
    # The stroke stays at WRAP_W, which is 2.
    #
    # A letter stem holds at one pixel because it is a straight vertical run;
    # this is a sine wave, traced on a mask at four times size and shrunk, so
    # at one pixel every diagonal step averages down into a fragment and the
    # wave breaks into dots.
    #
    # It does draw heavier than the text beside it, and that is the trade: the
    # mark has to survive the shrink as one continuous shape, because a reader
    # uses it to tell a wrapped row from a new source line.
    d.line(pts, fill=WRAP_INK, width=max(int(WRAP_W), 1))


def ink_span(font, ch, seen):
    """First and last column this character actually inks, its own origin at 0.

    The drawn width has to clear the ink, not the font's advance: a glyph can
    ink a column past its advance, and it then shares a pixel column with the
    letter after it.

    The mask is read in mode="L" for every character. The monochrome mask,
    mode="1", stops short of the mask value 64 the step curve inks from, so
    the layout would clear fewer columns than the page fills and a glyph
    would land against its neighbour's last column.
    """
    span = seen.get(ch)
    if span is None:
        box = font.getbbox(drawn(ch))
        mask = font.getmask(drawn(ch), mode="L")
        w, h = mask.size
        data = bytes(mask)
        cols = [i for i in range(w)
                if any(data[j * w + i] > INK_FLOOR for j in range(h))]
        span = (box[0] + cols[0], box[0] + cols[-1]) if cols else None
        seen[ch] = span
    return span


def build_flow(raw, python=True, legend=None):
    """One (char, ink, big) triple per drawn character, the whole file in order.

    big is True only for a character LIFT named that LIFT_PX draws larger.

    python=False picks plain_class_map, for a source tokenize cannot read.
    """
    if not raw.endswith("\n"):
        raise ValueError("the flow stores every newline as a mark. "
                         "This text does not end with one")
    if "\r" in raw:
        raise ValueError("carriage returns are not in the format")
    for mark in (NL_MARK, BLANK_MARK, TAB_MARK, UND_MARK):
        if not mark:
            # an empty mark is no mark
            continue
        if mark in raw:
            raise ValueError("source already holds the %r mark" % mark)
    lines = raw.split("\n")[:-1]
    form = dp._tag_form(raw)
    seen = {}
    cls = class_map(raw, lines) if python else plain_class_map(lines)
    pairs = []
    all_cols = [len(l[:len(l) - len(l.lstrip(" \t"))].expandtabs(4))
                for l in lines if l != ""]
    unit = min([v for v in all_cols if v > 0] or [4])
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == "":
            j = i
            while j < len(lines) and lines[j] == "":
                j += 1
            # No blank line count draws: every line carries its own number, so
            # a jump from 1 to 3 already says line 2 was blank. A count in
            # green digits beside a green line number would run together with
            # it.
            i = j
            continue
        # This line's number, in the break ink, so a reader can name any line
        # on any page. It opens the line, so two digit groups never touch.
        for _n in str(i + 1):
            pairs.append((_n, COUNT_INK, False))
        lead = line[:len(line) - len(line.lstrip(" \t"))]
        # The band behind this line carries its depth, and an indented line
        # also draws its exact column count, so the reader copies the exact
        # indent.
        cols_here = len(lead.expandtabs(4))
        ext_cols = set()
        if EXT_BLACK:
            for m in EXT_RE.finditer(line):
                ext_cols.update(range(m.start(), m.end()))
        if INDENT_MARK and cols_here:
            # The count draws on EVERY indented line. Depth times a step is not
            # enough: the same code at 4 spaces and at 2 would draw the same
            # bytes, and a reader could only guess the step. A red count beside
            # the green line number says indent.
            for d in "%d" % cols_here:
                pairs.append((d, BLANK_INK, False))
        spans = [] if (legend is None and not (LIFT_INK or LIFT_PX)) else [
            m.span() for m in LIFT.finditer(line, len(lead))]
        k = len(lead)
        quotes = {q: 0 for q in QUOTE_CLOSERS}
        while k < len(line):
            ch = line[k]
            # The second double quote of a line is the closing one and draws as
            # its own character, the closing curly quote, which carries its own
            # ink; the first draws as the opening one. A reader then finds a
            # string's end without counting quote pairs. A run of the same
            # quote, the three of a docstring, is one quote: all three open or
            # all three close.
            if ch in QUOTE_CLOSERS:
                if k == 0 or line[k - 1] != ch:
                    quotes[ch] += 1
                if quotes[ch] % 2 == 0:
                    ch = QUOTE_CLOSERS[ch]
            # A token class gives every character inside one token the same
            # ink, so a hex id such as 139811a4 would draw in one colour and a
            # reader could misread its digits. densepack.CHAR_INK, built by
            # densepack._colour_map() from CONFUSABLE, holds one ink per
            # look-alike character and is the same map densepack.classify()
            # draws prose with. Take it first for every character it knows, so
            # no two characters that look alike share a colour anywhere on the
            # page, not only inside a lifted token. A character it does not
            # know has no look-alike in the list and keeps its class ink, which
            # is what carries the code structure.
            if SCHEME == "simple":
                ink = simple_ink(ch)
            else:
                ink = (char_over(ch, "ink") or RESERVED.get(ch)
                       or dp.CHAR_INK.get(ch) or INK_FOR[cls[i][k]])
                if EXT_BLACK and k in ext_cols:
                    ink = (0, 0, 0)
            if spans and spans[0][0] == k:
                start, stop = spans.pop(0)
                if legend is None:
                    # The token stays in the picture and is marked there.
                    for p in range(start, stop):
                        # The character ink beats the lift ink here for
                        # the same reason: a lifted number is the run a
                        # reader has to copy digit by digit.
                        pairs.append((line[p],
                                      simple_ink(line[p]) if SCHEME == "simple"
                                      else (0, 0, 0) if EXT_BLACK and p in ext_cols
                                      else dp.CHAR_INK.get(line[p]) or
                                      LIFT_INK or RESERVED.get(
                                          line[p], INK_FOR[cls[i][p]]),
                                      bool(LIFT_PX)
                                      or line[p] in BIGGER))
                else:
                    for mark in tag_for(line[start:stop], legend, seen, form):
                        pairs.append((mark, INK_FOR["tag"], False))
                k = stop
                continue
            if ch == "_":
                run = 1
                while k + run < len(line) and line[k + run] == "_":
                    run += 1
                if run > 1:
                    k += run
                    # A run of underscores draws as the underscores themselves,
                    # the first red, the next blue, then red again, with the
                    # same-letter clear column between them, so two bars that
                    # would merge as one tell apart by ink and by a gap.
                    for n in range(run):
                        pairs.append(("_", UNDER_RUN_INKS[n % len(UNDER_RUN_INKS)], False))
                    continue
            pairs.append((ch, ink, ch in BIGGER))
            k += 1
        pairs.append((NL_MARK, PILCROW_INK, False))
        i += 1
    return pairs


def flow_depths(raw):
    """One nesting depth per drawn source line, in the order they draw.

    The band behind a line is this number. build_flow draws every line that
    is not empty and ends each one with a pilcrow, so this list lines up one
    for one with the line ids char_widths hands back. The indent step is
    taken off the file rather than assumed, so one level is one real nesting
    level whatever the file is written in.
    """
    cols = [len(l[:len(l) - len(l.lstrip(" \t"))].expandtabs(4))
            for l in raw.split("\n")[:-1] if l != ""]
    unit = min([c for c in cols if c > 0] or [4])
    return [c // unit for c in cols]


# Numbers a reader can misread. A run of two or more digits, a comma grouped
# number, and any token built only of 0 1 7 8 9 and l can leave the picture as
# the plain pack's numbered marker, with their text in the legend sidecar.
LIFT = re.compile(r"(?<![0-9A-Za-z_])"
                  r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{2,}|[01789l]{2,})"
                  r"(?![0-9A-Za-z_])")

# The same tokens, kept in the picture instead of lifted out of it. A caller
# that passes legend=None draws every digit run as itself; these two knobs say
# how such a token is drawn so a reader reads it right without a legend row to
# resolve. Both are off in the shipped build.
#
#   LIFT_INK  the ink every character of the token draws in, or None to keep
#             the syntax class ink. INK_FOR["tag"], lime, is the one ink the
#             search in densepack.INK measured at 210 from all eight code
#             inks, and with the markers off nothing else on the page uses it.
#   LIFT_PX   px added to the page size for that token, or 0 for the page
#             size. The bigger glyph sits on the row's own baseline and grows
#             upward, the mechanism densepack.py's IDENT_PX already uses for
#             an identifier, so no row moves and no page grows taller. It
#             costs width.
#
# A larger glyph pulls the reader's eye onto the row above, so the size does
# not ship. The colour is set but no page draws it: build_flow asks
# densepack.CHAR_INK first, and that map knows every character LIFT can match.
LIFT_INK = _S["code.ink.lift"]
LIFT_PX = _S["code.lift_px"]

# The marks a reader cannot tell apart on a packed page, such as the backtick
# and the dot marks, drawn BIGGER_PX larger than the type around them.
#
# The mechanism is the one already in this file for a lifted token and in
# densepack.py for an identifier: a second face BIGGER_PX larger, drawn on the
# row's own baseline through the big flag build_flow already carries as the
# third item of every pair. The bigger face has the taller ascent, so the glyph
# starts big_dy rows higher and grows upward into the clear rows above the
# type. No row moves and no page grows taller.
#
# The mark keeps the body face's cell. char_widths takes its pen step and its
# clear columns from the body face, so the larger glyph grows into the white
# the small one already owns and pushes no neighbour; the layout with the marks
# on is the layout with them off. pack_code scales BIGGER_PX and LIFT_PX by the
# supersample with every other pixel count.
#
# Nothing else is enlarged. A larger digit pulls the reader onto the line
# above, so punctuation marks are the whole of the named set, and no digit and
# no letter takes the bigger face.
BIGGER = tuple(_S["font.bigger_chars"])
BIGGER_PX = _S["font.bigger_px"]
# The marks that step by their ink, not by their face's advance: see
# char_widths(). Its own name, so a test that turns BIGGER off keeps the
# same cells.
INK_STEP = tuple(_S.get("font.ink_step_chars") or ())

# THE BRACKETS SIT ON THE BASELINE.
#
# Inter draws a bracket centred on the maths axis, so it hangs below the
# baseline the letters share: at 12 px ( and ) ink 2 rows below the baseline
# and [ ] { } ink 3. A bracket that hangs reads as a descender, which is the
# one thing a letter's shape below the baseline is supposed to mean.
#
# font.bigger_px is not the cause. face_for() hands back ascent - face ascent
# as the dy and the draw site adds it, so every face on a row lands on one
# baseline, and the same bracket inks the same 2 or 3 rows below it with the
# bigger face switched off.
#
# So the lift is taken from the glyph, not from a table: whatever the mask
# hangs below the baseline is what it comes up by. That holds at any size and
# needs no number that the font file must match.
ON_BASELINE = ("(", ")", "[", "]", "{", "}")


def baseline_lift(ch, mask, top):
    """The rows a bracket comes up by, as a share of what it hangs below.

    top is the mask's own top, counted from the baseline and negative above
    it, so top + mask.height is what the glyph hangs below. Every other
    character, a real descender included, gets nothing.

    mark.baseline_lift is the share. A full 1.0 puts the brackets too HIGH,
    standing above the line, because Inter centres a bracket on the
    mathematical axis by design and some of that hang belongs there.
    """
    if ch not in ON_BASELINE or mask is None or not BASELINE_LIFT:
        return 0
    return int(round(max(0, top + mask.height) * BASELINE_LIFT))


def tag_for(value, legend, seen, form):
    """The marker standing for one value, the same marker for the same text."""
    tag = seen.get(value)
    if tag is None:
        tag = form % (len(legend) + 1)
        seen[value] = tag
        legend.append((tag, value))
    return tag


# One band colour a nesting depth: red depth 0, blue depth 1, green depth 2,
# purple depth 3, then apricot, pink, beige, cyan and lavender to depth 8,
# because a repeated colour reads as the top level; see style.py band.tints.
# Past depth 8 the nine repeat.
#
# Full strength band colours clash with the dark ink nearest their own hue, at
# a contrast near 1.0, which is one colour on itself. The band is what changes,
# not the ink, because the inks are what separate the lookalike characters.
#
# The bar is 3.0 to 1, the contrast WCAG 2 publishes as the minimum for large
# text and for a graphical object. Each band is the most saturated colour on
# its hue that clears it against every one of the ten inks a code page draws,
# found by search over the light half of the cube. The tag ink is not one of
# the ten: every call site passes legend=None, so no code page carries it. The
# binding ink is green (0, 150, 60) on all four bands, at 3.022 to 3.029.
#
# A higher bar makes the bands too pale: held to 3.454, three of the four
# cannot be told from white. At 3.0 the bands separate clearly and the worst
# ink loses 13 per cent of its contrast ratio.
#
# band.strength mixes each tint toward the page background: 1.0 draws it as
# written, which is what ships.
#
# band.top_level False draws a line at depth 0 as plain text on the page
# background and starts the first tint at the first indented level, so a band
# and a red indent count always appear together. True puts depth 0 on the first
# tint.
BAND_TOP_LEVEL = bool(_S.get("band.top_level", False))


def band_index(depth):
    """The tint index a nesting depth draws on, or None for no band."""
    if BAND_TOP_LEVEL:
        return depth % len(TINTS)
    if depth <= 0:
        return None
    return (depth - 1) % len(TINTS)


TINTS = [tuple(int(round(b + (c - b) * _S["band.strength"]))
               for c, b in zip(tint, _S["page.background"]))
         for tint in _S["band.tints"]]

# see the spacing map above GAP
PAD = _S["page.pad"]
CAP_H = _S["page.height"]
SHEET_GAP = _S["page.sheet_gap"]  # white space between two pages


def keep_leading_tabs(text):
    """expandtabs(4) everywhere except a line's leading whitespace run.

    A tab in the indent survives to build_flow, which counts it and draws
    TAB_MARK for it. Every other tab still becomes spaces, which is what a
    proportional font needs. A text with no tab is returned unchanged, so
    its image does not move.
    """
    if "\t" not in text:
        return text
    out = []
    for line in text.split("\n"):
        cut = len(line) - len(line.lstrip(" \t"))
        out.append(line[:cut] + line[cut:].expandtabs(4))
    return "\n".join(out)


def scheme_for(pairs):
    """The header lines page one carries for this flow.

    The underscore line is added only when the flow holds the underscore
    mark, so a file without one keeps the four-line header.
    """
    rows = list(_S["card.scheme_rows"])
    rows[1] = rows[1] % NL_MARK
    if any(p[0] == UND_MARK for p in pairs):
        rows.insert(2, _S["card.scheme_underscore"] % UND_MARK)
    return rows


# The key row's own spacing: white columns between a swatch's outline and its
# digit, and between one swatch and the next.
SWATCH_PAD = 2
SWATCH_GAP = 3


# The name pack_code() puts at the head of the key row, set per draw; the
# three legend functions read it so no signature changes.
_LEGEND_TITLE = ""
# True when a line of the file starts with a tab, set per draw.
_TAB_KEY = False


def legend_parts():
    """The key row page one carries, as (text, ink, band) pieces.

    band is a tint index or None. Every piece is drawn in the ink and on
    the band the page itself uses for that thing, so the row is a sample
    of the page and not a description of it.
    """
    parts = []
    # The source file's name leads the row: neither a page nor a text Read
    # result names its file, and a reader with two pages that share a constant
    # name can answer with the wrong file's value.
    if _LEGEND_TITLE:
        parts.append((_LEGEND_TITLE + "    ", (0, 0, 0), None))
    # The red indent count expands a leading tab to 4 columns, the same count
    # as 4 spaces, so a tab-indented file says so and a reader edits with tabs.
    if _TAB_KEY:
        parts.append(("4", BLANK_INK, "box"))
        parts.append((" indent spaces = 1 tab    ", MUTED, None))
    # One swatch per depth the page can draw, labelled with the depth. With
    # no band at depth 0 the row opens with a plain 0 and the tints run from
    # depth 1.
    if BAND_TOP_LEVEL:
        parts += [("%d" % d, (0, 0, 0), d) for d in range(len(TINTS))]
    else:
        parts.append(("0 ", (0, 0, 0), None))
        parts += [("%d" % (d + 1), (0, 0, 0), d) for d in range(len(TINTS))]
    parts.append(("=depth of nesting    ", MUTED, None))
    parts.append(("N", COUNT_INK, "box"))
    parts.append(("=line number    ", MUTED, None))
    parts.append(("N", BLANK_INK, "box"))
    parts.append(("=indent spaces    ", MUTED, None))
    # the three inks named: a digit in the digit ink, a letter in the letter
    # ink, a pipe in the mark ink
    # the digit named is the 1, against the lowercase l beside it. It draws in
    # the digit ink, which is blue.
    parts.append(("1", INK_FOR["number"], None))
    parts.append(("=the number one    ", MUTED, None))
    parts.append(("l", INK_FOR["name"], None))
    parts.append(("=lowercase L    ", MUTED, None))  # l against 1
    parts.append(("|", INK_FOR["op"], None))
    parts.append(("=the pipe character    ", MUTED, None))
    parts.append(("", WRAP_INK, "wrap"))  # the zipper itself, drawn by _legend_line
    parts.append(("=the line continues on the next row", MUTED, None))
    return parts


def legend_width(font):
    """The pixels legend_row() needs, so a trimmed page stays wide enough."""
    w = 0.0
    for text, _ink, band in legend_parts():
        w += font.getlength(text)
        if band is not None:
            w += 2 * SWATCH_PAD + SWATCH_GAP
    return w


def legend_rows(font, max_w, face_for=None, renderer="pillow"):
    """The key row's parts split into rows no wider than max_w. A mark and
    the "=..." label after it stay on one row, so a mark never ends one row
    with its label opening the next."""
    parts = legend_parts()
    if not _S.get("page.key_row", True):
        # no key row at all: head_h is a count of these rows times the
        # pitch, so an empty list draws page one from its first band
        return []
    groups = []
    for part in parts:
        follows_mark = groups and groups[-1][-1][0] in (NL_MARK, INDENT_MARK) and part[2] is None
        if groups and ((part[0].startswith(("=", " ")) and part[2] is None) or follows_mark):
            groups[-1].append(part)
        else:
            groups.append([part])
    widths = [sum((WRAP_W * 4 + SWATCH_GAP) if p[2] == "wrap" else
                  _part_width(font, p[0], face_for, renderer)
                  + (2 * SWATCH_PAD + SWATCH_GAP if p[2] is not None else 0) for p in group)
              for group in groups]
    if sum(widths) <= max_w:
        return [[p for group in groups for p in group]]
    # Two rows share the width evenly: a greedy fill puts every key on the
    # first row and one label on the second. The split is the cut that leaves
    # the two rows closest in width with each under max_w; more than two rows
    # fall back to the greedy fill.
    best, best_gap = None, None
    for cut in range(1, len(groups)):
        left, right = sum(widths[:cut]), sum(widths[cut:])
        if left <= max_w and right <= max_w:
            gap = abs(left - right)
            if best_gap is None or gap < best_gap:
                best, best_gap = cut, gap
    if best is not None:
        return [[p for group in groups[:best] for p in group],
                [p for group in groups[best:] for p in group]]
    rows, row, w = [], [], 0.0
    for group, gw in zip(groups, widths):
        if row and w + gw > max_w:
            rows.append(row)
            row, w = [], 0.0
        row.extend(group)
        w += gw
    if row:
        rows.append(row)
    return rows


def legend_row(d, font, x, y, line_h, max_w=None, face_for=None, renderer="pillow", img=None, row_up=0):
    """Draw the key row, on as many rows as the width needs, and hand back
    the height it took. With face_for and img the row's characters draw
    from the same picks, faces and pen steps as the body, so an = in the
    key row is the = of the code. row_up is the rows the body baseline sits
    below the row top for the tallest pick."""
    rows = legend_rows(font, max_w, face_for, renderer) if max_w else [legend_parts()]
    top = y
    for parts in rows:
        _legend_line(d, font, x, y, line_h, parts, face_for, renderer, img, row_up)
        y += line_h + ROW_GAP
    return y - top


def _part_width(font, text, face_for=None, renderer="pillow"):
    """The pixels one key row part takes: the body face's length, or the
    body's own pen steps for its characters when the picks are in play."""
    if face_for is None or text.strip() == "":
        return font.getlength(text)
    pairs = [(ch, (0, 0, 0), False) for ch in text]
    widths, _ids = char_widths(font, pairs, None, face_for, renderer=renderer)
    return float(sum(widths))


def _legend_line(d, font, x, y, line_h, parts, face_for=None, renderer="pillow", img=None, row_up=0):
    cx = float(x)
    for text, ink, band in parts:
        w = _part_width(font, text, face_for, renderer)
        if (face_for is not None and img is not None and band is None and text.strip()
                and (text != "_" or char_over("_", "font"))):
            # every character of the part draws the way the body draws it:
            # its pick's face, its size, its pen step, its clear column
            pairs = [(ch, ink, False) for ch in text]
            widths, _ids = char_widths(font, pairs, None, face_for, renderer=renderer)
            for (ch, _ink, _big), step in zip(pairs, widths):
                if ch != " ":
                    f, dy = face_for(ch, False)
                    for ox, oy in _over_offsets(ch):
                        if renderer == "freetype":
                            backend_text(img, (cx + ox, y + dy + oy), ch, f, ink)
                        else:
                            d.text((cx + ox, y + dy + oy), drawn(ch), font=f, fill=ink)
                cx += step
            continue
        if band == "box":
            # the outline the page draws round a mark, with the page's own
            # background inside, so the key row shows the mark as it lands
            # MARK_BOX_INK at the page's own box width, not band.outline:
            # band.outline is 0 wide on this page and draws nothing
            bw = int(round(1 / img.ratio)) if isinstance(img, Shrunk) else 1
            room = [cx, y + bw, cx + w + 2 * SWATCH_PAD,
                    y + line_h - 2 * bw - BAND_GAP_Y]
            sx = cx + SWATCH_PAD
            for ch in text:
                if face_for is not None and img is not None:
                    f, dy = face_for(ch, False)
                    for ox, oy in _over_offsets(ch):
                        if renderer == "freetype":
                            backend_text(img, (sx + ox, y + dy + oy), ch, f, ink)
                        else:
                            d.text((sx + ox, y + dy + oy), drawn(ch), font=f, fill=ink)
                else:
                    d.text((sx, y), drawn(ch), font=font, fill=ink)
                sx += _part_width(font, ch, face_for, renderer)
            # the outline is fitted to the mark's own pixels once it is
            # drawn, the way the page's own mark boxes are fitted, so the key
            # row shows the same one page pixel of white on all four sides
            # _ink_bounds() skips the first row of its window, and the digits'
            # top row sits on it, so the window reaches 2 rows past the room.
            found = (_ink_bounds(img, (room[0], room[1] - 2, room[2], room[3] + 2))
                     if img is not None else None)
            if found is None:
                d.rectangle(room, outline=MARK_BOX_INK, width=bw)
            else:
                ImageDraw.Draw(img.im if isinstance(img, Shrunk) else img).rectangle(
                    [found[0] - 2, found[1] - 2, found[2] + 2, found[3] + 2],
                    outline=MARK_BOX_INK, width=1)
            cx += w + 2 * SWATCH_PAD + SWATCH_GAP
            continue
        if band == "wrap":
            # inset from the band the same rows the body's mark is, so the key
            # row shows the mark at the size the page draws it
            wrap_edge(d, cx + WRAP_W * 2, y + BAND_TEXT_CLEAR,
                      y + line_h - 1 - BAND_GAP_Y - BAND_TEXT_CLEAR)
            cx += WRAP_W * 4 + SWATCH_GAP
            continue
        if band is not None:
            d.rectangle([cx, y - 1, cx + w + 2 * SWATCH_PAD,
                         y + line_h - 1 - BAND_GAP_Y],
                        fill=TINTS[band % len(TINTS)], outline=OUTLINE if OUTLINE_W else None,
                        width=OUTLINE_W)
            if face_for is not None and img is not None:
                # the swatch digit is the page's own digit, from its pick
                sx = cx + SWATCH_PAD
                for ch in text:
                    f, dy = face_for(ch, False)
                    for ox, oy in _over_offsets(ch):
                        if renderer == "freetype":
                            backend_text(img, (sx + ox, y + dy + oy), ch, f, ink)
                        else:
                            d.text((sx + ox, y + dy + oy), drawn(ch), font=f, fill=ink)
                    sx += _part_width(font, ch, face_for, renderer)
            else:
                d.text((cx + SWATCH_PAD, y + row_up), text, font=font, fill=ink)
            cx += w + 2 * SWATCH_PAD + SWATCH_GAP
        else:
            # a one character part draws from its own override font and size,
            # the way the body draws that character, and twice if thick
            f = font
            if len(text) == 1 and (char_over(text, "font") or char_over(text, "px")):
                try:
                    path = char_over(text, "font")
                    f = dp.load([path] if path else dp.REGULAR,
                                font.size + (char_over(text, "px", 0.0) or 0.0))
                except Exception:  # noqa: BLE001
                    f = font
            for ox, oy in (_over_offsets(text) if len(text) == 1 else ((0, 0),)):
                d.text((cx + ox, y + oy), text, font=f, fill=ink)
            cx += w


# The ink curve. Anti-aliasing stays on, and the glyph mask FreeType blends is
# mapped through a curve before the ink colour is composited, so a pixel above
# the threshold takes the full ink and only a thin ring stays part-blended.
# Turning anti-aliasing off instead breaks small strokes into stubs and makes
# the underscore vanish. Every candidate but "soft" also snaps the pen to a
# whole pixel, because ImageDraw.text carries the fraction of a float x into
# FreeType and blends the stem across two columns. "step" leaves far more ink
# pixels at the full colour than "soft".
INK_CURVE = _S["curve.name"]
# Small pages take their own curve: a page at or under curve.small_px draws
# soft, since the step threshold breaks thin strokes into stubs at that size.
# See style.py, curve.small_px.
SMALL_PX = int(_S.get("curve.small_px", 8) or 0)
SMALL_CURVE = str(_S.get("curve.small_name", "soft") or "soft")
SMALL_THRESHOLD = int(_S.get("curve.small_threshold", 96) or 96)


def curve_for(px):
    """The ink curve name a page of this pixel size draws with."""
    return SMALL_CURVE if px <= SMALL_PX else INK_CURVE


# The edge knob; see style.py, curve.blur.
#
# No hardness multiplier acts on coverage. The renderer carries MacType's two
# curves alone, RenderWeight and Contrast, in freetype_glyph.ink_curve(), and
# MacType has no such control.
BLUR = str(_S.get("curve.blur", "auto") or "auto")
_BLUR_OF = {"hard": "none", "step": "ring", "soft": "full"}


def blur_for(curve):
    """The edge rule for this page: the blur setting, or the one the curve
    name implies."""
    return BLUR if BLUR != "auto" else _BLUR_OF.get(curve, "auto")


def threshold_for(px):
    """The step threshold a page of this pixel size draws with."""
    return SMALL_THRESHOLD if px <= SMALL_PX else CURVE_THRESHOLD

_BIG = {}


def _lut(name, threshold=None, blur="auto"):
    """The 256 entry map from mask value to ink weight, or None for no map.
    threshold is the step or hard cut for this page; None takes the
    global curve.threshold. blur, when not auto, replaces the edge rule the
    name implies: none, ring or full.
    """
    thr = CURVE_THRESHOLD if threshold is None else int(threshold)
    key = (name, thr, blur)
    table = _LUTS.get(key)
    if table is None and blur in ("none", "ring", "full"):
        if blur == "none":
            table = [0 if v < CURVE_RING else 255 for v in range(256)]
        elif blur == "ring":
            table = [0 if v < CURVE_RING else
                     CURVE_RING_WEIGHT if v < thr else 255
                     for v in range(256)]
        else:
            table = list(range(256))
        _LUTS[key] = table
        return table
    if table is None and name in ("step", "hard", "gamma", "sharp"):
        if name == "step":
            # A hard threshold, at half on larger pages, with one blended
            # ring below it.
            table = [0 if v < CURVE_RING else
                     CURVE_RING_WEIGHT if v < thr else 255
                     for v in range(256)]
        elif name == "hard":
            # Hard colour: every pixel that carries any ink past the ring floor
            # draws at the full ink colour, so no pixel is lighter than the ink
            # and no stroke breaks.
            table = [0 if v < CURVE_RING else 255 for v in range(256)]
        elif name == "gamma":
            table = [min(255, round(255 * (v / 255.0) ** CURVE_GAMMA))
                     for v in range(256)]
        else:
            # The sharpening curve for the three-times render: a contrast
            # stretch, so a downsampled pixel over two thirds takes the full
            # ink and only the band between a third and two thirds blends.
            table = [max(0, min(255, round((v - 85) * 255 / 85.0)))
                     for v in range(256)]
        _LUTS[key] = table
    return table


_LUTS = {}


def _big(font):
    """The same face at three times the size, for the downsampled render."""
    key = (getattr(font, "path", ""), font.size)
    big = _BIG.get(key)
    if big is None:
        big = ImageFont.truetype(font.path, font.size * 3)
        _BIG[key] = big
    return big


def ink_text(img, xy, text, font, fill, curve=None, threshold=None,
             blur="auto"):
    """One token drawn as a mask through the ink curve, on a whole pixel.
    curve names the curve for this page and threshold its cut; None takes
    the global ones. blur is the edge knob of style.py.

    This is the Pillow path. It draws nothing on a shipped page, because
    style.glyphrenderer is freetype and every draw site tests for it; it stays
    for the non-FreeType fallback."""
    curve = curve or INK_CURVE
    if curve == "ss3":
        mask, off = _big(font).getmask2(text, mode="L")
        w, h = mask.size
        im = Image.frombytes("L", (w, h), bytes(mask))
        im = im.resize((max(1, round(w / 3.0)), max(1, round(h / 3.0))),
                       Image.LANCZOS).point(_lut("sharp"))
        ox, oy = round(off[0] / 3.0), round(off[1] / 3.0)
    else:
        mask, off = font.getmask2(text, mode="L")
        im = Image.frombytes("L", mask.size, bytes(mask))
        table = _lut(curve, threshold, blur)
        if table:
            im = im.point(table)
        ox, oy = off
    img.paste(fill, (round(xy[0]) + ox, round(xy[1]) + oy), im)


# Set by pack_code while a supersampled page is drawn: the width the page
# shrinks to, or the factor it shrinks by. save_page() then shrinks the
# finished page in memory and writes only the small one, because writing the
# large page as a PNG, reopening it and converting it costs a large share of a
# draw.
SHRINK_TO = None
SHRINK_BY = None
# Band after a line number box starts this many page pixels past the last digit
# ink. Box right line sits 2 page pixels out. Difference is the white.
# Measured, not derived. bw rounds 15.815 layout columns up to 16.
#
# Swept in Inter over 201 line number boxes on one page. The page size stayed
# the same at every value, so a larger clearance costs nothing.
#   3     176 of 201 boxes touched a band
#   3.25  130 of 201
#   3.5    88 of 201
#   4      28 of 201
#   4.5     0 of 201
#   5       0 of 201
# 4.5 is the first value where no band touches a box line, so it is the value.
#
# Run this sweep again after any change to the font, to the shrink, to
# _ink_bounds, or to the box fit of 2 page pixels.
BAND_AFTER_BOX_PX = 4.5
# The direct canvas draws the page at its final size; False keeps the
# whole-page shrink, for a comparison.
DIRECT_CANVAS = True


def save_page(im, path):
    """Save one page with its width and height on the 28 pixel patch grid.

    A size off the grid makes the reader's own pipeline resample the picture,
    and that resampling blurs every glyph after the ink curve has sharpened
    it. The padding is the page background and moves no glyph. It costs no
    extra patch, because the patch count already rounds up, and it cannot
    cross the API cap, because the cap is 1568 pixels, itself 56 whole
    patches.
    """
    # A Shrunk page arrives at its final size and skips the shrink. The flag
    # guards the shrink as well as the padding, so a plain page drawn at a
    # supersample is not shrunk a second time here.
    if (SHRINK_TO or (SHRINK_BY and SHRINK_BY > 1)) and not im.info.get("densepack_small"):
        # the big page is padded to the patch grid first, so the shrink lands
        # on the same pixels as a page written at full size and shrunk
        bw = -(-im.width // dp.PATCH) * dp.PATCH
        bh = -(-im.height // dp.PATCH) * dp.PATCH
        if (bw, bh) != im.size:
            big = Image.new("RGB", (bw, bh), BACKGROUND)
            big.paste(im, (0, 0))
            im = big
        if SHRINK_TO:
            ratio = SHRINK_TO / float(im.width)
            im = im.resize((int(SHRINK_TO), max(1, round(im.height * ratio))), SHRINK_FILTER)
        else:
            im = im.resize((max(1, im.width // SHRINK_BY), max(1, im.height // SHRINK_BY)),
                           SHRINK_FILTER)
    w = -(-im.width // dp.PATCH) * dp.PATCH
    h = -(-im.height // dp.PATCH) * dp.PATCH
    if (w, h) != im.size:
        grid = Image.new("RGB", (w, h), BACKGROUND)
        grid.paste(im, (0, 0))
        im = grid
    if _TRIAL:
        # A search trial keeps its finished page in memory and encodes nothing,
        # because PNG encoding and quantising of pages the search then throws
        # away is the largest part of a draw. _write_trial() encodes the
        # winner's pages once.
        _TRIAL_PAGES[str(path)] = im
        if _NO_GLYPHS:
            _GLYPHLESS.add(str(path))
        else:
            _GLYPHLESS.discard(str(path))
        return im.width, im.height
    dp.save_png(im, path)
    return im.width, im.height


# The search's trial pages, path to image, while pack_code's search branch
# runs. Two trials at most sit here at a time: _forget() drops a loser as soon
# as the comparison is made.
_TRIAL = False
_TRIAL_PAGES = {}
# The trial pages drawn without glyphs, by path.
_GLYPHLESS = set()
# The layout width the last _fit_width() chose, read by _fit_page_width().
_LAST_LAYOUT_W = 0


def _forget(res):
    """Drop a losing trial's pages from memory."""
    if res:
        for f, _w, _h in res[0]:
            _TRIAL_PAGES.pop(str(f), None)


def _write_trial(res, out_stem):
    """Encode the winner's pages onto the final names, <out_stem>-N.png.

    dp.save_png is a function of the image alone, so the bytes are the ones
    a draw that wrote as it went produced. Returns the result with the final
    paths in place of the trial paths."""
    pages = []
    for n, (f, w, h) in enumerate(res[0], 1):
        final = "%s-%d.png" % (out_stem, n)
        im = _TRIAL_PAGES.pop(str(f), None)
        if im is not None:
            dp.save_png(im, final)
        elif str(f) != final:
            dp.replace_retry(str(f), final)
        pages.append((final, w, h))
        if str(f) in PAGE_FIRST_LINE:
            PAGE_FIRST_LINE[final] = PAGE_FIRST_LINE.pop(str(f))
    return (pages,) + tuple(res[1:])


# The drawn line each written image opens on, by image path, counted from 0:
# the number of line ends before the image's first row. _pack_code() fills it
# and _write_trial() moves it onto the final name. pointer.draw_drop_file()
# turns it into a source line number, so a Read that starts at line N gets the
# image that holds line N.
PAGE_FIRST_LINE = {}


# The glyphless trials the width search drew ahead in child processes, by (page
# width, layout width), each a (result, clamp hits) pair. Filled by
# _prefetch_trials(), read and emptied by _fill_bottom() and _fit_width().
_PREFETCH = {}

# The memory all trial helpers of one conversion may hold together, in MB.
# Each helper holds a full layout of the text, so a large file gets fewer
# helpers. DENSEPACK_HELPER_MEMORY_MB changes the budget.
HELPER_MEMORY_MB = int(_os.environ.get("DENSEPACK_HELPER_MEMORY_MB", "4000"))


def _prefetch_trials(text, px, python, reader, title, out_stem, jobs):
    """Draw every glyphless trial the search will ask for, at once, in as
    many child processes as the machine has cores, each child taking a
    share of the jobs in turn. jobs is [(page width, layout width)]. Fills
    _PREFETCH; on any failure, or with DENSEPACK_SERIAL_DRAW set, leaves it
    empty and the search draws each trial itself. A child imports this
    module, takes the parent's settings whole, and answers with each
    trial's page sizes, clamp count and the two numbers pack_code returns
    beside the pages. No image crosses a pipe and no file is written.

    The jobs go through a file each, not a child's stdin: a Windows pipe
    holds about 4 KB, so a larger job written to stdin blocks the parent
    until that child has imported this module and read it, and the children
    run one after another. Process creation and the repeated import cost
    most of a one-job child's time, so a child takes several jobs."""
    import json
    import os
    import pickle
    import subprocess
    import tempfile
    _PREFETCH.clear()
    # Text of 10 KB or less converts in this process: 12 helpers cost it about
    # 430 MB and gain no time.
    if os.environ.get("DENSEPACK_SERIAL_DRAW") or not jobs or len(text.encode("utf-8")) <= 10_000:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    # One helper holds about 60 MB plus 0.9 MB for every KB of text: a 1 MB
    # file peaked at 12,627 MB with 12 helpers. The helpers together stay
    # under HELPER_MEMORY_MB.
    per_helper_mb = 60 + 0.9 * len(text.encode("utf-8")) / 1000
    workers = max(1, min(len(jobs), os.cpu_count() or 1,
                         int(HELPER_MEMORY_MB // per_helper_mb)))
    shares = [jobs[i::workers] for i in range(workers)]
    procs = []
    try:
        for share in shares:
            job = {"text": text, "px": px, "python": python, "reader": reader,
                   "title": title, "settings": dict(_S), "stem": out_stem,
                   "trials": share}
            fd, job_path = tempfile.mkstemp(prefix="densepack-trial-", suffix=".pkl")
            with os.fdopen(fd, "wb") as fh:
                pickle.dump(job, fh)
            code = ("import sys; sys.path.insert(0, %r); import codepack; "
                    "codepack._trial_child(%r)" % (here, job_path))
            # "-c" puts the working folder on sys.path. The hook's working
            # folder is the user's project, so the child runs from this
            # scripts folder, where a project cannot plant a module.
            p = subprocess.Popen([sys.executable, "-c", code], cwd=here,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            procs.append(p)
        found = {}
        for p in procs:
            data, err = p.communicate()
            if p.returncode != 0:
                raise RuntimeError(err[-400:])
            for rec in json.loads(data):
                page_w, lw = rec["page_w"], rec["lw"]
                pages = [("%s.w%d.t%d-%d.png" % (out_stem, page_w, lw, i + 1), w, h)
                         for i, (w, h) in enumerate(rec["pages"])]
                found[(page_w, lw)] = ((pages, rec["target"], rec["line_h"]), rec["hits"])
        for f, _w, _h in (r[0][0][k] for r in found.values() for k in range(len(r[0][0]))):
            _GLYPHLESS.add(f)
        _PREFETCH.update(found)
    except Exception:  # noqa: BLE001
        _PREFETCH.clear()
        for p in procs:
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass


def _trial_child(job_path):
    """The child of _prefetch_trials(): its share of glyphless trials from
    the pickled job at job_path, which it removes, answered as one JSON
    list on stdout."""
    import json
    import os
    import pickle
    with open(job_path, "rb") as fh:
        job = pickle.load(fh)
    try:
        os.remove(job_path)
    except OSError:
        pass
    _S.clear()
    _S.update(job["settings"])
    global _FILL_GUARD, _NO_GLYPHS, _TRIAL
    _FILL_GUARD = True
    _NO_GLYPHS = True
    _TRIAL = True
    out = []
    for page_w, lw in job["trials"]:
        _S["page.code_width"] = page_w
        _S["page.code_layout_width"] = lw
        CLAMP_HITS[0] = 0
        res = pack_code(job["text"], job["px"], "%s.w%d.t%d" % (job["stem"], page_w, lw),
                        job["python"], None, None, job["reader"], job["title"])
        out.append({"page_w": page_w, "lw": lw, "hits": CLAMP_HITS[0],
                    "pages": [(w, h) for _f, w, h in res[0]],
                    "target": res[1], "line_h": res[2]})
        _TRIAL_PAGES.clear()
    sys.stdout.write(json.dumps(out))


# The underscore draws through backend_text() like every other character.
# Inter's underscore is a solid bar at every size the page uses, and a drawn
# rectangle in its place spans its whole cell with none of a glyph's side
# bearing, so it would touch the bracket beside it.


# THE SPACING MAP. Every constant that puts white on a page is named here,
# with what it moves. They are read in three places, this block, the head of
# the file and page.pad near the page size, and they are all in layout
# columns.
#
# What a layout column is worth. The layout runs larger than the page and the
# page is shrunk out of it, so a constant of 1 is a fraction of a page pixel,
# not a page pixel. There are two shrinks and they are not the same:
#
#   the narrow page, page.supersample 3 and no page.code_width: the layout
#   is three times the page, so 3 layout columns are 1 page pixel
#   the wide page, page.code_layout_width laid out at
#   page.code_supersample and shrunk to page.code_width: 1 page pixel is
#   1 / Shrunk.ratio layout columns
#
# So on the page a reader actually sees, MARK_CLEAR at 3 is 2.276 page
# pixels and BAND_GAP_X at 1 is 0.759. Anything that has to land on a whole
# page pixel is measured in bw instead, which the draw loop sets to
# round(1 / img.ratio), one page pixel in layout columns for the page in
# hand. The mark box and the band edges beside it are drawn in bw.
#
# The one gap size the page has is the white between two bands, and it
# measures 1 page pixel. Every other gap is matched against it.
#
#   PAD             page.pad, the white margin round the whole page
#   GAP             space.block_gap, after every line end, so blocks separate
#   BAND_GAP_X      white columns kept between two bands in a row
#   BAND_GAP_Y      white rows kept under every band
#   ROW_GAP         space.row_gap, added to the line height for the row pitch
#   BAND_PAD_X/Y    the band grown past its text, left and right, top and foot
#   BAND_OFF_X/Y    the band moved without moving its glyphs
#   BAND_INSET      band.text_inset, the glyphs moved in from the band's edge
#   EDGE_INSET      the band started left of the first glyph, out of GAP
#   LETTER_SPACE    space.letter, added to every pen step
#   CLEAR           space.clear, white columns between two glyphs
#   CLEAR_NARROW    the same for a pair where either glyph is narrow
#   NARROW_COLS     how few inked columns count as narrow
#   SAME_CLEAR      the same for two of one letter
#   QUOTE_RUN_CLEAR the same for two quote marks of one kind
#   STEM_QUOTE_CLEAR the same for an l against a quote
#   STEP_RIGHT      the white a mark keeps on its right
#   MARK_CLEAR      white round a mark that sits outside the bands
#   COUNT_CLEAR     white a count leaves before the word after it
#   BOX_CLEAR       white between a mark box and the band after it
#   BOX_GAP         mark.box_gap, the room the line break leaves before the
#                   next line number's box
#   SEAM_GAP        mark.seam_gap, white, the seam rule and white between a
#                   line number and an indent count
#   SWATCH_PAD/GAP  the key row's own padding and the gap between its parts
#
# The mark box itself takes no constant. It is fitted to the pixels its
# digits drew, two page pixels out on every side, so one page pixel of white
# is left inside it whatever the shrink rounds to: see _ink_bounds().

# The block gap that follows every line end, so blocks separate.
GAP = _S["space.block_gap"]
# The band starts EDGE_INSET columns to the left of the first glyph, inside the
# gap that already sits between two blocks, so the outline and the wrap edge
# never cover the first column of a letter. The glyphs and the row widths do
# not move, so no row wraps differently and no page grows.
# White between bands: gap_x columns stay white between two blocks in a row, so
# the inset never eats them; gap_y rows stay white under every band, taken from
# the row's own spare pixel.
BAND_GAP_X = int(_S.get("band.gap_x", 1) or 0)
BAND_GAP_Y = int(_S.get("band.gap_y", 1) or 0)
ROW_GAP = int(_S.get("space.row_gap", 0) or 0)
# The line end mark outside its band, in the white between two blocks.
PILCROW_OUTSIDE = bool(_S.get("mark.pilcrow_outside", True))
FILL = float(_S.get("page.fill", 0) or 0)
MARK_CLEAR = int(_S.get("mark.clear", 0) or 0)

# WRAP_GUTTER is the width a row keeps free on its right. The wrap mark draws
# in that width. The draw site puts the mark past the last character of the
# row. wrap_edge() then holds the mark inside the page. A gutter that is too
# small makes wrap_edge() move the mark left, onto the text.
#
# WRAP_SLACK is the last part of the gutter. It is set by measurement, not by
# calculation. Read the two rules below before you change it.
#
# RULE 1. Do not scale this constant with the page. The block in demo() at the
# end of this file multiplies every spacing constant by the supersample. Add
# WRAP_GUTTER to that list and the gutter grows to 15 page pixels. The clamp
# then fires more often, not less, and pages grow, because _fit_width() answers
# a narrower row by widening the layout, so it spends the width the gutter
# saves.
#
# RULE 2. Do not add the ink a glyph lays past its own advance. That ink is 1
# page pixel in Inter over every printable ASCII character. Adding it measures
# worse: more rows end within 2 page pixels of the edge.
#
# With no gutter the clamp fires many times on a long file and drags a mark up
# to about 15 page pixels onto the text; with a 15 column gutter and the inset
# charged it fires far less and the worst drag is under 3 page pixels.
WRAP_SLACK = 0
WRAP_GUTTER = (MARK_CLEAR + BAND_PAD_X + BAND_INSET + WRAP_W * 1.5 + 2
               + WRAP_SLACK)
# the clear columns after a count digit before the word that follows it
COUNT_CLEAR = int(_S.get("mark.count_clear", MARK_CLEAR) or MARK_CLEAR)
# the pen distance between two quote marks of one kind in a row
QUOTE_RUN_CLEAR = int(_S.get("space.quote_run_clear", 0) or 0)
QUOTES = "\"'`"
# the pen distance between two of the same letter in a row
SAME_CLEAR = int(_S.get("space.same_clear", 0) or 0)
# The stems that read as part of a quote when they touch one.
STEMS = "lI1i|"
# a stem before any of these keeps the quote clearance, the closing marks and
# the two curly closers included: build_flow() turns the second double quote of
# a line into the closing curly quote before the layout runs, so without the
# closers the l of jsonl" would never meet this rule.
STEM_CLOSERS = QUOTES + ">)]}" + "”" + "’"
STEM_QUOTE_CLEAR = int(_S.get("space.stem_quote_clear", 0) or 0)
# Clear columns after a mark that steps by its ink, so the white on its right
# matches the white on its left.
STEP_RIGHT = int(_S.get("mark.step_right", 0) or 0)
THICK_DX = 1
EDGE_INSET = max(0, min(GAP - 1 - BAND_GAP_X,
                        max(OUTLINE_W, WRAP_W) + 1 + MARK_CLEAR))


# The glyph renderer. "freetype" draws every character through FreeType with
# MacType's flags and ink curve, on every platform, and it is what style.py
# sets. Anything else falls to Pillow. FreeType draws the same grey on every
# platform, and MacType's curve is measured against it.
RENDERER = str(_S.get("glyphrenderer") or "pillow")


def glyph_renderer(font):
    """Which backend draws this face: "freetype" or "pillow".

    FreeType is the only backend, and it runs on every platform. A face it
    cannot open falls back to Pillow, so the page still draws.
    """
    if RENDERER == "freetype" and freetype_glyph.available(font.path):
        return "freetype"
    return "pillow"


def glyph_backend():
    """The module the draw sites call for a mask and a pen step."""
    return freetype_glyph


def _pillow_length(font, ch):
    return font.getlength(drawn(ch)) * getattr(font, "scale_x", 1.0)


def backend_length(font, ch):
    """The backend's pen step for one character, in pixels, fraction kept.

    The step is not rounded to a whole pixel. Rounding does not err the same
    way for every letter: against Inter's own advances at 12 px, b, d, p and
    q each lose 0.49 px while f, g and s each gain about 0.4, so two letters
    of the same apparent width step a whole pixel apart.

    The fraction is safe to keep because backend_text() draws the glyph at
    it, through freetype_glyph.split_pen(). A fractional step without that
    only moves the rounding to paste time and leaves the gaps as uneven.
    """
    # CACHED across the search's trials: a step depends on the face file, its
    # size, the bold flag, the scale and the character, and on nothing a trial
    # changes.
    key = (font.path, font.size, getattr(font, "sim_bold", False),
           getattr(font, "scale_x", 1.0), ch)
    hit = _LENGTH_CACHE.get(key)
    if hit is None:
        hit = float(glyph_backend().advance(font.path, font.size, drawn(ch),
                                            key[2], key[3]))
        _LENGTH_CACHE[key] = hit
    return hit


_LENGTH_CACHE = {}
_SPAN_CACHE = {}


def backend_span(font, ch, seen):
    """First and last column the backend inks above INK_FLOOR for this
    character, its pen at 0.

    The backend twin of ink_span(), read from the mask the page pastes by the
    floor ink_span() reads Pillow's mask by, so a faint edge column counts as
    ink on neither path.
    """
    span = seen.get(ch)
    if span is None:
        # The module cache outlives the caller's seen dict, so the search's
        # later trials find every span measured by the first.
        key = (font.path, font.size, getattr(font, "sim_bold", False),
               getattr(font, "scale_x", 1.0), ch)
        if key in _SPAN_CACHE:
            span = _SPAN_CACHE[key]
            seen[ch] = span
            return span
        mask, left, _top = glyph_backend().glyph(
            drawn(ch), font.path, font.size, key[2], key[3])
        span = None
        if mask is not None:
            w, h = mask.size
            data = mask.tobytes()
            cols = [i for i in range(w)
                    if any(data[j * w + i] > INK_FLOOR for j in range(h))]
            span = (left + cols[0], left + cols[-1]) if cols else None
        seen[ch] = span
        _SPAN_CACHE[key] = span
    return span


def backend_spills(pairs, face_for):
    """True when one character of this flow inks a column outside the span
    Pillow's layout clears for it.

    The layout keeps Pillow's advances while every backend glyph fits inside
    the columns ink_span() measured, because the clearance between neighbours
    then holds as drawn. When one spills, the page takes its advances and its
    spans from the backend instead.
    """
    seen_p = {}
    seen_b = {}
    for ch, big in {(p[0], p[2]) for p in pairs}:
        f = face_for(ch, big)[0]
        here = ink_span(f, ch, seen_p.setdefault(f.size, {}))
        there = backend_span(f, ch, seen_b.setdefault(f.size, {}))
        if there is None:
            continue
        if here is None or there[0] < here[0] or there[1] > here[1]:
            return True
    return False


def paste_ink(im, fill, box, mask):
    """One glyph composited the way MacType composites it, in linear light.

    Pillow's Image.paste blends the sRGB numbers themselves, so a pixel at half
    coverage lands halfway between the two sRGB values. Light does not add that
    way: half the light of full ink is a much darker sRGB number than the
    midpoint. The result is the washed grey fringe that makes an anti-aliased
    letter look soft beside a drawn rectangle, which has no partly covered
    pixels to wash.

    MacType converts both colours through its gamma transfer, tbl1 in
    CAlphaBlend::init, blends there, and converts the result back. That is what
    this does. With GAMMA_MODE at -1 the transfer is linear and this is
    arithmetically identical to Pillow's blend, which is why MacType's own
    default changes nothing until the mode is set.
    """
    tbl = glyph_backend().transfer_to_linear()
    if _np is None or glyph_backend().GAMMA_MODE < 0:
        im.paste(fill, box, mask)
        return
    x, y = int(box[0]), int(box[1])
    mw, mh = mask.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(im.width, x + mw), min(im.height, y + mh)
    if x1 <= x0 or y1 <= y0:
        return
    a = (_np.asarray(mask, dtype=_np.float32)[y0 - y:y1 - y, x0 - x:x1 - x]
         / 255.0)[..., None]
    to_lin = _np.asarray(tbl, dtype=_np.float32)
    from_lin = _np.asarray(glyph_backend().transfer_from_linear(),
                           dtype=_np.uint8)
    region = _np.asarray(im.crop((x0, y0, x1, y1)).convert("RGB"))
    lit = to_lin[region] * (1.0 - a) + to_lin[_np.asarray(fill, dtype=_np.uint8)] * a
    idx = _np.clip((lit * (from_lin.shape[0] - 1)).astype(_np.int32),
                   0, from_lin.shape[0] - 1)
    im.paste(Image.fromarray(from_lin[idx]), (x0, y0))


def backend_text(img, xy, ch, font, fill):
    """One character drawn by the backend, its baseline on the row Pillow's
    would use.

    Pillow's text call puts the face's ascent line at xy[1], so its baseline
    sits the ascent lower; the backend measures its mask from the baseline,
    top negative above it, so the mask goes at that row plus top.

    The mask arrives already inked by MacType's curve, in
    freetype_glyph.ink_curve(), which is RenderWeight and Contrast. Nothing
    else touches its coverage.
    """
    # MacType rasterises a glyph at the size it is shown at, and every setting
    # that helps a small glyph, hinting, stem darkening and increase-x-height,
    # is defined to act at that size. Asking for a large glyph and shrinking it
    # averages the ink away and discards all three.
    #
    # So when the layout is wider than the page, the glyph is asked for at the
    # size it will land at rather than drawn large and squeezed.
    # WHERE THE PEN'S FRACTION IS DRAWN. split_pen() picks the whole pixel to
    # paste on and the fraction to render the glyph at, together. Taking the
    # whole pixel with round() and throwing the fraction away makes the spacing
    # uneven: the pen steps Inter asks for are fractions and no two letters
    # lose the same amount to rounding. The two must be picked together,
    # because a pen at x.9 belongs on the pixel above x, not on x.
    ratio = getattr(img, "ratio", None)
    if GLYPH_AT_FINAL_SIZE and ratio and ratio < 1.0:
        small = max(1.0, font.size * ratio)
        column, phase = glyph_backend().split_pen(xy[0] * ratio)
        mask, left, top = glyph_backend().glyph(
            drawn(ch), font.path, small,
            getattr(font, "sim_bold", False),
            getattr(font, "scale_x", 1.0),
            char_over(ch, "weight", 1.0) or 1.0, phase)
        if mask is None:
            return
        top -= baseline_lift(ch, mask, top)
        base = int(round(xy[1] * ratio)) + int(round(font.getmetrics()[0] * ratio))
        # paste_ink, not img.im.paste. Pillow's own paste mixes the two colours
        # as sRGB numbers. Light does not mix that way, so a half covered pixel
        # comes out far too dark and every glyph grows a hard grainy edge.
        paste_ink(img.im, fill, (column + left, base + top), mask)
        return
    column, phase = glyph_backend().split_pen(xy[0])
    mask, left, top = glyph_backend().glyph(
        drawn(ch), font.path, font.size,
        getattr(font, "sim_bold", False),
        getattr(font, "scale_x", 1.0),
        char_over(ch, "weight", 1.0) or 1.0, phase)
    if mask is None:
        return
    # Every glyph the page draws comes through here, the body, the key row and
    # the marks alike, so the bracket lift is charged once and in one place.
    top -= baseline_lift(ch, mask, top)
    base = round(xy[1]) + font.getmetrics()[0]
    if isinstance(img, Shrunk) and img.ratio == 1.0:
        # The native layout: page space and layout space are one space, so
        # there is nothing to shrink and the glyph composites straight through
        # the gamma blend.
        paste_ink(img.im, fill, (column + left, base + top), mask)
        return
    if isinstance(img, Shrunk):
        # base is the row's baseline and every face on the row lands on it,
        # because face_for's dy is the ascent difference: see Shrunk.paste.
        img.paste(fill, (column + left, base + top), mask, anchor=base)
        return
    img.paste(fill, (column + left, base + top), mask)


def char_widths(font, pairs, big_font=None, face_for=None, renderer="pillow",
                shifts=None, spans=None):
    """The drawn width of every character in the flow, and its line id.

    shifts, when a list is passed, is filled with one draw offset per
    character: the columns an INK_STEP mark's glyph moves left so its ink
    starts CLEAR columns from the origin, zero for everything else.

    spans, when a list is passed, is filled with one (first, last) inked
    column per character, the glyph's own draw point at 0, and None for a
    character that inks nothing. The mark box is drawn from these, because a
    cell is wider than the ink inside it.

    renderer "freetype" measures with the backend that draws the glyph,
    backend_length() and backend_span(); any other value measures with
    Pillow.

    The id steps after each pilcrow, so every character of one source line
    carries the same id whatever row it lands on.

    One clear column sits between two glyphs, so no ink of one sits next to
    or diagonal from ink of the next. A second clear column is added when
    either glyph inks three columns or fewer, or when the two glyphs are the
    same, because a run of narrow letters such as the c, i, f and i inside
    hookSpecificOutput does not separate with one column. Asking every pair
    for the second column costs far more width, so the narrow test stays.
    """
    widths = []
    ids = []
    lid = 0
    # One ink span cache a face size: a character inks different columns at
    # each size, so two faces cannot share one. Keyed by size rather than by
    # a big flag, because font.group_px can put more than two faces on a page.
    seen = {}
    length, span = ({"freetype": (backend_length, backend_span)}
                    .get(renderer, (_pillow_length, ink_span)))

    def face(k, borrow=True):
        """The face that sets pairs[k]'s cell. A BIGGER mark keeps the body
        face's cell, its pen step and its clear columns, and draws its larger
        glyph inside it."""
        p = pairs[k]
        big = p[0] not in BIGGER and len(p) > 2 and p[2]
        if face_for is not None:
            return face_for(p[0], big, borrow)[0]
        return big_font if (big_font is not None and big) else font

    for k, item in enumerate(pairs):
        ch = item[0]
        f = face(k)
        # The pen step comes from the face measured here. The clearance below
        # measures the ink the glyph really draws, so a wider glyph still gets
        # its clear column and no two glyphs touch.
        body = face(k, borrow=False)
        own = length(f, ch) if f.path != body.path else max(length(body, ch), length(f, ch))
        # THE PEN KEEPS ITS FRACTION. A fractional step on its own does not
        # help: it gives each pair a different remainder and every glyph still
        # pastes on a whole pixel, so the gaps come out uneven. backend_text()
        # renders each glyph at its own offset through
        # freetype_glyph.split_pen(), so the fraction is drawn rather than
        # rounded away and the step can carry it.
        w = float(own + LETTER_SPACE + (char_over(ch, "adv", 0) or 0))
        # True once a MARK clearance has been charged to this step: the room a
        # line number box, an indent count, a seam or a line break needs. The
        # exact ink gap below must not overwrite those, because they are what
        # holds the boxes apart from each other and from the band.
        charged = False
        if ch == NL_MARK:
            # THE LINE END MARK NEVER DRAWS, and this does not ask a style
            # override whether it does. Blanking the pilcrow by a glyph
            # substitution is not the same as not drawing it: removing that
            # override would move this branch to the else and widen every row
            # on the page.
            #
            # The mark stays in the stream because it carries the band, the row
            # break rule, the band edge and the line id. It is not a character
            # a reader sees. The mark takes no glyph advance and no clear space
            # of its own, because nothing is drawn for it. It keeps BOX_CLEAR,
            # the white between the last letter and the next band.
            #
            # What the mark does carry is the only space that exists before the
            # next line number's box, and four things have to fit in it: the
            # last character's own clear column, the band edge one page pixel
            # past that ink, the white before the box and the box's own line.
            # BOX_CLEAR alone leaves almost no white on the left of a box, so
            # mark.box_gap is the rest of the room; see style.py for the sweep
            # that set it.
            #
            # BAND_PAD_X and BAND_INSET widen the band drawn round the run that
            # follows, on both sides, and they are not charged here.
            # flow_rows() already charges BAND_INSET at every segment start,
            # and WRAP_GUTTER already reserves BAND_PAD_X and BAND_INSET for
            # the mark. Charging them here counts them a second time, so
            # _fit_width() accepts layouts it should refuse and wrap marks move
            # onto text.
            w = float(BOX_CLEAR + 1 + BOX_GAP)
            charged = True
        elif _is_count(pairs[k]) and not (k + 1 < len(pairs) and _is_count(pairs[k + 1])):
            # the last digit of a count: clear space before the word after it
            w += COUNT_CLEAR
            charged = True
        elif (_is_count(pairs[k]) and k + 1 < len(pairs)
              and _is_count(pairs[k + 1]) and pairs[k + 1][1] != pairs[k][1]):
            # the seam between a green line number and a red indent count,
            # where the divider draws. It holds white, the rule and white,
            # the same page pixel each: see mark.seam_gap in style.py
            w += SEAM_GAP
            charged = True
        here = span(f, ch, seen.setdefault(f.size, {}))
        if spans is not None:
            # the raw span, its own draw point at 0, before the INK_STEP
            # rebase below moves the origin
            spans.append(here)
        shift = 0
        if ch in INK_STEP and here is not None:
            # A mark steps by its ink, not by its face's advance: a glyph from
            # a monospace face carries that face's whole cell as its advance,
            # so a comma would sit in far more white than a period. The glyph
            # moves left so its ink starts CLEAR columns from the origin, the
            # pen steps to just past the ink, and the pair rule below adds the
            # same clearance every other pair gets.
            shift = CLEAR - here[0]
            here = (CLEAR, here[1] + shift)
            w = float(round(here[1] + 1 + LETTER_SPACE + (char_over(ch, "adv", 0) or 0)))
        nxt = pairs[k + 1][0] if k + 1 < len(pairs) else None
        if ch in INK_STEP and nxt == " " and STEP_RIGHT:
            # A space after a mark keeps a full space. The pen steps to just
            # past the mark's ink, and a letter's own side bearing is what
            # makes a plain space wide, so without this the white after "aa, "
            # is barely more than after "aa," and a reader drops the space. The
            # mark's right step goes on top of the space.
            w += STEP_RIGHT
        if nxt is None:
            after = None
        else:
            nf = face(k + 1)
            after = span(nf, nxt, seen.setdefault(nf.size, {}))
            if nxt in INK_STEP and after is not None:
                after = (CLEAR, after[1] - after[0] + CLEAR)
        if here is not None and after is not None:
            clear = CLEAR
            # The underscore mark takes the wider clearance whatever it sits
            # beside. Its ink span is four columns at 10 px, wide enough to
            # miss the narrow test above, and the pair rule would then leave
            # one clear column between the mark and the letter after it, which
            # a reader reads as a letter that is not on the page.
            if (ch == nxt or UND_MARK in (ch, nxt)
                    or here[1] - here[0] <= NARROW_COLS
                    or after[1] - after[0] <= NARROW_COLS):
                clear = CLEAR_NARROW
            if UND_MARK in (ch, nxt):
                # the mark keeps the marks' own clearance whatever the letter
                # clearance is set to
                clear = max(clear, MARK_CLEAR)
            if ch == nxt and ch in QUOTES and QUOTE_RUN_CLEAR:
                # three quotes in a row read as three, not as a run of hooks
                clear = max(clear, QUOTE_RUN_CLEAR)
            elif ch == nxt and SAME_CLEAR:
                # two of one letter keep a column more: the f's crossbar
                clear = max(clear, SAME_CLEAR)
            if STEM_QUOTE_CLEAR and ((ch in STEMS and nxt in STEM_CLOSERS)
                                     or (ch in QUOTES and nxt in STEMS)):
                # the bar of an l against the bars of a quote or a closing
                # mark: without it jsonl" reads as json" and transcript.jsonl>
                # as transcript.json>
                clear = max(clear, STEM_QUOTE_CLEAR)
            if ch in INK_STEP and STEP_RIGHT:
                # the mark's right side keeps the white its left side has
                clear = max(clear, STEP_RIGHT)
            # EXACT, not a floor, when space.ink_gap_exact is on.
            #
            # here[1] is this glyph's last inked column and after[0] the next
            # glyph's first, both from the glyph's own pen, so this sets the
            # distance from ink to ink. With max() it is only a MINIMUM: a pair
            # sitting closer than `clear` is pushed apart and a pair already
            # further apart is left alone, so the gaps stay as uneven as the
            # font's side bearings make them.
            #
            # Assigning instead pulls the wide pairs in as well, so every pair
            # carries the same white. It gives up the rhythm the designer drew,
            # which is the trade: a reader that has to decide where one word
            # ends cannot use that rhythm anyway at eleven pixels.
            #
            # The floor below keeps a step from going backwards on a pair whose
            # ink already overlaps its own cell, which t and x do at this size.
            # ONLY ON AN ORDINARY PAIR. Assigning here discards whatever this
            # step already carried, and a step that has had a mark clearance
            # charged to it carries the room a line number box, an indent
            # count, a seam or a line break needs. Overwriting those runs the
            # boxes into each other and into the band.
            want = here[1] + clear - after[0]
            if EXACT_INK_GAP and not charged:
                w = float(max(1.0, want))
            else:
                w = max(w, want)
        widths.append(w)
        ids.append(lid)
        if shifts is not None:
            shifts.append(shift)
        if ch == NL_MARK:
            lid += 1
    return widths, ids


# One character, everywhere it appears: its ink, size, nudge, width and weight,
# set once. Empty in the shipped renderer, so nothing below changes a pixel
# until style.json names a character.
FONT_MAX_PX = int(_S.get("char.font_max_px", 9) or 0)
CHAR_OVER = {k: dict(v) for k, v in (_S.get("char.overrides") or {}).items()
             if isinstance(v, dict)}


def char_over(ch, field, default=None):
    """The override field for one character, or default."""
    entry = CHAR_OVER.get(ch)
    if not entry:
        return default
    value = entry.get(field, default)
    if field == "ink" and isinstance(value, (list, tuple)):
        return tuple(int(v) for v in value)
    return value


# The four marks readers swap for each other: at small sizes the semicolon and
# the colon differ by one pixel, and the comma and the period by two, so
# "a,b:c;d" reads back as "a.b;c:d".
TAILED = tuple(_S["code.tailed"])


def tail_box(font, ch, line_h, seen):
    """The block drawn under a comma or a semicolon, or None when it will not
    fit inside the row.

    Two pixels one row below the glyph's own lowest ink, in the columns that
    ink already holds. A period and a colon get nothing there, so the pair
    differs by a whole row instead of by one pixel. It moves no glyph and
    costs no width. The comma draws from the face one px larger and sits one
    row higher on the same baseline, so the row below its ink is clear and
    the tail is drawn at every size this packer uses.
    """
    key = (ch, line_h, font.size)
    if key in seen:
        return seen[key]
    box = font.getbbox(ch)
    mask = font.getmask(ch, mode="L")
    w, h = mask.size
    data = bytes(mask)
    ink = [(j, i) for j in range(h) for i in range(w)
           if data[j * w + i] > INK_FLOOR]
    out = None
    if ink:
        low = max(j for j, _i in ink)
        left = min(i for j, i in ink if j == low)
        y0 = box[1] + low + 1
        if y0 <= line_h - 2:
            x0 = box[0] + left
            out = (x0, y0, x0 + 1, y0)
    seen[key] = out
    return out


# A word is what a reader has to hold together to use it: letters, digits,
# and the underscores, dots, slashes and hyphens that build an identifier or
# a path. main.gd and _fit_height are each one word by this rule.
WORD_CHARS = _S["code.word_chars"]


def _ink_bounds(img, box):
    """The glyph pixels drawn inside a window, in the page's own pixels.

    This is how the mark box is placed. The box is drawn at these bounds less
    and plus two page pixels on every side, and Pillow draws an outline on the
    box's own edge, so exactly one page pixel of white is left inside it
    between the outline and the digits, on all four sides.

    Why it is fitted and not calculated, twice over.

    A digit's cell is wider than the ink in it, because the cell carries the
    glyph's own advance and its side bearings. A box drawn round the cells
    holds the cell minus the ink as white, and no clearance knob reaches it.

    Drawing round the ink span instead fixes the left and the right to within
    a pixel and no further. Shrunk.paste puts a glyph's mask on the output
    grid by the row's baseline and the mask's own height, so a glyph lands a
    whole page pixel away from where the layout coordinate rounds to, and by a
    different amount per row. Reading the page back removes the rounding from
    the question. The page background and a band tint are both flat colour,
    so anything else inside the window is a glyph.
    """
    im = img.im if isinstance(img, Shrunk) else img
    out = img._out if isinstance(img, Shrunk) else (lambda v: int(round(v)))
    x0, y0, x1, y1 = out(box[0]), out(box[1]), out(box[2]), out(box[3])
    w, h = im.size
    px = im.load()
    flat = set(TINTS) | {tuple(BACKGROUND)}
    xs, ys = [], []
    for y in range(max(0, y0 + 1), min(h, y1)):
        for x in range(max(0, x0 + 1), min(w, x1)):
            if px[x, y] not in flat:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _seam_column(img, bounds, near):
    """The page column a seam rule draws on: the middle of the white run
    between two mark runs, so the rule keeps white on both sides of it."""
    im = img.im if isinstance(img, Shrunk) else img
    px = im.load()
    x0, y0, x1, y1 = bounds
    bg = tuple(BACKGROUND)
    runs = []
    for x in range(x0, x1 + 1):
        if all(px[x, y] == bg for y in range(y0, y1 + 1)):
            if runs and x - runs[-1][1] == 1:
                runs[-1][1] = x
            else:
                runs.append([x, x])
    if not runs:
        return near
    a, b = min(runs, key=lambda r: min(abs(r[0] - near), abs(r[1] - near)))
    return (a + b) // 2


def _is_count(pair):
    """True for a blank-line count digit or its mark: mark ink, not text."""
    ch, ink = pair[0], pair[1]
    return ink in (BLANK_INK, PILCROW_INK, COUNT_INK) and (ch.isdigit() or (BLANK_MARK and ch == BLANK_MARK)
                                                or (INDENT_MARK and ch == INDENT_MARK))


def word_char(ch):
    """True for a character that may not be cut from its neighbour."""
    return ch.isalnum() or ch in WORD_CHARS


def _over_offsets(ch):
    """Where a character draws: once at its own spot, nudged by its dx and
    dy override, and a second time one pixel right when thick is set."""
    nudge = DY_BY_CHAR.get(ch, 0)
    if ch not in CHAR_OVER:
        return ((0, nudge),) if nudge else ((0, 0),)
    dx = char_over(ch, "dx", 0) or 0
    dy = (char_over(ch, "dy", 0) or 0) + nudge
    if char_over(ch, "thick", False):
        return ((dx, dy), (dx + THICK_DX, dy))
    return ((dx, dy),)


def _marked(p):
    """True for a line end mark, a blank run count, or the blank run bullet."""
    return p[0] in (NL_MARK, BLANK_MARK) or _is_count(p)


# an opening quote never ends a row and a closing quote never opens one, the
# same as the brackets; the pipe never sits at either end of a row
OPENERS = "([{" + '"' + "'" + "|"
CLOSERS = ")]}" + "\u201d" + "\u2019" + "|"


def split_here(pairs, k):
    """True if a row may end just before pairs[k].

    A line end mark and the count of blank lines after it are one thing a
    reader reads at once, so no row ends between them.
    """
    # The line-break mark, its count, the indent mark and its number and the
    # line's first word stay on one row: no row ends anywhere inside that run,
    # so the whole run moves to the next row with the word before the break.
    if INDENT_MARK:
        q = k - 1
        while q >= 0 and _marked(pairs[q]) and pairs[q][0] != NL_MARK:
            q -= 1
        if any(pairs[t][0] == INDENT_MARK for t in range(q + 1, k)):
            return False
    # An opening bracket never ends a row and a closing bracket never opens
    # one: a lone ( at a row's end and a lone ] or ) at a row's start costs a
    # reader a re-read.
    # looked at past any spaces, so "| " at a row's end and " )" at a row's
    # start are caught too
    q = k - 1
    while q > 0 and pairs[q][0] == " ":
        q -= 1
    if pairs[q][0] in OPENERS:
        return False
    r = k
    while r < len(pairs) - 1 and pairs[r][0] == " ":
        r += 1
    if pairs[r][0] in CLOSERS:
        return False
    if _marked(pairs[k - 1]) and _marked(pairs[k]):
        return False
    # A row never opens with a line break: the mark stays on the row of the
    # word it ends, so a wrap edge, which says the line runs on, is never
    # followed by a break as the first thing on the next row.
    if pairs[k][0] == NL_MARK:
        return False
    return not (word_char(pairs[k - 1][0]) and word_char(pairs[k][0]))


def flow_rows(pairs, widths, max_w, seg_starts=None):
    """Cut the character stream into rows, and never through a word.

    A cut that fills a row to max_w and stops wherever the width runs out
    lands half a name on one row and half on the next, and a reader has to
    rejoin the halves before it can use the name.

    The row ends at the last place inside it where two neighbouring
    characters are not both word characters. A word wider than a whole row
    still has to break; the row it breaks on keeps the WRAP_INK edge that
    already tells a reader the source line carries on.
    """
    # The draw step advances BAND_INSET at every segment on the row, at "x +=
    # seg_w + BAND_INSET", and a segment is one source line, so a row holding
    # several short lines is drawn that much wider than the widths summed here.
    # Without this charge the wrap mark lands past the row end and
    # wrap_edge()'s clamp drags it back onto the text. Charging the inset here
    # is what makes the row end where the draw step ends it.
    inset = BAND_INSET if seg_starts else 0

    def step(j):
        return widths[j] + (inset if j in seg_starts else 0)

    if not seg_starts:
        def step(j):  # noqa: F811 - the plain sum when no segments are given
            return widths[j]

    rows = []
    i = 0
    n = len(pairs)
    while i < n:
        w = 0.0
        j = i
        cut = -1
        while j < n and w + step(j) <= max_w:
            w += step(j)
            j += 1
            if j < n and split_here(pairs, j):
                cut = j
        if j < n and cut > i:
            # A word safe cut that leaves the row emptier than page.fill
            # gives way to the width cut, so the row runs to the edge.
            used = sum(widths[q] for q in range(i, cut))
            if FILL <= 0 or used >= (1.0 - FILL) * max_w:
                j = cut
        # The width cut can still land between a mark and its count. Walk
        # back to the last place a row may end, and take the width cut only
        # when the walk reaches the start of the row.
        if j < n:
            back = j
            while back > i + 1 and not split_here(pairs, back):
                back -= 1
            # A row with no place to end inside it keeps the width cut. Taking
            # the cut at i + 1 regardless would give a token wider than a row,
            # such as a long dash table rule, one row a character.
            if back > i and split_here(pairs, back):
                j = back
        rows.append((i, j))
        i = j
    return rows



class Shrunk(object):
    """A page drawn at its final size while the layout runs at the
    supersampled size.

    The layout hands every coordinate in the big space. A glyph mask
    arrives at the big size and is shrunk on its own, aligned to the output
    pixel it lands in, so it lands where the whole-page shrink would have
    put it; a band, a bar or a line is drawn straight at the small size.
    Nothing the size of the big page is ever allocated, and the page draws in
    a fraction of the time the whole-page shrink takes.
    """

    def __init__(self, width, height, shrink_to=None, shrink_by=None):
        big_w = -(-width // dp.PATCH) * dp.PATCH
        if shrink_to:
            self.ratio = float(shrink_to) / big_w
        else:
            self.ratio = 1.0 / float(shrink_by or 1)
        self.width = max(1, int(round(width * self.ratio)))
        self.height = max(1, int(round(height * self.ratio)))
        self.im = Image.new("RGB", (self.width, self.height), BACKGROUND)
        self.im.info["densepack_small"] = True
        self.mode = "RGB"
        self.size = self.im.size

    def _out(self, v):
        return int(round(v * self.ratio))

    def paste(self, fill, box, mask=None, anchor=None):
        """fill at box with a big-space mask, shrunk to land on the output grid.

        anchor, when given, is the row's own baseline in the big space, which
        every face on the row shares. The glyph hangs from it, and the rows it
        reaches below it truncate rather than round, so a round letter's
        one-column overshoot collapses onto the baseline while a real
    descender keeps the rows it needs. Without it a row's letters split
    across two output rows.
    """
        r = self.ratio
        if mask is None:
            # a whole image, as a sheet pastes a page: scale and paste
            im = fill
            w_out = max(1, int(round(im.width * r)))
            h_out = max(1, int(round(im.height * r)))
            self.im.paste(im.resize((w_out, h_out), SHRINK_FILTER), (self._out(box[0]), self._out(box[1])))
            return
        x, y = box[0], box[1]
        if SNAP_GLYPHS:
            # Each glyph lands on a whole output pixel, the way this class's
            # rectangle() already lands, and its shrunk mask keeps its own
            # width rather than growing into its neighbour. Keeping the
            # sub-pixel remainder and shrinking the mask with that offset baked
            # in spreads a stem over two columns, so a pair such as the n, c
            # and e of readonce meet and less ink lands at full strength.
            # Both axes round. Flooring the vertical biases every glyph
            # downward, and by a different amount per letter, because each mask
            # carries its own top offset: an l, a k, a d and an h reach higher,
            # so their offset lands on a different side of the whole pixel and
            # they sit a row below the round letters they share a line with.
            # The height takes the ceiling, not the round, because rounding
            # loses ink at small sizes. Lifting contrast after the draw is not
            # the answer: the page has to come off the renderer that way rather
            # than be corrected later.
            bx = int(round(x * r))
            # The width rounds, so a glyph is drawn at the width it really
            # shrinks to. A ceiling stretches every glyph into the next whole
            # pixel, which is the column it borrows from its neighbour, so a
            # pair such as the a and the b of "ab" meet. The height keeps its
            # ceiling, so the ink a letter carries up and down is untouched.
            w_out = max(1, int(round(mask.width * r)))
            h_out = max(1, int(math.ceil(mask.height * r)))
            # The glyph hangs from its bottom edge rather than its top. Every
            # letter on a row shares one bottom in the big space, the baseline,
            # while their tops differ by letter, so rounding the top puts an a
            # and an l on different output rows. Rounding the bottom and
            # subtracting the height lands every letter of a row on one
            # baseline, and a descender keeps its own lower bottom. Placement
            # only: the mask, its size and its ink are untouched, and the
            # horizontal keeps its single rounding, because rounding the pen
            # and the bearing apart doubles the worst error to a whole pixel
            # and opens gaps inside words.
            if anchor is None:
                by = int(round((y + mask.height) * r)) - h_out
            else:
                by = (int(round(anchor * r)) - h_out
                      + int((y + mask.height - anchor) * r))
            # paste_ink, not self.im.paste. See the note on the other paste in
            # this method.
            paste_ink(self.im, fill, (bx, by),
                      mask.resize((w_out, h_out), SHRINK_FILTER))
            return
        bx = int(math.floor(x * r))
        by = int(math.floor(y * r))
        ox = int(round(x - bx / r))
        oy = int(round(y - by / r))
        if ox < 0:
            ox = 0
        if oy < 0:
            oy = 0
        w_out = int(math.ceil((ox + mask.width) * r))
        h_out = int(math.ceil((oy + mask.height) * r))
        if w_out < 1 or h_out < 1:
            return
        tw = max(mask.width + ox, int(round(w_out / r)))
        th = max(mask.height + oy, int(round(h_out / r)))
        temp = Image.new("L", (tw, th), 0)
        temp.paste(mask, (ox, oy))
        small = temp.resize((w_out, h_out), SHRINK_FILTER)
        # paste_ink, not self.im.paste.
        #
        # THIS METHOD DRAWS EVERY GLYPH ON A SHIPPED PAGE. backend_text sends a
        # glyph here whenever the ratio is not exactly 1.0, and
        # page.fill_bottom puts it there on every page long enough to leave
        # white at the foot: the fill narrows the layout to grow the glyph, so
        # the page is wider than the layout and the ratio rises above 1.0.
        #
        # Pillow's own paste mixes the ink and the band as sRGB numbers. Light
        # does not mix that way, so every partly covered pixel comes out too
        # dark and the letters grow hard grainy edges. paste_ink does the mix
        # in linear light, which is what FreeType's own guidance calls the
        # correct way:
        #
        #   https://freetype.org/freetype2/docs/hinting/text-rendering-general.html
        #
        # DENSEPACK_GAMMA_MODE acts only inside paste_ink, so a paste that
        # skips it makes the mode change no pixel.
        paste_ink(self.im, fill, (bx, by), small)

    def drawer(self):
        return _ShrunkDraw(self)


class _ShrunkDraw(object):
    """ImageDraw's rectangle, line and text on a Shrunk canvas, big
    coordinates in, drawn at the small size."""

    def __init__(self, canvas):
        self.c = canvas
        self.d = ImageDraw.Draw(canvas.im)

    def _pt(self, pt):
        return (self.c._out(pt[0]), self.c._out(pt[1]))

    def _box(self, box):
        if len(box) == 2:
            (x0, y0), (x1, y1) = box
        else:
            x0, y0, x1, y1 = box
        a, b = self._pt((x0, y0)), self._pt((x1, y1))
        return [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]

    def rectangle(self, box, fill=None, outline=None, width=1):
        self.d.rectangle(self._box(box), fill=fill, outline=outline,
                         width=max(1, self.c._out(width)) if outline else width)

    def line(self, xy, fill=None, width=1):
        # drawn four times over on its own mask and shrunk, so a curve lands
        # smooth on the output grid; drawn straight onto the small canvas it
        # comes out as steps
        r = self.c.ratio
        ss = 4
        pts = [(pt[0] * r, pt[1] * r) for pt in xy]
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        pad = max(2, int(width * r) + 2)
        x0, y0 = int(min(xs)) - pad, int(min(ys)) - pad
        w, h = int(max(xs)) - x0 + pad + 1, int(max(ys)) - y0 + pad + 1
        mask = Image.new("L", (w * ss, h * ss), 0)
        ImageDraw.Draw(mask).line([((x - x0) * ss, (y - y0) * ss) for x, y in pts],
                                  fill=255, width=max(1, int(round(width * r * ss))))
        mask = mask.resize((w, h), Image.LANCZOS)
        self.im_paste(fill, (x0, y0), mask)

    def im_paste(self, fill, pos, mask):
        layer = Image.new("RGB", mask.size, fill)
        self.c.im.paste(layer, pos, mask)

    def text(self, xy, text, font=None, fill=None, **kw):
        if not text:
            return
        try:
            left, top, right, bottom = font.getbbox(text)
        except Exception:  # noqa: BLE001
            left, top, right, bottom = 0, 0, len(text) * font.size, font.size * 2
        w, h = max(1, right - left + 2), max(1, bottom - top + 2)
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).text((-left + 1, -top + 1), text, font=font, fill=255)
        self.c.paste(fill, (xy[0] + left - 1, xy[1] + top - 1), mask)


def _pack_code(text, px, out_stem, python=True, legend=None, layout=None):
    """Draw text as banded code pages named <out_stem>-1.png and up.

    python=False classifies the tokens by shape instead of by tokenize, for
    every code suffix in CODE_SUFFIXES other than .py.

    layout, when a dict is passed, is filled with where everything landed:
    "pairs" is the character stream as (char, big) tuples, "ids" the source
    line of each, "line_h" the row height, and "pages" one entry per page
    holding "rows" as (y, h, a, b), "chars" as (j, x, y, w), and the "sheet"
    number and "x_off" the page sits at inside its sheet file. None, the
    default, fills nothing.
    """
    raw = keep_leading_tabs(text)
    # build_flow stores each newline as a mark and raises without a last one,
    # and a source file that ends mid-line is common outside python. The
    # caller catches that raise and draws nothing, so the file would fall
    # back to the plain pack instead of the banded image.
    if not raw.endswith("\n"):
        raw += "\n"
    # ONE FLOW A FILE. build_flow() depends on the text, the language flag and
    # the legend, and the search's trials pass the same three every time, so
    # the flow is built once a file.
    _flow_key = (hash(raw), bool(python), id(legend) if legend is not None else None)
    _flow_hit = _FLOW_CACHE.get(_flow_key)
    if _flow_hit is not None and _flow_hit[0] == raw:
        pairs = list(_flow_hit[1])
    else:
        pairs = build_flow(raw, python, legend)
        _FLOW_CACHE.clear()
        _FLOW_CACHE[_flow_key] = (raw, list(pairs))
    depths = flow_depths(raw)
    font = dp.load(dp.REGULAR, px)
    written = []
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + 1

    # THE ROW HEIGHT CAN BE PINNED.
    #
    # space.row_px holds the glyph size the ROW is built for, while px is the
    # size the GLYPHS are drawn at. Zero means the row follows the glyphs.
    #
    # WHAT IT IS FOR. font.scale_x raises the x-height by asking for a larger
    # size and condensing the width back, so 17 px condensed to 0.588 draws an
    # x-height of 10 in the same 6 px column a 10 px face uses. The row would
    # then follow the 17 px face's own ascent and descent and the page would
    # grow with it. Pinning the row to the 10 px face keeps the band the size
    # it was and lets the taller glyphs use it.
    #
    # WHAT IT COSTS, and it is not small. On Inter SemiBold a 10 px row is 14
    # px tall and its ink spans 13 of them, so there is one spare pixel. A 17
    # px face condensed to 0.588 spans 22 px of ink. Pinned to the 10 px row, 8
    # px of that ink has nowhere to go, so ascenders reach into the band above
    # and descenders into the one below. The clamp below stops a glyph being
    # cut off at the page edge; it does not stop rows meeting.
    ROW_PX = float(_S.get("space.row_px", 0) or 0)
    if ROW_PX:
        row_font = dp.load(dp.REGULAR, int(round(ROW_PX)))
        row_ascent, row_descent = row_font.getmetrics()
        line_h = row_ascent + row_descent + 1
        # The baseline stays where the ROW puts it, so the band and the line
        # numbers sit where they did at that size.
        ascent = row_ascent

    # A character with its own font or size may be taller than the body face,
    # and may sit lower or higher on the row. The row grows by the tallest such
    # glyph's reach above and below the body's own, and the body baseline moves
    # down by the reach above, so no glyph runs into the row before it and none
    # is cut at the page's bottom.
    # The reach is the glyph's own ink, not its face's metrics: a face's ascent
    # can sit far above the mark it draws, and the metrics would make every row
    # and every band thick. The glyph is measured where the page draws it, on
    # the body baseline, at the size the page draws it, the larger size for a
    # BIGGER mark, with one px of slack for the renderer. The ink is taken from
    # the renderer the page draws with, because a backend's hinting can reach
    # past Pillow's bbox. Every glyph then gets the same clear room to the
    # band's edge, a fifth of the type size above and below, so the gap between
    # rows reads the same on every row.
    up = down = 0.0
    margin = px * 0.2
    for _ch, over in CHAR_OVER.items():
        if not (over.get("font") or over.get("px")):
            continue
        # the pick's own size, not the BIGGER one: the larger mark grows
        # into the margin, so the row is the same with the marks on or off
        size = px + float(over.get("px", 0) or 0)
        drawn_ch = over.get("glyph") or _ch
        ody = float(over.get("dy", 0) or 0)
        ink_top = ink_bottom = None
        if False and over.get("font"):
            try:
                mask, _left, top = glyph_backend().glyph(drawn_ch, over["font"], size,
                                                      bool(over.get("bold", False)),
                                                      float(over.get("scale_x", 1.0) or 1.0))
            except Exception:  # noqa: BLE001
                mask = None
            if mask is not None:
                ink_top = ascent + top + ody
                ink_bottom = ink_top + mask.height
        if ink_top is None:
            # A font override naming a file that is not on this machine falls
            # back to the body face, which is what face_for() does when it
            # builds the face the page really draws with. Dropping the
            # character instead would take that glyph's ink out of the row
            # height and move up, down and the baseline, shifting every glyph
            # on every row with the page size unchanged.
            box = None
            for paths in ([over["font"]] if over.get("font") else None,
                          dp.REGULAR):
                if not paths:
                    continue
                try:
                    of = dp.load(paths, size)
                    box = of.getbbox(drawn_ch)
                    break
                except Exception:  # noqa: BLE001
                    box = None
            if not box:
                continue
            oa = of.getmetrics()[0]
            ink_top = ascent + (box[1] - oa) + ody
            ink_bottom = ascent + (box[3] - oa) + ody
        up = max(up, margin - ink_top)
        down = max(down, ink_bottom + margin - (ascent + descent))
    # EVERY ROW KEEPS ITS OWN CLEAR ROWS.
    #
    # The loop above only reaches a character carrying a font or a px override,
    # and char.overrides holds none of those, so up and down stay 0 and the row
    # would come out exactly as tall as the tallest ink in it: every ascender
    # on the band's top edge and every descender on its bottom.
    #
    # Growing the band instead does not work. band.grow_t and grow_b move the
    # band edge without moving the glyph, so the band reaches into the row gap
    # and neighbouring bands merge.
    #
    # The room has to come from the row height, which is what this does. It
    # costs page, and the cost is the point: clearance is space.
    up = max(up, BAND_TEXT_CLEAR)
    # The band gives up BAND_GAP_Y rows off its FOOT, at by1 = line_h - 1 -
    # BAND_GAP_Y + ..., so a row tall enough for the ink plus a clear row each
    # side still leaves the band short by that gap. Charging it here is what
    # makes the band itself tall enough to centre in: without it the tallest
    # glyph, the pipe, sits in a band with one row of slack, and no offset can
    # give it a clear row above AND below.
    down = max(down, BAND_TEXT_CLEAR + BAND_GAP_Y)
    up, down = int(up + 0.999), int(down + 0.999)
    # THE BAND CENTRES ITSELF ON THE TEXT.
    #
    # band.offset_y moves the band as one, so it trades the clear rows above
    # the text against the clear rows below, two rows of balance per unit. A
    # hand tuned value is right at one glyph size only.
    #
    # The offset is derived from where the ink really falls. The band's own
    # edges sit at
    #
    #     top    = offset - band.pad_y - grow_t
    #     bottom = line_h - 1 - band.gap_y + band.pad_y + offset + grow_b
    #
    # and the ink at rows up through up + ink_h - 1 of the row, so asking for
    # equal clearance above and below gives
    #
    #     offset = (up - down + grow_t - grow_b + band.gap_y) / 2
    #
    # measured against the face's REAL ink rather than its nominal ascent and
    # descent, because a face's metrics reserve room it does not always use.
    if CENTRE_TEXT:
        ink_top = ink_bot = None
        for _c in "AQbdfghjklpqty0123456789|()[]{}_":
            # A character in font.bigger_chars is drawn BIGGER_PX larger and
            # hangs from the same baseline, so it reaches higher than the body
            # face does. Measuring it at the body size would understate the top
            # and put the pipe, parenthesis and bracket on the band's topmost
            # row.
            _px = px + (BIGGER_PX if _c in BIGGER else 0)
            try:
                _m, _l, _t = glyph_backend().glyph(_c, font.path, _px)
            except Exception:  # noqa: BLE001
                _m = None
            if _m is None:
                continue
            # A bracket is lifted onto the baseline before it is pasted, so
            # the band has to measure it where it lands. It changes no band
            # on a page that draws a pipe, because the lifted [ reaches the
            # pipe's own 15 rows above the baseline and no further.
            _t -= baseline_lift(_c, _m, _t)
            _a = ascent + _t
            _b = _a + _m.height
            ink_top = _a if ink_top is None else min(ink_top, _a)
            ink_bot = _b if ink_bot is None else max(ink_bot, _b)
        if ink_top is not None:
            # ink_bot from the loop is one PAST the last inked row, so the last
            # inked row is ink_bot - 1. Writing the band's own edges out,
            # relative to the row's top y,
            #
            #     band top    = offset - band.pad_y - grow_t
            #     band bottom = line_h - 1 - band.gap_y + band.pad_y
            #                   + offset + grow_b
            #
            # and asking for equal clearance above the first inked row and
            # below the last gives
            #
            #     offset = (ink_top + ink_last + 1 + gap_y - line_h
            #               + grow_t - grow_b) / 2
            #
            # FLOOR, NOT ROUND. Python's round is half to even, so
            # int(round(-0.5)) is 0 rather than -1, and the half step this
            # arithmetic lands on whenever the slack is odd would be thrown the
            # wrong way.
            #
            # Floor rather than ceil because the extra row is worth more below
            # the text than above it: a descender that touches reads as a
            # different letter, where an ascender that touches is still that
            # letter.
            #
            # Do not add an "+ up - down" term, which the derivation above
            # appears to ask for because ink_top and line_h are read before
            # "line_h += up + down" runs. It moves every band one row up. The
            # term the derivation really asks for is half of that, and the +1
            # the floor throws away is the same half step, so it is already
            # paid.
            #
            # WHAT IS LEFT IS NOT GEOMETRY, IT IS CONTENT. The band spans the
            # rows the tallest glyph on the page needs, a pipe drawn one px
            # bigger, and the rows the deepest descender needs. A row whose
            # tallest glyph is an ordinary ascender therefore shows paper the
            # band keeps for a character that row does not hold. No offset can
            # take that back; only a taller row can, and a taller row costs
            # page on every line.
            #
            # Measure a band against the page before touching this, and measure
            # WHOLE bands: a column scan taken down one column is cut in two by
            # the digits' own ink, and each half then measures as its own band.
            ink_last = ink_bot - 1
            BAND_OFF_Y_ROW = int(math.floor(
                (ink_top + ink_last + 1 + BAND_GAP_Y - line_h
                 + BAND_GROW[2] - BAND_GROW[3]) / 2.0))
        else:
            BAND_OFF_Y_ROW = BAND_OFF_Y
    else:
        BAND_OFF_Y_ROW = BAND_OFF_Y
    line_h += up + down
    ascent += up

    # The larger face, on the row's own baseline. Its ascent is taller, so a
    # character marked big starts that many rows higher and grows up into the
    # rows the type leaves clear; nothing below the baseline moves and no row
    # changes height. One face serves both callers of the big flag, the LIFT
    # token and the two BIGGER punctuation marks, because LIFT_PX ships at 0
    # and only one of the two is ever on.
    big_px = LIFT_PX or BIGGER_PX
    big_font = dp.load(dp.REGULAR, px + big_px) if big_px else None
    big_dy = ascent - big_font.getmetrics()[0] if big_font else 0

    # One face per size offset. The offset is the big flag's px plus the
    # character group's own, so the two knobs add rather than fight. With every
    # font.group_px at zero this hands back two faces, the body face and the
    # big one.
    faces = {(0.0, None): (font, up)}
    if big_font is not None:
        faces[(float(big_px), None)] = (big_font, big_dy)

    def face_for(ch, big, borrow=True):
        """The face one character draws from, and the rows it moves down.

        A character with a font override draws from that file and every other
        character stays in the body face. The dy is the ascent difference, so
        the borrowed glyph sits on the row's own baseline. A file that is not
        on this machine falls back to the body face, which is what keeps the
        override list from breaking a page drawn off Windows.

        borrow=False hands back the body face at the same size, and that is
        the face the pen step is measured from: see char_widths().
        """
        off = float((big_px if big else 0) + GROUP_PX.get(dp.group_for(ch), 0.0)
                    + (char_over(ch, "px", 0.0) or 0.0))
        # THE MARKS IN font.full_width_chars DRAW AT font.mark_px. They are not
        # condensed by font.scale_x either, so they keep their full width at
        # that size.
        #
        # Zero means the page's own size. The offset is from the page size, so
        # a mark_px of 12 on a 13 px page draws the marks one pixel smaller
        # than the letters are asked for, while the letters are condensed back
        # to the 10 px column and the marks are not.
        # A SIZE NAMED FOR ONE CHARACTER WINS OVER EVERY GROUP,
        # font.scaled_marks included. One setting names the size, the other
        # names the width, and either may be set for one character without
        # touching its group.
        if ch in MARK_PX_BY_CHAR:
            off += MARK_PX_BY_CHAR[ch] - px
        elif ch in SCALED_MARKS:
            # This group keeps the PAGE's size and takes its own condense from
            # scale_for, so no size rule applies to it.
            pass
        elif MARK_PX and ch in FULL_WIDTH:
            off += MARK_PX - px
        # Borrowed faces stop at char.font_max_px, because borrowed advances
        # split a page into more pages and cost patches.
        borrowed = borrow and px <= FONT_MAX_PX
        # font.scale_x is the page's own horizontal scale. It reaches FreeType
        # as face.set_char_size(width = size * scale, height = size), so the
        # outline is condensed and its height is untouched; the x-height
        # measures the same at every value. scale_for() decides which
        # characters take it.
        #
        # A per character scale_x in char.overrides still wins over this, and
        # nothing sets one.
        page_scale = scale_for(ch)
        # BOLD IS NOT GATED BY borrowed. borrowed means "this character takes
        # its glyph from ANOTHER font file", which is what char.font_max_px
        # limits. Bold is a property of the face already in hand, so the two
        # have nothing to do with each other. Tied together,
        # char.overrides[ch]["bold"] could never reach a page, because
        # char.font_max_px is 0 and borrowed is false at every size this
        # renderer draws.
        key = (off, char_over(ch, "font") if borrowed else None,
               bool(char_over(ch, "bold", False)),
               float(char_over(ch, "scale_x", page_scale) or page_scale)
               if borrowed else page_scale)
        if key not in faces:
            try:
                f = dp.load([key[1]] if key[1] else dp.REGULAR, px + off)
            except Exception:  # noqa: BLE001
                f = dp.load(dp.REGULAR, px + off)
            f.sim_bold = key[2]
            f.scale_x = key[3]
            faces[key] = (f, ascent - f.getmetrics()[0])
        return faces[key]

    # One answer a character for this draw. face_for() reads nothing but the
    # character, the two flags, px and the module's settings, and without the
    # memo it runs once a character a trial, millions of calls on one large
    # file.
    _face_memo = {}
    _face_inner = face_for

    def face_for(ch, big, borrow=True):
        key = (ch, bool(big), borrow)
        hit = _face_memo.get(key)
        if hit is None:
            hit = _face_inner(ch, big, borrow)
            _face_memo[key] = hit
        return hit

    tails = {}
    curve = curve_for(px)
    threshold = threshold_for(px)
    blur = blur_for(curve)
    # The soft path draws through Pillow's own text call, which is the blend as
    # the font draws it. Neither branch runs on a shipped page: curve.name is
    # "none", so curve is never "soft", and glyphrenderer is freetype.
    plain_soft = curve == "soft" and blur in ("auto", "full")
    # The renderer that draws this face; see glyph_renderer().
    renderer = glyph_renderer(font)
    use_backend = renderer == "freetype"
    # THE BACKEND THAT DRAWS A GLYPH MEASURES IT. Pillow's mask for ink_span()
    # is not condensed by font.scale_x, so its spans are wider than the glyph
    # the page draws, and the pair rule would spread the letters to clear them.
    shifts = []
    spans = []
    # ONE MEASUREMENT A FILE. The widths, ids, shifts and spans depend on the
    # characters, the faces and the size, and on nothing the search changes
    # between its trials, so the second trial of a file and every one after it
    # take the first trial's lists. Copies go out, because the draw below may
    # change what it holds.
    _cw_key = (px, renderer, getattr(font, "path", None), getattr(font, "size", None),
               getattr(big_font, "size", None) if big_font is not None else None,
               len(pairs), hash(tuple((p[0], p[2] if len(p) > 2 else None) for p in pairs)))
    _cw_hit = _CW_CACHE.get(_cw_key)
    if _cw_hit is not None:
        widths, ids = list(_cw_hit[0]), list(_cw_hit[1])
        shifts.extend(_cw_hit[2])
        spans.extend(_cw_hit[3])
    else:
        widths, ids = char_widths(
            font, pairs, big_font, face_for,
            renderer=renderer,
            shifts=shifts, spans=spans)
        _CW_CACHE.clear()
        _CW_CACHE[_cw_key] = (list(widths), list(ids), list(shifts), list(spans))
    words = word_indices(pairs, ids) if PLACEMENTS or layout is not None else None

    # The row width stays fixed at every type size: scaling it with the type
    # size costs more, with more cache written and more output.
    # The wrap mark is drawn past the row's last character, at the band's own
    # right edge, and wrap_edge() then clamps it back inside the page when it
    # would fall off. That clamp is what puts the mark on top of the last
    # columns of a row's text or line number.
    #
    # Reserving the mark's own columns here means a row can never fill them,
    # the clamp never fires, and a word that no longer fits moves to the next
    # row instead of being drawn under the mark. The rows this adds land in the
    # white page.fill_bottom already leaves at the foot of a page.
    max_w = PAGE_W - WRAP_GUTTER
    # One segment per source line, the same runs the draw loop below cuts on
    # with "while seg < b and ids[seg] == ids[k]".
    seg_starts = {j for j in range(len(ids)) if j == 0 or ids[j] != ids[j - 1]}
    rows = flow_rows(pairs, widths, max_w, seg_starts)

    # Reading guidance only. A reader answers from the code and never writes
    # the stream out, because an order to output the marked stream makes every
    # reader transcribe the pictures before answering, at many times the output
    # tokens.
    scheme = scheme_for(pairs)

    # The scheme is the prompt card's line, sent once a session, and no page
    # draws it. The budget still holds those rows back, so a page break falls
    # where it would with them and a page is shorter by them.
    # page.lines names the rows a page holds outright, for printed-sheet
    # shapes. Zero fills the page height.
    # The row pitch is line_h plus ROW_GAP; dividing by line_h alone would let
    # a full page overshoot page.code_height by one gap a row.
    per_page = (PAGE_LINES if PAGE_LINES
                else max(4, (CAP_H - 2 * PAD) // (line_h + ROW_GAP) - len(scheme)))
    # The rows spread evenly over the pages they need, not greedily onto the
    # first. A greedy fill puts per_page rows on page one and the remainder on
    # page two, and the sheet pairing the two is as tall as its tallest page,
    # so a short page two buys a full height column of white. An even split
    # never exceeds per_page, so the height cap still holds.
    page_count = max(1, -(-len(rows) // per_page))
    per_page = max(1, -(-len(rows) // page_count))
    pages = [rows[k:k + per_page] for k in range(0, len(rows), per_page)]
    n = 0
    page_imgs = []
    # Page one carries the key row. The band tints, the marks and the wrap edge
    # are drawn as themselves, so a reader names them without the session card.
    legend_w = legend_width(font)
    for page_i, chunk in enumerate(pages):
        # the same picks and renderer as the drawing, or the count differs and
        # the last row is cut off the page
        head_h = ((line_h + ROW_GAP) * len(legend_rows(font, max_w, face_for, renderer))
                  if page_i == 0 else 0)
        # A row that carries a blank line run ends a paragraph, and
        # space.paragraph_gap is the white that follows it. Zero ships.
        extras = [PARA_GAP if any(_is_count(pairs[j])
                                  for j in range(a, b)) else 0
                  for (a, b) in chunk]
        height = (2 * PAD + head_h
                  + len(chunk) * (line_h + ROW_GAP) + sum(extras))
        if _FILL_PASS and _FILL_STRETCH:
            # the stretched pitch needs the canvas to grow with it, or the rows
            # past the old height are clipped and the last rows of a file fall
            # off the page
            height = int(height + (len(chunk) + 1) * (line_h + ROW_GAP) * (_FILL_STRETCH - 1.0)) + 1
        width = int(2 * PAD + max_w) + PAGE_EXTRA
        # On the shrunk page every row snaps to the shrink grid and drifts down
        # a little each, so the last band would run past this height and be cut
        # before the page is padded white to a 28 px step. The height follows
        # the snapped pitch and keeps the band's own bottom pad.
        if DIRECT_CANVAS and (SHRINK_TO or (SHRINK_BY and SHRINK_BY > 1)) and renderer == "freetype":
            ratio = (float(SHRINK_TO) / width) if SHRINK_TO else 1.0 / float(SHRINK_BY)
            pitch = line_h + ROW_GAP
            snapped = round(pitch * ratio) / ratio
            height = int(height + (len(chunk) + 1) * max(0.0, snapped - pitch)
                         + BAND_PAD_Y + ROW_GAP + 1 / ratio) + 1
            # ONE ROW OF SLACK. The snapped height above can still leave the
            # last band short. The drift a row picks up as it snaps is not a
            # fixed amount, so no closed formula for it holds for every file;
            # one whole row pitch covers it outright.
            #
            # IT IS FREE. Nothing trims the page's height: PAGE_TRIM above
            # narrows the width only, and save_png pads the height up to the
            # next whole 28 px patch, which already leaves white rows under the
            # last band. The slack is spent inside that padding and the page
            # keeps its size. Check the size when changing it, since a page
            # whose last band sits near a patch boundary could grow by one
            # patch row.
            height += pitch
        if PAGE_TRIM and chunk:
            # the widest row on this page, plus the room its last block's
            # right edge and wrap edge take; never wider than before
            widest = max(sum(widths[j] for j in range(a, b)) for a, b in chunk)
            width = min(width, int(2 * PAD + widest + EDGE_INSET + 2 + BAND_PAD_X + BAND_INSET + MARK_CLEAR + WRAP_W))  # room for the wrap bar
            if head_h:
                # a trimmed page one never cuts the key row off
                width = max(width, int(2 * PAD + min(legend_w, max_w) + 2))
        if DIRECT_CANVAS and (SHRINK_TO or (SHRINK_BY and SHRINK_BY > 1)) and renderer == "freetype":
            # the page is drawn at its final size; see Shrunk above
            img = Shrunk(width, height, SHRINK_TO, SHRINK_BY)
            d = img.drawer()
        else:
            img = Image.new("RGB", (width, height), BACKGROUND)
            d = ImageDraw.Draw(img)
        # Every row lands on a whole page pixel. A row pitch in the big space
        # that is not a whole number of page pixels makes rows drift, so the
        # white between two rows would read 1 px on one pair and 3 px on the
        # next. The pitch and the starting rows are snapped to the shrink, so
        # every gap is the same.
        snap = (lambda v: round(v * img.ratio) / img.ratio) if isinstance(img, Shrunk) else (lambda v: v)
        # during a fill pass the pitch stays fractional, so the rows spread
        # over the page's height exactly and the gaps differ by one pixel at
        # most; see _fill_bottom
        pitch = (line_h + ROW_GAP) * (_FILL_STRETCH or 1.0) if _FILL_PASS else snap(line_h + ROW_GAP)
        y = snap(PAD)
        if head_h:
            y += legend_row(d, font, PAD, y, line_h, max_w, face_for, renderer, img, up)
            y = snap(y)
        page_rows = []
        page_chars = []
        # one page pixel, in the layout columns everything below is measured
        # in; the band edge and the mark box both keep one of these
        bw = int(round(1 / img.ratio)) if isinstance(img, Shrunk) else 1
        # a drawer on the page's own pixels, for the mark box, which is fitted
        # to the digits after they are drawn
        small = ImageDraw.Draw(img.im if isinstance(img, Shrunk) else img)
        for row_n, (a, b) in enumerate(chunk):
            page_rows.append((y, line_h, a, b))
            # one outlined block per line segment inside this row; the
            # outline marks the line break a reader asked to see
            x = float(PAD)
            k = a
            # the marks of a line break, the pilcrow, its count, the indent
            # mark and its number, get one black box as a unit: inside a long
            # print line they read as content when the band runs through them.
            # The run crosses the segment edge, because the pilcrow ends one
            # line's segment and the indent mark opens the next line's.
            mark_runs = []
            mark_splits = []          # where a run changes ink
            # The band's own top and bottom for this row, in layout space.
            # Every band on a row shares one y, so the first one drawn sets it.
            band_y = None
            run_ink = None
            run_start = None          # the run's leftmost inked column
            run_end = None            # its rightmost
            run_top = None            # its highest inked row
            run_bot = None            # its lowest
            while k < b:
                seg = k
                while seg < b and ids[seg] == ids[k]:
                    seg += 1
                seg_w = sum(widths[j] for j in range(k, seg))
                gap_here = GAP if pairs[seg - 1][0] == NL_MARK else 0
                # With the mark outside, the band stops one pixel before
                # the pilcrow's own column; the pilcrow keeps its place.
                if PILCROW_OUTSIDE and pairs[seg - 1][0] == NL_MARK and seg - k > 1:
                    # The band ends past the last character's ink, not a cell
                    # width past it: a cell is wider than the ink inside it, so
                    # the tint would run under the next line's number box. This
                    # moves the band's right edge only. The band's height is
                    # untouched.
                    m = seg - 1
                    tail = 0.0
                    while m > k and (spans[m] is None
                                     or pairs[m][0] == NL_MARK):
                        tail += widths[m]
                        m -= 1
                    if spans[m] is None:
                        # a segment of nothing but spaces keeps the old step
                        gap_here = (widths[seg - 1] - EDGE_INSET + MARK_CLEAR
                                    + BAND_PAD_X + BAND_INSET)
                    else:
                        # THE SAME PAPER ON BOTH SIDES. The glyphs start a
                        # whole BAND_INSET in from the band's left edge, so the
                        # trail on the right is BAND_INSET plus a measured
                        # step. A one pixel trail would leave the band flush
                        # against the last character's ink.
                        #
                        # THE TRAIL IS BAND_INSET + 2, and the step was
                        # measured over every unwrapped band on a page, with
                        # the wrap mark's own columns left out because that
                        # mark is drawn at the band's right edge on purpose.
                        # With the marks at font.mark_px, +2 balances the paper
                        # left and right; +1 leaves the right about one page
                        # pixel tighter, and +0 leans further. A LARGER trail
                        # moves the band's right edge further out, which is the
                        # other way from what the expression reads like. The
                        # page size is the same at each of these values.
                        #
                        # The clamp below still owns the other end: where the
                        # next line's number box is too close to give this
                        # much, the band takes whatever room is there.
                        gap_here = (BAND_PAD_X + tail + widths[m]
                                    - shifts[m] - spans[m][1]
                                    - (BAND_INSET + 2) * bw)
                        # and never so far right that it reaches the box the
                        # next line's number draws in. That box's left line
                        # lands two page pixels left of the first digit's
                        # ink, so the band stops two further left again and
                        # one page pixel of white is left between them. It
                        # never cuts its own last character: the ink rule
                        # above is the floor.
                        if (seg < len(pairs) and _is_count(pairs[seg])
                                and spans[seg] is not None):
                            gap_here = min(
                                max(gap_here,
                                    BAND_PAD_X - spans[seg][0] + 4 * bw),
                                BAND_PAD_X + tail + widths[m]
                                - shifts[m] - spans[m][1])
                # A blank-line count and its mark, "3" and the bullet, open
                # the block after a blank run. They belong with the line
                # break, between the bands, so the band starts after them.
                lead_w = 0
                lead_end = k
                if PILCROW_OUTSIDE:
                    j0 = k
                    while j0 < seg and _is_count(pairs[j0]):
                        j0 += 1
                    if k < j0 < seg:
                        lead_w = sum(widths[j] for j in range(k, j0))
                        lead_end = j0
                # The line's own placement moves its band and its glyphs
                # together; the band's own placement moves and grows the band
                # alone. Both are zero unless layout.placements sets them.
                line_key = "line:%d" % ids[k]
                band_key = "band:%d" % ids[k]
                ldx = _placed(line_key, "dx")
                ldy = _placed(line_key, "dy")
                bdx = ldx + _placed(band_key, "dx")
                bdy = ldy + _placed(band_key, "dy")
                g_l = _placed(line_key, "grow_l") + _placed(band_key, "grow_l") + BAND_GROW[0]
                g_r = _placed(line_key, "grow_r") + _placed(band_key, "grow_r") + BAND_GROW[1]
                g_t = _placed(line_key, "grow_t") + _placed(band_key, "grow_t") + BAND_GROW[2]
                g_b = _placed(line_key, "grow_b") + _placed(band_key, "grow_b") + BAND_GROW[3]
                # With a count in front, its digits end at x + BAND_INSET
                # - EDGE_INSET + lead_w, and the band starts MARK_CLEAR
                # after that; with no count the band keeps its pad.
                # the count digits end at x + lead_w - MARK_CLEAR, the clear
                # space is inside lead_w, and the band starts at x + lead_w;
                # with no count the band starts at x, one clear space after
                # the pilcrow before it
                bx0 = x + lead_w + (BOX_CLEAR if lead_w else 0) + BAND_OFF_X + bdx - g_l
                if lead_w and spans[lead_end - 1] is not None:
                    # The band starts one page pixel of white past the box the
                    # lead digits draw in: their last ink, the white, the box's
                    # own line, the white, the band.
                    m2 = lead_end - 1
                    # Band starts a fixed step past the number ink. Nothing
                    # pulls it back. A clamp that stops the band cutting the
                    # first character is the wrong fix: a character close to
                    # its number lets the clamp win, the band starts on the box
                    # line, and the white on the right of the box goes to 0. Do
                    # not fix this by widening the cell either. That works and
                    # costs a patch of page height. Band overlap only puts a
                    # character left edge on white in place of tint.
                    start = (x + lead_w - widths[m2] + shifts[m2]
                             + spans[m2][1] + BAND_AFTER_BOX_PX * bw)
                    bx0 = start + BAND_OFF_X + bdx - g_l
                by0 = y - BAND_PAD_Y + BAND_OFF_Y_ROW + bdy - g_t
                bx1 = (x + seg_w - gap_here + BAND_PAD_X + BAND_OFF_X
                       + bdx + g_r + BAND_INSET)
                by1 = (y + line_h - 1 - BAND_GAP_Y + BAND_PAD_Y
                       + BAND_OFF_Y_ROW + bdy + g_b)
                # A block of one narrow mark and its pilcrow, or a shrunk
                # band, can land the right edge left of the left one; Pillow
                # refuses that, so the band is at least one pixel wide.
                bx1 = max(bx1, bx0)
                by1 = max(by1, by0)
                # A block of nothing but marks gets no band: a block of a line
                # number and its break has no lead to start the band after, so
                # the tint would fill the number's own box and the white round
                # the digits would go.
                lone_mark = PILCROW_OUTSIDE and all(
                    _is_count(pairs[j]) or pairs[j][0] == NL_MARK
                    for j in range(k, seg))
                tint = band_index(depths[min(ids[k], len(depths) - 1)])
                if not lone_mark and tint is not None:
                    d.rectangle([bx0, by0, bx1, by1],
                                fill=TINTS[tint],
                                outline=OUTLINE if OUTLINE_W else None, width=OUTLINE_W)
                    if band_y is None:
                        band_y = (by0, by1)
                # A source line that runs past the row edge carries on at the
                # left of the next row. The edge the line runs through is drawn
                # in WRAP_INK, so a reader sees where a line wraps rather than
                # having to notice a missing mark. It moves no glyph and costs
                # no patch.
                if seg == b and pairs[seg - 1][0] != NL_MARK:
                    # At the band's own right edge, past the inset and the pad,
                    # so the last letter keeps its clear columns.
                    # The wave is inset from the BAND's own top and foot by the
                    # same rows the text keeps, not from y: the band starts at
                    # y + BAND_OFF_Y, so an inset from y would cancel against
                    # band.offset_y and put the mark flush on both band edges,
                    # where it reads as overlapping the bands above and below.
                    wy0 = y + BAND_OFF_Y_ROW + BAND_TEXT_CLEAR
                    wy1 = y + line_h - 1 - BAND_GAP_Y + BAND_OFF_Y_ROW - BAND_TEXT_CLEAR
                    # The mark is placed PAST the last character of the row,
                    # and it must stay there. wrap_edge() already moves it left
                    # when it will not fit the page, and that move puts it on
                    # top of text, which no reader can read through.
                    #
                    # What keeps it off the text is WRAP_GUTTER, which reserves
                    # the width the mark needs, and _fit_width() refusing any
                    # layout that moves a mark at all, counted in CLAMP_HITS.
                    wx = x + seg_w - gap_here + BAND_PAD_X + BAND_INSET + MARK_CLEAR
                    # THE MARK CLEARS THE LAST GLYPH'S INK, not the sum of the
                    # advances.
                    #
                    # The line above places the mark past where the row's
                    # widths say it ends. A glyph whose ink fills its own
                    # advance, and w, e, ] and / all do, then inks right up to
                    # that point and the wave lands on it, with no clear column
                    # on runs such as "format(row" and 'sides["off"]'.
                    #
                    # spans[j] is a glyph's inked columns counted from its own
                    # pen, so the last glyph's ink ends at its pen plus
                    # spans[-1][1]. The mark takes whichever is further right,
                    # that ink plus its clearance or the advance-based place
                    # above, so a row that already had room is not moved and
                    # the page does not grow.
                    #
                    # RAISING mark.clear INSTEAD COSTS AND DOES NOT WORK. It
                    # moves every mark rather than the ones that touch, so it
                    # buys a bigger page and still leaves a mark touching.
                    if spans is not None and seg - 1 < len(spans) and spans[seg - 1]:
                        pen_last = (x + BAND_INSET + seg_w - gap_here
                                    - widths[seg - 1])
                        ink_right = pen_last + spans[seg - 1][1]
                        wx = max(wx, ink_right + WRAP_W + WRAP_INK_CLEAR)
                    wrap_edge(d, wx, wy0, wy1)
                if k == a and a > 0 and pairs[a - 1][0] != NL_MARK and not lone_mark:
                    wrap_edge(d, x - EDGE_INSET, wy0, wy1)
                cx = x + BAND_INSET
                for j in range(k, seg):
                    jf, jdy = face_for(pairs[j][0], pairs[j][2])
                    jy = y + jdy
                    if PLACEMENTS:
                        # The glyph follows its line, then its own word.
                        wk = words[j] if words is not None else -1
                        gx = ldx + (_placed("word:%d:%d" % (ids[j], wk), "dx")
                                    if wk >= 0 else 0)
                        gy = ldy + (_placed("word:%d:%d" % (ids[j], wk), "dy")
                                    if wk >= 0 else 0)
                        if gx or gy:
                            jy += gy
                            cx += gx
                    else:
                        gx = 0
                    # The marks between bands sit in their own white: the
                    # pilcrow EDGE_INSET columns right of its column, a
                    # blank-line count EDGE_INSET columns left of its. The
                    # advance does not change, so the row does not move.
                    mx = 0
                    if PILCROW_OUTSIDE:
                        if j == seg - 1 and pairs[j][0] == NL_MARK and seg - k > 1:
                            mx = EDGE_INSET
                        elif j < lead_end:
                            mx = -BAND_INSET
                    if mx:
                        cx += mx
                    if layout is not None:
                        page_chars.append((j, cx, jy, widths[j]))
                    # an INK_STEP mark draws its glyph left of its origin,
                    # so its ink starts CLEAR columns in: see char_widths()
                    sx = shifts[j]
                    if sx:
                        cx += sx
                    # The line end mark has no ink, so it opens no box: a run
                    # started at it would begin one blank column left of the
                    # number, and its trail would pull the right edge onto the
                    # last digit. The mark is not drawn by construction, and
                    # this test says so outright rather than asking a style
                    # override.
                    is_mark = _is_count(pairs[j])
                    if is_mark:
                        # a space between the pilcrow and the indent mark stays
                        # inside the one box; the box ends at the last mark's
                        # ink, not at the clear space after it, so it never
                        # reaches the band the next word sits on.
                        # The run is the ink itself, not the cells around it. A
                        # digit's cell runs its own adv past its ink, so a box
                        # on the cells leaves more white on the right of the
                        # digits than on their left, and no clearance knob
                        # reaches it.
                        sp = spans[j]
                        # The key holds the face itself, not id(jf). Python
                        # reuses the id of a freed face, and a new face then
                        # read an old face's box.
                        _bk = (jf, pairs[j][0])
                        gb = _BBOX_CACHE.get(_bk)
                        if gb is None:
                            gb = jf.getbbox(drawn(pairs[j][0]))
                            _BBOX_CACHE[_bk] = gb
                        ix0 = cx + (sp[0] if sp else 0)
                        ix1 = cx + (sp[1] if sp else widths[j])
                        iy0, iy1 = jy + gb[1], jy + gb[3] - 1
                        if run_start is None:
                            run_start, run_end = ix0, ix1
                            run_top, run_bot = iy0, iy1
                            run_ink = pairs[j][1]
                        else:
                            if pairs[j][1] != run_ink:
                                # the green line number ends and the red
                                # indent count begins: mark the seam
                                mark_splits.append(cx)
                                run_ink = pairs[j][1]
                            run_start = min(run_start, ix0)
                            run_end = max(run_end, ix1)
                            run_top = min(run_top, iy0)
                            run_bot = max(run_bot, iy1)
                    elif run_start is not None and pairs[j][0] != " ":
                        mark_runs.append((run_start, run_end, run_top, run_bot))
                        run_start = None
                        run_end = None
                        run_top = None
                        run_bot = None
                        run_ink = None
                    if pairs[j][0] == NL_MARK:
                        # THE LINE END MARK IS NEVER DRAWN. It keeps its width
                        # and its line id, so the page does not move, and no
                        # glyph is asked for. The mark stays in the stream
                        # because it carries the band, the row break rule, the
                        # band edge and the line id, and it is not a character
                        # a reader sees.
                        cx += widths[j]
                        continue
                    if _NO_GLYPHS:
                        pass
                    elif use_backend:
                        for ox, oy in _over_offsets(pairs[j][0]):
                            backend_text(img, (cx + ox, jy + oy), pairs[j][0],
                                         jf, pairs[j][1])
                    elif plain_soft:
                        for ox, oy in _over_offsets(pairs[j][0]):
                            d.text((cx + ox, jy + oy), pairs[j][0], font=jf,
                                   fill=pairs[j][1])
                    else:
                        for ox, oy in _over_offsets(pairs[j][0]):
                            ink_text(img, (cx + ox, jy + oy), pairs[j][0],
                                     jf, pairs[j][1], curve=curve,
                                     threshold=threshold,
                                     blur=blur if curve != "soft" or blur != "auto" else "full")
                    if pairs[j][0] in TAILED:
                        t = tail_box(jf, pairs[j][0], line_h - jdy, tails)
                        if t is not None:
                            d.rectangle([cx + t[0], jy + t[1],
                                         cx + t[2], jy + t[3]],
                                        fill=pairs[j][1])
                    cx += widths[j] - gx - mx - sx
                x += seg_w + BAND_INSET
                k = seg
            if run_start is not None:
                mark_runs.append((run_start, run_end, run_top, run_bot))
            if __import__("os").environ.get("DENSEPACK_DEBUG_RUNS"):
                sys.stderr.write("row %d runs %s\n" % (row_n, [(round(a0), round(a1)) for a0, a1, _t, _b in mark_runs]))
            for rx0, rx1, ry0, ry1 in mark_runs:
                # One page pixel of white sits between the outline and the
                # digits on all four sides. The run's own layout extent is only
                # the window the digits are looked for in; the outline is set
                # from the pixels they really drew.
                # A trial that draws no glyphs has no digits to fit a box to,
                # and nothing reads its boxes.
                found = None if _NO_GLYPHS else _ink_bounds(
                    img, (rx0 - 2 * bw, ry0 - 2 * bw, rx1 + 2 * bw, ry1 + 2 * bw))
                if found is None:
                    continue
                ix0, iy0, ix1, iy1 = found
                # ALL FOUR SIDES COME FROM THE INK, so the digits sit centred
                # in their box with the same white on every side.
                #
                # Top and bottom taken from the BAND would make the box exactly
                # as tall as the band, so the box would touch the band's top
                # and bottom edges, the digits, which carry no descender, would
                # sit high inside it, and neighbouring boxes would run into
                # each other and into the band.
                #
                # Levelness survives. Every box on the page holds digits, and
                # digits all ink the same rows, so a box fitted to its own ink
                # lands at the same height as its neighbours.
                #
                # mark.box_fits_band takes top and bottom from the band
                # instead.
                if band_y is None or BOX_FITS_INK:
                    top, bot = iy0 - 2, iy1 + 2
                else:
                    top = (img._out(band_y[0]) if isinstance(img, Shrunk)
                           else int(round(band_y[0])))
                    bot = (img._out(band_y[1]) if isinstance(img, Shrunk)
                           else int(round(band_y[1])))
                small.rectangle([ix0 - 2, top, ix1 + 2, bot],
                                outline=MARK_BOX_INK, width=1)
                for sx_split in mark_splits:
                    if rx0 < sx_split < rx1:
                        sxs = (img._out(sx_split) if isinstance(img, Shrunk)
                               else int(round(sx_split)))
                        sxs = _seam_column(img, (ix0, iy0, ix1, iy1), sxs)
                        small.rectangle([sxs, top, sxs, bot],
                                        fill=MARK_BOX_INK)
            y += pitch + snap(extras[row_n])
        page_imgs.append(img.im if isinstance(img, Shrunk) else img)
        if layout is not None:
            layout.setdefault("pages", []).append(
                {"rows": page_rows, "chars": page_chars, "sheet": 0,
                 "x_off": 0, "width": width, "height": height})
    if layout is not None:
        layout["pairs"] = [(p[0], p[2]) for p in pairs]
        layout["ids"] = ids
        layout["words"] = words
        layout["line_h"] = line_h
        layout["pad"] = PAD
        layout["blank_mark"] = BLANK_MARK
        layout["blank_runs"] = {j for j, p in enumerate(pairs) if _is_count(p)}

    import bisect
    line_ends = [j for j, p in enumerate(pairs) if p[0] == NL_MARK]

    def opens_on(k):
        # The first line that STARTS on this image: a first row that
        # continues the line before holds only that line's end.
        if not pages[k]:
            return None
        a = pages[k][0][0]
        return bisect.bisect_left(line_ends, a) + (1 if a and pairs[a - 1][0] != NL_MARK else 0)

    # Two pages side by side on one sheet. A Read returns one file, so every
    # page after the first costs the reader a whole extra Read turn. Two pages
    # of 580 px sit inside densepack's 1568 px cap at the same patch cost as
    # the two pages apart, so most files take one Read. A gray divider marks
    # the seam.
    for s in range(0, len(page_imgs), COLUMNS):
        pair = page_imgs[s:s + COLUMNS]
        sheet_w = sum(im.width for im in pair) + SHEET_GAP * (len(pair) - 1)
        sheet_h = max(im.height for im in pair)
        if len(pair) > 1 and sheet_w > dp.CAP_W:
            # A page wider than half the cap goes out alone; never a
            # sheet the API would shrink.
            for q, im in enumerate(pair):
                n += 1
                path = "%s-%d.png" % (out_stem, n)
                written.append((path,) + save_page(im, path))
                PAGE_FIRST_LINE[path] = opens_on(s + q)
                if layout is not None:
                    layout["pages"][s + q]["sheet"] = n
            continue
        sheet = Image.new("RGB", (sheet_w, sheet_h), BACKGROUND)
        # A Shrunk page is already at its final size, and the flag that tells
        # save_page so lives on the page image, not on this fresh sheet.
        # Without it the plain path would shrink the sheet a second time.
        if any(im.info.get("densepack_small") for im in pair):
            sheet.info["densepack_small"] = True
        x = 0
        for q, im in enumerate(pair):
            sheet.paste(im, (x, 0))
            if layout is not None:
                layout["pages"][s + q]["sheet"] = n + 1
                layout["pages"][s + q]["x_off"] = x
            x += im.width + SHEET_GAP
        if len(pair) > 1:
            d = ImageDraw.Draw(sheet)
            seam = 0
            for im in pair[:-1]:
                seam += im.width + SHEET_GAP // 2
                d.line([(seam, 0), (seam, sheet_h)], fill=DIVIDER,
                       width=DIVIDER_W)
                seam += SHEET_GAP - SHEET_GAP // 2
        n += 1
        path = "%s-%d.png" % (out_stem, n)
        written.append((path,) + save_page(sheet, path))
        PAGE_FIRST_LINE[path] = opens_on(s)
    return written, int(max_w), line_h


# A fenced block whose fence line names python. Python blocks draw as banded
# pictures; every other label, and no label, is still lifted out as text.
_PY_FENCE = re.compile(r"\A```[ \t]*(?:python|py)[ \t]*\r?\n(.*?)\n?```\Z",
                       re.S | re.I)


def python_body(block):
    """The source inside a fenced block, or None when the fence is not python."""
    hit = _PY_FENCE.match(block)
    return hit.group(1) if hit else None



# Drawn at SUPERSAMPLE times the size and shrunk. Each final pixel is the mean
# of several drawn ones, so a stem lands as one clean column, and the font's
# hints run at the larger size where they work. 1 draws at the final size.
# Each glyph lands on a whole output pixel rather than keeping the sub-pixel
# remainder of its position. See Shrunk.paste.
SNAP_GLYPHS = bool(_S.get("page.snap_glyphs", True))
# A glyph is rasterised at the size it lands at, not at the layout's size and
# then shrunk. See backend_text.
GLYPH_AT_FINAL_SIZE = bool(_S.get("page.glyph_at_final_size", True))
SUPERSAMPLE = int(_S.get("page.supersample", 1) or 1)
# Hamming keeps more one pixel stems than Box or Lanczos when a page shrinks by
# three, and Lanczos rings.
SHRINK_FILTER = {"box": Image.BOX, "bilinear": Image.BILINEAR, "hamming": Image.HAMMING,
                 "bicubic": Image.BICUBIC, "lanczos": Image.LANCZOS}.get(
    str(_S.get("page.supersample_filter", "hamming")).lower(), Image.HAMMING)


# freetype_glyph holds the limit, so the Read gate checks the same number
# without loading this module.
MISSING_GLYPH_MAX = freetype_glyph.MISSING_GLYPH_MAX


class FontCannotDraw(ValueError):
    """The font has no glyph for too much of this text."""


def font_covers(text):
    """True when the font can draw all but MISSING_GLYPH_MAX of the text."""
    return freetype_glyph.font_covers(text, (_S.get("font.regular") or [""])[0])


def pack_code(text, px, out_stem, python=True, legend=None, layout=None,
              reader=None, title=""):
    """Draw text as banded code pages named <out_stem>-1.png and up, at
    SUPERSAMPLE times the size, then shrink each page by that factor.
    title is the source file's name, drawn at the head of the key row.

    Raises FontCannotDraw when the font lacks glyphs for more than
    MISSING_GLYPH_MAX of the text. Every caller catches a raise and sends
    the text instead."""
    if not font_covers(text):
        raise FontCannotDraw("the font cannot draw %.0f%% of this text"
                             % (100 * freetype_glyph.missing_share(
                                 text, (_S.get("font.regular") or [""])[0])))
    global _LEGEND_TITLE, _TAB_KEY, SNAP_GLYPHS
    _LEGEND_TITLE = str(title or "")
    # page.snap_glyphs is one setting for every reader, not a lookup keyed by
    # model name, so one page shape reaches every model.
    SNAP_GLYPHS = bool(_S.get("page.snap_glyphs", True))
    # The page's own marks are private-use code points, so a source's own
    # pilcrow, section sign or double dagger draws as itself, and build_flow's
    # guard fires only on those code points.
    # The code page has its own numbers, page.code_* in style.py: a wider
    # layout, a supersample and a final width. page.width and page.height are
    # the narrow prose page.
    # There is one code page shape, page.code_width wide, for every reader and
    # every glyph size. A glyph size that fell back to a narrow grid would draw
    # many narrow pages where the wide page draws one.
    fable = bool(_S.get("page.code_width"))
    if fable and _S.get("page.fill_bottom") and not _FILL_GUARD:
        # THE SEARCH DRAWS ON A WORK STEM, IN MEMORY. Every trial draws on a
        # stem of its own and keeps its pages in _TRIAL_PAGES instead of
        # encoding them, so no hook that lists the image folder can hand a
        # reader a page the search then rejects. Only the winner's pages are
        # written onto the final names, at the end.
        global _TRIAL
        work = out_stem + ".draw"
        _TRIAL = True
        try:
            res = _fit_page_width(text, px, work, python, legend, layout,
                                  reader, title)
            out = _write_trial(res, out_stem)
        finally:
            _TRIAL = False
            _TRIAL_PAGES.clear()
            _GLYPHLESS.clear()
        _drop_stale_pages(work, [])
        _drop_stale_pages(out_stem, out[0])
        return out
    s = int(_S.get("page.code_supersample") or SUPERSAMPLE) if fable else SUPERSAMPLE
    # a big file steps down: the tiers name the largest supersample for a
    # source up to that many characters, 0 meaning no limit
    if fable:
        for limit, tier in (_S.get("page.code_supersample_tiers") or []):
            if not limit or len(text) <= int(limit):
                s = min(s, max(1, int(tier)))
                break
    final_w = int(_S["page.code_width"]) if fable else None
    layout_w = int(_S.get("page.code_layout_width") or 0) if fable else 0
    # the key row names the glyph size the page ships at: the size shrunk by
    # the layout to final width
    glyph = round(px * final_w / layout_w) if (fable and layout_w and final_w) else px
    # The key row does not name the size; glyph stays computed for the callers
    # below.
    _LEGEND_TITLE = ("file=%s" % _LEGEND_TITLE).strip()
    # The red indent count expands a leading tab to 4 columns, the same count
    # as 4 spaces, so a tab-indented file says so and a reader edits with tabs.
    _TAB_KEY = any(line.startswith("\t") for line in text.split("\n"))
    # A line ending never reaches this function. build_flow raises on a
    # carriage return, and every caller reads its file with universal newlines,
    # so a CRLF file arrives here already turned to LF. The page therefore
    # cannot say which ending the file used, and a reader writes whichever its
    # own machine uses, so a CRLF file rebuilds one byte short a line. Naming
    # the ending here would be dead code. Fixing it means carrying the ending
    # from whichever script reads the file, which is pointer.py and
    # read_gate.py.
    if s <= 1 and not fable:
        return _pack_code(text, px, out_stem, python, legend, layout)
    # Every pixel count the page is drawn with grows by s, so the shrunk page
    # keeps the same padding, outline, wrap edge and gaps it has at one times;
    # without this the glyphs sit on the band outlines after the shrink.
    g = globals()
    names = [n for n in ("PAGE_W", "CAP_H", "FONT_MAX_PX", "PAD", "GAP", "THICK_DX",
                         "EDGE_INSET", "BAND_PAD_X", "BAND_PAD_Y",
                         "BAND_OFF_X", "BAND_OFF_Y", "BAND_INSET",
                         "BAND_GAP_X", "BAND_GAP_Y", "ROW_GAP", "PARA_GAP",
                         "OUTLINE_W", "WRAP_W", "DIVIDER_W", "SHEET_GAP",
                         "PAGE_EXTRA", "SWATCH_PAD", "SWATCH_GAP", "CLEAR",
                         "CLEAR_NARROW",
                         # the spacing rules
                         "MARK_CLEAR", "COUNT_CLEAR", "BOX_CLEAR", "BOX_GAP", "SEAM_GAP", "QUOTE_RUN_CLEAR",
                         "SAME_CLEAR", "STEM_QUOTE_CLEAR", "STEP_RIGHT", "LETTER_SPACE",
                         # the larger marks and the lifted token are pixels at
                         # the shipped size too
                         "BIGGER_PX", "LIFT_PX") if n in g]
    keep = {n: g[n] for n in names}
    grow = "BAND_GROW" in g and g["BAND_GROW"]
    for n in names:
        g[n] = keep[n] * s
    if layout_w:
        # the page adds 4 px of outline outside PAGE_W, PAD and PAGE_EXTRA
        g["PAGE_W"] = float((layout_w - 4 - 2 * keep["PAD"] - keep["PAGE_EXTRA"]) * s)
        # the wide page carries its own height cap, page.code_height at
        # the layout size, so one small file is one page
        if _S.get("page.code_height"):
            g["CAP_H"] = int(_S["page.code_height"]) * s
    if grow:
        g["BAND_GROW"] = tuple(v * s for v in grow)
    # a pick's size, nudge and spacing are pixels at the shipped size, and
    # the bold simulation's quarter pixel too; each grows by s with the page
    keep_over = {ch: dict(v) for ch, v in CHAR_OVER.items()}
    for ch, v in CHAR_OVER.items():
        for key in ("px", "dx", "dy", "adv"):
            if v.get(key):
                v[key] = v[key] * s
    global SHRINK_TO, SHRINK_BY
    SHRINK_TO, SHRINK_BY = (final_w or None), (None if final_w else s)
    try:
        written, max_w, line_h = _pack_code(text, px * s, out_stem, python,
                                            legend, layout)
    finally:
        SHRINK_TO, SHRINK_BY = None, None
        for n in names:
            g[n] = keep[n]
        if grow:
            g["BAND_GROW"] = grow
        CHAR_OVER.clear()
        CHAR_OVER.update(keep_over)
    # every page was shrunk and written small by save_page() as it finished
    out = [(path, w, h) for path, w, h in written]
    if final_w:
        ratio = final_w / (max_w if max_w else final_w)
        return out, final_w, max(1, round(line_h * ratio))
    return out, int(max_w / s), max(1, line_h // s)


def _page_image(path):
    """The page at path, from the search's memory when a trial holds it."""
    im = _TRIAL_PAGES.get(str(path))
    if im is not None:
        return im.convert("RGB")
    return Image.open(str(path)).convert("RGB")


def _bottom_white(path):
    """Rows of page background under the last ink on a written page."""
    im = _page_image(path)
    w, h = im.size
    bg = im.getpixel((0, h - 1))
    for y in range(h - 1, -1, -1):
        if im.crop((0, y, w, y + 1)).tobytes() != bytes(bg) * w:
            return h - 1 - y
    return h


def _top_white(path):
    """Rows of page background above the first ink on a written page."""
    im = _page_image(path)
    w, h = im.size
    bg = im.getpixel((0, 0))
    for y in range(h):
        if im.crop((0, y, w, y + 1)).tobytes() != bytes(bg) * w:
            return y
    return h


_FILL_GUARD = False
_FILL_PASS = False
_FILL_STRETCH = None  # the row pitch factor of the final fill pass
_FILL_LAST = None  # (layout width chosen, base layout width) of the last fill


_WIDTH_GUARD = False


def _page_cost(res):
    """What one result costs a reader: its visual tokens, plus two a page.

    A page is ceil(w / 28) by ceil(h / 28) patches. The two a page is the
    Read turn the page itself costs, which is what makes a two page result
    lose to a one page result of the same patch count.
    """
    return sum(-(-w // 28) * -(-h // 28) + 2 for _f, w, h in res[0])


def _drop_stale_pages(out_stem, pages):
    """Remove the page files a losing trial left past the winner's last page.

    Every trial of _fit_page_width, _fit_width and _fill_bottom writes to the
    same stem, and a trial that needs more pages than the winner leaves its
    extra pages on disk, where a reader that names a page by number can fetch
    one. Only the numbered page files of this stem are removed; a sheet the
    drop gate makes later is named -all and is not one of them.
    """
    keep = {Path(f).name for f, _w, _h in pages}
    stem = Path(out_stem)
    numbered = re.compile(re.escape(stem.name) + r"-\d+\.png$")
    for f in stem.parent.glob(stem.name + "-*.png"):
        if numbered.match(f.name) and f.name not in keep:
            try:
                f.unlink()
            except OSError:
                pass


def _fit_page_width(text, px, out_stem, python, legend, layout, reader, title):
    """Draw at every page width in page.code_width_choices, keep the cheapest.

    Find the width that wastes least, grow down before growing sideways, and
    offer 756 px or 784 px.

    Growing down happens first and inside each trial, because _fit_width()
    calls _fill_bottom() before it does anything else. Only when that has run
    at one width does this compare it against the next width.

    The layout width moves with the page width on every trial, keeping the
    ratio the settings ship, so a wider page packs proportionally more into a
    row rather than drawing the same row larger. Both shipped widths are whole
    28 px patches, so neither adds a white column.

    Nothing is scaled after hinting at any ratio, because backend_text() asks
    FreeType for the glyph at the size it will land at. Forcing the layout
    width down to the page width costs far more tokens for the same file.

    A width wins on two counts in order. First the patch cost. Then how many
    wrap marks the draw had to move onto the text, because a mark on a letter
    is a misread and a misread costs output at five times input. A tie keeps
    the width already in the settings, which is the first in the list.

    The winner is drawn once with glyphs at the end when it was a glyphless
    trial.
    """
    global _WIDTH_GUARD, _FILL_GUARD
    choices = [int(w) for w in (_S.get("page.code_width_choices") or ())]
    keep_w = _S.get("page.code_width")
    keep_lw = _S.get("page.code_layout_width")
    if _WIDTH_GUARD or not keep_w or not choices:
        return _fit_width(text, px, out_stem, python, legend, layout, reader,
                          title)
    # The width already set is tried first, so a tie keeps it, but only when
    # the list names it: a list holding 784 alone draws 784.
    if int(keep_w) in choices:
        choices.remove(int(keep_w))
        choices.insert(0, int(keep_w))

    best = None
    best_w = choices[0]
    best_clamp = best_cost = None
    layout_w = {}
    _WIDTH_GUARD = True
    try:
        # The layout keeps the ratio the settings ship, so a wider page packs
        # proportionally more into a row. Rounding to a whole column keeps the
        # arithmetic the layout does on integers.
        ratio = float(keep_lw) / float(keep_w) if keep_lw and keep_w else 1.0
        # Every glyphless trial both widths will ask for, drawn ahead at
        # once: the base layout of each width and its fifteen widening
        # steps. _fill_bottom() and _fit_width() take them from _PREFETCH.
        jobs = []
        for width in choices:
            b = int(round(width * ratio))
            jobs.append((width, b))
            jobs.extend((width, lw) for lw in range(b + 4, b + 61, 4))
        _prefetch_trials(text, px, python, reader, title, out_stem, jobs)
        for width in choices:
            _S["page.code_width"] = width
            _S["page.code_layout_width"] = int(round(width * ratio))
            CLAMP_HITS[0] = 0
            # Each width draws on its own stem, so its pages and the other
            # width's never share a name in memory.
            trial = _fit_width(text, px, "%s.w%d" % (out_stem, width), python,
                               legend, layout, reader, title)
            layout_w[width] = _LAST_LAYOUT_W
            hits = CLAMP_HITS[0]
            cost = _page_cost(trial)
            # Cost first, marks second. A mark moved onto a letter is a misread
            # and a misread costs output at five times input, but a larger page
            # costs tokens on every page, which is the larger bill, so the
            # clamp count breaks the tie whenever two widths cost the same.
            if best is None or cost < best_cost or (
                    cost == best_cost and hits < best_clamp):
                _forget(best)
                best, best_w, best_clamp, best_cost = trial, width, hits, cost
            else:
                _forget(trial)
        # The winner is drawn once with glyphs when it was a glyphless trial: a
        # widening winner, or the base draw of a file of more than one page. A
        # one page file's fill draw is complete already. This is the one real
        # draw of the whole search.
        if best is not None and str(best[0][0][0]) in _GLYPHLESS:
            _S["page.code_width"] = best_w
            _S["page.code_layout_width"] = layout_w.get(best_w, int(round(best_w * ratio)))
            CLAMP_HITS[0] = 0
            _forget(best)
            _FILL_GUARD = True
            try:
                best = pack_code(text, px, out_stem + ".final", python, legend,
                                 layout, reader, title)
            finally:
                _FILL_GUARD = False
    finally:
        _WIDTH_GUARD = False
        _PREFETCH.clear()
        _S["page.code_width"] = keep_w
        _S["page.code_layout_width"] = keep_lw
    return best


def _fit_width(text, px, out_stem, python, legend, layout, reader, title):
    """Draw, then try wider layouts and keep the page that costs least.

    _fill_bottom only narrows the layout, which grows the glyph to fill white
    space it already paid for. It never widens, so content that does not fit
    simply takes another row or another page.

    A wider layout draws a smaller glyph, fits more characters a row and so
    needs fewer rows, which puts a page the indent counts made taller back
    inside fewer patches, at a slightly smaller glyph.
    """
    # The width the page lays out on, one width for every model.
    base = int(_S.get("page.code_layout_width") or 0)

    def put(value):
        _S["page.code_layout_width"] = value

    global _LAST_LAYOUT_W
    _LAST_LAYOUT_W = base
    best = _fill_bottom(text, px, out_stem, python, legend, layout, reader,
                        title)
    if not base:
        return best

    # NATIVE LAYOUT. When the layout width already equals the page width there
    # is nothing to search: every width this loop would try is WIDER than the
    # page, and a layout wider than the page means each glyph is rasterised for
    # one grid and resampled onto another. That resample softens every letter,
    # and MacType does the opposite, rasterising a glyph at the size it is
    # shown at so its hinting lands on the real pixel grid.
    #
    # Nothing else is given up. The growth ladder is untouched: more text still
    # takes more rows, then a taller page up to the height cap, then a new
    # page. The page width search across page.code_width_choices is untouched,
    # and both its widths stay exact multiples of 28.
    # ONLY WHEN NOTHING CLAMPS. The loop below is what keeps a wrap mark off
    # the text: it searches for a layout whose CLAMP_HITS is zero and prefers
    # it over one that costs a patch row less. Skipping it would leave marks
    # drawn through characters that no reader can read past.
    #
    # A widened layout does bring back the rescale the native layout removes,
    # so the trade is taken only when a mark would otherwise land on a letter.
    # A misread costs output at five times input, which is more than the
    # sharper glyph saves.
    page_w = int(_S.get("page.code_width") or 0)
    if page_w and base <= page_w and not CLAMP_HITS[0]:
        return best

    cost = _page_cost

    global _FILL_GUARD
    low = cost(best)
    misses = 0
    lw = base
    # How many marks the first draw had to move onto the text. A layout that
    # moves none is worth more than a layout that costs one patch row less,
    # because a mark on a letter is a misread and a misread costs output at
    # five times input.
    best_clamp = CLAMP_HITS[0]
    best_lw = base
    try:
        # The guard stops each trial re-entering _fill_bottom, which would
        # narrow the layout straight back and pin the height to the first
        # draw. These trials are the plain renderer at one width each.
        _FILL_GUARD = True
        # Stop at the FIRST width that wins back a patch row. The point is to
        # fit the content into space the page already pays for, not to hunt
        # the smallest page. Minimising tokens here walks the glyph down until
        # a reader starts misreading, and a misread costs output at 5 times
        # input, which is more than the page ever saves.
        global _NO_GLYPHS
        # The fifteen widening trials depend on nothing but their own width, so
        # they draw at once in child processes, glyphless, and the walk below
        # reads them in width order with the rule unchanged. A child that
        # fails, or a wide burst, sends them through the loop one after another
        # instead.
        page_w_now = int(_S.get("page.code_width") or 0)

        def widen(lw):
            # Without this line _NO_GLYPHS is a local copy, and every trial draws every letter.
            global _NO_GLYPHS
            hit = _PREFETCH.pop((page_w_now, lw), None)
            if hit is not None:
                return hit
            put(lw)
            CLAMP_HITS[0] = 0
            _NO_GLYPHS = True
            try:
                trial = pack_code(text, px, "%s.t%d" % (out_stem, lw), python,
                                  legend, layout, reader, title)
            finally:
                _NO_GLYPHS = False
            return trial, CLAMP_HITS[0]

        while lw < base + 60:
            lw += 4
            trial, hits = widen(lw)
            # COST FIRST, CLAMPED MARKS SECOND, the same rule _fit_page_width
            # holds. The redraw in _fit_page_width keeps the file and the
            # returned sizes the same page.
            if cost(trial) < low or (cost(trial) == low and hits < best_clamp):
                _forget(best)
                best, best_clamp, low, best_lw = trial, hits, cost(trial), lw
                if hits == 0:
                    break
            else:
                _forget(trial)
        # Every trial draws on its own stem into memory, and a widening trial
        # draws no glyphs. _fit_page_width() draws the one overall winner with
        # glyphs at the end, at the layout width recorded here, so a width that
        # loses never costs a real draw.
        _LAST_LAYOUT_W = best_lw
    finally:
        _FILL_GUARD = False
        put(base)
    return best


# WHITE CAN STAY AT THE FOOT, and the reason is the ORDER these three run in,
# not anything inside _fill_bottom().
#
# _fit_page_width() calls _fill_bottom() FIRST and _fit_width() after it, so
# the fill measures a page that is then laid out again. A margin the fill
# measures can belong to a taller page than the one a reader sees.
#
# TWO THINGS DO NOT ANSWER IT:
#
#   Growing the glyph cannot fill it. line_h moves in whole pixels, so the
#   smallest growth that changes anything costs one pixel on every row,
#   which is more page than the white it reclaims. Fractional sizes do
#   draw, so the size is not the obstacle; the row pitch quantum is.
#
#   Spreading the white as row pitch through _FILL_STRETCH is the right
#   lever and it works, but computing it here corrects the wrong page, for
#   the ordering reason above.
#
# The fix is to run the fill LAST, once the width search has settled, which is
# a change to _fit_page_width() rather than to this function.


def _fill_bottom(text, px, out_stem, python, legend, layout, reader, title):
    """Grow the glyph from its floor until the page's foot margin equals its
    head margin, with the page the same height and one page.

    The floor page is drawn
    first; its height is padded to the 28 px patch step and a band of white
    sits under the last row. The glyph then grows by the ratio of the space
    available to the space used, the row pitch stays fractional for that
    pass so the rows spread over the page exactly, and the result is kept
    when the page is still one page of the same height with its last ink at
    least as far from the bottom edge as the first ink is from the top, and
    never more than three rows further. Up to six passes correct the ratio
    when the wrap points move. A file of more than one page keeps the floor."""
    global _FILL_GUARD, _FILL_PASS, _FILL_STRETCH
    base = int(_S.get("page.code_layout_width") or 0)
    if not base:
        return pack_code(text, px, out_stem, python, legend, layout, reader, title)
    # NATIVE LAYOUT, the same guard _fit_width() carries. This function NARROWS
    # the layout to grow the glyph into white space at the foot of a page,
    # which also breaks the one to one mapping between layout space and page
    # space and puts the resample back. With the layout already at the page
    # width the glyph is drawn at its true size, so the trade this search makes
    # is not one worth taking.
    #
    # _FILL_GUARD must be set around the draw exactly as the search below sets
    # it: pack_code() re-enters _fit_page_width() whenever the guard is clear,
    # and that path leads back here. Returning without it recurses forever.
    page_w = int(_S.get("page.code_width") or 0)
    if page_w and base <= page_w:
        _FILL_GUARD = True
        try:
            return pack_code(text, px, out_stem, python, legend, layout,
                             reader, title)
        finally:
            _FILL_GUARD = False
    def put(value):
        _S["page.code_layout_width"] = value

    _FILL_GUARD = True
    try:
        # The first draw finds the page count without glyphs. A file of more
        # than one page keeps the floor and goes back glyphless, because
        # nothing reads its pixels and _fit_page_width() draws the winner once
        # with glyphs at the end. A one page file is drawn again with glyphs,
        # because the fill below measures its white.
        global _NO_GLYPHS
        hit = _PREFETCH.pop((int(_S.get("page.code_width") or 0), base), None)
        if hit is not None:
            best, CLAMP_HITS[0] = hit
        else:
            _NO_GLYPHS = True
            try:
                best = pack_code(text, px, out_stem, python, legend, layout, reader, title)
            finally:
                _NO_GLYPHS = False
        if len(best[0]) != 1:
            return best
        _forget(best)
        best = pack_code(text, px, out_stem, python, legend, layout, reader, title)
        path = best[0][0][0]
        height = best[0][0][2]
        top = _top_white(path)
        bottom = _bottom_white(path)
        used = height - top - bottom
        if used <= 0 or bottom <= top:
            return best
        ratio = (height - 2 * top) / float(used)
        best_lw = base
        last_lw = base

        def draw(lw):
            global _FILL_PASS
            put(lw)
            _FILL_PASS = True
            try:
                trial = pack_code(text, px, "%s.f%d" % (out_stem, lw), python,
                                  legend, layout, reader, title)
            finally:
                _FILL_PASS = False
                put(base)
            ok = len(trial[0]) == 1 and trial[0][0][2] == height
            foot = _bottom_white(trial[0][0][0]) if ok else -1
            return trial, ok and foot >= top, foot

        # the ratio gives the first guess; the wrap points move with the
        # width, so the guess is walked up in steps of two until the page
        # holds, then down until the foot margin would drop under the head
        # margin, twelve draws at most
        lw = min(base - 1, max(1, int(round(base / ratio))))
        draws = 0
        trial, good, foot = draw(lw)
        draws += 1
        while not good and lw + 2 < base and draws < 12:
            _forget(trial)
            lw += 2
            trial, good, foot = draw(lw)
            draws += 1
        if good:
            _forget(best)
            best, best_lw, last_lw = trial, lw, lw
            while draws < 12 and lw - 2 > 1:
                trial2, good2, foot2 = draw(lw - 2)
                draws += 1
                last_lw = lw - 2
                if not good2:
                    _forget(trial2)
                    break
                lw -= 2
                _forget(best)
                best, best_lw = trial2, lw
        else:
            _forget(trial)
            last_lw = lw
        # the largest glyph is found; the white still left under the last band
        # is spread over the rows as row spacing, so the foot margin equals the
        # head margin
        foot = _bottom_white(best[0][0][0])
        stretch = None
        if foot > top + 4:
            # three rows of slack, or the stretched canvas pads onto the
            # next patch row and the pass is thrown away
            stretch = 1.0 + (foot - top - 3) / float(max(1, height - top - foot))
        if last_lw != best_lw or stretch:
            put(best_lw)
            _FILL_PASS = True
            _FILL_STRETCH = stretch
            try:
                final = pack_code(text, px, out_stem + ".s", python, legend,
                                  layout, reader, title)
            finally:
                _FILL_PASS = False
                _FILL_STRETCH = None
                put(base)
            if len(final[0]) == 1 and final[0][0][2] == height and _bottom_white(final[0][0][0]) >= top:
                _forget(best)
                best = final
            else:
                _forget(final)
                if stretch and not _TRIAL:
                    # the stretch tipped the page: draw the best without it. In
                    # the search's memory mode the best is still held, so no
                    # redraw is needed.
                    put(best_lw)
                    _FILL_PASS = best_lw != base
                    try:
                        best = pack_code(text, px, out_stem, python, legend, layout, reader, title)
                    finally:
                        _FILL_PASS = False
                        put(base)
        global _FILL_LAST
        _FILL_LAST = (best_lw, base)
        return best
    finally:
        _FILL_GUARD = False
        _FILL_PASS = False
        _FILL_STRETCH = None


def pack_fenced(fences, px, out_stem):
    """Draw the python blocks among fences as banded pages.

    Returns (pages, drawn): the page paths in order, as strings, and how many
    blocks were drawn. Each page carries the same #=N=# marker the caller put
    in the report or brief where the block used to be, so the reader lines a
    page up with its hole. A block whose fence names anything else is not
    drawn and stays in the caller's text file. Nothing here raises: a drawing
    that fails returns no page and the caller's text lift stands alone.
    """
    parts = []
    drawn = 0
    for n, block in enumerate(fences, 1):
        body = python_body(block)
        if body is None:
            continue
        drawn += 1
        parts.append("#=%d=#\n%s\n" % (n, body.rstrip("\n")))
    if not parts:
        return [], 0
    try:
        written, _target, _lh = pack_code("\n".join(parts), px, out_stem)
    except Exception:  # noqa: BLE001
        return [], 0
    return [str(p) for p, _w, _h in written], drawn
