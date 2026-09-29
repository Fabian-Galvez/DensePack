"""Pack a code file into a banded condensed image.

This file packs a source file into one long stream of characters. Each
source line gets its own background band. The band color is the nesting
depth of the line. Each line starts with its line number. An indented line
holds its exact indent as a count. The first page holds a key row that names
the bands and the marks. The model needs nothing else to read the page.

FreeType renders each character through freetype_glyph.py on each platform.
The Pillow path renders a character when FreeType cannot open the face.

A caller uses two functions. pack_code(text, px, out_stem) packs one whole
source file. pack_fenced(fences, px, out_stem) packs the python-labeled
blocks taken from a report or a brief. The two return what densepack.pack
returns. That is a list of (path, width, height), the wrap target and the
line height.
"""
import keyword
import math
import os
import re
import sys
import tokenize
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import densepack as dp  # noqa: E402
# Pillow gives the canvas, the rectangle fill, the resampler, the palette
# quantizer and the PNG encoder. Pillow does not set the value of an ink
# pixel. paste_ink() composites each glyph and blends in linear light the way
# MacType does. Without Pillow, this file needs its own PNG encoder.
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
try:
    # numpy does the linear-light blend. Without numpy, paste_ink() uses
    # Pillow's sRGB compositing.
    #
    # ONE BLAS THREAD. numpy's OpenBLAS reserves a work buffer for each core
    # when the library loads. The blend is elementwise, and no pack uses these
    # buffers. On a machine with many cores, the buffers commit hundreds of
    # megabytes to a hook process before its first pack. A burst of hooks
    # multiplies that. OpenBLAS reads the variable once, when it loads. This
    # code sets the variable before the import and keeps a value that is
    # already in the environment.
    import os as _os  # noqa: E402
    _os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    import numpy as _np  # noqa: E402
except ImportError:
    _np = None
import style  # noqa: E402
import freetype_glyph  # noqa: E402

# Each number and color below comes from style.load(). style.load() reads the
# defaults in style.py and any style.json on disk.
_S = style.load()

BACKGROUND = _S["page.background"]
OUTLINE = _S["band.outline"]
OUTLINE_W = _S["band.outline_width"]
MARK_BOX_INK = tuple(_S.get("mark.box_ink") or (0, 0, 0))  # the box around a line break run
BOX_CLEAR = int(_S.get("mark.box_clear", 0) or 0)  # white between the box and the band after it, in layout pixels
# The box around a line number fits its own digits on its left and right.
# mark.box_fits_band, which style.py ships on, takes its top and bottom from
# the band of its row. Off, the box fits its digits on all four sides. See
# the render loop.
BOX_FITS_INK = not bool(_S.get("mark.box_fits_band", False))
BOX_GAP = float(_S.get("mark.box_gap", 0) or 0)
SEAM_GAP = float(_S.get("mark.seam_gap", 0) or 0)  # white, rule, white between a line number and an indent count
DIVIDER = _S["page.divider"]
DIVIDER_W = _S["page.divider_width"]
WRAP_W = _S["code.wrap_width"]
# The text width of one page column, from page.width. 580 px of page gives 560
# px of text. The column loses page.pad on each side and the 8 px that the
# render loop adds. A4 is 794 px of page.
PAGE_EXTRA = 8
PAGE_W = float(_S["page.width"] - 2 * _S["page.pad"] - PAGE_EXTRA)
# The page ends at its widest row. See page.trim in style.py.
PAGE_TRIM = bool(_S.get("page.trim", True))
# Source rows one page holds, or 0 to fill the page height.
PAGE_LINES = _S["page.lines"]
# Page columns on one sheet.
COLUMNS = _S["page.columns"]
# One block above GAP maps the spacing constants of this file.
# The horizontal scale of the page. Below 1.0, the render step condenses each
# glyph and keeps its height. More characters then fit a row at the same size.
# See face_for() in pack_code.
SCALE_X = float(_S.get("font.scale_x", 1.0) or 1.0)
LETTER_SPACE = _S["space.letter"]
PARA_GAP = _S["space.paragraph_gap"]
CLEAR = _S["space.clear"]
CLEAR_NARROW = _S["space.clear_narrow"]
NARROW_COLS = _S["space.narrow_cols"]
INK_FLOOR = _S["space.ink_floor"]
# The px offset for the size of a character group, added to the page size.
GROUP_PX = _S["font.group_px"]
PILCROW_INK = _S["mark.pilcrow_ink"]
COUNT_INK = tuple(_S.get("mark.count_ink") or PILCROW_INK)  # the blank line count
# The count and the mark of a blank line run, in the order the render step
# writes them.
BLANK_FORMAT = _S["mark.blank_format"]
CURVE_THRESHOLD = _S["curve.threshold"]
CURVE_RING = _S["curve.ring"]
CURVE_RING_WEIGHT = _S["curve.ring_weight"]
CURVE_GAMMA = _S["curve.gamma"]


# The suffixes that a Read packs as banded code. pointer.py reads this one
# set. The choice of the banded path is then in one place. Python's own
# tokenize module classifies Python. Each other suffix here goes through
# plain_class_map below. A suffix outside this set keeps the plain pack.
CODE_SUFFIXES = frozenset(_S["code.suffixes"]) | frozenset(
    _S["band.text_suffixes"] if _S["band.text_files"] else ())


# The color table and the token classifier.

# Comment ink and string ink. They use different hues. The model can then tell
# a comment from a string on a tint set that holds a green. The two inks are
# dark enough to read at small sizes.
MUTED = _S["code.ink.comment"]
# No page shows the gutter. The key stays because a saved style.json that names
# it must still load.
GUTTER = _S["code.ink.gutter"]
BROWN = _S["code.ink.string"]

INK_FOR = {name: _S["code.ink." + name] for name in
           ("comment", "string", "keyword", "number", "name", "op",
            "tag")}

# Reserved character inks. A model misreads these two characters on shape
# alone. Each one gets a color that no syntax class and no other reserved
# character uses. The ink applies wherever the character appears in code.
#   backtick - a model reads ` as a double quote whatever its shape. Orange is
#   the plugin's own free ink. The nearest ink is lime at 225. The nearest
#   band is at 409.
#   underscore - a model reads _ as a space. Plum is the one color from the
#   grid search that clears 210 against all six anchor inks (black, blue,
#   green at 210, magenta 215, orange 275, lime 270) and each band (nearest
#   504).
RESERVED = dict(_S["code.ink.reserved"])

# The ink scheme. "simple" writes each letter in the name ink, each digit in
# the number ink and all else in the op ink. The model can hold these three
# inks as one rule. The look-alike, reserved, class and per-character inks
# above stay off. "lookalike" is the other scheme.
SCHEME = str(_S.get("ink.scheme") or "simple")


# A model mixes up a few marks even in a good face. These marks keep their own
# ink under the simple scheme. The dot family . , : ; gets four inks of its own
# and the quote family " ` ' gets three. The render step never writes . and :
# in the same ink.
SIMPLE_PUNCT = {k: tuple(v) for k, v in (_S.get("ink.simple_punct") or {}).items()}
# The inks that a run of underscores uses in turn, red then blue.
UNDER_RUN_INKS = [tuple(v) for v in (_S.get("ink.underscore_run") or [(150, 0, 0), (0, 30, 160)])]


# The render step writes the second quote of a kind on a line as its closing
# character.
QUOTE_CLOSERS = {'"': "”", "'": "’"}


# The share of a bracket's hang below the baseline that the render step removes.
# 1.0 puts its ink on the baseline. 0.0 leaves it where Inter puts it, on the
# mathematical axis. See baseline_lift().
BASELINE_LIFT = float(_S.get("mark.baseline_lift", 0.0) or 0.0)

# One size for one mark, when the size of the whole set does not suit it. The
# pipe is the main case. It is the tallest mark on the page and looks a size
# larger than all around it.
MARK_PX_BY_CHAR = {k: float(v) for k, v
                   in (_S.get("font.mark_px_by_char") or {}).items()}

# ROWS ONE CHARACTER MOVES DOWN, negative to raise it. A closing double quote
# sits lower in its em than the opening one. The two then do not align on a
# row. No font setting fixes that. The glyph sits where its designer put it,
# and the page moves it.
DY_BY_CHAR = {k: int(v) for k, v
              in (_S.get("font.dy_by_char") or {}).items()}

# The horizontal scale of one character. It overrides each group below it. A
# single mark can then leave the column of its group without a new group for
# it.
SCALE_X_BY_CHAR = {k: float(v) for k, v
                   in (_S.get("font.scale_x_by_char") or {}).items()}

# The marks that render at the PAGE's size and condense to their own share of
# it. They sit between the letters, which condense most, and the marks that
# keep their full width at a size of their own. scale_for checks this set
# FIRST. face_for then does not also give a mark named here font.mark_px.
SCALED_MARKS = tuple(_S.get("font.scaled_marks") or ())
SCALED_MARK_SCALE = float(_S.get("font.scaled_mark_scale_x", 0) or 0)

# The width a DIGIT condenses to, as a share of its own. Zero means a
# digit keeps its full width. It is separate from font.scale_x because a
# digit must stay legible against each other digit. The whole rebuild
# contract depends on the line number.
DIGIT_SCALE_X = float(_S.get('font.digit_scale_x', 0) or 0)

# The marks that condense WITH the letters and do not keep their own width.
# These are the opening quotes only. The render step writes the second quote
# of a kind on a line as its closing form through QUOTE_CLOSERS. The closing
# forms are not in this set. An opener then follows the letters and a closer
# keeps its width.
CONDENSED_MARKS = tuple(_S.get('font.condensed_marks') or ('"', "'"))

# THE SIZE THE FULL WIDTH MARKS RENDER AT. Zero means the page's own size. It
# sets the marks apart from the letters. The render step asks for the letters
# at a larger size and condenses them back to the column width. It asks for
# these marks at their own size and does not condense them.
MARK_PX = float(_S.get("font.mark_px", 0) or 0)

# The marks that render EXACTLY as they are, not condensed and not taller.
# They keep their width and do not take the extra height of the larger size.
#
# HOW. font.scale_x does not apply to them. face_for offsets their size back
# to space.row_px. A mark on a 13 px page at scale 0.769 then becomes a 10 px
# mark. A letter beside it is 13 px condensed to the same column width. The
# letters gain height and the marks do not.
#
# THE DOT MARKS ARE NOT IN THIS SET. The period, comma, semicolon and colon
# render a size LARGER, and font.bigger_chars holds them.
FULL_WIDTH = tuple(_S.get("font.full_width_chars")
                   or ("(", ")", "[", "]", "{", "}", "|", "\\", "/",
                       "%", "<", ">", "+", "=", "*", "&", "^", "$", "#",
                       "@", "!", "?", "~", "-"))


def scale_for(ch):
    """The horizontal scale one character renders at.

    font.scale_x raises the x-height. It asks FreeType for a larger size and
    condenses the width back to the target. A glyph then gains rows and keeps
    its columns. FreeType takes the width and the height separately and hints
    the glyph at that aspect. The stems then fit the grid at their final
    width, and nothing scales them afterward.

    The checks run in this order.

    A scale named for one character in font.scale_x_by_char overrides each
    group.

    font.scaled_marks render at the page's own size and condense to
    font.scaled_mark_scale_x. That scale sits between the letters and the
    marks that keep their width. This check runs before the other groups.
    face_for then does not also give a mark named there font.mark_px.

    font.condensed_marks, the opening quotes, condense with the letters. The
    render step writes the second quote of a kind on a line as its closing
    form through QUOTE_CLOSERS. The closing forms are not in the set. An
    opener then follows the letters and a closer keeps its own width.

    A digit takes font.digit_scale_x. It condenses less than a letter does,
    because a digit must stay legible against each other digit. The whole
    rebuild contract depends on the line number. Zero means the digits keep
    their full width.

    Each other mark keeps its full width, and font.mark_px sets its size. A
    quote left uncondensed at the page's larger size renders narrower and
    denser than the letters beside it. On Inter SemiBold, hinting mode 2,
    snapped:

        10 px plain                 the quote is 5 columns, 40.0 percent solid
        12 px condensed to 0.833    5 columns, 40.0 percent solid, 1 row taller
        12 px NOT condensed         4 columns, 50.0 percent solid

    A letter takes font.scale_x, because a letter has spare width.
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


HASH_INK = (60, 60, 60)


def simple_ink(ch):
    """The ink of a character under the simple scheme. It is one of three
    inks, or its own ink for a mark in ink.simple_punct."""
    if ch in SIMPLE_PUNCT:
        return SIMPLE_PUNCT[ch]
    # The hash renders in dark gray, not the red of the other marks. A model
    # reads a red # beside a red space box as part of the box. A model reads a
    # blue # as a digit and a black # as a letter.
    if ch == "#":
        return HASH_INK
    if ch.isalpha():
        return INK_FOR["name"]
    if ch.isdigit():
        return INK_FOR["number"]
    return INK_FOR["op"]


def drawn(ch):
    """The glyph that the render step writes for a source character. It is
    the character itself, or the glyph that an override names, such as the
    curly double quote for the straight one. The tab mark and the underscore
    mark are private-use code points. They render as the arrow and the double
    dagger."""
    if ch == TAB_MARK:
        return "→"
    if ch == UND_MARK:
        return "‡"
    # The render step never writes the line-end and indent marks. Their glyph
    # widths are part of each row measure. They keep those glyphs here, and
    # the layout does not move.
    if ch == NL_MARK:
        return "¶"
    if ch == INDENT_MARK:
        return "§"
    return char_over(ch, "glyph") or ch


_TOKCLASS = {tokenize.COMMENT: "comment", tokenize.STRING: "string",
             tokenize.NUMBER: "number", tokenize.OP: "op"}
for _n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
    _t = getattr(tokenize, _n, None)
    if _t is not None:
        _TOKCLASS[_t] = "string"


def _tokens(raw):
    """tokenize's tokens, or all it read before it stopped.

    A block taken from a report is a fragment, not a whole module. tokenize
    raises an error on a fragment, such as an unclosed bracket, a first line
    that is already indented, or a stray quote. The tokens that tokenize read
    get their colors. The rest keeps the default class and still renders.
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


# The classifier for each code suffix that is not python. tokenize reads
# python and nothing else. This classifier reads a .gd, .js or .ps1 file by
# shape. A comment runs from # or // to the end of the line. A string sits
# between quotes. Digits are numbers, words are names, and each other
# character is punctuation. The regex tries the alternatives in order. A #
# inside quotes then stays part of the string, and a quote inside a comment
# stays part of the comment. The bands hold the line structure. The colors
# only need to be steady.
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


# The marks in the flow.
NL_MARK = dp.NL_MARK
BLANK_MARK = _S["mark.blank"]   # the bullet, a run of blank lines
# The section sign. No page shows it, because the bands and the indent count
# hold the indent. The name stays for the callers that read it.
COUNT_MARK = _S["mark.count"]
# The band as a shape. pad grows or shrinks it past the text, and offset moves
# it, in pixels. All zero in the shipped renderer.
BAND_PAD_X = int(_S.get("band.pad_x", 0) or 0)
BAND_PAD_Y = int(_S.get("band.pad_y", 0) or 0)
BAND_OFF_X = int(_S.get("band.offset_x", 0) or 0)
BAND_OFF_Y = int(_S.get("band.offset_y", 0) or 0)
BAND_INSET = int(_S.get("band.text_inset", 0) or 0)
# The rows of band kept clear above the tallest ink of a row and below the
# lowest. No glyph then sits on the edge of its band. It grows the ROW, not
# the band. A larger band alone reaches into the row gap and merges
# neighbors.
BAND_TEXT_CLEAR = int(_S.get("band.text_clear", 1) or 0)
# The render step centers the band on the real ink of the row. band.offset_y
# then needs no measure by eye at each glyph size. See _pack_code.
CENTRE_TEXT = bool(_S.get("band.centre_text", True))
# Each pair gets the same distance from ink to ink. Without it, space.clear is
# only a floor. See char_widths().
EXACT_INK_GAP = bool(_S.get("space.ink_gap_exact", True))
BAND_GROW = tuple(int(_S.get("band.grow_" + s, 0) or 0) for s in "lrtb")

# Objects placed by hand, as "line:N", "band:N" and "word:N:K". Empty in the
# shipped renderer. See layout.placements in style.py.
PLACEMENTS = {k: dict(v) for k, v in (_S.get("layout.placements") or {}).items()
              if isinstance(v, dict)}


def _placed(key, field):
    """One placement field, or 0 when no placement moves the object."""
    entry = PLACEMENTS.get(key)
    if not entry:
        return 0
    try:
        return int(entry.get(field, 0) or 0)
    except (TypeError, ValueError):
        return 0


def word_indices(pairs, ids):
    """The word number of each character inside its own source line, or -1
    for a character that is not part of a word. "word:N:K" then names one
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
# A dot, then a letter and up to five more letters or digits, with no word
# character after them.
EXT_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,5}(?![A-Za-z0-9_])")
TAB_MARK = _S["mark.tab"]       # the right arrow, leading tabs
UND_MARK = _S["mark.underscore"]  # the double dagger, an underscore run

# The underscore run mark stays in the reserved set that build_flow rejects in
# a source. A run of underscores renders as the underscores themselves, in
# alternating inks. No page shows this mark.

# The runs inside the leading whitespace of one line, in source order.
# build_flow counts the columns of a tab-indented line with expandtabs(4). The
# indent count is then the column count.
_LEAD_RUN = re.compile(r" +|\t+")

# The two inks.
INDENT_INK = _S["code.ink.indent"]
BLANK_INK = _S["code.ink.blank"]
# Runs of spaces inside a line and at its end render as red boxed counts. See
# build_flow(). DENSEPACK_SPACE_RUNS=0 stops them for a comparison.
SPACE_RUNS = os.environ.get("DENSEPACK_SPACE_RUNS", "1") != "0"
# The render step writes the indent count in this ink and then makes its box
# solid. The result is a white number in a black box, and the model never
# reads it as the red space count. The ink is near black and not black. No
# text character then has this ink.
INDENT_INK = (1, 1, 1)
# The tab count of a line indented with tabs. It is a number beside the green
# line number, in its box, in an ink of its own, as the space count has red.
# A black count merges with the green line number, and a model then writes
# the line one tab short. Vivid blue, not red, because red means spaces. The
# code digit blue is (0, 0, 165).
TAB_INK = (0, 0, 235)
# The second tab of a two-tab line renders red. The model then never reads
# "\t\t" as one tab. Not BLANK_INK, because BLANK_INK is the space count.
TAB2_INK = (231, 0, 0)
# THE BLANK LINE SQUARE. build_flow() writes no square. The blank line count
# "1\n" takes its place (see THE ESCAPE LETTERS below). The layout, the row
# rules and the render loop still handle a square in a flow. Without a mark,
# the only sign of a blank line is a jump in the line numbers, such as 210 to
# 212, and a model can then move the blank line to the wrong place. The
# square is one more character in the flow. It takes its width and its letter
# clearance on the two sides. A row can start with it, and no row ends
# between it and the line number after it. Inter has no block glyph (U+2588
# renders the placeholder box). The render loop fills a rectangle as tall as
# the band and half as wide. The pair is (GAP_MARK, GAP_INK), and a square in
# the source is not one.
GAP_MARK = "■"
# The line number's own green. The square belongs to the numbering, and blue
# already means tabs. Each check that reads COUNT_INK as a line number also
# asks for a digit. No check then takes the square for a digit.
GAP_INK = COUNT_INK
# The width of the square in final image pixels and in layout pixels.
# _pack_code() sets it when it knows the row height and the canvas ratio.
_GAP_W = 7
_GAP_W_LAYOUT = 7.0
# The row offset of the band that _pack_code() last measured, for the square
# in the key.
_KEY_BAND_OFF_Y = 0


def _is_gap(p):
    """True for the blank line square."""
    return p[0] == GAP_MARK and p[1] == GAP_INK


# THE ESCAPE LETTERS. The tab count ends with the two characters \t, and the
# blank line count ends with \n, the way code spells a tab and a line break.
# A model can read a bare blue tab count as a nesting level and write a line
# one tab off. "2\t" reads as 2 tabs. The whole "2\t" is the count, and it
# sits inside the box. The blank line count replaces the square. It is "1\n"
# in the line number green, in a box of its own before the box of the line
# number. Only a count renders these letters in these inks. No source
# character has TAB_INK or COUNT_INK.
TAB_ESC = ("\\", "t")
GAP_ESC = ("\\", "n")


def _one_box_ink(a, b):
    """True when two count marks share one box with no seam. That is the same
    ink, or the blue and red tabs of "\\t\\t", which flow as one mark."""
    return a == b or {a, b} == {TAB_INK, TAB2_INK}


def _is_esc(p):
    """True for the \\t after a tab count or the \\n after a blank line count."""
    return ((p[1] in (TAB_INK, TAB2_INK) and p[0] in TAB_ESC)
            or (p[1] == COUNT_INK and p[0] in GAP_ESC))


def _box_ends(pairs, k):
    """True when the box of the blank line count closes after pairs[k]. Its n
    is the last letter, and the line number after it opens a box of its own."""
    return (pairs[k][0] == GAP_ESC[1] and pairs[k][1] == COUNT_INK
            and k + 1 < len(pairs) and _is_count(pairs[k + 1]))


def _drop_blank_counts(pairs):
    """The flow without the blank line counts and the \\t after the tab
    counts, for the old width search. That search picks the glyph scale, and
    the escape letters must not move it."""
    out = []
    k = 0
    n = len(pairs)
    while k < n:
        if pairs[k][1] in (TAB_INK, TAB2_INK) and pairs[k][0] in TAB_ESC:
            k += 1
            continue
        q = k
        while q < n and pairs[q][1] == COUNT_INK and pairs[q][0].isdigit():
            q += 1
        if (q > k and q + 1 < n and pairs[q][1] == COUNT_INK
                and pairs[q][0] == GAP_ESC[0] and pairs[q + 1][0] == GAP_ESC[1]):
            k = q + 2
            continue
        out.append(pairs[k])
        k += 1
    return out


def _gap_span():
    """The square's inked columns in layout pixels, from its own pen."""
    return (0, max(1, int(round(_GAP_W_LAYOUT))) - 1)

# The edge mark for a source line that continues on the next row.
WRAP_INK = _S["code.ink.wrap"]
# Page pixels of paper between the stroke of the wrap mark and the INK of the
# last character on that row. The note at the wx placement in the render loop
# explains why the advance sum is the wrong base for this measure. It also
# gives the sweep that set this number.
WRAP_INK_CLEAR = float(_S.get("mark.wrap_ink_clear", 3) or 0)


# How many times wrap_edge() moved a mark onto the text in this pack. It is a
# list, and a nested pack can then reset it and read it back.
CLAMP_HITS = [0]

# True while _fit_width() packs a widening trial. _fit_width() compares a
# trial on its page sizes and its clamp count and never reads a pixel of it.
# The trial then skips the glyph paste. The bands and the wrap marks still
# render, because the clamp count comes from the wrap mark. A trial that wins
# renders again with its glyphs.
_NO_GLYPHS = False

# The character measure of the last file, one entry. See _pack_code().
_CW_CACHE = {}
# The flow of the last file, one entry. See _pack_code().
_FLOW_CACHE = {}
# What build_flow() returned for the last file, before the old search drops
# its blank line counts, one entry. See _pack_code().
_BUILT_FLOW = {}
# A glyph's bounding box per face and character, for the mark box runs.
_BBOX_CACHE = {}


def wrap_edge(d, wx, y0, y1):
    """The wrap edge as one wavy line as tall as the row. It is a sine curve
    in WRAP_INK that swings WRAP_W left and right of wx, three waves a row.
    No character has this shape, and it does not merge with a | in the text.
    A straight bar reads as a pipe, and a zigzag reads as square."""
    import math
    # The wave swings WRAP_W on each side of wx. It stays inside the page,
    # because a row that runs to the edge clips the right half of the wave.
    canvas = getattr(d, "c", None)
    if canvas is not None and getattr(canvas, "ratio", None):
        limit = (canvas.width - 1) / canvas.ratio - WRAP_W * 1.5 - 2  # the swing plus half the stroke
        if wx > limit:
            # The mark does not fit. wrap_edge renders it at the limit, on top
            # of the text that is already there. CLAMP_HITS counts that.
            # _fit_width() reads the count and rejects a layout that clamps.
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
    # A letter stem holds at one pixel because it is a straight vertical run.
    # This mark is a sine wave, traced on a mask at four times size and
    # shrunk. At one pixel, the average of each diagonal step becomes a
    # fragment, and the wave breaks into dots.
    #
    # The mark renders heavier than the text beside it, and that is the
    # trade. The mark must stay one continuous shape after the shrink, because
    # the model uses it to tell a wrapped row from a new source line.
    d.line(pts, fill=WRAP_INK, width=max(int(WRAP_W), 1))


