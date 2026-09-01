"""The engine. Turns a wall of text into one small picture.

HOW THIS FILE FITS, in plain words: everything else here is plumbing, this is
the machine the plumbing feeds. It lays the words out in tiny type, colors the
characters that look alike so they cannot be confused, keeps the image inside
the exact size the AI reads without shrinking, and saves it as a PNG. It is a
faithful port of the DensePack browser app in the folder above, same rules,
same colors, same measurements.

ORIGINAL NOTE: Pack text into the smallest image the reader can still read.
The size comes from the reader profile: 8 px for Fable 5, 10 px for Opus 5,
set by /fablepack and /opuspack. --size overrides it.

A port of the browser app in the folder above, so a script, a right-click or an
agent can do the same job with no browser. Same constants, same layout, same
color coding, same downscale check.

    python densepack.py report.md
    python densepack.py report.md --size 11 --out packed
    some-command | python densepack.py - --out packed

Writes packed-1.png and so on, prints one line per file, and prints the token
comparison so the saving is a number rather than a claim.
"""

import os
import argparse
import hashlib
import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# The API's real limits, taken from the app. The app follows the resize rule
# Anthropic publishes rather than guessing at it; this file holds only the
# constants that rule produces, not an implementation of it. They are the same for every model on
# the high-resolution tier, so they do not change with the reader profile.
# The API accepts 2576 px on the long edge for a single image, but a request
# holding more than 20 images gets a stricter limit: any dimension over
# 2000 px is shrunk, and shrinking destroys text this small. A busy session can
# queue more than 20 packed reports, so every image is built under 2000 on
# both sides. 1988 is 71 patches of 28 px, the largest patch-aligned edge
# under that limit. This rule was set; recorded here 16 August 2026.
EDGE = 1988        # longest side this packer will produce
MAX_TOK = 4784     # most patches the API accepts per image
CAP_W = 1932       # largest guaranteed-no-downscale canvas
CAP_H = 1932
RATIO = 1.0        # a square uses the token budget best

# Below the floor, digits misread even in color. 6 px returned "#2___5" for a
# 5 digit number. The floor is per reader, from the readability tests: two cold
# Fable 5 readers scored 10 of 10 at 8 px on 14 August 2026, two cold Opus 5
# readers scored 10 of 10 and 12 of 12 at 10 px on 18 August 2026, where 8 px
# scored 1 of 10 and 9 px scored 6 of 10, and Sonnet 5 scored 12 of 12 twice
# at 12 px on 25 August 2026, where 11 px swapped two answers, 10 px dropped
# a word from two, and 8 px invented a file name. FIXED 29 August 2026:
# "sonnet" was missing from this dict entirely, so pack() below had no floor
# to enforce for Sonnet callers and RISKY_DEFAULT, Fable's 8 px, the smallest
# of the three, silently stood in for it.
# Haiku 4.5 has no floor here and gets no image at all, measured 31 August 2026:
# two cold Haiku readers scored 1 of 10 and 1 of 10 at 12 px on a 7,546
# character archived report, and both invented well shaped wrong numbers rather
# than reporting UNREADABLE. bench/HAIKU-READER-FLOOR.md holds all twenty
# answers. A larger floor would not fix it, so Haiku reads plain text.
RISKY = {"fable": 8, "opus": 10, "sonnet": 12}
RISKY_DEFAULT = 8  # the floor used when the reader profile cannot be read

# 29 August 2026: pack() used to draw whatever `size` it was given, so a
# caller that computed the wrong px for its own reader, or a fallback that
# guessed low, produced an image below the floor two cold readers were
# actually scored against. No agent should be handed an image it was never
# scored to read. pack() below now takes the reader as well as the size and
# refuses to draw under that reader's own RISKY floor: it draws at the floor
# instead and prints one line to stderr recording that it did, so a caller
# or a test can see the clamp happened without pack()'s return value
# changing shape for the callers that already unpack it.
FLOOR_NOTE = ("DensePack: %d px requested for %s is under its measured "
              "%d px floor. Drew at %d px instead.")

