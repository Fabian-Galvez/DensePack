"""Runs right after the assistant collects a helper's answer. The bill.

HOW THIS FILE FITS, in plain words: subagent_stop.py left pictures on the
queue. This script tells the assistant where those pictures are and to read
them instead of the text, and it prints the receipt: how many characters, how
big the picture, what each cost, what was saved. It also keeps the running
total that session_end.py turns into the final bill.

PostToolUse hook. Hand the lead the images and the receipt.

Four receipt modes, stored in the settings file:

  default  One 6 column table per batch of agents, one row per agent that
           returned images, plus a label row and a BATCH TOTALS row for this
           batch at the bottom of that same table. That row is part of the
           table always, in default and verbose alike; the totals setting
           does not gate it. A second label row and a CONVERSATION TOTALS row,
           the whole conversation's own sums, follow it when the totals
           setting is on; with the setting off that second row is held back
           for the wrap-up only. The running total also prints as its own "Conversation so
           far" line under the table either way. BATCH TOTALS reads BATCH
           TOTALS, not CONVERSATION TOTALS, because the numbers under it are
           this batch's own; CONVERSATION TOTALS carries the whole
           conversation's sums, the same figures the "Conversation so far"
           line already states.
  verbose  The same batch with the arithmetic split into its own columns and a
           Dimensions column, plus a per image table for any agent that
           returned more than one image. BATCH TOTALS prints in every
           response, the same as default. CONVERSATION TOTALS follows it
           when the totals setting is on, and prints by default in this mode
           when the totals setting has never been touched (auto follows verbose). Both
           totals rows spell the model name out in full, Haiku 4.5, Sonnet 5,
           Opus 5, Fable 5, rather than the single letter default uses.
  light    The compact 6 column table with no totals row at all, whatever
           the totals setting says. The "Conversation so far" line still prints
           under it.
  quiet    No table in the response. The hook writes the table to
           .claude/tmp/densepack-receipt-last.md and tells the lead in one
           line to show it only when the user's prompt asked for a report.
           The numbers are still measured and the manifest still gains a row
           for every finished agent; only the printed table is withheld.

The character U+2248, almost equal to, replaces = in the default and light
tables' column names, because a token count taken from characters or pixels
is an estimate.
This hook's output is JSON, so json.dumps writes the character as an ASCII
escape and Claude Code decodes it. Nothing here prints raw UTF-8 to a console.
"""

import os
import sys


def _nothing_queued():
    """The cheap exit, taken before anything else is imported. True when there
    is certainly no queue to drain, which is the case after nearly every tool
    call. os.path is used rather than pathlib because importing pathlib costs
    about 15 ms on its own, and this runs after every
    tool call."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        return False
    return not os.path.exists(os.path.join(
        root, ".claude", "tmp", "densepack-queue.jsonl"))


# The drop scan below imports nothing from common.py, so an empty scan costs
# nothing: common.py is not loaded until a report is actually queued or a
# drop file is actually found, the same reason _nothing_queued() above uses
# os.path rather than pathlib.


# A scan claims a to-draw file by renaming it in place to
# CLAIM_PREFIX<epoch seconds>-<8 hex>-<name>. The file never leaves to-draw,
# where no prune deletes anything. A claim older than CLAIM_STALE_SECONDS was
# left by a scan that was killed, and gets its name back. A file that could
# neither be converted nor set aside keeps its bytes under FAILED_PREFIX<name>,
# which the scan skips.
CLAIM_PREFIX = ".densepack-claim-"
FAILED_PREFIX = ".densepack-failed-"
CLAIM_STALE_SECONDS = 1800


def _find_drop_file():
    """Every file waiting in the to-draw folder or the drop folder, as
    (None, [paths]), or None when both are empty, which is true after nearly
    every tool call. Cheap on purpose: os.walk on two folders, nothing else,
    no watcher and no hook on Read. Every file is offered, so one file held
    open by another program does not block the files after it."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        return None
    # The folder a person copies a file into to have it drawn is "to-draw".
    # The walk also reaches a file left in the "drop" folder or in one of its
    # subfolders. The reader name is resolved by draw_drop_file(), because
    # this scan runs before common is imported.
    bases = [os.path.join(root, ".claude", "densepack-vault", "to-draw"),
             os.path.join(root, ".claude", "densepack-vault", "drop")]
    # A link is never followed and never offered: the draw refuses it, so it
    # would sit here and slow every later tool call.
    # common.is_junction, inline: this scan runs before common is imported.
    # os.path.isjunction is 3.12 and the hooks run on 3.10, where a junction
    # reads as a plain folder unless the reparse tag is read.
    import stat as _stat

    def isjunction(p):
        if hasattr(os.path, "isjunction"):
            return os.path.isjunction(p)
        try:
            return (os.lstat(p).st_reparse_tag
                    == getattr(_stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003))
        except (OSError, ValueError, AttributeError):
            return False
    import time as _time
    found = []
    for base in bases:
        for folder, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if not (os.path.islink(os.path.join(folder, d))
                                               or isjunction(os.path.join(folder, d)))]
            for name in sorted(names):
                path = os.path.join(folder, name)
                if not os.path.isfile(path) or os.path.islink(path):
                    continue
                if name.startswith(FAILED_PREFIX):
                    continue
                if name.startswith(CLAIM_PREFIX):
                    parts = name[len(CLAIM_PREFIX):].split("-", 2)
                    if (len(parts) == 3 and parts[0].isdigit() and parts[2]
                            and not parts[2].startswith((CLAIM_PREFIX, FAILED_PREFIX))
                            and _time.time() - int(parts[0]) > CLAIM_STALE_SECONDS):
                        back = os.path.join(folder, parts[2])
                        try:
                            if not os.path.exists(back):
                                os.replace(path, back)
                                found.append(back)
                        except OSError:
                            pass
                    continue
                found.append(path)
    return (None, found) if found else None


if __name__ == "__main__":
    # Read stdin once, here, before anything decides whether to exit. A
    # TaskStop tool call carries no report to drain, so the queue-and-drop
    # check just below would otherwise see nothing queued and exit before
    # main() ever learns a stop happened, and nothing on disk would record it.
    # _RAW_STDIN is handed to read_event() inside main() instead of letting
    # it read stdin a second time, which would find the pipe already
    # drained. Reconfigured to utf-8 first, the same fix read_event() itself
    # applies before reading: Windows pipes hook stdin as cp1252 otherwise,
    # which turns every UTF-8 quote into mojibake with no error raised.
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    _RAW_STDIN = sys.stdin.read()
    _DROP_HIT = _find_drop_file()
    # A cheap substring check, not a json.loads: this runs before json is
    # even imported below, the same reason _nothing_queued() uses os.path
    # instead of pathlib. A false positive costs one ordinary run through
    # main(), the same cost every batch with something queued already
    # pays; it must never skip a real TaskStop call, which is the one
    # failure that matters here.
    _TASK_STOP = '"TaskStop"' in _RAW_STDIN
    if _DROP_HIT is None and _nothing_queued() and not _TASK_STOP:
        raise SystemExit(0)
else:
    _DROP_HIT = None
    _RAW_STDIN = None

import json  # noqa: E402  imported below the cheap exit, not above it
import re  # noqa: E402
import time  # noqa: E402
try:
    import densepack as _dp  # noqa: E402
except ImportError:
    # Pillow is missing. Nothing can be drawn or priced, and a hook that
    # raised here would fail on every tool call; bootstrap.py already tells
    # the user Pillow is missing.
    raise SystemExit(0)

# The divisor as it prints inside a receipt's "Characters / N = text tokens"
# column. Built from the constant, never typed as a literal: the receipt has
# to name the same number the receipt's own arithmetic used.
DIV = "%.2f" % _dp.CHARS_PER_TOKEN

from common import (append_lifecycle, code_size, disabled, drain_queue, emit,  # noqa: E402
                    read_event, read_leads,
                    read_totals, receipts_mode, status_shown,
                    tmp_dir, MEASURED_MODELS, vault_dir,
                    resolved_reader, UNKNOWN_READER,
                    totals_shown, write_totals, report_pointer, stub_pointer,
                    STALE_AFTER, DEAD_AFTER, jsonl_rows)

# The one non-ASCII character in the output, written as an escape so this
# source file stays plain ASCII.
APPROX = "\u2248"
PATCH = 28
RECEIPT_FILE = "densepack-receipt-last.md"

# The one row that introduces the inlined legend. It says where the rows came
# from and nothing else. It names no file, because a model told a value sits
# in a file opens that file. It gives no order, because an order not to
# verify, arriving beside a tool result, is the shape of a prompt injection.
# It is one line, because its characters are charged against the picture's
# saving in drop_read_gate.main().
MARKER_HEADING = ("DensePack copied the rows below out of the file before it "
                  "drew the picture. Each row is the exact text behind one "
                  "[#N] tag:")

# The label every marker row carries about its own text. A claim read once in
# a heading loses to a reader's own habit of verifying numbers, so the claim
# sits in the row, beside the value. It states the provenance only: a label
# that warned against the picture reads as an order to trust the row.
MARKER_SOURCE = "copied from the file"


def marker_rows(rows):
    """The sidecar's rows as the message delivers them: every "[#1] = value"
    row says in the row itself that the text is the file's own bytes.

    The value is never touched, so the row still holds the sidecar's exact
    characters. A row with no " = " in it, the escalated-tag header
    legend_sidecar() writes for a {#n} or <#n> report, passes through
    unchanged. Splitting on the FIRST " = " is what keeps a value that
    contains " = " whole, because a tag never contains one.
    """
    out = []
    for row in rows.split("\n"):
        tag, sep, value = row.partition(" = ")
        out.append("%s %s%s%s" % (tag, MARKER_SOURCE, sep, value)
                   if sep else row)
    return "\n".join(out)


def _drop_only_payload(drop_line):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": drop_line,
        }
    }


def image_stem(path):
    """The name part every image of `path` starts with: the file's folder
    inside the project, each separator a dash, then the file's name with its
    extension.

    README.md at the project root gives README.md, and src/README.md gives
    src-README.md. The extension stays, so same.py and same.md in one folder
    never share an image name or a sidecar; without it, a turn that read both
    could hand the first Read the second file's image. A file outside the
    project keeps only its own folder's name. The folder part keeps its last
    80 characters and the name its first 48, so a deep path still fits a
    Windows path.
    """
    from pathlib import Path
    from common import project_dir

    def safe(part):
        # A hyphen joins the folders to the name, so a hyphen inside a part
        # becomes _. a-b/c.py and a/b-c.py then get two names, not one.
        return re.sub(r"[^A-Za-z0-9_.]", "_", part)

    src = Path(path)
    try:
        parent = src.resolve().parent
    except OSError:
        parent = src.parent
    try:
        folders = parent.relative_to(Path(project_dir()).resolve()).parts
    except (ValueError, OSError):
        # A file outside the project keeps only its own folder's name, so an
        # image name never carries the user name or the machine's folder layout.
        folders = parent.parts[-1:]
    head = "-".join(safe(p) for p in folders if p)[-80:].lstrip("-")
    # The cut keeps the extension, so two long names that differ only there
    # still get two image names.
    stem = safe(src.stem)[:40] + safe(src.suffix)[:8]
    return "%s-%s" % (head, stem) if head else stem


