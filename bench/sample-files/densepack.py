"""The engine. Turns a wall of text into one small picture.

HOW THIS FILE FITS, in plain words: everything else here is plumbing, this is
the machine the plumbing feeds. It lays the words out in tiny type, colors the
characters that look alike so they cannot be confused, keeps the image inside
the exact size the AI reads without shrinking, and saves it as a PNG. It is a
faithful port of the DensePack browser app in the folder above, same rules,
same colors, same measurements.

ORIGINAL NOTE: Pack text into the smallest image the reader can still read.
The size is the plugin's one size, common.CODE_PX, for every reader.
--size overrides it. The per-reader sizes went on 12 September 2026.

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

# Every number and colour below comes from style.load(). The defaults in
# style.py are the values this file held before, so a run with no style.json
# on disk draws the same bytes. tools/tuner.py is what writes that file.
_S = style.load()

# The API's real limits, taken from the app. The app follows the resize rule
# Anthropic publishes rather than guessing at it; this file holds only the
# constants that rule produces, not an implementation of it. They are the same for every model on
# the high-resolution tier, so they do not change with the reader.
# The API accepts 2576 px on the long edge for a single image, but a request
# holding more than 20 images gets a stricter limit: any dimension over
# 2000 px is shrunk, and shrinking destroys text this small. A busy session can
# queue more than 20 packed reports, so every image is built under 2000 on
# both sides. 1988 is 71 patches of 28 px, the largest patch-aligned edge
# under that limit. This rule was set; recorded here 16 August 2026.
EDGE = _S["page.edge"]  # longest side this packer will produce; past 1568 the
                   # delivery layer can shrink an image silently, measured
                   # 2 September 2026 on three contaminated bench pages
MAX_TOK = _S["page.max_tok"]   # most patches the API accepts per image
CAP_W = _S["page.cap_w"]       # largest guaranteed-no-downscale canvas
CAP_H = _S["page.cap_h"]
RATIO = _S["page.ratio"]       # a square uses the token budget best

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
# ONE SIZE FOR EVERY READER, from 11 September 2026. This held a size per
# model and they were four names for one number, because one image is
# drawn for all of them and common.READER_SIZES already returns the same
# size for each. The map stays so callers that ask by reader name still
# work; every entry now answers with font.px.
RISKY = {"fable": _S["font.px"], "opus": _S["font.px"],
         "sonnet": _S["font.px"]}
RISKY_DEFAULT = _S["font.px"]  # used when the profile cannot be read

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

# A page over 512,000 bytes reaches the model as a JPEG, not as the PNG on
# disk. The number is a constant in the Claude Code binary, read out of it on
# 8 September 2026: `var yje=512000` beside `imageMaxRawBytes:307200` and
# `imageMaxRawBytes:512000`, and the Read tool passes yje when the session is
# local. Over it the file is re-encoded by a JPEG quality search, 90 down to
# 20. No setting reaches the number: the settings schema has no image key.
#
# MEASURED the same day on one 756 by 1120 page read in an isolated session:
# at 202,948 bytes it arrived as image/png, at 574,654 bytes as image/jpeg,
# and the JPEG copy held 87,307 colours where the file holds 4,700. The
# re-encode lands on the glyph edges, which is where a reader loses a letter:
# a Sonnet run answered densepack-readone for the densepack-readonce drawn on
# the page. So a page is written to fit under the number instead, keeping
# every pixel position and rounding only the anti-aliased shades.
#
# The number was held in a constant named CLAUDE_CODE_IMAGE_CAP until
# 10 September 2026. Nothing read it. PNG_BYTE_CAP below is the cap the
# renderer enforces, and save_png() is what enforces it.
# 250,000 since 8 September 2026. The cap was 500,000, the size past
# which Claude Code turns a page into a JPEG. The unsnapped Opus page
# holds 4,870 colours and writes 487,088 bytes, under the old cap and
# twice the snapped page's 238,888. From a 256 colour palette the same
# page writes 172,358 bytes and 117 of its 550,621 ink pixels change
# colour, 0.02 per cent, with every glyph in the same place.
PNG_BYTE_CAP = 250000
PALETTE_STEPS = (256, 128, 64, 32)


def save_png(im, path):
    """Write a PNG small enough to reach the model as a PNG.

    The full-colour page is written first, and it stands when it fits. A page
    over the cap is written again from a palette, fewest colours last, and the
    first one under the cap is kept. A page that fits under none of them is
    left at its smallest, which is still better than the JPEG that follows.
    """
    # Written beside the name and moved onto it in one step, the same rule
    # sheet.save above follows: a reader served the path while this function
    # was writing its second, smaller copy received the first copy cut in
    # half. MEASURED 8 September 2026 on a sixteen file run: one 756 by 1148
    # page reached the model as 327,769 bytes with no IEND chunk, and the
    # picture would not decode.
    part = str(path) + ".part"
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
    """os.replace that waits out a busy destination.

    On Windows a replace onto a file another process holds open raises
    PermissionError. FOUND 13 September 2026 on a thirty-two file read:
    three of thirty-two draws died on that error, each leaving a .part file
    beside a finished page one, because the read gate of a neighbouring Read
    opens page files in the drop folder to measure them while this draw
    writes its winner again. Forty tries at fifty milliseconds is two
    seconds, longer than any measure holds a file open.
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
# One ink for every character, or None for the per-group colours that ship.
UNIVERSAL_INK = _S["ink.universal"]
# A px offset a character group draws at, added to the body size. Every one
# is zero in the shipped renderer.
GROUP_PX = _S["font.group_px"]
LETTER_SPACE = _S["space.letter_text"]
WORD_SPACE = _S["space.word"]
LINE_FACTOR = _S["space.line_factor"]
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
IMAGE_BLOCK = _S["page.image_block"]

