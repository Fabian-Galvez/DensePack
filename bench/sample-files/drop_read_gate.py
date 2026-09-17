"""Stops a raw Read of a text file worth packing, and redirects it to a
drawn image of the same words instead.

HOW THIS FILE FITS, in plain words: PLAN-FABLE.md step 5 built the drop
folder, so a file copied into drop/<model> comes back as an image, drawn
fresh every time, in drops/. Building the folder did not make any agent
use it. This is a PreToolUse hook on Read, for every agent, lead and
subagent alike. verify_gate.py only reaches the lead, and only an image or
a file under a repo's own src or tests tree. subread_gate.py only reaches
a subagent, and points it at cat, packed through Bash, not at the drop
folder. Neither one teaches the drop folder at all, which is the gap this
file closes.

WHAT IT DOES. A Read of a text file at or over the packing floor, with no
sibling image already sitting beside it (see sibling_image() in common.py
for the file that does have one), is copied into this session's own
drop/<model> folder and drawn immediately, in the SAME hook turn, through
pointer.draw_drop_file(): the one place this plugin turns a dropped file
into an image. The Read is then rewritten to that image, exactly like the
sibling-image redirect, so the agent never copies the file itself and
never spends a retry turn waiting. FIXED 29 August 2026, FIXES-PENDING.md
section 3's remaining gap: an ordinary repo file with no sibling image,
COSTS.md was the real case that surfaced it, used to be let straight
through, because there was nothing for the old code to redirect to.

READING AGENT'S MODEL UNKNOWN. FIXED 29 August 2026, the regression this
same night's brief repaired: drop_and_draw() no longer gives up when
common.event_reader() cannot name the reading agent's model, off a
missing or unreadable transcript_path. It draws at FALLBACK_READER's
size instead, sonnet's 12 px, the largest measured floor, so a reader too
small for the image never happens; only a reader given more pixels than
it needed can. Never the lead's own cached size, which would be wrong
for a subagent as often as right, and never a skipped redirect: a gate
that cannot decide a size still redirects.

FALLBACK, when the automatic draw fails for a real reason (Pillow
missing, the file vanished, or the draw itself raised): the first Read is
denied instead, naming the drop folder to copy the file into by hand. A
retry of the identical Read passes, the same one-deny-then-pass shape
subread_gate.py already uses: an agent about to Edit the file still gets
the real bytes on its second try, so the plugin never deadlocks a Write
or Edit behind a file it will not let the agent read at all.

EXEMPTIONS, each one required or the plugin deadlocks on itself.
  A file already an image: checked by its own suffix. Never by a
  densepack- name prefix; a name prefix is the wrong key for whether a
  file is a picture, because a plugin file can be text too, the exact
  sidecar densepack-bashsrc-*.txt beside every packed image.
  Anything under a scratchpad or temp directory: a .claude folder, a path
  holding "sandbox" or "scratch", or anything under the OS temp root,
  where a test fixture or a working file lives and is never worth a gate.
  The drop folder's own input and output, drop/ and drops/ under
  densepack-vault/, so pointer.py's own scan can still read what it just
  copied or just drew.
  A densepack- named file with NO image beside it, the plugin's own
  bookkeeping (settings, manifest, legend sidecar), the same exemption
  verify_gate.py and subread_gate.py both give them. A densepack- named
  file that DOES have an image beside it, a source-text sidecar such as
  densepack-briefsrc-<stamp>.txt or densepack-src-<agent id>.txt, is not
  exempt: FIXED 29 August 2026, FIXES-PENDING.md section 3, after the name
  prefix alone let a read of that sidecar through even though the drawn
  image right beside it, densepack-brief-<stamp>-1.png or
  densepack-img-<agent id>-1.png, already held the same words. The Read is
  redirected to that image instead, through common.sibling_image(), which
  matches the file's own name against the patterns the packers write and
  checks the image is really on disk before redirecting to it.
  An offset or limit read: already a targeted, economical read.

NEVER CRASH A CALLER. One try around everything; any fault allows the
Read, the same failure mode every gate in this folder chooses.

NO FLOOR, A LIVE COMPARISON INSTEAD. FIXED 30 August 2026, DensePack brief
30 August 2026, job 3. Until this fix, the gate above skipped drawing
altogether whenever the file's byte size was under common.stub_chars(),
1,047 to 1,565 depending on reader at the time (corrected 30 August 2026,
same night, and again the same day after the LINE_GAP move to 0.85; see the
STUB_CHARS note in common.py for the current values).
Those constants are bisected for the
REPORT and BASH routes, whose delivery fee is a printed pointer line plus
one 80 token Read call per image, common.report_pointer()/stub_pointer()
and subagent_stop.READ_TOKENS. This route pays neither: the Read call was
already going to happen (drop_and_draw() rewrites the SAME call, it never
adds one) and no pointer line is ever printed, the redirect happens inside
this one PreToolUse turn. Re-bisected against the production packer with
the fee at zero, `bisect_floor.py` against a real file (MATH.md, tiled to
length), the true crossing point is 10 to 11 characters at 8 px, 15 to 16
at 10 px, 42 to 43 at 12 px, three orders of magnitude below stub_chars().
Applying the higher, wrong floor to a route that pays a lower, near-zero
fee refused a redirect on every file between the true floor and
stub_chars(), which is most of what this route ever sees: a bug, not a
rounding difference. Fixed by dropping the floor pre-check entirely and
measuring instead, the same live comparison subagent_stop.py already
applies with no floor of its own: draw the image, price it in real
patches, price the raw Read in text tokens at the same CHARS_PER_TOKEN
divisor densepack.py holds, and
redirect only when the image is actually cheaper. A file too small to
redirect self-selects out of the comparison; nothing hardcodes where that
point is, so it never goes stale again the way stub_chars() did here.
"""

