"""All values the renderer uses, in one dict.

WHAT THIS FILE DOES. codepack.py, densepack.py and prompt_card.py get their
numbers and colors from this file. load() returns one flat dict. Without a
style.json on disk, a run uses the defaults below.

WHERE THE FILE IS. style_path() returns
~/.claude/densepack-state/projects/<hash>/style.json, outside the project.
<hash> is the first 16 hex characters of a SHA-256 of the lowercase project
path from common.project_dir(). When that step fails, the path is
~/.claude/densepack-state/projects/style.json. DENSEPACK_STYLE names another
file in its place. style_path() makes no folder. save() makes the folder
when it writes the file. A missing file means the defaults, which are the
shipped renderer.

WHAT THE JSON HOLDS. Any subset of the keys below. A key that the JSON does
not name keeps its default. A file with one line changes one value. The JSON
holds a color as [r, g, b], and load() returns it as a tuple, because Pillow
takes a tuple.

WHO READS IT. The three renderer files, codepack.py, densepack.py and
prompt_card.py, read it through load(). drop_read_gate.py also imports it
and reads font.regular through load(). bootstrap.py also imports it and
hashes the bytes of the file at style_path().

THE KEY NAMES. Each key is a dotted name with the group first. The groups are
ink.*, palette.*, code.ink.*, band.*, page.*, mark.*, space.*, curve.*,
font.* and card.*.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STYLE_FILE = "style.json"

_FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"

# The nine inks densepack.py uses for prose, spread around the hue circle.
# Green is dark enough that a stem one column wide keeps its contrast. The
# dict holds the key "orange" twice. The second entry, the vivid
# (255, 104, 0) at the end, wins over the dark (140, 50, 0). ink.orange, the
# look-alike ink "orange" and the backtick in code.ink.reserved use the vivid
# value. The hues stay for the look-alike coloring.
_INK = {
    "black":   (0, 0, 0),
    # Blue is 98.4 from black in Lab. This distance keeps a blue mark
    # different from a black letter. Blue keeps a contrast of 9.2 on the
    # worst band.
    "blue":    (0, 0, 165),
    "green":   (0, 80, 30),
    "magenta": (150, 0, 110),
    "orange":  (140, 50, 0),
    "teal":    (0, 140, 150),
    "red":     (150, 0, 0),
    "purple":  (90, 0, 160),
    "lime":    (90, 210, 0),
    # Two harder inks. The purple above is faint on the double quote. The
    # line end mark needs a green that is clearly different from the letters.
    "hardpurple": (110, 0, 200),
    # Contrast on the four band tints. (0, 120, 0) gives 5.04, and the period
    # gives 8.08. (0, 84, 0) gives 8.19, the same lightness as the period.
    # The greens of Kelly, Trubetskoy and Okabe-Ito all give less than 5.
    "hardgreen": (0, 84, 0),
    # A darker teal for the comma. (0, 140, 150) is faint on the tinted
    # bands. (0, 95, 105) gives a contrast of 6.54 on the lightest tint, and
    # (0, 80, 89) gives 8.10, the same as the period. No teal in the three
    # palettes reaches 4.
    "darkteal": (0, 80, 89),
    # Three inks from Kelly's 22 colors of maximum contrast. The comma and
    # the semicolon take the two inks that pass the period's contrast on all
    # band tints and are farthest in CIE Lab from all other inks. Strong
    # violet is 40.6 from the digit blue. Deep yellowish brown is 38.8 from
    # the letters. Vivid orange is an unused hue 43 from the period's red.
    # This second "orange" entry replaces the first one above. The row edge
    # does not use it. The row edge uses code.ink.wrap, a purple wave.
    "violet": (83, 55, 122),
    "brown": (89, 51, 21),
    "orange": (255, 104, 0),
}

# The look-alike pairs. Each entry is one edge in a confusion graph. The
# coloring gives no two joined characters the same ink.
_CONFUSABLE = [
    ("0", "6"), ("0", "8"), ("0", "9"), ("1", "7"), ("1", "4"),
    ("2", "7"), ("3", "5"), ("3", "8"), ("3", "9"), ("4", "9"),
    ("5", "6"), ("6", "8"), ("6", "9"), ("8", "9"),
    ("0", "O"), ("0", "o"), ("0", "D"), ("0", "Q"),
    ("1", "l"), ("1", "I"), ("1", "i"),
    ("2", "Z"), ("2", "z"), ("5", "S"), ("5", "s"),
    ("6", "b"), ("6", "G"), ("7", "T"), ("7", "t"),
    ("8", "B"), ("9", "g"), ("9", "q"),
    ("l", "I"), ("l", "i"), ("I", "i"),
    ("O", "Q"), ("O", "D"), ("O", "C"), ("O", "o"), ("D", "Q"), ("Q", "C"),
    ("Q", "G"), ("C", "G"), ("C", "c"), ("S", "s"),
    ("c", "e"), ("c", "o"), ("a", "o"), ("a", "e"),
    ("a", "4"), ("a", "9"), ("e", "6"), ("d", "0"),
    (",", "."), (",", "`"), (".", "`"), (",", "'"), (".", "'"),
    ("'", "`"), ('"', "'"), (":", ";"), (":", "."), (";", ","),
    ("m", "n"), ("n", "h"), ("h", "b"), ("b", "d"), ("d", "c"),
    ("u", "v"), ("v", "y"), ("V", "Y"), ("U", "V"),
    ("g", "q"), ("q", "p"), ("f", "t"), ("j", "i"),
    ("K", "X"), ("M", "N"), ("E", "F"), ("P", "R"),
    ("|", "1"), ("|", "l"), ("|", "I"), ("|", "i"),
    # A model reads a b or a d as 0 in a hex id when 0 and b share black and
    # 6 and d share green. These eighteen pairs join each pair of risky
    # characters that can share an ink. Because of this, no such pair shares
    # an ink.
    ("0", "b"), ("0", "4"), ("6", "d"), ("9", "O"), ("1", "a"), ("1", "b"),
    ("8", "l"), ("6", "o"), ("0", "q"), ("0", "B"), ("1", "5"), ("1", "2"),
    ("0", "2"), ("8", "D"), ("9", "G"), ("6", "g"), ("1", "q"), ("1", "B"),
    # At 12 px a model writes b as o. It drops the d from "4d0" when 4 and d
    # share magenta.
    ("b", "o"), ("4", "d"),
]

# The font the plugin ships, first on all platforms, then the fallbacks.
#
# Inter ships in plugin/fonts under the SIL Open Font License. Verdana cannot
# ship, because its license forbids bundling. A machine without Verdana makes
# a different image.
#
# ONE FONT. The image uses Inter and no other font. The source text sets which
# characters are bold. No table sets the face of a character.
#
# INTER SEMIBOLD, weight 600. Inter Regular, weight 400, is the thinnest
# upright weight Inter ships. It needs a heavy ink curve before a model can
# read it.
#
# Weight reaches the page only under the FONT'S OWN hinting. The widest solid
# run inside an n, measured at 11 px:
#
#   hinting mode 2, the auto-hinter    400: 2 px   500: 2 px   600: 2 px
#   hinting mode 0, Inter's bytecode   400: 4 px   500: 4 px   600: 2 px
#
# The auto-hinter snaps all stems to the same whole pixel. A 400 face and a
# 600 face then give the same stroke, and the heavier file adds only width.
#
# The body ink under mode 0 at 10 px:
#
#   Regular  400   solid 34.6%   gray 28.5%   648 tokens
#   Medium   500   solid 37.7%   gray 30.6%   588
#   SemiBold 600   solid 46.2%   gray 26.2%   594
#
# SemiBold has a third more solid ink than Regular, with less gray, for
# fifty fewer tokens.
#
# The Inter files come from the Inter 4.0 release and ship under the SIL Open
# Font License.
_REGULAR = [str(_FONT_DIR / "Inter-SemiBold.ttf"),
            str(_FONT_DIR / "Inter-Medium.ttf"),
            str(_FONT_DIR / "DejaVuSansMono.ttf"),
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
            "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/System/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/Supplemental/Courier New.ttf",
            "/Library/Fonts/Courier New.ttf"]

# The first part of the text prompt_card.py sends once a session. This
# string holds no newline. prompt_card.py joins card.opening and
# card.code_scheme with a newline, and this file keeps each part on its own.
# Keep the two parts. A shorter card makes a model think more over an image.
# Test each change of wording on a bench, because the wording changes how
# much a model thinks and whether a safeguard rejects the turn. The second
# sentence of this string tells the model how to pull one line from the text.
_CARD_OPENING = (
    "A prompt, a report or a file may arrive as a picture of small text: "
    "read it and follow it. When a long number, a hash or a path in the "
    "picture does not read clean, pull that one line from the text by its "
    "green line number: Read with offset N and limit 1. A long file arrives "
    "as several png images named <folder>-<file>-image-N-of-M-DensePack.png, and the note "
    "beside image 1 names the others. "
    # Edit and Write check one thing. They check for a Read of this exact
    # path in this session. Claude Code records the Read when the model makes
    # the Read call. The record does not depend on whether the result is text
    # or a picture. Because of this, the two tools work on a file that
    # DensePack replaced with images. A .doc or .docx is the exception.
    # Claude Code rejects the Read before any hook runs and does not mark the
    # path as read. The two tools then reject the file. Without this line an
    # agent loses turns before it finds this.
    "To change a file that arrived as a picture, use Edit with the exact "
    "text you read off the picture, or Write with the whole new file. Both "
    "work. A .doc or .docx is the exception. Claude Code will not Read one, "
    "and Edit and Write both refuse it. DensePack converts one to images for "
    "you automatically. Read those images.")

# The code scheme card holds only what the key row on image one does not
# show. A longer card costs about 450 tokens on the first turn of each
# session that gets images, and it makes the model think more over the image.
_CARD_CODE_SCHEME = (
    "In a code picture the first row names the file and the marks: letters "
    "are black, digits blue, the colon and the backtick blue, the semicolon "
    "teal, the comma "
    "and the double quote black, every other character red, and the band "
    "behind a line is its nesting depth. Green numbers are the file's own "
    "line numbers, a missing number is a blank line, red numbers are indent "
    "spaces, and a purple mark ending a row means the line continues. Read "
    "the code as written.")

# The card's own rows, which name the marks on a code image.
_CARD_SCHEME_ROWS = [
    "the band behind a line is its nesting depth: red 0, cyan 1, green 2, purple 3, apricot 4, beige 5, blue 6, lavender 7, one colour a depth. A purple row edge means that line goes on into the next row",
    "a green number opens each line and is that line's number in the file. A jump from 2 to 6 means lines 3 to 5 are blank (%s unused)",
    "a red number after the green one is that line's indent in spaces. Where none is printed the band gives the indent",
    "image one opens with a key row: a swatch a depth, then the marks and the purple wrap edge",
]
_CARD_SCHEME_UNDER = "underscores in a row appear as themselves, red then blue (%s unused)"

# The suffixes that pointer.py packs as banded code.
_CODE_SUFFIXES = [".py", ".gd", ".js", ".ts", ".c", ".h", ".cpp", ".rs",
                  ".go", ".java", ".cs", ".sh", ".ps1", ".rb", ".lua",
                  # A model reads each of these back at 0.961 or better with
                  # the line edges removed, the same range as the types above.
                  ".html", ".css", ".mjs", ".bat", ".tscn", ".svg"]

# The suffixes that get bands when band.text_files is on.
_TEXT_SUFFIXES = [".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".ini",
                  ".cfg", ".log", ".csv", ".rst"]


DEFAULTS = {
    # ---- font -------------------------------------------------------
    "font.regular": list(_REGULAR),
    "font.bold": list(_REGULAR),
    # One size for all models, because each model gets the same image.
    "font.px": 12,  # 9 pt at 96 DPI
    "font.ident_px": 0,
    "font.min_ident_chars": 8,
    # The marks grow inside the cell of the body glyph. They move no other
    # glyph.
    "font.bigger_px": 2.0,
    # The brackets also grow inside the cell, to at least the height of the
    # f. The row does not grow for them.
    "font.bigger_chars": ["`", ",", ".", ";", ":", "(", ")", "[", "]", "{", "}"],
    # The marks that step by their ink, not by the advance of their face.
    # This prevents a wide cell of white on each side of the mark.
    "font.ink_step_chars": ["`", ",", ".", ";", ":", "\"", "\u201d", "'", "\u2019"],
    # The glyph renderer. "freetype" renders each character through FreeType
    # on all platforms. Any other value uses Pillow.
    "glyphrenderer": "freetype",
    # A size offset per character group, in pixels, added to the body size.
    # Half a pixel is a legal value, because Pillow takes a float size. All
    # offsets are zero in the shipped renderer, and the page does not move.
    #
    # The six names are the ones densepack.group_for() returns. The two
    # renderers find the offset through it, and each name here is in use.
    # The backtick, the comma and the period are all in lookalike.
    "font.group_px": {"body": 0.0, "lookalike": 0.0, "num": 0.0,
                      "sym": 0.0, "punct": 0.0, "nl": 0.0},

    # ---- one character, everywhere it appears ------------------------
    # The mark the flow uses for the indent count of a line. codepack.py
    # writes the count as a red number after the line number.
    "mark.indent": "\ue001",
    # Clear columns between a band edge and the marks beside it. A mark then
    # touches neither the band outline nor the character beside it.
    # WHAT THE UNIT IS. All spacing numbers in this file are layout columns.
    # codepack.py multiplies them by the shrink ratio, Shrunk.ratio, to get
    # image pixels. codepack.py holds the full map of these constants in one
    # block above GAP. Read it before a change to any of them.
    "mark.clear": 3,
    # The white after a count, before the next word. At 2 a model reads the
    # last digit of a long value as part of the number box of the next line.
    "mark.count_clear": 3,
    # A file extension, the dot and the letters after it as in .jsonl or
    # .txt, gets black ink as one piece. A model then keeps its last letter.
    "code.extension_black": True,
    "char.font_max_px": 12,  # the foot of this file sets the value that ships
    # A VALUE HERE IS NOT ALWAYS THE VALUE AN IMAGE USES. The foot of this
    # file writes into DEFAULTS again after this literal, and the last write
    # sets the value. Print a setting. Do not read it from this literal:
    #   python -c "import sys;sys.path.insert(0,'plugin/scripts');import
    #   style;print(style.load()['char.overrides'])"
    #
    # char.overrides holds per-character entries keyed by the character. The
    # foot of this file sets the entry that ships.
    #
    #   ink.scheme ships as "simple". In that branch codepack.py uses
    #   simple_ink(ch) and does not read the ink of an entry. simple_ink gives
    #   all digits blue ink and all letters black ink. The 1 and the l then
    #   have two different colors.
    "char.overrides": {},

    # ---- ink --------------------------------------------------------
    "ink.black": _INK["black"],
    "ink.blue": _INK["blue"],
    "ink.green": _INK["green"],
    "ink.magenta": _INK["magenta"],
    "ink.orange": _INK["orange"],
    "ink.teal": _INK["teal"],
    "ink.red": _INK["red"],
    "ink.purple": _INK["purple"],
    "ink.lime": _INK["lime"],
    # The five inks of the look-alike groups, in the order the coloring uses
    # them. These are the look-alike group colors.
    "ink.lookalike_groups": ["black", "blue", "green", "magenta", "orange"],
    # One ink for all characters, and the bands hold the meaning.
    # None keeps the per-group colors. None ships.
    "ink.universal": None,
    # The code ink scheme. "simple" gives letters code.ink.name, digits
    # code.ink.number and all other characters code.ink.op, with the
    # look-alike, reserved and per-character inks off. "lookalike" is the
    # other scheme. It stays for a style.json that names it.
    "ink.scheme": "simple",
    # Under the simple scheme, the marks that a model confuses keep their own
    # inks. These are the dot family and the quote family. No two members of
    # one family share an ink. A shared ink across the two families does no
    # harm.
    "ink.simple_punct": {
        # THE ROUND BRACKETS TAKE THE OPERATOR INK, (150, 0, 0). With black
        # brackets, a model loses the last clause of a string inside
        # brackets. With red brackets, a model reads the full string on the
        # same image.
        # Do not put "(" or ")" in this dict.
        ".": _INK["red"], ",": _INK["black"],  # black, because a model drops a violet comma
                         ":": _INK["blue"], ";": _INK["darkteal"],
                         '"': _INK["black"], "\u201d": _INK["black"], "`": _INK["blue"],  # the closing quote takes the same black
                         "'": _INK["red"], "\u2019": _INK["red"]},
    # A run of two or more underscores shows each underscore, the first red,
    # the next blue, then red again. A model can then count them.
    "ink.underscore_run": [_INK["red"], _INK["blue"]],
    "ink.confusable": [list(pair) for pair in _CONFUSABLE],

    # ---- palette, the three classes a glyph separates ---------------
    "palette.num": _INK["blue"],
    "palette.sym": _INK["red"],
    "palette.nl": _INK["teal"],
    "palette.punct": _INK["purple"],
    "palette.tag": _INK["lime"],
    "palette.confusion": {":": "nl", ",": "punct", "`": "punct", "'": "num"},

    # ---- code ink, one per token class -----------------------------
    "code.ink.gutter": (118, 118, 118),
    "code.ink.comment": (45, 45, 45),
    "code.ink.string": (150, 75, 0),
    "code.ink.keyword": _INK["magenta"],
    "code.ink.number": _INK["blue"],
    "code.ink.name": _INK["black"],
    "code.ink.op": _INK["red"],
    "code.ink.tag": (0, 130, 0),
    # The reserved inks give the backtick, the underscore and the comma an
    # ink of their own.
    "code.ink.reserved": {"`": _INK["orange"], "_": (75, 45, 90),
                          ",": _INK["purple"]},
    "code.ink.indent": _INK["teal"],
    # The ink of the blank-line count.
    "code.ink.blank": (230, 0, 0),  # red, because purple marks here cost a model more output tokens
    "code.ink.wrap": (120, 0, 220),  # the wave purple. The marks stay green and red.
    "code.ink.lift": (0, 130, 0),
    "code.lift_px": 0,
    # The width of the purple wrap wave at the end of a row, in code.ink.wrap.
    # The wave marks a source line that continues into the next row. It swings
    # this many pixels to each side, and its stroke is this wide.
    "code.wrap_width": 2,
    "code.suffixes": list(_CODE_SUFFIXES),
    # Empty, because a tail block under a comma shows as a stray dot on the
    # image. The font has tails of its own.
    "code.tailed": [],
    # The layout does not break a run joined by underscore, hyphen or equals.
    # "Things like=this" stays whole. A run wider than a full row still
    # breaks at the row edge, because flow_rows() takes the width cut when
    # the walk back reaches the start of the row.
    "code.word_chars": "_.-/\\=",

    # ---- band -------------------------------------------------------
    # Eight depths. No color repeats past the last depth, because a model
    # reads a repeated color as the top level. Each tint here is at twice its
    # distance from white, because band.strength below halves it. The tints
    # are far apart in CIE Lab, and black text keeps a contrast of 12 or more
    # on each tint.
    # The order alternates cool and warm. Two depths next to each other are
    # then never two pale cool tints. With blue at depth 1 and green at depth
    # 2, a model confuses the two and writes a line one tab short. Depth 2 is
    # yellow.
    "band.tints": [(255, 220, 212), (115, 223, 247), (255, 245, 145), (247, 143, 241),
                   (150, 255, 150), (255, 177, 99), (183, 195, 241),
                   (199, 151, 255)],  # eight depths
    # 1.0 uses the tint as written. A value under 1.0 mixes it toward the
    # image background. A value over 1.0 pushes it away from the background.
    # At 1.0 the tints are as hard as the letters on them.
    "band.strength": 0.5,
    # Whether a line at depth 0 gets the first tint. With True, the band
    # behind a top-level line helps a model keep a thin last letter, such as
    # a final l.
    "band.top_level": True,
    # The band as a shape. pad grows or shrinks the band past the text on
    # each side, and offset moves it. The two are in pixels.
    # The space between the left edge of a band and its first letter, in
    # pixels. The outline then does not touch the first glyph. The band grows
    # by the same amount on the right, and the last letter keeps its room.
    "band.text_inset": 4,
    # White between bands. gap_y is the white rows between one band and the
    # band under it. It comes from the spare pixel that each row holds under
    # its descenders, and it costs no height. gap_x is the white columns
    # between two blocks in one row, kept out of the block gap. space.row_gap
    # adds real rows between bands and costs height.
    "band.gap_x": 1,
    "band.gap_y": 1,
    # The pixels that all bands grow on one side at once.
    "band.grow_l": 0,
    "band.grow_r": 0,
    # CENTERING THE TEXT IN ITS BAND. band.grow_b 1, band.pad_y 0 and
    # band.centre_text together center the ink in its band. Each one alone
    # leaves the text off center, and grow_b alone merges neighboring bands.
    "band.grow_t": 0,
    "band.grow_b": 1,
    # At 0 the first character of a line is on the band outline. The band
    # widens the two sides at once, and no glyph moves into the right outline.
    "band.pad_x": 3,
    # The rows of band kept clear above the tallest ink of a row and below
    # the lowest ink. No glyph then touches the edge of its band.
    #
    # It grows the ROW, not the band. band.grow_t and grow_b move the band
    # edge without moving the glyph. The band then extends into the row gap,
    # and neighboring bands merge. The room must come from the row height, and
    # it costs image height.
    # It also insets the wrap mark from the top and foot of the band. The mark
    # then does not touch the bands above and below.
    #
    # ANCHOR IT TO THE BAND, NOT TO y. The band starts at y + band.offset_y. A
    # change of band.offset_y cancels an inset measured from y.
    "band.text_clear": 1,
    # THE CODE CENTERS THE BAND ON THE TEXT. A fixed band.offset_y trades the
    # clear rows above the text against those below, two rows of balance per
    # unit, and the correct value depends on the glyph size.
    #
    # With this on, the code gets the offset for each render from the position
    # of the face's ink. It measures a set with the tallest ascenders and the
    # lowest descenders. It does not use the nominal ascent and descent, which
    # hold room that the face does not always use. band.offset_y is then only
    # the manual override, for a caller that needs the band off center.
    "band.centre_text": True,
    # False fits the box around a line number to its own digits on all four
    # sides. True takes its top and bottom from the band. This dict holds the
    # key twice. The second entry, True, further below, wins over this False.
    # The foot of this file also sets True, which ships.
    #
    # The boxes in a row stay level with either value. Each box holds digits,
    # and all digits ink the same rows. A box fitted to its own ink is at the
    # same height as its neighbors.
    "mark.box_fits_band": False,
    # IT DEPENDS ON THE SIZE. MEASURE IT AGAIN WHEN CODE_PX CHANGES.
    # The band moves as one. This value trades the clear rows above the text
    # against the clear rows below, two rows of balance per unit.
    #
    # The line number box can take its height from the band. Any imbalance in
    # the band is then also in the box.
    #
    # 0 keeps the text centered in its band. A negative value lifts the band
    # off the text and puts each descender on the bottom edge of the band.
    "band.offset_y": 0,
    "band.pad_y": 0,
    "band.offset_x": 0,
    # Objects placed by hand. The keys are "line:N" for source line N and its
    # band together, "band:N" for the band alone, and "word:N:K" for the K-th
    # word of line N. Each entry holds dx and dy in pixels. A band or a line
    # can also hold grow_l, grow_r, grow_t and grow_b, the pixels its band
    # grows on that side. The dict ships empty, and no object moves.
    "layout.placements": {},
    "band.outline": (150, 150, 150),
    "band.outline_width": 0,  # no gray border around a band
    # True sends a text file through the code renderer, the one with the ink
    # curve, the glyph clearance and the per-character inks. Models copy more
    # hard values from it than from the plain pack.
    "band.text_files": True,
    "band.text_suffixes": list(_TEXT_SUFFIXES),

    # ---- page -------------------------------------------------------
    # page.width, further below, is the rendered width of one prose page
    # column. codepack.py takes page.pad from each side and the 8 px that the
    # render loop adds. page.width ships as 336 and page.pad as 3, which gives
    # 322 px of text. A4 is 794.
    # page.trim, further below, ends the image at its widest row. The code
    # removes the white past the last letter of the widest row. The patch
    # grid still rounds the size up when page.patch is above 1.
    # page.snap_glyphs True puts the shrunk mask of a glyph on a whole output
    # pixel at its own width, the same as a rectangle. A stem then fills one
    # column, and more ink is at full strength. False shrinks the sub-pixel
    # remainder of each glyph into the mask.
    "page.snap_glyphs": True,
    # page.glyph_at_final_size True gets each glyph from FreeType at its final
    # size. The hinting then acts at that size, and the code does not resize
    # a glyph after the hinting.
    "page.glyph_at_final_size": True,
    "page.supersample": 3,
    # The layout width. It equals page.code_width. The code then renders each
    # glyph on its final grid and scales nothing. See common.CODE_PX.
    "page.code_layout_width": 756,
    # The glyph grows into the white under the last band, and the padded
    # image keeps its height. This applies to one-image files only. See
    # codepack._fill_bottom.
    "page.fill_bottom": True,
    # page.key_row False makes image one with no key row at its head. The
    # image ships with the row.
    "page.key_row": True,
    # 1, because supersampling renders the glyph large and takes the mean of
    # the pixels as it shrinks the glyph. A hinted small glyph needs the
    # opposite. The hints fit the outline to the pixel grid at the target
    # size, and the shrink averages the pixels and removes that fit.
    "page.code_supersample": 1,
    "page.code_width": 756,
    # THE TWO IMAGE WIDTHS THAT THE FIT SEARCH TESTS. The two are whole
    # counts of 28 px patches, 27 and 28, and neither adds a white column.
    # The layout width follows the image width on each trial. The shrink
    # ratio then stays 1.0, and the code scales no glyph after FreeType
    # hinted it.
    #
    # WHAT THE SEARCH COSTS. Each width runs the two fit steps of
    # codepack.py, _fill_bottom() to grow the glyph down and then
    # _fit_width() to grow the layout. Two widths cost more than two
    # renders. The model does not pay this cost, because it is build time.
    # A slow hook still delays the turn.
    #
    # WHAT IT SAVES. read_gate.py costs 1,975 visual tokens at 756 and 1,964
    # at 784. The search saves 11 tokens on that file.
    #
    # A list of one width renders at that width and compares nothing. Use it
    # when the wait matters more than the tokens. An empty list leaves
    # page.code_width as it is.
    "page.code_width_choices": [756, 784],
    # A taller cap holds more text on one image. A lower cap splits larger
    # files into more images. The foot of this file sets the value that
    # ships.
    "page.code_height": 2000,
    # Images per row on a delivery sheet. 1 gives each image its own row. A
    # file then arrives as single column images, and a model does not read
    # across a seam. 0 fits as many images across as page.edge allows, which
    # puts two 756 px images on a 1512 px sheet.
    #
    # A two column sheet costs a model its answers. On a bench of 16 files,
    # Sonnet answered 3 of 5 on two column sheets and 5 of 5 on single column
    # images. On the same bench, the Opus saving rose from 48.4% to 64.7%.
    # Each pair below counts at the two prices, with 5 of 5 answers on the
    # two arms:
    #
    #   16-file Sonnet  59.3%     32-file Sonnet  72.7%
    #   16-file Opus    64.7%     32-file Opus    75.3%
    #
    # Single column images cost no extra tokens. A file is ceil(w/28) *
    # ceil(h/28) visual tokens with either value. Two 784 px images and one
    # 1568 px sheet of the same height give the same count. drop_read_gate.py
    # measures 7,224 tokens wide and 7,168 narrow.
    #
    # The stack passes page.edge. composite_grid() then returns None, and the
    # pages ship one to an image. The coverage does not change. With either
    # value, drop_read_gate.py starts at line 1 and its last image starts at
    # line 577.
    "page.grid_per_row": 1,
    # The supersample by source size, as [up to this many characters, s]. 0
    # means no limit. A high supersample on a large file can pass the time
    # limit of the hook.
    "page.code_supersample_tiers": [[0, 12]],
    # The filter the shrink uses: box, bilinear, hamming, bicubic or lanczos.
    "page.supersample_filter": "hamming",
    "page.trim": True,
    # When the word safe cut leaves a row emptier than this share of its
    # width, the row takes the width cut. Rows then run to the right edge,
    # and the wrap edge marks the cut. 0 keeps all rows word safe.
    "page.fill": 0,  # 0, because a larger share cuts words such as transcript.jsonl across rows
    "page.width": 336,
    # The maximum height of one page column. A4 is 1123.
    "page.height": 1176,
    # Source rows a page holds, or 0 to fill page.height. 40 is about a
    # printed sheet.
    "page.lines": 0,
    "page.columns": 1,
    "page.sheet_gap": 16,
    "page.pad": 3,  # 6 leaves a patch row of white under a short image
    "page.text_pad": 2,
    "page.patch": 28,
    "page.cap_w": 1568,
    "page.cap_h": 1568,
    "page.edge": 1568,
    "page.max_tok": 4784,
    "page.ratio": 1.0,
    "page.image_block": 2,
    "page.background": (255, 255, 255),
    "page.divider": (150, 150, 150),
    "page.divider_width": 2,

    # ---- marks ------------------------------------------------------
    # PRIVATE-USE CODE POINTS. No text holds U+E000 to U+E003. An arrow,
    # dagger, pilcrow or section sign in the source text then shows as itself.
    # codepack.drawn() maps the tab mark to the arrow glyph and the underscore
    # mark to the dagger.
    "mark.count": "\ue001",
    "mark.pilcrow": "\ue000",
    # The line break and its blank count take hard green. The indent count
    # takes red.
    "mark.pilcrow_ink": _INK["hardgreen"],
    # The ink of the blank line count after the line-break mark.
    "mark.count_ink": _INK["hardgreen"],
    "mark.box_ink": (0, 0, 0),
    # The room between the line break and the box of the next line number.
    # It holds the clear column of the last character, the band edge past it
    # and the white before the box. At 3.5 a few boxes keep only one image
    # pixel of white on the left, the side of the last character of the
    # previous line. A model then misreads a digit there. 5.5 gives these
    # boxes enough white.
    "mark.box_gap": 5.5,
    # White, the seam rule and white between a green line number and a red
    # indent count. At 2.5 no rule touches a digit. A few digits are at two
    # columns on one side, because the bearing of a digit moves the white run
    # by a column. One constant cannot keep all pairs at three columns.
    "mark.seam_gap": 2.5,
    "mark.box_clear": 2,  # white between the mark box and the band after it
    # THE WHITE BETWEEN THE WRAP MARK AND THE INK OF THE LAST CHARACTER, in
    # image pixels.
    #
    # WHERE THE MARK GOES. The render loop puts it at the end of the row plus
    # band.pad_x, band.text_inset and mark.clear. The end of the row is the
    # SUM OF THE ADVANCES. The ink of w, e, ] and / fills its own advance and
    # reaches that point. The wave then lands one pixel from it, and a row
    # that ends in a narrow glyph gets a lot of room. This setting is a FLOOR
    # measured from the ink. It moves only the tight rows and leaves the
    # other rows as they are.
    #
    # DO NOT RAISE mark.clear IN PLACE OF THIS SETTING. mark.clear moves ALL
    # marks. The layout then needs a wider row everywhere, and the image
    # grows. Measured on one file with 38 end-of-row marks, in visual tokens:
    #
    #   mark.clear 3   5 marks tight   840 tokens
    #   mark.clear 4   3 marks tight   918 tokens
    #   mark.clear 5   3 marks tight   918 tokens
    #   mark.clear 6   1 mark  tight   918 tokens
    #
    # A higher mark.clear costs 9.3 percent more page and still does not
    # reach zero tight marks.
    "mark.wrap_ink_clear": 3,
    # codepack.py skips the line end mark before it gets a glyph.
    # The line end mark is outside its band, in the white between one block
    # and the next. The band stops one pixel before the mark. The mark does
    # not move.
    "mark.pilcrow_outside": True,
    # Empty, because the count after a line end shows the blank lines on its
    # own, in the mark ink, in the white between bands. A dot here puts a mark
    # after the count.
    "mark.blank": "",
    # The count and the mark, in the order the code renders them.
    # "%(count)d%(mark)s" is the shipped run, the digits and then mark.blank.
    # mark.blank ships empty, and the run is the digits only.
    "mark.blank_format": "%(count)d%(mark)s",
    "mark.underscore": "\ue003",
    "mark.tab": "\ue002",

    # ---- spacing ----------------------------------------------------
    # THE HORIZONTAL SCALE. Below 1.0 the code condenses each letter and keeps
    # its height. FreeType gets it as face.set_char_size(width = size * scale,
    # height = size). This is a real outline scale, not a resample, and the
    # x-height does not move. FreeType hints at that aspect and fits the stems
    # to the grid at their final width.
    #
    # MEASURED at 12 px on a sample of ordinary words, the width one row takes,
    # the share of letter pairs whose ink touches, and the solid ink:
    #
    #   1.00   row 369   collisions 55%   solid 35.1%
    #   0.95   row 355   collisions 71%   solid 34.3%
    #   0.90   row 350   collisions 18%   solid 43.5%
    #   0.85   row 310   collisions 43%   solid 42.9%
    #   0.80   row 292   collisions 43%   solid 35.0%
    #   0.75   row 287   collisions 47%   solid 13.4%
    #
    # The column is not a trend. Do not read it as one. Condensing moves each
    # outline against the pixel grid. A value either lands the stems on whole
    # pixels or scatters them. 0.95 is worse than the two values next to it,
    # and 0.75 collapses the ink. Measure each value. Do not interpolate.
    #
    # IT APPLIES TO LETTERS ONLY.
    # A letter has spare width. At 12 px an n is 7 px wide, and 0.85 costs it
    # one column in seven. Punctuation is two or three pixels wide, and the
    # same fraction is most of the mark. A digit must stay different from all
    # other digits. Punctuation and digits render at full width. See
    # face_for() in codepack.
    # The foot of this file sets the value that ships.
    "font.scale_x": 0.769231,
    # The only uniform spacing control. char_widths() adds it to each pen
    # step. Each pair then widens by the same amount, and the rhythm of the
    # font design stays. It must be a WHOLE number. char_widths() rounds
    # own + LETTER_SPACE to a whole pixel. A fraction rounds up on some
    # characters and down on others, and the gaps become uneven.
    "space.letter": 1.0,
    "space.letter_text": 0.0,
    "space.word": 0.0,
    "space.line_gap": 0.85,
    "space.line_factor": 1.2,
    # The white after a line end holds the right edge of the band, a clear
    # column, the mark, a clear column and the left edge of the next band.
    # 4 is enough for these parts. The value ships as 8.
    "space.block_gap": 8,
    # space.row_gap, further below, sets the white rows BETWEEN two bands.
    # This table is about that key, not about space.row_px under it. 2 keeps
    # all gaps uniform and uses little of the row pitch for white. Measured
    # at 10 px, the gap in the image and the cost of the image:
    #
    #   row_gap 4   gaps 4 px on 35 of 38   728 visual tokens
    #   row_gap 3   gaps 3 px on 37 of 40   675
    #   row_gap 2   gaps 2 px on 35 of 38   644
    #   row_gap 1   gaps 1 px on 38 of 40   594
    #
    # The band height stays the same at each value, and glyphs and baselines
    # do not move. More text still takes more rows, then a taller image up to
    # the height cap, then a new image. The rows are closer, and more rows
    # fit.
    # THE GLYPH SIZE FOR THE ROW, when it differs from the glyph size.
    # Zero means the row follows the glyphs. The literal here is 10, and the
    # foot of this file sets 13, which ships. Set it with
    # font.scale_x to raise the x-height without a larger page. 17 px
    # condensed to 0.588 gives an x-height of 10 in the column of a 10 px
    # face, and space.row_px 10 keeps the band at its 10 px size. codepack.py
    # describes the cost, which is ascenders that extend into the band above.
    "space.row_px": 10,
    # THE MARKS AT FULL WIDTH. font.scale_x does not condense them, and they
    # do not get the extra height of the larger size.
    #
    # codepack reads this twice. scale_for leaves them uncondensed, and
    # face_for offsets their size back to space.row_px. A bracket on a 13 px
    # page then stays a 10 px bracket, and the letters beside it are 13 px
    # condensed to the same column width.
    #
    # The period, comma, semicolon and colon are NOT here on purpose. They
    # render a size larger through font.bigger_chars.
    # The size of the full width marks. Zero means the size of the page. 12
    # on a 13 px page renders them one pixel below the size of the letters.
    # font.scale_x does not condense them, and they keep their full width at
    # that size.
    'font.mark_px': 12,
    # The share of the hang of a bracket below the baseline that the code
    # removes. 1.0 puts its ink on the baseline. 0.0 leaves it where Inter
    # puts it, on the mathematical axis. This value is a share, because a
    # full lift puts brackets too high at the shipped sizes.
    'mark.baseline_lift': 0.4,
    # One size for one mark, when the size of its set does not fit it. The
    # pipe is the tallest mark on the page and looks a size larger than the
    # glyphs around it. It renders one size smaller than the rest.
    'font.mark_px_by_char': {'|': 11},
    # The marks that condense WITH the letters and do not keep their own
    # width. These are the opening quotes only. The second quote of a kind on
    # a line renders as its closing form, and the closing forms keep their
    # width.
    'font.condensed_marks': ['"', "'", '\u2019'],
    # The rows that one character moves down, or a negative value to raise
    # it. A closing double quote is lower in its em than the opening one, and
    # the two are not level on a row. The font puts the glyph at its design
    # position, and the page moves it.
    "font.dy_by_char": {},
    # THE MARK BOX TAKES THE HEIGHT OF THE BAND. A box fitted to its own
    # digits is shorter than the band. Its outline is then inside the row,
    # and the digits touch it. A top and bottom from the band give the digits
    # room. False fits the box to its own ink. This is the second
    # mark.box_fits_band entry in this dict, and its True wins over the False
    # above.
    "mark.box_fits_band": True,
    # The horizontal scale of one character. It overrides all groups. Use it
    # to move one mark off the column of its group without a new group.
    "font.scale_x_by_char": {},
    # The marks at the size of the page that condense to
    # font.scaled_mark_scale_x. They are between the letters, which condense
    # most, and the marks that keep their full width at a size of their own.
    # The closing DOUBLE quote is not here on purpose, because the design
    # keeps it at its own width. A zero scale turns the group off.
    "font.scaled_marks": ["%", "#", "?", "{", "}", "[", "]", "(", ")",
                          '"', "'", "\u2019"],
    "font.scaled_mark_scale_x": 0,
    # The width of a condensed digit, as a share of its own width. Zero means
    # a digit keeps its full width. It is separate from font.scale_x, because
    # a digit must stay different from all other digits. 12/17 renders a
    # 17 px digit at the width of a 12 px digit, and a letter goes to the
    # width of a 10 px letter.
    'font.digit_scale_x': 0,
    "font.full_width_chars": ["(", ")", "[", "]", "{", "}", "|", "\\", "/",
                              "%", "<", ">", "+", "=", "*", "&", "^", "$",
                              "#", "@", "!", "?", "~", "-"],
    "space.row_gap": 2,  # with band.pad_y 1 each side, 2 gives one clear row of white between bands and no taller page. band.pad_y ships as 0.
    # The edge control. curve.blur sets the edge. none renders each ink pixel
    # at full ink or not at all. ring keeps one blended ring. full keeps the
    # blend of the font. auto follows the curve name. It acts only on the
    # Pillow path, through _lut(). A shipped image renders all glyphs through
    # FreeType.
    "curve.blur": "auto",
    # A small image renders its glyphs with the gray ramp of the font. The
    # step curve quantizes a 10 px stroke to three levels, and the stroke
    # becomes blobs.
    "curve.small_px": 12,
    "curve.small_name": "soft",
    # The step threshold on a small image. It is lower than the 128 of larger
    # images. A one pixel stroke under half ink then still renders and does
    # not break into stubs.
    "curve.small_threshold": 96,
    "space.paragraph_gap": 0,
    # The pen distance from the last inked column of one glyph to the first
    # inked column of the next. 2 gives one white column between them, also
    # for narrow letters. The underscore mark keeps mark.clear through
    # codepack.py.
    "space.clear": 2,
    "space.clear_narrow": 2,
    # The pen distance between two quote marks of the same kind in a row. A
    # model then reads the three curly quotes of a docstring as three.
    "space.quote_run_clear": 2,  # quotes get the same space as letters
    # The pen distance between two of the same letter in a row. The
    # crossbars of the two f in "off" then do not join.
    "space.same_clear": 3,
    # A stem, l I 1 i or |, beside a quote keeps this many columns clear. A
    # model then does not read the bar of an l and the bars of a quote as one
    # mark.
    "space.stem_quote_clear": 2,  # the foot of this file sets the value that ships
    # Clear columns after a mark that steps by its ink, the period, comma,
    # colon, semicolon and backtick. Its right side then keeps the same white
    # as its left side. 3 grows no image. 4 adds one wrapped row to most
    # images, about 3 percent of their tokens.
    "mark.step_right": 3,
    "space.narrow_cols": 2,
    "space.ink_floor": 40,

    # ---- ink curve --------------------------------------------------
    # "hard" turns anti-aliasing fully off, "soft" leaves it fully on,
    # "step" is the shipped curve between the two.
    "curve.name": "step",
    "curve.threshold": 128,
    "curve.ring": 64,
    "curve.ring_weight": 128,
    "curve.gamma": 0.45,

    # ---- the card ---------------------------------------------------
    "card.opening": _CARD_OPENING,
    "card.code_scheme": _CARD_CODE_SCHEME,
    "card.scheme_rows": list(_CARD_SCHEME_ROWS),
    "card.scheme_underscore": _CARD_SCHEME_UNDER,
}


def style_path():
    """The JSON file, ~/.claude/densepack-state/projects/<hash>/style.json.
    This function makes no folder. save() makes it.

    DENSEPACK_STYLE names another file in its place. A preview can then
    render without a change to the file that the live plugin reads.
    """
    named = os.environ.get("DENSEPACK_STYLE")
    if named:
        return Path(named)
    # The file is outside the project. A cloned project can commit a style
    # file that renders one character as another, and the image then does not
    # match the file. The file is under the home folder and never under
    # CLAUDE_PLUGIN_DATA. dpctl.py and densepack.py run without that variable
    # and must use the same style file as the hooks. Each project has one folder,
    # named by a hash of its path.
    base = Path.home() / ".claude" / "densepack-state" / "projects"
    try:
        import hashlib
        from common import project_dir
        key = hashlib.sha256(str(project_dir().resolve()).lower().encode("utf-8")).hexdigest()[:16]
        return base / key / STYLE_FILE
    except Exception:  # noqa: BLE001
        return base / STYLE_FILE


def _rgb(value):
    """A color in the form Pillow takes. JSON returns a list, and PIL takes a tuple."""
    if isinstance(value, list) and 3 <= len(value) <= 4 and all(
            isinstance(v, (int, float)) for v in value):
        return tuple(int(v) for v in value)
    return value


def _coerce(key, value, default):
    """One override, in the same shape as its default."""
    if isinstance(default, tuple):
        return _rgb(value) if isinstance(value, list) else value
    if isinstance(default, list):
        return [_rgb(v) for v in value] if isinstance(value, list) else value
    if isinstance(default, dict) and isinstance(value, dict):
        out = dict(default)
        out.update({k: _rgb(v) for k, v in value.items()})
        return out
    return value


def read_overrides(path=None):
    """The JSON file's contents, or an empty dict when it is not there."""
    path = Path(path) if path is not None else style_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def load(path=None):
    """All tunable values, the defaults with the values of style.json over them."""
    out = dict(DEFAULTS)
    for key, value in read_overrides(path).items():
        if key in DEFAULTS:
            out[key] = _coerce(key, value, DEFAULTS[key])
    return out


