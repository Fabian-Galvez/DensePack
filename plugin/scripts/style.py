"""Every value the renderer draws with, in one dict.

WHAT THIS FILE DOES. codepack.py, densepack.py and prompt_card.py ask this
file for their numbers and colours. load() returns one flat dict. A run with
no style.json on disk draws with the defaults below.

WHERE THE FILE IS. Beside the settings file dpctl.py writes, which is
<project>/.claude/tmp/densepack-settings.json, under the name style.json.
The path is built from common.project_dir() and no directory is created here:
a missing file means the defaults, which is the shipped renderer.

WHAT THE JSON HOLDS. Any subset of the keys below. A key it does not name
keeps its default, so a file holding one line changes one thing. A colour is
written as [r, g, b] and read back as a tuple, because Pillow draws a tuple.

WHO READS IT. The three renderer files read it. Nothing else in the plugin
depends on this file.

THE KEY NAMES. A dotted name, group first: ink.*, palette.*, code.ink.*,
band.*, page.*, mark.*, space.*, curve.*, font.*, card.*.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STYLE_FILE = "style.json"

_FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"

# The nine inks densepack.py draws prose with, spread around the hue circle.
# Green and orange are dark enough that a one column stem in either carries
# contrast; the hues stay for the look-alike colouring.
_INK = {
    "black":   (0, 0, 0),
    # Blue sits 98.4 from black in Lab, so it reads apart from a black
    # letter, and it keeps a contrast of 9.2 on the worst band.
    "blue":    (0, 0, 165),
    "green":   (0, 80, 30),
    "magenta": (150, 0, 110),
    "orange":  (140, 50, 0),
    "teal":    (0, 140, 150),
    "red":     (150, 0, 0),
    "purple":  (90, 0, 160),
    "lime":    (90, 210, 0),
    # Two harder inks: the purple above reads faint on the double quote,
    # and the line end mark wants a green that stands out from the letters.
    "hardpurple": (110, 0, 200),
    # Measured on the four band tints: (0, 120, 0) gives a contrast of 5.04
    # against the period's 8.08; (0, 84, 0) gives 8.19, the same lightness as
    # the period. Kelly's, Trubetskoy's and Okabe-Ito's greens all sit under 5.
    "hardgreen": (0, 84, 0),
    # A darker teal for the comma: (0, 140, 150) reads faint on the tinted
    # bands. (0, 95, 105) gives a contrast of 6.54 on the lightest tint and
    # (0, 80, 89) gives 8.10, the period's own. No teal in the three palettes
    # reaches 4.
    "darkteal": (0, 80, 89),
    # Three inks from Kelly's 22 colours of maximum contrast. The comma and
    # the semicolon take the two that pass the period's contrast on every band
    # tint and sit farthest in CIE Lab from every other ink: strong violet at
    # 40.6 from the digit blue and deep yellowish brown at 38.8 from the
    # letters. The row edge, a bar and not a thin mark, takes vivid orange,
    # an unused hue 43 from the period's red.
    "violet": (83, 55, 122),
    "brown": (89, 51, 21),
    "orange": (255, 104, 0),
}

# The look-alike pairs. Each entry is one edge in a confusion graph and the
# colouring hands no two joined characters the same ink.
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
    # A reader takes a b or a d for 0 in a hex id when 0 and b share black and
    # 6 and d share green. These eighteen pairs join every pair of risky
    # characters that could share an ink, so no pair shares one.
    ("0", "b"), ("0", "4"), ("6", "d"), ("9", "O"), ("1", "a"), ("1", "b"),
    ("8", "l"), ("6", "o"), ("0", "q"), ("0", "B"), ("1", "5"), ("1", "2"),
    ("0", "2"), ("8", "D"), ("9", "G"), ("6", "g"), ("1", "q"), ("1", "B"),
    # A reader at 12 px writes b as o, and drops the d from "4d0" while 4
    # and d share magenta.
    ("b", "o"), ("4", "d"),
]

# The font the plugin ships, first on every platform, then the fallbacks.
#
# Inter ships in plugin/fonts under the SIL Open Font License. Verdana cannot
# ship, because its licence forbids bundling, so a machine without it would
# make a different image.
#
# ONE FONT. The image draws Inter and nothing else. The source text says which
# characters are bold. No table decides a character's face for it.
#
# INTER SEMIBOLD, weight 600. Inter Regular, weight 400, is the thinnest
# upright weight Inter ships, and it needs a heavy ink curve to read.
#
# Weight only reaches the page under the FONT'S OWN hinting. Measured at 11 px,
# the widest solid run inside an n:
#
#   hinting mode 2, the auto-hinter    400: 2 px   500: 2 px   600: 2 px
#   hinting mode 0, Inter's bytecode   400: 4 px   500: 4 px   600: 2 px
#
# The auto-hinter snaps every stem to the same whole pixel, so a 400 and a 600
# face draw the identical stroke and the heavier file buys nothing but width.
#
# Under mode 0 at 10 px, of the body ink:
#
#   Regular  400   solid 34.6%   grey 28.5%   648 tokens
#   Medium   500   solid 37.7%   grey 30.6%   588
#   SemiBold 600   solid 46.2%   grey 26.2%   594
#
# SemiBold carries a third more solid ink than Regular with less grey, for
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

# The sentence prompt_card.py sends once a session, split at the newline it
# already carries, so each half is edited on its own.
# Keep both sentences: a shorter card makes a reader think more over an image.
# Test any rewording on a bench, because the wording changes how much a reader
# thinks and whether a safeguard refuses the turn. The second sentence teaches
# the line pull.
_CARD_OPENING = (
    "A prompt, a report or a file may arrive as a picture of small text: "
    "read it and follow it. When a long number, a hash or a path in the "
    "picture does not read clean, pull that one line from the text by its "
    "green line number: Read with offset N and limit 1. A long file arrives "
    "as several png images named <folder>-<file>-image-N-of-M-DensePack.png, and the note "
    "beside image 1 names the others. "
    # CORRECTED 19 September 2026, measured both ways. Edit and Write both
    # ask one question: has this exact path been Read in this session? The
    # answer is recorded when the Read CALL is made, and it does not depend
    # on whether the result came back as text or as a picture, so both tools
    # work on a file DensePack swapped. The 16 September note here said
    # Write refuses such a file; a Write to a .md read as an image was
    # accepted, so that was wrong. A .doc or .docx is the real exception:
    # Claude Code rejects the Read before any hook runs, the path is never
    # marked as read, and BOTH tools refuse. Without this line an agent
    # loses turns finding that out.
    "To change a file that arrived as a picture, use Edit with the exact "
    "text you read off the picture, or Write with the whole new file. Both "
    "work. A .doc or .docx is the exception. Claude Code will not Read one, "
    "and Edit and Write both refuse it. DensePack converts one to images for "
    "you automatically. Read those images.")

# The code scheme card holds only what the key row on image one does not
# show. A longer card costs every image arm about 450 tokens on its first
# turn and makes the reader think more over the image.
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

# The suffixes pointer.py draws as banded code.
_CODE_SUFFIXES = [".py", ".gd", ".js", ".ts", ".c", ".h", ".cpp", ".rs",
                  ".go", ".java", ".cs", ".sh", ".ps1", ".rb", ".lua",
                  # Each of these reads back at 0.961 or better with line
                  # edges stripped, the same band as the types above.
                  ".html", ".css", ".mjs", ".bat", ".tscn", ".svg"]

# The suffixes the bands reach when band.text_files is on.
_TEXT_SUFFIXES = [".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".ini",
                  ".cfg", ".log", ".csv", ".rst"]


DEFAULTS = {
    # ---- font -------------------------------------------------------
    "font.regular": list(_REGULAR),
    "font.bold": list(_REGULAR),
    # One size for every reader, because one image serves every reader.
    "font.px": 12,  # 9 pt at 96 DPI
    "font.ident_px": 0,
    "font.min_ident_chars": 8,
    # The marks grow inside the cell the body glyph owns, so they push nothing.
    "font.bigger_px": 2.0,
    # The brackets grow inside the cell too, to at least the f's height, and
    # the row never grows for them.
    "font.bigger_chars": ["`", ",", ".", ";", ":", "(", ")", "[", "]", "{", "}"],
    # The marks that step by their ink instead of their face's advance, so a
    # mark does not carry a wide cell of white on both sides.
    "font.ink_step_chars": ["`", ",", ".", ";", ":", "\"", "\u201d", "'", "\u2019"],
    # The glyph renderer. "freetype" draws every character through FreeType
    # on every platform; any other value falls back to Pillow.
    "glyphrenderer": "freetype",
    # A size offset per character group, in pixels, added to the body size.
    # Half a pixel is a legal value: Pillow takes a float size. Every offset
    # is zero in the shipped renderer, so the page does not move.
    #
    # The six names are the ones densepack.group_for() hands back, and both
    # renderers look the offset up through it, so no name here is dead. The
    # backtick, the comma and the period all sit in lookalike.
    "font.group_px": {"body": 0.0, "lookalike": 0.0, "num": 0.0,
                      "sym": 0.0, "punct": 0.0, "nl": 0.0},

    # ---- one character, everywhere it appears ------------------------
    # The mark the flow uses for a line's indent count. codepack.py draws the
    # count as a red number after the line number.
    "mark.indent": "\ue001",
    # Clear columns between a band edge and the marks beside it, so a mark
    # touches neither the band outline nor the character beside it.
    # WHAT THE UNIT IS. Every spacing number in this file is layout columns.
    # codepack.py multiplies them by the shrink ratio, Shrunk.ratio, to get
    # image pixels. codepack.py holds the whole map of these constants in one
    # block above GAP; read it before changing any of them.
    "mark.clear": 3,
    # The white a count leaves before the word after it. At 2 a reader takes
    # the last digit of a long value for part of the next line's number box.
    "mark.count_clear": 3,
    # A file extension, the dot and the letters after it as in .jsonl or
    # .txt, draws black as one piece, so a reader keeps its last letter.
    "code.extension_black": True,
    "char.font_max_px": 12,  # the foot of this file sets the value that ships
    # WHAT YOU SEE HERE IS NOT ALWAYS WHAT AN IMAGE DRAWS WITH. The foot of
    # this file writes into DEFAULTS again after this literal, and the last
    # write wins. Print a setting rather than reading it off this literal:
    #   python -c "import sys;sys.path.insert(0,'plugin/scripts');import
    #   style;print(style.load()['char.overrides'])"
    #
    # char.overrides holds per-character entries keyed by the character. The
    # entry that ships is set at the foot of this file.
    #
    #   ink.scheme ships as "simple", and codepack.py takes simple_ink(ch) in
    #   that branch and never reads an entry's ink. simple_ink draws every
    #   digit blue and every letter black, so the 1 and the l are two colours
    #   apart.
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
    # The five inks the look-alike groups are handed, in the order the
    # colouring hands them out. These are the look-alike group colours.
    "ink.lookalike_groups": ["black", "blue", "green", "magenta", "orange"],
    # One ink for every character, with the bands carrying the meaning.
    # None keeps the per-group colours, which is what ships.
    "ink.universal": None,
    # The code ink scheme. "simple" draws letters in code.ink.name, digits in
    # code.ink.number and everything else in code.ink.op, with the look-alike,
    # reserved and per-character inks off. "lookalike" is the other scheme,
    # kept for a style.json that asks for it.
    "ink.scheme": "simple",
    # Under the simple scheme the marks a reader mixes up keep their own
    # ink: the dot family and the quote family. No two members of one family
    # share an ink; a share across the families is harmless.
    "ink.simple_punct": {
        # THE ROUND BRACKETS TAKE THE OPERATOR INK, (150, 0, 0). Black
        # brackets cost a reader the last clause of a string inside brackets,
        # and red brackets read in full on the same image.
        # Do not put "(" or ")" in this dict.
        ".": _INK["red"], ",": _INK["black"],  # black: a reader drops a violet comma
                         ":": _INK["blue"], ";": _INK["darkteal"],
                         '"': _INK["black"], "”": _INK["black"], "`": _INK["blue"],  # the closing quote takes the same black
                         "'": _INK["red"], "’": _INK["red"]},
    # A run of two or more underscores draws as the underscores, the first
    # red, the next blue, then red again, so a reader can count them.
    "ink.underscore_run": [_INK["red"], _INK["blue"]],
    "ink.confusable": [list(pair) for pair in _CONFUSABLE],

    # ---- palette, the three classes told apart by glyph -------------
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
    "code.ink.blank": (230, 0, 0),  # red: purple marks here cost a reader more output tokens
    "code.ink.wrap": (120, 0, 220),  # the wave purple; the marks stay green and red
    "code.ink.lift": (0, 130, 0),
    "code.lift_px": 0,
    # The width of the teal edge that says a source line runs into the next row.
    "code.wrap_width": 2,
    "code.suffixes": list(_CODE_SUFFIXES),
    # Empty: a tail block under a comma lands as a stray dot on the image,
    # and the font draws tails of its own.
    "code.tailed": [],
    # A run joined by underscore, hyphen or equals never breaks, so
    # "Things like=this" stays whole. A run wider than a whole row still
    # breaks at the row edge, because flow_rows() takes the width cut when
    # the walk back reaches the start of the row.
    "code.word_chars": "_.-/\\=",

    # ---- band -------------------------------------------------------
    # Eight depths, and no colour repeats past the last depth, because a
    # repeated colour reads as the top level. Each tint is written at twice
    # its distance from white, because band.strength below halves it. The
    # tints sit far apart from each other in CIE Lab, and black text keeps a
    # contrast of 12 or more on every one.
    "band.tints": [(255, 220, 212), (115, 223, 247), (150, 255, 150), (247, 143, 241),
                   (255, 177, 99), (255, 245, 145), (183, 195, 241),
                   (199, 151, 255)],  # eight depths
    # 1.0 draws the tint as written. Under 1.0 mixes it toward the image
    # background, over 1.0 pushes it away from the background. At 1.0 the
    # tints draw as hard as the letters on them.
    "band.strength": 0.5,
    # Whether a line at depth 0 draws on the first tint. True: the band
    # behind a top-level line helps a reader keep a thin last letter, such as
    # a final l.
    "band.top_level": True,
    # The band as a shape: pad grows or shrinks the band past the text on
    # each side, offset moves it, both in pixels.
    # The space between a band's left edge and its first letter, in pixels,
    # so the outline does not touch the first glyph. The band grows by the
    # same amount on the right so the last letter keeps its room.
    "band.text_inset": 4,
    # White between bands. gap_y is the white rows between one band and the
    # one under it, taken from the spare pixel every row holds under its
    # descenders, so it costs no height; gap_x is the white columns between
    # two blocks in one row, kept out of the block gap. space.row_gap adds
    # real rows between bands and costs height.
    "band.gap_x": 1,
    "band.gap_y": 1,
    # Every band grown on one side at once, in pixels.
    "band.grow_l": 0,
    "band.grow_r": 0,
    # CENTRING THE TEXT IN ITS BAND. band.grow_b 1, band.pad_y 0 and
    # band.centre_text together centre the ink in its band. Each alone leaves
    # the text off centre, and grow_b alone merges neighbouring bands.
    "band.grow_t": 0,
    "band.grow_b": 1,
    # At 0 the first character of a line sits on the band outline. The band
    # widens both sides at once, so nothing moves into the right outline.
    "band.pad_x": 3,
    # The rows of band kept clear above the tallest ink of a row and below the
    # lowest, so no glyph sits on its band's edge.
    #
    # It grows the ROW, not the band. band.grow_t and grow_b move the band edge
    # without moving the glyph, so the band reaches into the row gap and
    # neighbouring bands merge. The room has to come from the row height, and
    # it costs image height.
    # It also insets the wrap mark from the band's top and foot, so the mark
    # does not touch the bands above and below.
    #
    # ANCHOR IT TO THE BAND, NOT TO y. The band starts at y + band.offset_y, so
    # an inset measured from y is cancelled when band.offset_y moves.
    "band.text_clear": 1,
    # THE BAND CENTRES ITSELF ON THE TEXT. A fixed band.offset_y trades the
    # clear rows above the text against those below, two rows of balance per
    # unit, and the right value depends on the glyph size.
    #
    # With this on, the offset is derived per draw from where the face's ink
    # really falls, measured over a set carrying the tallest ascenders and the
    # lowest descenders rather than taken from the nominal ascent and descent,
    # which reserve room the face does not always use. band.offset_y is then
    # only the manual override, for a caller that wants the band off centre.
    "band.centre_text": True,
    # False fits the box round a line number to its own digits on all four
    # sides. True takes its top and bottom from the band. The foot of this
    # file sets the value that ships.
    #
    # Levelness across a row holds either way: every box holds digits, and
    # digits all ink the same rows, so a box fitted to its own ink lands at the
    # same height as its neighbours.
    "mark.box_fits_band": False,
    # IT IS SIZE DEPENDENT AND MUST BE RE-MEASURED WHENEVER CODE_PX CHANGES.
    # The band moves as one, so this trades the clear rows above the text
    # against the clear rows below, two rows of balance per unit.
    #
    # The line number box can take its height from the band, so whatever
    # imbalance the band carries the box carries too.
    #
    # 0 keeps the text centred in its band. A negative value lifts the band
    # off the text and sets every descender on the band's bottom edge.
    "band.offset_y": 0,
    "band.pad_y": 0,
    "band.offset_x": 0,
    # Objects placed by hand. Keyed "line:N" for source line N and its band
    # together, "band:N" for the band alone, and "word:N:K" for the K-th word
    # of line N. Each holds dx and dy in pixels, and a band or a line may hold
    # grow_l, grow_r, grow_t and grow_b, the pixels its band grows on that
    # side. Empty ships, so nothing moves.
    "layout.placements": {},
    "band.outline": (150, 150, 150),
    "band.outline_width": 0,  # no grey border around a band
    # True: a text file draws through the code renderer, the one with the ink
    # curve, the glyph clearance and the per-character inks. Readers copy
    # more hard values off it than off the plain pack.
    "band.text_files": True,
    "band.text_suffixes": list(_TEXT_SUFFIXES),

    # ---- page -------------------------------------------------------
    # The drawn width of one page column. 580 is the shipped page: 560 of
    # text, 6 of padding a side and 8 the draw loop adds. A4 is 794.
    # The image ends at its widest row: the white past the last letter of
    # the widest row goes, and the patch grid still rounds the size up when
    # page.patch is above 1.
    # page.snap_glyphs True lands a glyph's shrunk mask on a whole output
    # pixel at its own width, the way a rectangle lands, so a stem sits in
    # one column and more ink draws at full strength. False shrinks each
    # glyph's sub-pixel remainder into the mask.
    "page.snap_glyphs": True,
    # page.glyph_at_final_size True asks FreeType for each glyph at the size
    # it lands at, so hinting acts at that size and no glyph is resized after
    # it is hinted.
    "page.glyph_at_final_size": True,
    "page.supersample": 3,
    # The layout width. It equals page.code_width, so each glyph is drawn on
    # the grid it ships on and nothing is rescaled. See common.CODE_PX.
    "page.code_layout_width": 756,
    # The glyph grows into the white under the last band while the padded
    # image keeps its height, on one-image files only; codepack._fill_bottom.
    "page.fill_bottom": True,
    # page.key_row False draws image one with no key row at its head. The
    # image ships with the row.
    "page.key_row": True,
    # 1: supersampling draws the glyph large and takes the mean of the pixels
    # on the way down, which is the opposite of what a hinted small glyph
    # needs. The hints fit the outline to the pixel grid at the target size,
    # and the shrink averages that fit away.
    "page.code_supersample": 1,
    "page.code_width": 756,
    # THE TWO IMAGE WIDTHS THE FIT SEARCH TRIES. Both are whole 28 px patches,
    # 27 and 28 of them, so neither adds a white column. The layout width
    # follows the image width on every trial, so the shrink ratio stays 1.0
    # and no glyph is scaled after FreeType hinted it.
    #
    # WHAT THE SEARCH COSTS. Each width runs the whole ladder, _fill_bottom()
    # to grow the glyph down and then _fit_width() to grow the layout, so two
    # widths is more than two draws. The reader never pays that, it is build
    # time, but a slow hook keeps the reader waiting.
    #
    # WHAT IT BUYS. read_gate.py costs 1,975 visual tokens at 756 and 1,964
    # at 784, so the search saves 11 there.
    #
    # A list of one width draws at that width and compares nothing, which is
    # the switch to throw if the wait matters more than the tokens. An empty
    # list leaves page.code_width alone.
    "page.code_width_choices": [756, 784],
    # A taller cap holds more text on one image; a lower cap sends larger
    # files out as more images. The foot of this file sets the value that
    # ships.
    "page.code_height": 2000,
    # Images per row on a delivery sheet. 1 gives every image its own row, so
    # a file arrives as single column images and a reader never reads across a
    # seam. 0 fits as many across as page.edge allows, which puts two 756 px
    # images on a 1512 px sheet.
    #
    # A two column sheet costs a reader its answers. On the 16-file bench
    # Sonnet answered 3 of 5 on two column sheets and 5 of 5 on single column
    # images, and Opus went from 48.4% saved to 64.7%. Every pair below counts
    # at both prices, 5 of 5 on both arms:
    #
    #   16-file Sonnet  59.3%     32-file Sonnet  72.7%
    #   16-file Opus    64.7%     32-file Opus    75.3%
    #
    # It costs nothing. A file is ceil(w/28) * ceil(h/28) visual tokens either
    # way, so two 784 px images and one 1568 px sheet of the same height are
    # the same count. drop_read_gate.py measures 7,224 tokens wide and 7,168
    # narrow.
    #
    # The stack passes page.edge, so composite_grid() returns None and the
    # pages ship one to an image. Coverage is unchanged: drop_read_gate.py
    # opens at line 1 and its last image at line 577 at either value.
    "page.grid_per_row": 1,
    # The supersample by source size, [up to this many characters, s],
    # 0 meaning no limit. A high supersample on a large file can pass the
    # hook's time limit.
    "page.code_supersample_tiers": [[0, 12]],
    # The filter the shrink uses: box, bilinear, hamming, bicubic or lanczos.
    "page.supersample_filter": "hamming",
    "page.trim": True,
    # A row the word safe cut would leave emptier than this share of
    # its width takes the width cut instead, so rows run to the right
    # edge and the wrap edge marks the cut. 0 keeps every row word safe.
    "page.fill": 0,  # 0: a larger share cuts words such as transcript.jsonl across rows
    "page.width": 336,
    # The height one page column may reach. A4 is 1123.
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
    # PRIVATE-USE CODE POINTS. No text holds U+E000 to U+E003, so a user's own
    # arrow, dagger, pilcrow or section sign draws as itself.
    # codepack.drawn() maps the tab mark to the arrow glyph and the underscore
    # mark to the dagger.
    "mark.count": "\ue001",
    "mark.pilcrow": "\ue000",
    # The line break and its blank count take hard green; the indent count
    # takes red.
    "mark.pilcrow_ink": _INK["hardgreen"],
    # The ink of the blank line count after the line-break mark.
    "mark.count_ink": _INK["hardgreen"],
    "mark.box_ink": (0, 0, 0),
    # The room the line break leaves before the next line number's box:
    # the last character's own clear column, the band edge past it and
    # the white before the box. At 3.5 a few boxes keep a single image pixel
    # of white on the left, the side the previous line's last character
    # arrives on, and a reader misreads a digit there. 5.5 clears them.
    "mark.box_gap": 5.5,
    # White, the seam rule and white between a green line number and a
    # red indent count. 2.5 leaves no rule touching a digit. A few sit at two
    # columns on one side, because a digit's own bearing moves the white run
    # by a column and one constant cannot hold every pair at three columns.
    "mark.seam_gap": 2.5,
    "mark.box_clear": 2,  # white between the mark box and the band after it
    # PAPER THE WRAP MARK KEEPS FROM THE LAST CHARACTER'S INK, in image pixels.
    #
    # HOW THE MARK IS PLACED. The draw loop puts it at the row's end plus
    # band.pad_x, band.text_inset and mark.clear, and the row's end is the SUM
    # OF THE ADVANCES. A glyph whose ink fills its own advance, and w, e, ]
    # and / all do, inks right up to that point, so the wave lands a pixel off
    # it while a row ending in a narrow glyph gets plenty of room. This
    # setting is a FLOOR measured from the ink itself, so it moves only the
    # rows that are tight and leaves the rest alone.
    #
    # RAISING mark.clear INSTEAD IS THE TRAP. It moves EVERY mark, so the
    # layout needs a wider row everywhere and the image grows. Measured on
    # one file with 38 end-of-row marks, in visual tokens:
    #
    #   mark.clear 3   5 marks tight   840 tokens
    #   mark.clear 4   3 marks tight   918 tokens
    #   mark.clear 5   3 marks tight   918 tokens
    #   mark.clear 6   1 mark  tight   918 tokens
    #
    # so it buys 9.3 per cent more page and still never reaches zero.
    "mark.wrap_ink_clear": 3,
    # codepack.py skips the line end mark before it asks for a glyph.
    # The line end mark sits outside its band, in the white between one
    # block and the next. The band stops one pixel before the mark; the mark
    # does not move.
    "mark.pilcrow_outside": True,
    # Empty: the count after a line end says the blank lines by itself, in
    # the mark ink, in the white between bands. A dot here puts a mark after
    # the count.
    "mark.blank": "",
    # The count and the mark, in the order they draw. "%(count)d%(mark)s"
    # is the shipped run: the digits, then the bullet.
    "mark.blank_format": "%(count)d%(mark)s",
    "mark.underscore": "\ue003",
    "mark.tab": "\ue002",

    # ---- spacing ----------------------------------------------------
    # THE HORIZONTAL SCALE. Below 1.0 every letter is condensed and its height
    # is kept. It reaches FreeType as face.set_char_size(width = size * scale,
    # height = size), so this is a real outline scale rather than a resample,
    # and the x-height does not move. FreeType hints at that aspect, so stems
    # are grid fitted at the width they land at.
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
    # The column is not a trend and must not be read as one. Condensing moves
    # each outline against the pixel grid, so a value either happens to land
    # stems on whole pixels or happens to scatter them: 0.95 is worse than both
    # its neighbours and 0.75 collapses the ink. Every value has to be measured
    # rather than interpolated.
    #
    # IT APPLIES TO LETTERS ALONE.
    # A letter has width to spare: at 12 px an n is 7 px across, so 0.85 costs
    # it one column in seven. Punctuation is two or three pixels across, where
    # the same fraction is most of the mark, and a digit has to stay apart from
    # every other digit. Both draw at full width. See face_for() in codepack.
    # The foot of this file sets the value that ships.
    "font.scale_x": 0.769231,
    # The only uniform spacing control: char_widths() adds it to every pen
    # step, so every pair widens by the same amount and the rhythm the font
    # designer drew is kept. It must be a WHOLE number: char_widths() rounds
    # own + LETTER_SPACE to a whole pixel, so a fraction rounds up on some
    # characters and down on others and makes the gaps uneven.
    "space.letter": 1.0,
    "space.letter_text": 0.0,
    "space.word": 0.0,
    "space.line_gap": 0.85,
    "space.line_factor": 1.2,
    # The white after a line end holds the band's right edge, a clear
    # column, the mark, a clear column and the next band's left edge;
    # 4 is enough.
    "space.block_gap": 8,
    # The white rows BETWEEN two bands. 2 keeps every gap uniform and spends
    # little of the row pitch on white. Measured at 10 px, the gap the image
    # draws and what the image costs:
    #
    #   row_gap 4   gaps 4 px on 35 of 38   728 visual tokens
    #   row_gap 3   gaps 3 px on 37 of 40   675
    #   row_gap 2   gaps 2 px on 35 of 38   644
    #   row_gap 1   gaps 1 px on 38 of 40   594
    #
    # Band height stays the same at every value, so glyphs and baselines do
    # not move. More text still takes more rows, then a taller image to the
    # height cap, then a new image; the rows are pitched closer, so more fit.
    # THE GLYPH SIZE THE ROW IS BUILT FOR, when that is not the glyph size
    # itself. Zero, which ships, means the row follows the glyphs as it always
    # has. Set it beside font.scale_x to raise the x-height without growing
    # the page: 17 px condensed to 0.588 draws an x-height of 10 in the column
    # a 10 px face uses, and space.row_px 10 keeps the band at its 10 px size.
    # codepack.py carries what that costs, which is ascenders reaching into
    # the band above.
    "space.row_px": 10,
    # THE MARKS DRAWN AT FULL WIDTH, not condensed by font.scale_x and not
    # given the extra height the larger size carries.
    #
    # codepack reads this twice. scale_for leaves them uncondensed, and
    # face_for offsets their size back to space.row_px, so a bracket on a
    # 13 px page is the 10 px bracket it always was while the letters beside
    # it are 13 px condensed to the same column width.
    #
    # The period, comma, semicolon and colon are deliberately NOT here: they
    # draw a size larger through font.bigger_chars.
    # The size the full width marks draw at. Zero means the page's own
    # size. 12 on a 13 px page draws them one pixel below what the
    # letters are asked for, and they are not condensed by font.scale_x,
    # so they keep their full width at that size.
    'font.mark_px': 12,
    # How much of a bracket's hang below the baseline is taken back. 1.0 lands
    # its ink on the baseline, 0.0 leaves it where Inter draws it, on the
    # mathematical axis. A full lift puts brackets too high at the shipped
    # sizes, so this is a share.
    'mark.baseline_lift': 0.4,
    # One size for one mark, when the set's own size does not suit it. The
    # pipe is the tallest mark on the page and reads a size above everything
    # around it, so it draws one smaller than the rest.
    'font.mark_px_by_char': {'|': 11},
    # The marks that condense WITH the letters rather than keeping their
    # own width. The opening quotes only: the second quote of a kind on a
    # line draws as its closing form, and those keep their width.
    'font.condensed_marks': ['"', "'", '’'],
    # Rows one character moves down, negative to raise it. A closing double
    # quote sits lower in its em than the opening one, so the two do not line
    # up on a row. The glyph is drawn where its designer put it, so the page
    # moves it.
    "font.dy_by_char": {},
    # THE MARK BOX TAKES THE BAND'S HEIGHT. A box fitted to its own digits is
    # shorter than the band, so its outline sits inside the row and the digits
    # meet it. Taking the top and bottom from the band gives the digits room.
    # False fits the box to its own ink.
    "mark.box_fits_band": True,
    # One character's own horizontal scale, which beats every group. Use it to
    # move a single mark off its group's column without inventing a group.
    "font.scale_x_by_char": {},
    # The marks that draw at the page's own size and condense to
    # font.scaled_mark_scale_x. They sit between the letters, which condense
    # hardest, and the marks that keep their full width at a size of their
    # own. The closing DOUBLE quote is deliberately absent: the design keeps
    # that one at its own width. Zero scale means the group does nothing.
    "font.scaled_marks": ["%", "#", "?", "{", "}", "[", "]", "(", ")",
                          '"', "'", "’"],
    "font.scaled_mark_scale_x": 0,
    # The width a digit condenses to, as a share of its own. Zero means
    # a digit keeps its full width. Separate from font.scale_x because a
    # digit has to stay legible against every other digit: 12/17 draws a
    # 17 px digit at the width a 12 px one has, where a letter goes to
    # the width of a 10 px one.
    'font.digit_scale_x': 0,
    "font.full_width_chars": ["(", ")", "[", "]", "{", "}", "|", "\\", "/",
                              "%", "<", ">", "+", "=", "*", "&", "^", "$",
                              "#", "@", "!", "?", "~", "-"],
    "space.row_gap": 2,  # 2: with band.pad_y 1 each side, one clear row of white between bands and the page no taller
    # The edge knob. curve.blur is the edge: none draws every ink pixel or
    # nothing, ring keeps one blended ring, full keeps the blend as the font
    # draws it, auto follows the curve name. It reaches only the Pillow path,
    # through _lut(); a shipped image draws every glyph through FreeType.
    "curve.blur": "auto",
    # A small image draws its glyphs with the font's own grey ramp. The step
    # curve quantizes a 10 px stroke to three levels and reads as blobs.
    "curve.small_px": 12,
    "curve.small_name": "soft",
    # The step threshold on a small image, lower than the 128 of larger
    # images so a one pixel stroke under half ink still draws instead of
    # breaking into stubs.
    "curve.small_threshold": 96,
    "space.paragraph_gap": 0,
    # The pen distance from the last inked column of one glyph to the first
    # of the next, so 2 is one white column between them, narrow letters too;
    # the underscore mark keeps mark.clear through codepack.py.
    "space.clear": 2,
    "space.clear_narrow": 2,
    # The pen distance between two quote marks of the same kind in a row,
    # so a docstring's three curly quotes read as three.
    "space.quote_run_clear": 2,  # quotes space like letters
    # The pen distance between two of the same letter in a row, so the
    # crossbars of the two f in "off" do not join.
    "space.same_clear": 3,
    # A stem, l I 1 i or |, beside a quote keeps this many columns clear, so
    # the bar of an l and the bars of a quote do not read as one mark.
    "space.stem_quote_clear": 2,  # the foot of this file sets the value that ships
    # Clear columns after a mark that steps by its ink, the period, comma,
    # colon, semicolon and backtick, so its right side keeps the white its
    # left side has. 3 grows no image; 4 adds one wrapped row to most images,
    # about 3 per cent of their tokens.
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
    """The JSON file, beside densepack-settings.json. No folder is created.

    DENSEPACK_STYLE names another file instead, so a preview can draw
    without touching the file the live plugin reads.
    """
    named = os.environ.get("DENSEPACK_STYLE")
    if named:
        return Path(named)
    # Outside the project: a cloned project could commit a style file that
    # draws one character as another, so the image would not match the file.
    # Under the home folder, never CLAUDE_PLUGIN_DATA: bash_pack.py and the
    # tuner run without that variable and must draw with the same style file
    # the hooks read. One folder per project, named by a hash of its path.
    base = Path.home() / ".claude" / "densepack-state" / "projects"
    try:
        import hashlib
        from common import project_dir
        key = hashlib.sha256(str(project_dir().resolve()).lower().encode("utf-8")).hexdigest()[:16]
        return base / key / STYLE_FILE
    except Exception:  # noqa: BLE001
        return base / STYLE_FILE


def _rgb(value):
    """A colour as Pillow wants it. JSON hands back a list; PIL draws a tuple."""
    if isinstance(value, list) and 3 <= len(value) <= 4 and all(
            isinstance(v, (int, float)) for v in value):
        return tuple(int(v) for v in value)
    return value


def _coerce(key, value, default):
    """One override, shaped like the default beside it."""
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
    """Every tunable value, the defaults with style.json laid over them."""
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
    """A value as JSON writes it, so a tuple and its list compare equal."""
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def demo():
    """The self check: defaults survive a round trip and an override lands."""
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
# The image draws Inter, from plugin/fonts/Inter-SemiBold.ttf, at one size,
# for every reader. font.regular and font.bold both name that one file, so
# the source text alone decides which run is bold. Print the path rather than
# trusting a comment:
#   python -c "import sys;sys.path.insert(0,'plugin/scripts');import
#   densepack as dp,common;print(dp.load(dp.REGULAR,common.CODE_PX).path)"
# A thin letter is carried by the ink curve in plugin/scripts/freetype_glyph.py,
# not by a per-character table.
#
# WHAT char.overrides MAY HOLD
#   ink      the colour rule, which carries the meaning of the image.
#   glyph    the character drawn in place of another.
#   adv      extra width after a character.
# An entry holding font, px, scale_x, dy, bold, thick or weight gives one
# character its own face, which the one font design does not allow.

# THE LINE END MARK DRAWS NOTHING.
#
# The green line number says where a line starts, so a line end mark says
# nothing the number does not. codepack.py does not draw the mark:
# char_widths() charges the blank width outright, the draw loop skips the mark
# before it asks for a glyph, and the box test treats it as inkless. The mark
# is still in the flow, because it carries the band, the row break rule, the
# band edge and the line id; it is not a character a reader sees.

# THE DOT MARKS DO NOT DRAW BOLD. The embolden widens a mark across and caps
# the vertical widening at half a pixel below 15 px, so a two pixel period
# widens into a bar and closes the gap to the letter after it.

# THE CLEAR RULES. These add columns between two characters. Inter already
# spaces its own letters, and a gap of 3 next to a gap of 6 does not read as
# one word, so three of the five stay at zero. Inter's own alternates answer
# a look-alike glyph instead.
DEFAULTS["space.same_clear"] = 0
DEFAULTS["space.quote_run_clear"] = 0
# 5 keeps clear columns between an l and a closing quote, so a reader keeps
# the l of jsonl". codepack.STEM_CLOSERS holds both closing quotes, so the
# rule reaches the curly one. 6 moves wraps.
DEFAULTS["space.stem_quote_clear"] = 5

# space.clear and space.clear_narrow are FLOORS, at 2 and EQUAL.
#
# The value is the pen distance from the last inked column of one glyph to
# the first inked column of the next, so 2 leaves one white column between two
# glyphs that would otherwise touch. Under the hinter some pairs ink right up
# to their advance, and a pair whose ink is adjacent reads as one shape.
#
# WHY THEY MUST BE EQUAL. clear_narrow applies whenever either glyph inks
# space.narrow_cols columns or fewer, which is every i, l, t, f, r and j. A
# larger clear_narrow opens a hole around exactly those letters and breaks
# words apart.
#
# WHY THE GAP IS NOT EXACT. space.ink_gap_exact sets the same ink to ink
# distance for every pair. A letter whose ink fills its advance (n, o, a, b)
# then keeps Inter's step while a letter whose ink sits well inside it
# (f, r, t, i, l, /) is pushed a whole pixel wider. Measured over 2,471 pairs
# against the step Inter designs:
#
#   exact on    spread 0.526 px, worst pair 2.83 px from its neighbour
#   exact off   spread 0.268 px, worst pair 1.01 px
#
# So the rule stays off and the font's own advances decide the rhythm.
DEFAULTS["space.ink_gap_exact"] = False
DEFAULTS["space.clear"] = 2
DEFAULTS["space.clear_narrow"] = 2

# THE PUNCTUATION DRAWS LARGER. A comma, a colon, a slash and a brace are a
# handful of pixels, so one pixel is a small share of the type but a large
# share of the mark.
#
# THE IMAGE DOES NOT GROW, and the mechanism guarantees it.
#
#   char_widths() takes the pen step and the clear columns from the BODY face,
#   never the larger one, so the cell is the cell the small glyph owned. The
#   test at codepack.py face() reads "p[0] not in BIGGER", which deliberately
#   hands a BIGGER mark the body face for its cell while the draw uses the big
#   flag. The layout with the marks on is the layout with them off.
#
#   Vertically the larger face has a taller ascent, so a marked glyph starts
#   that many rows higher and grows UPWARD into the clear rows the row already
#   reserves above the type. Nothing below the baseline moves and no row
#   changes height.
#
#
# No letter and no digit is in the set. The underscore is absent on purpose:
# it is drawn by under_bar() as a rectangle taken from the font's own
# footprint, not as a glyph, so the bigger face would never reach it.
# 2 pixels larger.
DEFAULTS["font.bigger_px"] = 2
# THE FOUR DOT MARKS ARE IN THIS SET. Nothing draws bold, so a larger dot
# mark stays a dot rather than a wide square.
DEFAULTS["font.bigger_chars"] = [
    "'", '"', "`", "’", "”",
    "|", "\\", "/", "(", ")", "[", "]", "{", "}",
    "-", "=", "+", "<", ">", "*", "&", "^", "%", "$", "#", "@", "!", "?", "~",
    ".", ",", ";", ":",
]
DEFAULTS["font.ink_step_chars"] = []

# The bold face is the same file as the regular face.
# A bold run is drawn by emboldening the outline, which
# plugin/scripts/freetype_glyph.py does with FT_Outline_EmboldenXY.
DEFAULTS["font.bold"] = list(DEFAULTS["font.regular"])

# THE UNDERSCORE DRAWS ITS OWN GLYPH. Inter's own underscore is a solid bar,
# and the ink curve in freetype_glyph.py carries it to full ink, so extra rows
# on a drawn bar only make it heavier than the letters beside it.

# NO CAP ON THE GLYPH SIZE. A cap would only stop the image being drawn at a
# larger size on purpose.
DEFAULTS["char.font_max_px"] = 0

# Nothing is scaled after hinting. backend_text() in codepack.py reads
# page.glyph_at_final_size and asks FreeType for the glyph at the size it
# will land at.

# THE IMAGE CEILING. 1596 px is 57 patches on a side. An image at or under it
# is not resized by the client or the API.
DEFAULTS["page.code_height"] = 1596

# ONE INK CURVE. The backend's curve in freetype_glyph.py is the only one, so
# the curve in codepack is off and two curves never stack on the same pixels.
DEFAULTS["curve.name"] = "none"
DEFAULTS["curve.small_name"] = "none"

# FreeType draws every character, on every platform.
DEFAULTS["glyphrenderer"] = "freetype"


# THE SHIPPED RECIPE. These values with common.CODE_PX at 17 draw the image
# every bench scores.
DEFAULTS['font.scale_x'] = 0.5882352941176471
DEFAULTS['font.digit_scale_x'] = 0.7058823529411765
DEFAULTS['font.scaled_marks'] = ['%', '#', '?', '{', '}', '[', ']', '(', ')', '"', "'", '’']
DEFAULTS['font.scaled_mark_scale_x'] = 0.7058823529411765
DEFAULTS['space.row_px'] = 13
DEFAULTS['font.mark_px'] = 16
DEFAULTS['font.mark_px_by_char'] = {'|': 14, '”': 14, "'": 18}
DEFAULTS['mark.baseline_lift'] = 0.4
DEFAULTS['font.scale_x_by_char'] = {'"': 0.6470588235294118, "'": 0.6666666666666666, 'l': 0.7058823529411765, ',': 0.7058823529411765}
DEFAULTS['font.dy_by_char'] = {'”': -3, '(': 1, ')': 1, '[': 2, ']': 2, '{': 2, '}': 2}
DEFAULTS['mark.box_fits_band'] = True
DEFAULTS['char.overrides'] = {'(': {'adv': 1}}