import hashlib
import sys

from common import (BURST_BYTES, actor_key, actor_reader, actor_size, line_pull,
                    burst_cap, claim_once, disabled, emit, is_subagent,
                    over_cap, queue_cap_row, read_event, sibling_image,
                    tmp_dir, turn_reads, vault_dir)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf",
                  ".ipynb")

# The size drop_and_draw() falls back to when common.event_reader() cannot
# name the reading agent's model. Sonnet's 12 px, the largest of the three
# measured floors (common.MEASURED_MODELS: fable 10, opus 10, sonnet 12), so
# an unreadable folder never happens; only more pixels than a smaller
# reader needed can. Never common.resolved_reader() or common.UNKNOWN_READER,
# both the LEAD's own cached size: a subagent's Read is as often not the
# lead's model as it is, which is JOB 1's own finding.
FALLBACK_READER = "sonnet"

# One marker per session and file, the same shape subread_gate.py uses so a
# retry can still reach the real bytes before an Edit. Only reached now when
# drop_and_draw() below could not draw an image at all.
MARKER = "densepack-dropread-%s-%s"

MESSAGE = (
    "DensePack tried to draw this file as an image automatically and could "
    "not. This file is %s bytes. Do not Read it raw. "
    "Copy it into .claude/densepack-vault/drop/ instead, then "
    "make any other tool call: the scan draws it fresh from the file's "
    "current bytes, the image lands in .claude/densepack-vault/drops/, and "
    "the copy is deleted. Read that image, not this file. This path itself "
    "is never modified by the drop, so edit it as normal once you have the "
    "information. Use the Read tool on this exact path only when you are "
    "about to Edit it: repeat this exact Read and it will pass.\n\n"
    "File: %s"
)


def marker_path(session_id, file_path):
    digest = hashlib.sha256(
        str(file_path).replace("\\", "/").lower().encode("utf-8")
    ).hexdigest()[:12]
    return tmp_dir() / (MARKER % (str(session_id)[:8], digest))


def is_image(path):
    """True only by the file's own suffix, never by a densepack- name
    prefix: a plugin file can be text, the exact-text sidecar beside every
    packed image, so a prefix answers a different question than this one."""
    return path.replace("\\", "/").lower().endswith(IMAGE_SUFFIXES)