# Every pair of characters that look alike in small type. Each entry is one
# edge in a confusion graph, and the coloring below gives no two characters
# joined by an edge the same color. Written as pairs so a reader can check one
# without reading the whole map.
#
# The list started from the standard small-type look-alikes and gained every
# pair a reader actually confused in the tests of 25 August 2026: 8 read as 3
# and as 9, 9 read as 0, 5 read as 3, O read as D, S read as D.
CONFUSABLE = [tuple(pair) for pair in _S["ink.confusable"]]
# The pairs themselves live in style.py, under ink.confusable, so one
# file holds every value the renderer draws with. The measurement
# records for each batch stay in the comment above.

# Nine colors, spread around the hue circle so no two are close, and each one
# dark enough to stay itself when the type is antialiased at 8 px.
INK = {name: _S["ink." + name] for name in
       ("black", "blue", "green", "magenta", "orange", "teal", "red",
        "purple", "lime")}

# The five the alphanumerics use, in the order the coloring hands them out.
# black first, because it takes the largest group and is the most legible.
#
# These five are the ones that have to survive antialiasing at 8 px, because a
# letter and a digit are the same shape at that size and the color is the only
# thing left. The closest two are 210 apart on the sum of their channel
# differences. Blue and a teal sat 140 apart in the first attempt on
# 25 August 2026, which test_palette.py refused.
ALNUM_INKS = tuple(_S["ink.lookalike_groups"])


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
PALETTE = {name: _S["palette." + name] for name in
           ("num", "sym", "nl", "punct", "tag")}

# Shape-confusion pairs among the symbols. Each would otherwise share the one
# symbol color with the character it is most often mistaken for.
CONFUSION = dict(_S["palette.confusion"])

NL_MARK = _S["mark.pilcrow"]

# The DejaVu Sans Mono pair this repo carries in plugin/fonts. Every system
# that is not Windows reads the same two files, so a packed image drawn on
# Linux and one drawn on macOS carry identical glyphs and identical pixel
# sizes. The licence beside them is the Bitstream Vera licence, which permits
# redistribution.
FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
BUNDLED_REGULAR = str(FONT_DIR / "DejaVuSansMono.ttf")
BUNDLED_BOLD = str(FONT_DIR / "DejaVuSansMono-Bold.ttf")

