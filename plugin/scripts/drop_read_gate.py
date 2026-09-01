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
STUB_CHARS_BY_READER note in common.py for the current values).
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

from common import (actor_size, agent_model, disabled, emit, event_reader,
                    is_subagent, read_event, sibling_image, tmp_dir,
                    transcript_key, vault_dir)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf",
                  ".ipynb")

# The size drop_and_draw() falls back to when common.event_reader() cannot
# name the reading agent's model. Sonnet's 12 px, the largest of the three
# measured floors (common.MEASURED_MODELS: fable 8, opus 10, sonnet 12), so
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
    "Copy it into the drop folder named for your own model instead, "
    ".claude/densepack-vault/drop/fable, drop/opus or drop/sonnet, then "
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
    return "densepack-vault" in parts and ("drop" in parts or "drops" in parts)


def drop_and_draw(path, event):
    """Copy `path`'s current bytes into this session's own drop/<model>
    folder and draw them in the SAME hook turn, through
    pointer.draw_drop_file(), the one place this plugin turns a dropped
    file into an image, per FIXES-PENDING.md section 3's instruction to
    wire this to that rather than drawing a second way. Returns (image
    path as a string, its real patch cost) or (None, None) when nothing
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
    common.agent_model() is tried FIRST, the deterministic record
    subagent_start.py writes at spawn from Claude Code's own
    agent-<id>.meta.json, keyed on this event's own transcript_key(). That
    record is written once, at spawn, ahead of this agent's own turn, so
    a later Read here never reads a transcript file at all.
    common.event_reader() is tried SECOND, for a session that started
    before that record existed. FALLBACK_READER is tried LAST, sonnet's
    12 px, the largest measured floor, never the lead's own cached size and
    never a skipped redirect: a gate that cannot decide a size still
    redirects.
    """
    import shutil
    from pathlib import Path
    import pointer

    model = (agent_model(transcript_key(event)) or event_reader(event)
             or FALLBACK_READER)
    src = Path(path)
    try:
        if not src.is_file():
            return None, None
    except OSError:
        return None, None

    drop_dir = vault_dir() / "drop" / model
    try:
        drop_dir.mkdir(parents=True, exist_ok=True)
        dest = drop_dir / src.name
        shutil.copyfile(str(src), str(dest))
    except OSError:
        return None, None

    _line, image = pointer.draw_drop_file(model, str(dest))
    if image is None:
        return None, None

    try:
        import densepack as dp
        from PIL import Image
        with Image.open(image) as im:
            width, height = im.size
        patch_tokens = dp.image_cost(width, height)
    except Exception:
        # The image is on disk but its own price could not be read back.
        # main() cannot compare what it cannot price, so this counts as a
        # draw failure and falls through to the same deny-and-instruct
        # message a Pillow-missing or vanished-file failure already uses.
        Path(image).unlink(missing_ok=True)
        return None, None

    return str(image), patch_tokens


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
        if tool_input.get("offset") or tool_input.get("limit"):
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
        image, patch_tokens = drop_and_draw(path, event)
        if image is not None:
            import densepack as dp
            text_tokens = round(size / dp.CHARS_PER_TOKEN)
            if patch_tokens is not None and patch_tokens >= text_tokens:
                # Measured cheaper as text. This route's own fee is zero,
                # so the comparison is the image's real patches against the
                # text tokens the raw Read would have cost, nothing added
                # either side. The picture nobody should read is deleted
                # and the Read proceeds exactly as written.
                Path(image).unlink(missing_ok=True)
                return 0
            tool_input["file_path"] = image
            emit({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": tool_input,
                }
            })
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