def save(values, path=None):
    """Write only the values that differ from the default, and return the path."""
    path = Path(path) if path is not None else style_path()
    keep = {}
    for key, default in DEFAULTS.items():
        if key in values and _plain(values[key]) != _plain(default):
            keep[key] = _plain(values[key])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keep, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def _plain(value):
    """A value in the form JSON writes. A tuple and its list then compare equal."""
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def demo():
    """The self check. The defaults stay the same after a round trip, and an override takes effect."""
    import tempfile
    base = load(Path(tempfile.gettempdir()) / "densepack-no-such-style.json")
    assert base["curve.name"] == "step"
    assert base["page.width"] == 336
    assert base["ink.black"] == (0, 0, 0)
    with tempfile.TemporaryDirectory() as folder:
        spot = Path(folder) / STYLE_FILE
        spot.write_text(json.dumps({"page.width": 794,
                                    "ink.black": [10, 20, 30],
                                    "curve.name": "hard"}), encoding="utf-8")
        over = load(spot)
        assert over["page.width"] == 794
        assert over["ink.black"] == (10, 20, 30), over["ink.black"]
        assert over["curve.name"] == "hard"
        assert over["page.height"] == DEFAULTS["page.height"]
        save(over, spot)
        again = load(spot)
        assert again["page.width"] == 794
        assert again["page.height"] == DEFAULTS["page.height"]
    print("style.py self check passed")