PATCH = 28         # one visual token is one 28 by 28 patch
PAD = 2
# Characters per token for the text this plugin packs. THE SINGLE SOURCE:
# every script in plugin/scripts, tools/ and bench/ reads this name rather
# than writing a number of its own. index.html and tools/densepack-clip.ps1
# cannot import Python, so they carry the value with a comment naming this
# line, and tests/test_divisor_agreement.py fails if any of them drift apart.
#
# Measured 31 August 2026 against Anthropic's count_tokens endpoint, model
# claude-opus-5, over 92 archived packed source texts drawn evenly across the
# whole vault, 860,637 characters against 357,951 counted tokens: 2.4043. A
# second sample balanced by kind rather than by traffic, 90 texts and 559,234
# characters against 232,893 tokens, read 2.4012. Both round to 2.40, over
# five times the character volume behind the earlier figure. A one character
# message is counted first and its wrapper subtracted from every figure.
#
# The value stood at 4 until 24 August 2026, then at 2.65 from a sample of 28
# agent reports only. 2.65 was too high because the constant does not price
# reports only: it prices bash output, briefs and file reads on the same line,
# and bash output is most of what the plugin packs. By kind, in the traffic
# weighted sample: bash output 2.37, agent reports 2.60, briefs 2.79.
CHARS_PER_TOKEN = 2.40
# The date above, as a value rather than as prose, so a page that prints the
# constant can print when it was measured without re-typing the date.
CHARS_PER_TOKEN_MEASURED = "31 August 2026"

# What one image content block costs on top of its patches. Measured the same
# day on 28 packed PNGs, 418x412 up to 1144x1168: the counted token figure was
# the patch count plus exactly 2, at every size.
IMAGE_BLOCK = 2

# Every pair of characters that look alike in small type. Each entry is one
# edge in a confusion graph, and the coloring below gives no two characters
# joined by an edge the same color. Written as pairs so a reader can check one
# without reading the whole map.
#
# The list started from the standard small-type look-alikes and gained every
# pair a reader actually confused in the tests of 25 August 2026: 8 read as 3
# and as 9, 9 read as 0, 5 read as 3, O read as D, S read as D.
CONFUSABLE = [
    # digit against digit. Every wrong answer in the reading tests was one of
    # these, and the old palette gave all ten digits the same blue.
    ("0", "6"), ("0", "8"), ("0", "9"), ("1", "7"), ("1", "4"),
    ("2", "7"), ("3", "5"), ("3", "8"), ("3", "9"), ("4", "9"),
    ("5", "6"), ("6", "8"), ("6", "9"), ("8", "9"),
    # digit against letter
    ("0", "O"), ("0", "o"), ("0", "D"), ("0", "Q"),
    ("1", "l"), ("1", "I"), ("1", "i"),
    ("2", "Z"), ("2", "z"), ("5", "S"), ("5", "s"),
    ("6", "b"), ("6", "G"), ("7", "T"), ("7", "t"),
    ("8", "B"), ("9", "g"), ("9", "q"),
    # letter against letter
    ("l", "I"), ("l", "i"), ("I", "i"),
    ("O", "Q"), ("O", "D"), ("O", "C"), ("O", "o"), ("D", "Q"), ("Q", "C"),
    ("Q", "G"), ("C", "G"), ("C", "c"), ("S", "s"), ("O", "0"),
    ("c", "e"), ("c", "o"), ("a", "o"), ("a", "e"),
    ("m", "n"), ("n", "h"), ("h", "b"), ("b", "d"), ("d", "cl"[0]),
    ("u", "v"), ("v", "y"), ("V", "Y"), ("U", "V"),
    ("g", "q"), ("q", "p"), ("f", "t"), ("j", "i"),
    ("K", "X"), ("M", "N"), ("E", "F"), ("P", "R"),
    # the vertical bar against the tall thin group
    ("|", "1"), ("|", "l"), ("|", "I"), ("|", "i"),
]