def ink_span(font, ch, seen):
    """First and last column this character inks, with its own origin at 0.

    The rendered width must clear the ink, not the font's advance. A glyph can
    ink a column past its advance, and it then shares a pixel column with the
    letter after it.

    This function reads the mask in mode="L" for each character. The
    monochrome mask, mode="1", stops short of the mask value 64 where the step
    curve starts to ink. With it, the layout clears fewer columns than the
    page fills, and a glyph lands against the last column of its neighbor.
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
    """One (char, ink, big) triple per rendered character, the whole file in
    order.

    big is True only for a character that LIFT names and LIFT_PX renders
    larger.

    python=False picks plain_class_map, for a source that tokenize cannot read.
    """
    if not raw.endswith("\n"):
        raise ValueError("the flow stores each newline as a mark. "
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
            # A run of blank lines renders no rows. The line after the run
            # holds the count of blank lines, in a box of its own, and the
            # green count then does not merge with the green line number.
            run = j - i
            i = j
            if i < len(lines):
                # The line after the blank run starts with its blank line
                # count, "1\n", in a box of its own before the line number.
                for _n in "%d" % run:
                    pairs.append((_n, COUNT_INK, False))
                for _e in GAP_ESC:
                    pairs.append((_e, COUNT_INK, False))
            continue
        # The number of this line, in the break ink. The model can then name
        # any line on any page. It starts the line, and two digit groups then
        # never touch.
        for _n in str(i + 1):
            pairs.append((_n, COUNT_INK, False))
        lead = line[:len(line) - len(line.lstrip(" \t"))]
        # The band behind this line shows its depth. An indented line also
        # shows its exact column count, and the model copies the exact
        # indent.
        cols_here = len(lead.expandtabs(4))
        ext_cols = set()
        if EXT_BLACK:
            for m in EXT_RE.finditer(line):
                ext_cols.update(range(m.start(), m.end()))
        # In a file indented with tabs only, a tab-indented line gets no red
        # column count. It gets the blue tab count below. A red 4, 8 or 12
        # reads as spaces.
        tabs_only = _TAB_KEY and not _SPACE_INDENT_KEY and set(lead) == {"\t"}
        if INDENT_MARK and tabs_only:
            # The band color alone is not enough. With a correct band, a model
            # can still write a line one tab short. The tab count renders in
            # blue, TAB_INK.
            # The render step writes one or two tabs out, as "\t" and "\t\t",
            # with the second \t in red. It counts three and more, as "3\t".
            # Without the count, a model can write a 3-tab line as 2 tabs.
            if len(lead) >= 3:
                for d in "%d" % len(lead):
                    pairs.append((d, TAB_INK, False))
            for _t in range(1 if len(lead) >= 3 else len(lead)):
                for _e in TAB_ESC:
                    pairs.append((_e, TAB2_INK if _t == 1 else TAB_INK, False))
        # THE LAST LINE OF A FILE WITH NO NEWLINE AT ITS END shows its count,
        # 0 included. It starts its own row at the left edge (see
        # _last_line_start()), but the lines before it are indented. With no
        # count, a model can give this line the indent of the lines before
        # it. A red "0" says that the line has no indent, in the same form
        # that each indented line uses.
        # ONLY AFTER AN INDENTED LINE. When the line before has no indent, a
        # model has no indent to copy, and the red "0" is the one count on
        # the page. The model then reads each other line as indented. Bash
        # output has no final newline. On a /tmp listing from Bash, a model
        # wrote a space before each line.
        _last_open = (_NO_FINAL_NL and i == len(lines) - 1
                      and next((l for l in reversed(lines[:i]) if l.strip()), "")[:1] in (" ", "\t"))
        if INDENT_MARK and (cols_here or _last_open) and not tabs_only:
            # The count renders on EACH indented line. Depth times a step is
            # not enough. The same code at 4 spaces and at 2 packs to the same
            # bytes, and a model can only guess the step. A red count beside
            # the green line number means indent.
            # A file indented with tabs only counts its tabs, as 1, 2, 3. The
            # model then does not divide 4, 8, 12 columns back to tabs, a step
            # where a model can write 2 tabs as 1. A file with mixed tab and
            # space indents keeps columns.
            count = cols_here
            for d in "%d" % count:
                pairs.append((d, BLANK_INK, False))
        spans = [] if (legend is None and not (LIFT_INK or LIFT_PX)) else [
            m.span() for m in LIFT.finditer(line, len(lead))]
        k = len(lead)
        quotes = {q: 0 for q in QUOTE_CLOSERS}
        while k < len(line):
            ch = line[k]
            # The second double quote of a line is the closing one. It renders
            # as its own character, the closing curly quote, with its own ink.
            # The first renders as the opening one. The model then finds the
            # end of a string without counting quote pairs. A run of the same
            # quote, the three of a docstring, is one quote. All three open or
            # all three close.
            if ch in QUOTE_CLOSERS:
                if k == 0 or line[k - 1] != ch:
                    quotes[ch] += 1
                if quotes[ch] % 2 == 0:
                    ch = QUOTE_CLOSERS[ch]
            # A token class gives each character inside one token the same
            # ink. A hex id such as 139811a4 then renders in one color, and a
            # model can misread its digits. densepack.CHAR_INK holds one ink
            # per look-alike character. densepack._colour_map() builds it from
            # CONFUSABLE, and densepack.classify() uses the same map for
            # prose. This code takes it first for each character in the map.
            # No two characters that look alike then share a color anywhere
            # on the page, not only inside a lifted token. A character outside
            # the map has no look-alike in the list. It keeps its class ink,
            # which holds the code structure.
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
                    # The token stays in the image, with a mark on it.
                    for p in range(start, stop):
                        # The character ink overrides the lift ink here for
                        # the same reason. A lifted number is the run that
                        # the model must copy digit by digit.
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
            # TAB RUNS. A tab inside a line gets the same marks as a tab in
            # the indent. One tab is \t, two tabs are \t\t with the second in
            # red, and three or more are N\t. keep_leading_tabs() keeps these
            # tabs for this step. When a tab becomes spaces, the page shows a
            # space count, and a model writes spaces in place of the tab.
            if ch == "\t":
                run = 1
                while k + run < len(line) and line[k + run] == "\t":
                    run += 1
                k += run
                if run >= 3:
                    for d in "%d" % run:
                        pairs.append((d, TAB_INK, False))
                for _t in range(1 if run >= 3 else run):
                    for _e in TAB_ESC:
                        pairs.append((_e, TAB2_INK if _t == 1 else TAB_INK, False))
                continue
            # SPACE RUNS. In the condensed face, a run of spaces is only a
            # wider gap, and a model that rebuilds a file guesses its length.
            # A model can drop runs inside a line and spaces at its end. A run
            # of two or more inside the line, or any spaces at its end,
            # renders as its count in the red box ink of the indent count. The
            # one "N = spaces" entry in the key then covers all three places.
            # After the green line number, it is the indent. Inside a line, it
            # is a run. At the end, it is trailing spaces.
            if ch == " " and SPACE_RUNS:
                run = 1
                while k + run < len(line) and line[k + run] == " ":
                    run += 1
                if run >= 2 or k + run == len(line):
                    k += run
                    for d in "%d" % run:
                        pairs.append((d, BLANK_INK, False))
                    continue
            if ch == "_":
                run = 1
                while k + run < len(line) and line[k + run] == "_":
                    run += 1
                if run > 1:
                    k += run
                    # A run of underscores renders as the underscores
                    # themselves, the first red, the next blue, then red
                    # again, with the same-letter clear column between them.
                    # Two bars that otherwise merge into one then differ by
                    # ink and by a gap.
                    for n in range(run):
                        pairs.append(("_", UNDER_RUN_INKS[n % len(UNDER_RUN_INKS)], False))
                    continue
            pairs.append((ch, ink, ch in BIGGER))
            k += 1
        pairs.append((NL_MARK, PILCROW_INK, False))
        i += 1
    return pairs


def flow_depths(raw):
    """One nesting depth per rendered source line, in render order.

    The band behind a line is this number. build_flow renders each line that
    is not empty and ends each one with a pilcrow. This list then matches one
    for one the line ids that char_widths returns. The indent step comes from
    the file and is not a fixed guess. One level is then one real nesting
    level whatever language the file uses.
    """
    cols = [len(l[:len(l) - len(l.lstrip(" \t"))].expandtabs(4))
            for l in raw.split("\n")[:-1] if l != ""]
    unit = min([c for c in cols if c > 0] or [4])
    return [c // unit for c in cols]


# Numbers a model can misread. A run of two or more digits, a comma-grouped
# number, and any token of only 0 1 7 8 9 and l can leave the image as the
# numbered marker of the plain pack, with their text in the legend sidecar.
LIFT = re.compile(r"(?<![0-9A-Za-z_])"
                  r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{2,}|[01789l]{2,})"
                  r"(?![0-9A-Za-z_])")

# The same tokens, kept in the image and not lifted out of it. A caller that
# passes legend=None renders each digit run as itself. These two settings set
# how such a token renders. The model then reads it right without a legend
# row. The two are off in the shipped build.
#
#   LIFT_INK  the ink for each character of the token, or None to keep the
#             syntax class ink. INK_FOR["tag"], lime, is the one ink that the
#             search in densepack.INK measured at 210 from all eight code
#             inks. With the markers off, nothing else on the page uses it.
#   LIFT_PX   px added to the page size for that token, or 0 for the page
#             size. The bigger glyph sits on the row's own baseline and grows
#             upward. IDENT_PX in densepack.py uses the same method for an
#             identifier. No row moves and no page grows taller. It costs
#             width.
#
# A larger glyph reaches into the row above, and the model can read it as
# part of that row. The size does not ship. The color is set, but no page
# shows it. build_flow asks densepack.CHAR_INK first, and that map holds each
# character that LIFT can match.
LIFT_INK = _S["code.ink.lift"]
LIFT_PX = _S["code.lift_px"]

# The marks that a model cannot tell apart on a packed page, such as the
# backtick and the dot marks. They render BIGGER_PX larger than the type
# around them.
#
# The method is the same as for a lifted token in this file and for an
# identifier in densepack.py. A second face is BIGGER_PX larger. It renders on
# the row's own baseline through the big flag, which build_flow already sets
# as the third item of each pair. The bigger face has the taller ascent. The
# glyph then starts big_dy rows higher and grows upward into the clear rows
# above the type. No row moves and no page grows taller.
#
# The mark keeps the cell of the body face. char_widths takes its pen step
# and its clear columns from the body face. The larger glyph then grows into
# the white that the small one already holds and pushes no neighbor. The
# layout with the marks on is the layout with them off. pack_code scales
# BIGGER_PX and LIFT_PX by the supersample with each other pixel count.
#
# Nothing else is larger. A larger digit reaches into the line above, and the
# model can read it as part of that line. The named set is punctuation marks
# only. No digit and no letter takes the bigger face.
BIGGER = tuple(_S["font.bigger_chars"])
BIGGER_PX = _S["font.bigger_px"]
# The marks that step by their ink, not by the advance of their face. See
# char_widths(). It has its own name, and a test that empties BIGGER then
# keeps the same cells.
INK_STEP = tuple(_S.get("font.ink_step_chars") or ())

# THE BRACKETS SIT ON THE BASELINE.
#
# Inter centers a bracket on the math axis, and the bracket hangs below the
# baseline that the letters share. At 12 px, ( and ) ink 2 rows below the
# baseline and [ ] { } ink 3. A bracket that hangs reads as a descender. A
# shape below the baseline means a descender and nothing else.
#
# font.bigger_px is not the cause. face_for() returns ascent - face ascent as
# the dy, and the render site adds it. Each face on a row then sits on one
# baseline. With the bigger face off, the same bracket inks the same 2 or 3
# rows below it.
#
# The lift then comes from the glyph, not from a table. The glyph moves up by
# the depth that the mask hangs below the baseline. That holds at any size
# and needs no number that the font file must match.
ON_BASELINE = ("(", ")", "[", "]", "{", "}")


def baseline_lift(ch, mask, top):
    """The rows a bracket moves up, as a share of its depth below the baseline.

    top is the mask's own top, counted from the baseline and negative above
    it. top + mask.height is then the depth of the glyph below the baseline.
    Each other character, a real descender included, gets nothing.

    mark.baseline_lift is the share. A full 1.0 puts the brackets too HIGH,
    above the line. Inter centers a bracket on the mathematical axis by
    design, and part of that hang belongs there.
    """
    if ch not in ON_BASELINE or mask is None or not BASELINE_LIFT:
        return 0
    return int(round(max(0, top + mask.height) * BASELINE_LIFT))


def tag_for(value, legend, seen, form):
    """The marker for one value, the same marker for the same text."""
    tag = seen.get(value)
    if tag is None:
        tag = form % (len(legend) + 1)
        seen[value] = tag
        legend.append((tag, value))
    return tag


# One band color per nesting depth. band.tints in style.py holds eight tints,
# and style.py gives the reason for each tint and for their order. A depth
# past the last tint takes the tints again from the first.
#
# band.strength mixes each tint toward the page background. 1.0 uses the tint
# as written. style.py ships 0.5, and each tint there sits at twice its
# distance from white for that reason.
#
# band.top_level False renders a line at depth 0 as plain text on the page
# background and starts the first tint at the first indented level. A band
# and a red indent count then always appear together. True puts depth 0 on
# the first tint, and style.py ships True.
BAND_TOP_LEVEL = bool(_S.get("band.top_level", False))


def band_index(depth):
    """The tint index for a nesting depth, or None for no band."""
    if BAND_TOP_LEVEL:
        return depth % len(TINTS)
    if depth <= 0:
        return None
    return (depth - 1) % len(TINTS)


TINTS = [tuple(int(round(b + (c - b) * _S["band.strength"]))
               for c, b in zip(tint, _S["page.background"]))
         for tint in _S["band.tints"]]

# See the spacing map above GAP.
PAD = _S["page.pad"]
CAP_H = _S["page.height"]
SHEET_GAP = _S["page.sheet_gap"]  # white space between two pages


def keep_leading_tabs(text):
    """Return the text unchanged, with each tab kept.

    A tab in the indent stays until build_flow, which counts it and writes a
    tab count or a column count for it. A tab inside a line also stays until
    build_flow, which writes the tab marks for it. A tab inside a line then
    never shows as a space count.
    """
    return text


def scheme_for(pairs):
    """The scheme rows for this flow, card.scheme_rows in style.py, which
    name the marks. No page shows them. _pack_code() only subtracts their
    count from the rows of each page.

    This function adds the underscore row only when the flow holds the
    underscore mark. A file without one keeps the four rows.
    """
    rows = list(_S["card.scheme_rows"])
    rows[1] = rows[1] % NL_MARK
    if any(p[0] == UND_MARK for p in pairs):
        rows.insert(2, _S["card.scheme_underscore"] % UND_MARK)
    return rows


# The spacing of the key row. White columns between the outline of a swatch
# and its digit, and between one swatch and the next.
SWATCH_PAD = 2
SWATCH_GAP = 3


# The name that pack_code() puts at the head of the key row, set per pack.
# The three legend functions read it, and no signature changes.
_LEGEND_TITLE = ""
# True when a line of the file starts with a tab, set per pack.
_TAB_KEY = False
# True when a line holds a tab after its indent, set per pack. The key then
# names the tab marks, the same as for a file with tab indents.
_INNER_TAB_KEY = False
# True when a line starts with a space, and when a line holds a run of two
# or more spaces or ends in a space, set per pack.
_SPACE_INDENT_KEY = False
_RUN_KEY = False
# "lines=a-b  chars=N" for the image that holds the key, or empty.
_KEY_STATS = ""
# True when the packed text has no newline after its last line, set per pack.
_NO_FINAL_NL = False
# True for a file indented with spaces. No depth bands, no swatches.
_NO_BANDS = False
# True for a file indented with spaces in the UNIFORM pack. Each line sits on
# one band color, the depth 0 color. The band separates the lines, and the
# red count gives the indent. The width search runs with no bands.
_ONE_BAND = False
ONE_BAND_TINT = 0
# True when the file holds a blank line. The key then says that a missing
# line number is a blank line.
_BLANK_KEY = False


def legend_parts():
    """The key row on page one, as (text, ink, band) pieces.

    band is a tint index or None. Each piece renders in the ink and on the
    band that the page itself uses for that thing. The row is then a sample
    of the page and not a description of it.
    """
    parts = []
    # A SLIM KEY for a small command output. bash_image.py sets it through the
    # environment, and the render helpers then read it too. It drops the depth
    # swatches, and the key stays short. The full key costs two rows, 54
    # tokens at the 756 pixel page width. On a few lines of output, that is
    # most of the image. It keeps the file name. The name of a command output
    # is its text copy, bash-output-<id>.txt, and the model Greps that file
    # for an exact string.
    slim = os.environ.get("DENSEPACK_SLIM_KEY") == "1"
    # The name of the source file leads the row. No page and no text Read
    # result names its file. A model with two pages that share a constant
    # name can answer with the value from the wrong file.
    if _LEGEND_TITLE:
        parts.append((_LEGEND_TITLE + "  ", (0, 0, 0), None))
    # One swatch per depth that the page can show, labeled with the depth.
    # With no band at depth 0, the row starts with a plain 0 and the tints
    # run from depth 1.
    if slim or _NO_BANDS or _ONE_BAND:
        pass
    elif BAND_TOP_LEVEL:
        parts += [("%d" % d, (0, 0, 0), d) for d in range(len(TINTS))]
    else:
        parts.append(("0 ", (0, 0, 0), None))
        parts += [("%d" % (d + 1), (0, 0, 0), d) for d in range(len(TINTS))]
    # The label of the depth swatches, when the key shows them.
    if not slim and not _NO_BANDS and not _ONE_BAND:
        parts.append(("=nesting depth  ", MUTED, None))
    parts.append(("N", COUNT_INK, "box"))
    # A blank line renders nothing, only a skipped line number. Without a key
    # entry, a model can drop a blank line. The word "missing" goes on the
    # label before it, and the boxes stay one set.
    # The UNIFORM pack names the blank line count in their place, rendered as
    # the page renders it, "N\n" in a box in the line number green. Without a
    # name, a model cannot tell whether the count means blank lines or
    # something else. The old width search renders no count, and its key
    # keeps the words.
    if _BLANK_KEY and UNIFORM:
        parts.append(("=line number  ", MUTED, None))
        parts.append(("N" + "".join(GAP_ESC), COUNT_INK, "box"))
        parts.append(("=blank lines before  ", MUTED, None))
    elif _BLANK_KEY:
        parts.append(("=line number  missing ", MUTED, None))
        parts.append(("N", COUNT_INK, "box"))
        parts.append(("=blank line  ", MUTED, None))
    else:
        parts.append(("=line number  ", MUTED, None))
    # The slim key names a mark only when the output uses it. It names the
    # indent count when a line starts with spaces, and the pipe when a |
    # appears. bash_image.py checks the output and sets DENSEPACK_KEY_INDENT
    # and DENSEPACK_KEY_PIPE.
    # One entry for each red count. An indent count and a run inside a line
    # are each a count of spaces.
    if (((os.environ.get("DENSEPACK_KEY_SPACES") == "1"
          or os.environ.get("DENSEPACK_KEY_INDENT") == "1") if slim
         else (_RUN_KEY or _SPACE_INDENT_KEY))):
        parts.append(("N", BLANK_INK, "box"))
        parts.append(("=spaces  ", MUTED, None))
    # A file indented with tabs only names its tab counts as tabs. A model
    # reads a column count as spaces and can write a tab-indented file with
    # spaces. With "1 tab", the model writes nearly all lines right.
    if ((_TAB_KEY and not _SPACE_INDENT_KEY) or _INNER_TAB_KEY) and not slim:
        parts.append(("".join(TAB_ESC), TAB_INK, "box"))
        parts.append(("=1 tab  ", MUTED, None))
        parts.append(("".join(TAB_ESC) * 2, TAB_INK, "box"))  # second \t red, below
        parts.append(("=2 tabs  ", MUTED, None))
        parts.append(("N" + "".join(TAB_ESC), TAB_INK, "box"))
        parts.append(("=N tabs  ", MUTED, None))
    # The three inks named. A digit in the digit ink, a letter in the letter
    # ink, a pipe in the mark ink.
    # The digit named is the 1, against the lowercase l beside it. It renders
    # in the digit ink, which is blue.
    # The slim key names 1 against l only when a 1 appears.
    if not slim or os.environ.get("DENSEPACK_KEY_ONE") == "1":
        parts.append(("1", INK_FOR["number"], None))
        # A tab-indented file keeps the long labels, because a model rebuilds
        # a tab-indented file right with them.
        parts.append(("=the number one  " if _TAB_KEY else "=one  ", MUTED, None))
        parts.append(("l", INK_FOR["name"], None))
        parts.append(("=lowercase L  ", MUTED, None))  # l against 1
    if not slim or os.environ.get("DENSEPACK_KEY_PIPE") == "1":
        parts.append(("|", INK_FOR["op"], None))
        parts.append(("=the pipe character  " if _TAB_KEY else "=pipe  ", MUTED, None))
    parts.append(("", WRAP_INK, "wrap"))  # the wrap mark itself, rendered by _legend_line
    parts.append(("=same line  ", MUTED, None))
    return parts


def _first_line_number(pairs, chunk):
    """The first line number in the rows of a page, or None."""
    for a, b in chunk:
        j = a
        while j < b:
            if pairs[j][1] == COUNT_INK and _is_count(pairs[j]) and pairs[j][0].isdigit():
                digits = ""
                while j < len(pairs) and pairs[j][1] == COUNT_INK and pairs[j][0].isdigit():
                    digits += pairs[j][0]
                    j += 1
                if j < len(pairs) and _is_esc(pairs[j]):
                    # a blank line count, "1\n", not the line number
                    j += len(GAP_ESC)
                    continue
                return int(digits)
            j += 1
    return None


def _set_key_stats(text, pairs, pages, pitch=0.0):
    """Row two of the key names the lines on the first page and their
    characters. The model then checks its copy against the two."""
    global _KEY_STATS, _LEGEND_TITLE
    base = _LEGEND_TITLE
    _KEY_STATS = ""
    if not base or not pages or os.environ.get("DENSEPACK_SLIM_KEY") == "1":
        return
    lines = text.split("\n")
    total = len(lines) - (1 if text.endswith("\n") else 0)
    first = _first_line_number(pairs, pages[0]) or 1
    # The gate stacks pages into one image while the stack stays under the
    # longest side that the API keeps. The first image can then hold several
    # pages. Its lines run to the first page it does not hold. The height of
    # each page is its rows times the row pitch in image pixels, plus two
    # rows for the key on page one.
    held = 1
    if pitch and len(pages) > 1:
        h = (len(pages[0]) + 2) * pitch
        while held < len(pages) and h + len(pages[held]) * pitch <= dp.EDGE:
            h += len(pages[held]) * pitch
            held += 1
    nxt = _first_line_number(pairs, pages[held]) if len(pages) > held else None
    last = (nxt - 1) if nxt else total
    start = sum(len(l) + 1 for l in lines[:first - 1])
    end = min(len(text), sum(len(l) + 1 for l in lines[:last]))
    # An image that holds the whole file names no lines and characters. Its
    # own line numbers run from 1 to the last, and the key stays one row
    # where it fits. A tab-indented file keeps the stats.
    # THE END OF THE FILE. The page renders each line ending the same way. A
    # file whose last line has no newline then looks like one that has it,
    # and a model can add a newline. The key says so at the right end of row
    # two, in the words that git uses for it.
    tail = "" if text.endswith("\n") or not text else "no newline at end of file"
    if first == 1 and last == total and not _TAB_KEY:
        _KEY_STATS = tail
        return
    _KEY_STATS = "lines=%d-%d  chars=%d" % (first, last, end - start) + ("  " + tail if tail else "")


def legend_width(font):
    """The pixels that legend_row() needs. A trimmed page then stays wide
    enough."""
    w = 0.0
    for text, _ink, band in legend_parts():
        w += font.getlength(text)
        if band == "gap":
            w += _GAP_W_LAYOUT + SWATCH_GAP
        elif band is not None:
            w += 2 * SWATCH_PAD + SWATCH_GAP
    return w


def legend_rows(font, max_w, face_for=None, renderer="pillow"):
    """The parts of the key row, split into rows no wider than max_w. A mark
    and the "=..." label after it stay on one row. A mark then never ends
    one row with its label at the start of the next."""
    parts = legend_parts()
    if not _S.get("page.key_row", True):
        # No key row at all. head_h is a count of these rows times the pitch.
        # With an empty list, page one starts from its first band.
        return []
    groups = []
    for part in parts:
        follows_mark = groups and groups[-1][-1][0] in (NL_MARK, INDENT_MARK) and part[2] is None
        if groups and ((part[0].startswith(("=", " ")) and part[2] is None) or follows_mark):
            groups[-1].append(part)
        else:
            groups.append([part])
    # The count boxes, line number, spaces and indent, read as one set. They
    # stay together on one row of the key.
    merged = []
    for g in groups:
        if merged and g[0][2] == "box" and merged[-1][0][2] == "box":
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    groups = merged
    # the depth swatches and their label are one entry
    ends = [i for i, g in enumerate(groups) if any(p[0].startswith(("=nesting", "=tabs")) for p in g)]
    if ends:
        first = 1 if groups[0][0][0].startswith("file=") else 0
        groups = (groups[:first] + [[p for g in groups[first:ends[0] + 1] for p in g]]
                  + groups[ends[0] + 1:])
    widths = [sum((WRAP_W * 4 + SWATCH_GAP) if p[2] == "wrap" else
                  (_GAP_W_LAYOUT + SWATCH_GAP) if p[2] == "gap" else
                  _part_width(font, p[0], face_for, renderer)
                  + (2 * SWATCH_PAD + SWATCH_GAP if p[2] is not None else 0) for p in group)
              for group in groups]
    # The file name sits at the right end of the first row. The entries take
    # any order that fits two rows. In the order of legend_parts(), the four
    # boxes cannot share a row with anything else, and the key takes three
    # rows.
    title = [g for g in groups if g[0][0].startswith("file=")]
    if title:
        tw = widths[groups.index(title[0])]
        keep = [(g, w) for g, w in zip(groups, widths) if g is not title[0]]
        groups, widths = [g for g, _ in keep], [w for _, w in keep]
    else:
        tw = 0.0
    # The lines and characters of the image sit at the right end of row two,
    # under the file name.
    stats = [(_KEY_STATS, MUTED, None)] if _KEY_STATS else []
    sw = _part_width(font, _KEY_STATS, face_for, renderer) if stats else 0.0
    if not stats and sum(widths) + tw <= max_w:
        return [[p for group in groups for p in group] + (title[0] if title else [])]
    best, best_w = None, None
    n = len(groups)
    # The "=same line" entry sits on row one.
    same = [i for i, g in enumerate(groups) if any(p[0].startswith("=same line") for p in g)]
    for mask in range(1 << n):
        if n and not mask & 1:
            # The first entry, the depth of nesting, starts the first row.
            continue
        if any(not mask >> i & 1 for i in same):
            continue
        one = [i for i in range(n) if mask >> i & 1]
        two = [i for i in range(n) if not mask >> i & 1]
        w1 = sum(widths[i] for i in one) + tw
        w2 = sum(widths[i] for i in two) + sw
        # The key is two rows at most. A page with enough content to need
        # each entry is a wide page. A narrow page holds little and names few
        # entries. This loop keeps the split with the narrower wide row.
        if best_w is None or max(w1, w2) < best_w:
            best, best_w = (one, two), max(w1, w2)
    rows = [[p for i in best[0] for p in groups[i]] + (title[0] if title else []),
            [p for i in best[1] for p in groups[i]] + stats]
    return [r for r in rows if r]


def legend_row(d, font, x, y, line_h, max_w=None, face_for=None, renderer="pillow", img=None, row_up=0):
    """Render the key row, on as many rows as the width needs, and return
    the height it took. With face_for and img, the characters of the row
    render from the same picks, faces and pen steps as the body. An = in the
    key row is then the = of the code. row_up is the rows that the body
    baseline sits below the row top for the tallest pick."""
    rows = legend_rows(font, max_w, face_for, renderer) if max_w else [legend_parts()]
    top = y
    for parts in rows:
        if max_w and parts and parts[-1][0].startswith(("file=", "lines=", "no newline")):
            # The file name, or the lines and characters of the image, at the
            # right end of its row.
            name = (parts[-1][0].rstrip(),) + tuple(parts[-1][1:])
            _legend_line(d, font, x, y, line_h, parts[:-1], face_for, renderer, img, row_up)
            nx = x + max_w - _part_width(font, name[0], face_for, renderer)
            _legend_line(d, font, nx, y, line_h, [name], face_for, renderer, img, row_up)
        else:
            _legend_line(d, font, x, y, line_h, parts, face_for, renderer, img, row_up)
        y += line_h + ROW_GAP
    return y - top


def _legend_count(font, max_w, face_for=None, renderer="pillow"):
    """len(legend_rows(...)). A plan asks once for each trial of the width
    search, with the same font, parts and spacing. This function then keeps
    the answer per value of all that legend_rows() and char_widths() read. A
    pack measures it."""
    if not _PLAN_ONLY:
        return len(legend_rows(font, max_w, face_for, renderer))
    g = globals()
    key = (_LEGEND_TITLE, _KEY_STATS, tuple((p[0], p[2]) for p in legend_parts()), getattr(font, "path", None), getattr(font, "size", None),
           getattr(font, "scale_x", None), getattr(font, "sim_bold", None), float(max_w),
           renderer, face_for is None, bool(_S.get("page.key_row", True)),
           tuple(g.get(n) for n in ("WRAP_W", "SWATCH_GAP", "SWATCH_PAD", "LETTER_SPACE",
                                     "CLEAR", "CLEAR_NARROW", "MARK_CLEAR", "COUNT_CLEAR",
                                     "BOX_CLEAR", "BOX_GAP", "SEAM_GAP", "QUOTE_RUN_CLEAR",
                                     "SAME_CLEAR", "STEM_QUOTE_CLEAR", "STEP_RIGHT",
                                     "BIGGER_PX", "LIFT_PX", "FONT_MAX_PX", "PAGE_W")),
           repr(sorted(CHAR_OVER.items())))
    hit = _LEGEND_COUNT.get(key)
    if hit is None:
        if len(_LEGEND_COUNT) > 64:
            _LEGEND_COUNT.clear()
        hit = _LEGEND_COUNT[key] = len(legend_rows(font, max_w, face_for, renderer))
    return hit


def _part_width(font, text, face_for=None, renderer="pillow"):
    """The pixels that one key row part takes. That is the length in the body
    face, or the body's own pen steps for its characters when the picks
    apply."""
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
            # Each character of the part renders the way the body renders it,
            # with the face of its pick, its size, its pen step and its clear
            # column.
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
        if band == "gap":
            # The blank line square, as tall as the band of the page and on
            # whole page pixels, the way the render loop fills it.
            gy0 = y - BAND_PAD_Y + _KEY_BAND_OFF_Y - BAND_GROW[2]
            gy1 = y + line_h - 1 - BAND_GAP_Y + BAND_PAD_Y + _KEY_BAND_OFF_Y + BAND_GROW[3]
            if isinstance(img, Shrunk):
                _r = img.ratio
                _c = _round_px(cx * _r)
                gx0, gx1 = _c / _r, (_c + _GAP_W - 1) / _r
            else:
                gx0, gx1 = cx, cx + _gap_span()[1]
            d.rectangle([gx0, gy0, gx1, gy1], fill=ink)
            cx += _GAP_W_LAYOUT + SWATCH_GAP
            continue
        if band == "box":
            # The outline that the page renders around a mark, with the page's
            # own background inside. The key row then shows the mark as it
            # appears on the page.
            # MARK_BOX_INK at the page's own box width, not band.outline.
            # band.outline is 0 wide on this page and renders nothing.
            bw = int(round(1 / img.ratio)) if isinstance(img, Shrunk) else 1
            room = [cx, y + bw, cx + w + 2 * SWATCH_PAD,
                    y + line_h - 2 * bw - BAND_GAP_Y]
            sx = cx + SWATCH_PAD
            two_tabs = ink == TAB_INK and text == "".join(TAB_ESC) * 2
            for i_ch, ch in enumerate(text):
                # The "\t\t" in the key renders its second \t red, as the page
                # does.
                ink_ch = TAB2_INK if two_tabs and i_ch >= len(TAB_ESC) else ink
                if face_for is not None and img is not None:
                    f, dy = face_for(ch, False)
                    for ox, oy in _over_offsets(ch):
                        if renderer == "freetype":
                            backend_text(img, (sx + ox, y + dy + oy), ch, f, ink_ch)
                        else:
                            d.text((sx + ox, y + dy + oy), drawn(ch), font=f, fill=ink_ch)
                else:
                    d.text((sx, y), drawn(ch), font=font, fill=ink_ch)
                sx += _part_width(font, ch, face_for, renderer)
            # This code fits the outline to the mark's own pixels after the
            # mark renders, the way it fits the page's own mark boxes. The key
            # row then shows the same one page pixel of white on all four
            # sides.
            # _ink_bounds() skips the first row of its window, and the top row
            # of the digits sits on it. The window then reaches 2 rows past
            # the room.
            found = (_ink_bounds(img, (room[0], room[1] - 2, room[2], room[3] + 2))
                     if img is not None else None)
            if found is None:
                d.rectangle(room, outline=MARK_BOX_INK, width=bw)
            else:
                ImageDraw.Draw(img.im if isinstance(img, Shrunk) else img).rectangle(
                    [found[0] - 2, found[1] - 2, found[2] + 2, found[3] + 2],
                    outline=MARK_BOX_INK, width=1)
                if ink == INDENT_INK:
                    _invert_box(img.im if isinstance(img, Shrunk) else img,
                                (found[0] - 1, found[1] - 1, found[2] + 2, found[3] + 2))
            cx += w + 2 * SWATCH_PAD + SWATCH_GAP
            continue
        if band == "wrap":
            # Inset from the band by the same rows as the body's mark. The key
            # row then shows the mark at the size that the page renders it.
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
                # The swatch digit is the page's own digit, from its pick.
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
            # A one-character part renders from its own override font and
            # size, the way the body renders that character, and twice if
            # thick.
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


# The ink curve. Anti-aliasing stays on. This code maps the glyph mask that
# FreeType blends through a curve before it composites the ink color. A pixel
# above the threshold then takes the full ink, and only a thin ring stays
# part-blended. With anti-aliasing off, small strokes break into stubs and
# the underscore vanishes. Each candidate but "soft" also snaps the pen to a
# whole pixel, because ImageDraw.text carries the fraction of a float x into
# FreeType and blends the stem across two columns. "step" leaves far more ink
# pixels at the full color than "soft".
INK_CURVE = _S["curve.name"]
# Small pages take their own curve. A page at or under curve.small_px renders
# soft, because the step threshold breaks thin strokes into stubs at that
# size. See curve.small_px in style.py.
SMALL_PX = int(_S.get("curve.small_px", 8) or 0)
SMALL_CURVE = str(_S.get("curve.small_name", "soft") or "soft")
SMALL_THRESHOLD = int(_S.get("curve.small_threshold", 96) or 96)


def curve_for(px):
    """The ink curve name for a page of this pixel size."""
    return SMALL_CURVE if px <= SMALL_PX else INK_CURVE


# The edge setting. See curve.blur in style.py.
#
# No hardness multiplier acts on coverage. The renderer uses only MacType's
# two curves, RenderWeight and Contrast, in freetype_glyph.ink_curve(), and
# MacType has no such control.
BLUR = str(_S.get("curve.blur", "auto") or "auto")
_BLUR_OF = {"hard": "none", "step": "ring", "soft": "full"}


def blur_for(curve):
    """The edge rule for this page. That is the blur setting, or the rule
    that the curve name implies."""
    return BLUR if BLUR != "auto" else _BLUR_OF.get(curve, "auto")


def threshold_for(px):
    """The step threshold for a page of this pixel size."""
    return SMALL_THRESHOLD if px <= SMALL_PX else CURVE_THRESHOLD

_BIG = {}


def _lut(name, threshold=None, blur="auto"):
    """The 256 entry map from mask value to ink weight, or None for no map.
    threshold is the step or hard cut for this page. None takes the global
    curve.threshold. blur, when not auto, replaces the edge rule that the
    name implies with none, ring or full.
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
            # Hard color. Each pixel with any ink past the ring floor renders
            # at the full ink color. No pixel is then lighter than the ink,
            # and no stroke breaks.
            table = [0 if v < CURVE_RING else 255 for v in range(256)]
        elif name == "gamma":
            table = [min(255, round(255 * (v / 255.0) ** CURVE_GAMMA))
                     for v in range(256)]
        else:
            # The sharpening curve for the three-times render. It is a
            # contrast stretch. A downsampled pixel over two thirds takes the
            # full ink, and only the band between a third and two thirds
            # blends.
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
    """One token rendered as a mask through the ink curve, on a whole pixel.
    curve names the curve for this page, and threshold names its cut. None
    takes the global ones. blur is the edge setting of style.py.

    This is the Pillow path. It renders nothing on a shipped page, because
    style.glyphrenderer is freetype and each render site tests for it. It
    stays for the path without FreeType."""
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


