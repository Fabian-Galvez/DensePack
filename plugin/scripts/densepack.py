"""The engine. It packs a long text into one small picture.

HOW THIS FILE FITS. The other files bring text to this file. This file lays
the words out in small type and colors the characters that look alike, and a
model then does not confuse them. It keeps the image inside the exact size
that the API accepts without a resize, and it saves the image as a PNG.

Pack text into the smallest image the model can still read.
The size is the one size of the plugin, common.CODE_PX, for all models.
--size overrides it.

It is a port of the DensePack browser app, index.html at the root of the
repository. It has the same rules, constants, layout, color coding,
measurements and downscale check. A script, a right-click or an agent can
do the same job without a browser.

    python densepack.py report.md
    python densepack.py report.md --size 14 --out packed
    some-command | python densepack.py - --out packed

It writes packed-1.png and the next files, prints one line per file, and
prints the token comparison. The saving is then a number and not a claim.
"""

import os
import zlib
import argparse
import hashlib
import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

import style  # noqa: E402

# All numbers and colors below come from style.load(). Without a style.json
# on disk, a run uses the defaults in style.py.
_S = style.load()

# The real limits of the API, taken from the app. The app follows the resize
# rule that Anthropic publishes and does not guess. This file holds only the
# constants from that rule, not the rule itself. They are the same for all
# models on the high-resolution tier and do not change with the model.
# The API accepts 2576 px on the long edge for a single image. A request with
# more than 20 images gets a stricter limit. The API shrinks any dimension
# over 2000 px, and the shrink destroys text this small. A busy session can
# queue more than 20 packed reports. For this reason, each image is under
# 2000 px on the two sides. EDGE is lower still, 1568 px or 56 patches of
# 28 px, from page.edge in style.py.
EDGE = _S["page.edge"]  # longest side this packer makes. Past 1568 the
                   # delivery layer can shrink an image without a notice
MAX_TOK = _S["page.max_tok"]   # most patches the API accepts per image
CAP_W = _S["page.cap_w"]       # largest guaranteed-no-downscale canvas
CAP_H = _S["page.cap_h"]
RATIO = _S["page.ratio"]       # a square uses the token budget best

# The floor that a bench scored each model against. Below it a model
# misreads digits, even in color. At 6 px a model returned "#2___5" for a 5
# digit number. DensePack packs one image for all models, and each entry
# returns font.px. The map stays, and callers that ask by model name still
# work. Haiku has no entry and gets no image. Haiku invented well shaped
# wrong numbers from a packed image and did not report UNREADABLE. A larger
# size did not fix this.
RISKY = {"fable": _S["font.px"], "opus": _S["font.px"],
         "sonnet": _S["font.px"]}
RISKY_DEFAULT = _S["font.px"]  # the floor for an unreadable profile

# pack() takes the model as well as the size. It does not pack under the
# RISKY floor of that model. It packs at the floor and prints one line to
# stderr about the clamp. A caller or a test can then see the clamp, and the
# shape of the return value of pack() does not change. No agent gets an image
# at a size that no bench scored.
FLOOR_NOTE = ("DensePack got a request for %d px for %s, under the measured "
              "%d px floor of that model. It packed the text at %d px.")

# A page over 512,000 bytes reaches the model as a JPEG, not as the PNG on
# disk. The number is a constant in the Claude Code binary, beside
# imageMaxRawBytes, and the Read tool uses it when the session is local. Over
# that size, Claude Code encodes the file again with a JPEG quality search,
# from 90 to 20. No setting changes the number, because the settings schema
# has no image key.
#
# The JPEG encode changes the glyph edges, and there a model loses a letter.
# A 756 by 1120 page at 574,654 bytes arrived as image/jpeg with 87,307
# colors, and the file has 4,700. For this reason the code writes a page
# under a cap. It keeps each pixel position and rounds only the anti-aliased
# shades.
#
# PNG_BYTE_CAP is the cap of the renderer, and save_png() enforces it. It is
# at half the JPEG threshold. A heavy page holds about 4,870 colors and
# writes 487,088 bytes. From a 256 color palette the same page writes 172,358
# bytes, and 117 of its 550,621 ink pixels change color, 0.02 percent. Each
# glyph stays in the same place.
PNG_BYTE_CAP = 250000
PALETTE_STEPS = (256, 128, 64, 32)


def clear_link(path):
    """Remove any link at this name before a write to it.

    A project can put the name of the part file in the images folder as a
    symbolic link, a junction or a second hard link. A write to that name then
    goes into the file that the link shares. A hard link is a real directory
    entry, and only the link count separates it from an ordinary file. The
    move after this uses os.replace, which replaces a link and does not write
    through it. Only the part name needs this step."""
    # common.is_junction reads the reparse tag, because os.path.isjunction is
    # 3.12 and the two launchers accept 3.10, where a junction looks like a
    # folder.
    from common import clear_link as _clear_link
    _clear_link(path)