# Nine colors, spread around the hue circle so no two are close, and each one
# dark enough to stay itself when the type is antialiased at 8 px.
INK = {
    "black":   (0, 0, 0),
    "blue":    (0, 60, 210),
    "green":   (0, 150, 60),
    "magenta": (195, 0, 140),
    "orange":  (205, 100, 0),
    "teal":    (0, 140, 150),
    "red":     (150, 0, 0),
    "purple":  (110, 0, 200),
    # JOB 2, DensePack brief 29 August 2026. A tag lift_identifiers() invents,
    # such as [#3], used to draw with the ordinary per-character classes: '['
    # and ']' and '#' as sym (red), the digit as num (blue). A literal [#1]
    # a source string already carried, a footnote or an issue reference,
    # drew in that exact same red-blue-red, so a reader had no way to tell a
    # marker the packer invented from one the source text already held.
    # "lime" sits 210 apart, on the sum of the three channel differences,
    # from every one of the eight colors above, the same bar this file's own
    # comment already accepts as the closest any two of them come. Searched
    # over every RGB triple in steps of 15 up to 220 a channel and 380 the
    # sum, so the type stays dark enough to read at 8, 10 and 12 px.
    "lime":    (90, 210, 0),
}

# The five the alphanumerics use, in the order the coloring hands them out.
# black first, because it takes the largest group and is the most legible.
#
# These five are the ones that have to survive antialiasing at 8 px, because a
# letter and a digit are the same shape at that size and the color is the only
# thing left. The closest two are 210 apart on the sum of their channel
# differences. Blue and a teal sat 140 apart in the first attempt on
# 25 August 2026, which test_palette.py refused.
ALNUM_INKS = ("black", "blue", "green", "magenta", "orange")


def _colour_map():
    """Assign each character in CONFUSABLE an ink, so that no two characters
    that look alike share one. Greedy, highest degree first, which is what
    keeps the count to five. Computed once at import, not per character."""
    graph = {}
    for a, b in CONFUSABLE:
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)
    out = {}
    for ch in sorted(graph, key=lambda c: (-len(graph[c]), c)):
        taken = {out[n] for n in graph[ch] if n in out}
        k = 0
        while k in taken:
            k += 1
        out[ch] = k
    return {ch: INK[ALNUM_INKS[k % len(ALNUM_INKS)]] for ch, k in out.items()}


CHAR_INK = _colour_map()

# The three classes a reader tells apart for a different reason than shape.
# The line break mark, the symbols and the punctuation. These three do not
# need the separation the five above need: none of them is the shape of a
# letter or a digit, so a reader tells them apart by their glyph and the color
# only says which class they belong to.
PALETTE = {"num": INK["blue"], "sym": INK["red"], "nl": INK["teal"],
           "punct": INK["purple"], "tag": INK["lime"]}

# Shape-confusion pairs among the symbols. Each would otherwise share the one
# symbol color with the character it is most often mistaken for.
CONFUSION = {":": "nl", ",": "punct", "`": "punct", "'": "num"}

NL_MARK = "\u00b6"

# The DejaVu Sans Mono pair this repo carries in plugin/fonts. Every system
# that is not Windows reads the same two files, so a packed image drawn on
# Linux and one drawn on macOS carry identical glyphs and identical pixel
# sizes. The licence beside them is the Bitstream Vera licence, which permits
# redistribution.
FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
BUNDLED_REGULAR = str(FONT_DIR / "DejaVuSansMono.ttf")
BUNDLED_BOLD = str(FONT_DIR / "DejaVuSansMono-Bold.ttf")

# The monospace font each platform ships, Windows first, then the bundled
# copy, then the system paths on Linux and macOS. Pillow's built-in fallback
# font ignores the size argument and returns a fixed bitmap, so a missing font
# would draw the image at the wrong size and print a saving that never
# happened. load() raises instead of falling back, and the caller passes the
# text through unpacked, which is the same refuse-when-worse rule the rest of
# the plugin follows.
#
# Windows keeps consola.ttf in first place. The bundled entry sits directly
# after it, so no Windows machine changes font and every other system resolves
# to one known file before any system path is tried.
REGULAR = [r"C:\Windows\Fonts\consola.ttf",
           BUNDLED_REGULAR,
           "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
           "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
           "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
           "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
           "/System/Library/Fonts/Menlo.ttc",
           "/System/Library/Fonts/Supplemental/Courier New.ttf",
           "/Library/Fonts/Courier New.ttf"]
BOLD = [r"C:\Windows\Fonts\consolab.ttf",
        BUNDLED_BOLD,
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
        "/Library/Fonts/Courier New Bold.ttf"]