# pack_code sets these while it renders a supersampled page. They hold the
# width the page shrinks to, or the factor it shrinks by. save_page() then
# shrinks the finished page in memory and writes only the small one. Writing
# the large page as a PNG, then opening and converting it again, costs a
# large share of a pack.
SHRINK_TO = None
SHRINK_BY = None
# The band after a line number box starts this many page pixels past the last
# digit ink. The right line of the box sits 2 page pixels out. The difference
# is the white. A measure set the value, not a derivation. bw rounds 15.815 layout
# columns up to 16.
#
# A sweep in Inter over 201 line number boxes on one page set this value. The
# page size stayed the same at each value, and a larger clearance costs
# nothing.
#   3     176 of 201 boxes touched a band
#   3.25  130 of 201
#   3.5    88 of 201
#   4      28 of 201
#   4.5     0 of 201
#   5       0 of 201
# 4.5 is the first value where no band touches a box line, and it is the
# value.
#
# Run this sweep again after any change to the font, to the shrink, to
# _ink_bounds, or to the box fit of 2 page pixels.
BAND_AFTER_BOX_PX = 4.5
# The direct canvas renders the page at its final size. False keeps the
# whole-page shrink, for a comparison.
DIRECT_CANVAS = True


class _PlanPage(object):
    """A page with a size and no pixels, for the glyphless trials of a plan.
    It gives the sizes that the layout reads and nothing else."""

    def __init__(self, width, height, small):
        self.width = int(width)
        self.height = int(height)
        self.size = (self.width, self.height)
        self.info = {"densepack_small": True} if small else {}
        self.mode = "RGB"
        self.im = self


class _NullDraw(object):
    """An ImageDraw stand-in that renders nothing, for a _PlanPage. wrap_edge()
    reads the canvas through .c, and this class keeps it. Each render call
    is a no-op."""

    def __init__(self, canvas):
        self.c = canvas

    def __getattr__(self, name):
        return lambda *a, **k: None


# TRIM TO INK. The layout adds one row pitch of slack under the last line for
# the rounding of the shrink. Without a trim, a page can pay for a whole patch
# row of white. Blank rows can be 3 percent of the tokens, and the white can
# make the width search pick the width that costs more. This step cuts a page
# to its last ink row plus this margin, rounded up to whole patches. Nothing
# rendered moves.
TRIM_MARGIN = 4
# The rows that trim_to_ink() reads at a time, from the foot of the page up.
TRIM_BLOCK = 64


