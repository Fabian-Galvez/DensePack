"""Returns the output of a Bash call as an image, in the same tool result.

A Read of a file returns an image with no extra turn, because read_image.py
replaces the Read result with its image after the Read runs. This hook does
the same for Bash output. It replaced an older route that wrote the output
to a file and returned a pointer that the model read in a separate turn.
That route took 3 to 7 turns and 1.3 to 2.9 times the billed tokens of
plain text.

PostToolUse on Bash. The command already ran, and its output is in
tool_response. When the images of that output cost fewer tokens than the
text, the hook returns updatedToolOutput in the image shape of Bash, with
stdout as a PNG data URL and isImage true. Claude Code then shows the model
the image in place of the text, in the same result, and the model uses the
same number of turns as with text. A Bash result holds one image. Output
that needs more than one image returns image 1 in the result, and a note
beside it names the path and the lines of each other image (see
pages_output()). A model reads a number such as 745120 from such an image.
In each other case, the output stays text. A line that holds a git --stat
bar, a pip list rule, a number of 18 or more digits, a random ID with a
capital I or a small l, only spaces, or a tab inside a line goes beside the
image as exact text (see TEXT_ONLY and exact_lines_note()).

Text copy. Each output returned as an image keeps its literal text in
.claude/densepack-vault/images/bash-output-<id>.txt. The image next to it is
bash-output-<id>.txt-image-1-of-N-DensePack.png. The key shows
file=bash-output-<id>.txt, and the model can Grep that file for an exact
string. Output that stays text needs no copy.

Grep output cannot take this route. The output shape of Grep has no image
form. Claude Code rejected the image shapes of Read and Bash on a Grep result.
A data URL in the content field of Grep reached the model as base64 text and
cost 70 per cent more. Grep output stays text.

A fault never blocks the call. After a fault, the output stays as it was.
"""
import base64
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (actor_key, actor_reader, disabled, emit, ensure_pillow,  # noqa: E402
                    gets_images, read_event)

# Below this many characters, the text costs less than the image, and the
# hook packs nothing. The bill on Opus 5.5, with the one-row key and the
# bottom trim below, against the rate that claude -p billed for Python text,
# 2.885 characters a token, gives these costs. 150 characters cost 81 tokens
# as an image and 51 as text, 300 cost 111 and 103, and 500 cost 136 and
# 173. The break-even is near 330. With the full two-row key and no trim, it
# was near 700. The price check below uses the plugin rate of 2.40, which
# counts code text at a higher cost than the bill, and near the break-even
# that check is not exact. For this reason the floor is above the
# break-even.
MIN_CHARS = 400

# Output lines that hold one of these go beside the image as exact text. In
# a test, Opus 5.5 copied real Bash output from its images two times,
# and two kinds of string failed.
#   A random ID that holds a capital I or a small l. 76 of 108 were typed
#   wrong, each time with I and l swapped. The two letters have the same
#   pixels on the page, and in a random ID no word tells them apart.
#   A git --stat bar. 54 of 72 runs of + or - were typed with the wrong
#   count, even runs of 6.
# All other strings were typed right. These were random IDs without I or l
# (106 of 108), hex hashes of 7 to 64 characters (167 of 168), numbers of 8
# to 17 digits (160 of 160), UUIDs (27 of 28), temp folder names (96 of 96)
# and table rules between pipes (54 of 54). A word keeps I and l apart.
# Lowercase temp names with l or 1 (64 of 64), a word and a number such as
# logfile12 (36 of 36) and code names such as ILogger and IReadOnlyList (36
# of 36) were typed right. For this reason only an ID that mixes capitals
# and small letters counts. The model typed 2 of 64 numbers of 18 to 20
# digits wrong in this test and 4 of 44 in an earlier test, and these
# numbers count too. In earlier tests, the model lost each line of only
# spaces (14 of 14), each tab inside a line (18 of 18) and a pip list rule
# of 20 dashes (2 of 2).
TEXT_ONLY = re.compile(
    r"^\s*\S.*\|\s+\d+\s+[+-]+$"                           # a git --stat bar
    r"|^(?=[ -]*-{9}) *-{3,}(?: +-{3,})+ *$"               # column rules, as pip list prints
    r"|(?<![0-9A-Za-z])\d{18,}(?![0-9A-Za-z])"             # a number of 18+ digits
    r"|(?<![0-9A-Za-z])(?=[0-9A-Za-z]*[Il])(?=[0-9A-Za-z]*\d)(?=[0-9A-Za-z]*[A-Z])(?=[0-9A-Za-z]*[a-z])"
    r"(?![A-Za-z]?[a-z]+\d+(?![0-9A-Za-z]))"               # not a word and a number, such as Makefile2
    r"[0-9A-Za-z]{8,}(?![0-9A-Za-z])"                      # an ID of letters and digits with I or l
    r"|(?<![0-9A-Za-z])(?=[A-Za-z]*[Il])(?=[A-Za-z]*[a-z])(?=[A-Za-z]+[A-Z]{2})"
    r"(?![A-Za-z]*[a-z]{4})[A-Za-z]{8,}(?![0-9A-Za-z])"    # letters in random case with I or l
    r"|^[ \t]+$"                                           # only spaces or tabs
    r"|^(?![ ]*(?:[^ \t\n]+[ ]+)?\d+\t+[^\t\n]*$)[ \t]*[^ \t\n][^\n]*\t",  # a tab inside a
    # line, but not the tab after a line number as cat -n or nl print it
    # ("    12<tab>code"), even behind one label that a script adds
    # ("+4      1<tab>code"). That tab only separates the number from the
    # line. A tab after other words, as in git ls-files -s, or later in the
    # line stays risky. When this pattern matched the numbered tab too, 4
    # outputs of 4,235 to 7,377 characters of numbered code stayed text for
    # these tabs alone.
    re.M)