if __name__ == "__main__":
    demo()


# ONE FONT AT ONE SIZE.
#
# The image uses Inter, from plugin/fonts/Inter-SemiBold.ttf, at one size,
# for all models. font.regular and font.bold name the same file. Only the
# source text sets which run is bold. Print the path. Do not trust a
# comment:
#   python -c "import sys;sys.path.insert(0,'plugin/scripts');import
#   densepack as dp,common;print(dp.load(dp.REGULAR,common.CODE_PX).path)"
# The ink curve in plugin/scripts/freetype_glyph.py gives a thin letter
# enough ink. No per-character table does this.
#
# WHAT char.overrides CAN HOLD
#   ink      the color rule, which holds the meaning of the image.
#   glyph    the character rendered in place of another.
#   adv      extra width after a character.
# An entry with font, px, scale_x, dy, bold, thick or weight gives one
# character its own face. The one font design does not allow this.

# THE LINE END MARK HAS NO INK.
#
# The green line number shows where a line starts. A line end mark adds no
# fact that the number does not show. codepack.py does not render the mark.
# char_widths() charges the blank width in full, the render loop skips the
# mark before it gets a glyph, and the box test treats it as inkless. The
# mark is still in the flow, because it holds the band, the row break rule,
# the band edge and the line id. A model does not see it as a character.