def is_plugin_own(path):
    """True only for a densepack- named file that has NO image beside it:
    the plugin's own bookkeeping, never a source-text sidecar that a drawn
    image already covers. See sibling_redirect() for that other case."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not name.startswith("densepack-"):
        return False
    return sibling_image(path) is None


def is_drop_folder(path):
    """True inside densepack-vault/drop/ or densepack-vault/drops/, the
    folder this gate exists to point an agent at, so the scan in
    pointer.py can still read what it just copied or just drew."""
    parts = [p.lower() for p in path.replace("\\", "/").split("/") if p]
    return "densepack-vault" in parts and ("drop" in parts or "drops" in parts
                                           or "drop-gate" in parts)


def drop_and_draw(path, event):
    """Copy `path`'s current bytes into this session's own drop/<model>
    folder and draw them in the SAME hook turn, through
    pointer.draw_drop_file(), the one place this plugin turns a dropped
    file into an image, per FIXES-PENDING.md section 3's instruction to
    wire this to that rather than drawing a second way. Returns (image
    path as a string, its real patch cost, the note the reader receives,
    which since 4 September 2026 holds the legend's own "[#1] = <exact
    text>" rows and never the sidecar's path, empty when nothing was
    lifted and the file fitted one page) or (None, None, None) when nothing
    could be drawn: the file vanished, Pillow is missing, or the draw
    itself failed; main() falls back to the old deny-and-instruct message
    in every one of those cases, which names the SAME three drop/<model>
    folders and lets the agent place the copy itself, so the folder still
    answers the question even when this automatic path cannot.

    The patch cost is read back off the drawn PNG's own pixels, through
    densepack.image_cost(), the identical formula subagent_stop.py and
    bash_pack.py price an image with. main() compares it against the raw
    Read's text tokens, with no delivery fee added on this side: see the
    "NO FLOOR, A LIVE COMPARISON INSTEAD" note above the imports.

    JOB 1, DensePack brief 29 August 2026, FIXED: this used to call
    common.resolved_reader(), the LEAD's own cached model, on the theory
    that bash_pack.py and subagent_stop.py already accept that same limit
    for the images they draw. Those two draw a brief or a report BEFORE or
    DURING a subagent's own turn, when no event yet names the model it
    will run on. A Read is different: it fires from inside the reading
    agent's own turn, and common.event_reader() reads that agent's own
    transcript_path off THIS event, never the lead's cached one, so a
    Sonnet subagent's Read lands in drop/sonnet at its own 12 px floor
    instead of drop/opus at the lead's 10, a size below Sonnet's measured
    floor that made the subagent distrust the image and go re-read the raw
    file, the leak that started this fix.

    REGRESSION FIXED 29 August 2026, found the same night: JOB 1 made
    event_reader() return None whenever it could not name the reading
    agent's model. event_reader() reads the agent's own transcript file
    live, and a transcript not yet flushed to disk at that moment also
    reads as empty. This function returned None right behind it, which
    sent every one of those reads down main()'s deny-and-instruct path
    instead of a redirect. The FIRST such Read denied correctly, but the
    marker main() writes on that deny makes the identical retry pass
    SILENTLY, raw, with no redirect and no message at all: a Read event
    built with no transcript_path, or one whose transcript reads empty at
    that moment, stopped being drawn at all. Not a guess: measured by
    piping a real Read event for plugin/COSTS.md through this script twice
    in a row with no transcript_path on it.

    FIXED the same night, properly rather than by widening the guess:
    common.actor_reader() answers it, in one place for every gate: this
    agent's own spawn record, then Claude Code's own agent-<id>.meta.json,
    then this event's transcript when it is this agent's own file. See
    that function for the order and the 3 September 2026 measurement that
    set it. FALLBACK_READER is tried LAST, sonnet's 12 px, the largest
    measured floor, never the lead's own cached size and never a skipped
    redirect: a gate that cannot decide a size still redirects.
    """
    import shutil
    from pathlib import Path
    import pointer

    model = actor_reader(event) or FALLBACK_READER
    src = Path(path)
    try:
        if not src.is_file():
            return None, None, None, None
    except OSError:
        return None, None, None, None

    # A staging folder of this gate's own, never drop/<model>. FIXED 3
    # September 2026: the copy sat in drop/<model> for the length of one
    # hook turn, and pointer.py's PostToolUse scan, fired by a parallel
    # tool call, found it there, drew it a second time and sent the reader
    # a scan line about a file it never asked for; sixteen files produced
    # 22 to 25 drops on the Opus and Sonnet on arms. The scan lists
    # drop/<model> only, so a copy here is invisible to it.
    drop_dir = vault_dir() / "drop-gate" / model
    try:
        drop_dir.mkdir(parents=True, exist_ok=True)
        dest = drop_dir / src.name
        shutil.copyfile(str(src), str(dest))
    except OSError:
        return None, None, None, None

    # actor_key(event) names the agent that will read this picture, or is
    # None for the lead. It only reaches the manifest row; the size is
    # already this agent's own, through the model resolved above.
    line, image = pointer.draw_drop_file(model, str(dest), actor_key(event))
    if image is None:
        return None, None, None, None

    # draw_drop_file() appends extra rows to line after the scan sentence:
    # "Tags: <full path>" when it wrote a legend sidecar, "Pages: <p2> ,
    # <p3>" when the file needed more than one page, and since 4 September
    # 2026 the legend's own "[#1] = <exact text>" rows under one heading.
    # The rows after the first are the note; the scan sentence is never
    # charged to a reader that ran no scan.
    #
    # The Tags row is read for its path and then THROWN AWAY, never put in
    # note_rows. discard() below needs the path; the reader must not see it.
    # Until 4 September 2026 that row shipped, and pair 53 answered it the
    # way any model does when a message says a value sits in a file: it read
    # the file. Four such Reads, plus a Grep, a Glob and a Bash listing
    # drops/, took the on arm to 16,465 output tokens against the off arm's
    # 3,333 and cut the saving to 4.27 per cent, where pair 52 saved 48.43.
    # The marker rows carry the same values in this same message, so there
    # is nothing left to open.
    #
    # ADDED 4 September 2026: each of those rows now names its own source,
    # "[#1] copied from the file = <text>", built by pointer.marker_rows();
    # the label and heading were reworded the same day, see pointer.py
    # MARKER_HEADING. The heading alone was not enough. Pair 58,
    # Sonnet 5 on the 26 file GDScript corpus, spent 54,319 tokens more than
    # the off arm and grepped five files to confirm two numbers it had
    # already been handed, calling the rows a "misread marker" risk. The
    # label costs 2,065 tokens across the whole corpus, 3.80 per cent of what
    # the verifying cost, and note_tokens below charges every one of those
    # characters against the picture before the picture is kept. Six Sonnet
    # readers still checked the source through it; pointer.MARKER_SOURCE
    # carries what they said and why the wording is not what fixes it.
    rows = line.split("\n")[1:] if line else []
    more_pages = []
    note_rows = []
    legend = None
    priced = None   # the pages the price is read from, when it is not image
    for row in rows:
        if row.startswith("Pages: "):
            more_pages = [p.strip() for p in row[len("Pages: "):].split(" , ") if p.strip()]
        elif row.startswith("Tags: "):
            legend = row[len("Tags: "):].strip()
        else:
            note_rows.append(row)
    # Every file this draw put on disk. A discard below must take the whole
    # set: page one alone left later pages and the legend sidecar, which hold
    # the same words, sitting in the vault for a Read that was never
    # redirected. FIXED 3 September 2026, security audit.
    drawn = [str(image)] + more_pages + ([legend] if legend else [])
    sheeted = False
    if more_pages:
        # Every page in the one Read, the way read_gate.py does it at its
        # step 8. The stack ships only when the API would leave it at the
        # size it was drawn; a shrunk image loses the text it carries.
        # ADDED 3 September 2026.
        try:
            import densepack as dp
            all_png = str(Path(image).with_name(Path(image).stem + "-all.png"))
            # Side by side first: a 392 px page grid holds eight pages in one
            # PNG, where the vertical stack held two and the PDF below bills
            # about 1,577 tokens a page flat. 6 September 2026.
            stack = dp.composite_grid([str(image)] + more_pages, all_png)
            if stack is None:
                stack = dp.composite([str(image)] + more_pages, all_png)
        except Exception:  # noqa: BLE001
            stack = None
        if stack is not None and dp.no_downscale(stack[1], stack[2]):
            image = stack[0]
            drawn.append(str(stack[0]))
            more_pages = []
        else:
            # One sheet did not fit under page.edge, so the pages go into as
            # many sheets as it takes, largest first. A 756 px page sits two
            # to a row, so a sheet holds about four pages; a file of seven
            # pages became six loose pages in the note before this, and a
            # reader that skipped the note never saw them. MEASURED
            # 8 September 2026 on the sixteen file bench: 36 pages reached
            # the model as 18 images, every file's first page and two others.
            # FIXED the same day: the note names sheets, not pages.
            try:
                pages_left = [str(image)] + more_pages
                sheets = []
                while pages_left:
                    take = len(pages_left)
                    made = None
                    while take > 1:
                        suffix = "-all.png" if not sheets else "-all%d.png" % (len(sheets) + 1)
                        part = str(Path(image).with_name(Path(image).stem + suffix))
                        made = dp.composite_grid(pages_left[:take], part)
                        if made is not None and dp.no_downscale(made[1], made[2]):
                            break
                        made = None
                        take -= 1
                    if made is None:
                        # a page on its own always fits, the packer drew it to
                        sheets.append(pages_left[0])
                        pages_left = pages_left[1:]
                    else:
                        sheets.append(made[0])
                        drawn.append(str(made[0]))
                        pages_left = pages_left[take:]
                if len(sheets) < 1 + len(more_pages):
                    image = sheets[0]
                    more_pages = sheets[1:]
                    sheeted = True
            except Exception:  # noqa: BLE001
                pass
    if more_pages:
        # The stack was over the cap, so the pages go out as one PDF instead,
        # one page per image. A Read of a PDF returns every page as its own
        # picture in the one tool result, which is the delivery rule this
        # gate holds: no tool result ever asks the model to Read again for
        # more pages. ADDED 4 September 2026, after two sheets of
        # bench/gdcorpus/main.gd at 10 px measured 1176 by 2856 stacked and
        # 2352 by 1428 side by side, both over the 1568 cap.
        # A Read asks for its pages argument on a PDF of more than ten pages,
        # and that argument is the second request this fix exists to remove.
        # The argument is no way out either: a Read carrying pages rasterizes
        # through pdftoppm, and poppler is not on this machine, measured
        # 4 September 2026, where the same PDF read whole without the argument
        # returned both pages. So an eleventh page keeps the note below. The
        # largest file this repo routes here, tools/live_dashboard.py at 3,051
        # lines, draws 9 sheets at 10 px, measured the same day.
        # A PDF page bills about 1,591 tokens flat against 1,244 for the
        # same page as a PNG, 28 per cent over, bench/session-2026-09-07/
        # pdf_tall.py. The two other routes were measured the same night and
        # lost more: a note asking for the later pages cost Opus a turn and
        # Sonnet never read them, and plain text for a file past one PNG
        # took the gd corpus from 45.4 to 27.6 per cent on Fable. The PDF
        # stands until a route measures better.
        # NO PDF, the user's standing call of 8 September 2026: a PDF page
        # bills a flat fee that a PNG page does not. Pages past the one PNG
        # ride as the note below and cost the reader its own Reads.
        bound = None
        if bound is not None:
            # The price is still read off the PNG pages, which is what the
            # PDF carries; a PDF has no width and height of its own.
            priced = [str(image)] + more_pages
            image = bound
            drawn.append(bound)
            more_pages = []
    if more_pages:
        # FIXED 3 September 2026: the reader received page one alone and
        # the price compared one page with the whole text, so a long file
        # was read in part and looked cheaper than it was. A Read returns
        # one file, so the rest ride as a note the reader acts on.
        # The wording says who drew the pages and what this Read returned,
        # and it gives no order. Until 8 September 2026 it read "Read those
        # pages before you answer", an instruction from nobody the reader
        # could name: Sonnet reported it as an attempt to redirect it and
        # wrote no answers on three of twenty runs of the sixteen file bench.
        pages = len(more_pages) + 1
        if True:
            # The note states what this Read returned and what it did not, and
            # names every remaining page. It gives no order, because the older
            # imperative wording read to Sonnet as an attempt to redirect it
            # and cost three of twenty runs their answers. Stating the count
            # is a fact, not an order. FIXED 8 September 2026, after a leg
            # received 18 of the 37 pages the sixteen files hold.
            note_rows.append(
                "DensePack drew this file as %d pages. This Read returned "
                "page 1 of %d, so it holds %d of the file's %d pages. The "
                "other %d are separate images at: %s"
                % (pages, pages, 1, pages, pages - 1, " , ".join(more_pages)))
        elif sheeted:
            # The pages went into sheets, so the note names sheets. A sheet
            # holds every page that fits one PNG under the API's edge, and a
            # seven page file names one more sheet here rather than six loose
            # pages. FIXED 8 September 2026.
            rest = ("the rest of the file is %s" % more_pages[0] if pages == 2
                    else "the rest of the file is in %s" % " , ".join(more_pages))
            note_rows.append("DensePack drew this file as sheets of pages and "
                             "this Read returned the first sheet, so %s." % rest)
        else:
            rest = ("page 2 of the same file is %s" % more_pages[0] if pages == 2
                    else "pages 2 to %d of the same file are %s"
                         % (pages, " , ".join(more_pages)))
            note_rows.append("DensePack drew this file as %d pages and this Read "
                             "returned page 1, so %s." % (pages, rest))

    try:
        import densepack as dp
        from PIL import Image
        patch_tokens = 0
        for page in priced or ([str(image)] + more_pages):
            with Image.open(page) as im:
                width, height = im.size
            patch_tokens += dp.image_cost(width, height)
    except Exception:
        # A page is on disk but its own price could not be read back.
        # main() cannot compare what it cannot price, so this counts as a
        # draw failure and falls through to the same deny-and-instruct
        # message a Pillow-missing or vanished-file failure already uses.
        discard(drawn)
        return None, None, None, None

    tags = "\n".join(note_rows)
    return str(image), patch_tokens, tags, drawn


def discard(drawn):
    """Delete every page and sidecar of a drawing nobody will read.

    The vault keeps what it is given for good: drops/ is skipped by
    common.vault_trim() and by bootstrap.prune_old_files(), so a page left
    here holds the file's own words in the project folder forever.
    """
    from pathlib import Path
    for name in drawn or ():
        try:
            Path(name).unlink(missing_ok=True)
        except OSError:
            continue


def is_scratch_or_temp(path):
    """True under a .claude folder, a sandbox or scratch named folder, or
    the OS temp root: working files and test fixtures, never worth a gate."""
    norm = path.replace("\\", "/")
    parts = [p.lower() for p in norm.split("/") if p]
    if ".claude" in parts:
        return True
    if any("sandbox" in p or "scratch" in p for p in parts):
        return True
    import tempfile
    from pathlib import Path
    try:
        troot = str(Path(tempfile.gettempdir()).resolve()).replace("\\", "/").lower()
    except OSError:
        return False
    return norm.lower().startswith(troot)


def capped(event, model, cap):
    """True when this turn's batch is too wide for this reader to be handed
    pictures, so the Read goes through as text.

    MEASURED 4 September 2026: the batch is not all on disk when the first
    hooks of it run. Claude Code writes an assistant message one content
    block to a line as the reply streams, and it starts read-only tools
    while it is still writing, so the hooks that fire first see a short
    batch and only the later ones see the whole one. Pair 61's shape run
    again with the cap in place drew 5 pictures out of 26 for exactly that
    reason. Two ways of closing it were measured and neither held: a second
    look after the drawing sees the same short batch, because a picture
    already in the drop folder is returned at once, and waiting for the file
    to stop growing fails on the gaps the note in common.py records. So the
    cap holds every read that starts after its batch has landed, which is
    most of a wide one, and up to `cap` pictures still reach the turn.
    """
    if cap is None:
        return False
    batch, turn_id = turn_reads(event)
    if not batch or not over_cap(batch, cap):
        return False
    if claim_once("%s-%s" % (event.get("session_id") or "", turn_id)):
        queue_cap_row(
            event, model,
            "%d reads in one turn, past the %s cap of %d files or %s bytes, "
            "all of them text"
            % (len(batch), model, cap, format(BURST_BYTES, ",")),
            sum(text_bytes(name) for name in batch))
    return True


def text_bytes(path):
    """The bytes a raw Read of `path` would return, 0 when it cannot be
    measured. Only the receipt row uses it, so a missing file costs the row
    a number and costs the read nothing."""
    from pathlib import Path
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def main():
    # NEVER CRASH A CALLER. This runs before every Read in every session.
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0

        if (event.get("tool_name") or "") != "Read":
            return 0

        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        path = tool_input.get("file_path")
        if not isinstance(path, str) or not path:
            return 0
        # THE LINE PULL, common.line_pull(): a few lines by their green
        # number pass before the sibling redirect below, so a pull from a
        # sidecar comes back as text and never as the image again.
        if line_pull(tool_input):
            return 0

        if is_image(path):
            return 0
        if is_plugin_own(path):
            return 0

        # IMAGES ONLY TO MEASURED READERS. Both routes below hand this
        # actor a drawn image: the sibling redirect immediately after, and
        # drop_and_draw() further down. An agent running a model that was
        # never scored on a condensed image, or one that cannot be named
        # at all, must get the raw text instead, which is what returning 0
        # here does. MEASURED 31 August 2026: haiku readers in delegated
        # legs were served images drawn at another model's floor and
        # misread facts from them.
        #
        # This asks about the ACTOR, never the file. The lead keeps
        # FALLBACK_READER and resolved_reader() below, which are separate
        # decisions recorded on those names, so this changes nothing for a
        # lead's own Read.
        if is_subagent(event) and actor_size(event) is None:
            return 0

        image = sibling_image(path)
        if image is not None:
            tool_input["file_path"] = image
            emit({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": tool_input,
                }
            })
            return 0
        if is_drop_folder(path):
            return 0
        if is_scratch_or_temp(path):
            return 0
        # A Read of more than LINE_PULL_MAX lines is a whole read. Until the
        # night of 12 September 2026 any offset or limit passed here, and a
        # Sonnet rebuild leg read a 116 line file as text in two Reads,
        # lines 1 to 20 and 20 to 120, and scored a byte identical rebuild
        # it never read off the page. The pull of a few lines passes at the
        # top of main(), through common.line_pull().

        # THE PICTURE CAP. A reader whose profile carries a measured cap,
        # common.BURST_CAPS and common.BURST_BYTES, draws pictures only for
        # a turn inside that cap and reads a wider turn as text whole. The
        # test is on the whole batch the assistant message asked for, not on
        # this Read alone, so every hook in the batch reads the same answer
        # off the same transcript and no counter file is needed. MEASURED
        # 4 September 2026, bench/sonnet-burst-2026-09-04.md. Pair 61 is the
        # case: 26 Sonnet Reads in one turn saved 23,899 input tokens, 6.13
        # per cent, and cost $0.2163 more, 44.98 per cent, all of it in the
        # 27,449 extra output tokens of the single request that held the
        # pictures. Only sonnet has a cap; Opus saved 62.98 per cent on the
        # same corpus and is left alone.
        model = actor_reader(event) or FALLBACK_READER
        cap = burst_cap(model)
        if capped(event, model, cap):
            return 0

        from pathlib import Path
        try:
            size = Path(path).stat().st_size
        except OSError:
            return 0

        # NO FLOOR HERE. See the module note above the imports: this route
        # pays no delivery fee, so there is no fixed character count below
        # which packing loses, and stub_chars() answered a question priced
        # for the other routes. draw_and_draw() always attempts the draw;
        # the comparison right below it is what decides, on this file's own
        # measured price, the same way subagent_stop.py decides with no
        # floor of its own.
        image, patch_tokens, tags, drawn = drop_and_draw(path, event)
        if image is not None:
            import densepack as dp
            text_tokens = round(size / dp.CHARS_PER_TOKEN)
            # The note ships in the same message as the picture, so it is
            # part of what the picture costs. ADDED 4 September 2026, with
            # the inlined legend: a file whose markers cost more than the
            # file's own text now loses the comparison and is read as text,
            # which is the whole guarantee, per file, on that file's own
            # measurement. No floor and no cap: the count decides.
            note_tokens = round(len(tags or "") / dp.CHARS_PER_TOKEN)
            if patch_tokens is not None and patch_tokens + note_tokens >= text_tokens:
                # Measured cheaper as text. This route's own fee is zero,
                # so the comparison is the image's real patches against the
                # text tokens the raw Read would have cost, nothing added
                # either side. The picture nobody should read is deleted
                # and the Read proceeds exactly as written.
                # Every page and the legend sidecar go with it, not page
                # one alone: they hold the same words and nothing prunes
                # drops/. FIXED 3 September 2026, security audit.
                discard(drawn)
                return 0
            tool_input["file_path"] = image
            # The one thing this route could not carry before 3 September
            # 2026: the exact bytes of every id, hash and long number in the
            # file. draw_drop_file() lifts them out of the picture, and since
            # 4 September 2026 tags carries their text itself, in this same
            # message, so a reader quotes a value instead of reading it off
            # pixels and without opening anything. Empty when the file held
            # nothing to lift and fitted one page.
            answer = {
                "hookEventName": "PreToolUse",
                "updatedInput": tool_input,
            }
            # One line saying what arrived, and nothing telling the reader
            # what to do about it. A brief that says a file is plain text
            # and then receives a picture makes Opus reconcile the two:
            # measured 9 September 2026, every on leg of the three step and
            # five step benches opened one thinking block per image, at
            # 1,021 to 2,811 output tokens against 245 for a leg that
            # opened none, and two legs appended an unasked caveat saying
            # the tool returned a rendered image rather than plain text.
            # The off legs, receiving text, opened none.
            #
            # It states a fact and gives no instruction, which is what
            # separates it from the line tried on 3 September 2026. That
            # one told the reader to answer from the picture and not read
            # the file again, and Sonnet's sixteen-file on arm went from 19
            # turns and 0.35 dollars to 40 turns and 1.13 dollars.
            # The redirect carries the marker rows and the page note, when
            # there are any, and no path to any file.
            # NO PULL NOTE. A one line note on the first drawn Read, saying a
            # doubtful value is one Read away, was tried on the night of
            # 12 September 2026 and taken out the same night. Ten legs a
            # reader on the single file bench: Sonnet pulled the jsonl line
            # on 10 of 10 legs and its 26.6 per cent saving became minus
            # 2.9; Opus pulled the 18054707 line on 10 of 10 legs, two of
            # those pulls drew the API's safeguards refusal, and its saving
            # became minus 8.4; Fable never pulled. A reader cannot tell a
            # value it doubts from one it misread, so the note made every
            # reader check a value it had read right. The rule stays in
            # the rules card, which a lead reads before it spawns or writes.
            if tags:
                answer["additionalContext"] = tags
            emit({"hookSpecificOutput": answer})
            return 0

        sid = str(event.get("session_id") or "")
        if not sid:
            return 0

        marker = marker_path(sid, path)
        if marker.exists():
            return 0
        # Written before the deny goes out: a fault after this line lets
        # the Read through with the marker already down, which only means
        # this one file was never deflected. The reverse order could deny
        # the same file forever.
        try:
            marker.write_text("1", encoding="utf-8")
        except OSError:
            return 0

        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": MESSAGE % (format(size, ","), path),
            }
        })
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