# The lines that TEXT_ONLY matches go beside the image as exact text, and the
# rest of the output still goes as the image. An earlier version kept the
# whole output as text on one match, and cat of a 22,024 character file
# stayed text for one code name on one line. The price check counts this
# note, and when the exact lines cost more than the image saves, the output
# stays text. An image with only the numbers of those lines cost more. On a
# sample where each line is risky, the model read each line from the text
# copy to type it exactly, at $0.0825 against $0.0669 for the text.
def risky_rows(text):
    """The 0-based numbers of the lines TEXT_ONLY matches, in order."""
    return sorted({text.count("\n", 0, m.start()) for m in TEXT_ONLY.finditer(text)})


def exact_lines_note(text):
    """Returns the note that gives the exact text of each line TEXT_ONLY
    matches, or "" when no line matches."""
    rows = text.split("\n")
    hits = risky_rows(text)
    if not hits:
        return ""
    return ("A model can misread these lines of the image, such as a capital I "
            "against a small l. Their exact text, by line number:\n"
            + "\n".join("%d: %s" % (n + 1, rows[n]) for n in hits))


def pick_note(cost, text, exact):
    """The note to send with an image that costs `cost` tokens. The note is
    `exact`, the exact lines, or "" when no line is risky. Returns None when
    the image and the note cost as much as the text, and the output then
    stays text."""
    import densepack as dp
    if cost + round(len(exact) / dp.CHARS_PER_TOKEN) < round(len(text) / dp.CHARS_PER_TOKEN):
        return exact
    return None


def tool_output(out, note=""):
    """The PostToolUse answer that shows `out`, with `note` as text beside
    it."""
    spec = {"hookEventName": "PostToolUse", "updatedToolOutput": out}
    if note:
        spec["additionalContext"] = note
    return {"hookSpecificOutput": spec}


# Output under this many characters gets a small pack. It uses the slim key
# and a search over each whole-patch width. A few lines then fill their
# patches and do not pay for a 756 pixel row each.
SLIM_MAX_CHARS = 1000
# The narrowest width that the search tests. Narrower rows wrap more, and the
# key takes more rows. The search prices the two effects.
SLIM_MIN_WIDTH = 224
# The widest width that the search tests.
SLIM_MAX_WIDTH = 756
SLIM_ENV_NAMES = ("DENSEPACK_SLIM_KEY", "DENSEPACK_KEY_INDENT", "DENSEPACK_KEY_PIPE",
                  "DENSEPACK_WIDTH_CHOICES", "DENSEPACK_NATIVE_ONLY", "DENSEPACK_KEY_ONE",
                  "DENSEPACK_KEY_SPACES")