# What has to survive character for character. A token of 8 or more that mixes
# letters with digits, optionally joined by hyphen, underscore, dot or slash,
# or a number written in comma groups. That is an agent id, a hash, a commit, a
# session id, a file name and a token count.
#
# A plain English word never mixes letters with digits, so prose is untouched.
# Measured 25 August 2026 over 42 real agent reports, 362,319 characters: this
# marks 0.96 per cent of them, and the image grows 1.20 per cent.
IDENT_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-_./\\][A-Za-z0-9]+)*")
IDENT_NUMBER = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+")

# The tag threshold, PLAN-FABLE.md step 7, 29 August 2026: fewer strings get
# tagged. Every string this project has scored a reader on, MATH.md "Identifiers
# never go through the image", was 8 characters or longer, from
# "22,520,080" up to the 36 character "425a249c-de50-49d5-8346-986dad7c4e32",
# and every one of them read wrong at some drawn size before it was lifted. No
# string under 8 characters has ever been scored misread, at any px this
# packer draws. _is_identifier already held this floor for the letter and
# digit mix; IDENT_NUMBER held none, so a comma grouped number as short as
# "1,234" was tagged though nothing that short has ever been shown to misread.
# Applying the one measured floor to both closes that gap instead of adding a
# second, unscored one.
MIN_IDENT_CHARS = 8

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


# WIDENED 29 August 2026: two kinds a reader cannot verify small were let
# through this rule unlifted. Found by running lift_identifiers() against
# both, not by reading the rule: neither survived in the tagged text before
# this change, both do after it, and the three checks below still leave an
# ordinary word alone.
#
#   A long exact number with no comma grouping, such as a byte count or a
#   timestamp written as one run of digits. IDENT_NUMBER only ever matched
#   the comma grouped form, so "134217728" carried none of the punctuation
#   that rule looked for and passed through no rule at all, not even the
#   digit-and-letter mix _is_identifier already checked, because it has no
#   letter in it. The same MIN_IDENT_CHARS floor applies, so "2026" still
#   passes through untouched.
#
#   An absolute or a multi-segment path with no digit in it at all, such as
#   "Repos/DensePack/plugin/scripts/bash_gate.py" or, on Windows,
#   "C:\Projects\Repos\DensePack\plugin\scripts". Every project path this
#   packer's own reports name is exactly this shape, letters only, and the
#   digit-and-letter mix demanded a digit that a path this ordinary never
#   carries. Counted by its own path separators rather than by carrying one
#   at all, so an ordinary slash-joined word pair such as "input/output" or
#   "before/after", one separator and no digit, is not swept in with it: a
#   real path in this project's own text has never been one segment.
def _is_identifier(token):
    body = re.sub(r"[-_./\\]", "", token)
    if len(body) < MIN_IDENT_CHARS:
        return False
    if any(c.isdigit() for c in body) and any(c.isalpha() for c in body):
        return True
    if body.isdigit():
        return True
    if body.isalpha() and (token.count("/") + token.count("\\")) >= 2:
        return True
    return False


def big_mask(text):
    """One flag per character: True where it belongs to an identifier."""
    big = [False] * len(text)
    for m in IDENT_TOKEN.finditer(text):
        if _is_identifier(m.group(0)):
            for i in range(m.start(), m.end()):
                big[i] = True
    for m in IDENT_NUMBER.finditer(text):
        if len(m.group(0)) < MIN_IDENT_CHARS:
            continue
        for i in range(m.start(), m.end()):
            big[i] = True
    return big



# JOB 3, DensePack brief 29 August 2026. The forms lift_identifiers() may
# tag with, tried in this fixed order. [#N] is first because it is what
# shared.txt teaches every reader by default. The next two are reached only
# when the SOURCE TEXT ITSELF already carries a run shaped like the form
# before it, a markdown footnote or an issue reference the packer never
# invented, which would otherwise read as the same tag a lifted identifier
# gets and could not be told apart, in the plain-text sidecar, from one the
# packer actually invented: the sidecar carries no color, only the shape
# of the tag itself.
TAG_FORMS = ("[#%d]", "{#%d}", "<#%d>")
TAG_PATTERNS = tuple(
    re.compile(re.escape(form % 0).replace("0", r"\d+")) for form in TAG_FORMS)