# THE DOT MARKS ARE NOT BOLD. The embolden widens a mark across and caps the
# vertical widening at half a pixel below 15 px. A two pixel period then
# widens into a bar and closes the gap to the letter after it.

# THE CLEAR RULES. These add columns between two characters. Inter already
# spaces its own letters. A gap of 3 next to a gap of 6 does not look like
# one word. Three of the five rules stay at zero for this reason. The
# alternate glyphs of Inter fix a look-alike glyph.
DEFAULTS["space.same_clear"] = 0
DEFAULTS["space.quote_run_clear"] = 0
# 5 keeps clear columns between an l and a closing quote. A model then keeps
# the l of jsonl". codepack.STEM_CLOSERS holds the two closing quotes, and
# the rule also applies to the curly one. 6 moves wraps.
DEFAULTS["space.stem_quote_clear"] = 5

# space.clear and space.clear_narrow are FLOORS, at 2 and EQUAL.
#
# The value is the pen distance from the last inked column of one glyph to
# the first inked column of the next. 2 leaves one white column between two
# glyphs that touch without it. Under the hinter some pairs ink up to their
# advance, and a model reads a pair with adjacent ink as one shape.
#
# WHY THEY MUST BE EQUAL. clear_narrow applies when either glyph inks
# space.narrow_cols columns or fewer, which is each i, l, t, f, r and j. A
# larger clear_narrow opens a hole around these letters and splits words.
#
# WHY THE GAP IS NOT EXACT. space.ink_gap_exact sets the same ink to ink
# distance for all pairs. A letter whose ink fills its advance (n, o, a, b)
# then keeps the step of Inter, and a letter whose ink is well inside the
# advance (f, r, t, i, l, /) moves a whole pixel wider. Measured over 2,471
# pairs against the step of the Inter design:
#
#   exact on    spread 0.526 px, worst pair 2.83 px from its neighbor
#   exact off   spread 0.268 px, worst pair 1.01 px
#
# The rule stays off for this reason, and the advances of the font set the
# rhythm.
DEFAULTS["space.ink_gap_exact"] = False
DEFAULTS["space.clear"] = 2
DEFAULTS["space.clear_narrow"] = 2