def slim_env(text):
    """Return the settings that codepack reads for a small output.

    The settings hold the slim key and each whole-patch width from
    SLIM_MIN_WIDTH to 756. The slim key names the indent count, a run of
    spaces, the pipe and the digit 1 only when the output uses them."""
    lines = text.split("\n")
    return {
        "DENSEPACK_SLIM_KEY": "1",
        # The red box names a space count for an indent, a run of two or more
        # spaces, or spaces at the end of a line.
        "DENSEPACK_KEY_INDENT": "1" if any(l[:1] == " " for l in lines) else "0",
        "DENSEPACK_KEY_SPACES": "1" if any("  " in l.lstrip(" \t") or (l.endswith(" ") and l.strip())
                                          for l in lines) else "0",
        "DENSEPACK_KEY_PIPE": "1" if "|" in text else "0",
        "DENSEPACK_KEY_ONE": "1" if "1" in text else "0",
        "DENSEPACK_WIDTH_CHOICES": ",".join(str(w) for w in range(SLIM_MIN_WIDTH, 757, PATCH)),
        # The renderer uses the glyph size only. It never widens or resamples
        # a glyph. See codepack._fit_width().
        "DENSEPACK_NATIVE_ONLY": "1",
    }


# The page layout adds one row pitch of slack under the last line. The
# layout uses the 28 px patch padding to hide it. On a short output, the
# padding does not hide it. A 150 character output packs to 756 by 140, with
# the last ink at row 89. The bottom 50 rows are blank and cost 27 of the 137
# tokens of the image. TRIM_MARGIN is the margin under the last ink row, in
# pixels.
TRIM_MARGIN = 4
PATCH = 28