def _tag_form(text):
    """The first form in TAG_FORMS whose pattern matches nothing already in
    `text`, checked against the text BEFORE any tag is inserted, so a form
    is never picked against tags it is about to create itself. Falls back
    to the last form when every one collides, rather than growing the list
    without end against text no fixed list can ever fully clear."""
    for form, pattern in zip(TAG_FORMS, TAG_PATTERNS):
        if not pattern.search(text):
            return form
    return TAG_FORMS[-1]


def tag_pattern_from_legend(legend):
    """The compiled TAG_PATTERNS entry matching the form lift_identifiers()
    actually used, read off the first legend row rather than passed as a
    second value, so callers written against the existing two-value
    lift_identifiers() return keep working unchanged. None when legend is
    empty: nothing was tagged, so pack() has no marker run to color."""
    if not legend:
        return None
    first_tag = legend[0][0]
    for pattern in TAG_PATTERNS:
        if pattern.fullmatch(first_tag):
            return pattern
    return None


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

    The tag form is chosen by _tag_form() before any tag is written, so a
    literal [#1] already in the source, a footnote or an issue reference,
    never collides with one this function invents; see TAG_FORMS above.
    """
    mask = big_mask(text)
    form = _tag_form(text)
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
            tag = form % n
            seen[value] = tag
            legend.append((tag, value))
            out.append(tag)
            n += 1
        i = j
    return "".join(out), legend


# legend_text(), LEGEND_FIRST, LEGEND_LATER, LEGEND_MARKER and
# legend_preamble() are retired here, PLAN-FABLE.md step 7, 29 August 2026.
# They built the legend as a text block that rode in the message beside the
# image, so every packed result that lifted an identifier paid for it again
# on every later turn: 424,990 characters of pointer and receipt text over
# 41 blocks measured this session, against 34,444 tokens for the images that
# text describes. legend_sidecar() below writes the same values to a file
# instead. FIXES-PENDING.md section 7 names the sidecar as one of two ways
# the legend can leave the message text; the file keeps the values exact
# bytes, which drawing them larger cannot promise.
def legend_sidecar(legend, out_stem):
    """Write every lifted identifier's value to a file beside the image,
    named densepack-legend-<12 hex>.txt, and return that file's own name.

    Returns None when nothing was lifted, so a report with no identifier
    writes no file and the pointer gains no tag line. The hex is a SHA-256
    of the sidecar's own text, so packing the same values twice names the
    same file instead of writing a second copy. out_stem is the same stem
    pack() writes its image beside, str or Path; the sidecar lands in that
    stem's own folder.
    """
    if not legend:
        return None
    rows = ["%s = %s" % (tag, value) for tag, value in legend]
    text = "\n".join(rows) + "\n"
    # JOB 3, DensePack brief 29 August 2026. The sidecar carries no color,
    # only the tag's own shape, so the one case where lift_identifiers()
    # escalated off the usual [#N] form has to say so here in plain text:
    # a reader of the .txt alone has no other way to learn which form this
    # report's tags use. Silent for the ordinary [#N] case, which
    # shared.txt already teaches every reader, so every sidecar this
    # plugin has ever written stays byte for byte the same.
    first_tag = legend[0][0]
    if not TAG_PATTERNS[0].fullmatch(first_tag):
        for form, pattern in zip(TAG_FORMS, TAG_PATTERNS):
            if pattern.fullmatch(first_tag):
                # form is a %-template such as "{#%d}"; "n" replaces "%d"
                # so the header reads as a shape, [#n], {#n} or <#n>, the
                # same lowercase-n convention shared.txt already teaches,
                # never the raw Python format specifier.
                shape = form.replace("%d", "n")
                text = ("# This report's tags read %s, not the usual [#n]: "
                         "a run shaped like [#n] was already in the source "
                         "text.\n" % shape) + text
                break
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    name = "densepack-legend-%s.txt" % digest
    path = Path(out_stem).parent / name
    path.write_text(text, encoding="utf-8")
    return name


def patches(width, height):
    """Patch count alone. This is the figure the downscale limit is checked
    against, so it must stay the raw count with no block cost added."""
    return -(-width // PATCH) * -(-height // PATCH)


def image_cost(width, height):
    """What one image really costs: its patches plus the content block itself."""
    return patches(width, height) + IMAGE_BLOCK


def no_downscale(width, height):
    """True when the API would leave the image at the size it was drawn."""
    return (-(-width // PATCH) * PATCH <= EDGE
            and -(-height // PATCH) * PATCH <= EDGE
            and patches(width, height) <= MAX_TOK)


def face(path, size, bold):
    """The regular or the bold face out of one font file, or None when that
    file holds neither. A .ttc file holds several faces, and the order differs
    between builds, so the face is matched by its own name, not by an index."""
    if not path.lower().endswith(".ttc"):
        return ImageFont.truetype(path, size)
    for index in range(8):
        try:
            font = ImageFont.truetype(path, size, index=index)
        except Exception:
            return None
        name = " ".join(part for part in font.getname() if part).lower()
        if ("bold" in name) == bold and "italic" not in name and "oblique" not in name:
            return font
    return None


def load(paths, size, bold=False):
    """One font face at this pixel size. Raises when no font file is found,
    because Pillow's fallback font ignores the size and would produce an image
    at a size the reader was never tested on."""
    for path in paths:
        if Path(path).is_file():
            font = face(path, size, bold)
            if font is not None:
                return font
    raise RuntimeError("No monospace font found. Looked for: %s. Install one of "
                       "them, or add the path to REGULAR and BOLD in %s."
                       % (", ".join(paths), Path(__file__).name))


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
    """Color and weight for one character. Returns (rgb, bold).

    A character that looks like another gets its own ink from CHAR_INK, so no
    two look-alikes ever share one. Anything not in that map falls back to the
    class colors, which is what the palette did for everything before
    25 August 2026.
    """
    if not colors:
        return (0, 0, 0), False
    if ch == NL_MARK:
        return PALETTE["nl"], True
    ink = CHAR_INK.get(ch)
    if ink is not None:
        return ink, ch.isdigit()
    if ch.isdigit():
        return PALETTE["num"], True
    if ch != " " and not ch.isalnum():
        alt = CONFUSION.get(ch)
        return PALETTE[alt] if alt else PALETTE["sym"], True
    return (0, 0, 0), False


def composite(paths, out_path, size=None):
    """Stack several packed images into one, with a header line above each.

    A composite here means one PNG holding every image that is waiting to be
    read, so the lead fetches all of them in a single Read call. Each Read
    call is a turn, and a turn re-reads the whole conversation: measured
    25 August 2026, 220,917 tokens, the mean over 470 turns. Five Read calls
    in one session spent 1,104,584 tokens against the 3,602,187 that drawing
    the reports as images saved.

    The header names which image each block came from, because a reader given
    three stacked pages with nothing between them cannot say where one report
    ends and the next begins.

    Returns (out_path, width, height), the same shape pack() returns for one
    image, or None when the stack would come out larger than the API leaves
    alone. A downscaled composite loses the text, so refusing is the only
    safe answer.
    """
    # The header size, not the page size. It sits above each stacked image and
    # names the file that image came from. 10 px is the size an Opus reader
    # was scored exact on, and the lead is the only reader a composite is ever
    # built for. densepack.py holds no default size of its own: every caller
    # passes one, which is why this argument has a literal default here.
    size = size or 10
    regular = load(REGULAR, size)
    line_h = size + 3
    pages = []
    for path in paths:
        try:
            pages.append((path, Image.open(path).convert("RGB")))
        except Exception:  # noqa: BLE001
            continue
    if not pages:
        return None

    width = max(img.width for _p, img in pages)
    height = sum(img.height + line_h + 2 for _p, img in pages)
    if not no_downscale(width, height):
        return None

    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for path, img in pages:
        draw.text((0, y), "== %s ==" % Path(path).name,
                  font=regular, fill=INK["red"])
        y += line_h
        sheet.paste(img, (0, y))
        y += img.height + 2
    # Drawn beside the final name and moved into place in one step: a
    # reader served the path mid-write uploads a truncated file, and the
    # API rejects it as an image it cannot process. Seen live 31 August
    # 2026 on a subagent's redirected read.
    part = Path(str(out_path) + ".part")
    sheet.save(part, "PNG", optimize=True)
    os.replace(part, out_path)
    return (out_path, width, height)


def _tag_mask(text, pattern):
    """One flag per character: True where it belongs to a marker tag this
    packer invented, matched by `pattern`. Every flag False when pattern is
    None, the default: nothing was tagged in this text, so pack() colors
    nothing as a tag. JOB 2, DensePack brief 29 August 2026: get this from
    tag_pattern_from_legend(), never guessed, so a coincidental [#N]-shaped
    run the source carried is never painted as a marker it is not."""
    mask = [False] * len(text)
    if pattern is None:
        return mask
    for m in pattern.finditer(text):
        for i in range(m.start(), m.end()):
            mask[i] = True
    return mask


# Measured 30 August 2026, bench/PACKING-ECONOMICS.md. A 0.85 gap costs 13 to
# 20 per cent fewer tokens than 1.0 at every pixel size, and the glyph the
# model reads does not change. The 10 px code image at 0.85 was read back in
# full before this became the default.
LINE_GAP = 0.85


def pack(text, size, out_stem, spacing=LINE_GAP, colors=True, tag_pattern=None,
        reader=None):
    # FIXED 29 August 2026: refuse a size under the reader's own scored
    # floor. `reader` is optional and defaults to None so every existing
    # caller that already computes a correct size from common.font_size()
    # or common.MEASURED_MODELS is unaffected; a caller that names its
    # reader gets the floor enforced even if its own size math was wrong.
    # Bumping size up, never down: a bigger-than-needed image only costs a
    # few more tokens, while a smaller one produces wrong answers, the
    # asymmetry every floor in RISKY was measured against.
    if reader is not None:
        floor = RISKY.get(reader, RISKY_DEFAULT)
        if size < floor:
            print(FLOOR_NOTE % (size, reader, floor, floor), file=sys.stderr)
            size = floor

    # Flatten here, not in the caller. A line break the font cannot draw
    # vanishes, and the page then runs together with nothing marking where a
    # line ended. Two of the five callers did not flatten before 25 August
    # 2026, and one of them was the right-click tool, so every file a person
    # packed that way lost its line structure. flatten() on text that is
    # already flat finds no line break and changes nothing, so calling it
    # twice is safe and the callers that already do are left alone.
    text = flatten(text)
    big = big_mask(text)
    tag = _tag_mask(text, tag_pattern)
    ident_px = max(size, IDENT_PX)
    regular = load(REGULAR, size)
    bold = load(BOLD, size, True)
    big_regular = load(REGULAR, ident_px)
    big_bold = load(BOLD, ident_px, True)
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
        """Width of a run of (character, big, tag) triples."""
        total = 0.0
        for ch, b, _t in pairs:
            _c, bold_flag = classify(ch, colors)
            total += char_w(ch, bold_flag, b)
        return total

    def height_of(pairs):
        """A line takes the height of the tallest thing on it."""
        return big_line_h if any(b for _c, b, _t in pairs) else line_h

    pairs = list(zip(text, big, tag))

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
    # list of (character, big, tag) triples, not a string, because a string
    # cannot carry the flags that say which characters draw bigger or in the
    # marker color.
    words, word = [], []
    for pair in pairs:
        if pair[0] == " ":
            words.append(word)
            word = []
        else:
            word.append(pair)
    words.append(word)

    SPACE = [(" ", False, False)]
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
            for ch, is_big, is_tag in line:
                color, is_bold = classify(ch, colors)
                # A marker tag draws as one color for the whole run, JOB 2,
                # DensePack brief 29 August 2026, so a tag this packer
                # invented never reads as the same red-blue-red a literal
                # [#1] the source carried would draw under the ordinary
                # per-character classes.
                if is_tag and colors:
                    color = PALETTE["tag"]
                # Every character sits on one baseline, so a bigger one grows
                # upward out of the line rather than shifting the rest down.
                top = y + row_h - (ident_px if is_big else size) - 1
                draw.text((x, top), ch, font=face(is_big, is_bold), fill=color)
                x += char_w(ch, is_bold, is_big)
            y += row_h

        path = Path("%s-%d.png" % (out_stem, number))
        # Same one-step move as sheet.save above: no reader ever sees a
        # half-written page.
        part = Path(str(path) + ".part")
        img.save(part, "PNG", optimize=True)
        os.replace(part, path)
        written.append((path, width, height))

    return written, int(target), line_h


def reader_size():
    """The size this session draws at, from the reader profile the slash
    commands set, or 8 when the settings cannot be found.

    The briefing tells the lead to pack a long brief with this command, so it
    has to agree with the hooks. It did not: the hooks called font_size() and
    this file had its own default of 8, so a session on /opuspack wrote
    its agent reports at 10 px and its briefs at 8 px, and 8 px is the size two
    cold Opus 5 readers scored 1 of 10 on. The import is guarded because this
    file is also shipped beside the app, where common.py is not present."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from common import font_size, resolved_reader
        return font_size(), resolved_reader()
    except Exception:
        # 8 px is Fable's floor and the size two cold Opus 5 readers scored
        # 1 of 10 on, so falling back to it silently can hand an Opus session
        # a brief it cannot read. The fallback stays, because a packer that
        # refuses to run is worse, but it announces itself.
        return 8, "unknown"


def main():
    ap = argparse.ArgumentParser(description="Pack text into a dense image a vision model reads.")
    ap.add_argument("input", help="text file to pack, or - for stdin")
    size_default, profile = reader_size()
    ap.add_argument("--size", type=int, default=size_default,
                    help="font size in px. Defaults to the reader profile's size, "
                         "8 for fable and 10 for opus, set by /fablepack and "
                         "/opuspack. Below 8 misreads digits.")
    ap.add_argument("--out", default="packed", help="output name stem")
    ap.add_argument("--spacing", type=float, default=LINE_GAP,
                help="line gap, default %s" % LINE_GAP)
    ap.add_argument("--no-color", action="store_true", help="black text only")
    ap.add_argument("--quiet", action="store_true", help="print only the image paths")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(
        encoding="utf-8", errors="replace")
    if not raw.strip():
        raise SystemExit("Nothing to pack.")

    text = flatten(raw)
    try:
        written, target, line_h = pack(text, args.size, args.out, args.spacing, not args.no_color)
    except RuntimeError as err:
        raise SystemExit(str(err))

    # The API charge for an image is its patch count and nothing else. A
    # pipeline that hands the image to an agent pays its own handover cost on
    # top, so the plugin's receipt is lower than this one by that fee.
    text_tokens = len(raw) / CHARS_PER_TOKEN
    image_tokens = sum(image_cost(w, h) for _p, w, h in written)

    for path, _w, _h in written:
        print(path)

    if args.quiet:
        return

    saving = (1 - image_tokens / text_tokens) * 100 if text_tokens else 0
    out = sys.stderr
    print("", file=out)
    print("characters   %d raw, %d flattened" % (len(raw), len(text)), file=out)
    print("layout       %d px wide, %d px line height, %d px font" % (target, line_h, args.size), file=out)
    print("images       %d, all checked against the API's own resize rule" % len(written), file=out)
    if profile == "unknown":
        print("reader       NOT READ. Defaulted to %d px, which Fable 5 reads and "
              "Opus 5 does not. Pass --size 10 for an Opus reader." % args.size,
              file=out)
    elif profile:
        print("reader       %s profile, %d px" % (profile, args.size), file=out)
    print("as text      %d tokens" % round(text_tokens), file=out)
    print("as image     %d tokens" % image_tokens, file=out)
    floor = RISKY.get(profile, RISKY_DEFAULT)
    if args.size < floor:
        print("WARNING      %d px is under the %d px floor measured for this reader. "
              "Digits misread even in color. Verify a test image first."
              % (args.size, floor), file=out)
    if saving > 0:
        print("saving       %.0f percent, patches only. The plugin's receipt "
              "also charges the handover cost, about 148 tokens for one image, "
              "so it reads a few points lower for the same report."
              % saving, file=out)
    else:
        print("WORSE by     %.0f percent. Send the text instead." % -saving, file=out)


if __name__ == "__main__":
    main()