# THE PUNCTUATION IS LARGER. A comma, a colon, a slash and a brace are a few
# pixels. One pixel is a small share of the type but a large share of the
# mark.
#
# THE IMAGE DOES NOT GROW, because of the method below.
#
#   char_widths() takes the pen step and the clear columns from the BODY
#   face, never from the larger one. The cell is then the cell of the small
#   glyph. The test at codepack.py face() reads "p[0] not in BIGGER". It
#   gives a BIGGER mark the body face for its cell on purpose, and the render
#   uses the big flag. The layout with the marks on is the same as the layout
#   with them off.
#
#   Vertically, the larger face has a taller ascent. A marked glyph then
#   starts that many rows higher and grows UPWARD into the clear rows that
#   the row already holds above the type. No glyph below the baseline moves,
#   and no row changes height.
#
# No letter and no digit is in the set. The underscore is not in the set on
# purpose, and THE UNDERSCORE note below gives the reason. The marks in the
# set render 2 pixels larger than the body glyph.
DEFAULTS["font.bigger_px"] = 2
# THE FOUR DOT MARKS ARE IN THIS SET. No mark is bold, and a larger dot mark
# stays a dot and does not become a wide square.
DEFAULTS["font.bigger_chars"] = [
    "'", '"', "`", "\u2019", "\u201d",
    "|", "\\", "/", "(", ")", "[", "]", "{", "}",
    "-", "=", "+", "<", ">", "*", "&", "^", "%", "$", "#", "@", "!", "?", "~",
    ".", ",", ";", ":",
]
DEFAULTS["font.ink_step_chars"] = []