def save_png(im, path):
    """Write a PNG small enough to reach the model as a PNG.

    The function writes the full-color page first and keeps it when it fits.
    It writes a page over the cap again from a palette, with the fewest
    colors last, and keeps the first one under the cap. A page that fits
    under none of them stays at its smallest size, which is still better than
    the JPEG that follows.
    """
    # The function writes beside the name and moves the file onto it in one
    # step, the same rule that composite() and pack() follow. A process that
    # reads the path while this function writes its second, smaller copy
    # gets the first copy cut in half, a PNG with no IEND chunk that does
    # not decode.
    part = str(path) + ".part"
    clear_link(part)
    im.save(part, "PNG", optimize=True)
    if os.path.getsize(part) > PNG_BYTE_CAP:
        source = im.convert("RGB")
        for colours in PALETTE_STEPS:
            source.quantize(colors=colours, method=Image.MEDIANCUT).save(
                part, "PNG", optimize=True)
            if os.path.getsize(part) <= PNG_BYTE_CAP:
                break
    replace_retry(part, str(path))


def replace_retry(src, dst, tries=40, wait=0.05):
    """os.replace that waits while the destination is busy.

    On Windows a replace onto a file that another process holds open raises
    PermissionError. The read gate of a parallel Read opens image files to
    measure them while a pack writes its chosen image. A wide burst of Reads
    then gets this error. Forty tries at fifty milliseconds is two seconds,
    longer than any measure holds a file open.
    """
    import time
    for n in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if n == tries - 1:
                raise
            time.sleep(wait)


PATCH = _S["page.patch"]   # one visual token is one 28 by 28 patch
PAD = _S["page.text_pad"]
BACKGROUND = _S["page.background"]
# One ink for all characters, or None for the per-group colors that ship.
UNIVERSAL_INK = _S["ink.universal"]
# A px offset for a character group, added to the body size. All offsets
# are zero in the shipped renderer.
GROUP_PX = _S["font.group_px"]
LETTER_SPACE = _S["space.letter_text"]
WORD_SPACE = _S["space.word"]
LINE_FACTOR = _S["space.line_factor"]
# Characters per token for the text this plugin packs. THE SINGLE SOURCE.
# All scripts in plugin/scripts read this name and do not write a number of
# their own. The browser app and the clipboard script cannot import Python.
# They hold the value with a comment that names this constant.
#
# Measured against Anthropic's count_tokens endpoint, model claude-opus-5,
# over 92 packed source texts. 860,637 characters against 357,951 counted
# tokens give 2.4043. A second sample, balanced by kind and not by traffic,
# with 90 texts and 559,234 characters against 232,893 tokens, gives 2.4012.
# The two round to 2.40. The measure counts a one character message first
# and subtracts its wrapper from each figure.
#
# The constant prices bash output, briefs and file reads as well as agent
# reports. Bash output is most of what the plugin packs. By kind, in the
# traffic weighted sample: bash output 2.37, agent reports 2.60, briefs 2.79.
CHARS_PER_TOKEN = 2.40
# The date of the divisor measure, as a value. A page that prints the
# constant can then print the date without a second copy of it.
CHARS_PER_TOKEN_MEASURED = "31 August 2026"

# The cost of one image content block on top of its patches. Measured on 28
# packed PNGs, from 418x412 to 1144x1168, the counted token figure was the
# patch count plus exactly 2 at each size.
IMAGE_BLOCK = _S["page.image_block"]

# All pairs of characters that look alike in small type. Each entry is one
# edge in a confusion graph. The coloring below gives no two characters
# joined by an edge the same color. The list holds pairs, and a check of one
# pair needs no read of the whole map.
#
# The list starts from the standard small-type look-alikes and holds each
# pair that a model confused in tests. A model read 8 as 3 and as 9, 9 as 0,
# 5 as 3, O as D and S as D.
CONFUSABLE = [tuple(pair) for pair in _S["ink.confusable"]]
# The pairs are in style.py, under ink.confusable, because one file holds
# all values that the renderer uses.

# Nine colors, spread around the hue circle, and no two are close. Each one
# is dark enough to keep its color when the renderer antialiases the type at
# a small size.
INK = {name: _S["ink." + name] for name in
       ("black", "blue", "green", "magenta", "orange", "teal", "red",
        "purple", "lime")}

# The five inks of the letters and digits, in the order the coloring uses
# them. Black is first, because it takes the largest group and is the
# easiest to read.
#
# These five must stay clear after antialiasing at a small size. There a
# letter and a digit have the same shape, and the color is the only
# difference. The closest two are 210 apart on the sum of their channel
# differences.
ALNUM_INKS = tuple(_S["ink.lookalike_groups"])