# The font each platform ships, Windows first, then the bundled copy, then
# the system paths on Linux and macOS. Pillow's built-in fallback font
# ignores the size argument and returns a fixed bitmap, so a missing font
# would draw the image at the wrong size and print a saving that never
# happened. load() raises instead of falling back, and the caller passes the
# text through unpacked, which is the same refuse-when-worse rule the rest of
# the plugin follows.
#
# Windows draws in Verdana, set 2 September 2026. Verdana is proportional,
# and the draw loop below measures every glyph with getlength, so no fixed
# cell width is assumed anywhere. Verdana's licence forbids bundling, so
# every other system falls to the bundled DejaVu Sans Mono and resolves to
# one known file before any system path is tried.
REGULAR = list(_S["font.regular"])
# One face only, since 2 September 2026: the characters the
# classifier marks bold draw in the same regular face, so no second font
# file is ever loaded.
BOLD = list(_S["font.bold"])



# What has to survive character for character. A token of 8 or more that mixes
# letters with digits, optionally joined by hyphen, underscore, dot or slash,
# or a number written in comma groups. That is an agent id, a hash, a commit, a
# session id, a file name and a token count.
#
# A plain English word never mixes letters with digits, so prose is untouched.
# Measured 25 August 2026 over 42 real agent reports, 362,319 characters: this
# marks 0.96 per cent of them, and the image grows 1.20 per cent.
# The joiners may run two deep since 8 September 2026, so a path through a
# dot folder, ab-lead\.claude\densepack-vault, is one token: with one joiner
# the token ended at ab-lead, the next began at claude, and a Sonnet reader
# handed the two tags composed the path without its dot, found nothing at
# it, spent six tool calls and gave up.
IDENT_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-_./\\]{1,2}[A-Za-z0-9]+)*")
IDENT_NUMBER = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+")

# The tag threshold, PLAN-FABLE.md step 7, 29 August 2026: fewer strings get
# tagged. Every string this project has scored a reader on, MATH.md "Identifiers
# never go through the image", was 8 characters or longer, from
# "22,520,080" up to the 36 character "574f750d-cb49-50c4-1653-013cfc2d5b67",
# and every one of them read wrong at some drawn size before it was lifted. No
# string under 8 characters has ever been scored misread, at any px this
# packer draws. _is_identifier already held this floor for the letter and
# digit mix; IDENT_NUMBER held none, so a comma grouped number as short as
# "1,234" was tagged though nothing that short has ever been shown to misread.
# Applying the one measured floor to both closes that gap instead of adding a
# second, unscored one.
MIN_IDENT_CHARS = _S["font.min_ident_chars"]

# The size an identifier is drawn at, when one is drawn at all. Zero means the
# prose size, which is what ships: lift_identifiers() takes every identifier
# out of the image and sends its value as text, so nothing is left to enlarge.
#
# Drawing them at 12 px was measured on 25 August 2026 and it works, partly. It
# took Fable 5 from 0-to-4 of 5 up to 4, 4, 4 of 5 and Opus 5 from 2-to-3 up to
# 4 of 5, for 4.54 per cent more pixels. Every failure that remained was the
# same string in the same place. Set this to 12 to turn that back on; the code
# that reads it is still here.
IDENT_PX = _S["font.ident_px"]


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


# OFF from 12 September 2026, a design decision. The lift dates from 25 August
# 2026, when an enlarged identifier was read back wrong; every page has
# carried the look-alike colouring since, and the lift now costs the reader
# every path and hash in a packed command output, drawn as a tag it cannot
# open. With the switch off lift_identifiers() returns the text unchanged and
# an empty legend, so no caller writes a sidecar and no tag is drawn. Set it
# back to True to get the tags and the legend file again.
LIFT_IDENTIFIERS = False


def lift_identifiers(text, start=1):
    """Replace every identifier with a short tag and return the values.

    Does nothing while LIFT_IDENTIFIERS is False, see the note above it.

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


def group_for(ch):
    """The group a character's size offset is looked up under.

    The names match the keys of style.py's font.group_px. A look-alike
    character is its own group, because that is the set under test for a
    larger draw than the body text since 4 September 2026, and the backtick
    and the comma are both in it.
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
    """Color and weight for one character, the universal ink laid over it,
    and the character's own override ink over both."""
    ink, bold = _classify(ch, colors)
    if colors and UNIVERSAL_INK is not None:
        ink = tuple(UNIVERSAL_INK)
    over = char_over(ch, "ink")
    if colors and over:
        ink = over
    return ink, bold