# The bold face is the same file as the regular face.
# plugin/scripts/freetype_glyph.py renders a bold run with a bolder outline,
# through FT_Outline_EmboldenXY.
DEFAULTS["font.bold"] = list(DEFAULTS["font.regular"])

# THE UNDERSCORE USES ITS OWN GLYPH. The underscore of Inter is a solid bar,
# and the ink curve in freetype_glyph.py takes it to full ink. Extra rows on
# a rendered bar only make it heavier than the letters beside it.

# NO CAP ON THE GLYPH SIZE. A cap only stops a render at a larger size that
# a style sets on purpose.
DEFAULTS["char.font_max_px"] = 0

# The code scales no glyph after hinting. backend_text() in codepack.py
# reads page.glyph_at_final_size and gets the glyph from FreeType at its
# final size.

# THE IMAGE CEILING. 1596 px is 57 patches on a side. The client and the API
# do not resize an image at or under it.
DEFAULTS["page.code_height"] = 1596

# ONE INK CURVE. The curve of the backend in freetype_glyph.py is the only
# one. The curve in codepack is off, and two curves never act on the same
# pixels.
DEFAULTS["curve.name"] = "none"
DEFAULTS["curve.small_name"] = "none"

# FreeType renders all characters, on all platforms.
DEFAULTS["glyphrenderer"] = "freetype"


# THE SHIPPED VALUES. These values with common.CODE_PX at 17 make the image
# that all benches score.
DEFAULTS['font.scale_x'] = 0.5882352941176471
DEFAULTS['font.digit_scale_x'] = 0.7058823529411765
DEFAULTS['font.scaled_marks'] = ['%', '#', '?', '{', '}', '[', ']', '(', ')', '"', "'", '\u2019']
DEFAULTS['font.scaled_mark_scale_x'] = 0.7058823529411765
DEFAULTS['space.row_px'] = 13
DEFAULTS['font.mark_px'] = 16
DEFAULTS['font.mark_px_by_char'] = {'|': 14, '\u201d': 14, "'": 18}
DEFAULTS['mark.baseline_lift'] = 0.4
DEFAULTS['font.scale_x_by_char'] = {'"': 0.6470588235294118, "'": 0.6666666666666666, 'l': 0.7058823529411765, ',': 0.7058823529411765}
DEFAULTS['font.dy_by_char'] = {'\u201d': -3, '(': 1, ')': 1, '[': 2, ']': 2, '{': 2, '}': 2}
DEFAULTS['mark.box_fits_band'] = True
DEFAULTS['char.overrides'] = {'(': {'adv': 1}}