def _colour_map():
    """Assign each character in CONFUSABLE an ink. No two characters that
    look alike share one. The method is greedy, highest degree first, and
    this keeps the count at five. The code computes it once at import, not
    per character."""
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

# The three classes that a model separates for a reason other than shape.
# These are the line break mark, the symbols and the punctuation. They do not
# need the separation of the five inks above. None of them has the shape of
# a letter or a digit. A model separates them by their glyph, and the color
# only shows their class.
PALETTE = {name: _S["palette." + name] for name in
           ("num", "sym", "nl", "punct", "tag")}

# Shape-confusion pairs among the symbols. Without this map, each one shares
# the symbol color with the character that a model most often reads in its
# place.
CONFUSION = dict(_S["palette.confusion"])

NL_MARK = _S["mark.pilcrow"]

# The font files to try, in order, from font.regular in style.py. The
# built-in fallback font of Pillow ignores the size argument and returns a
# fixed bitmap. With a missing font, the image then has the wrong size, and
# the tool prints a false saving. load() raises an error and does not use a
# fallback. The caller then sends the text unpacked. The rest of the plugin
# follows the same rule and skips the pack when the pack is worse. The render
# loop measures each glyph with getlength and uses no fixed cell width.
REGULAR = list(_S["font.regular"])
# The bold face, from font.bold in style.py. When it names the same file as
# font.regular, a character that the classifier marks bold uses the same face,
# and the code loads no second font file.
BOLD = list(_S["font.bold"])


# The text that must stay exact, character for character. A token of 8 or
# more that mixes letters with digits, with an optional hyphen, underscore,
# dot or slash between parts, or a number written in comma groups. These are
# an agent id, a hash, a commit, a session id, a file name and a token count.
#
# A plain English word never mixes letters with digits, and the prose does
# not change. Measured over 42 agent reports, 362,319 characters, this marks
# 0.96 percent of them, and the image grows 1.20 percent.
# Two joiners can be next to each other. A path through a dot folder,
# project\.claude\densepack-vault, is then one token. With one joiner, the
# token ends at project and the next one starts at claude. A model that gets
# the two tags then writes the path without its dot.
IDENT_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-_./\\]{1,2}[A-Za-z0-9]+)*")
IDENT_NUMBER = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+")

# The tag threshold. Each identifier that a model misread in a scored test
# was 8 characters or longer, from "22,520,080" to the 36 character
# "12345678-90ab-cdef-1234-567890abcdef". No test scored a misread string
# under 8 characters at any size this packer uses. _is_identifier holds this
# floor for the letter and digit mix, and big_mask() applies the same floor
# to IDENT_NUMBER. A comma grouped number as short as "1,234" then gets no
# tag.
MIN_IDENT_CHARS = _S["font.min_ident_chars"]

# The size of an identifier. Zero means the prose size, which ships.
#
# Larger identifiers work in part. With 12 px identifiers on a smaller prose
# size, two models rose to 4 of 5 for 4.54 percent more pixels, and each
# remaining failure was the same string in the same place. font.ident_px in
# style.json sets this size. pack() uses it only when it is larger than the
# prose size.
IDENT_PX = _S["font.ident_px"]


# Three kinds count as an identifier, each at MIN_IDENT_CHARS or longer.
#
#   A token that mixes letters with digits.
#
#   A long exact number with no comma grouping, such as a byte count or a
#   timestamp written as one run of digits. IDENT_NUMBER matches only the
#   comma grouped form, and "134217728" needs this rule. The same floor
#   applies, and "2026" stays as it is.
#
#   An absolute or a multi-segment path with no digit in it, such as
#   "plugin/scripts/read_gate.py" or, on Windows, "C:\Projects\plugin\scripts".
#   The rule counts the separators of a path and needs two or more. An
#   ordinary slash-joined word pair such as "input/output" or "before/after",
#   with one separator and no digit, does not count.
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
    """One flag per character. The flag is True where the character is part of an identifier."""
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


# The tag forms that lift_identifiers() can use, tested in this fixed order.
# [#N] is first, because it is the usual form. The code uses the next two
# only when the SOURCE TEXT ITSELF already holds a run in the shape of the
# form before it. This is a markdown footnote or an issue reference that the
# packer did not make. Without the next form, that run has the same shape as
# the tag of a lifted identifier. In the plain-text sidecar, a model cannot
# separate the two, because the sidecar has no color, only the shape of the
# tag.
TAG_FORMS = ("[#%d]", "{#%d}", "<#%d>")
TAG_PATTERNS = tuple(
    re.compile(re.escape(form % 0).replace("0", r"\d+")) for form in TAG_FORMS)