def claimed_stem(path, base=None):
    """image_stem(path), made unique to this one source file.

    image_stem() is readable, not unique: a-b/c.py and a_b/c.py, two files
    outside the project with the same folder name, and two long names that
    match in their first 40 characters all give one stem, and the second draw
    would overwrite the first file's images. A claim file beside the images,
    created in one step with O_EXCL, holds the source's real path. The first
    file keeps the plain stem; another file with the same stem gets ~2, ~3.
    No hash reaches the name.
    """
    from pathlib import Path
    from common import project_dir, through_link, vault_dir
    # base is image_stem(path) on the Read route, and the file's own name on
    # the to-draw route.
    if base is None:
        base = image_stem(path)
    images = vault_dir() / "images"
    try:
        # A committed link at images/ would carry the claim, which holds the
        # source's full path, to a folder outside the project.
        if through_link(project_dir(), images):
            return base
        images.mkdir(parents=True, exist_ok=True)
        if through_link(project_dir(), images):
            return base
        me = os.path.normcase(os.path.realpath(str(path)))
    except OSError:
        return base
    # 50 names, not more: a project can commit claim files for every name,
    # and reading thousands of them made each Read take half a minute. Past
    # 50 the name carries 8 hex characters of the path, which no committed
    # claim can take in advance.
    for n in range(1, 51):
        stem = base if n == 1 else "%s~%d" % (base, n)
        claim = images / ("%s-claim-DensePack.txt" % stem)
        try:
            fd = os.open(str(claim), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            # Only a regular file is read, and only as far as the path's own
            # length: a committed claim can be huge, or a FIFO that blocks.
            try:
                if Path(claim).is_file():
                    with open(claim, encoding="utf-8", errors="replace") as fh:
                        if fh.read(len(me) + 1) == me:
                            return stem
            except OSError:
                pass
            continue
        except OSError:
            return base
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(me)
        return stem
    import hashlib
    return "%s~%s" % (base, hashlib.sha256(me.encode("utf-8")).hexdigest()[:8])


def deliver_names(image, more, drawn, stem, keep=()):
    """Name what a reader gets <stem>-image-N-of-M-DensePack.<suffix>, N
    from 1, where stem comes from image_stem() on the Read route.

    image is the first file, more the rest, drawn every file the draw put on
    disk. A page that went into a sheet is removed, because the sheet holds
    it; a file named in keep stays, because the price is read off it. The
    suffix stays, so a PDF keeps .pdf. Returns (image, more, drawn) with the
    new names. A reader finds an image by its name, so the name says the
    file and the count and nothing else.
    """
    delivered = [str(image)] + [str(p) for p in more]
    folder = os.path.dirname(delivered[0])
    total = len(delivered)
    named = []
    for n, old in enumerate(delivered, 1):
        new = os.path.join(folder, "%s-image-%d-of-%d-DensePack%s"
                           % (stem, n, total, os.path.splitext(old)[1].lower()))
        if new != old:
            _dp.replace_retry(old, new)
        named.append(new)
    keep = set(str(k) for k in keep)
    for old in drawn:
        old = str(old)
        if (old not in delivered and old not in keep and old.endswith(".png")
                and os.path.exists(old)):
            try:
                os.remove(old)
            except OSError:
                pass
    rest = [str(d) for d in drawn if not str(d).endswith(".png")]
    kept = [k for k in keep if k not in named and k not in rest]
    return named[0], named[1:], named + rest + kept


def later_images_note(src_name, folder, names, at=1):
    """The note beside image `at` of a file that became several images. It
    names the plugin, the file, the folder once, and every image."""
    total = len(names)
    # The project names its own files, and this sentence reaches the reader as
    # the plugin's words, so nothing a shell or a line break acts on goes in.
    from common import no_metacharacters
    # The file name only. The folder and the image names go through as they
    # are, because the reader opens them: a project folder called
    # "My Project (x86)" cleans to a path that does not exist, and an image
    # name built from a bracketed file name cleans to a file that is not
    # there. grep_gate.py follows the same rule for the same reason.
    src_name = no_metacharacters(src_name)
    rows = ["DensePack plugin converted %s into %d png images in %s. This is "
            "image %d of %d, %s." % (src_name, total, folder, at, total, names[at - 1])]
    for n, name in enumerate(names, 1):
        if n != at:
            rows.append("Image %d of %d is %s." % (n, total, name))
    return " ".join(rows)


def draw_drop_file(model, src_path, actor=None, name_stem=None, name=None):
    """Draw the file found in the to-draw folder, at the reader's pixel size,
    into images/, then delete the copy. Returns (line, image_path): one
    line naming the image, and the image's own Path, or (None, None) when
    nothing was drawn: the model has no measured size, Pillow is missing, or
    the draw itself failed. A failed draw deletes the copy.

    When ident_legend holds identifiers, line carries the legend's OWN ROWS,
    "[#1] copied from the file = <exact text>", under one heading row. This
    function reads those rows back out of the sidecar file it has just
    written, so the value in the message is the record's own characters and
    no second format exists to be updated separately. marker_rows() adds the
    label and nothing else. Both draw paths below leave ident_legend empty,
    so no rows are written.

    The "Tags: <full path>" row is still built, because discard() has to
    delete the sidecar it names, but both callers strip it before the line
    reaches a model: naming that file reads as an instruction to open it.

    The one place this plugin turns a dropped file into an image.
    pointer.py's own scan below reaches it through _draw_drop_file, the
    status line alone, the only thing that scan ever needed.
    drop_read_gate.py calls this directly, so an ordinary file with no
    sibling image is still redirected. Calling this in the SAME hook turn
    means the Read is rewritten straight to the image, no agent action and
    no retry turn, the same shape the sibling-image redirect already uses.
    """
    import hashlib
    from pathlib import Path
    if model is None:
        model = resolved_reader() or UNKNOWN_READER
    px = MEASURED_MODELS.get(model)
    if px is None:
        return None, None
    # A test override: DENSEPACK_PX_OVERRIDE set in the environment draws
    # every drop at that size, so another size can be measured for cost and
    # accuracy. Unset, which is every normal session, nothing changes. Never
    # a settings key, never a default.
    override = os.environ.get("DENSEPACK_PX_OVERRIDE", "").strip()
    if override.isdigit() and 6 <= int(override) <= 16:
        px = int(override)
    src = Path(src_path)
    # The name the file had when a person put it in to-draw. The scan renames
    # a file it claims, and that claim name must never reach an image.
    shown = Path(name) if name else src
    # This function deletes src. A path through a link or a junction may point
    # outside the project, so it is never touched.
    from common import project_dir, through_link
    if through_link(project_dir(), src):
        return None, None
    # No age rule: a copied or moved file keeps an old time, and was deleted
    # unseen. A file whose draw fails is left for the caller: the to-draw scan
    # moves it to not-converted/, and the Read gate deletes its own staging
    # copy. Nothing here deletes a file it could not draw.
    try:
        mtime = src.stat().st_mtime
    except OSError:
        return None, None
    try:
        text = src.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    # The renderer refuses a source holding its own marks, U+E000 to U+E003.
    # A null byte, more than 250,000 characters or more than 6,000 lines is
    # binary or too big, the same limits a Read keeps as text.
    if (any(mark in text for mark in "\ue000\ue001\ue002\ue003")
            or "\x00" in text or len(text) > 250000 or text.count("\n") > 6000):
        return None, None
    digest = hashlib.sha256(
        ("%s|%f" % (src, mtime)).encode("utf-8")).hexdigest()[:12]
    images = vault_dir() / "images"
    # A committed link at images/ would carry every image outside the project.
    if through_link(project_dir(), images):
        return None, None
    images.mkdir(parents=True, exist_ok=True)
    if through_link(project_dir(), images):
        return None, None
    # The work name carries the digest so two draws of two files with one
    # stem never write onto each other while they draw. deliver_names()
    # renames what a reader gets to <stem>-image-N-of-M-DensePack.png, a name
    # a reader can read, with no reader name and no hash in it.
    # The extension stays in the name, so same.py and same.md dropped into
    # to-draw never overwrite each other's images.
    safe_stem = (re.sub(r"[^A-Za-z0-9_.-]", "_", shown.stem)[:40]
                 + re.sub(r"[^A-Za-z0-9_.-]", "_", shown.suffix)[:8])
    stem = images / ("%s.%s" % (safe_stem, digest))
    code_image = False
    ident_legend = []
    try:
        import densepack as dp
        # reader=model is a backstop: px above already comes from
        # MEASURED_MODELS.get(model), so a caller that computes px some other
        # way still cannot hand this model an image under its own scored
        # floor.
        # A code source is drawn by codepack, the banded code renderer: one
        # light background block per source line, so a reader stops
        # misreading identifiers where the stream wraps.
        # Python is classified by tokenize and every other file by codepack's
        # plain classifier. Every file gets the raw text: flatten() removed
        # every indent and blank line, so a .tsx, .php, Dockerfile or any
        # suffix outside codepack.CODE_SUFFIXES lost its indentation and its
        # green line numbers stopped matching the file.
        import codepack
        suffix = shown.suffix.lower()
        # legend=None: the numbers stay in the picture. Marker references
        # cost a reader far more output to resolve than the look-alike
        # inks cost, so ident_legend stays empty here and no sidecar or
        # marker row is written. Every file takes the code image for every
        # reader, at code_size().
        written, _target, _lh = codepack.pack_code(
            text, code_size(px, model), str(stem), python=(suffix == ".py"),
            legend=None, reader=model, title=shown.name)
        code_image = True
    except Exception:
        written = None
    if not written:
        return None, None
    # The pages take their reader facing names here, so the scan's own line
    # and the Pages row below name what a reader will find. The gate names
    # them once more after it composes sheets.
    # The source line each image opens on. codepack counts drawn lines from
    # 0, and a drawn line is a source line that is not blank: build_flow()
    # skips an empty code line, and dp.flatten() drops a blank prose line.
    kept = [n for n, row in enumerate(text.split("\n"), 1)
            if (row != "" if code_image else row.strip())]
    opens = [codepack.PAGE_FIRST_LINE.get(str(p)) for p, _w, _h in written]
    first_lines = ([kept[k] for k in opens]
                   if all(isinstance(k, int) and k < len(kept) for k in opens) else [])
    # name_stem is the Read route's image_stem() of the file really read.
    # Two files named x.py in two folders, read in one turn, then never
    # rename their pages onto one shared name.
    first, rest, _all = deliver_names(written[0][0], [p for p, _w, _h in written[1:]],
                                      [p for p, _w, _h in written], name_stem or safe_stem)
    written = [(first,) + tuple(written[0][1:])] + [
        (r,) + tuple(w[1:]) for r, w in zip(rest, written[1:])]
    image = Path(first)
    try:
        src.unlink()
    except OSError:
        pass
    # Who drew it and what it is, not the file operations behind it. A line
    # that narrates a copy and a delete in a folder the reader never named
    # reads to a reader as an attempt to redirect it.
    # The image name is cleaned; the source name is whatever the project
    # committed, so it never reaches the reader as words.
    line = "DensePack converted a file from the to-draw folder into %s." % image
    # Every page, not page one alone. A Read returns one file, so without this
    # row a reader of a long file would see only its first page, and the
    # price would compare one page against the whole text. The Pages row
    # names the rest; drop_read_gate.py hands it to the reader as the note
    # and prices every page.
    if len(written) > 1:
        line = line + "\nPages: " + " , ".join(str(p) for p, _w, _h in written[1:])
    # The first source line of every page, so the gate can hand a Read that
    # starts at line N the image that holds line N.
    if len(first_lines) > 1:
        line = line + "\nLines: " + " , ".join(str(n) for n in first_lines)

    # The sidecar lands beside the image, and the Tags row names it by its
    # full path, because drop_read_gate.discard() deletes the file that row
    # names when the price says the picture loses. Both callers strip the row
    # before a model sees the line.
    #
    # The marker rows follow, in the message itself. They are read back off
    # the sidecar rather than rebuilt from ident_legend, so the escalated-tag
    # header legend_sidecar() writes for a {#n} or <#n> report reaches the
    # reader too, and one format serves the file and the message.
    # marker_rows() then labels each row with MARKER_SOURCE; the value's own
    # characters are untouched.
    try:
        legend_file = dp.legend_sidecar(ident_legend, stem)
    except OSError:
        legend_file = None
    if legend_file:
        line = line + "\nTags: " + str(images / legend_file)
        try:
            rows = (images / legend_file).read_text(encoding="utf-8").strip()
        except OSError:
            rows = ""
        if rows:
            line = line + "\n" + MARKER_HEADING + "\n" + marker_rows(rows)

    # Every pack kind logs a manifest row so its saving counts toward the live
    # dashboard's Without DensePack column. image_tokens here is the visual
    # cost only, patch count times dp.image_cost, because a drop is
    # redirected straight to the image with no separate pointer read to add
    # in, unlike a bash, brief or report pack.
    try:
        from subagent_stop import manifest_write
        here = (tmp_dir() / "densepack-lead-session").read_text(
            encoding="utf-8").strip()
        manifest_write({
            "packed": True,
            "spawned_by": here,
            "chars": len(text),
            # A code image says so here, in the same field every
            # other pack kind writes.
            "kind": "code" if code_image else "drop",
            # Who this picture was drawn for, and the model that set its
            # size. spawned_by is the LEAD's session on every route, so
            # without these a drop or code image drawn for a subagent and one
            # drawn for the lead would be the same row in the records and no
            # measurement could group by agent. px and model are the ones
            # this draw actually used, taken above, never re-derived.
            "font_px": px,
            "drawn_for": str(actor or ""),
            "drawn_model": model,
            "text_tokens": round(len(text) / dp.CHARS_PER_TOKEN),
            "image_tokens": sum(dp.image_cost(w, h) for _p, w, h in written),
            "ended": time.time(),
        })
    except Exception:
        pass
    return line, image


def _name_stem(name):
    """The image stem of a to-draw file: its own name, cleaned, with the
    extension, the same rule draw_drop_file() uses for safe_stem."""
    from pathlib import Path
    own = Path(name)
    return (re.sub(r"[^A-Za-z0-9_.-]", "_", own.stem)[:40]
            + re.sub(r"[^A-Za-z0-9_.-]", "_", own.suffix)[:8])


def _claim_drop_file(src_path):
    """Rename one to-draw file in place to CLAIM_PREFIX<epoch>-<8 hex>-<name>
    and return the new path; None when another scan took it first, another
    program holds it open, or a link sits on the way. The file stays inside
    to-draw, where no prune deletes anything."""
    from pathlib import Path
    from common import project_dir, through_link
    src = Path(src_path)
    try:
        if through_link(project_dir(), src):
            return None
        target = src.with_name("%s%d-%s-%s" % (CLAIM_PREFIX, int(time.time()),
                                              os.urandom(4).hex(), src.name))
        os.replace(str(src), str(target))
        return target
    except OSError:
        return None


def _set_aside(src_path, name):
    """Move a claimed to-draw file that could not be converted into
    not-converted/ under its own name, so it is never tried again on every
    tool call and never deleted. It is the person's own copy. Returns the one
    line the reader receives, or None when it cannot be moved safely."""
    from pathlib import Path
    from common import project_dir, through_link
    src = Path(src_path)
    if not src.is_file():
        return None
    aside = vault_dir() / "not-converted"
    try:
        if through_link(project_dir(), src) or through_link(project_dir(), aside):
            return None
        aside.mkdir(parents=True, exist_ok=True)
        if through_link(project_dir(), aside):
            return None
        own = Path(name)
        target = aside / own.name
        n = 2
        while target.exists():
            target = aside / ("%s~%d%s" % (own.stem, n, own.suffix))
            n += 1
        os.replace(str(src), str(target))
    except OSError:
        return None
    # The file's name is not in the line: the project chose that name.
    return ("DensePack could not convert a file from the to-draw folder. It is in "
            ".claude/densepack-vault/not-converted/.")


def _draw_drop_file(model, src_paths):
    """pointer.py's own scan only ever needed the status line; see
    draw_drop_file() above for the (line, image_path) pair
    drop_read_gate.py uses instead.

    The Tags row is dropped here. This scan has no file to delete, so the
    sidecar's path serves it nothing, and a path in the text sends a reader
    to open that file. The marker rows below the heading stay: they are
    what the reader needs.

    One file is converted per tool call: the first of src_paths this scan
    can claim. Parallel tool calls start several scans at once, and a scan
    whose claim fails moves on, so no two scans work on one file."""
    from pathlib import Path
    paths = [src_paths] if isinstance(src_paths, str) else list(src_paths or [])
    for src_path in paths:
        claimed = _claim_drop_file(src_path)
        if claimed is None:
            continue
        name = Path(src_path).name
        # to-draw/sub1/x.py and to-draw/sub2/x.py both have the name x.py; the
        # claim gives the second x.py~2, so neither overwrites the other image.
        stem = claimed_stem(src_path, base=_name_stem(name))
        line, _image = draw_drop_file(model, str(claimed), name=name, name_stem=stem)
        if line:
            # Neither row is for a reader: Tags names the legend file, and
            # Lines is the first source line of each image, which the gate's
            # own sidecar carries.
            return "\n".join(row for row in line.split("\n")
                             if not row.startswith(("Tags: ", "Lines: ")))
        aside = _set_aside(str(claimed), name)
        if aside:
            return aside
        # Neither converted nor set aside: the file keeps its bytes in
        # to-draw under a name the scan skips, so it is never lost and never
        # tried again on every tool call.
        try:
            os.replace(str(claimed), str(claimed.with_name(FAILED_PREFIX + name)))
        except OSError:
            pass
        return None
    return None


def _rule_already_sent(name):
    """True when this session has already been told the rule called `name`.

    A rule the lead has read once does not need resending. Resending it does,
    because every character sent sits in the prefix of every later turn.
    In one measured lead transcript, 9 report blocks
    carried 13,271 characters and 8 outbound brief blocks carried 8,877, and
    the rule prose is most of both.

    The marker is a file, because every hook run is a fresh process. It is
    written on the first call, so the first batch gets the whole rule and
    every batch after it gets one line.
    """
    marker = tmp_dir() / ("densepack-rule-%s" % name)
    if marker.exists():
        return True
    # Moved onto the name, so a link planted at it takes no write.
    from common import write_text_atomic
    write_text_atomic(marker, "1")
    return False

# Claude Code caps additionalContext, systemMessage and plain stdout at 10,000
# characters and writes anything longer to a file, showing a preview and the
# path instead, per the hooks reference. The receipt
# stays under that with room to spare, so it is never turned into a preview.
MESSAGE_CHARS = 9000


def group(number):
    return format(int(number), ",")


def model_cell(item):
    """The model, trimmed to the part a person reads. A full id such as
    claude-opus-5 is shown as Opus 5. An unknown model is a dash rather than a
    guess, because a wrong name on a receipt is worse than no name."""
    raw = str(item.get("model") or "").strip()
    if not raw:
        return "-"
    known = [("fable", "Fable"), ("opus", "Opus"), ("sonnet", "Sonnet"),
             ("haiku", "Haiku"), ("mythos", "Mythos")]
    low = raw.lower()
    for key, pretty in known:
        if key not in low:
            continue
        rest = low.split(key, 1)[1].strip("-_ ")
        # claude-haiku-4-5-20251001 -> Haiku 4.5. The version is the numeric
        # parts joined with a dot, and an 8 digit part is a date rather than a
        # version, so it is dropped.
        parts = [p for p in rest.split("-")
                 if p.isdigit() and len(p) < 8]
        return (pretty + " " + ".".join(parts)).strip() if parts else pretty
    return raw


def is_brief(item):
    """A brief is the outbound half of the pipeline: an instruction packed for
    a subagent before it started, not a report packed after one finished. It
    belongs on the receipt, because the user paid for it and saved on it, and
    it must never reach the lead as an image to read: the lead WROTE that
    brief, and re-reading it would spend back the tokens the pack just saved.
    """
    return item.get("kind") == "brief"


def label_with_model(item):
    """The Packed reports cell for the default receipt: the agent, then the
    model that wrote the report, in one cell. The default receipt is five
    columns and the model does not get one of its own."""
    who = label(item)
    model = model_cell(item)
    return who if model == "-" else "%s, %s" % (who, model)


def label(item):
    """The agent type, with the asterisk that marks a report the lead already
    read as text. The lead replaces this with the task it assigned."""
    if is_brief(item):
        return "brief to %s" % item["agent_type"]
    if not item.get("images"):
        return item["agent_type"]
    return item["agent_type"] + ("" if item["mode"] == "stub" else "*")


REASON_SAID = {
    "under the saving threshold": "Under the saving threshold, text is cheaper",
    "no prose report": "No prose report, structured output only",
    "mostly code": "Mostly code, code is never condensed",
    "pack failed": "Pack failed, text delivered",
    "Pillow missing": "Pillow missing, text delivered",
}


def reason_said(item):
    return REASON_SAID.get(item.get("reason", ""), item.get("reason", "text"))


# The two reasons that mean the plugin could not do its job. The other reasons
# in REASON_SAID are decisions the plugin made on purpose: text measured
# cheaper, there was no prose, the report was code. Only these two are worth
# telling the user about on their own.
BROKEN = ("pack failed", "Pillow missing")


def text_row_default(item):
    """An agent whose reply stayed words. It has a raw text cost and no
    DensePack cost, so the reason sits where the picture's price would."""
    chars = ("%s %s %s" % (group(item["chars"]), APPROX, group(item["text_tokens"]))
             if item.get("chars") else "-")
    return r"| %s | %s | %s | - |" % (
        model_cell(item), chars, reason_said(item))


def text_row_verbose(item):
    chars = ("%s / " + DIV + " = %s") % (group(item["chars"]), group(item["text_tokens"])) \
        if item.get("chars") else "-"
    return (r"| %s | %s | No images | - | %s | - | %s | %s | - |"
            % (label(item), model_cell(item), chars, group(item["text_tokens"]) if item.get("chars") else "-",
               reason_said(item)))


def dims_of(item):
    """The per image sizes subagent_stop.py recorded, as (width, height)."""
    out = []
    for text in item.get("dims", []):
        parts = str(text).lower().split("x")
        if len(parts) != 2:
            continue
        try:
            out.append((int(parts[0]), int(parts[1])))
        except ValueError:
            continue
    return out


def dim_cell(width, height):
    return "%s x %s" % (group(width), group(height))


def patch_cell(width, height):
    across = -(-width // PATCH)
    down = -(-height // PATCH)
    return "%s x %s = %s" % (group(across), group(down), group(across * down))


def packed_count(totals):
    """How many packed entries the stored totals cover, reports and briefs
    together. An older totals file has no "packed" key,
    so the reports count stands in and an existing session keeps working."""
    if "packed" in totals:
        return totals["packed"]
    return totals.get("reports", 0) + totals.get("briefs", 0)


def saved_cell(text_tokens, image_tokens):
    saved = text_tokens - image_tokens
    pct = round(saved / text_tokens * 100) if text_tokens else 0
    return r"%d%% \| %s" % (pct, group(saved))


def sums(entries):
    out = {}
    for key in ("chars", "pixels", "text_tokens", "image_tokens"):
        out[key] = sum(e.get(key, 0) for e in entries)
    out["images"] = sum(len(e.get("images", [])) for e in entries)
    out["patch_tokens"] = sum(e.get("patch_tokens", 0) for e in entries)
    return out


# The Model cell on every receipt row: the model family and a number, counted
# per model within the batch, so two Sonnet agents read as Sonnet-01 and
# Sonnet-02 rather than as two rows called Sonnet.
def numbered_model(item, seen):
    family = model_cell(item)
    if family == "-":
        return "-"
    short = family.split()[0]
    seen[short] = seen.get(short, 0) + 1
    return "%s-%02d" % (short, seen[short])


def default_header(first="Model"):
    """The four column names and the divider under them.

    Raw text cost is what the words would have cost. DensePack cost is what
    the picture cost, delivery included. The Images count is on the verbose
    receipt only, because a reader who wants the saving does not need the
    file count to read it.
    """
    return [r"| %s | Raw text cost | DensePack cost | Saved %% \| tokens |"
            % first,
            "| --- | --- | --- | --- |"]


def default_table(entries):
    lines = default_header()
    seen = {}
    for item in entries:
        if not item.get("images"):
            lines.append(text_row_default(item))
            continue
        lines.append(r"| %s | %s %s %s | %s %s %s | %s |" % (
            numbered_model(item, seen),
            group(item["chars"]), APPROX, group(item["text_tokens"]),
            group(item["pixels"]), APPROX, group(item["image_tokens"]),
            saved_cell(item["text_tokens"], item["image_tokens"])))
    return lines


# The letters that name each model family. Order does not matter here, only
# membership.
MODEL_LETTERS = (("Haiku", "H"), ("Sonnet", "S"), ("Opus", "O"), ("Fable", "F"))

# The order the totals rows' Model cell prints in, Fable then Opus then
# Sonnet then Haiku, always all four, even for a model that ran zero agents
# in this batch. A fixed order and all four every time means the row never
# moves and never has to be read to find out which model is missing. One
# line, never a <br> break, which the receipt's reader does not render as one.
MODEL_TOTALS_ORDER = (("Fable", "F"), ("Opus", "O"), ("Sonnet", "S"), ("Haiku", "H"))

# The full names printed on the verbose totals row's Model cell instead of the
# letters, same order, same all-four-always rule.
MODEL_FULL_NAMES = {"Haiku": "Haiku 4.5", "Sonnet": "Sonnet 5",
                    "Opus": "Opus 5", "Fable": "Fable 5"}


def _model_family(item):
    """Which of the four measured model names this row belongs to, Haiku,
    Sonnet, Opus or Fable, or None when the model does not match any of
    them, the same way model_cell shows a dash rather than a guess for an
    unknown model."""
    pretty = model_cell(item)
    for name, _letter in MODEL_LETTERS:
        if pretty.startswith(name):
            return name
    return None


def model_counts(entries):
    """How many of the given entries ran on each of the four measured
    models, keyed by the plain family name, Fable, Opus, Sonnet, Haiku."""
    counts = {name: 0 for name, _letter in MODEL_TOTALS_ORDER}
    for item in entries:
        family = _model_family(item)
        if family is not None:
            counts[family] += 1
    return counts


def format_counts(counts, spelled_out):
    """counts, whichever source built it, as one plain line, Fable then Opus
    then Sonnet then Haiku, comma separated, all four printed every time.

    Not a <br> tag: a br tag does not render as a line break wherever this
    user reads the receipt, so four lines joined by <br> read as one run of
    joined letters. One line
    with commas reads correctly everywhere. spelled_out=False prints the
    count with the single letter, 0F; True prints the full model name, 0
    Fable 5, for the verbose table.
    """
    if spelled_out:
        return ", ".join("%d %s" % (counts.get(name, 0), MODEL_FULL_NAMES[name])
                         for name, _letter in MODEL_TOTALS_ORDER)
    return ", ".join("%d%s" % (counts.get(name, 0), letter)
                     for name, letter in MODEL_TOTALS_ORDER)


def model_breakdown(entries):
    """This batch's per model counts, as one plain line, letters only."""
    return format_counts(model_counts(entries), spelled_out=False)


def model_breakdown_spawns(spawns):
    """The same per model line for the status table's totals row.

    A spawn row carries the model under a different key from a receipt entry,
    so model_counts cannot read it. The counting is the same and the output
    is the same four letters in the same fixed order.
    """
    counts = {name: 0 for name, _letter in MODEL_TOTALS_ORDER}
    for row in spawns:
        family = _model_family(row)
        if family in counts:
            counts[family] += 1
    return format_counts(counts, spelled_out=False)


def model_breakdown_full(entries):
    """This batch's per model counts, as one plain line, names spelled out,
    for the verbose table's totals rows."""
    return format_counts(model_counts(entries), spelled_out=True)


def totals_rows_default(packed):
    """The two rows added to the bottom of the default table: a label row,
    then the sums, each column totalled the same way that column is already
    formatted in an agent row. Scoped to the packed rows, the ones with real
    numbers in the Characters, Pixels and Saved columns.

    Labeled BATCH TOTALS, not CONVERSATION TOTALS: the sums below are drawn
    from `packed`, this batch's own rows, never the whole conversation. The
    whole conversation's own sums are a separate row, CONVERSATION TOTALS,
    added by conversation_totals_rows below when the totals setting calls for it, and
    giving this row that other row's name would make the two look
    interchangeable when they answer different questions. The totals setting
    does not gate this row; it prints whenever the table itself does."""
    run = sums(packed)
    return [
        "| **BATCH TOTALS** | | | |",
        r"| %s | %s %s %s | %s %s %s | %s |" % (
            model_breakdown(packed),
            group(run["chars"]), APPROX, group(run["text_tokens"]),
            group(run["pixels"]), APPROX, group(run["image_tokens"]),
            saved_cell(run["text_tokens"], run["image_tokens"])),
    ]


def totals_rows_verbose(packed):
    """The same two rows, sized to the verbose table's nine columns.
    Dimensions holds a dash, the same mark the per agent rows already use
    for a value a totals row does not have. The Model cell spells out each
    model's full name rather than the letter default uses."""
    run = sums(packed)
    return [
        "| **BATCH TOTALS** | | | | | | | | |",
        (r"| %d | %s | %d | - | %s / " + DIV + r" = %s | %s | %s | %s + %s fee = %s | %s |") % (
            len(packed), model_breakdown_full(packed), run["images"],
            group(run["chars"]), group(run["text_tokens"]),
            group(run["patch_tokens"]), group(run["text_tokens"]),
            group(run["patch_tokens"]),
            group(run["image_tokens"] - run["patch_tokens"]),
            group(run["image_tokens"]),
            saved_cell(run["text_tokens"], run["image_tokens"])),
    ]


def run_totals_rows(packed, mode):
    """The BATCH TOTALS block for this batch, packed rows only, or nothing
    when none of this batch's rows packed. Built here, once, so the same two
    rows go into the table wherever the receipt is rendered: filed to disk,
    shown to the lead, or shown to the user.

    The totals setting never gates it: BATCH TOTALS is part of the default and
    verbose tables themselves, not an add-on the setting turns on. Only the
    receipt mode decides whether it appears. light never gets a totals
    block, whatever the totals setting says: that mode is the compact
    table, and its whole point is to stay that shape."""
    if not packed or mode == "light":
        return []
    return (totals_rows_verbose(packed) if mode == "verbose"
            else totals_rows_default(packed))


def format_stored_counts(stored, spelled_out):
    """The same per model line format_counts prints, built from the counts
    kept in the totals file rather than from a batch of entries. `stored` is
    totals.get("models"), a plain dict of family name to count; an older
    totals file carries no such key, and a
    missing or partial dict reads as zero for whichever model it lacks
    rather than raising, so an old totals file still prints a CONVERSATION
    TOTALS row, just with counts that start from zero on the update that
    adds the field."""
    stored = stored or {}
    counts = {name: int(stored.get(name, 0)) for name, _letter in MODEL_TOTALS_ORDER}
    return format_counts(counts, spelled_out)


def totals_rows_conversation_default(totals):
    """The CONVERSATION TOTALS label row and numbers row, sized to the
    default table's six columns, drawn from the same stored totals the
    "Conversation so far" line reads, so the two can never disagree.

    The Packed reports and Images columns read totals["reports"] and
    totals["images"] rather than a fresh sum over packed entries, on
    purpose: those are the exact fields the "Conversation so far" line
    already prints, and a second count built a different way could drift
    from it even when both are technically correct answers to slightly
    different questions."""
    text_tokens = totals.get("text_tokens", 0)
    image_tokens = totals.get("image_tokens", 0)
    return [
        "CONVERSATION TOTALS:",
        "",
        *default_header("Models"),
        r"| %s | %s | %s | %s %s %s | %s %s %s | %s |" % (
            format_stored_counts(totals.get("models"), spelled_out=False),
            group(packed_count(totals)), group(totals.get("images", 0)),
            group(totals.get("chars", 0)), APPROX, group(text_tokens),
            group(totals.get("pixels", 0)), APPROX, group(image_tokens),
            saved_cell(text_tokens, image_tokens)),
    ]


def totals_rows_conversation_verbose(totals):
    """The same CONVERSATION TOTALS rows, sized to the verbose table's nine
    columns, model names spelled out in full. Needs totals["patch_tokens"],
    the running sum of every batch's patch cost, to split the Image tokens
    column into patches plus the handover fee the way the per agent and
    BATCH TOTALS rows do; an older totals file without that field reads
    as zero patches, so the whole image cost prints as fee until the field
    has accumulated something of its own."""
    text_tokens = totals.get("text_tokens", 0)
    image_tokens = totals.get("image_tokens", 0)
    patch_tokens = totals.get("patch_tokens", 0)
    return [
        "CONVERSATION TOTALS:",
        "",
        *verbose_header("Models"),
        (r"| %s | %s | %s | - | %s / " + DIV + r" = %s | %s | %s | %s + %s fee = %s | %s |") % (
            group(packed_count(totals)),
            format_stored_counts(totals.get("models"), spelled_out=True),
            group(totals.get("images", 0)),
            group(totals.get("chars", 0)), group(text_tokens),
            group(patch_tokens), group(text_tokens), group(patch_tokens),
            group(image_tokens - patch_tokens), group(image_tokens),
            saved_cell(text_tokens, image_tokens)),
    ]


def conversation_totals_rows(totals, mode, packed):
    """The CONVERSATION TOTALS block, gated the way the totals setting governs it:
    only when this batch already earned a BATCH TOTALS block (packed rows
    exist and the mode is not light), and the caller has already checked
    totals_shown(). Kept as its own function, mirroring run_totals_rows,
    so the two blocks are built the same way wherever the receipt is
    rendered."""
    if not packed or mode == "light":
        return []
    return (totals_rows_conversation_verbose(totals) if mode == "verbose"
            else totals_rows_conversation_default(totals))


def verbose_header(second="Model"):
    """The nine column names and the divider under them. The second column
    is Model on the batch table and Models on the conversation table."""
    return [(r"| Packed reports | %s | Images | Dimensions | Characters / " + DIV + r" = text tokens |"
             r" Patches, ceil(w/28) x ceil(h/28) | Text tokens |"
             r" Image tokens, patches plus the handover cost | Saved %% \| tokens |")
            % second,
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]


def verbose_table(entries):
    lines = verbose_header()
    for item in entries:
        if not item.get("images"):
            lines.append(text_row_verbose(item))
            continue
        dims = dims_of(item)
        patches = item.get("patch_tokens", item["image_tokens"])
        if len(dims) == 1:
            dim = dim_cell(*dims[0])
            patch = patch_cell(*dims[0])
        elif dims:
            dim = "%d images, table below" % len(dims)
            patch = group(patches)
        else:
            dim = "not recorded"
            patch = group(patches)
        fee = item["image_tokens"] - patches
        lines.append((r"| %s | %s | %d | %s | %s / " + DIV + r" = %s | %s | %s | %s + %s fee = %s | %s |") % (
            label(item), model_cell(item), len(item["images"]), dim,
            group(item["chars"]), group(item["text_tokens"]), patch,
            group(item["text_tokens"]), group(patches), group(fee),
            group(item["image_tokens"]),
            saved_cell(item["text_tokens"], item["image_tokens"])))
    return lines


def image_detail_lines(entries):
    """The per image dimension tables, one for each agent that returned more
    than one image. Kept apart from verbose_table so the totals block can sit
    between the agent rows and this detail."""
    lines = []
    for item in entries:
        dims = dims_of(item)
        if len(dims) < 2:
            continue
        lines.append("")
        # No agent id here, on purpose: an internal identifier means nothing
        # to a reader, so the row's own agent type names it instead.
        lines.append("The %d images of the %s report above. The characters "
                     "and the saving belong to the whole report, in the row "
                     "above:" % (len(dims), item["agent_type"]))
        lines.append("| Image | Dimensions | Patches, ceil(w/28) x ceil(h/28) |")
        lines.append("| --- | --- | --- |")
        total = 0
        for n, (width, height) in enumerate(dims, 1):
            total += -(-width // PATCH) * -(-height // PATCH)
            lines.append("| %d | %s | %s |" % (n, dim_cell(width, height),
                                               patch_cell(width, height)))
        lines.append("| **Total, %d images** |  | %s |" % (len(dims), group(total)))
    return lines


def delegation_entries():
    """Every spawn brief_pack.py has logged, across every session, in the
    order the file holds them. Never drained: this table is pulled on
    demand, not consumed once like the queue."""
    from common import sealed_rows
    return sealed_rows(tmp_dir() / "densepack-delegation.jsonl")


def manifest_entries():
    """Every row subagent_stop.py has written, in file order. Read fresh
    every call rather than cached, because the delegation table can be
    pulled at any point in a session and a stale copy would show a finished
    agent as still running."""
    from common import sealed_rows
    return sealed_rows(tmp_dir() / "densepack-manifest.jsonl")


def _finished_by_type(session):
    """This session's finished agents, one row per agent id, grouped by
    agent type, oldest start first. subagent_stop.py can write a provisional
    row for an agent that ignored the delivery rule and was blocked once
    until it complied, followed by a final row once it did; the final row
    wins when both exist. The provisional row stands alone when a harness
    ignores the block and no final row ever comes, so that agent still
    counts as one that ran."""
    by_id = {}
    for row in manifest_entries():
        if str(row.get("spawned_by") or "") != str(session or ""):
            continue
        agent_id = row.get("agent_id") or ""
        current = by_id.get(agent_id)
        if current is None or (current.get("provisional")
                               and not row.get("provisional")):
            by_id[agent_id] = row
    grouped = {}
    for row in sorted(by_id.values(), key=lambda r: r.get("started") or 0):
        grouped.setdefault(row.get("agent_type") or "agent", []).append(row)
    return grouped


# The smallest sample a median is trusted from. Below this, one or two
# outlier runs could swing the number, so the cell says how thin the sample
# is instead of printing a number that reads as settled.
MIN_MEDIAN_RUNS = 3


def _median(values):
    values = sorted(values)
    n = len(values)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def _all_finished_rows():
    """Every manifest row across every session, one per agent id, the final
    row preferred over a provisional one when both exist for that id. Used
    only for the median duration baseline: that estimate needs the widest
    sample the manifest holds, not one session's handful of finished agents,
    the way _finished_by_type is scoped."""
    by_id = {}
    for row in manifest_entries():
        agent_id = row.get("agent_id") or ""
        current = by_id.get(agent_id)
        if current is None or (current.get("provisional")
                               and not row.get("provisional")):
            by_id[agent_id] = row
    return list(by_id.values())


def duration_medians():
    """Median finished duration in seconds, and the sample size it came
    from, for each of the four measured models. {"Sonnet": (432.0, 68), ...}.
    A model with no finished runs in the manifest maps to (None, 0)."""
    by_family = {}
    for row in _all_finished_rows():
        duration = row.get("duration_s")
        if duration is None:
            continue
        family = _model_family(row)
        if family is None:
            continue
        by_family.setdefault(family, []).append(float(duration))
    return {name: (_median(by_family.get(name, [])), len(by_family.get(name, [])))
            for name, _letter in MODEL_LETTERS}


def estimate_phrase(family, medians):
    """The words a running agent's row shows in place of a real duration: a
    median with its sample size when there is one, otherwise a plain
    admission that there is not enough measured to say. Never a number built
    from fewer than MIN_MEDIAN_RUNS finished runs, because one or two samples
    are not a median, they are a guess wearing a median's decimal point."""
    if family is None:
        return "no estimate, model not measured"
    median, count = medians.get(family, (None, 0))
    if median is None or count < MIN_MEDIAN_RUNS:
        return "no estimate, %d runs measured" % count
    return "median %.1fm over %d runs" % (median / 60.0, count)


def _mmss(seconds):
    """A duration as minutes and seconds, or seconds alone under a minute."""
    seconds = float(seconds)
    if seconds < 60:
        return "%.1fs" % seconds
    minutes, rest = divmod(seconds, 60)
    return "%dm %02ds" % (int(minutes), int(round(rest)))


def state_cell(duration, spawned_at=None, now=None, started=True):
    """What the agent is doing right now, in one or two words.

    Never a bare number. One column that prints "done in 19m 04s" beside
    "running, 6m so far" makes a reader decide which numbers were spent and
    which were left. This cell says the state and the
    Time left cell says the number, so neither can be read as the other.
    """
    # Done, or the minutes it has been running. The State cell says Done or a
    # number of minutes spent, and the Finished cell says the number of
    # minutes it took or has left.
    if duration is not None:
        return "Done"
    if spawned_at is None:
        return "Running"
    quiet = (now if now is not None else time.time()) - float(spawned_at)
    if quiet >= DEAD_AFTER and not started:
        # No start marker and no finished run. SubagentStart never fired, so
        # the agent never began: another PreToolUse hook denied the call after
        # brief_pack.py had already written this row.
        return "Spawn denied, never ran"
    if quiet >= DEAD_AFTER:
        return "No stop record %dm" % int(quiet // 60)
    if quiet >= STALE_AFTER:
        return "Silent %dm" % int(quiet // 60)
    return "%dm" % int(quiet // 60)


def left_cell(duration, spawned_at=None, now=None, family=None,
              medians=None, started=True):
    """How much longer, or how long it took.

    A finished agent shows what it really took, worded "took" so it cannot be
    read as a countdown. A running agent shows the median for its model less
    the time already spent, which is the only estimate available and is worth
    printing only while it is still positive. Past the median the honest
    answer is that the estimate is spent, not a larger number invented to
    replace it.
    """
    # Minutes only. The column is named Finished, so a word such as "took"
    # would say the same thing twice. A run under a minute reads
    # as under 1m rather than as 0m, which would look like it never ran.
    if duration is not None:
        minutes = int(float(duration) // 60)
        return "%dm" % minutes if minutes else "under 1m"
    if spawned_at is None:
        return "unknown"
    quiet = (now if now is not None else time.time()) - float(spawned_at)
    if quiet >= DEAD_AFTER and not started:
        return "none"
    if quiet >= DEAD_AFTER:
        return "may have died, check it"
    if quiet >= STALE_AFTER:
        return "no report, check it"
    if family is None:
        return "unknown, model not measured"
    median, count = (medians or {}).get(family, (None, 0))
    if median is None or count < MIN_MEDIAN_RUNS:
        return "unknown, %d runs measured" % count
    remaining = median - quiet
    if remaining <= 0:
        return "past its %.0fm median" % (median / 60.0)
    if remaining < 60:
        return "about %ds left" % int(remaining)
    return "about %dm left" % int(round(remaining / 60.0))


def seconds_left(duration, spawned_at=None, now=None, family=None, medians=None):
    """The seconds this agent still has to run, or None when it is finished or
    cannot be estimated. The table's total uses the LARGEST of these, never
    the sum, because agents run at the same time."""
    if duration is not None or spawned_at is None:
        return None
    quiet = (now if now is not None else time.time()) - float(spawned_at)
    if quiet >= STALE_AFTER or family is None:
        return None
    median, count = (medians or {}).get(family, (None, 0))
    if median is None or count < MIN_MEDIAN_RUNS:
        return None
    remaining = median - quiet
    return remaining if remaining > 0 else 0.0


# How long after PreToolUse the matching SubagentStart is allowed to fire.
# Measured over a batch of eight agents spawned in one
# message: every gap fell between 1.8 and 2.4 seconds, and the order never
# differed. 60 seconds is 25 times the widest gap seen and still far tighter
# than a batch's own spread, which was 74 seconds. A spawn whose agent starts
# later than this had no agent behind it, and the row stays unmatched rather
# than taking the next agent's number.
START_WINDOW = 60.0


def _session_agents(session):
    """Every agent this session spawned, oldest start first, whether it
    finished or not.

    Each entry is (started, agent_id, manifest row or None). A row of None
    means the agent has a start marker still on disk, so it never stopped.

    This list exists so delegation_table() can pair spawn rows to agents by
    ORDER OF START rather than by nearest time. Nearest time fails the
    moment a batch spawns several agents inside the window: eight agents
    spawned across 74 seconds against a 90 second window print every
    duration against the wrong job. The order of
    SubagentStart matches the order of PreToolUse exactly, so position is the
    identity the spawn row itself does not carry.
    """
    seen = {}
    for row in manifest_entries():
        if str(row.get("spawned_by") or "") != str(session or ""):
            continue
        agent_id = row.get("agent_id") or ""
        current = seen.get(agent_id)
        if current is None or (current.get("provisional")
                               and not row.get("provisional")):
            seen[agent_id] = row
    out = [(float(row.get("started") or 0), agent_id, row)
           for agent_id, row in seen.items() if row.get("started")]
    for started, agent_id in _unstopped_markers(session):
        if agent_id not in seen:
            out.append((float(started), agent_id, None))
    out.sort(key=lambda item: item[0])
    return out


def plural(count, word):
    """One agent, two agents. A count and its word are written together here
    so no table has to read "1 agents"."""
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


# A marker's time and its spawn row's time come from the same tool call, so
# they land within seconds of each other. The window is wide enough to absorb
# a slow start and far narrower than the gap between two batches.
MARKER_WINDOW = 120.0


def _unstopped_markers(session):
    """Every start marker still on disk for this session, as (at, agent_id),
    oldest first.

    A marker exists between SubagentStart and SubagentStop, so one still on
    disk means that agent never stopped. Read failures are skipped rather
    than raised: this table must never be the reason a receipt cannot print.
    """
    out = []
    try:
        entries = list(tmp_dir().iterdir())
    except OSError:
        return out
    for path in entries:
        name = path.name
        if not name.startswith("densepack-start-"):
            continue
        agent_id = name[len("densepack-start-"):]
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (ValueError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("spawned_by") or "") != str(session or ""):
            continue
        at = data.get("at")
        if at is None:
            try:
                at = path.stat().st_mtime
            except OSError:
                continue
        out.append((float(at), agent_id))
    out.sort()
    return out


def job_role(agent_type):
    """The Job cell: the short role the agent was given.

    A custom agent type IS the role, so it prints as it stands. The default
    type, general-purpose, names no role, so the cell holds a dash and the
    lead replaces it with the role it assigned. The lead is the only thing
    that knows: this hook sees the type and the task, never the role.
    """
    if agent_type in ("general-purpose", "-", "agent", ""):
        return "-"
    return agent_type


def job_cell(job, agent_type):
    """The Job column's content: the task description alone for the default
    agent type, general-purpose, or the task followed by the type in
    brackets for anything else, because a custom agent type is worth seeing
    and general-purpose repeated down the whole table tells a reader
    nothing. Never the agent id: an internal identifier like
    afd9d9266a2192de6 means nothing to a reader, and the job description is
    what actually says what happened."""
    if agent_type in ("general-purpose", "-"):
        return job
    return "%s (%s)" % (job, agent_type)


def delegation_table(session):
    """The Model, Job, State, Time left table: every agent this session has
    spawned, oldest first, ending in a total row. Job is the description the
    lead passed at spawn time, with the agent type appended in brackets only
    when it is not general-purpose, the default every built-in spawn uses.
    Runtime is matched against the manifest by agent type, in spawn order,
    because the row brief_pack.py writes carries no agent id: the subagent
    tool has not assigned one yet when PreToolUse fires, so an id cannot be
    recorded at spawn time. No agent id ever prints here, or anywhere else
    this table reaches, whether or not one was available to match with.

    A finished row's Runtime is its real duration_s. A still-running row's
    Runtime is the median duration_s of every OTHER finished agent measured
    anywhere in the manifest on that same model, with the sample size stated
    beside it, never a guess dressed as a number."""
    spawns = [row for row in delegation_entries()
             if str(row.get("session") or "") == str(session or "")]
    spawns.sort(key=lambda r: r.get("time") or 0)
    agents = _session_agents(session)
    medians = duration_medians()
    # Counts a number per model family, so two Sonnet agents read Sonnet-01
    # and Sonnet-02 rather than as two rows both called Sonnet.
    numbering = {}
    # Five columns. Job is the short
    # role the lead gave the agent. Report is what the lead asked it to do.
    # State says Done or how long it has been running. Finished says how long
    # it took, or how long is left.
    lines = ["| Model | Job | Report | State | Finished |",
             "| --- | --- | --- | --- | --- |"]
    running = 0
    no_record = 0
    longest_left = None
    unknown_left = False
    total_seconds = 0.0
    for index, row in enumerate(spawns):
        agent_type = row.get("subagent_type") or "-"
        # The index-th spawn belongs to the index-th agent to start. Accepted
        # only when that agent started within START_WINDOW of this spawn, so
        # a spawn row with no agent behind it leaves the row unmatched rather
        # than taking a later agent's duration.
        started = None
        manifest_row = None
        if index < len(agents):
            at, _agent_id, found = agents[index]
            spawn_time = row.get("time")
            if spawn_time is None or -5.0 <= at - float(spawn_time) <= START_WINDOW:
                started = at
                manifest_row = found
        # A manifest row of None means the agent has a start marker still on
        # disk, so it never stopped: running or dead, and it must not be given
        # somebody else's finished duration.
        duration = manifest_row.get("duration_s") if manifest_row else None
        if duration is not None:
            total_seconds += float(duration)
        job = row.get("description") or "-"
        family = _model_family(row)
        spawned = row.get("time")
        if duration is None:
            quiet = time.time() - float(spawned) if spawned else 0.0
            if quiet >= DEAD_AFTER:
                no_record += 1
            else:
                running += 1
            left = seconds_left(duration, spawned, family=family, medians=medians)
            if left is None:
                unknown_left = True
            elif longest_left is None or left > longest_left:
                longest_left = left
        lines.append("| %s | %s | %s | %s | %s |" % (
            numbered_model(row, numbering), job_role(agent_type), job,
            state_cell(duration, spawned, started=started is not None),
            left_cell(duration, spawned, family=family, medians=medians,
                      started=started is not None)))
    # The total row has four cells too, so the count of spawns and the agent
    # minutes spent, this run's cost figure, sit in the State cell, and the
    # LARGEST remaining time, never the sum, sits in Time left: agents run
    # at the same time, so the run ends when its slowest one does.
    # An agent with no stop record is not running and must not be counted as
    # though the run is waiting on it. It is reported separately so the count
    # of live agents stays true. A dead agent is not something the run is
    # waiting on, so it is kept out of the running count above; its own row
    # already says it has no stop record.
    if running == 0:
        time_left = ("none, run complete" if not no_record
                     else "check the ones with no record")
    elif unknown_left and longest_left is None:
        time_left = "%s still running, unknown" % plural(running, "agent")
    else:
        base = longest_left if longest_left is not None else 0.0
        # Every running agent is already past the median for its model, so
        # there is no measured number left to quote. Elapsed time is never
        # reported as time remaining, and "about 0s to all done" beside an
        # agent 15 minutes past its median would say exactly that.
        if base <= 0:
            left_phrase = "past the median for its model, finish unknown"
        elif base < 60:
            left_phrase = "about %ds to all done" % int(base)
        else:
            left_phrase = "about %dm to all done" % int(round(base / 60.0))
        if unknown_left:
            left_phrase += ", one not measured"
        time_left = "%s still running, %s" % (plural(running, "agent"), left_phrase)
    # Two rows, matching the receipt's BATCH TOTALS shape: a label row, then
    # the counts. The Job cell holds the agent count, State holds the agent
    # minutes spent, Finished holds the longest remaining time and never a
    # sum, because agents run at the same time.
    lines.append("| **STATUS TOTALS** | | | | |")
    lines.append("| %s | %s | | %s agent minutes | %s |" % (
        model_breakdown_spawns(spawns), len(spawns),
        "%.1f" % (total_seconds / 60.0), time_left))
    return lines


# The words used when nothing in the delegation log is close enough to
# trust. Never the agent id: an id means nothing to a reader, and a plain
# admission that the task was not logged is more honest than a guess.
NO_LOGGED_JOB = "an agent whose task was not logged"


def job_for_marker(session, marker_at, window=MARKER_WINDOW):
    """The task description behind a still-unstopped agent's start marker,
    found by matching the marker's own timestamp against the delegation
    log, the same way delegation_table pairs a spawn to its marker.

    Used so a stall or a no-stop-record message names the
    work the agent was given, not the internal agent id: a string like
    afd9d9266a2192de6 means nothing to a reader. Falls back to NO_LOGGED_JOB,
    never the id, when nothing in the log is close enough to trust."""
    if marker_at is None:
        return NO_LOGGED_JOB
    best, best_gap = None, None
    for row in delegation_entries():
        if str(row.get("session") or "") != str(session or ""):
            continue
        spawn_time = row.get("time")
        if spawn_time is None:
            continue
        gap = abs(float(spawn_time) - float(marker_at))
        if best_gap is None or gap < best_gap:
            best, best_gap = row, gap
    if best is None or best_gap > window:
        return NO_LOGGED_JOB
    return best.get("description") or NO_LOGGED_JOB


def totals_table(totals, mode):
    """The whole conversation's totals, as their own small table. Used only by
    session_end.py, for the wrap-up summary a next session opens with, where
    there is no per-agent table for the numbers to sit inside. pointer.py's
    own per-batch receipt does not call this: its batch totals live inside
    the same six (or nine) column table, built by run_totals_rows."""
    text_tokens = totals.get("text_tokens", 0)
    image_tokens = totals.get("image_tokens", 0)
    row = r"| %s %s %s | %s %s %s | %s |" % (
        group(totals.get("chars", 0)), APPROX, group(text_tokens),
        group(totals.get("pixels", 0)), APPROX, group(image_tokens),
        saved_cell(text_tokens, image_tokens))
    head = (r"| Total characters %s tokens | Total pixels %s tokens | Saved (%% and tokens) |"
            % (APPROX, APPROX))
    rule = "| --- | --- | --- |"
    if mode == "verbose":
        head = (r"| Images | Total characters %s tokens | Total pixels %s tokens | Saved (%% and tokens) |"
                % (APPROX, APPROX))
        rule = "| --- | --- | --- | --- |"
        row = "| %s | %s" % (group(totals.get("images", 0)), row[2:])
    return [head, rule, row]


def record_stop_by_lead(event):
    """Append the lifecycle record's "stopped-by-lead" row for the agent
    named on a TaskStop tool call, or do nothing when the call names none.

    task_id is the field the TaskStop tool itself takes; shell_id is its
    deprecated alias, read the same way. Either one is the same agent id
    the start marker and subagent_stop.py already key their own rows on.
    The lane tag comes from that agent's own start marker when it is still
    on disk, which it is here: a lead-ordered stop never reaches
    subagent_stop.py, so nothing has deleted the marker yet.
    """
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    agent_id = tool_input.get("task_id") or tool_input.get("shell_id")
    if not agent_id:
        return
    lane = ""
    marker_path = tmp_dir() / ("densepack-start-%s" % agent_id)
    try:
        record = json.loads(marker_path.read_text(encoding="utf-8"))
        if isinstance(record, dict):
            lane = record.get("lane") or ""
    except (OSError, ValueError):
        pass
    append_lifecycle(agent_id, "stopped-by-lead", lane)


def main():
    # The event is read before the switch is checked, because the off
    # switch is per session and the id that names
    # the session is on the event. _RAW_STDIN is the same text the cheap
    # exit above already read; read_event() parses it instead of reading
    # stdin a second time.
    event = read_event(_RAW_STDIN)
    if disabled(event.get("session_id")):
        return 0

    # The one thing a TaskStop tool call needs from this hook: a lifecycle
    # row saying the lead, not silence, ended this agent. Runs before the
    # queue and lead-ownership checks below, because a TaskStop call
    # carries no report to drain and must not depend on either being true.
    # See common.py's LIFECYCLE_FILE note for the fault this closes.
    if event.get("tool_name") == "TaskStop":
        record_stop_by_lead(event)

    # The drop scan runs for every session, lead or subagent, before the
    # lead-only queue logic below: a subagent can copy a file into its own
    # drop folder too. drop_line is emitted at whichever return point this
    # call reaches first.
    drop_line = _draw_drop_file(*_DROP_HIT) if _DROP_HIT else None

    # Only a lead session drains the queue. This hook fires in every session,
    # subagents included, and a subagent draining the queue steals the lead's
    # pointers and receipts. bootstrap.py records every session that started as
    # a lead. With no lead on record every session drains, so the plugin
    # still works on a harness that omits the field. Once any lead is on
    # record this fails closed: an event carrying NO session id must not slip
    # through, or a subagent is handed the lead's receipt and delegation
    # table for agents it never ran. bootstrap.py runs at SessionStart and a
    # subagent is not a session, so a missing id while leads exist means
    # this is not a lead.
    sid = event.get("session_id")
    leads = read_leads()
    if leads and (not sid or str(sid) not in leads):
        if drop_line:
            emit(_drop_only_payload(drop_line))
        return 0

    entries = drain_queue()
    if not entries:
        if drop_line:
            emit(_drop_only_payload(drop_line))
        return 0

    # A subagent can spawn subagents of its own. Such a report is delivered to
    # that subagent, never to the lead, but the queue is one shared file, so
    # without this filter the lead would drain the row, charge itself a saving
    # for text it never read, and hold a row it cannot label.
    #
    # spawned_by is the session that spawned the agent, recorded in its start
    # marker. A row with no spawned_by comes from a harness that omits
    # session_id, so it is treated as the lead's.
    nested = [item for item in entries
              if item.get("spawned_by") and str(item["spawned_by"]) != str(sid or "")]
    entries = [item for item in entries if item not in nested]
    if not entries and not nested:
        if drop_line:
            emit(_drop_only_payload(drop_line))
        return 0

    # Briefs are on the same queue as reports so the user sees one receipt for
    # the whole pipeline, but everything below that hands the lead an image to
    # READ has to skip them. The lead wrote each brief; pointing it back at
    # its own words as a picture would spend the saving straight back.
    brief_entries = [item for item in entries if is_brief(item)]
    report_entries = [item for item in entries if not is_brief(item)]

    packed_entries = [item for item in entries if item.get("images")]
    packed_reports = [item for item in report_entries if item.get("images")]
    # run covers the whole batch, briefs included, because that is what the
    # receipt table adds up. report_run covers reports only, because that is
    # what the pointer lines above the table are about.
    run = sums(packed_entries)
    report_run = sums(packed_reports)
    totals = read_totals()
    totals["reports"] = totals.get("reports", 0) + len(packed_reports)
    totals["briefs"] = totals.get("briefs", 0) + len(brief_entries)
    # Every packed entry, reports and briefs alike. The CONVERSATION TOTALS
    # count column reads this, because the Images, Characters, Pixels and both
    # token columns beside it are summed over the same population. Counting
    # reports there while summing briefs beside it printed 1 next to 2.
    totals["packed"] = totals.get("packed", 0) + len(packed_entries)
    totals["text_reports"] = (totals.get("text_reports", 0)
                              + len(report_entries) - len(packed_reports))
    for key in ("images", "chars", "pixels", "text_tokens", "image_tokens",
                "patch_tokens"):
        totals[key] = totals.get(key, 0) + run[key]
    # Per model counts for the CONVERSATION TOTALS row.
    # An older totals file has no "models" key;
    # setdefault starts it at zero for every model and this batch's own
    # counts are the first added to it, so an old totals file keeps working
    # and simply starts counting models from the update forward.
    stored_models = totals.setdefault("models", {})
    for name, count in model_counts(packed_entries).items():
        stored_models[name] = stored_models.get(name, 0) + count
    write_totals(totals)

    mode = receipts_mode()

    # Name the folder and the naming pattern once, list agent ids, and stop
    # repeating full paths on every delivery.
    all_stub = all(item["mode"] == "stub" for item in packed_reports)
    if all_stub:
        # Built in common.py for the same reason as the line below it:
        # subagent_stop.py charges the receipt for this exact text, and a
        # second copy here would drift away from the one being charged.
        head = stub_pointer(report_run["images"], tmp_dir())
    else:
        # One sentence, built in common.py, because subagent_stop.py charges
        # the receipt for exactly this text. Two copies would drift and the
        # receipt would price a line the lead never received.
        head = report_pointer(report_run["images"], tmp_dir())
    if not packed_reports:
        head = ("DensePack: %d agent report(s) came back as text (%s), no image "
                "was made and nothing was billed to DensePack."
                % (len(report_entries),
                   "; ".join(sorted({reason_said(i) for i in report_entries}))))
    if not report_entries:
        head = ("DensePack: no agent report arrived in this batch, only "
                "outbound briefs. The receipt below is the brief saving.")
    if not entries and nested:
        head = ("DensePack: nothing in this batch was yours. Every report in "
                "it came from an agent one of your subagents spawned, so "
                "there is no receipt and nothing was charged to you.")
    lines = [head]
    if drop_line:
        lines.append("")
        lines.append(drop_line)
    # A report from an agent one of your subagents spawned is named but not
    # charged. The lead never received that text, so counting its saving would
    # overstate the total, and the lead cannot label a task it never assigned.
    # Naming it still matters: it tells the lead that findings exist which
    # reached a subagent and will be lost unless that subagent folds them into
    # its own report.
    if nested:
        # Numbered, never by agent id: an internal identifier means nothing
        # to a reader, and the count here is only to tell two same-type
        # agents apart, not to look either one up.
        lines.append(
            "  %d report(s) came from agents your subagents spawned. Their "
            "text was delivered to those subagents, not to you, so they are "
            "not counted below. Tell each subagent to fold its own subagents' "
            "findings into its report, or those findings are lost: %s"
            % (len(nested),
               ", ".join("%s #%d" % (i.get("agent_type", "agent"), n)
                         for n, i in enumerate(nested, 1))))
    if brief_entries:
        lines.append(
            "  %d brief(s) packed at each reader's own size."
            % len(brief_entries))
    for item in report_entries:
        if not item.get("images"):
            lines.append("  %s: text, %s" % (
                item["agent_type"], reason_said(item)))
            continue
        # No "captured by the net" note. The stop hook files EVERY report
        # itself from the agent's final message, so the note would print on
        # every stub row, and its "no summary heading" claim is usually false:
        # the filed message opens with whatever the agent's message opened
        # with, most often the five line summary the delivery rule asks for.
        # The manifest still records captured per agent for the audit trail.
        lines.append("  %s: %d image(s)" % (
            item["agent_type"], len(item["images"])))
        if item.get("code"):
            lines.append("  Code blocks came out of that image: each #=N=# "
                         "marker in it stands where block N belongs. The "
                         "python blocks are drawn banded, in order, in: "
                         + (", ".join(item.get("code_images") or [])
                            or "no page")
                         + ". Every block at full fidelity here: "
                         + item["code"])
        # Every identifier the packer took out of the image lives in a
        # sidecar file, not in this text: the lead sees [#3] in the image and
        # this one line naming the file that resolves it, and opens that file
        # only when it needs the value, the same sed -n rule shared.txt
        # teaches for the exact text file. The lift is off by default.
        if item.get("legend_file"):
            # Full path, never the bare name.
            lines.append("  Tags: " + str(tmp_dir() / item["legend_file"]))

    # The table is built in every mode, because quiet files it rather than
    # printing it, and that file is what the lead shows when the user asks.
    with_images = packed_reports
    table = []
    detail = []
    if entries:
        table = (verbose_table(entries) if mode == "verbose"
                 else default_table(entries))
        if mode == "verbose":
            detail = image_detail_lines(entries)
    # BATCH TOTALS is part of the table itself, not an add-on the totals
    # setting gates: it goes straight onto the end of `table` here, so every
    # place that prints `table` below prints it too, unconditionally, whenever
    # this batch packed at least one report or brief. Empty when nothing
    # packed, so there is nothing yet to total.
    table = table + run_totals_rows(packed_entries, mode)
    # CONVERSATION TOTALS is the row the totals setting governs: the whole
    # conversation's own sums, the same figures the "Conversation so far"
    # line below states. totals_shown() gates this row only, never BATCH
    # TOTALS above.
    conversation_block = (conversation_totals_rows(totals, mode, packed_entries)
                          if totals_shown() else [])
    net_seen = any(item["mode"] != "stub" for item in with_images)
    footnote = ("* returned its full text as well as the image, so this row's "
                "saving applies to re-reads rather than delivery.")

    filed = list(table) + detail
    if net_seen:
        filed += ["", footnote]
    filed += ([""] + conversation_block) if conversation_block else []
    filed += ["", "Conversation so far: %s reports, %s images, %s tokens saved."
              % (totals["reports"], totals["images"],
                 group(totals["text_tokens"] - totals["image_tokens"]))]
    receipt_file = tmp_dir() / RECEIPT_FILE
    receipt_file.write_text("\n".join(filed) + "\n", encoding="utf-8")

    if mode == "quiet":
        # This one line stays a judgement call for the lead, and that is the
        # right answer here. Quiet is the user's own order to print no
        # receipt, so a hook field that printed one would be the defect.
        # Nothing is lost when the lead ignores this line, because the table
        # is on disk and the user only ever wanted it after asking for it,
        # which is a question answered like any other question in the
        # conversation.
        lines.append("")
        lines.append("DensePack receipts are quiet. This batch's table is in %s . "
                     "Show that table only if the user asked for a report in "
                     "their prompt." % receipt_file)
    elif table:
        lines.append("")
        # The long form goes out ONCE per session and every batch after it
        # gets one line. In one measured lead transcript, resending it with
        # every batch put 9 report blocks at 13,271 characters and 8 outbound
        # brief blocks at 8,877, and every one of those characters then sat in
        # the prefix of every later turn. The lead has already been told what
        # to do with the table, so repeating it buys nothing.
        if _rule_already_sent("receipt"):
            lines.append("Print this table with the rows labeled, the same way "
                         "as the earlier one:")
        else:
            lines.append("The hook has already shown the user this table, so the user has "
                         "the numbers whatever you do. Show it again with the rows labeled, "
                         "which is the one thing this hook cannot do. The numbers are measured by "
                         "the hook from the source text and the PNG on disk, both kept next "
                         "to the image for checking. Keep the rows in this order, and label "
                         "each row with the task you assigned that agent, which you know "
                         "and this hook does not, the hook only knows the agent type. Rows "
                         "that say No images are agents whose reply stayed text; they are "
                         "listed so the user sees every agent, and they are not in the "
                         "run totals or the savings:")
        lines += table
        lines += detail
        if net_seen:
            lines.append("")
            lines.append(footnote)
        if conversation_block:
            lines.append("")
            lines.append("Print these two rows as their OWN table, separate from the one above, the whole conversation's own totals so far, the same "
                         "figures the line below states:")
            lines.append("")
            lines += conversation_block
        lines.append("")
        lines.append("Conversation so far: %s reports, %s images, %s tokens saved."
                     % (totals["reports"], totals["images"],
                        group(totals["text_tokens"] - totals["image_tokens"])))
    # OUTSIDE the receipt branch, on purpose. Inside it, the table would
    # appear only when a finished agent's report arrived, so a lead that
    # spawned four agents and answered before any of them finished would
    # print nothing, at the exact moment the user most needs to see which
    # models are running.
    delegation = delegation_table(sid)
    if len(delegation) > 3 and status_shown():
        lines.append("")
        if _rule_already_sent("delegation"):
            lines.append("Print the delegation table below too, as before:")
        else:
            lines.append("Print the delegation table below too, exactly as given: every "
                         "agent you have spawned this session, oldest first. Print it "
                         "whether or not any of them has finished. The Model column is "
                         "the point of it. It is the only place that shows which model "
                         "actually ran each agent, so a subagent that should only "
                         "diagnose, plan or critique but did heavy building work instead "
                         "is visible here, not found later. Every spawn is recorded:")
        lines += delegation

    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(lines),
        }
    }
    # systemMessage is the one hook field Claude Code shows to the user
    # directly (hooks reference, JSON output table). A rule the lead must
    # obey is not a guarantee and a hook field the user sees is, so the WHOLE
    # table goes here. The lead still gets its own copy in additionalContext,
    # because only the lead knows which task each agent was given and can
    # label the rows; if it prints that, the user gets a labeled table, and if
    # it does not, the user still gets this one.
    code_files = [item["code"] for item in entries if item.get("code")]
    # The python blocks are drawn, not lifted out.
    # The pages are named here in the order the blocks stood in, and the .txt
    # is still named beside them, so a reader that needs an exact byte opens
    # the file and a reader that only needs to read the code opens the page.
    code_pages = [page for item in entries
                  for page in (item.get("code_images") or [])]
    code_drawn = sum(item.get("code_drawn") or 0 for item in entries)
    code_text = sum(item.get("code_text") or 0 for item in entries)

    # Record that a receipt is owed for this turn, so a stop hook can hold a
    # reply that lacks one. A reminder does not make the lead relay the one
    # column no hook can fill in, the task each agent was given; a gate does.
    # Quiet mode owes nothing: the user asked for no table.
    if table and mode != "quiet" and packed_entries:
        try:
            (tmp_dir() / "densepack-receipt-owed.json").write_text(
                json.dumps({
                    "session": str(event.get("session_id") or ""),
                    # The turn this debt belongs to. Without it a debt left
                    # behind by an interrupted turn blocks the NEXT reply,
                    # which owes nothing, and costs the user a turn for no
                    # reason.
                    "prompt_id": str(event.get("prompt_id") or ""),
                    "written": time.time(),
                    "agents": [item.get("agent_type", "agent")
                               for item in packed_entries],
                }), encoding="utf-8")
        except OSError:
            pass

    if table and mode != "quiet" and packed_entries:
        run_saved = run["text_tokens"] - run["image_tokens"]
        run_pct = (round(run_saved / run["text_tokens"] * 100)
                   if run["text_tokens"] else 0)
        opening = ("DensePack receipt. Measured by the hook from the source "
                   "text and the PNG on disk, both kept beside the image.")
        plural = lambda n, word: "%s %s%s" % (group(n), word, "" if n == 1 else "s")
        closing = ("This batch: %s packed, %d%% saved, %s tokens, delivery "
                   "fee included. Conversation so far: %s, %s, %s tokens saved."
                   % (plural(len(with_images), "report"), run_pct, group(run_saved),
                      plural(totals["reports"], "report"),
                      plural(totals["images"], "image"),
                      group(totals["text_tokens"] - totals["image_tokens"])))
        # Code lifted out of an image lives in a file the lead is told about.
        # The user was told only if the lead passed the path on, so the path
        # is named here as well: the code is the part of the report that
        # cannot be read off the image.
        code_line = ("Code blocks came out of %s. %s drew banded in: %s. "
                     "%s stayed text. Every block is at full fidelity "
                     "in: %s"
                     % (plural(len(code_files), "report"),
                        plural(code_drawn, "python block"),
                        ", ".join(code_pages) or "no page",
                        plural(code_text, "block"),
                        ", ".join(code_files)))
        note = [opening, ""] + table + detail
        if net_seen:
            note += ["", footnote]
        if conversation_block:
            note += [""] + conversation_block
        if code_files:
            note += ["", code_line]
        note += ["", closing]
        shown = "\n".join(note)
        if len(shown) > MESSAGE_CHARS:
            # Claude Code caps a hook string at 10,000 characters and replaces
            # anything longer with a preview and a file path, which would
            # break the guarantee on a long run. A receipt over the limit is
            # cut here to the numbers plus the path of the table the hook
            # already filed, so the user still gets both.
            short = [opening, "", closing, "",
                     "The full table for this batch is in %s ." % receipt_file]
            if code_files:
                short += ["", code_line]
            shown = "\n".join(short)
        payload["systemMessage"] = shown
    elif mode != "quiet" and [i for i in entries if i.get("reason") in BROKEN]:
        # A batch where nothing packed carries no saving, so there is no table
        # to show and in most cases nothing to say: text measuring cheaper is
        # the plugin working, not failing. A batch that failed is different.
        # Silence here would let a user watch a whole session pack nothing
        # and never learn that Pillow was missing or the packer threw.
        # One line, only on a failure.
        broken = sorted({reason_said(i) for i in entries if i.get("reason") in BROKEN})
        payload["systemMessage"] = (
            "DensePack packed nothing from this batch of %d agent report(s) "
            "and the reports arrived as plain text: %s."
            % (len(entries), "; ".join(broken)))
    emit(payload)
    return 0


def guarded_main():
    """Never let an exception out of this hook.

    main() outside any try would let a fault change the outcome of the tool
    call that fired the hook. The error is written to stderr so the fault is
    still visible. The exit code stays 0, which lets the call through.
    """
    try:
        return main()
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack %s: %s\n" % ("pointer.py", err))
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