# One character, everywhere it appears. ADDED 4 September 2026 for the
# tuner; empty in the shipped renderer. codepack reads the same map
# through its own copy of these two names.
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


def pages_pdf(paths, out_path):
    """Bind several packed pages into one PDF, one page per image.

    The delivery rule this exists for: one Read call returns every page of a
    file, and no tool result ever asks the model to Read again for more pages.
    composite() answers that by stacking, and refuses when the stack passes
    CAP_H; side by side is no answer on a code file, measured 4 September 2026
    on bench/gdcorpus/main.gd at 10 px, where two sheets stack to 1176 by 2856
    and sit side by side at 2352 by 1428, both over the 1568 cap. A Read of a
    PDF returns each page as its own picture inside the one tool result, so
    the pages arrive whole with no second Read and no sheet to shrink.

    The pages are written at 72 points per inch, one point per pixel, so a
    page keeps the exact size it was drawn at. Returns the PDF path, or None
    when nothing could be bound; the caller keeps the PNG pages, which is what
    the patch price is still read from.

    The writer here is this file's own, and it writes every page through
    FlateDecode, which is zlib and gives back the bytes it was handed.
    Pillow's PdfImagePlugin writes an RGB page through DCTDecode, which is
    JPEG: measured 5 September 2026 on an 8 px code page, that path changed
    96.00 per cent of the pixels with a worst channel error of 176 of 255,
    and a 256 colour palette page still changed 8.26 per cent. This writer
    changes none.
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
        # draws a page at 72 points to the inch, one point one pixel, so this
        # box hands the reader the PNG's pixels unchanged. The three quarter
        # box tried on 5 September 2026, for a viewer's 100 per cent, made
        # such a rasterizer shrink every glyph by a quarter first; a viewer's
        # zoom is the place to scale, not the page box.
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
    # every page names its parent, so the number above has to be the real one
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

    sheet = Image.new("RGB", (width, height), BACKGROUND)
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
    save_png(sheet, part)
    os.replace(part, out_path)
    return (out_path, width, height)


def composite_grid(paths, out_path):
    """The pages of one file laid side by side, left to right then down,
    with a divider line between them, as one PNG the API will not downscale.

    Returns (out_path, width, height), or None when even the grid would be
    downscaled, so the caller falls back to the vertical composite or the
    PDF. Added 6 September 2026: the count_tokens endpoint bills a PDF page
    about 1,577 tokens flat whatever its pixels, so three 392 by 700 pages
    cost 4,780 as a PDF and 996 as PNGs. A grid of 392 px pages holds four
    across under the 1568 px edge and two rows under it, eight pages in one
    Read at about 1,400 patches a row. bench/session-2026-09-06/PAIR-2026-09-06.md.
    """
    pages = []
    for path in paths:
        try:
            pages.append(Image.open(path).convert("RGB"))
        except Exception:  # noqa: BLE001
            continue
    if not pages:
        return None
    # No gap between columns: a page ends in its own white margin, and four
    # 392 px pages are exactly the 1568 px edge. A divider line sits between
    # rows, where nothing else marks the break.
    gap = int(_S["page.divider_width"])
    divider = tuple(_S["page.divider"])
    forced = int(_S.get("page.grid_per_row", 0) or 0)
    per_row = forced if forced else max(1, EDGE // max(im.width for im in pages))
    rows = [pages[i:i + per_row] for i in range(0, len(pages), per_row)]
    width = max(sum(im.width for im in row) for row in rows)
    height = sum(max(im.height for im in row) for row in rows) + gap * (len(rows) - 1)
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
        if y < height:
            draw.rectangle((0, y, width - 1, y + gap - 1), fill=divider)
            y += gap
    part = Path(str(out_path) + ".part")
    save_png(sheet, part)
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
LINE_GAP = _S["space.line_gap"]


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

        img = Image.new("RGB", (width, height), BACKGROUND)
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
                if ch in CHAR_OVER:
                    # The character's own nudge, and a second draw one
                    # pixel right when it is marked thick.
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
        # Same one-step move as sheet.save above: no reader ever sees a
        # half-written page.
        part = Path(str(path) + ".part")
        save_png(img, part)
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
        print("reader       NOT READ. Defaulted to %d px." % args.size,
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