def _tag_form(text):
    """The first form in TAG_FORMS whose pattern matches nothing in `text`.
    The check runs on the text BEFORE the code inserts any tag, and a form
    never matches tags that it is about to make. The function uses the last
    form when all forms collide. It does not grow the list without end,
    because no fixed list can clear all text."""
    for form, pattern in zip(TAG_FORMS, TAG_PATTERNS):
        if not pattern.search(text):
            return form
    return TAG_FORMS[-1]


def tag_pattern_from_legend(legend):
    """The compiled TAG_PATTERNS entry that matches the form that
    lift_identifiers() used. The function reads it from the first legend row.
    It is not a second return value, and callers that use the two-value
    return of lift_identifiers() work without a change. None when legend is
    empty, because no text has a tag and pack() has no marker run to color."""
    if not legend:
        return None
    first_tag = legend[0][0]
    for pattern in TAG_PATTERNS:
        if pattern.fullmatch(first_tag):
            return pattern
    return None


# OFF by default. The look-alike coloring on each image keeps an identifier
# readable. The lift costs the model each path and hash in a packed command
# output, because the image shows a tag that the model cannot open. With the
# switch off, lift_identifiers() returns the text unchanged and an empty
# legend. No caller then writes a sidecar, and the image has no tag. Set it
# to True to get the tags and the legend file.
LIFT_IDENTIFIERS = False


def lift_identifiers(text, start=1):
    """Replace each identifier with a short tag and return the values.

    Does nothing while LIFT_IDENTIFIERS is False. See the note above it.

    Returns (tagged_text, legend), where legend is a list of (tag, value).
    An identifier is what big_mask marks. That is 8 or more characters that
    mix letters with digits, joined by hyphen, underscore, dot or slash, or a
    number in comma groups. A model cannot misread a value that is not in the
    image. This is the purpose of the function.

    A value that appears twice takes the same tag. A report that names one
    agent id ten times pays for it once.

    _tag_form() chooses the tag form before the function writes any tag. A
    literal [#1] already in the source, such as a footnote or an issue
    reference, then never collides with a tag from this function. See
    TAG_FORMS above.
    """
    if not LIFT_IDENTIFIERS:
        return text, []
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