def trim_bottom(path):
    """Crop the blank rows under the last ink to the smallest whole patch row
    that still holds the ink and TRIM_MARGIN. The crop never removes ink."""
    from PIL import Image
    import densepack as dp
    with Image.open(str(path)) as im:
        im = im.convert("RGB")
    w, h = im.size
    last = dp.last_ink_row(im)
    keep = -(-(last + 1 + TRIM_MARGIN) // PATCH) * PATCH
    if keep < h:
        dp.save_png(im.crop((0, 0, w, keep)), str(path))


def copy_folder():
    """Return .claude/densepack-vault/images/, where each Bash output image is
    next to its text copy. Return None when the folder path passes through a
    link, because a link can put the copies outside the project."""
    from common import project_dir, through_link, vault_dir
    images = vault_dir() / "images"
    if through_link(project_dir(), images):
        return None
    images.mkdir(parents=True, exist_ok=True)
    if through_link(project_dir(), images):
        return None
    return images


def write_copy(path, text):
    """Write the literal text of the output to path, byte for byte. The write
    does not translate newlines, and the file holds exactly what the command
    printed."""
    Path(path).write_bytes(text.encode("utf-8"))


def same_page_each_width():
    """True when each width of the draw_small() search packs the same page
    as the pack that just ran.

    The UNIFORM pack fixes the glyph scale that one glyphless pack at the
    set width gives. It then packs each image width in UNI_WIDTHS at that
    scale. The width that draw_small() sets reaches the layout only through
    that scale. The scale is the page width over the width of the layout
    page, padded to whole patches. With the layout at the page width and no
    supersample, the layout page is the page width less a fixed gutter. The
    padding then returns the page width at each whole-patch width, or at
    none. A scale of 1.0 at one width is then 1.0 at each width, and each
    width packs the same rows at the same image width. The canvas height
    reads the page width too. A narrower width makes the canvas taller by a
    few white rows at its foot, and save_page() trims each page to its last
    ink. codepack._UNI_R holds the scale of the last pack."""
    import codepack
    s = codepack._S
    return bool(codepack.UNIFORM and codepack._UNI_R == 1.0
                and s.get("page.code_width")
                and s.get("page.code_layout_width") == s.get("page.code_width")
                and int(s.get("page.code_supersample") or codepack.SUPERSAMPLE) == 1)


def draw_small(text, model, title=""):
    """Return the cheapest single image of a small output as (PNG bytes,
    tokens). Return None when the model is not measured or no width fits the
    output on one image. title is the name of the text copy, shown as file=
    in the key.

    The function packs the output once at each whole-patch width from
    SLIM_MIN_WIDTH to 756, at the native glyph size. It trims each image and
    prices it at the billed size. The search inside the renderer prices a
    width before the trim, with its one row of slack under the last line.
    For a 500 character git log, that search chose 728 wide at 158 tokens,
    where 616 wide cost 156. A width whose wrap marks land on a letter ranks
    below each width without that fault. The function calls codepack
    directly, and the trial packs write no manifest rows.

    Under UNIFORM, each width packs the same page (see
    same_page_each_width()). The search then stops after the first width
    that packs, because each later width ties with it and a tie keeps the
    first."""
    import codepack
    import densepack as dp
    from common import MEASURED_MODELS, code_size
    from PIL import Image
    px = MEASURED_MODELS.get(model)
    if px is None:
        return None
    size = code_size(px, model)
    work = Path(tempfile.mkdtemp(prefix="densepack-bashsmall-"))
    best = None
    try:
        for width in range(SLIM_MIN_WIDTH, SLIM_MAX_WIDTH + 1, PATCH):
            env = dict(slim_env(text), DENSEPACK_WIDTH_CHOICES=str(width))
            os.environ.update(env)
            try:
                codepack.CLAMP_HITS[0] = 0
                written, _target, _lh = codepack.pack_code(
                    text, size, str(work / ("w%d" % width)), python=False, reader=model,
                    title=title)
                hits = codepack.CLAMP_HITS[0]
            except Exception:  # noqa: BLE001
                continue
            finally:
                for name in SLIM_ENV_NAMES:
                    os.environ.pop(name, None)
            # The check reads the scale of the pack that just returned. A
            # width whose pack raises an error does not reach the check, and
            # the next width packs. Without UNIFORM, each width packs at its
            # own page width, and an error can depend on the width.
            last = same_page_each_width()
            if len(written) == 1:
                page = Path(written[0][0])
                trim_bottom(page)
                with Image.open(str(page)) as im:
                    cost = dp.image_cost(*im.size)
                rank = (1 if hits else 0, cost)
                if best is None or rank < best[0]:
                    best = (rank, page.read_bytes(), cost)
            if last:
                break
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if best is None:
        return None
    return best[1], best[2]


def image_output(event):
    """Return the PostToolUse output that replaces this Bash output with its
    image, or None to keep the output as text."""
    if event.get("tool_name") != "Bash" or disabled(event.get("session_id")):
        return None
    resp = event.get("tool_response")
    if not isinstance(resp, dict) or resp.get("isImage") or resp.get("interrupted"):
        return None
    text = resp.get("stdout")
    if not isinstance(text, str):
        return None
    # A Windows command ends each line with CRLF. The renderer takes LF only.
    # The Read route gets the same result, because it reads its file with
    # universal newlines. Without this step, write_text() below changes each
    # CRLF to CR CR LF, and the page shows an empty line after each line.
    text = text.replace("\r\n", "\n")
    # The same ceiling as for files, READ_MAX_BYTES in drop_read_gate.py.
    # Output over it stays text, because the pack wait grows with its length.
    from drop_read_gate import READ_MAX_BYTES
    if len(text) < MIN_CHARS or len(text) > READ_MAX_BYTES or "\x00" in text:
        return None
    exact = exact_lines_note(text)
    if not gets_images(event) or not ensure_pillow():
        return None
    import densepack as dp
    import pointer
    from PIL import Image
    from drop_read_gate import FALLBACK_READER
    # Each image keeps its literal text on disk. The text copy is
    # bash-output-<id>.txt. The image next to it is that name plus
    # -image-1-of-N-DensePack.png. The file= field of the key shows the name
    # of the copy. The model can Grep that file for an exact string without
    # a turn to find it. When the hook cannot write the copy, the output
    # stays text.
    copy_name = "bash-output-%s.txt" % str(event.get("tool_use_id") or os.getpid())[-12:]
    if len(text) < SLIM_MAX_CHARS:
        small = draw_small(text, actor_reader(event) or FALLBACK_READER, copy_name)
        if small is None:
            return None
        raw, cost = small
        note = pick_note(cost, text, exact)
        if note is None:
            return None
        try:
            folder = copy_folder()
            if folder is None:
                return None
            write_copy(folder / copy_name, text)
            (folder / (copy_name + "-image-1-of-1-DensePack.png")).write_bytes(raw)
        except (OSError, UnicodeError):
            return None
        out = dict(resp)
        out["stdout"] = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        out["isImage"] = True
        return tool_output(out, note)
    stage_dir = Path(tempfile.mkdtemp(prefix="densepack-bashimg-"))
    stage = stage_dir / copy_name
    stem = copy_name
    image = None
    slim = len(text) < SLIM_MAX_CHARS
    try:
        stage.write_text(text, encoding="utf-8")
        model = actor_reader(event) or FALLBACK_READER
        if slim:
            os.environ.update(slim_env(text))
        _line, image = pointer.draw_drop_file(model, str(stage), actor_key(event), stem,
                                              name=copy_name, source="bash")
    except Exception:  # noqa: BLE001
        image = None
    finally:
        for name in SLIM_ENV_NAMES:
            os.environ.pop(name, None)
        shutil.rmtree(str(stage_dir), ignore_errors=True)
    if image is None:
        return None
    image = Path(image)
    try:
        # A Bash result holds one image. Output of more than one page returns
        # its first page here and names the others in the hook's note.
        if not image.name.endswith("-image-1-of-1-DensePack.png"):
            return pages_output(resp, text, image, _line, copy_name, exact)
        trim_bottom(image)
        with Image.open(str(image)) as im:
            cost = dp.image_cost(*im.size)
        note = pick_note(cost, text, exact)
        if note is None:
            image.unlink(missing_ok=True)
            return None
        data = base64.b64encode(image.read_bytes()).decode("ascii")
        write_copy(image.parent / copy_name, text)
    except (OSError, UnicodeError):
        # The hook does not return an image without a text copy next to it.
        try:
            image.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    out = dict(resp)
    out["stdout"] = "data:image/png;base64," + data
    out["isImage"] = True
    return tool_output(out, note)


def pages_output(resp, text, first, line, copy_name, exact=""):
    """The PostToolUse output for Bash output of more than one page.

    A Bash result holds one image, and for this reason it holds the first
    page. The context note of the hook names each other page and the lines
    it holds, the same as the Read of a long file names its pages, and the
    model Reads the pages it needs. A long output is the text that costs the
    most, and this route packs it. `line` is the status line of
    pointer.draw_drop_file(). Its Pages row holds the path of each page
    after the first, and its Lines row holds the first source line of each
    page. The pages together must cost fewer tokens than the text, or the
    output stays text and the code deletes the pages."""
    import densepack as dp
    from PIL import Image
    rows = (line or "").split("\n")
    pages_row = next((r[len("Pages: "):] for r in rows if r.startswith("Pages: ")), "")
    lines_row = next((r[len("Lines: "):] for r in rows if r.startswith("Lines: ")), "")
    pages = [first] + [Path(p.strip()) for p in pages_row.split(" , ") if p.strip()]

    def drop():
        for p in pages:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        return None

    m = re.search(r"-image-1-of-(\d+)-DensePack\.png$", first.name)
    if not m or len(pages) != int(m.group(1)) or not all(p.is_file() for p in pages):
        return drop()
    cost = 0
    for p in pages:
        trim_bottom(p)
        with Image.open(str(p)) as im:
            cost += dp.image_cost(*im.size)
    extra = pick_note(cost, text, exact)
    if extra is None:
        return drop()
    data = base64.b64encode(first.read_bytes()).decode("ascii")
    write_copy(first.parent / copy_name, text)
    firsts = [int(x) for x in lines_row.split(" , ") if x.strip().isdigit()]
    total = text.count("\n") + (0 if text.endswith("\n") else 1)
    spans = []
    for k in range(len(pages)):
        a = firsts[k] if k < len(firsts) else None
        b = firsts[k + 1] - 1 if k + 1 < len(firsts) else total
        spans.append("lines %d to %d" % (a, b) if a else "")
    others = " , ".join("image %d of %d%s: %s" % (k + 1, len(pages), " (%s)" % spans[k] if spans[k] else "",
                                                   pages[k]) for k in range(1, len(pages)))
    note = ("DensePack packed this Bash output into %d images. This result is image 1 of %d%s. "
            "Read the others for the rest of the output: %s." % (
                len(pages), len(pages), " (%s)" % spans[0] if spans[0] else "", others))
    out = dict(resp)
    out["stdout"] = "data:image/png;base64," + data
    out["isImage"] = True
    return tool_output(out, note + ("\n" + extra if extra else ""))


def main():
    try:
        answer = image_output(read_event())
        if answer:
            emit(answer)
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