def trim_to_ink(im):
    """im cut to the smallest whole-patch height that holds its last ink row
    and TRIM_MARGIN. Returns im unchanged when it already has that height."""
    w, h = im.size
    try:
        rgb = im if im.mode == "RGB" else im.convert("RGB")
        bg = _np.array(BACKGROUND, dtype=_np.int16)[:3]
        # The last ink row is near the foot of a page. The test reads blocks
        # of rows from the foot up and stops at the first block with ink. The
        # rest of the page never leaves Pillow.
        last = 0
        foot = h
        while foot > 0:
            head = max(0, foot - TRIM_BLOCK)
            arr = _np.asarray(rgb.crop((0, head, w, foot))).astype(_np.int16)
            far = _np.abs(arr - bg) > dp.NEAR_BLANK
            ink = _np.nonzero(far.any(axis=(1, 2)))[0]
            if len(ink):
                last = head + int(ink[-1])
                break
            foot = head
    except Exception:  # noqa: BLE001
        last = dp.last_ink_row(im)
    keep = -(-(last + 1 + TRIM_MARGIN) // dp.PATCH) * dp.PATCH
    if keep >= h:
        return im
    return im.crop((0, 0, w, keep))


def save_page(im, path):
    """Save one page with its width and height on the 28 pixel patch grid.

    The API resamples an image with a size off the grid. That resampling
    blurs each glyph after the ink curve sharpened it. The padding is the
    page background and moves no glyph. It costs no extra patch, because the
    patch count already rounds up. It cannot cross the API cap, because the
    cap is 1568 pixels, which is 56 whole patches.
    """
    # A plan's page has a size and no pixels. It gets the size that the
    # padding below gives, and the same trial bookkeeping. A plan never reads
    # the pixels of a trial, and this code makes none. Only a page already at
    # its final size (a Shrunk page, or a sheet of them) is ever a _PlanPage.
    if isinstance(im, _PlanPage):
        w = -(-im.width // dp.PATCH) * dp.PATCH
        # A plan page has no ink to measure. Its price does not include the
        # slack row that the layout added. That is the height that trim_to_ink()
        # leaves on a rendered page.
        h = -(-(im.height - getattr(im, "slack", 0) + TRIM_MARGIN) // dp.PATCH) * dp.PATCH
        h = min(h, -(-im.height // dp.PATCH) * dp.PATCH)
        if _TRIAL:
            _TRIAL_PAGES[str(path)] = im
            if _NO_GLYPHS:
                _GLYPHLESS.add(str(path))
            else:
                _GLYPHLESS.discard(str(path))
        return w, h
    # A Shrunk page arrives at its final size and skips the shrink. The flag
    # guards the shrink as well as the padding. This code then does not
    # shrink a second time a plain page that rendered at a supersample.
    if (SHRINK_TO or (SHRINK_BY and SHRINK_BY > 1)) and not im.info.get("densepack_small"):
        # This code pads the big page to the patch grid first. The shrink
        # then gives the same pixels as a page written at full size and
        # shrunk.
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
    im = trim_to_ink(im)
    if _TRIAL:
        # A search trial keeps its finished page in memory and encodes
        # nothing. PNG encoding and quantizing of pages that the search then
        # drops is the largest part of a pack. _write_trial() encodes the
        # pages of the winner once.
        _TRIAL_PAGES[str(path)] = im
        if _NO_GLYPHS:
            _GLYPHLESS.add(str(path))
        else:
            _GLYPHLESS.discard(str(path))
        return im.width, im.height
    if _PNG_JOBS is not None:
        _PNG_JOBS.append((im, path))
    else:
        dp.save_png(im, path)
    return im.width, im.height


# THE PAGES OF ONE PACK ENCODE ON THREADS. dp.save_png() spends nearly all of
# its time in zlib, and Pillow lets other threads run while zlib works. The
# sheet loop of _pack_code() collects its pages in this list, and
# _save_pngs() encodes them together before _pack_code() returns. dp.save_png()
# reads the image alone, and each page then gets the bytes that a save on its
# own gives. None outside that loop, and save_page() then encodes at once.
_PNG_JOBS = None


def _save_pngs(jobs):
    """dp.save_png() for each (image, path) in jobs, one thread per page. It
    raises the error of the first page that failed, after each page is done."""
    if len(jobs) < 2:
        for im, path in jobs:
            dp.save_png(im, path)
        return
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(len(jobs), os.cpu_count() or 1)) as pool:
        list(pool.map(lambda job: dp.save_png(*job), jobs))


# The trial pages of the search, path to image, while the search branch of
# pack_code runs. Two trials at most sit here at a time. _forget() drops a
# loser right after the comparison.
_TRIAL = False
_TRIAL_PAGES = {}
# The trial pages rendered without glyphs, by path.
_GLYPHLESS = set()
# The layout width that the last _fit_width() chose, read by
# _fit_page_width().
_LAST_LAYOUT_W = 0


def _forget(res):
    """Drop a losing trial's pages from memory."""
    if res:
        for f, _w, _h in res[0]:
            _TRIAL_PAGES.pop(str(f), None)


def _write_trial(res, out_stem):
    """Encode the winner's pages onto the final names, <out_stem>-N.png.

    dp.save_png is a function of the image alone. The bytes are then the
    same as the bytes of a pack that wrote each page at once. Returns the
    result with the final paths in place of the trial paths."""
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


# The packed line that each written image starts on, by image path, counted
# from 0. That is the number of line ends before the first row of the image.
# _pack_code() fills it, and _write_trial() moves it to the final name.
# pointer.draw_drop_file() makes a source line number from it. A Read that
# starts at line N then gets the image that holds line N.
PAGE_FIRST_LINE = {}


# The glyphless trials that the width search packed ahead in child processes,
# by (page width, layout width), each a (result, clamp hits) pair.
# _prefetch_trials() fills it. _fill_bottom() and _fit_width() read and empty
# it.
_PREFETCH = {}

# The memory that all trial helpers of one conversion can hold together, in
# MB. Each helper holds a full layout of the text, and a large file then gets
# fewer helpers. DENSEPACK_HELPER_MEMORY_MB changes the budget.
HELPER_MEMORY_MB = int(_os.environ.get("DENSEPACK_HELPER_MEMORY_MB", "4000"))


def _prefetch_trials(text, px, python, reader, title, out_stem, jobs):
    """Pack each glyphless trial that the search asks for, at once, in as
    many child processes as the machine has cores. Each child takes a share
    of the jobs in turn. jobs is [(page width, layout width)]. Fills
    _PREFETCH. On any failure, or with DENSEPACK_SERIAL_DRAW set, it leaves
    _PREFETCH empty, and the search packs each trial itself. A child imports
    this module, takes the parent's settings whole, and returns each trial's
    page sizes, clamp count and the two numbers that pack_code returns
    beside the pages. No image crosses a pipe. The parent writes one job file
    per child, the child removes it after it reads it, and no child writes
    an image file.

    Each job goes through a file, not through the stdin of a child. A
    Windows pipe holds about 4 KB. A larger job written to stdin blocks the
    parent until that child imports this module and reads the job, and the
    children then run one after another. Process creation and the repeated
    import cost most of the time of a one-job child, and a child therefore
    takes several jobs."""
    import json
    import os
    import pickle
    import subprocess
    import tempfile
    _PREFETCH.clear()
    # Text of 10 KB or less converts in this process. 12 helpers cost it
    # about 430 MB and gain no time.
    # A plan renders no pixels. Its trials then cost less than the start of a
    # helper and its copy of the layout. In a measure, the plan ran twice as
    # fast with no helpers, and it uses none of their memory.
    if (_PLAN_ONLY or os.environ.get("DENSEPACK_SERIAL_DRAW") or not jobs
            or len(text.encode("utf-8")) <= 10_000):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    # One helper holds about 60 MB plus 0.9 MB for each KB of text. A 1 MB
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
            # "-c" puts the working folder on sys.path. The working folder of
            # the hook is the project. The child then runs from this scripts
            # folder, where a project cannot add a module.
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
                for (f, _w, _h), first in zip(pages, rec.get("firsts") or []):
                    if isinstance(first, int):
                        PAGE_FIRST_LINE[f] = first
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
    """The child of _prefetch_trials(). It packs its share of glyphless
    trials from the pickled job at job_path, removes that file, and returns
    the results as one JSON list on stdout."""
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
        # "firsts" returns the start line of each page. This child fills
        # PAGE_FIRST_LINE in its own memory, and a plan reads it in the parent.
        out.append({"page_w": page_w, "lw": lw, "hits": CLAMP_HITS[0],
                    "pages": [(w, h) for _f, w, h in res[0]],
                    "firsts": [PAGE_FIRST_LINE.get(str(f)) for f, _w, _h in res[0]],
                    "target": res[1], "line_h": res[2]})
        _TRIAL_PAGES.clear()
    sys.stdout.write(json.dumps(out))


# The underscore renders through backend_text() like each other character.
# Inter's underscore is a solid bar at each size that the page uses. A filled
# rectangle in its place spans its whole cell with none of the side bearing
# of a glyph, and it then touches the bracket beside it.


# THE SPACING MAP. This block names each constant that puts white on a page,
# with what it moves. The constants sit in three places, this block, the head
# of the file and page.pad near the page size. They are all in layout
# columns.
#
# The value of a layout column. The layout is larger than the page, and the
# page shrinks from it. A constant of 1 is then a fraction of a page pixel,
# not a page pixel. There are two shrinks, and they differ.
#
#   the narrow page, page.supersample 3 and no page.code_width. The layout
#   is three times the page, and 3 layout columns are 1 page pixel.
#   the wide page, page.code_layout_width laid out at
#   page.code_supersample and shrunk to page.code_width. 1 page pixel is
#   1 / Shrunk.ratio layout columns.
#
# On the page that the model sees, MARK_CLEAR at 3 is then 2.276 page pixels
# and BAND_GAP_X at 1 is 0.759. A value that must land on a whole page pixel
# uses bw. The render loop sets bw to round(1 / img.ratio), one page pixel in
# layout columns for the current page. The mark box and the band edges beside
# it use bw.
#
# The page has one gap size, the white between two bands, and it measures 1
# page pixel. Each other gap matches against it.
#
#   PAD             page.pad, the white margin around the whole page
#   GAP             space.block_gap, after each line end, to separate blocks
#   BAND_GAP_X      white columns kept between two bands in a row
#   BAND_GAP_Y      white rows kept under each band
#   ROW_GAP         space.row_gap, added to the line height for the row pitch
#   BAND_PAD_X/Y    the band grown past its text, left and right, top and foot
#   BAND_OFF_X/Y    the band moved without moving its glyphs
#   BAND_INSET      band.text_inset, the glyphs moved in from the band's edge
#   EDGE_INSET      the band started left of the first glyph, out of GAP
#   LETTER_SPACE    space.letter, added to each pen step
#   CLEAR           space.clear, white columns between two glyphs
#   CLEAR_NARROW    the same for a pair where either glyph is narrow
#   NARROW_COLS     how few inked columns count as narrow
#   SAME_CLEAR      the same for two of one letter
#   QUOTE_RUN_CLEAR the same for two quote marks of one kind
#   STEM_QUOTE_CLEAR the same for an l against a quote
#   STEP_RIGHT      the white a mark keeps on its right
#   MARK_CLEAR      white around a mark that sits outside the bands
#   COUNT_CLEAR     white a count leaves before the word after it
#   BOX_CLEAR       white between a mark box and the band after it
#   BOX_GAP         mark.box_gap, the room the line break leaves before the
#                   next line number's box
#   SEAM_GAP        mark.seam_gap, white, the seam rule and white between a
#                   line number and an indent count
#   SWATCH_PAD/GAP  the key row's own padding and the gap between its parts
#
# The mark box itself takes no constant. The render step fits its left and
# right to the pixels of its digits, two page pixels out on each side. One
# page pixel of white then stays inside it whatever the shrink rounds to. Its
# top and bottom come from the band while mark.box_fits_band is on. See
# _ink_bounds().

# The block gap after each line end, to separate blocks.
GAP = _S["space.block_gap"]
# The band starts EDGE_INSET columns to the left of the first glyph, inside
# the gap that already sits between two blocks. The outline and the wrap edge
# then never cover the first column of a letter. The glyphs and the row
# widths do not move. No row then wraps differently, and no page grows.
# White between bands. gap_x columns stay white between two blocks in a row,
# and the inset never takes them. gap_y rows stay white under each band,
# taken from the row's own spare pixel.
BAND_GAP_X = int(_S.get("band.gap_x", 1) or 0)
BAND_GAP_Y = int(_S.get("band.gap_y", 1) or 0)
ROW_GAP = int(_S.get("space.row_gap", 0) or 0)
# The line end mark outside its band, in the white between two blocks.
PILCROW_OUTSIDE = bool(_S.get("mark.pilcrow_outside", True))
FILL = float(_S.get("page.fill", 0) or 0)
MARK_CLEAR = int(_S.get("mark.clear", 0) or 0)

# WRAP_GUTTER is the width that a row keeps free on its right. The wrap mark
# renders in that width. The render site puts the mark past the last
# character of the row. wrap_edge() then holds the mark inside the page. A
# gutter that is too small makes wrap_edge() move the mark left, onto the
# text.
#
# WRAP_SLACK is the last part of the gutter. A measure sets it, not a
# calculation. Read the two rules below before you change it.
#
# RULE 1. Do not scale this constant with the page. pack_code() multiplies
# each spacing constant by the supersample. With WRAP_GUTTER in that list,
# the gutter grows to 15 page pixels. The clamp then fires more often, not
# less, and pages grow. _fit_width() widens the layout for a narrower row,
# and it spends the width that the gutter saves.
#
# RULE 2. Do not add the ink that a glyph puts past its own advance. That ink
# is 1 page pixel in Inter over each printable ASCII character. With it
# added, the measure is worse. More rows end within 2 page pixels of the edge.
#
# With no gutter, the clamp fires many times on a long file and moves a mark
# up to about 15 page pixels onto the text. With a 15 column gutter and the
# inset counted, it fires far less, and the worst move is under 3 page pixels.
WRAP_SLACK = 0
WRAP_GUTTER = (MARK_CLEAR + BAND_PAD_X + BAND_INSET + WRAP_W * 1.5 + 2
               + WRAP_SLACK)
# The clear columns after a count digit, before the word that follows it.
COUNT_CLEAR = int(_S.get("mark.count_clear", MARK_CLEAR) or MARK_CLEAR)
# The extra white on each side of a space box inside a line. Its outline then
# never sits against the band or the letter beside it.
SPACE_BOX_CLEAR = 3
# With no bands, the white at a line end before the next line number, and
# after a line number or indent count before the text. Each is less than a
# space, and only a real space then looks like one.
NOBAND_LINE_GAP = 3
NOBAND_COUNT_CLEAR = 2
# The columns from the ink of a count digit to its box outline and past it.
BOX_ROOM = 3

# UNIFORM WHITE. Each gap on the page is a fixed count of white columns IN
# THE FINAL IMAGE, from the last inked column of one thing to the first
# inked column of the next. The render step measures each glyph as the page
# renders it. The glyphs, their sizes and the width search do not change.
#   W_CHAR   between two characters with no space between them
#   W_SPACE  a real space, the only gap this wide
#   W_BOX    between a box outline and the character beside it
#   W_BAND   between the edge of a band and the first or last character on it
# A box outline with its own line sits 2 columns past the ink of its digits.
# BOX_SIDE columns on each side of the digits then belong to the box.
# Off while the width search runs (see _fit_page_width), in this process
# and in the trial children, which read it from the environment.
UNIFORM = os.environ.get("DENSEPACK_UNIFORM", "1") == "1"
W_CHAR = int(os.environ.get("DENSEPACK_W_CHAR", "2"))
W_SPACE = 7
W_BOX = 3
W_BAND = 5
# The white between the band of the line before and a line number box, in
# image pixels. W_BOX_AFTER is the white between the box and the band of its
# own line. With the same white on the two sides, a box sits halfway between
# two bands, and a model can give a line the band color of its neighbor.
W_BOX_BEFORE = 2
# Each row starts this many image pixels in from the left edge. A row that
# continues a line at 3 px from the edge loses the start of its band, and a
# model can miss its first word.
ROW_LEFT = 8
W_BOX_AFTER = 3
BOX_SIDE = 3
# The ratio from layout pixels to final image pixels for the current pack.
# _pack_code() sets it before it measures the steps.
_UNI_R = 1.0
_PSPAN = {}
# _page_span() by (face, character, ratio). Each pack makes its own faces,
# and _pack_code() empties this memo when it starts. The faces of the packs
# before it then do not stay in memory.
_PSPAN_FACE = {}
# The fixed scale of the UNIFORM final pack from layout to image pixels, the
# scale that the old width search gave, and the image width it packs to. None
# outside that pack. See _fit_page_width().
_FIXED_R = None
_IMG_W = None
# The mask value, out of 255, from which a column counts as ink when this code
# measures a gap. A faint edge column counts, and the white between glyphs is
# then clean.
UNI_FLOOR = int(os.environ.get("DENSEPACK_UNI_FLOOR", "20"))
# The image widths that the UNIFORM final pack tries at the fixed scale. The
# cheapest width wins, and a tie keeps the narrower one. 896 is there for the
# blank line square. The square can push a file over its token ceiling at
# each width up to 840. In one file, 784x840 costs 842 tokens and 896x728
# costs 834. 952 is there for LINE_TEXT_MIN. Moving a line start off the end
# of a row can cost a row at each width up to 896. In one file, 784x1400
# costs 1402 tokens and 952x1120 costs 1362.
UNI_WIDTHS = tuple(int(v) for v in os.environ.get("DENSEPACK_UNI_WIDTHS", "700,728,756,784,812,840,896,952").split(","))


def _round_px(v):
    """v rounded half up to a whole pixel."""
    return int(math.floor(v + 0.5))


def _page_span(font, ch):
    """First and last inked column of ch in the final image, from the column
    where backend_text() pastes it, at the size it renders it, or None."""
    if ch in (" ", NL_MARK):
        return None
    if ch == GAP_MARK:
        # The blank line square, a filled rectangle from its own pen.
        return (0, _GAP_W - 1)
    r = _UNI_R
    # The key below reads the face's file, size and two attributes, the
    # character, the ratio and settings that stay the same in a process.
    # face_for() sets the two attributes once, when it makes the face. The
    # face object, the character and the ratio then fix the key. A pack asks
    # for the same few pairs many times, and this memo answers them before
    # this code builds the key.
    fast = (font, ch, r)
    span = _PSPAN_FACE.get(fast, _PSPAN_FACE)
    if span is not _PSPAN_FACE:
        return span
    size = max(1.0, font.size * r) if (GLYPH_AT_FINAL_SIZE and r < 1.0) else font.size
    bold = getattr(font, "sim_bold", False)
    sx = getattr(font, "scale_x", 1.0)
    wt = char_over(ch, "weight", 1.0) or 1.0
    key = (font.path, round(size, 4), bold, sx, wt, ch, UNI_FLOOR)
    if key in _PSPAN:
        _PSPAN_FACE[fast] = _PSPAN[key]
        return _PSPAN[key]
    mask, left, _top = glyph_backend().glyph(drawn(ch), font.path, size, bold, sx, wt, 0.0)
    span = None
    if mask is not None:
        w, h = mask.size
        data = mask.tobytes()
        cols = [i for i in range(w) if any(data[j * w + i] > UNI_FLOOR for j in range(h))]
        if cols:
            span = (left + cols[0], left + cols[-1])
    _PSPAN[key] = span
    _PSPAN_FACE[fast] = span
    return span
# One column less between a 1 in a count and the digit after it.
ONE_TIGHT = 1
# The pen distance between two quote marks of one kind in a row.
QUOTE_RUN_CLEAR = int(_S.get("space.quote_run_clear", 0) or 0)
QUOTES = "\"'`"
# The pen distance between two of the same letter in a row.
SAME_CLEAR = int(_S.get("space.same_clear", 0) or 0)
# The stems that read as part of a quote when they touch one.
STEMS = "lI1i|"
# A stem before any of these keeps the quote clearance, the closing marks and
# the two curly closers included. build_flow() changes the second double
# quote of a line to the closing curly quote before the layout runs. Without
# the closers, the l of jsonl" never meets this rule.
STEM_CLOSERS = QUOTES + ">)]}" + "”" + "’"
STEM_QUOTE_CLEAR = int(_S.get("space.stem_quote_clear", 0) or 0)
# Clear columns after a mark that steps by its ink. The white on its right
# then matches the white on its left.
STEP_RIGHT = int(_S.get("mark.step_right", 0) or 0)
THICK_DX = 1
EDGE_INSET = max(0, min(GAP - 1 - BAND_GAP_X,
                        max(OUTLINE_W, WRAP_W) + 1 + MARK_CLEAR))


# The glyph renderer. "freetype" renders each character through FreeType with
# MacType's flags and ink curve, on each platform, and style.py sets it. Any
# other value uses Pillow. FreeType renders the same gray on each platform,
# and the measure of MacType's curve uses it.
RENDERER = str(_S.get("glyphrenderer") or "pillow")


def glyph_renderer(font):
    """Which backend renders this face: "freetype" or "pillow".

    FreeType is the only backend, and it runs on each platform. For a face
    that FreeType cannot open, this function returns Pillow, and the page
    still renders.
    """
    if RENDERER == "freetype" and freetype_glyph.available(font.path):
        return "freetype"
    return "pillow"


def glyph_backend():
    """The module that the render sites call for a mask and a pen step."""
    return freetype_glyph


def _pillow_length(font, ch):
    return font.getlength(drawn(ch)) * getattr(font, "scale_x", 1.0)


def backend_length(font, ch):
    """The backend's pen step for one character, in pixels, fraction kept.

    This function does not round the step to a whole pixel. Rounding does not
    err the same way for each letter. Against Inter's own advances at 12 px,
    b, d, p and q each lose 0.49 px while f, g and s each gain about 0.4. Two
    letters of the same apparent width then step a whole pixel apart.

    The fraction is safe to keep because backend_text() renders the glyph at
    it, through freetype_glyph.split_pen(). Without that, a fractional step
    only moves the rounding to paste time and leaves the gaps as uneven.
    """
    # CACHED across the trials of the search. A step depends on the face
    # file, its size, the bold flag, the scale and the character, and on
    # nothing that a trial changes.
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
    """First and last column that the backend inks above INK_FLOOR for this
    character, with its pen at 0.

    The backend twin of ink_span(). It reads the mask that the page pastes,
    with the same floor that ink_span() uses on Pillow's mask. A faint edge
    column then counts as ink on neither path.
    """
    span = seen.get(ch)
    if span is None:
        # The module cache lasts longer than the caller's seen dict. The later
        # trials of the search then find each span that the first measured.
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
    that Pillow's layout clears for it.

    The layout keeps Pillow's advances while each backend glyph fits inside
    the columns that ink_span() measured, because the clearance between
    neighbors then holds as rendered. When one spills, the page takes its
    advances and its spans from the backend.
    """
    seen_p = {}
    seen_b = {}
    for ch, big in {(p[0], p[2]) for p in pairs if not _is_gap(p)}:
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

    Pillow's Image.paste blends the sRGB numbers themselves. A pixel at half
    coverage then lands halfway between the two sRGB values. This function
    blends in linear light.

    MacType converts the two colors through its gamma transfer, tbl1 in
    CAlphaBlend::init, blends there, and converts the result back. This
    function does the same. With GAMMA_MODE at -1, the transfer is linear, and
    this function is arithmetically identical to Pillow's blend. That is why
    MacType's own default changes nothing until the mode is set.
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
    """One character rendered by the backend, with its baseline on the row
    that Pillow uses.

    Pillow's text call puts the face's ascent line at xy[1]. Its baseline
    then sits the ascent lower. The backend measures its mask from the
    baseline, with top negative above it. The mask then goes at that row
    plus top.

    The mask arrives already inked by MacType's curve, in
    freetype_glyph.ink_curve(), which is RenderWeight and Contrast. Nothing
    else changes its coverage.
    """
    # MacType rasterizes a glyph at the size it shows at. Each setting that
    # helps a small glyph, hinting, stem darkening and increase-x-height, acts
    # at that size. A large glyph that shrinks loses its ink in the average
    # and loses all three.
    #
    # When the layout is wider than the page, this code then asks for the
    # glyph at its final size. It does not render the glyph large and
    # squeeze it.
    # WHERE THE PEN'S FRACTION RENDERS. split_pen() picks the whole pixel to
    # paste on and the fraction to render the glyph at, together. round() on
    # the whole pixel with the fraction dropped makes the spacing uneven. The
    # pen steps that Inter asks for are fractions, and no two letters lose the
    # same amount to rounding. split_pen() must pick the two together,
    # because a pen at x.9 belongs on the pixel above x, not on x.
    # UNIFORM rounds the column and drops the fraction. Its gaps come from
    # _page_span(), which measures each glyph on whole image pixels.
    ratio = getattr(img, "ratio", None)
    if GLYPH_AT_FINAL_SIZE and ratio and ratio < 1.0:
        small = max(1.0, font.size * ratio)
        column, phase = glyph_backend().split_pen(xy[0] * ratio)
        if UNIFORM:
            column, phase = _round_px(xy[0] * ratio), 0.0
        mask, left, top = glyph_backend().glyph(
            drawn(ch), font.path, small,
            getattr(font, "sim_bold", False),
            getattr(font, "scale_x", 1.0),
            char_over(ch, "weight", 1.0) or 1.0, phase)
        if mask is None:
            return
        top -= baseline_lift(ch, mask, top)
        base = int(round(xy[1] * ratio)) + int(round(font.getmetrics()[0] * ratio))
        # paste_ink, not img.im.paste. Pillow's own paste mixes the two colors
        # as sRGB numbers. paste_ink mixes them in linear light.
        paste_ink(img.im, fill, (column + left, base + top), mask)
        return
    column, phase = glyph_backend().split_pen(xy[0])
    if UNIFORM:
        column, phase = _round_px(xy[0]), 0.0
    mask, left, top = glyph_backend().glyph(
        drawn(ch), font.path, font.size,
        getattr(font, "sim_bold", False),
        getattr(font, "scale_x", 1.0),
        char_over(ch, "weight", 1.0) or 1.0, phase)
    if mask is None:
        return
    # Each glyph that the page renders comes through here, the body, the key
    # row and the marks alike. The bracket lift then applies once and in one
    # place.
    top -= baseline_lift(ch, mask, top)
    base = round(xy[1]) + font.getmetrics()[0]
    if isinstance(img, Shrunk) and img.ratio == 1.0:
        # The native layout. Page space and layout space are one space.
        # There is then nothing to shrink, and the glyph composites directly
        # through the gamma blend.
        paste_ink(img.im, fill, (column + left, base + top), mask)
        return
    if isinstance(img, Shrunk):
        # base is the row's baseline, and each face on the row lands on it,
        # because face_for's dy is the ascent difference. See Shrunk.paste.
        img.paste(fill, (column + left, base + top), mask, anchor=base)
        return
    img.paste(fill, (column + left, base + top), mask)


def char_widths(font, pairs, big_font=None, face_for=None, renderer="pillow",
                shifts=None, spans=None, start=0, stop=None, lid=0):
    """The rendered width of each character in the flow, and its line id.

    start and stop measure only pairs[start:stop], and lid is the line id of
    pairs[start]. See _shared_widths() for when a part gives the same values
    as the whole.

    shifts, when the caller passes a list, gets one render offset per
    character. That is the columns that an INK_STEP mark's glyph moves left
    to start its ink CLEAR columns from the origin, and zero for all else.

    spans, when the caller passes a list, gets one (first, last) inked
    column per character, with the glyph's own render point at 0, and None
    for a character that inks nothing. The mark box comes from these,
    because a cell is wider than the ink inside it.

    renderer "freetype" measures with the backend that renders the glyph,
    backend_length() and backend_span(). Any other value measures with
    Pillow.

    The id steps after each pilcrow. Each character of one source line then
    has the same id whatever row it lands on.

    One clear column sits between two glyphs. No ink of one then sits next
    to or diagonal from ink of the next. This function adds a second clear
    column when either glyph inks three columns or fewer, or when the two
    glyphs are the same. A run of narrow letters, such as the c, i, f and i
    inside hookSpecificOutput, does not separate with one column. The second
    column on each pair costs far more width, and the narrow test stays.
    """
    widths = []
    ids = []
    # One ink span cache per face size. A character inks different columns
    # at each size, and two faces cannot share one cache. The key is the
    # size, not a big flag, because font.group_px can put more than two faces
    # on a page.
    seen = {}
    length, span = ({"freetype": (backend_length, backend_span)}
                    .get(renderer, (_pillow_length, ink_span)))

    def face(k, borrow=True):
        """The face that sets the cell of pairs[k]. A BIGGER mark keeps the
        cell of the body face, its pen step and its clear columns, and
        renders its larger glyph inside it."""
        p = pairs[k]
        big = p[0] not in BIGGER and len(p) > 2 and p[2]
        if face_for is not None:
            return face_for(p[0], big, borrow)[0]
        return big_font if (big_font is not None and big) else font

    # A character's width, shift and raw span depend on it and the character
    # after it, and on nothing else of the flow. A pair seen before then
    # gives the same three values. Source text repeats its pairs many times.
    _memo = {}
    # The inked columns of the last character from its own pen, and its step.
    prev = (None, 0.0)
    # The page span and page step of the last character, for UNIFORM.
    uprev = (None, 0)
    for k in range(start, len(pairs) if stop is None else stop):
        item = pairs[k]
        _mk = (item, pairs[k + 1] if k + 1 < len(pairs) else None)
        _hit = None if (UNIFORM and face_for is not None) else _memo.get(_mk)
        if _hit is not None and _NO_BANDS and item[0] == NL_MARK:
            # The step of a line end depends on the character before it.
            _hit = None
        if _hit is not None:
            w, shift, _raw = _hit
            if spans is not None:
                spans.append(_raw)
            widths.append(w)
            ids.append(lid)
            if shifts is not None:
                shifts.append(shift)
            prev = ((_raw[0] + shift, _raw[1] + shift) if _raw else None, w)
            if item[0] == NL_MARK:
                lid += 1
            continue
        ch = item[0]
        f = face(k)
        # The pen step comes from the face measured here. The clearance below
        # measures the ink that the glyph renders. A wider glyph then still
        # gets its clear column, and no two glyphs touch.
        body = face(k, borrow=False)
        if ch == GAP_MARK:
            # The blank line square renders no glyph. Its width is its own.
            own = _GAP_W_LAYOUT
        else:
            own = length(f, ch) if f.path != body.path else max(length(body, ch), length(f, ch))
        # THE PEN KEEPS ITS FRACTION. A fractional step alone does not help.
        # It gives each pair a different remainder, and each glyph still
        # pastes on a whole pixel. The gaps are then uneven. backend_text()
        # renders each glyph at its own offset through
        # freetype_glyph.split_pen(). The fraction then renders, no rounding
        # removes it, and the step can keep it.
        w = float(own + LETTER_SPACE + (char_over(ch, "adv", 0) or 0))
        # True after this step takes a MARK clearance. That is the room that a
        # line number box, an indent count, a seam or a line break needs. The
        # exact ink gap below must not overwrite those, because they hold the
        # boxes apart from each other and from the band.
        charged = False
        if ch == NL_MARK:
            # THE LINE END MARK NEVER RENDERS, and this code does not ask a
            # style override whether it does. A pilcrow blanked by a glyph
            # substitution is not the same as a pilcrow that does not render.
            # Without that override, this branch moves to the else and each
            # row on the page gets wider.
            #
            # The mark stays in the stream because it holds the band, the row
            # break rule, the band edge and the line id. The model does not
            # see it as a character. The mark takes no glyph advance and no
            # clear space of its own, because nothing renders for it. It keeps
            # BOX_CLEAR, the white between the last letter and the next band.
            #
            # The mark does hold the only space before the box of the next
            # line number, and four things must fit in it. These are the clear
            # column of the last character, the band edge one page pixel past
            # that ink, the white before the box and the box's own line.
            # BOX_CLEAR alone leaves almost no white on the left of a box.
            # mark.box_gap is the rest of the room. See style.py for the sweep
            # that set it.
            #
            # BAND_PAD_X and BAND_INSET widen the band around the run that
            # follows, on the two sides, and this step does not count them.
            # flow_rows() already counts BAND_INSET at each segment start, and
            # WRAP_GUTTER already reserves BAND_PAD_X and BAND_INSET for the
            # mark. Here they count a second time. _fit_width() then accepts
            # layouts that it must reject, and wrap marks move onto text.
            # With no band, the white before the next line number reads as a
            # space. It is then only the room that the box outline needs.
            w = float(NOBAND_LINE_GAP if _NO_BANDS else BOX_CLEAR + 1 + BOX_GAP)
            charged = True
        elif _is_count(pairs[k]) and not (k + 1 < len(pairs) and _is_count(pairs[k + 1])):
            # The last digit of a count. Clear space before the word after it.
            w += ((COUNT_CLEAR if _inner_space(pairs, k) else NOBAND_COUNT_CLEAR) if _NO_BANDS
                  else COUNT_CLEAR + (SPACE_BOX_CLEAR if _inner_space(pairs, k) else 0))
            charged = True
        elif _box_ends(pairs, k):
            # The box of the blank line count ends, and the box of the line
            # number opens. The white after a box, then the white before one.
            w += COUNT_CLEAR + BOX_CLEAR + 1 + BOX_GAP
            charged = True
        elif (_is_count(pairs[k]) and k + 1 < len(pairs)
              and _is_count(pairs[k + 1]) and not _one_box_ink(pairs[k + 1][1], pairs[k][1])):
            # The seam between a green line number and a red indent count,
            # where the divider renders. It holds white, the rule and white,
            # the same page pixel each. See mark.seam_gap in style.py.
            w += SEAM_GAP
            charged = True
        elif (SPACE_RUNS and pairs[k][0] != NL_MARK and not _is_count(pairs[k])
              and k + 1 < len(pairs) and _is_count(pairs[k + 1])
              and pairs[k + 1][1] == BLANK_INK):
            # The character before a space count inside a line. It gets the
            # same clear space that the count leaves after itself. The box
            # outline then never touches the letter or pipe before it.
            w += COUNT_CLEAR + (0 if _NO_BANDS else SPACE_BOX_CLEAR)
            charged = True
        here = (_gap_span() if ch == GAP_MARK
                else span(f, ch, seen.setdefault(f.size, {})))
        _raw = here
        if spans is not None:
            # The raw span, with its own render point at 0, before the
            # INK_STEP rebase below moves the origin.
            spans.append(here)
        shift = 0
        if ch in INK_STEP and here is not None:
            # A mark steps by its ink, not by its face's advance. A glyph from
            # a monospace face has that face's whole cell as its advance, and
            # a comma then sits in far more white than a period. The glyph
            # moves left until its ink starts CLEAR columns from the origin.
            # The pen steps to right past the ink, and the pair rule below
            # adds the same clearance that each other pair gets.
            shift = CLEAR - here[0]
            here = (CLEAR, here[1] + shift)
            w = float(round(here[1] + 1 + LETTER_SPACE + (char_over(ch, "adv", 0) or 0)))
        nxt = pairs[k + 1][0] if k + 1 < len(pairs) else None
        if ch in INK_STEP and nxt == " " and STEP_RIGHT:
            # A space after a mark keeps a full space. The pen steps to right
            # past the mark's ink, and a letter's own side bearing makes a
            # plain space wide. Without this step, the white after "aa, " is
            # barely more than after "aa,", and the model drops the space. The
            # mark's right step goes on top of the space.
            w += STEP_RIGHT
        if nxt is None:
            after = None
        else:
            nf = face(k + 1)
            after = (_gap_span() if nxt == GAP_MARK
                     else span(nf, nxt, seen.setdefault(nf.size, {})))
            if nxt in INK_STEP and after is not None:
                after = (CLEAR, after[1] - after[0] + CLEAR)
        if here is not None and after is not None:
            clear = CLEAR
            # The underscore mark takes the wider clearance whatever sits
            # beside it. Its ink span is four columns at 10 px, wide enough to
            # miss the narrow test above. The pair rule then leaves one clear
            # column between the mark and the letter after it, and the model
            # reads a letter that is not on the page.
            if (ch == nxt or UND_MARK in (ch, nxt)
                    or here[1] - here[0] <= NARROW_COLS
                    or after[1] - after[0] <= NARROW_COLS):
                clear = CLEAR_NARROW
            if UND_MARK in (ch, nxt):
                # The mark keeps the marks' own clearance whatever the letter
                # clearance is.
                clear = max(clear, MARK_CLEAR)
            if ch == nxt and ch in QUOTES and QUOTE_RUN_CLEAR:
                # Three quotes in a row read as three, not as a run of hooks.
                clear = max(clear, QUOTE_RUN_CLEAR)
            elif ch == nxt and SAME_CLEAR:
                # Two of one letter keep one more column, for the crossbar of
                # the f.
                clear = max(clear, SAME_CLEAR)
            if STEM_QUOTE_CLEAR and ((ch in STEMS and nxt in STEM_CLOSERS)
                                     or (ch in QUOTES and nxt in STEMS)):
                # The bar of an l against the bars of a quote or a closing
                # mark. Without it, jsonl" reads as json" and
                # transcript.jsonl> reads as transcript.json>.
                clear = max(clear, STEM_QUOTE_CLEAR)
            if ch in INK_STEP and STEP_RIGHT:
                # The right side of the mark keeps the white of its left side.
                clear = max(clear, STEP_RIGHT)
            # EXACT, not a floor, when space.ink_gap_exact is on.
            #
            # here[1] is the last inked column of this glyph, and after[0] is
            # the first of the next glyph, each from the glyph's own pen. This
            # line then sets the distance from ink to ink. With max(), it is
            # only a MINIMUM. A pair closer than `clear` moves apart, and a
            # pair that is already further apart stays. The gaps then stay as
            # uneven as the font's side bearings make them.
            #
            # An assignment also pulls the wide pairs in, and each pair then
            # has the same white. It loses the rhythm of the designer's
            # spacing, and that is the trade. At eleven pixels, a model that
            # must find where one word ends cannot use that rhythm anyway.
            #
            # The floor below keeps a step from going backward on a pair whose
            # ink already overlaps its own cell, as t and x do at this size.
            # ONLY ON AN ORDINARY PAIR. An assignment here discards all that
            # this step already holds. A step with a mark clearance holds the
            # room that a line number box, an indent count, a seam or a line
            # break needs. An overwrite of those runs the boxes into each other
            # and into the band.
            want = here[1] + clear - after[0]
            if EXACT_INK_GAP and not charged:
                w = float(max(1.0, want))
            else:
                w = max(w, want)
        if (ch == "1" and nxt is not None and _is_count(pairs[k]) and _is_count(pairs[k + 1])
                and pairs[k + 1][1] == pairs[k][1]):
            # A 1 in a count sits a column closer to the digit after it.
            # Without this, its thin stem makes 14 look like 1 4.
            w -= ONE_TIGHT
        if _NO_BANDS and nxt is not None and after is not None:
            # NO BANDS. Only white marks a line edge, and the white must not
            # read as a space. A box outline sits BOX_ROOM columns past the
            # ink of its digits. The white from a letter to the next box, and
            # from a box to the next letter, is then CLEAR, the gap between
            # two letters. A real space stays a space wide.
            if ch == NL_MARK and _is_count(pairs[k + 1]) and prev[0] is not None:
                room = BOX_ROOM - 1 + (BOX_ROOM if k > 0 and _is_count(pairs[k - 1]) else 0)
                w = float(max(-6.0, prev[0][1] + CLEAR + room - after[0] - prev[1]))
            elif (_is_count(pairs[k]) and here is not None
                  and not _is_count(pairs[k + 1]) and pairs[k + 1][0] != NL_MARK
                  and not _inner_space(pairs, k)):
                w = float(max(1.0, here[1] + BOX_ROOM + 1 + CLEAR - after[0]))
        if UNIFORM and face_for is not None:
            r = _UNI_R
            ps = _page_span(face_for(ch, len(item) > 2 and bool(item[2]))[0], ch)
            pa = None
            if nxt is not None:
                nk = pairs[k + 1]
                pa = _page_span(face_for(nk[0], len(nk) > 2 and bool(nk[2]))[0], nk[0])
            band = 0 if _NO_BANDS else W_BAND
            kk = None
            if nxt is None:
                pass
            elif ch == " ":
                if pa is not None:
                    kk = W_SPACE - pa[0]
            elif ch == NL_MARK:
                if _is_gap(pairs[k + 1]) and pa is not None and uprev[0] is not None:
                    # The blank line square. The band before it ends, then
                    # comes the white between two letters, then the square.
                    t = band + W_CHAR + 1
                    kk = t - pa[0] - (uprev[1] - uprev[0][1])
                elif _is_count(pairs[k + 1]) and pa is not None and uprev[0] is not None:
                    if k > 0 and _is_count(pairs[k - 1]):
                        t = 2 * BOX_SIDE + W_BOX - 1
                    else:
                        t = band + W_BOX_BEFORE + BOX_SIDE
                    kk = t - pa[0] - (uprev[1] - uprev[0][1])
            elif ps is not None:
                if nxt in (" ", NL_MARK):
                    kk = ps[1] + 1
                elif pa is not None:
                    if _box_ends(pairs, k):
                        # The box of the blank line count, then the box of
                        # the line number. Outline, W_BOX of white, outline,
                        # the same white that a letter keeps before a box.
                        kk = ps[1] + 2 * BOX_SIDE + W_BOX - 1 - pa[0]
                    elif (_is_count(pairs[k]) and _is_count(pairs[k + 1])
                            and _one_box_ink(pairs[k][1], pairs[k + 1][1])):
                        # Two digits of one number. The same white as two
                        # letters, and a 1 then never touches the digit
                        # beside it.
                        kk = ps[1] + W_CHAR + 1 - pa[0]
                    elif _is_count(pairs[k]) and _is_count(pairs[k + 1]):
                        pass  # the seam between a line number and its count
                    elif _is_count(pairs[k]):
                        t = (BOX_SIDE + W_BOX if _inner_space(pairs, k)
                             else BOX_SIDE + W_BOX_AFTER + band)
                        kk = ps[1] + t - pa[0]
                    elif _is_count(pairs[k + 1]):
                        # A letter, or the blank line square, then a box.
                        kk = ps[1] + W_BOX + BOX_SIDE - pa[0]
                    else:
                        kk = ps[1] + W_CHAR + 1 - pa[0]
            if kk is None:
                kk = _round_px(w * r)
            w = kk / r
            uprev = (ps, kk)
        _memo[_mk] = (w, shift, _raw)
        prev = (here, w)
        widths.append(w)
        ids.append(lid)
        if shifts is not None:
            shifts.append(shift)
        if ch == NL_MARK:
            lid += 1
    return widths, ids


# One character, everywhere it appears, with its ink, size, nudge, width and
# weight set once. style.py ships one entry, "adv" 1 for the (. Each other
# character keeps the settings of its group.
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


# The four marks that models swap for each other. At small sizes, the
# semicolon and the colon differ by one pixel, and the comma and the period
# by two. The model then reads "a,b:c;d" as "a.b;c:d". style.py ships
# code.tailed empty, because a tail block under a comma shows as a stray dot.
# No page then renders a tail.
TAILED = tuple(_S["code.tailed"])


def tail_box(font, ch, line_h, seen):
    """The block under a comma or a semicolon, or None when it does not fit
    inside the row.

    Two pixels one row below the glyph's own lowest ink, in the columns that
    ink already holds. A period and a colon get nothing there. The pair then
    differs by a whole row and not by one pixel. It moves no glyph and costs
    no width. The comma renders from the face one px larger and sits one row
    higher on the same baseline. The row below its ink is then clear, and the
    tail renders at each size that this packer uses.
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


# A word is what the model must keep together to use it. That is letters,
# digits, and the underscores, dots, slashes and hyphens that make an
# identifier or a path. main.gd and _fit_height are each one word by this
# rule.
WORD_CHARS = _S["code.word_chars"]


_FLAT_KEYS = {}


def _flat_keys(flat):
    """The 24-bit RGB value of each color in flat that an RGB pixel can equal,
    sorted, as an array. A pixel is three whole numbers from 0 to 255, and no
    other color matches one."""
    key = frozenset(flat)
    if key not in _FLAT_KEYS:
        keys = set()
        for c in key:
            if len(c) == 3 and all(0 <= v <= 255 and v == int(v) for v in c):
                keys.add((int(c[0]) << 16) | (int(c[1]) << 8) | int(c[2]))
        _FLAT_KEYS[key] = _np.array(sorted(keys), dtype=_np.int32)
    return _FLAT_KEYS[key]


def _ink_bounds(img, box):
    """The glyph pixels inside a window, in the page's own pixels.

    The mark box uses these bounds. The box sits at these bounds less and
    plus two page pixels on each side, and Pillow renders an outline on the
    box's own edge. Exactly one page pixel of white then stays inside it
    between the outline and the digits, on all four sides.

    There are two reasons to fit the box and not to calculate it.

    A digit's cell is wider than the ink in it, because the cell holds the
    glyph's own advance and its side bearings. A box around the cells holds
    the cell minus the ink as white, and no clearance setting reaches it.

    A box around the ink span fixes the left and the right to within a pixel
    and no better. Shrunk.paste puts a glyph's mask on the output grid by the
    row's baseline and the mask's own height. A glyph then lands a whole page
    pixel away from where the layout coordinate rounds to, and by a different
    amount per row. A read of the page removes the rounding from the
    question. The page background and a band tint are each a flat color, and
    anything else inside the window is a glyph.
    """
    im = img.im if isinstance(img, Shrunk) else img
    out = img._out if isinstance(img, Shrunk) else (lambda v: int(round(v)))
    x0, y0, x1, y1 = out(box[0]), out(box[1]), out(box[2]), out(box[3])
    w, h = im.size
    flat = set(TINTS) | {tuple(BACKGROUND)}
    xa, ya, xb, yb = max(0, x0 + 1), max(0, y0 + 1), min(w, x1), min(h, y1)
    if _np is not None and im.mode == "RGB":
        # The same window and the same test as the loop below, on the whole
        # window at once. A pixel of an RGB page is a 3-tuple, and only a
        # 3-tuple of bytes in flat can equal one.
        if xa >= xb or ya >= yb:
            return None
        a = _np.asarray(im.crop((xa, ya, xb, yb)))
        keys = (a[..., 0].astype(_np.int32) << 16) | (a[..., 1].astype(_np.int32) << 8) | a[..., 2]
        known = _flat_keys(flat)
        if len(known):
            # searchsorted() gives each key of known its own place. Any other
            # key gets the place of a different key, and it counts as ink.
            ink = known[_np.minimum(_np.searchsorted(known, keys), len(known) - 1)] != keys
        else:
            ink = _np.ones(keys.shape, dtype=bool)
        rows = _np.flatnonzero(ink.any(axis=1))
        if not len(rows):
            return None
        cols = _np.flatnonzero(ink.any(axis=0))
        return xa + int(cols[0]), ya + int(rows[0]), xa + int(cols[-1]), ya + int(rows[-1])
    px = im.load()
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
    """The page column for a seam rule. That is the middle of the white run
    between two mark runs, and the rule then keeps white on its two sides."""
    im = img.im if isinstance(img, Shrunk) else img
    x0, y0, x1, y1 = bounds
    bg = tuple(BACKGROUND)
    w, h = im.size
    if (_np is not None and im.mode == "RGB" and len(bg) == 3
            and 0 <= x0 <= x1 < w and 0 <= y0 <= y1 < h):
        # The same columns as the loop below, read from the window at once.
        a = _np.asarray(im.crop((x0, y0, x1 + 1, y1 + 1)))
        white = (a == _np.array(bg)).all(axis=2).all(axis=0)
        columns = (x0 + _np.flatnonzero(white)).tolist()
    else:
        px = im.load()
        columns = [x for x in range(x0, x1 + 1)
                   if all(px[x, y] == bg for y in range(y0, y1 + 1))]
    runs = []
    for x in columns:
        if runs and x - runs[-1][1] == 1:
            runs[-1][1] = x
        else:
            runs.append([x, x])
    if not runs:
        return near
    a, b = min(runs, key=lambda r: min(abs(r[0] - near), abs(r[1] - near)))
    return (a + b) // 2


def _is_indent_box(target, box):
    """True when the digits in box are the near-black indent ink, not the
    green line number or the red space count."""
    if _np is None:
        return False
    x0, y0, x1, y1 = [int(v) for v in box]
    a = _np.asarray(target.crop((max(0, x0), max(0, y0), x1, y1)).convert("RGB")).astype(_np.int16)
    dark = int((a.max(axis=2) < 90).sum())
    red = int((_np.abs(a - _np.array(BLANK_INK, dtype=_np.int16)).max(axis=2) < 60).sum())
    green = int((_np.abs(a - _np.array(COUNT_INK, dtype=_np.int16)).max(axis=2) < 60).sum())
    return dark > 3 and dark > red and dark > green


def _invert_box(target, box):
    """The inside of an indent box made solid black with white digits. Each
    pixel there is a blend of the background and the near-black ink, and
    this function flips the blend."""
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(target.width, x1), min(target.height, y1)
    if x1 <= x0 or y1 <= y0:
        return
    from PIL import ImageOps
    target.paste(ImageOps.invert(target.crop((x0, y0, x1, y1)).convert("RGB")), (x0, y0))


def _whiten_colors(a):
    """The new color of each pixel in a, an array of float64 pixels with RGB
    on its last axis, as uint8. See _whiten_box()."""
    bg = _np.array(BACKGROUND, dtype=_np.float64)
    out = a.copy()
    done = _np.zeros(a.shape[:-1], dtype=bool)
    for tint, ink in [(t, i) for i in (BLANK_INK, INDENT_INK) for t in TINTS]:
        ink = _np.array(ink, dtype=_np.float64)
        t = _np.array(tint, dtype=_np.float64)
        d = t - ink
        c = int(_np.argmax(_np.abs(d)))
        if abs(d[c]) < 1:
            continue
        # The share of ink in each pixel, when it is a blend of this tint and
        # the ink.
        cover = _np.clip((t[c] - a[..., c]) / d[c], 0.0, 1.0)
        blend = t + (ink - t) * cover[..., None]
        on_line = (_np.abs(a - blend).max(axis=-1) <= 6) & ~done
        done |= on_line
        mix = bg + (ink - bg) * cover[..., None]
        out[on_line] = mix[on_line]
    return _np.clip(out + 0.5, 0, 255).astype(_np.uint8)


# The new color that _whiten_box() gives each old color, by the color tables
# that it reads, then by the old color's 24-bit RGB value. The new color of a
# pixel depends on its old color alone, and the count boxes of a pack share a
# few colors. The arithmetic then runs once for each color in a process, and
# a box runs it only for a color that no box before it held.
_WHITEN_MEMO = {}


def _whiten_box(target, box):
    """The inside of a count box on white, not on the band behind it.

    A count inside a line sits on the band. With the outline alone, the tint
    shows around the digits. This function sets each tint pixel in the box
    to the background. It blends an edge pixel, where a digit blends into the
    tint, again against the background, and the digits keep their shape."""
    if _np is None:
        return
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(target.width, x1), min(target.height, y1)
    if x1 <= x0 or y1 <= y0:
        return
    region = target.crop((x0, y0, x1, y1))
    region = _np.asarray(region if region.mode == "RGB" else region.convert("RGB"))
    keys = ((region[..., 0].astype(_np.int32) << 16)
            | (region[..., 1].astype(_np.int32) << 8) | region[..., 2]).ravel()
    colors, where = _np.unique(keys, return_inverse=True)
    colors = colors.tolist()
    memo = _WHITEN_MEMO.setdefault(
        (tuple(BACKGROUND), tuple(TINTS), tuple(BLANK_INK), tuple(INDENT_INK)), {})
    new = [memo.get(k) for k in colors]
    todo = [n for n, v in enumerate(new) if v is None]
    if todo:
        rgb = _np.array([(colors[n] >> 16, (colors[n] >> 8) & 255, colors[n] & 255)
                         for n in todo], dtype=_np.float64)
        for n, v in zip(todo, _whiten_colors(rgb).tolist()):
            new[n] = memo[colors[n]] = tuple(v)
    out = _np.array(new, dtype=_np.uint8)[where.ravel()].reshape(region.shape)
    # When no pixel changes, the paste changes nothing, and this code skips it.
    if _np.array_equal(out, region):
        return
    target.paste(Image.fromarray(out, "RGB"), (x0, y0))


def _center_boxes(img, runs, bw):
    """Return {run: dx}, the columns that move each box of marks sideways so
    the white on its left equals the white on its right.

    A box of marks (a line number, a blank line count, an indent count) sits
    in the white between the band before it and the band after it. The layout
    rounds each position, and the white on the two sides differs by a pixel
    or more. Boxes side by side, with only white between their outlines, move
    as one group. A group without a band on each side, such as a box at the
    start of a row, does not move. When the white on the two sides adds up to
    an odd count, the band after the group starts one column sooner, and the
    two sides then match. The outline sits 2 columns out from the ink of its
    digits, as small.rectangle() draws it."""
    im = img.im if isinstance(img, Shrunk) else img
    px = im.load()
    W, H = im.size
    tints = set(TINTS)
    bg = tuple(BACKGROUND)
    boxes = []
    for run in runs:
        rx0, rx1, ry0, ry1 = run
        found = _ink_bounds(img, (rx0 - 2 * bw, ry0 - 2 * bw, rx1 + 2 * bw, ry1 + 2 * bw))
        if found is not None:
            boxes.append((run, found))
    boxes.sort(key=lambda b: b[1][0])
    groups = []
    for run, b in boxes:
        if groups:
            p = groups[-1][-1][1]
            y = (b[1] + b[3]) // 2
            gap = range(p[2] + 3, b[0] - 2)
            if len(gap) <= W_BOX + 2 and all(px[x, y] == bg for x in gap):
                groups[-1].append((run, b))
                continue
        groups.append([(run, b)])
    out = {}
    for g in groups:
        left_line = g[0][1][0] - 2
        right_line = g[-1][1][2] + 2
        y = (min(b[1] for _, b in g) + max(b[3] for _, b in g)) // 2
        x = left_line - 1
        while x >= 0 and px[x, y] == bg:
            x -= 1
        if x < 0 or px[x, y] not in tints:
            continue
        band_before = x
        x = right_line + 1
        while x < W and px[x, y] == bg:
            x += 1
        if x >= W or px[x, y] not in tints:
            continue
        band_after = x
        white_l = left_line - band_before - 1
        white_r = band_after - right_line - 1
        if (white_l + white_r) % 2:
            # The band after the group starts one column sooner: a copy of its
            # first column, on each of its rows.
            y0 = y
            while y0 > 0 and px[band_after, y0 - 1] in tints:
                y0 -= 1
            y1 = y
            while y1 < H - 1 and px[band_after, y1 + 1] in tints:
                y1 += 1
            for yy in range(y0, y1 + 1):
                px[band_after - 1, yy] = px[band_after, yy]
            white_r -= 1
        dx = (white_l + white_r) // 2 - white_l
        if dx:
            for run, _ in g:
                out[run] = dx
    return out


def _shift_box(target, box, dx):
    """Move the pixels inside a box dx columns sideways, and set the columns it
    leaves to the page background. box is (x0, y0, x1, y1), with x1 and y1
    one past the last column and row, as in _whiten_box()."""
    x0, y0, x1, y1 = [int(v) for v in box]
    region = target.crop((x0, y0, x1, y1))
    target.paste(tuple(BACKGROUND), (x0, y0, x1, y1))
    target.paste(region, (x0 + dx, y0))


def _is_count(pair):
    """True for a blank-line count digit or its mark. That is mark ink, not
    text."""
    ch, ink = pair[0], pair[1]
    return ink in (BLANK_INK, PILCROW_INK, COUNT_INK, INDENT_INK, TAB_INK, TAB2_INK) and (ch.isdigit() or (BLANK_MARK and ch == BLANK_MARK)
                                                or (INDENT_MARK and ch == INDENT_MARK)
                                                or _is_esc(pair))


def _inner_space(pairs, k):
    """True when pairs[k] is a digit of a space count inside a line. That is
    a red count with text before it, not the indent count after a line
    number."""
    if not SPACE_RUNS or pairs[k][1] != BLANK_INK or not _is_count(pairs[k]):
        return False
    q = k
    while q > 0 and _is_count(pairs[q - 1]) and pairs[q - 1][1] == BLANK_INK:
        q -= 1
    return q > 0 and not _is_count(pairs[q - 1]) and pairs[q - 1][0] != NL_MARK


def word_char(ch):
    """True for a character that must stay with its neighbor."""
    return ch.isalnum() or ch in WORD_CHARS


def _over_offsets(ch):
    """Where a character renders. That is once at its own spot, nudged by
    its dx and dy override, and a second time one pixel right when thick is
    set."""
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


# An opening quote never ends a row, and a closing quote never starts one,
# the same as the brackets. The pipe never sits at either end of a row.
OPENERS = "([{" + '"' + "'" + "|"
CLOSERS = ")]}" + "\u201d" + "\u2019" + "|"
# The marks of an operator word. A word of only these never ends a row.
OPERATOR_CHARS = "%+-*/=<>!&^~@#"


def split_here(pairs, k, comment_heads=None, unbroken=None):
    """True if a row can end right before pairs[k].

    The model reads a line end mark and the count of blank lines after it as
    one thing, and no row ends between them. comment_heads is
    _comment_head_table(pairs), and unbroken is _unbroken_table(pairs), when
    the caller has them.
    """
    # A space count inside a line never starts a row. At the start of a row,
    # it has no line number before it and reads as an indent. A model can
    # then rebuild "#   reached_cat" as a line "#" and a new line.
    # The blank line square and the line number after it stay on one row,
    # and a row can start with the square, as it can with a line number.
    if 0 < k < len(pairs) and _is_gap(pairs[k - 1]):
        return False
    if 0 < k < len(pairs) and _is_gap(pairs[k]) and pairs[k - 1][0] == NL_MARK:
        return True
    if (SPACE_RUNS and 0 < k < len(pairs) and pairs[k][1] == BLANK_INK
            and _is_count(pairs[k]) and not _is_count(pairs[k - 1])
            and pairs[k - 1][0] != NL_MARK):
        return False
    # The line-break mark, its count, the indent mark and its number, and the
    # first word of the line stay on one row. No row ends anywhere inside
    # that run, and the whole run moves to the next row with the word before
    # the break.
    if INDENT_MARK:
        q = k - 1
        while q >= 0 and _marked(pairs[q]) and pairs[q][0] != NL_MARK:
            q -= 1
        if any(pairs[t][0] == INDENT_MARK for t in range(q + 1, k)):
            return False
    # An opening bracket never ends a row, and a closing bracket never starts
    # one. A lone ( at the end of a row, or a lone ] or ) at the start of a
    # row, makes the model read the row again.
    # The check looks past any spaces. "| " at the end of a row and " )" at
    # the start of a row then count too.
    q = k - 1
    while q > 0 and pairs[q][0] == " ":
        q -= 1
    if pairs[q][0] in OPENERS:
        return False
    # An operator alone never ends a row. A lone %, =, +, - or # before the
    # wrap mark reads as the end of a source line. A row that ends in
    # '"..." %' and then a break can make a model move the % that starts the
    # next line to the end of the line before it. The operator starts the
    # next row, the same way as a real line break before its %.
    # Only in the UNIFORM width packs. The old search that fixes the glyph
    # scale keeps its rows.
    # A tab-indented file keeps a narrower rule, a lone % only. The full set
    # moves the rows of a tab-indented file, and a model can then move a
    # blank line.
    if (_TAB_KEY and UNIFORM and _FIXED_R and _IMG_W and 0 < q < len(pairs) - 1
            and pairs[q][0] == "%" and not _marked(pairs[q])
            and pairs[q - 1][0] == " "):
        return False
    if (not _TAB_KEY and UNIFORM and _FIXED_R and _IMG_W and 0 < k < len(pairs)
            and pairs[q][0] in OPERATOR_CHARS and not _marked(pairs[q])):
        a = q
        while a > 0 and pairs[a - 1][0] in OPERATOR_CHARS and not _marked(pairs[a - 1]):
            a -= 1
        if a == 0 or pairs[a - 1][0] == " " or _marked(pairs[a - 1]):
            return False
    r = k
    while r < len(pairs) - 1 and pairs[r][0] == " ":
        r += 1
    if pairs[r][0] in CLOSERS:
        return False
    # A row can start with a line number. The start of the line is the best
    # place for a row to start. Short lines with no space in them leave no
    # other place, and a row then breaks inside a word.
    if pairs[k - 1][0] == NL_MARK and pairs[k][1] == COUNT_INK and _is_count(pairs[k]):
        return True
    if _marked(pairs[k - 1]) and _marked(pairs[k]):
        return False
    # A row never starts with a line break. The mark stays on the row of the
    # word it ends. A wrap edge says that the line continues, and a break is
    # then never the first thing on the next row.
    if pairs[k][0] == NL_MARK:
        return False
    # A count and the text after it stay on one row. A line number or a space
    # box never ends a row away from what it counts.
    if _is_count(pairs[k - 1]) and not _marked(pairs[k]):
        return False
    # A row never ends a few characters into a comment that follows code.
    # The comment starts the next row. When a row ends with the first words
    # of a comment and the next row holds the rest, a model can misread a
    # word of the comment. With the whole comment on one row, the model
    # reads it right.
    if (comment_heads[k] if comment_heads is not None
            else _short_comment_head(pairs, k)):
        return False
    # A row ends only at a space. A break inside "_refresh_texture()", as
    # "_refresh_texture" and "()", puts the number of the next line right
    # after the "()", and a model can write that line one tab short. A run
    # with no space longer than UNBROKEN_MAX can still break, and it then
    # fits.
    if unbroken[k] if unbroken is not None else _in_unbroken(pairs, k):
        return False
    return not (word_char(pairs[k - 1][0]) and word_char(pairs[k][0]))


# The longest run with no space that never breaks across rows.
UNBROKEN_MAX = 40


def _solid(p):
    """True for a rendered character of the text, not a space and not a
    mark."""
    return p[0] != " " and not _marked(p)


COMMENT_HEAD_MIN = 11


def _short_comment_head(pairs, k):
    """True when a row that ends at k holds fewer than COMMENT_HEAD_MIN
    characters of a comment that follows code on its line. A comment starts
    at a # after a space or a space count, with code before it."""
    a = k - 1
    while a >= 0 and pairs[a][0] != NL_MARK:
        a -= 1
    code = False
    for h in range(a + 1, k):
        p = pairs[h]
        if (p[0] == "#" and code and h > a + 1
                and (pairs[h - 1][0] == " " or _is_count(pairs[h - 1]))):
            return k - h < COMMENT_HEAD_MIN
        if _solid(p) and not _is_count(p) and not _is_gap(p):
            if p[0] == "#" and not code:
                return False
            code = True
    return False


def _comment_head_table(pairs):
    """[_short_comment_head(pairs, k) for every k], in one pass.

    _short_comment_head() walks from k back to the start of the line and
    forward again, so a line of n characters costs n * n steps. On a file
    with long lines, such as an HTML email, that took most of the pack and
    gave the same page. The answer at k depends only on the first comment or
    first code character of k's line before k, and this pass finds that once
    per line. The checks and their order are those of _short_comment_head().
    """
    out = [False] * len(pairs)
    start = 0       # the first position of the current line
    code = False
    event = None    # (position, is_comment) of the line's first answer
    for k in range(1, len(pairs)):
        h = k - 1
        p = pairs[h]
        if p[0] == NL_MARK:
            start, code, event = k, False, None
        elif event is None:
            if (p[0] == "#" and code and h > start
                    and (pairs[h - 1][0] == " " or _is_count(pairs[h - 1]))):
                event = (h, True)
            elif _solid(p) and not _is_count(p) and not _is_gap(p):
                if p[0] == "#" and not code:
                    event = (h, False)
                else:
                    code = True
        if event is not None and event[1]:
            out[k] = k - event[0] < COMMENT_HEAD_MIN
    return out


def _in_unbroken(pairs, k):
    """True when pairs[k-1] and pairs[k] sit inside one run with no space,
    and that run is at most UNBROKEN_MAX characters."""
    if not (_solid(pairs[k - 1]) and _solid(pairs[k])):
        return False
    a = k - 1
    while a > 0 and _solid(pairs[a - 1]) and k - a < UNBROKEN_MAX:
        a -= 1
    b = k
    while b + 1 < len(pairs) and _solid(pairs[b + 1]) and b - a < UNBROKEN_MAX:
        b += 1
    return b - a + 1 <= UNBROKEN_MAX


def _unbroken_table(pairs):
    """[_in_unbroken(pairs, k) for every k], in one pass.

    _in_unbroken() walks the run around k at each k, up to UNBROKEN_MAX
    characters each way. Its answer is True exactly when k - 1 and k are
    both inside one run of solid characters no longer than UNBROKEN_MAX.
    This pass measures each run once. At k = 0 the walk reads the last pair,
    and this code keeps the walk there.
    """
    n = len(pairs)
    solid = [_solid(p) for p in pairs]
    out = [False] * n
    s = 0
    while s < n:
        if not solid[s]:
            s += 1
            continue
        e = s
        while e + 1 < n and solid[e + 1]:
            e += 1
        if e - s + 1 <= UNBROKEN_MAX:
            for k in range(s + 1, e + 1):
                out[k] = True
        s = e + 1
    if n:
        out[0] = _in_unbroken(pairs, 0)
    return out


# split_here() reads the characters and the mark constants, never a width.
# Its answer at a position is then the same in each trial of a file's width
# search. The table holds it for each position once. The search makes a
# layout of the same flow at up to 32 widths. A new call at each position of
# each trial took most of the time of a plan. The table keeps one entry, the
# file that is packing now.
_SPLIT_MEMO = [None, None]


def _split_table(pairs, key=None):
    """[split_here(pairs, k) for every k], built once per flow. A caller
    that has the key of its flow passes it and saves the hashing."""
    if key is None:
        key = (len(pairs), hash(tuple((p[0], p[1]) for p in pairs)))
    if _SPLIT_MEMO[0] != key:
        heads = _comment_head_table(pairs)
        unbroken = _unbroken_table(pairs)
        _SPLIT_MEMO[1] = [split_here(pairs, k, heads, unbroken) for k in range(len(pairs))]
        _SPLIT_MEMO[0] = key
    return _SPLIT_MEMO[1]


# THE ROW TABLES. The walk in flow_rows() reads each character of the file to
# find each row end, and the width search makes a layout of one file at up to
# 32 widths. Three tables, built once per flow, give the same answers by
# lookup.
#   steps[k]  the sum of the render steps before character k
#   sums[k]   the sum of the widths before character k
#   last[k]   the last position at or before k where a row can end, or -1
# Each width is a whole or half pixel. A difference of two sums is then
# exactly the sum that the walk adds up, and the rows are the walk's rows.
_ROW_MEMO = [None, None]


def _row_tables(pairs, widths, seg_starts, inset, key, split_key=None):
    if _ROW_MEMO[0] == key:
        return _ROW_MEMO[1]
    n = len(pairs)
    can = _split_table(pairs, key[0] if split_key is None else split_key)
    steps = [0.0] * (n + 1)
    sums = [0.0] * (n + 1)
    last = [-1] * n
    s = w = 0.0
    prev = -1
    for k in range(n):
        wk = widths[k]
        s += wk + (inset if seg_starts and k in seg_starts else 0)
        w += wk
        steps[k + 1] = s
        sums[k + 1] = w
        if can[k]:
            prev = k
        last[k] = prev
    tables = (can, steps, sums, last)
    _ROW_MEMO[0] = key
    _ROW_MEMO[1] = tables
    return tables


def flow_rows(pairs, widths, max_w, seg_starts=None, memo_key=None,
              split_key=None):
    """The rows that _flow_rows_walk() cuts, found by lookup. memo_key names
    the flow and its widths. split_key names the flow alone, for the split
    table, which reads no width. Without memo_key, the walk runs."""
    if memo_key is None:
        return _flow_rows_walk(pairs, widths, max_w, seg_starts)
    inset = BAND_INSET if seg_starts else 0
    can, steps, sums, last = _row_tables(pairs, widths, seg_starts, inset,
                                         (memo_key, inset), split_key)
    rows = []
    i = 0
    n = len(pairs)
    tail = _last_line_start(pairs)
    while i < n:
        base = steps[i]
        # The furthest j with steps[j] - steps[i] <= max_w. That is where the
        # walk stops, compared as the same exact difference that it adds up.
        # A binary search by hand, because bisect's key argument needs Python
        # 3.10.
        lo, hi = i, n
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if steps[mid] - base <= max_w:
                lo = mid
            else:
                hi = mid - 1
        j = lo
        if j == i:
            # The walk cannot place even one character here. This code
            # returns the case to the walk unchanged and does not answer it.
            return _flow_rows_walk(pairs, widths, max_w, seg_starts)
        top = min(j, n - 1)
        cut = last[top] if top > i and last[top] > i else -1
        if j < n and cut > i:
            used = sums[cut] - sums[i]
            if FILL <= 0 or used >= (1.0 - FILL) * max_w:
                j = cut
        if j < n and last[j] >= i + 1:
            j = last[j]
        if UNIFORM and j < n and pairs[j - 1][0] != NL_MARK:
            # NO SCRAP OF A LINE AT A ROW'S END. When the row ends a few
            # characters into a line, the whole line moves to the next row.
            # A short head such as "148 if" alone at the end of a row shows
            # its band as a sliver, and a model can give the line the band
            # color of the line before it.
            q = j - 1
            while q > i and pairs[q - 1][0] != NL_MARK:
                q -= 1
            if q > i and pairs[q - 1][0] == NL_MARK and (
                    j - q < LINE_HEAD_MIN or _short_head(pairs, q, j)):
                j = q
        if i < tail < j:
            j = tail
        rows.append((i, j))
        i = j
    return rows


def _last_line_start(pairs):
    """The index where the last rendered line of the file starts, with its
    number first, or -1 for a file of one line or a file that ends with a
    newline.

    A FILE WITH NO NEWLINE AT ITS END STARTS ITS LAST LINE ON ITS OWN ROW,
    and the key says "no newline at end of file". When the last line starts
    at the end of the row before it, a model can give it the indent of that
    row and add a newline after it. On its own row, the line starts at the
    left edge like line 1, and build_flow gives it a red count, "0" when it
    has no indent. The end of the file then stands apart from the rest. A
    file that ends with a newline keeps its rows."""
    if not _NO_FINAL_NL:
        return -1
    q = len(pairs) - 2
    while q >= 0 and pairs[q][0] != NL_MARK:
        q -= 1
    return q + 1 if q >= 0 else -1


# The fewest characters of a line, its number included, that a row can end
# with. With depth bands, a higher value keeps a sliver of band from giving a
# line the color of its neighbor. At 6, the pages stay inside their token
# ceilings.
LINE_HEAD_MIN = 6
# The fewest TEXT characters of a line that a row can end with. The square,
# the number, the count and the spaces around the text do not count. "146 1
# if" at the end of a row passes the 6 above with only two letters of text,
# and a model can then write the lines after it at the wrong depth.
LINE_TEXT_MIN = 3


def _head_len(pairs, q):
    """How many pairs start the line at q before its text. These are the
    blank line count with its \\n, the line number and the indent count
    with its \\t."""
    n = len(pairs)
    k = q
    if k < n and _is_gap(pairs[k]):
        k += 1
    while k < n and pairs[k][1] == COUNT_INK and _is_count(pairs[k]):
        k += 1
    while k < n and pairs[k][1] in (TAB_INK, TAB2_INK, BLANK_INK) and _is_count(pairs[k]):
        k += 1
    return k - q


def _short_head(pairs, q, j):
    """True when a row that ends at j holds fewer than LINE_TEXT_MIN text
    characters of the line at q, such as "146 1 if" before the rest of its
    line."""
    text = "".join(p[0] for p in pairs[q + _head_len(pairs, q):j]).strip()
    return len(text) < LINE_TEXT_MIN



def _flow_rows_walk(pairs, widths, max_w, seg_starts=None):
    """Cut the character stream into rows, and never through a word.

    A cut that fills a row to max_w and stops wherever the width ends puts
    half a name on one row and half on the next. The model must then join
    the halves before it can use the name.

    The row ends at the last place inside it where at least one of two
    neighboring characters is not a word character. A word wider than a whole row
    must still break. The row where it breaks keeps the WRAP_INK edge, which
    already tells the model that the source line continues.
    """
    # The render step advances BAND_INSET at each segment on the row, at "x
    # += seg_w + BAND_INSET", and a segment is one source line. A row with
    # several short lines then renders that much wider than the widths summed
    # here. Without this charge, the wrap mark lands past the row end, and
    # the clamp in wrap_edge() moves it back onto the text. The inset charge
    # here makes the row end where the render step ends it.
    inset = BAND_INSET if seg_starts else 0

    def step(j):
        return widths[j] + (inset if j in seg_starts else 0)

    if not seg_starts:
        def step(j):  # noqa: F811 - the plain sum when the caller gives no segments
            return widths[j]

    rows = []
    i = 0
    n = len(pairs)
    can = _split_table(pairs)
    tail = _last_line_start(pairs)
    while i < n:
        w = 0.0
        j = i
        cut = -1
        while j < n and w + step(j) <= max_w:
            w += step(j)
            j += 1
            if j < n and can[j]:
                cut = j
        if j < n and cut > i:
            # A word-safe cut that leaves the row emptier than page.fill
            # yields to the width cut, and the row then runs to the edge.
            used = sum(widths[q] for q in range(i, cut))
            if FILL <= 0 or used >= (1.0 - FILL) * max_w:
                j = cut
        # The width cut can still land between a mark and its count. This
        # code walks back to the last place where a row can end. It takes the
        # width cut only when the walk reaches the start of the row.
        if j < n:
            back = j
            while back > i + 1 and not can[back]:
                back -= 1
            # A row with no place to end inside it keeps the width cut. A cut
            # at i + 1 in all cases gives a token wider than a row, such as a
            # long dash table rule, one row per character.
            if back > i and can[back]:
                j = back
        if i < tail < j:
            j = tail
        rows.append((i, j))
        i = j
    return rows



class Shrunk(object):
    """A page rendered at its final size while the layout runs at the
    supersampled size.

    The layout gives each coordinate in the big space. A glyph mask arrives
    at the big size, and this class shrinks it alone, aligned to the output
    pixel it lands in. It then lands where the whole-page shrink puts it. A
    band, a bar or a line renders directly at the small size. Nothing the
    size of the big page is ever allocated, and the page renders in a
    fraction of the time of the whole-page shrink.
    """

    def __init__(self, width, height, shrink_to=None, shrink_by=None, pixels=True):
        big_w = -(-width // dp.PATCH) * dp.PATCH
        if shrink_to:
            self.ratio = float(shrink_to) / big_w
        else:
            self.ratio = 1.0 / float(shrink_by or 1)
        if _FIXED_R:
            self.ratio = _FIXED_R
        self.width = max(1, int(round(width * self.ratio)))
        self.height = max(1, int(round(height * self.ratio)))
        if pixels:
            self.im = Image.new("RGB", (self.width, self.height), BACKGROUND)
            self.im.info["densepack_small"] = True
        else:
            # A plan's trial, with the same size and no pixels. See _PlanPage.
            self.im = _PlanPage(self.width, self.height, True)
        self.mode = "RGB"
        self.size = self.im.size

    def _out(self, v):
        return int(round(v * self.ratio))

    def paste(self, fill, box, mask=None, anchor=None):
        """fill at box with a big-space mask, shrunk to land on the output grid.

        anchor, when given, is the row's own baseline in the big space, which
        each face on the row shares. The glyph hangs from it. The rows it
        reaches below the baseline truncate and do not round. The one-column
        overshoot of a round letter then collapses onto the baseline, while a
        real descender keeps the rows it needs. Without anchor, the letters
        of a row split across two output rows.
        """
        r = self.ratio
        if mask is None:
            # A whole image, as a sheet pastes a page. Scale and paste.
            im = fill
            w_out = max(1, int(round(im.width * r)))
            h_out = max(1, int(round(im.height * r)))
            self.im.paste(im.resize((w_out, h_out), SHRINK_FILTER), (self._out(box[0]), self._out(box[1])))
            return
        x, y = box[0], box[1]
        if SNAP_GLYPHS:
            # Each glyph lands on a whole output pixel, the way this class's
            # rectangle() already lands. Its shrunk mask keeps its own width
            # and does not grow into its neighbor. With the sub-pixel
            # remainder kept and the mask shrunk at that offset, a stem spreads
            # over two columns. A pair such as the n, c and e of readonce then
            # touch, and less ink lands at full strength.
            # The two axes round. A floor on the vertical moves each glyph
            # down, by a different amount per letter, because each mask has
            # its own top offset. An l, a k, a d and an h reach higher. Their
            # offset then lands on a different side of the whole pixel, and
            # they sit a row below the round letters on the same line.
            # The height takes the ceiling, not the round, because rounding
            # loses ink at small sizes. A contrast lift after the render is
            # not the answer. The page must come from the renderer that way
            # and not get a later correction.
            bx = int(round(x * r))
            # The width rounds, and a glyph then renders at the width it
            # shrinks to. A ceiling stretches each glyph into the next whole
            # pixel, the column of its neighbor. A pair such as the a and the
            # b of "ab" then touch. The height keeps its ceiling, and the ink
            # of a letter above and below stays the same.
            w_out = max(1, int(round(mask.width * r)))
            h_out = max(1, int(math.ceil(mask.height * r)))
            # The glyph hangs from its bottom edge, not its top. Each letter
            # on a row shares one bottom in the big space, the baseline, while
            # their tops differ by letter. A round of the top then puts an a
            # and an l on different output rows. A round of the bottom minus
            # the height lands each letter of a row on one baseline, and a
            # descender keeps its own lower bottom. This is placement only.
            # The mask, its size and its ink stay the same. The horizontal
            # keeps its single rounding, because a separate round of the pen
            # and the bearing doubles the worst error to a whole pixel and
            # opens gaps inside words.
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
        # THIS METHOD RENDERS EACH GLYPH OF A PAGE WHOSE RATIO IS ABOVE 1.0.
        # backend_text sends a glyph here at such a ratio, and at each ratio
        # other than 1.0 when page.glyph_at_final_size is off.
        # page.fill_bottom makes such a page when a one page file leaves more
        # white at its foot than at its head. The fill narrows the layout to
        # grow the glyph. The page is then wider than the layout, and the
        # ratio rises above 1.0.
        #
        # Pillow's own paste mixes the ink and the band as sRGB numbers.
        # paste_ink does the mix in linear light, which FreeType's own
        # guidance calls the correct way.
        #
        #   https://freetype.org/freetype2/docs/hinting/text-rendering-general.html
        #
        # DENSEPACK_GAMMA_MODE acts only inside paste_ink. With a paste that
        # skips paste_ink, the mode changes no pixel.
        paste_ink(self.im, fill, (bx, by), small)

    def drawer(self):
        return _ShrunkDraw(self)


class _ShrunkDraw(object):
    """ImageDraw's rectangle, line and text on a Shrunk canvas. They take big
    coordinates and render at the small size."""

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
        # This method renders the line at four times the size on its own mask
        # and shrinks it. A curve then lands smooth on the output grid. On the
        # small canvas directly, it becomes steps.
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
    """Pack text as banded code pages named <out_stem>-1.png and up.

    python=False classifies the tokens by shape and not by tokenize, for
    each code suffix in CODE_SUFFIXES other than .py.

    layout, when the caller passes a dict, gets the place of each item. "pairs" is
    the character stream as (char, big) tuples, "ids" the source line of
    each, "line_h" the row height, and "pages" one entry per page. Each page
    entry holds "rows" as (y, h, a, b), "chars" as (j, x, y, w), and the
    "sheet" number and "x_off" where the page sits inside its sheet file.
    None, the default, fills nothing.
    """
    raw = keep_leading_tabs(text)
    global _NO_FINAL_NL
    _NO_FINAL_NL = bool(raw) and not raw.endswith("\n")
    # build_flow stores each newline as a mark and raises an error without a
    # last one. A source file that ends mid-line is common outside python.
    # Without this newline, the caller catches that error and packs nothing,
    # and the file gets the plain pack and not the banded image.
    if not raw.endswith("\n"):
        raw += "\n"
    # ONE FLOW PER FILE. build_flow() depends on the text, the language flag
    # and the legend, and the trials of the search pass the same three each
    # time. This code then builds the flow once per file.
    _flow_key = (hash(raw), bool(python), id(legend) if legend is not None else None,
                 _NO_FINAL_NL, UNIFORM)
    # A glyphless trial that records no layout skips the per-character render
    # loop below. See the loop for what it makes and why none of it stays.
    # This code reads the switch once, not once per row.
    _DEBUG_RUNS = __import__("os").environ.get("DENSEPACK_DEBUG_RUNS")
    _SKIP_CHARS = bool(_NO_GLYPHS and layout is None and not _DEBUG_RUNS)
    # A plan's trial makes no pixels at all. Its pages are sizes. The plan
    # reads page sizes, start lines and the clamp count, never a pixel. The
    # one pass that reads the pixels of a trial, the one page fill, does not
    # run for a plan.
    _NO_PIXELS = bool(_SKIP_CHARS and _PLAN_ONLY)
    _flow_hit = _FLOW_CACHE.get(_flow_key)
    if _flow_hit is not None and _flow_hit[0] == raw:
        pairs = list(_flow_hit[1])
    else:
        # build_flow() does not read UNIFORM. The search and the UNIFORM pack
        # of one file then share one build, and only the drop below differs.
        _built = _BUILT_FLOW.get(_flow_key[:-1])
        if _built is not None and _built[0] == raw:
            pairs = list(_built[1])
        else:
            pairs = build_flow(raw, python, legend)
            _BUILT_FLOW.clear()
            _BUILT_FLOW[_flow_key[:-1]] = (raw, list(pairs))
        if not UNIFORM:
            # The old width search runs with no blank line count. It picks
            # the glyph scale, and the count must not move it. With a blank
            # line mark in the search, the scale of a file can change, such
            # as from 0.931 to 0.9333. The UNIFORM pack that ships has the
            # count.
            pairs = _drop_blank_counts(pairs)
        _FLOW_CACHE.clear()
        _FLOW_CACHE[_flow_key] = (raw, list(pairs))
    # flow_depths() reads only the text. This code keeps its result per flow,
    # like the flow.
    if _DEPTHS[0] != _flow_key:
        _DEPTHS[1] = flow_depths(raw)
        _DEPTHS[0] = _flow_key
    depths = list(_DEPTHS[1])
    # The split table reads the flow and the operator rule of split_here(),
    # never a width. Its key then leaves out the widths.
    _split_key = (_flow_key, len(pairs), bool(UNIFORM and _FIXED_R and _IMG_W))
    if _WARM_FLOW:
        # A render helper before the plan comes. The plan picks the widths,
        # and the widths set char_widths(). The flow and the split table do
        # not change with the widths, and the helper keeps them for the
        # planned pack.
        _split_table(pairs, _split_key)
        return [], 0, 0
    font = dp.load(dp.REGULAR, px)
    written = []
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + 1

    # A SETTING CAN PIN THE ROW HEIGHT.
    #
    # space.row_px holds the glyph size that sets the ROW, while px
    # is the size that the GLYPHS render at. Zero means that the row follows
    # the glyphs.
    #
    # WHAT IT IS FOR. font.scale_x raises the x-height. It asks for a larger
    # size and condenses the width back. 17 px condensed to 0.588 then renders
    # an x-height of 10 in the same 6 px column that a 10 px face uses. The
    # row then follows the ascent and descent of the 17 px face, and the page
    # grows with it. A row pinned to the 10 px face keeps the band at the
    # 10 px size and lets the taller glyphs use it.
    #
    # WHAT IT COSTS, and it is not small. On Inter SemiBold, a 10 px row is 14
    # px tall and its ink spans 13 of them, which leaves one spare pixel. A 17
    # px face condensed to 0.588 spans 22 px of ink. Pinned to the 10 px row,
    # 8 px of that ink has no room. Ascenders reach into the band above and
    # descenders into the one below. The clamp below keeps the page edge from
    # cutting a glyph. It does not keep rows apart.
    ROW_PX = float(_S.get("space.row_px", 0) or 0)
    if ROW_PX:
        row_font = dp.load(dp.REGULAR, int(round(ROW_PX)))
        row_ascent, row_descent = row_font.getmetrics()
        line_h = row_ascent + row_descent + 1
        # The baseline stays where the ROW puts it. The band and the line
        # numbers then sit where they sit at that size.
        ascent = row_ascent

    # A character with its own font or size can be taller than the body face,
    # and can sit lower or higher on the row. The row grows by the reach of
    # the tallest such glyph above and below the body's own. The body
    # baseline moves down by the reach above. No glyph then touches the row
    # before it, and the bottom of the page cuts none.
    # The reach is the glyph's own ink, not the metrics of its face. A face's
    # ascent can sit far above the mark it renders, and the metrics make each
    # row and each band thick. This code measures the glyph on the body
    # baseline, at the pick's own size. The backend branch below is off
    # ("if False"), and Pillow's getbbox gives the ink, from the body face
    # when the override font file is missing. Each glyph then gets the same
    # clear room to the band's edge, a fifth of the type size above and
    # below. The gap between rows then reads the same on each row.
    up = down = 0.0
    margin = px * 0.2
    for _ch, over in CHAR_OVER.items():
        if not (over.get("font") or over.get("px")):
            continue
        # The pick's own size, not the BIGGER one. The larger mark grows into
        # the margin, and the row is the same with the marks on or off.
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
            # A font override that names a missing font file uses the body
            # face. face_for() does the same when it builds the face that
            # the page renders with. Without the character, the row height
            # loses that glyph's ink, and up, down and the baseline move. Each
            # glyph on each row then shifts while the page size stays the
            # same.
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
    # EACH ROW KEEPS ITS OWN CLEAR ROWS.
    #
    # The loop above only reaches a character with a font or a px override,
    # and char.overrides holds none of those. Up and down then stay 0, and the
    # row is exactly as tall as the tallest ink in it. Each ascender is then
    # on the band's top edge and each descender on its bottom.
    #
    # A larger band does not work. band.grow_t and grow_b move the band edge
    # without moving the glyph. The band then reaches into the row gap, and
    # neighboring bands merge.
    #
    # The room must come from the row height, and this code does that. It
    # costs page, and the cost is the point. Clearance is space.
    up = max(up, BAND_TEXT_CLEAR)
    # The band loses BAND_GAP_Y rows off its FOOT, at by1 = line_h - 1 -
    # BAND_GAP_Y + .... A row tall enough for the ink plus a clear row on each
    # side still leaves the band short by that gap. The charge here makes the
    # band itself tall enough to center in. Without it, the tallest glyph, the
    # pipe, sits in a band with one row of slack, and no offset can give it a
    # clear row above AND below.
    down = max(down, BAND_TEXT_CLEAR + BAND_GAP_Y)
    up, down = int(up + 0.999), int(down + 0.999)
    # THE BAND CENTERS ON THE TEXT.
    #
    # band.offset_y moves the band as one unit. It trades the clear rows above
    # the text against the clear rows below, two rows of balance per unit. A
    # value tuned by hand is right at one glyph size only.
    #
    # The offset comes from where the ink falls. The band's own edges sit at
    #
    #     top    = offset - band.pad_y - grow_t
    #     bottom = line_h - 1 - band.gap_y + band.pad_y + offset + grow_b
    #
    # and the ink sits at rows up through up + ink_h - 1 of the row. Equal
    # clearance above and below then gives
    #
    #     offset = (up - down + grow_t - grow_b + band.gap_y) / 2
    #
    # measured against the face's REAL ink and not its nominal ascent and
    # descent, because the metrics of a face reserve room that it does not
    # always use.
    if CENTRE_TEXT:
        ink_top = ink_bot = None
        for _c in "AQbdfghjklpqty0123456789|()[]{}_":
            # A character in font.bigger_chars renders BIGGER_PX larger and
            # hangs from the same baseline. It then reaches higher than the
            # body face does. A measure at the body size understates the top
            # and puts the pipe, parenthesis and bracket on the band's topmost
            # row.
            _px = px + (BIGGER_PX if _c in BIGGER else 0)
            try:
                _m, _l, _t = glyph_backend().glyph(_c, font.path, _px)
            except Exception:  # noqa: BLE001
                _m = None
            if _m is None:
                continue
            # The paste step lifts a bracket onto the baseline, and the band
            # must measure it where it lands. It changes no band on a page
            # that shows a pipe, because the lifted [ reaches the pipe's own
            # 15 rows above the baseline and no further.
            _t -= baseline_lift(_c, _m, _t)
            _a = ascent + _t
            _b = _a + _m.height
            ink_top = _a if ink_top is None else min(ink_top, _a)
            ink_bot = _b if ink_bot is None else max(ink_bot, _b)
        if ink_top is not None:
            # ink_bot from the loop is one PAST the last inked row, and the
            # last inked row is ink_bot - 1. The band's own edges, relative to
            # the row's top y, are
            #
            #     band top    = offset - band.pad_y - grow_t
            #     band bottom = line_h - 1 - band.gap_y + band.pad_y
            #                   + offset + grow_b
            #
            # Equal clearance above the first inked row and below the last
            # then gives
            #
            #     offset = (ink_top + ink_last + 1 + gap_y - line_h
            #               + grow_t - grow_b) / 2
            #
            # FLOOR, NOT ROUND. Python's round is half to even.
            # int(round(-0.5)) is then 0 and not -1, and round sends the half
            # step of an odd slack the wrong way.
            #
            # Floor and not ceil, because the extra row is worth more below
            # the text than above it. A descender that touches reads as a
            # different letter, while an ascender that touches is still that
            # letter.
            #
            # Do not add an "+ up - down" term. The derivation above appears
            # to ask for it, because this code reads ink_top and line_h before
            # "line_h += up + down" runs. It moves each band one row up. The
            # term that the derivation asks for is half of that, and
            # the +1 that the floor drops is the same half step. It is then
            # already paid.
            #
            # WHAT IS LEFT IS NOT GEOMETRY, IT IS CONTENT. The band spans the
            # rows that the tallest glyph on the page needs, a pipe rendered
            # one px bigger, and the rows the deepest descender needs. A row
            # whose tallest glyph is an ordinary ascender then shows paper
            # that the band keeps for a character that the row does not hold.
            # No offset can remove that. Only a taller row can, and a taller
            # row costs page on each line.
            #
            # Measure a band against the page before you change this, and
            # measure WHOLE bands. The digits' own ink cuts a scan down one
            # column in two, and each half then measures as its own band.
            ink_last = ink_bot - 1
            BAND_OFF_Y_ROW = int(math.floor(
                (ink_top + ink_last + 1 + BAND_GAP_Y - line_h
                 + BAND_GROW[2] - BAND_GROW[3]) / 2.0))
        else:
            BAND_OFF_Y_ROW = BAND_OFF_Y
    else:
        BAND_OFF_Y_ROW = BAND_OFF_Y
    # The blank line square of the key row sits on the same rows as the
    # bands of the page.
    global _KEY_BAND_OFF_Y
    _KEY_BAND_OFF_Y = BAND_OFF_Y_ROW
    line_h += up + down
    ascent += up

    # The larger face, on the row's own baseline. Its ascent is taller. A
    # character marked big then starts that many rows higher and grows up
    # into the rows that the type leaves clear. Nothing below the baseline
    # moves, and no row changes height. One face serves the two callers of
    # the big flag, the LIFT token and the two BIGGER punctuation marks,
    # because LIFT_PX ships at 0 and only one of the two is ever on.
    big_px = LIFT_PX or BIGGER_PX
    big_font = dp.load(dp.REGULAR, px + big_px) if big_px else None
    big_dy = ascent - big_font.getmetrics()[0] if big_font else 0

    # One face per size offset. The offset is the big flag's px plus the
    # character group's own, and the two settings add and do not conflict.
    # With each font.group_px at zero, this returns two faces, the body face
    # and the big one.
    faces = {(0.0, None): (font, up)}
    if big_font is not None:
        faces[(float(big_px), None)] = (big_font, big_dy)

    def face_for(ch, big, borrow=True):
        """The face that one character renders from, and the rows it moves
        down.

        A character with a font override renders from that file, and each
        other character stays in the body face. The dy is the ascent
        difference, and the borrowed glyph then sits on the row's own
        baseline. For a font file that is missing, this function uses the
        body face. An override list that names a Windows font then does not
        break a page on another system.

        borrow=False returns the body face at the same size. That is the face
        for the measure of the pen step. See char_widths().
        """
        off = float((big_px if big else 0) + GROUP_PX.get(dp.group_for(ch), 0.0)
                    + (char_over(ch, "px", 0.0) or 0.0))
        # THE MARKS IN font.full_width_chars RENDER AT font.mark_px.
        # font.scale_x does not condense them either, and they keep their full
        # width at that size.
        #
        # Zero means the page's own size. The offset is from the page size. A
        # mark_px of 12 on a 13 px page then renders the marks one pixel
        # smaller than the size asked for the letters. The letters condense
        # back to the 10 px column, and the marks do not.
        # A SIZE NAMED FOR ONE CHARACTER OVERRIDES EACH GROUP,
        # font.scaled_marks included. One setting names the size, the other
        # names the width, and either can apply to one character without a
        # change to its group.
        if ch in MARK_PX_BY_CHAR:
            off += MARK_PX_BY_CHAR[ch] - px
        elif ch in SCALED_MARKS:
            # This group keeps the PAGE's size and takes its own condense from
            # scale_for. No size rule then applies to it.
            pass
        elif MARK_PX and ch in FULL_WIDTH:
            off += MARK_PX - px
        # Borrowed faces stop at char.font_max_px, because borrowed advances
        # split a page into more pages and cost patches.
        borrowed = borrow and px <= FONT_MAX_PX
        # font.scale_x is the page's own horizontal scale. It reaches FreeType
        # as face.set_char_size(width = size * scale, height = size). The
        # outline then condenses, and its height stays the same. The x-height
        # measures the same at each value. scale_for() sets which characters
        # take it.
        #
        # A per character scale_x in char.overrides still overrides this, and
        # nothing sets one.
        page_scale = scale_for(ch)
        # borrowed DOES NOT GATE BOLD. borrowed means "this character takes
        # its glyph from ANOTHER font file", and char.font_max_px limits that.
        # Bold is a property of the current face, and the two are unrelated.
        # Tied together, char.overrides[ch]["bold"] never reaches a page,
        # because char.font_max_px is 0 and borrowed is false at each size
        # that this renderer renders.
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

    # One answer per character for this pack. face_for() reads only the
    # character, the two flags, px and the module's settings. Without the
    # memo, it runs once per character per trial, millions of calls on one
    # large file.
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
    # The soft path renders through Pillow's own text call, which is the
    # blend of the font itself. Neither branch runs on a shipped page.
    # curve.name is "none", and curve is then never "soft". glyphrenderer is
    # freetype.
    plain_soft = curve == "soft" and blur in ("auto", "full")
    # The renderer for this face. See glyph_renderer().
    renderer = glyph_renderer(font)
    use_backend = renderer == "freetype"
    # THE BACKEND THAT RENDERS A GLYPH MEASURES IT. font.scale_x does not
    # condense Pillow's mask for ink_span(). Its spans are then wider than the
    # glyph on the page, and the pair rule spreads the letters to clear them.
    shifts = []
    spans = []
    # ONE MEASURE PER FILE. The widths, ids, shifts and spans depend on the
    # characters, the faces and the size, and on nothing that the search
    # changes between its trials. The second trial of a file and each one
    # after it then take the lists of the first trial. This code returns
    # copies, because the pack below can change what they hold.
    global _UNI_R
    _UNI_R = 1.0
    _PSPAN_FACE.clear()
    if UNIFORM and _FIXED_R:
        _UNI_R = _FIXED_R
    elif UNIFORM:
        _w0 = int(2 * PAD + (PAGE_W - WRAP_GUTTER)) + PAGE_EXTRA
        _big = -(-_w0 // dp.PATCH) * dp.PATCH
        if DIRECT_CANVAS and SHRINK_TO and renderer == "freetype":
            _UNI_R = float(SHRINK_TO) / _big
        elif DIRECT_CANVAS and SHRINK_BY and SHRINK_BY > 1 and renderer == "freetype":
            _UNI_R = 1.0 / float(SHRINK_BY)
    # The blank line square. As tall as the band, half as wide, in whole
    # final image pixels. The band's height is by1 - by0 + 1 in the render
    # loop.
    global _GAP_W, _GAP_W_LAYOUT
    _band_h = line_h - BAND_GAP_Y + 2 * BAND_PAD_Y + BAND_GROW[2] + BAND_GROW[3]
    _GAP_W = max(1, _round_px(_round_px(_band_h * _UNI_R) / 2.0))
    _GAP_W_LAYOUT = _GAP_W / _UNI_R
    _cw_key = (px, renderer, getattr(font, "path", None), getattr(font, "size", None), _UNI_R,
               getattr(big_font, "size", None) if big_font is not None else None,
               len(pairs), _pairs_hash(_flow_key, pairs))
    _cw_hit = _CW_CACHE.get(_cw_key)
    if _cw_hit is not None:
        widths, ids = list(_cw_hit[0]), list(_cw_hit[1])
        shifts.extend(_cw_hit[2])
        spans.extend(_cw_hit[3])
    elif _CW_SHARE is not None and UNIFORM:
        widths, ids = _shared_widths(font, pairs, big_font, face_for, renderer,
                                     shifts, spans)
        _CW_CACHE.clear()
        _CW_CACHE[_cw_key] = (list(widths), list(ids), list(shifts), list(spans))
    else:
        widths, ids = char_widths(
            font, pairs, big_font, face_for,
            renderer=renderer,
            shifts=shifts, spans=spans)
        _CW_CACHE.clear()
        _CW_CACHE[_cw_key] = (list(widths), list(ids), list(shifts), list(spans))
    words = word_indices(pairs, ids) if PLACEMENTS or layout is not None else None

    # The row width stays fixed at each type size. A width that scales with
    # the type size costs more, with more cache written and more output.
    # The wrap mark renders past the row's last character, at the band's own
    # right edge. wrap_edge() then clamps it back inside the page when it
    # does not fit. That clamp puts the mark on top of the last columns of a
    # row's text or line number.
    #
    # With the mark's own columns reserved here, a row can never fill them,
    # and the clamp never fires. A word that no longer fits moves to the next
    # row and does not render under the mark. The rows that this adds land
    # in the white that page.fill_bottom already leaves at the foot of a page.
    max_w = PAGE_W - WRAP_GUTTER
    if UNIFORM and _FIXED_R and _IMG_W:
        # The row runs to the image width at the fixed scale, less the pads
        # and the room of the wrap mark past the last ink. That is the band,
        # the white, the wave and the clamp margin that wrap_edge() keeps.
        max_w = (int(_IMG_W / _FIXED_R) - 2 * PAD - ROW_LEFT / _FIXED_R
                 - (W_BAND + W_BOX + 2 + 3 * WRAP_W + 4) / _FIXED_R)
    # One segment per source line. seg_end[k] is the end of the segment that
    # holds k, where the render loop below cuts it. line_ends holds each line
    # break. The three depend only on the flow and its ids, and each trial of
    # the search gets the same three. This code then makes them once per flow
    # and widths.
    if _SEG_MEMO[0] != (_flow_key, _cw_key):
        _n = len(ids)
        _ends = [_n] * _n
        for _j in range(_n - 2, -1, -1):
            _ends[_j] = _ends[_j + 1] if ids[_j + 1] == ids[_j] else _j + 1
        _SEG_MEMO[1] = ({j for j in range(_n) if j == 0 or ids[j] != ids[j - 1]}, _ends,
                        [j for j, p in enumerate(pairs) if p[0] == NL_MARK])
        _SEG_MEMO[0] = (_flow_key, _cw_key)
    seg_starts, seg_end, line_ends = _SEG_MEMO[1]
    rows = flow_rows(pairs, widths, max_w, seg_starts, memo_key=(_flow_key, _cw_key),
                     split_key=_split_key)
    # A run of widths summed through the row tables that flow_rows() used. It
    # is a difference of two running sums, exact because each width is a
    # whole or half pixel. No code below this line changes widths. Without
    # the tables, the plain sum runs.
    _rt = _ROW_MEMO[1] if (_ROW_MEMO[0] is not None
                           and _ROW_MEMO[0][0] == (_flow_key, _cw_key)) else None
    if _rt is not None:
        _sums = _rt[2]

        def _wsum(a, b):
            return _sums[b] - _sums[a] if b > a else 0
    else:
        def _wsum(a, b):
            return sum(widths[j] for j in range(a, b))
    # True when each character from a to b is a count mark or a line break.
    # This is the lone mark test, once per segment. A running count of such
    # characters per flow answers it without a walk over the segment.
    _mk = _MARK_COUNT[1] if _MARK_COUNT[0] == _flow_key else None
    if _mk is None:
        _mk = [0] * (len(pairs) + 1)
        _c = 0
        for _j, _p in enumerate(pairs):
            if _is_count(_p) or _p[0] == NL_MARK:
                _c += 1
            _mk[_j + 1] = _c
        _MARK_COUNT[0] = _flow_key
        _MARK_COUNT[1] = _mk

    def _all_marks(a, b):
        return _mk[b] - _mk[a] == b - a

    # Reading guidance only. The model answers from the code and never writes
    # the stream out. An order to output the marked stream makes each model
    # copy the images out before it answers, at many times the output tokens.
    if _SCHEME[0] != _flow_key:
        _SCHEME[1] = scheme_for(pairs)
        _SCHEME[0] = _flow_key
    scheme = list(_SCHEME[1])

    # The scheme is the line on the prompt card, sent once per session, and
    # no page shows it. The budget still holds those rows back. A page break
    # then falls where it falls with them, and a page is shorter by them.
    # page.lines names the exact rows of a page, for printed-sheet shapes.
    # Zero fills the page height.
    # The row pitch is line_h plus ROW_GAP. A division by line_h alone lets a
    # full page overshoot page.code_height by one gap per row.
    per_page = (PAGE_LINES if PAGE_LINES
                else max(4, (CAP_H - 2 * PAD) // (line_h + ROW_GAP) - len(scheme)))
    # The rows spread evenly over the pages they need, not greedily onto the
    # first. A greedy fill puts per_page rows on page one and the rest on
    # page two. The sheet that pairs the two is as tall as its tallest page,
    # and a short page two then costs a full height column of white. An even
    # split never exceeds per_page, and the height cap still holds.
    page_count = max(1, -(-len(rows) // per_page))
    per_page = max(1, -(-len(rows) // page_count))
    pages = [rows[k:k + per_page] for k in range(0, len(rows), per_page)]
    n = 0
    page_imgs = []
    # Page one holds the key row. The band tints, the marks and the wrap edge
    # render as themselves, and the model names them without the session
    # card.
    _set_key_stats(text, pairs, pages, (line_h + ROW_GAP) * (_UNI_R if UNIFORM else 1.0))
    legend_w = legend_width(font)
    # The height of the last wrap mark rendered. One process always has it
    # when a row needs it. Only a helper's unsaved first page can lack it.
    wy0 = wy1 = None
    for page_i, chunk in enumerate(pages):
        # A render helper of pack_planned() renders only its own sheets. The
        # layout above is for the whole file. Each page that the helper
        # renders is then the page that one process renders. It also renders
        # the page before its first, unsaved. A row that continues a wrapped
        # line takes the height of its left wrap mark from the row before it.
        # For the first row of a page, that is the last row of the page
        # before. UNIFORM renders no left wrap mark, and each row sets the
        # height of its own right mark. The helper then renders no page
        # before its first.
        warm = False
        if _DRAW_SHEETS is not None:
            first_page = _DRAW_SHEETS[0] * COLUMNS
            if (page_i < first_page - (0 if UNIFORM else 1)
                    or page_i // COLUMNS >= _DRAW_SHEETS[1]):
                page_imgs.append(None)
                continue
            warm = page_i < first_page
        # The same picks and renderer as the render step. Otherwise the count
        # differs, and the page loses the last row.
        head_h = ((line_h + ROW_GAP) * _legend_count(font, max_w, face_for, renderer)
                  if page_i == 0 else 0)
        # A row with a blank line run ends a paragraph, and
        # space.paragraph_gap is the white that follows it. Zero ships.
        # This code checks PARA_GAP first. At zero, which ships, the
        # per-character count test cannot change a row's extra, and it runs
        # for each row of each trial of the width search.
        extras = [PARA_GAP if PARA_GAP and any(_is_count(pairs[j])
                                               for j in range(a, b)) else 0
                  for (a, b) in chunk]
        height = (2 * PAD + head_h
                  + len(chunk) * (line_h + ROW_GAP) + sum(extras))
        if _FILL_PASS and _FILL_STRETCH:
            # The stretched pitch needs the canvas to grow with it. Otherwise
            # the canvas clips the rows past the old height, and the page
            # loses the last rows of a file.
            height = int(height + (len(chunk) + 1) * (line_h + ROW_GAP) * (_FILL_STRETCH - 1.0)) + 1
        width = int(2 * PAD + max_w) + PAGE_EXTRA
        if UNIFORM and _FIXED_R and _IMG_W:
            width = int(_IMG_W / _FIXED_R)
        # The slack row added below, in the big space. A plan page can then
        # get its price without it. See save_page().
        slack_big = 0
        # On the shrunk page, each row snaps to the shrink grid and moves down
        # a little. The last band then runs past this height, and the page
        # cuts it before the white padding to a 28 px step. The height follows
        # the snapped pitch and keeps the band's own bottom pad.
        if DIRECT_CANVAS and (SHRINK_TO or (SHRINK_BY and SHRINK_BY > 1)) and renderer == "freetype":
            ratio = (float(SHRINK_TO) / width) if SHRINK_TO else 1.0 / float(SHRINK_BY)
            pitch = line_h + ROW_GAP
            snapped = round(pitch * ratio) / ratio
            height = int(height + (len(chunk) + 1) * max(0.0, snapped - pitch)
                         + BAND_PAD_Y + ROW_GAP + 1 / ratio) + 1
            # ONE ROW OF SLACK. The snapped height above can still leave the
            # last band short. The drift of a row as it snaps is not a fixed
            # amount, and no closed formula for it holds for each file. One
            # whole row pitch covers it.
            #
            # IT IS FREE. save_page() calls trim_to_ink(), which cuts the page
            # to its last ink row plus TRIM_MARGIN, rounded up to whole 28 px
            # patches. The slack row is white under the last ink, and the trim
            # removes it. A plan page does not count it in its price, through
            # slack_big. See save_page(). PAGE_TRIM above narrows the width
            # only.
            height += pitch
            slack_big = pitch
        if PAGE_TRIM and chunk:
            # The widest row on this page, plus the room for the right edge
            # and wrap edge of its last block. Never wider than before.
            widest = max(_wsum(a, b) for a, b in chunk)
            if not (UNIFORM and SHRINK_TO):
                width = min(width, int(2 * PAD + widest + EDGE_INSET + 2 + BAND_PAD_X + BAND_INSET + MARK_CLEAR + WRAP_W))  # room for the wrap bar
            if head_h:
                # A trimmed page one never cuts the key row.
                width = max(width, int(2 * PAD + min(legend_w, max_w) + 2))
        if DIRECT_CANVAS and (SHRINK_TO or (SHRINK_BY and SHRINK_BY > 1)) and renderer == "freetype":
            # The page renders at its final size. See Shrunk above.
            img = Shrunk(width, height, SHRINK_TO, SHRINK_BY, pixels=not _NO_PIXELS)
            d = _NullDraw(img) if _NO_PIXELS else img.drawer()
            if isinstance(img.im, _PlanPage):
                img.im.slack = int(slack_big * img.ratio)
        else:
            img = Image.new("RGB", (width, height), BACKGROUND)
            d = ImageDraw.Draw(img)
        # Each row lands on a whole page pixel. A row pitch in the big space
        # that is not a whole number of page pixels makes rows drift. The
        # white between two rows then reads 1 px on one pair and 3 px on the
        # next. This code snaps the pitch and the starting rows to the shrink,
        # and each gap is then the same.
        snap = (lambda v: round(v * img.ratio) / img.ratio) if isinstance(img, Shrunk) else (lambda v: v)
        # During a fill pass, the pitch stays fractional. The rows then spread
        # over the page's height exactly, and the gaps differ by one pixel at
        # most. See _fill_bottom.
        pitch = (line_h + ROW_GAP) * (_FILL_STRETCH or 1.0) if _FILL_PASS else snap(line_h + ROW_GAP)
        y = snap(PAD)
        if head_h:
            # A plan skips the render of the key row. y only places what
            # renders, and the page height above already holds the row.
            if not _NO_PIXELS:
                y += legend_row(d, font, PAD, y, line_h, max_w, face_for, renderer, img, up)
            y = snap(y)
        page_rows = []
        page_chars = []
        # One page pixel, in the layout columns that all code below measures
        # in. The band edge and the mark box each keep one of these.
        bw = int(round(1 / img.ratio)) if isinstance(img, Shrunk) else 1
        # An ImageDraw.Draw on the page's own pixels, for the mark box. This code
        # fits the mark box to the digits after they render.
        small = (None if _NO_PIXELS
                 else ImageDraw.Draw(img.im if isinstance(img, Shrunk) else img))
        for row_n, (a, b) in enumerate(chunk):
            page_rows.append((y, line_h, a, b))
            # One outlined block per line segment inside this row. The
            # outline marks the line break.
            x = float(PAD) + (ROW_LEFT / _UNI_R if UNIFORM else 0.0)
            k = a
            # The marks of a line break, the pilcrow, its count, the indent
            # mark and its number, get one black box as a unit. Inside a long
            # print line, they read as content when the band runs through
            # them. The run crosses the segment edge, because the pilcrow
            # ends the segment of one line and the indent mark starts the
            # segment of the next.
            mark_runs = []
            mark_splits = []          # where a run changes ink
            # The band's own top and bottom for this row, in layout space.
            # Each band on a row shares one y, and the first band rendered
            # sets it.
            band_y = None
            run_ink = None
            run_start = None          # the run's leftmost inked column
            run_end = None            # its rightmost
            run_top = None            # its highest inked row
            run_bot = None            # its lowest
            while k < b:
                seg = min(b, seg_end[k])
                seg_w = _wsum(k, seg)
                gap_here = GAP if pairs[seg - 1][0] == NL_MARK else 0
                # With the mark outside, the band stops one pixel before the
                # pilcrow's own column. The pilcrow keeps its place.
                if PILCROW_OUTSIDE and pairs[seg - 1][0] == NL_MARK and seg - k > 1:
                    # The band ends past the last character's ink, not a cell
                    # width past it. A cell is wider than the ink inside it,
                    # and the tint then runs under the number box of the next
                    # line. This moves the band's right edge only. The band's
                    # height stays the same.
                    m = seg - 1
                    tail = 0.0
                    while m > k and (spans[m] is None
                                     or pairs[m][0] == NL_MARK):
                        tail += widths[m]
                        m -= 1
                    if spans[m] is None:
                        # A segment of only spaces has no ink, and the band
                        # ends at the step from the cell widths.
                        gap_here = (widths[seg - 1] - EDGE_INSET + MARK_CLEAR
                                    + BAND_PAD_X + BAND_INSET)
                    else:
                        # THE SAME PAPER ON THE TWO SIDES. The glyphs start a
                        # whole BAND_INSET in from the band's left edge. The
                        # trail on the right is then BAND_INSET plus a
                        # measured step. A one pixel trail leaves the band
                        # flush against the last character's ink.
                        #
                        # THE TRAIL IS BAND_INSET + 2. A measure over each
                        # unwrapped band on a page set the step. It does not
                        # count the wrap mark's own columns, because that mark
                        # renders at the band's right edge on purpose. With
                        # the marks at font.mark_px, +2 balances the paper
                        # left and right. +1 leaves the right about one page
                        # pixel tighter, and +0 leans further. A LARGER trail
                        # moves the band's right edge further out, which is
                        # the opposite of how the expression reads. The page
                        # size is the same at each of these values.
                        #
                        # The clamp below still sets the other end. Where the
                        # number box of the next line is too close to give
                        # this much, the band takes the room that is there.
                        gap_here = (BAND_PAD_X + tail + widths[m]
                                    - shifts[m] - spans[m][1]
                                    - (BAND_INSET + 2) * bw)
                        # The band never reaches so far right that it touches
                        # the box of the next line number. That box's left
                        # line lands two page pixels left of the first digit's
                        # ink. The band stops two further left again, and one
                        # page pixel of white stays between them. It never
                        # cuts its own last character. The ink rule above is
                        # the floor.
                        if (seg < len(pairs) and _is_count(pairs[seg])
                                and spans[seg] is not None):
                            gap_here = min(
                                max(gap_here,
                                    BAND_PAD_X - spans[seg][0] + 4 * bw),
                                BAND_PAD_X + tail + widths[m]
                                - shifts[m] - spans[m][1])
                if _NO_PIXELS:
                    # A plan's trial. Only the band renders, and nothing below
                    # reads it except the lone mark test, which the left wrap
                    # mark uses.
                    lone_mark = PILCROW_OUTSIDE and _all_marks(k, seg)
                else:
                    # A blank-line count and its mark, "3" and the bullet,
                    # start the block after a blank run. They belong with the
                    # line break, between the bands, and the band starts after
                    # them.
                    lead_w = 0
                    lead_end = k
                    if PILCROW_OUTSIDE:
                        j0 = k
                        # The blank line square starts the lead. It sits
                        # between the bands, before the line number.
                        while j0 < seg and (_is_count(pairs[j0]) or _is_gap(pairs[j0])):
                            j0 += 1
                        if k < j0 < seg:
                            lead_w = _wsum(k, j0)
                            lead_end = j0
                    # The line's own placement moves its band and its glyphs
                    # together. The band's own placement moves and grows the
                    # band alone. The two are zero unless layout.placements
                    # sets them.
                    if PLACEMENTS:
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
                    else:
                        # No placements. Each lookup above returns 0, which
                        # ships. Two keys and eight lookups per segment cost a
                        # real share of a plan.
                        ldx = ldy = bdx = bdy = 0
                        g_l, g_r, g_t, g_b = BAND_GROW[0], BAND_GROW[1], BAND_GROW[2], BAND_GROW[3]
                    # The lead is the counts and the blank line square at the
                    # start of the segment. With a lead, the band starts at
                    # x + lead_w + BOX_CLEAR. With no lead, it starts at x.
                    # The branch below moves it to a fixed step past the ink
                    # of the lead digits, and UNIFORM sets it from the page
                    # span of the first ink after the lead.
                    bx0 = x + lead_w + (BOX_CLEAR if lead_w else 0) + BAND_OFF_X + bdx - g_l
                    if lead_w and spans[lead_end - 1] is not None:
                        # The band starts one page pixel of white past the box
                        # of the lead digits. The order is their last ink, the
                        # white, the box's own line, the white, the band.
                        m2 = lead_end - 1
                        # The band starts a fixed step past the number ink.
                        # Nothing pulls it back. A clamp that keeps the band
                        # off the first character is the wrong fix. With a
                        # character close to its number, the clamp wins, the
                        # band starts on the box line, and the white on the
                        # right of the box goes to 0. Do not widen the cell
                        # either. That works and costs a patch of page height.
                        # Band overlap only puts the left edge of a character
                        # on white in place of tint.
                        start = (x + lead_w - widths[m2] + shifts[m2]
                                 + spans[m2][1] + BAND_AFTER_BOX_PX * bw)
                        bx0 = start + BAND_OFF_X + bdx - g_l
                    by0 = y - BAND_PAD_Y + BAND_OFF_Y_ROW + bdy - g_t
                    bx1 = (x + seg_w - gap_here + BAND_PAD_X + BAND_OFF_X
                           + bdx + g_r + BAND_INSET)
                    by1 = (y + line_h - 1 - BAND_GAP_Y + BAND_PAD_Y
                           + BAND_OFF_Y_ROW + bdy + g_b)
                    # A block of one narrow mark and its pilcrow, or a shrunk
                    # band, can put the right edge left of the left one.
                    # Pillow rejects that, and the band is then at least one
                    # pixel wide.
                    if UNIFORM and face_for is not None:
                        _r = img.ratio if isinstance(img, Shrunk) else 1.0
                        _ink = []
                        for _j in range(lead_end, seg):
                            if pairs[_j][0] == NL_MARK:
                                continue
                            _sp = _page_span(face_for(pairs[_j][0], pairs[_j][2])[0], pairs[_j][0])
                            if _sp is not None:
                                _ink.append((_j, _sp))
                        if _ink:
                            (_j0, _s0), (_j1, _s1) = _ink[0], _ink[-1]
                            _c0 = _round_px((x + BAND_INSET + _wsum(k, _j0)) * _r)
                            _c1 = _round_px((x + BAND_INSET + _wsum(k, _j1)) * _r)
                            bx0 = (_c0 + _s0[0] - W_BAND) / _r
                            bx1 = (_c1 + _s1[1] + W_BAND) / _r
                    bx1 = max(bx1, bx0)
                    by1 = max(by1, by0)
                    # A block of only marks gets no band. A block of a line
                    # number and its break has no lead to start the band
                    # after. The tint then fills the number's own box, and the
                    # white around the digits goes.
                    lone_mark = PILCROW_OUTSIDE and _all_marks(k, seg)
                    # A file indented with spaces shows no band. Its red count
                    # gives the depth. A trial page of the width search
                    # renders no glyph, and save_page() trims it to its last
                    # colored row. The bands then still render there. Without
                    # them, the trial page trims to the key, each width gets
                    # too low a price, and a file can cost far more tokens,
                    # such as 974 in place of 866.
                    tint = (ONE_BAND_TINT if _ONE_BAND
                            else None if (_NO_BANDS and not _NO_GLYPHS)
                            else band_index(depths[min(ids[k], len(depths) - 1)]))
                    if not lone_mark and tint is not None:
                        d.rectangle([bx0, by0, bx1, by1],
                                    fill=TINTS[tint],
                                    outline=OUTLINE if OUTLINE_W else None, width=OUTLINE_W)
                        if band_y is None:
                            band_y = (by0, by1)
                # A source line that runs past the row edge continues at the
                # left of the next row. The edge where the line wraps renders
                # in WRAP_INK. The model then sees where a line wraps and does
                # not need to notice a missing mark. It moves no glyph and
                # costs no patch.
                if seg == b and pairs[seg - 1][0] != NL_MARK:
                    # At the band's own right edge, past the inset and the
                    # pad. The last letter then keeps its clear columns.
                    # The wave is inset from the BAND's own top and foot by
                    # the same rows that the text keeps, not from y. The band
                    # starts at y + BAND_OFF_Y. An inset from y then cancels
                    # against band.offset_y and puts the mark flush on the two
                    # band edges, where it reads as an overlap with the bands
                    # above and below.
                    wy0 = y + BAND_OFF_Y_ROW + BAND_TEXT_CLEAR
                    wy1 = y + line_h - 1 - BAND_GAP_Y + BAND_OFF_Y_ROW - BAND_TEXT_CLEAR
                    # This code places the mark PAST the last character of the
                    # row, and it must stay there. wrap_edge() already moves
                    # it left when it does not fit the page. That move puts it
                    # on top of text, and no model can read through it.
                    #
                    # Two things keep it off the text. WRAP_GUTTER reserves
                    # the width that the mark needs. _fit_width() rejects any
                    # layout that moves a mark at all, counted in CLAMP_HITS.
                    wx = x + seg_w - gap_here + BAND_PAD_X + BAND_INSET + MARK_CLEAR
                    # THE MARK CLEARS THE LAST GLYPH'S INK, not the sum of the
                    # advances.
                    #
                    # The line above places the mark past where the row's
                    # widths say it ends. A glyph whose ink fills its own
                    # advance, as w, e, ] and / do, then inks right up to that
                    # point, and the wave lands on it. Runs such as
                    # "format(row" and 'sides["off"]' then get no clear column.
                    #
                    # spans[j] is a glyph's inked columns counted from its own
                    # pen. The last glyph's ink then ends at its pen plus
                    # spans[-1][1]. The mark takes whichever is further right,
                    # that ink plus its clearance or the advance-based place
                    # above. A row that already has room then does not move,
                    # and the page does not grow.
                    #
                    # A HIGHER mark.clear COSTS MORE AND DOES NOT WORK. It
                    # moves each mark, not only the ones that touch. It makes
                    # a bigger page and still leaves a mark that touches.
                    if spans is not None and seg - 1 < len(spans) and spans[seg - 1]:
                        pen_last = (x + BAND_INSET + seg_w - gap_here
                                    - widths[seg - 1])
                        ink_right = pen_last + spans[seg - 1][1]
                        wx = max(wx, ink_right + WRAP_W + WRAP_INK_CLEAR)
                    if UNIFORM and face_for is not None:
                        _r = img.ratio if isinstance(img, Shrunk) else 1.0
                        for _j in range(seg - 1, k - 1, -1):
                            if pairs[_j][0] == NL_MARK:
                                continue
                            _sp = _page_span(face_for(pairs[_j][0], pairs[_j][2])[0], pairs[_j][0])
                            if _sp is not None:
                                _c = _round_px((x + BAND_INSET + _wsum(k, _j)) * _r)
                                wx = (_c + _sp[1] + (0 if _NO_BANDS else W_BAND) + W_BOX + 2) / _r
                                break
                    wrap_edge(d, wx, wy0, wy1)
                # The same line mark goes on the right only. This left one
                # renders off the page's left edge, and no page shows it. With
                # the rows moved in by ROW_LEFT, it lands on the page, and
                # UNIFORM does not render it. The call stays for the old
                # spacing, where it still lands off the page.
                if (not UNIFORM and k == a and a > 0 and pairs[a - 1][0] != NL_MARK
                        and not lone_mark and wy0 is not None):
                    wrap_edge(d, x - EDGE_INSET, wy0, wy1)
                cx = x + BAND_INSET
                # A glyphless trial with no layout record keeps nothing that
                # this loop makes. It renders no glyph, it boxes no mark
                # (found is None below), and x moves by seg_w after it. This
                # loop was most of the cost of a search trial, and the trial
                # skips it. The debug print of mark runs still needs the loop.
                for j in (() if _SKIP_CHARS else range(k, seg)):
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
                    # The marks between bands sit in their own white. The
                    # pilcrow sits EDGE_INSET columns right of its column, and
                    # a blank-line count EDGE_INSET columns left of its own.
                    # The advance does not change, and the row does not move.
                    mx = 0
                    if PILCROW_OUTSIDE:
                        if j == seg - 1 and pairs[j][0] == NL_MARK and seg - k > 1:
                            mx = EDGE_INSET
                        elif j < lead_end:
                            mx = 0 if (_NO_BANDS or UNIFORM) else -BAND_INSET
                    if mx:
                        cx += mx
                    if layout is not None:
                        page_chars.append((j, cx, jy, widths[j]))
                    # An INK_STEP mark renders its glyph left of its origin,
                    # and its ink starts CLEAR columns in. See char_widths().
                    sx = shifts[j]
                    if sx:
                        cx += sx
                    # The line end mark has no ink, and it opens no box. A run
                    # that starts at it begins one blank column left of the
                    # number, and its trail pulls the right edge onto the last
                    # digit. The mark never renders by design, and this test
                    # says so directly and does not ask a style override.
                    is_mark = _is_count(pairs[j])
                    if is_mark:
                        # A space between the pilcrow and the indent mark stays
                        # inside the one box. The box ends at the last mark's
                        # ink, not at the clear space after it. It then never
                        # reaches the band of the next word.
                        # The run is the ink itself, not the cells around it.
                        # A digit's cell runs its own adv past its ink. A box
                        # on the cells then leaves more white on the right of
                        # the digits than on their left, and no clearance
                        # setting reaches it.
                        sp = spans[j]
                        # The key holds the face itself, not id(jf). Python
                        # reuses the id of a freed face, and a new face then
                        # reads an old face's box.
                        _bk = (jf, pairs[j][0])
                        gb = _BBOX_CACHE.get(_bk)
                        if gb is None:
                            gb = jf.getbbox(drawn(pairs[j][0]))
                            _BBOX_CACHE[_bk] = gb
                        ix0 = cx + (sp[0] if sp else 0)
                        ix1 = cx + (sp[1] if sp else widths[j])
                        iy0, iy1 = jy + gb[1], jy + gb[3] - 1
                        if run_start is not None and j > 0 and _box_ends(pairs, j - 1):
                            # "1\n" closes its own box before the line number.
                            mark_runs.append((run_start, run_end, run_top, run_bot))
                            run_start = None
                        if run_start is None:
                            run_start, run_end = ix0, ix1
                            run_top, run_bot = iy0, iy1
                            run_ink = pairs[j][1]
                        else:
                            if not _one_box_ink(pairs[j][1], run_ink):
                                # The green line number ends, and the red
                                # indent count starts. Mark the seam.
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
                        # THE LINE END MARK NEVER RENDERS. It keeps its width
                        # and its line id. The page then does not move, and
                        # this code asks for no glyph. The mark stays in the
                        # stream because it holds the band, the row break
                        # rule, the band edge and the line id. The model does
                        # not see it as a character.
                        cx += widths[j]
                        continue
                    if _is_gap(pairs[j]):
                        # THE BLANK LINE SQUARE, a filled rectangle as tall
                        # as the band on this row and half as wide. It lands
                        # on the page pixel from the widths, the same column
                        # rule that the band edges use.
                        if not _NO_PIXELS:
                            if UNIFORM and face_for is not None:
                                _r = img.ratio if isinstance(img, Shrunk) else 1.0
                                _c = _round_px((x + BAND_INSET + _wsum(k, j)) * _r)
                                gx0, gx1 = _c / _r, (_c + _GAP_W - 1) / _r
                            else:
                                gx0 = cx
                                gx1 = cx + _gap_span()[1]
                            d.rectangle([gx0, by0, gx1, by1], fill=GAP_INK)
                        cx += widths[j] - gx - mx - sx
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
            if _DEBUG_RUNS:
                sys.stderr.write("row %d runs %s\n" % (row_n, [(round(a0), round(a1)) for a0, a1, _t, _b in mark_runs]))
            # CENTERED BOXES. Each box of marks moves sideways until the white on
            # its left equals the white on its right. See _center_boxes().
            box_dx = ({} if _NO_GLYPHS or _NO_BANDS
                      else _center_boxes(img, mark_runs, bw))
            for rx0, rx1, ry0, ry1 in mark_runs:
                # One page pixel of white sits between the outline and the
                # digits on all four sides. The run's own layout extent is only
                # the window where this code looks for the digits. The outline
                # comes from the pixels that the digits rendered.
                # A trial that renders no glyphs has no digits to fit a box to,
                # and nothing reads its boxes.
                found = None if _NO_GLYPHS else _ink_bounds(
                    img, (rx0 - 2 * bw, ry0 - 2 * bw, rx1 + 2 * bw, ry1 + 2 * bw))
                if found is None:
                    continue
                ix0, iy0, ix1, iy1 = found
                # WITH mark.box_fits_band OFF, ALL FOUR SIDES COME FROM THE
                # INK. The digits then sit centered in their box with the same
                # white on each side.
                #
                # A top and bottom from the BAND make the box exactly as tall
                # as the band. The box then touches the band's top and bottom
                # edges, and the digits, which have no descender, sit high
                # inside it. Neighboring boxes then touch each other and the
                # band.
                #
                # The boxes stay level. Each box on the page holds digits, and
                # all digits ink the same rows. A box fitted to its own ink
                # then lands at the same height as its neighbors.
                #
                # mark.box_fits_band takes top and bottom from the band
                # instead, and style.py ships it on.
                if band_y is None or BOX_FITS_INK:
                    top, bot = iy0 - 2, iy1 + 2
                else:
                    top = (img._out(band_y[0]) if isinstance(img, Shrunk)
                           else int(round(band_y[0])))
                    bot = (img._out(band_y[1]) if isinstance(img, Shrunk)
                           else int(round(band_y[1])))
                _target = img.im if isinstance(img, Shrunk) else img
                dx = box_dx.get((rx0, rx1, ry0, ry1), 0)
                if dx:
                    # The digits and each mark inside the box move with it.
                    _shift_box(_target, (ix0 - 1, top + 1, ix1 + 2, bot), dx)
                    ix0, ix1 = ix0 + dx, ix1 + dx
                _whiten_box(_target, (ix0 - 1, top + 1, ix1 + 2, bot))
                # Only the indent's part of the box turns solid. A line number
                # and its indent share one box, split by the seam, and the
                # line number stays green on white.
                left = ix0 - 1
                seams = {}
                for sx_split in mark_splits:
                    if rx0 < sx_split < rx1:
                        seam_x = (img._out(sx_split) if isinstance(img, Shrunk)
                                  else int(round(sx_split)))
                        # Found once, before the fill changes the pixels.
                        seams[sx_split] = _seam_column(img, (ix0, iy0, ix1, iy1), seam_x + dx)
                        left = seams[sx_split] + 1
                if not UNIFORM and _is_indent_box(_target, (left, top + 1, ix1 + 2, bot)):
                    _invert_box(_target, (left, top, ix1 + 3, bot + 1))
                small.rectangle([ix0 - 2, top, ix1 + 2, bot],
                                outline=MARK_BOX_INK, width=1)
                for sx_split in mark_splits:
                    if rx0 < sx_split < rx1:
                        sxs = (img._out(sx_split) if isinstance(img, Shrunk)
                               else int(round(sx_split)))
                        sxs = seams.get(sx_split, None)
                        if sxs is None:
                            sxs = _seam_column(img, (ix0, iy0, ix1, iy1),
                                               (img._out(sx_split) if isinstance(img, Shrunk)
                                                else int(round(sx_split))) + dx)
                        small.rectangle([sxs, top, sxs, bot],
                                        fill=MARK_BOX_INK)
            y += pitch + snap(extras[row_n])
        page_imgs.append(None if warm
                         else img.im if isinstance(img, Shrunk) else img)
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

    def opens_on(k):
        # The first line that STARTS on this image. A first row that
        # continues the line before holds only the end of that line.
        if not pages[k]:
            return None
        a = pages[k][0][0]
        return bisect.bisect_left(line_ends, a) + (1 if a and pairs[a - 1][0] != NL_MARK else 0)

    # A sheet holds page.columns pages side by side, with a gray divider at
    # each seam. A Read returns one file, and two pages on one sheet cost one
    # Read turn in place of two. A sheet wider than dp.CAP_W ships its pages
    # apart. style.py ships page.columns at 1, and each page is then its own
    # sheet.
    global _PNG_JOBS
    _PNG_JOBS = []
    try:
        for s in range(0, len(page_imgs), COLUMNS):
            pair = page_imgs[s:s + COLUMNS]
            if pair[0] is None:
                continue
            sheet_w = sum(im.width for im in pair) + SHEET_GAP * (len(pair) - 1)
            sheet_h = max(im.height for im in pair)
            if len(pair) > 1 and sheet_w > dp.CAP_W:
                # A page wider than half the cap ships alone, and never as a sheet
                # that the API shrinks.
                for q, im in enumerate(pair):
                    n += 1
                    path = "%s-%d.png" % (out_stem, n)
                    written.append((path,) + save_page(im, path))
                    PAGE_FIRST_LINE[path] = opens_on(s + q)
                    if layout is not None:
                        layout["pages"][s + q]["sheet"] = n
                continue
            if _NO_PIXELS:
                # The sheet that a plan's trial saves. It has its size, and the
                # same name and start line as the rendered sheet below.
                sheet = _PlanPage(sheet_w, sheet_h,
                                  any(im.info.get("densepack_small") for im in pair))
                n += 1
                path = "%s-%d.png" % (out_stem, n)
                written.append((path,) + save_page(sheet, path))
                PAGE_FIRST_LINE[path] = opens_on(s)
                continue
            sheet = Image.new("RGB", (sheet_w, sheet_h), BACKGROUND)
            # A Shrunk page is already at its final size. The flag that tells
            # save_page so is on the page image, not on this new sheet. Without
            # it, the plain path shrinks the sheet a second time.
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
    finally:
        # The pages that the loop finished before an error still reach
        # their files, as each page did when the loop saved it at once.
        jobs, _PNG_JOBS = _PNG_JOBS, None
        _save_pngs(jobs)
    return written, int(max_w), line_h


# A fenced block whose fence line names python. Python blocks pack as banded
# images. Each other label, and no label, still leaves the block as text.
_PY_FENCE = re.compile(r"\A```[ \t]*(?:python|py)[ \t]*\r?\n(.*?)\n?```\Z",
                       re.S | re.I)


def python_body(block):
    """The source inside a fenced block, or None when the fence is not python."""
    hit = _PY_FENCE.match(block)
    return hit.group(1) if hit else None



# Rendered at SUPERSAMPLE times the size and shrunk. Each final pixel is the
# mean of several rendered ones. A stem then lands as one clean column, and
# the font's hints run at the larger size where they work. 1 renders at the
# final size.
# Each glyph lands on a whole output pixel and does not keep the sub-pixel
# remainder of its position. See Shrunk.paste.
SNAP_GLYPHS = bool(_S.get("page.snap_glyphs", True))
# The rasterizer renders a glyph at the size it lands at, not at the layout's
# size and then shrunk. See backend_text.
GLYPH_AT_FINAL_SIZE = bool(_S.get("page.glyph_at_final_size", True))
SUPERSAMPLE = int(_S.get("page.supersample", 1) or 1)
# Hamming keeps more one pixel stems than Box or Lanczos when a page shrinks by
# three, and Lanczos rings.
SHRINK_FILTER = {"box": Image.BOX, "bilinear": Image.BILINEAR, "hamming": Image.HAMMING,
                 "bicubic": Image.BICUBIC, "lanczos": Image.LANCZOS}.get(
    str(_S.get("page.supersample_filter", "hamming")).lower(), Image.HAMMING)


# freetype_glyph holds the limit. The Read gate then checks the same number
# without a load of this module.
MISSING_GLYPH_MAX = freetype_glyph.MISSING_GLYPH_MAX


class FontCannotDraw(ValueError):
    """The font has no glyph for too much of this text."""


_COVERS_MEMO = {}


def font_covers(text):
    """True when the font can render all but MISSING_GLYPH_MAX of the text.
    Kept per text. pack_code() asks for each trial of the width search, and
    the answer walks each character."""
    font = (_S.get("font.regular") or [""])[0]
    key = (hash(text), len(text), font)
    hit = _COVERS_MEMO.get(key)
    if hit is None:
        if len(_COVERS_MEMO) > 8:
            _COVERS_MEMO.clear()
        hit = _COVERS_MEMO[key] = freetype_glyph.font_covers(text, font)
    return hit


# The key of the width cache hashes each character of the flow on each trial.
# _flow_key fixes the flow, and this code then keeps its hash per flow.
_PAIRS_HASH = [None, None]
# Running count of count marks and line breaks, per flow. See _all_marks in
# _pack_code.
_MARK_COUNT = [None, None]
# The segment starts, segment ends and line breaks, per flow and widths. See
# seg_end in _pack_code.
_SEG_MEMO = [None, None]
# The line count of the key row, per file and font and width. See
# _legend_count.
_LEGEND_COUNT = {}
# scheme_for() per flow.
_SCHEME = [None, None]
# flow_depths() per flow.
_DEPTHS = [None, None]


def _pairs_hash(flow_key, pairs):
    if _PAIRS_HASH[0] != flow_key:
        _PAIRS_HASH[1] = hash(tuple((p[0], p[2] if len(p) > 2 else None) for p in pairs))
        _PAIRS_HASH[0] = flow_key
    return _PAIRS_HASH[1]


def pack_code(text, px, out_stem, python=True, legend=None, layout=None,
              reader=None, title=""):
    """Pack text as banded code pages named <out_stem>-1.png and up, at
    SUPERSAMPLE times the size, then shrink each page by that factor.
    title is the source file's name, rendered at the head of the key row.

    Raises FontCannotDraw when the font lacks glyphs for more than
    MISSING_GLYPH_MAX of the text. Each caller catches the error and sends
    the text in place of the image."""
    if not font_covers(text):
        raise FontCannotDraw("the font has no glyphs for %.0f%% of this text"
                             % (100 * freetype_glyph.missing_share(
                                 text, (_S.get("font.regular") or [""])[0])))
    global _LEGEND_TITLE, _TAB_KEY, _INNER_TAB_KEY, _SPACE_INDENT_KEY, _RUN_KEY, _BLANK_KEY, _NO_BANDS, SNAP_GLYPHS, _ONE_BAND
    _LEGEND_TITLE = str(title or "")
    # page.snap_glyphs is one setting for each model, not a lookup keyed by
    # model name. One page shape then reaches each model.
    SNAP_GLYPHS = bool(_S.get("page.snap_glyphs", True))
    # The page's own marks are private-use code points. A source's own
    # pilcrow, section sign or double dagger then renders as itself, and
    # build_flow's guard fires only on those code points.
    # The code page has its own numbers, page.code_* in style.py, for a wider
    # layout, a supersample and a final width. page.width and page.height are
    # the narrow prose page.
    # There is one code page shape, page.code_width wide, for each model and
    # each glyph size. A glyph size with a narrow grid renders many narrow
    # pages where the wide page renders one.
    fable = bool(_S.get("page.code_width"))
    if fable and _S.get("page.fill_bottom") and not _FILL_GUARD:
        # THE SEARCH PACKS ON A WORK STEM, IN MEMORY. Each trial packs on a
        # stem of its own and keeps its pages in _TRIAL_PAGES. It does not
        # encode them. No hook that lists the image folder can then give the
        # model a page that the search later rejects. Only the pages of the
        # winner go to the final names, at the end.
        global _TRIAL
        work = out_stem + ".draw"
        _TRIAL = True
        try:
            res = _fit_page_width(text, px, work, python, legend, layout,
                                  reader, title)
            # A plan needs the winner's layout and nothing on disk. The
            # winner is a glyphless trial in memory, and its page start
            # lines are already in PAGE_FIRST_LINE under its paths.
            if _PLAN_ONLY:
                return res
            out = _write_trial(res, out_stem)
        finally:
            _TRIAL = False
            _TRIAL_PAGES.clear()
            _GLYPHLESS.clear()
        _drop_stale_pages(work, [])
        _drop_stale_pages(out_stem, out[0])
        return out
    s = int(_S.get("page.code_supersample") or SUPERSAMPLE) if fable else SUPERSAMPLE
    # A big file gets a lower supersample. The tiers name the largest
    # supersample for a source up to that many characters, and 0 means no
    # limit.
    if fable:
        for limit, tier in (_S.get("page.code_supersample_tiers") or []):
            if not limit or len(text) <= int(limit):
                s = min(s, max(1, int(tier)))
                break
    final_w = int(_S["page.code_width"]) if fable else None
    layout_w = int(_S.get("page.code_layout_width") or 0) if fable else 0
    # glyph is the glyph size that the page ships at, the size after the
    # shrink from the layout to the final width. The key row does not name
    # it, and no code below reads it.
    glyph = round(px * final_w / layout_w) if (fable and layout_w and final_w) else px
    _LEGEND_TITLE = ("file=%s" % _LEGEND_TITLE).strip()
    # A file indented with tabs only names its tab marks in the key, and the
    # model then edits with tabs. See legend_parts().
    _TAB_KEY = any(line.startswith("\t") for line in text.split("\n"))
    _INNER_TAB_KEY = any("\t" in line.lstrip(" \t") for line in text.split("\n"))
    _SPACE_INDENT_KEY = any(line.startswith(" ") for line in text.split("\n"))
    _space_file = _SPACE_INDENT_KEY and not _TAB_KEY
    _NO_BANDS = _space_file and not UNIFORM
    # ONE SCHEME FOR TABS AND SPACES. A tab-indented file can get the one
    # band color too. Its blue tab count beside the line number then holds
    # the indent, as the red space count does in a space-indented file. A
    # model cannot always tell the pastel depth tints apart, and the tints
    # hold no count. By default, a tab-indented file renders its depth colors.
    # DENSEPACK_DEPTH_BANDS=0 gives it the one band color. A space-indented
    # file keeps the one band color.
    _tab_file = _TAB_KEY and not _SPACE_INDENT_KEY
    _ONE_BAND = ((_SPACE_INDENT_KEY or _TAB_KEY) and UNIFORM
                 and not (_tab_file and os.environ.get("DENSEPACK_DEPTH_BANDS", "1") != "0"))
    _RUN_KEY = any("  " in line.lstrip(" \t") or (line.endswith(" ") and line.strip())
                   for line in text.split("\n"))
    _BLANK_KEY = "" in (text[:-1] if text.endswith("\n") else text).split("\n")
    # A carriage return never reaches this function. build_flow raises an
    # error on one, and each caller reads its file with universal newlines.
    # A CRLF file then arrives here already converted to LF. The page does
    # not say which ending the file used, and a model writes the ending of
    # its own system. A CRLF file then rebuilds one byte short per line. Only
    # the script that reads the file, pointer.py or read_gate.py, knows the
    # ending, and this function cannot name it.
    if s <= 1 and not fable:
        return _pack_code(text, px, out_stem, python, legend, layout)
    # Each pixel count of the page grows by s. The shrunk page then keeps the
    # same padding, outline, wrap edge and gaps that it has at one times.
    # Without this, the glyphs sit on the band outlines after the shrink.
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
                         # the larger marks and the lifted token are pixels
                         # at the shipped size too
                         "BIGGER_PX", "LIFT_PX") if n in g]
    keep = {n: g[n] for n in names}
    grow = "BAND_GROW" in g and g["BAND_GROW"]
    for n in names:
        g[n] = keep[n] * s
    if UNIFORM:
        # UNIFORM WHITE renders the text where its steps say. The inset adds
        # a fraction of a page pixel between two lines on a row. The box of
        # the next line then lands 4 px further than the steps put it.
        g["BAND_INSET"] = 0
    if layout_w:
        # the page adds 4 px of outline outside PAGE_W, PAD and PAGE_EXTRA
        g["PAGE_W"] = float((layout_w - 4 - 2 * keep["PAD"] - keep["PAGE_EXTRA"]) * s)
        # The wide page has its own height cap, page.code_height at the
        # layout size, and one small file is then one page.
        if _S.get("page.code_height"):
            g["CAP_H"] = int(_S["page.code_height"]) * s
    if grow:
        g["BAND_GROW"] = tuple(v * s for v in grow)
    # A pick's size, nudge and spacing are pixels at the shipped size, and
    # the bold simulation's quarter pixel too. Each grows by s with the page.
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
    # save_page() already shrank each page to its final size.
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
    """What one result costs the model. That is its visual tokens, plus two
    per page.

    A page is ceil(w / 28) by ceil(h / 28) patches. The two per page are the
    Read turn that the page itself costs. A two page result then loses to a
    one page result of the same patch count.
    """
    return sum(-(-w // 28) * -(-h // 28) + 2 for _f, w, h in res[0])


def _drop_stale_pages(out_stem, pages):
    """Remove the page files that a losing trial left past the winner's last
    page.

    Each trial of _fit_page_width, _fit_width and _fill_bottom writes to the
    same stem. A trial that needs more pages than the winner leaves its extra
    pages on disk, where a model that names a page by number can get one.
    This function removes only the numbered page files of this stem. A sheet
    that the drop gate makes later has the name -all and is not one of them.
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


# THE PLAN. The model asks for each page of a file in one message, and it
# needs the page list before it reads. The layout alone sets where each page
# starts. That is build_flow, char_widths, flow_rows and the even split of
# rows over pages. No pixel of a glyph takes part. plan_pages() runs the
# width search with no glyph rendered and stops before the final pack.
# pack_planned() makes that final pack later from the plan. The search then
# runs once per file, and the pages are the pages that the search packs.
_PLAN_ONLY = False
_PLAN_RESULT = {}


def plan_pages(text, px, python=True, legend=None, layout=None, reader=None,
               title=""):
    """The page layout that pack_code() packs, with no glyph rendered and no
    file written. Returns {"width", "layout_width", "first_lines", "pages"}.
    first_lines holds the packed line that each page starts on, counted from
    0 the way PAGE_FIRST_LINE counts. Returns None when the code page is not
    in use or the search gave no plan. Raises FontCannotDraw like
    pack_code()."""
    global _PLAN_ONLY
    if not (_S.get("page.code_width") and _S.get("page.fill_bottom")):
        return None
    import tempfile
    import shutil
    if layout is None and legend is None:
        _start_helpers(text, px, python, reader, title)
    tmp = tempfile.mkdtemp(prefix="densepack-plan-")
    _PLAN_ONLY = True
    _PLAN_RESULT.clear()
    try:
        res = pack_code(text, px, str(Path(tmp) / "plan"), python, legend,
                        layout, reader, title)
    finally:
        _PLAN_ONLY = False
        shutil.rmtree(tmp, ignore_errors=True)
    if not res or not _PLAN_RESULT:
        _stop_helpers()
        return None
    firsts = [PAGE_FIRST_LINE.pop(str(p), None) for p, _w, _h in res[0]]
    if not firsts or not all(isinstance(k, int) for k in firsts):
        _stop_helpers()
        return None
    return {"width": int(_PLAN_RESULT["width"]),
            "layout_width": int(_PLAN_RESULT["layout_width"]),
            "first_lines": firsts, "pages": len(firsts)}


def pack_planned(text, px, out_stem, plan, python=True, legend=None,
                 layout=None, reader=None, title=""):
    """pack_code() run once from a plan_pages() plan, with no search. It sets
    the same two widths and guards as the search's own final pack, and the
    pages then match it byte for byte. A plan of one page, or no plan, runs
    pack_code() whole, because the fill pass of a one page file reads
    pixels."""
    global _FILL_GUARD, _WIDTH_GUARD
    if not plan or int(plan.get("pages") or 0) < 2:
        _stop_helpers()
        return pack_code(text, px, out_stem, python, legend, layout, reader,
                         title)
    keep_w = _S.get("page.code_width")
    keep_lw = _S.get("page.code_layout_width")
    _S["page.code_width"] = int(plan["width"])
    _S["page.code_layout_width"] = int(plan["layout_width"])
    CLAMP_HITS[0] = 0
    _FILL_GUARD = True
    _WIDTH_GUARD = True
    try:
        out = None
        if layout is None and legend is None:
            out = _draw_split(text, px, out_stem, plan, python, reader, title)
        if out is None:
            out = pack_code(text, px, out_stem, python, legend, layout,
                            reader, title)
    finally:
        _FILL_GUARD = False
        _WIDTH_GUARD = False
        _S["page.code_width"] = keep_w
        _S["page.code_layout_width"] = keep_lw
    _drop_stale_pages(out_stem, out[0])
    return out


# THE RENDER SPLIT, `_draw_split()`. The plan fixes each page before any
# pixel renders. Several processes can then render the sheets at once, each
# its own run of sheets, and the files are the files that one process
# writes. A helper must make the layout of the whole file again before its
# first page, a few seconds on a big file. plan_pages() then starts the
# helpers when it starts. Each helper makes the flow and the split table
# while the plan runs, then waits for the plan and renders its run. A file
# under DRAW_SPLIT_BYTES keeps one process, because the start of a helper
# costs more than it saves there.
DRAW_SPLIT_BYTES = 60_000
# About how many bytes of text fill a page, to size the helpers before the
# plan counts the pages.
BYTES_PER_PAGE = 6_000
_DRAW_SHEETS = None
_HELPERS = []
# True while a render helper packs before its plan. _pack_code() then stops
# after the flow and the split table. See _draw_child().
_WARM_FLOW = False
# (share, shares, folder) while this process packs its run of a split render.
# See _shared_widths().
_CW_SHARE = None


def _shared_widths(font, pairs, big_font, face_for, renderer, shifts, spans):
    """char_widths() for a split render, measured once across the processes.

    Each process of _draw_split() needs the widths of the whole file at the
    plan's scale. Each process measures one part, writes it to the shared
    folder, and reads the other parts. Under UNIFORM, the memo of
    char_widths() gives no answer, and a width reads the character before it
    only at a line break. A part that starts at a line start, after a line
    break and not on one, then gives the same values as the same part of the
    whole. This process measures a part itself when the part does not come
    within twice the time of its own part."""
    import pickle
    import time
    share, shares, folder = _CW_SHARE
    n = len(pairs)
    cuts = [0]
    for i in range(1, shares):
        c = max(cuts[-1], i * n // shares)
        while c < n and (pairs[c - 1][0] != NL_MARK or pairs[c][0] == NL_MARK):
            c += 1
        cuts.append(c)
    cuts.append(n)
    lids = [0]
    for i in range(1, shares):
        lids.append(lids[-1] + sum(1 for p in pairs[cuts[i - 1]:cuts[i]]
                                   if p[0] == NL_MARK))

    def measure(i):
        sh, sp = [], []
        w, d = char_widths(font, pairs, big_font, face_for, renderer=renderer,
                           shifts=sh, spans=sp, start=cuts[i],
                           stop=cuts[i + 1], lid=lids[i])
        return w, d, sh, sp

    def name(i):
        return os.path.join(folder, "w%d.pkl" % i)

    t0 = time.time()
    parts = {share: measure(share)}
    spent = time.time() - t0
    try:
        with open(name(share) + ".part", "wb") as fh:
            pickle.dump(parts[share], fh, pickle.HIGHEST_PROTOCOL)
        os.replace(name(share) + ".part", name(share))
    except OSError:
        pass
    t1 = time.time()
    while len(parts) < shares:
        for i in range(shares):
            if i not in parts and os.path.exists(name(i)):
                try:
                    with open(name(i), "rb") as fh:
                        parts[i] = pickle.load(fh)
                except (OSError, EOFError, pickle.UnpicklingError):
                    pass
        if len(parts) < shares:
            if time.time() - t1 > 2 * spent + 0.5:
                i = min(i for i in range(shares) if i not in parts)
                parts[i] = measure(i)
            else:
                time.sleep(0.01)
    widths, ids = [], []
    for i in range(shares):
        w, d, sh, sp = parts[i]
        widths.extend(w)
        ids.extend(d)
        shifts.extend(sh)
        spans.extend(sp)
    return widths, ids


def _stop_helpers():
    for rec in _HELPERS:
        p = rec["proc"]
        try:
            p.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.kill()
        except Exception:  # noqa: BLE001
            pass
    _HELPERS.clear()


def _start_helpers(text, px, python, reader, title):
    """Start the render helpers for text. They make its layout while the
    plan runs. Starts none for a small file, under DENSEPACK_SERIAL_DRAW or
    inside a helper."""
    import os
    import pickle
    import subprocess
    import tempfile
    _stop_helpers()
    size = len(text.encode("utf-8"))
    if (size < DRAW_SPLIT_BYTES or _DRAW_SHEETS is not None
            or os.environ.get("DENSEPACK_SERIAL_DRAW")):
        return
    sheets = -(-size // BYTES_PER_PAGE // COLUMNS)
    per_helper_mb = 60 + 0.9 * size / 1000
    workers = max(1, min(sheets // 2, os.cpu_count() or 1,
                         int(HELPER_MEMORY_MB // per_helper_mb)))
    here = os.path.dirname(os.path.abspath(__file__))
    job = {"text": text, "px": px, "python": python, "reader": reader,
           "title": title, "settings": dict(_S)}
    for _k in range(1, workers):
        fd, job_path = tempfile.mkstemp(prefix="densepack-pack-",
                                        suffix=".pkl")
        with os.fdopen(fd, "wb") as fh:
            pickle.dump(job, fh)
        code = ("import sys; sys.path.insert(0, %r); import codepack; "
                "codepack._draw_child(%r)" % (here, job_path))
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", code], cwd=here,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        except OSError:
            break
        _HELPERS.append({"proc": proc, "key": hash(text)})


def _draw_split(text, px, out_stem, plan, python, reader, title):
    """Render the planned sheets across the helpers that plan_pages()
    started. Returns what pack_code() returns, or None to render in this
    process alone."""
    import json
    import os
    import pickle
    import shutil
    import tempfile
    global _DRAW_SHEETS, _CW_SHARE
    helpers = [r for r in _HELPERS if r["key"] == hash(text)]
    if not helpers or _DRAW_SHEETS is not None:
        _stop_helpers()
        return None
    _HELPERS.clear()
    sheets = -(-int(plan["pages"]) // COLUMNS)
    folder = None
    if UNIFORM:
        # Under UNIFORM a helper renders no page before its first, and one
        # sheet is then worth a helper. Each helper made the split table
        # while the plan ran. This process makes it after the plan, and it
        # then takes the smallest share.
        workers = min(len(helpers) + 1, sheets)
        base, extra = divmod(sheets, workers)
        cuts = [k * base + max(0, k - (workers - extra))
                for k in range(workers + 1)]
        # The folder where the processes trade their parts of the widths.
        # See _shared_widths().
        try:
            folder = tempfile.mkdtemp(prefix="densepack-widths-")
        except OSError:
            folder = None
    else:
        workers = min(len(helpers) + 1, max(1, sheets // 2))
        cuts = [round(k * sheets / workers) for k in range(workers + 1)]
    used = []
    try:
        for k, rec in enumerate(helpers, 1):
            p = rec["proc"]
            if k >= workers:
                p.kill()
                continue
            fd, msg = tempfile.mkstemp(prefix="densepack-plan-",
                                       suffix=".pkl")
            with os.fdopen(fd, "wb") as fh:
                pickle.dump({"plan": plan, "stem": "%s.d%d" % (out_stem, k),
                             "sheets": (cuts[k], cuts[k + 1]),
                             "widths": (k, workers, folder) if folder else None}, fh)
            p.stdin.write((msg + "\n").encode("utf-8"))
            p.stdin.close()
            used.append((k, p))
        _DRAW_SHEETS = (cuts[0], cuts[1])
        _CW_SHARE = (0, workers, folder) if folder else None
        try:
            out = pack_code(text, px, out_stem, python, None, None, reader,
                            title)
        finally:
            _DRAW_SHEETS = None
            _CW_SHARE = None
        written = list(out[0])
        for _k, p in used:
            data, err = p.communicate()
            if p.returncode != 0:
                raise RuntimeError(err[-400:])
            for path, w, h in json.loads(data):
                final = "%s-%d.png" % (out_stem, len(written) + 1)
                os.replace(path, final)
                written.append((final, w, h))
        for rec in helpers[len(used):]:
            rec["proc"].communicate()
        firsts = plan["first_lines"]
        if len(written) != len(firsts):
            raise RuntimeError("split packed %d pages, plan has %d"
                               % (len(written), len(firsts)))
        for (path, _w, _h), first in zip(written, firsts):
            PAGE_FIRST_LINE[str(path)] = first
        return [written] + list(out[1:])
    except Exception:  # noqa: BLE001
        for rec in helpers:
            try:
                rec["proc"].kill()
            except Exception:  # noqa: BLE001
                pass
        for k, _p in used:
            for f in Path(out_stem).parent.glob(
                    Path(out_stem).name + ".d%d-*.png" % k):
                try:
                    f.unlink()
                except OSError:
                    pass
        return None
    finally:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)


def _draw_child(job_path):
    """One helper of _draw_split(). Makes the flow and the split table of the
    text in the pickled job at job_path, removes that file, and renders no
    glyph. They are then in memory when the plan comes. Then reads the path
    of the pickled plan on stdin, renders its run of sheets, and returns the
    pages it wrote as a JSON list on stdout. An empty stdin means that the
    plan has no sheets for it."""
    import json
    import os
    import pickle
    import shutil
    import tempfile
    global _DRAW_SHEETS, _PLAN_ONLY, _FILL_GUARD, _WIDTH_GUARD, _NO_GLYPHS, _WARM_FLOW, _CW_SHARE
    with open(job_path, "rb") as fh:
        job = pickle.load(fh)
    try:
        os.remove(job_path)
    except OSError:
        pass
    _S.clear()
    _S.update(job["settings"])
    tmp = tempfile.mkdtemp(prefix="densepack-warm-")
    _PLAN_ONLY = _FILL_GUARD = _WIDTH_GUARD = _NO_GLYPHS = _WARM_FLOW = True
    try:
        pack_code(job["text"], job["px"], str(Path(tmp) / "w"),
                  job["python"], None, None, job["reader"], job["title"])
    except Exception:  # noqa: BLE001
        pass
    finally:
        _PLAN_ONLY = _FILL_GUARD = _WIDTH_GUARD = _NO_GLYPHS = _WARM_FLOW = False
        shutil.rmtree(tmp, ignore_errors=True)
        PAGE_FIRST_LINE.clear()
    msg = sys.stdin.readline().strip()
    if not msg:
        return
    with open(msg, "rb") as fh:
        got = pickle.load(fh)
    try:
        os.remove(msg)
    except OSError:
        pass
    _DRAW_SHEETS = tuple(got["sheets"])
    _CW_SHARE = tuple(got["widths"]) if got.get("widths") else None
    out = pack_planned(job["text"], job["px"], got["stem"], got["plan"],
                       job["python"], None, None, job["reader"],
                       job["title"])
    sys.stdout.write(json.dumps([[str(p), w, h] for p, w, h in out[0]]))


def _fit_page_width(text, px, out_stem, python, legend, layout, reader, title):
    """Pack at each page width in page.code_width_choices, keep the cheapest.

    The search keeps the width that wastes the least. It grows a page down
    before it grows it sideways, and page.code_width_choices offers 756 px
    and 784 px.

    The downward growth comes first and inside each trial, because
    _fit_width() calls _fill_bottom() before it does anything else. Only
    after that runs at one width does this function compare it against the
    next width.

    The layout width moves with the page width on each trial and keeps the
    ratio that the settings ship. A wider page then packs proportionally more
    into a row and does not render the same row larger. The two shipped
    widths are whole 28 px patches, and neither adds a white column.

    Nothing scales after hinting at any ratio, because backend_text() asks
    FreeType for the glyph at the size it lands at. A layout width forced
    down to the page width costs far more tokens for the same file.

    A width wins on two counts in order. First the patch cost. Then how many
    wrap marks the pack moved onto the text, because a mark on a letter is a
    misread, and a misread costs output at five times input. A tie keeps the
    width already in the settings, which is the first in the list.

    When the winner was a glyphless trial, it renders once with glyphs at the
    end.
    """
    global _WIDTH_GUARD, _FILL_GUARD
    choices = [int(w) for w in (_S.get("page.code_width_choices") or ())]
    # A small command output searches each whole-patch width, set by
    # bash_image.py. The wide page is for long files, which models read
    # better wide. A few lines packed narrow fill their patches and waste
    # less.
    env_w = os.environ.get("DENSEPACK_WIDTH_CHOICES", "")
    if env_w:
        choices = [int(w) for w in env_w.split(",") if w.strip().isdigit()] or choices
    keep_w = _S.get("page.code_width")
    keep_lw = _S.get("page.code_layout_width")
    if _WIDTH_GUARD or not keep_w or not choices:
        return _fit_width(text, px, out_stem, python, legend, layout, reader,
                          title)
    # The search tries the width already set first, and a tie keeps it, but
    # only when the list names it. A list with 784 alone packs 784.
    if int(keep_w) in choices:
        choices.remove(int(keep_w))
        choices.insert(0, int(keep_w))

    best = None
    best_w = choices[0]
    best_clamp = best_cost = None
    layout_w = {}
    _WIDTH_GUARD = True
    # THE SEARCH RUNS WITH THE OLD SPACING. It picks the page width and the
    # layout width, and the layout width sets the size of each glyph. With
    # UNIFORM WHITE, it picks other widths, and each glyph changes. The search
    # then runs with the old spacing, and only the final pack takes the new
    # spacing.
    global UNIFORM
    uni = UNIFORM
    keep_env = os.environ.get("DENSEPACK_UNIFORM")
    if uni:
        UNIFORM = False
        os.environ["DENSEPACK_UNIFORM"] = "0"
        _CW_CACHE.clear()
    try:
        # The layout keeps the ratio that the settings ship. A wider page then
        # packs proportionally more into a row. A round to a whole column
        # keeps the layout arithmetic on integers.
        ratio = float(keep_lw) / float(keep_w) if keep_lw and keep_w else 1.0
        # Each glyphless trial that the two widths ask for, packed ahead at
        # once. That is the base layout of each width and its fifteen
        # widening steps. _fill_bottom() and _fit_width() take them from
        # _PREFETCH.
        native_only = os.environ.get("DENSEPACK_NATIVE_ONLY") == "1"
        jobs = []
        for width in choices:
            b = int(round(width * ratio))
            jobs.append((width, b))
            if not native_only:
                jobs.extend((width, lw) for lw in range(b + 4, b + 61, 4))
        _prefetch_trials(text, px, python, reader, title, out_stem, jobs)
        for width in choices:
            _S["page.code_width"] = width
            _S["page.code_layout_width"] = int(round(width * ratio))
            CLAMP_HITS[0] = 0
            # Each width packs on its own stem. Its pages and the pages of
            # the other width then never share a name in memory.
            trial = _fit_width(text, px, "%s.w%d" % (out_stem, width), python,
                               legend, layout, reader, title)
            layout_w[width] = _LAST_LAYOUT_W
            hits = CLAMP_HITS[0]
            cost = _page_cost(trial)
            # Native only. A width whose wrap marks land on letters is not a
            # candidate while any width without that remains.
            if native_only and hits:
                cost += 10 ** 6
            # Cost first, marks second. A mark moved onto a letter is a
            # misread, and a misread costs output at five times input. But a
            # larger page costs tokens on each page, which is the larger bill.
            # The clamp count then breaks the tie whenever two widths cost the
            # same.
            if best is None or cost < best_cost or (
                    cost == best_cost and hits < best_clamp):
                _forget(best)
                best, best_w, best_clamp, best_cost = trial, width, hits, cost
            else:
                _forget(trial)
        # When the winner was a glyphless trial, it renders once with glyphs.
        # That is a widening winner, or the base pack of a file of more than
        # one page. The fill pack of a one page file is already complete.
        # This is the one real render of the whole search.
        # A plan stops here. It records the two widths for the final pack,
        # and pack_planned() makes that same pack later.
        if _PLAN_ONLY:
            _PLAN_RESULT.clear()
            if best is not None:
                _PLAN_RESULT["width"] = best_w
                _PLAN_RESULT["layout_width"] = layout_w.get(best_w, int(round(best_w * ratio)))
            return best
        if uni:
            UNIFORM = True
            if keep_env is None:
                os.environ.pop("DENSEPACK_UNIFORM", None)
            else:
                os.environ["DENSEPACK_UNIFORM"] = keep_env
            _CW_CACHE.clear()
        if best is not None and uni:
            best = _uniform_draw(text, px, out_stem, python, legend, layout,
                                 reader, title, best, best_w,
                                 layout_w.get(best_w, int(round(best_w * ratio))))
        elif best is not None and str(best[0][0][0]) in _GLYPHLESS:
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
        if uni:
            UNIFORM = True
            if keep_env is None:
                os.environ.pop("DENSEPACK_UNIFORM", None)
            else:
                os.environ["DENSEPACK_UNIFORM"] = keep_env
        _WIDTH_GUARD = False
        _PREFETCH.clear()
        _S["page.code_width"] = keep_w
        _S["page.code_layout_width"] = keep_lw
    return best


def _uniform_draw(text, px, out_stem, python, legend, layout, reader, title,
                  old, page_w, layout_w):
    """The UNIFORM final pack. The old search picked page_w and layout_w,
    and with them the scale of each glyph. This function holds that scale
    fixed and packs each width in UNI_WIDTHS without glyphs. The cheapest
    then renders with glyphs. The glyphs are the old glyphs at each width,
    and the cost is never above the cost of the old pack."""
    global _FIXED_R, _IMG_W, _FILL_GUARD, _NO_GLYPHS, _TRIAL
    _S["page.code_width"] = page_w
    _S["page.code_layout_width"] = layout_w
    _forget(old)
    _FILL_GUARD = True
    try:
        # The scale from the old widths, read from one glyphless pack.
        _NO_GLYPHS = _TRIAL = True
        try:
            probe = pack_code(text, px, out_stem + ".u0", python, legend,
                              layout, reader, title)
        finally:
            _NO_GLYPHS = _TRIAL = False
        _forget(probe)
        _FIXED_R = _UNI_R
        # split_here() cuts rows differently after _FIXED_R and _IMG_W are
        # set.
        _SPLIT_MEMO[0] = _ROW_MEMO[0] = None
        best_w, best_cost = None, None
        for w in UNI_WIDTHS:
            _IMG_W = w
            CLAMP_HITS[0] = 0
            _NO_GLYPHS = _TRIAL = True
            try:
                trial = pack_code(text, px, "%s.u%d" % (out_stem, w), python,
                                  legend, layout, reader, title)
            finally:
                _NO_GLYPHS = _TRIAL = False
            cost = _page_cost(trial) + (10 ** 6 if CLAMP_HITS[0] else 0)
            _forget(trial)
            if best_cost is None or cost < best_cost:
                best_w, best_cost = w, cost
        # The cheapest width, plus DENSEPACK_UNI_EXTRA pixels (0 by default).
        _IMG_W = best_w + int(os.environ.get("DENSEPACK_UNI_EXTRA", "0"))
        CLAMP_HITS[0] = 0
        return pack_code(text, px, out_stem + ".final", python, legend,
                         layout, reader, title)
    finally:
        _FIXED_R = None
        _IMG_W = None
        _FILL_GUARD = False
        _SPLIT_MEMO[0] = _ROW_MEMO[0] = None


def _fit_width(text, px, out_stem, python, legend, layout, reader, title):
    """Pack, then try wider layouts and keep the page that costs least.

    _fill_bottom only narrows the layout, which grows the glyph to fill white
    space that the page already paid for. It never widens. Content that does
    not fit then takes another row or another page.

    A wider layout renders a smaller glyph and fits more characters per row.
    It then needs fewer rows. A page that the indent counts made taller then
    fits back inside fewer patches, at a slightly smaller glyph.
    """
    # The layout width of the page, one width for each model.
    base = int(_S.get("page.code_layout_width") or 0)

    def put(value):
        _S["page.code_layout_width"] = value

    global _LAST_LAYOUT_W
    _LAST_LAYOUT_W = base
    best = _fill_bottom(text, px, out_stem, python, legend, layout, reader,
                        title)
    if not base:
        return best

    # NATIVE LAYOUT. When the layout width already equals the page width,
    # there is nothing to search. Each width that this loop tries is WIDER
    # than the page. With a layout wider than the page, each glyph rasterizes
    # for one grid and resamples onto another. That resample softens each
    # letter. MacType does the opposite. It rasterizes a glyph at the size it
    # shows at, and its hinting lands on the real pixel grid.
    #
    # Nothing else is lost. The order of growth stays the same. More text still
    # takes more rows, then a taller page up to the height cap, then a new
    # page. The page width search across page.code_width_choices stays the
    # same, and its two widths stay exact multiples of 28.
    # ONLY WHEN NOTHING CLAMPS. The loop below keeps a wrap mark off the text.
    # It searches for a layout whose CLAMP_HITS is zero and prefers it over
    # one that costs a patch row less. Without the loop, marks render through
    # characters, and no model can read past them.
    #
    # A widened layout does restore the rescale that the native layout
    # removes. This code makes that trade only when a mark otherwise lands on
    # a letter. A misread costs output at five times input, which is more
    # than the sharper glyph saves.
    page_w = int(_S.get("page.code_width") or 0)
    if page_w and base <= page_w and not CLAMP_HITS[0]:
        return best
    # NATIVE ONLY, set by bash_image.py for a small output. A widened layout
    # resamples each glyph, and on a narrow page the resample is large. A 224
    # px page widened by 60 px renders the 17 px face near 13 px, and the t
    # can lose its crossbar and read as a 1. The width search in
    # _fit_page_width() drops any width that clamps.
    if os.environ.get("DENSEPACK_NATIVE_ONLY") == "1":
        return best

    cost = _page_cost

    global _FILL_GUARD
    low = cost(best)
    misses = 0
    lw = base
    # How many marks the first pack moved onto the text. A layout that moves
    # none is worth more than a layout that costs one patch row less, because
    # a mark on a letter is a misread, and a misread costs output at five
    # times input.
    best_clamp = CLAMP_HITS[0]
    best_lw = base
    try:
        # The guard keeps each trial from a new entry into _fill_bottom. That
        # entry narrows the layout back at once and fixes the height to the
        # first pack. These trials are the plain renderer at one width each.
        _FILL_GUARD = True
        # Stop at the FIRST width that wins back a patch row. The goal is to
        # fit the content into space that the page already pays for, not to
        # find the smallest page. A token minimum here moves the glyph size
        # down until the model starts to misread, and a misread costs output
        # at 5 times input, which is more than the page ever saves.
        global _NO_GLYPHS
        # The fifteen widening trials depend only on their own width. They
        # then pack at once in child processes, glyphless, and the walk below
        # reads them in width order with the rule unchanged. A child that
        # fails, or a wide burst, sends them through the loop one after
        # another.
        page_w_now = int(_S.get("page.code_width") or 0)

        def widen(lw):
            # Without this line, _NO_GLYPHS is a local copy, and each trial renders each letter.
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
            # COST FIRST, CLAMPED MARKS SECOND, the same rule as in
            # _fit_page_width. The second render in _fit_page_width keeps the
            # file and the returned sizes on the same page.
            if cost(trial) < low or (cost(trial) == low and hits < best_clamp):
                _forget(best)
                best, best_clamp, low, best_lw = trial, hits, cost(trial), lw
                if hits == 0:
                    break
            else:
                _forget(trial)
        # Each trial packs on its own stem into memory, and a widening trial
        # renders no glyphs. _fit_page_width() renders the one overall winner
        # with glyphs at the end, at the layout width recorded here. A width
        # that loses then never costs a real render.
        _LAST_LAYOUT_W = best_lw
    finally:
        _FILL_GUARD = False
        put(base)
    return best


# WHITE CAN STAY AT THE FOOT. The reason is the ORDER in which these three
# run, not anything inside _fill_bottom().
#
# _fit_width() calls _fill_bottom() FIRST and widens the layout after it. The
# fill then measures a page that gets a new layout after it. A margin that
# the fill measures can belong to a taller page than the one the model sees.
#
# TWO THINGS DO NOT SOLVE IT.
#
#   A larger glyph cannot fill it. line_h moves in whole pixels. The
#   smallest growth that changes anything costs one pixel on each row,
#   which is more page than the white it fills. Fractional sizes do
#   render. The size is not the obstacle. The quantum of the row pitch is.
#
#   White spread as row pitch through _FILL_STRETCH is the right setting,
#   and it works. A calculation here still corrects the wrong page, for the
#   reason of order above.
#
# Only a fill that runs LAST, after the width search in _fit_page_width()
# ends, measures the page that the model sees.


def _fill_bottom(text, px, out_stem, python, legend, layout, reader, title):
    """Grow the glyph from its floor until the page's foot margin equals its
    head margin, with the page the same height and one page.

    The floor page renders first. Its height pads to the 28 px patch step,
    and a band of white sits under the last row. The glyph then grows by the
    ratio of the space available to the space used. The row pitch stays
    fractional for that pass, and the rows spread over the page exactly.
    This function keeps the result when the page is still one page of the
    same height, with its last ink at least as far from the bottom edge as
    the first ink is from the top, and never more than three rows further.
    Up to 12 passes correct the ratio when the wrap points move. A file of
    more than one page keeps the floor."""
    global _FILL_GUARD, _FILL_PASS, _FILL_STRETCH, _NO_GLYPHS
    base = int(_S.get("page.code_layout_width") or 0)
    if not base:
        return pack_code(text, px, out_stem, python, legend, layout, reader, title)
    # NATIVE LAYOUT, the same guard as in _fit_width(). This function NARROWS
    # the layout to grow the glyph into white space at the foot of a page.
    # That also breaks the one to one mapping between layout space and page
    # space and puts the resample back. With the layout already at the page
    # width, the glyph renders at its true size, and the trade of this search
    # is not worth it.
    #
    # This code must set _FILL_GUARD around the pack exactly as the search
    # below sets it. pack_code() enters _fit_page_width() again whenever the
    # guard is clear, and that path leads back here. A return without the
    # guard recurses forever.
    page_w = int(_S.get("page.code_width") or 0)
    if page_w and base <= page_w:
        # A plan counts pages and clamped marks, and neither needs a glyph.
        # Without this, the branch renders each glyph of the file at each page
        # width only for its clamp count, which was most of the time of a
        # plan. The glyphless base that the helpers packed ahead is the same
        # layout.
        if _PLAN_ONLY:
            hit = _PREFETCH.pop((page_w, base), None)
            if hit is not None:
                res, CLAMP_HITS[0] = hit
                return res
            _FILL_GUARD = True
            _NO_GLYPHS = True
            try:
                return pack_code(text, px, out_stem, python, legend, layout,
                                 reader, title)
            finally:
                _FILL_GUARD = False
                _NO_GLYPHS = False
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
        # The first pack finds the page count without glyphs. A file of more
        # than one page keeps the floor and returns glyphless, because
        # nothing reads its pixels, and _fit_page_width() renders the winner
        # once with glyphs at the end. A one page file renders again with
        # glyphs, because the fill below measures its white. The top of this
        # function declares _NO_GLYPHS global.
        hit = _PREFETCH.pop((int(_S.get("page.code_width") or 0), base), None)
        if hit is not None:
            best, CLAMP_HITS[0] = hit
        else:
            _NO_GLYPHS = True
            try:
                best = pack_code(text, px, out_stem, python, legend, layout, reader, title)
            finally:
                _NO_GLYPHS = False
        # A plan needs only the page count and start lines, which this first
        # layout already holds. The growth passes below read pixels and run
        # only for a one page file, which needs no page list.
        if _PLAN_ONLY:
            return best
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

        # The ratio gives the first guess. The wrap points move with the
        # width. This code then moves the guess up in steps of two until the
        # page holds, then down until the foot margin drops under the head
        # margin, twelve packs at most.
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
        # This code now has the largest glyph. It spreads the white still left
        # under the last band over the rows as row spacing. The foot margin
        # then equals the head margin.
        foot = _bottom_white(best[0][0][0])
        stretch = None
        if foot > top + 4:
            # Three rows of slack. Otherwise the stretched canvas pads onto
            # the next patch row, and this code drops the pass.
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
                    # The stretch pushed the page over. Render the best
                    # without it. In the memory mode of the search, the best
                    # is still in memory, and this code needs no second render.
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
    """Pack the python blocks among fences as banded pages.

    Returns (pages, drawn), the page paths in order, as strings, and how
    many blocks packed. Each page holds the same #=N=# marker that the caller
    put in the report or brief where the block was. The model then matches a
    page with its hole. A block whose fence names anything else does not
    pack and stays in the caller's text file. Nothing here raises an error. A
    pack that fails returns no page, and the caller's text lift stands alone.
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