# legend_sidecar() writes the lifted values to a file beside the image, not
# into the message. A packed result then does not pay for them again on each
# later turn. The file keeps the exact bytes of the values, and a larger size
# in the image cannot do that.
def legend_sidecar(legend, out_stem):
    """Write the value of each lifted identifier to a file beside the image,
    named densepack-legend-<12 hex>.txt, and return the name of that file.

    Returns None when the function lifted nothing. A report with no
    identifier then writes no file, and the pointer gets no tag line. The hex
    is a SHA-256 of the sidecar text. Two packs of the same values name the
    same file and do not write a second copy. out_stem is the stem that
    pack() writes its image beside, str or Path. The sidecar goes in the
    folder of that stem.
    """
    if not legend:
        return None
    rows = ["%s = %s" % (tag, value) for tag, value in legend]
    text = "\n".join(rows) + "\n"
    # The sidecar has no color, only the shape of the tag. When
    # lift_identifiers() moved off the usual [#N] form, the sidecar must say
    # so here in plain text. A model that reads only the .txt has no other way
    # to find the tag form of this report. The sidecar adds no line for the
    # usual [#N] form.
    first_tag = legend[0][0]
    if not TAG_PATTERNS[0].fullmatch(first_tag):
        for form, pattern in zip(TAG_FORMS, TAG_PATTERNS):
            if pattern.fullmatch(first_tag):
                # form is a %-template such as "{#%d}". "n" replaces "%d",
                # and the header shows a shape, [#n], {#n} or <#n>, never
                # the raw Python format specifier.
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
    """The patch count only. The downscale check uses this figure, and it
    must stay the raw count with no block cost."""
    return -(-width // PATCH) * -(-height // PATCH)


def image_cost(width, height):
    """The full cost of one image, its patches plus the content block."""
    return patches(width, height) + IMAGE_BLOCK


def no_downscale(width, height):
    """True when the API keeps the image at its rendered size."""
    return (-(-width // PATCH) * PATCH <= EDGE
            and -(-height // PATCH) * PATCH <= EDGE
            and patches(width, height) <= MAX_TOK)


def face(path, size, bold):
    """The regular or the bold face from one font file, or None when that
    file holds neither. A .ttc file holds several faces, and the order differs
    between builds. The function matches the face by its name, not by an
    index."""
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
    """One font face at this pixel size. Raises an error when it finds no
    font file. The fallback font of Pillow ignores the size and makes an
    image at a size that no test checked for the model."""
    for path in paths:
        if Path(path).is_file():
            font = face(path, size, bold)
            if font is not None:
                return font
    raise RuntimeError("DensePack found no font file. It looked for %s. Install one of "
                       "them, or add the path to REGULAR and BOLD in %s."
                       % (", ".join(paths), Path(__file__).name))


def flatten(raw, mark=NL_MARK):
    """Collapse the text to one string, and keep each line break as a marker.

    This step makes the pack dense. Real line breaks leave ragged right edges,
    and the blank pixels beside a short line cost as many tokens as inked
    ones. A marker in place of the break lets each line fill the full width.
    """
    lines = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        piece = " ".join(line.split())
        if piece:
            lines.append(piece)
    return mark.join(lines)


def group_for(ch):
    """The group that holds the size offset of a character.

    The names match the keys of font.group_px in style.py. The look-alike
    characters are a group of their own, and that set can have a size of its
    own. The backtick and the comma are in it.
    """
    if ch == NL_MARK:
        return "nl"
    if ch in CHAR_INK:
        return "lookalike"
    if ch.isdigit():
        return "num"
    if ch != " " and not ch.isalnum():
        return "punct" if CONFUSION.get(ch) == "punct" else "sym"
    return "body"


def classify(ch, colors=True):
    """Color and weight for one character, with the universal ink over it and
    the override ink of the character over the two."""
    ink, bold = _classify(ch, colors)
    if colors and UNIVERSAL_INK is not None:
        ink = tuple(UNIVERSAL_INK)
    over = char_over(ch, "ink")
    if colors and over:
        ink = over
    return ink, bold


# The overrides of one character, at each place it appears, from
# char.overrides in style.py. codepack reads the same map through its own
# copy of these two names.
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


def _classify(ch, colors=True):
    """Color and weight for one character. Returns (rgb, bold).

    A character that looks like another gets its own ink from CHAR_INK, and
    no two look-alikes share one. A character that is not in that map uses
    the class colors.
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


def pages_pdf(paths, out_path):
    """Bind several packed pages into one PDF, one page per image.

    The delivery rule behind this function. One Read call returns all pages
    of a file, and no tool result asks the model to Read again for more
    pages. composite() meets that rule with a stack and returns None when the
    stack passes CAP_H. Side by side does not work on a long code file
    either. There two sheets stack to 1176 by 2856 and are 2352 by 1428 side
    by side, and the two sizes are over the 1568 cap. A Read of a PDF returns
    each page as its own picture inside the one tool result. The pages then
    arrive whole, with no second Read and no sheet to shrink.

    The function writes the pages at 72 points per inch, one point per pixel,
    and a page keeps its exact rendered size. Returns the PDF path, or None
    when the function cannot bind the pages. The caller keeps the PNG pages,
    and the patch price still comes from them.

    This file has its own writer. It writes each page through FlateDecode,
    which is zlib and returns the same bytes it gets. The PdfImagePlugin of
    Pillow writes an RGB page through DCTDecode, which is JPEG. Measured on a
    small code page, that path changed 96.00 percent of the pixels with a
    worst channel error of 176 of 255. A 256 color palette page still changed
    8.26 percent. This writer changes no pixel.
    """
    rasters = []
    for path in paths:
        try:
            im = Image.open(path).convert("RGB")
        except Exception:  # noqa: BLE001
            return None
        rasters.append((im.width, im.height, im.tobytes()))
    if not rasters:
        return None

    objs = [b""]  # object numbers start at 1

    def add(body):
        objs.append(body)
        return len(objs) - 1

    kids = []
    pages_id = 1 + 1 + 2 * len(rasters)  # catalog, then two objects a page
    for w, h, raw in rasters:
        stream = zlib.compress(raw, 9)
        img_id = add(
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
            b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
            b"/Length %d >>\nstream\n" % (w, h, len(stream))
            + stream + b"\nendstream")
        # One point per pixel. A PDF rasterizer with no other instruction
        # renders a page at 72 points to the inch, one point to one pixel.
        # This box then gives the model the pixels of the PNG unchanged. A
        # smaller box, sized for 100 percent in a viewer, makes such a
        # rasterizer shrink each glyph first. Scale with the zoom of the
        # viewer, not with the page box.
        pw, ph = float(w), float(h)
        content = b"q %.4f 0 0 %.4f 0 0 cm /Im Do Q" % (pw, ph)
        cs = zlib.compress(content, 9)
        con_id = add(b"<< /Filter /FlateDecode /Length %d >>\nstream\n" % len(cs)
                     + cs + b"\nendstream")
        kids.append((img_id, con_id, pw, ph))

    page_ids = []
    for img_id, con_id, w, h in kids:
        page_ids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.4f %.4f] "
            b"/Resources << /XObject << /Im %d 0 R >> >> /Contents %d 0 R >>"
            % (pages_id, w, h, img_id, con_id)))
    pages_id = add(b"<< /Type /Pages /Count %d /Kids [%s] >>"
                   % (len(page_ids),
                      b" ".join(b"%d 0 R" % i for i in page_ids)))
    # each page names its parent, and the number above must be the real one
    for i, pid in enumerate(page_ids):
        objs[pid] = objs[pid].replace(b"/Parent %d 0 R" % (1 + 1 + 2 * len(rasters)),
                                      b"/Parent %d 0 R" % pages_id)
    root_id = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for n in range(1, len(objs)):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + objs[n] + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % len(objs)
    for n in range(1, len(objs)):
        out += b"%010d 00000 n \n" % offsets[n]
    out += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs), root_id, start))

    part = Path(str(out_path) + ".part")
    try:
        clear_link(part)
        part.write_bytes(bytes(out))
        os.replace(part, out_path)
    except Exception:  # noqa: BLE001
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return str(out_path)


def composite(paths, out_path, size=None):
    """Stack several packed images into one, with a header line above each.

    A composite here is one PNG with all images that wait for a Read. The
    lead agent then gets all of them in a single Read call. Each Read call is
    a turn, and a turn reads the whole conversation again. In one measured
    session a turn averaged 220,917 tokens over 470 turns. Five Read calls
    spent 1,104,584 tokens, and the packed reports saved 3,602,187 tokens.

    The header names the source image of each block. A model that gets three
    stacked pages with nothing between them cannot tell where one report ends
    and the next starts.

    Returns (out_path, width, height), the same shape pack() returns for one
    image, or None when the stack is larger than the size the API keeps
    unchanged. A downscaled composite loses the text, and None is the only
    safe result.
    """
    # The header size, not the page size. The header is above each stacked
    # image and names the source file of that image. densepack.py has no
    # default size of its own, and each caller passes one. For this reason
    # this argument has a literal default here.
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

    sheet = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    y = 0
    for path, img in pages:
        draw.text((0, y), "== %s ==" % Path(path).name,
                  font=regular, fill=INK["red"])
        y += line_h
        sheet.paste(img, (0, y))
        y += img.height + 2
    # The code writes beside the final name and moves the file into place in
    # one step. A process that reads the path during the write uploads a
    # truncated file, and the API rejects it as an image it cannot process.
    part = Path(str(out_path) + ".part")
    save_png(sheet, part)
    os.replace(part, out_path)
    return (out_path, width, height)


def grid_size(sizes):
    """The images per row, the width and the height of a grid of images of
    these (width, height) sizes, laid out the way composite_grid() lays them."""
    gap = int(_S["page.divider_width"])
    forced = int(_S.get("page.grid_per_row", 0) or 0)
    per_row = forced if forced else max(1, EDGE // max(w for w, _h in sizes))
    rows = [sizes[i:i + per_row] for i in range(0, len(sizes), per_row)]
    width = max(sum(w for w, _h in row) for row in rows)
    height = sum(max(h for _w, h in row) for row in rows) + gap * (len(rows) - 1)
    return per_row, width, height


# A pixel this close to the background on all channels is not ink. The page
# edge leaves single pixels such as (254, 253, 255) at x = 0 under the last
# line. When the code counts them as ink, a stack keeps many blank rows.
NEAR_BLANK = 6


def last_ink_row(im):
    """The last row holding a pixel further than NEAR_BLANK from the
    background, or 0."""
    w, h = im.size
    rgb = im.convert("RGB")
    bg = tuple(BACKGROUND)[:3]
    for y in range(h - 1, 0, -1):
        lo, hi = zip(*rgb.crop((0, y, w, y + 1)).getextrema())
        if any(abs(v - b) > NEAR_BLANK for v, b in zip(lo + hi, bg + bg)):
            return y
    return 0


def ink_crop(im, margin=4):
    """im cut under its last row of ink, with margin rows kept. No rounding
    here, because the code rounds the full sheet that holds the page."""
    w, h = im.size
    last = last_ink_row(im)
    keep = min(h, last + 1 + margin)
    return im.crop((0, 0, w, keep)) if keep < h else im


def composite_grid(paths, out_path):
    """The pages of one file side by side, left to right and then down, with
    a divider line between them, as one PNG that the API does not downscale.

    Returns (out_path, width, height), or None when the API downscales even
    the grid. The caller then uses the vertical composite or the PDF. The
    count_tokens endpoint bills a PDF page a flat fee of about 1,577 tokens
    for any pixel count. Three 392 by 700 pages then cost 4,780 as a PDF and
    996 as PNGs. A grid of 392 px pages holds four across under the 1568 px
    edge and two rows under it, eight pages in one Read at about 1,400
    patches a row.
    """
    pages = []
    for path in paths:
        try:
            pages.append(Image.open(path).convert("RGB"))
        except Exception:  # noqa: BLE001
            continue
    if not pages:
        return None
    # No gap between columns, because a page ends in its own white margin,
    # and four 392 px pages are exactly the 1568 px edge. A divider line is
    # between rows, where no other mark shows the break.
    gap = int(_S["page.divider_width"])
    divider = tuple(_S["page.divider"])
    per_row, width, height = grid_size([im.size for im in pages])
    if per_row == 1 and len(pages) > 1:
        # ONE COLUMN. The pages run top to bottom, and their line numbers
        # continue. The stack needs no divider. The code cuts a page above
        # another page to its own ink. The code rounds each page up to whole
        # 28 px patches to ship on its own, and in a stack that rounding puts
        # blank rows in the middle. A tall stack can hold many blank rows and
        # a divider between its pages. This step removes them. The code rounds
        # only the finished sheet to the patch grid.
        pages = [ink_crop(im) for im in pages]
        gap = 0
        width = max(im.width for im in pages)
        height = sum(im.height for im in pages)
        height = -(-height // PATCH) * PATCH
    rows = [pages[i:i + per_row] for i in range(0, len(pages), per_row)]
    if not no_downscale(width, height):
        return None
    sheet = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    y = 0
    for row in rows:
        x = 0
        row_h = max(im.height for im in row)
        for im in row:
            sheet.paste(im, (x, y))
            x += im.width
        y += row_h
        if gap and y < height:
            draw.rectangle((0, y, width - 1, y + gap - 1), fill=divider)
            y += gap
    part = Path(str(out_path) + ".part")
    save_png(sheet, part)
    os.replace(part, out_path)
    return (out_path, width, height)


def _tag_mask(text, pattern):
    """One flag per character. The flag is True where the character is part
    of a marker tag from this packer, matched by `pattern`. All flags are
    False when pattern is None, the default. The text then has no tag, and
    pack() colors nothing as a tag. Get the pattern from
    tag_pattern_from_legend(). Do not guess it. A [#N]-shaped run in the
    source then never gets the color of a marker."""
    mask = [False] * len(text)
    if pattern is None:
        return mask
    for m in pattern.finditer(text):
        for i in range(m.start(), m.end()):
            mask[i] = True
    return mask


# A 0.85 line gap costs 13 to 20 percent fewer tokens than 1.0 at each pixel
# size, and the glyph the model reads does not change.
LINE_GAP = _S["space.line_gap"]


def pack(text, size, out_stem, spacing=LINE_GAP, colors=True, tag_pattern=None,
        reader=None):
    # Reject a size under the scored floor of the model. `reader` is optional
    # and defaults to None. A caller that already computes a correct size from
    # common.font_size() or common.MEASURED_MODELS then sees no change. A
    # caller that names its model gets the floor even when its own size math
    # is wrong. The code raises the size and never lowers it. A larger image
    # costs only a few more tokens, and a smaller one gives wrong answers.
    if reader is not None:
        floor = RISKY.get(reader, RISKY_DEFAULT)
        if size < floor:
            print(FLOOR_NOTE % (size, reader, floor, floor), file=sys.stderr)
            size = floor

    # Flatten here, not in the caller. A line break that the font cannot
    # render disappears, and the lines of the page then run together with no
    # mark at the end of a line. flatten() on flat text finds no line break
    # and changes nothing. Two calls are safe.
    text = flatten(text)
    big = big_mask(text)
    tag = _tag_mask(text, tag_pattern)
    ident_px = max(size, IDENT_PX)
    regular = load(REGULAR, size)
    bold = load(BOLD, size, True)
    big_regular = load(REGULAR, ident_px)
    big_bold = load(BOLD, ident_px, True)
    line_h = max(1, round(size * spacing * LINE_FACTOR))
    big_line_h = max(1, round(ident_px * spacing * LINE_FACTOR))

    widths = {}
    grouped = {}

    def face(is_big, is_bold, ch=None):
        base = ((big_bold if is_bold else big_regular) if is_big
                else (bold if is_bold else regular))
        off = ((GROUP_PX.get(group_for(ch), 0.0)
                + (char_over(ch, "px", 0.0) or 0.0))
               if ch is not None else 0.0)
        if not off:
            return base
        key = (base.size, off, is_bold)
        if key not in grouped:
            grouped[key] = load(BOLD if is_bold else REGULAR,
                                base.size + off, is_bold)
        return grouped[key]

    def char_w(ch, is_bold, is_big=False):
        key = (ch, is_bold, is_big)
        if key not in widths:
            extra = WORD_SPACE if ch == " " else LETTER_SPACE
            extra += char_over(ch, "adv", 0) or 0
            widths[key] = face(is_big, is_bold, ch).getlength(ch) + extra
        return widths[key]

    def measure(pairs):
        """Width of a run of (character, big, tag) triples."""
        total = 0.0
        for ch, b, _t in pairs:
            _c, bold_flag = classify(ch, colors)
            total += char_w(ch, bold_flag, b)
        return total

    def height_of(pairs):
        """A line takes the height of its tallest character."""
        return big_line_h if any(b for _c, b, _t in pairs) else line_h

    pairs = list(zip(text, big, tag))

    # The target is a square. A square uses the patch budget best.
    max_text_w = CAP_W - 2 * PAD
    total_w = measure(pairs)
    target = math.sqrt(total_w * line_h * RATIO) if total_w else 180
    target = min(max(target, 180), max_text_w)

    # The API pads each image up to whole 28 px patches and charges for the
    # padding in any case. A wider page up to the next boundary is free room
    # and never a cost.
    grid_w = (max_text_w + 2 * PAD) // PATCH * PATCH - 2 * PAD
    snapped = -(-int(target + 2 * PAD) // PATCH) * PATCH - 2 * PAD
    if snapped <= grid_w and snapped <= max_text_w:
        target = snapped

    # Greedy wrap on spaces. The wrap splits any word too long to fit. A line
    # is a list of (character, big, tag) triples, not a string, because a
    # string cannot hold the flags that mark the characters that render
    # bigger or in the marker color.
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

    # Fill a page. Stop before the line that makes the API downscale the page.
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

        img = Image.new("RGB", (width, height), BACKGROUND)
        draw = ImageDraw.Draw(img)
        y = float(PAD)
        for line in page:
            x = float(PAD)
            row_h = height_of(line)
            for ch, is_big, is_tag in line:
                color, is_bold = classify(ch, colors)
                # A marker tag has one color for the whole run. A tag from
                # this packer then never looks like a literal [#1] from the
                # source, which gets the red-blue-red of the ordinary
                # per-character classes.
                if is_tag and colors:
                    color = PALETTE["tag"]
                # All characters are on one baseline. A bigger character grows
                # upward out of the line and does not move the rest down.
                top = y + row_h - (ident_px if is_big else size) - 1
                if ch in CHAR_OVER:
                    # The offset of the character, and a second render one
                    # pixel to the right when its entry sets thick.
                    ox = char_over(ch, "dx", 0) or 0
                    oy = char_over(ch, "dy", 0) or 0
                    spots = ((ox, oy), (ox + 1, oy)) if char_over(
                        ch, "thick", False) else ((ox, oy),)
                else:
                    spots = ((0, 0),)
                for ox, oy in spots:
                    draw.text((x + ox, top + oy), ch,
                              font=face(is_big, is_bold, ch), fill=color)
                x += char_w(ch, is_bold, is_big)
            y += row_h

        path = Path("%s-%d.png" % (out_stem, number))
        # The same one-step move as in composite(). No process sees a
        # half-written page.
        part = Path(str(path) + ".part")
        save_png(img, part)
        os.replace(part, path)
        written.append((path, width, height))

    return written, int(target), line_h


def reader_size():
    """The pack size of this session and the model profile, or 17 and
    "unknown" when the function cannot import common.py.

    The command line uses this size when --size is absent. The size must
    match the size of the hooks. For this reason the function gets it from
    common.font_size(). A try block guards the import, because a copy of
    this file can run with no common.py beside it."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from common import font_size, resolved_reader
        return font_size(), resolved_reader()
    except Exception:
        # common.py is absent, and the code cannot read CODE_PX. 17 is its
        # value.
        return 17, "unknown"


def main():
    ap = argparse.ArgumentParser(description="Pack text into a dense image a vision model reads.")
    ap.add_argument("input", help="text file to pack, or - for stdin")
    size_default, profile = reader_size()
    ap.add_argument("--size", type=int, default=size_default,
                    help="font size in px. Defaults to the plugin's one size, "
                         "17. Below 12 the tool prints a warning, because a "
                         "model misreads digits below 12.")
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

    # The API charge for an image is its patch count and nothing more. A
    # pipeline that gives the image to an agent also pays its own handover
    # cost. The saving on the plugin's receipt is lower than this one by that
    # cost.
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
        print("model        NOT FOUND. The tool uses the default, %d px." % args.size,
              file=out)
    elif profile:
        print("model        %s profile, %d px" % (profile, args.size), file=out)
    print("as text      %d tokens" % round(text_tokens), file=out)
    print("as image     %d tokens" % image_tokens, file=out)
    floor = RISKY.get(profile, RISKY_DEFAULT)
    if args.size < floor:
        print("WARNING      %d px is under the %d px floor measured for this model. "
              "A model misreads digits under this floor, even in color. Verify a test image first."
              % (args.size, floor), file=out)
    if saving > 0:
        print("saving       %.0f percent, patches only. The plugin's receipt "
              "also counts the handover cost, about 148 tokens for one image. "
              "The receipt shows a saving a few points lower for the same report."
              % saving, file=out)
    else:
        print("WORSE by     %.0f percent. Send the text instead." % -saving, file=out)


if __name__ == "__main__":
    main()
