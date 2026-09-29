"""PostToolUse hook. It gives the lead model the images and the receipt.

Claude Code runs this hook after each tool call. subagent_stop.py puts images
on the queue. This hook tells the lead model where the images are and tells it
to read them in place of the text. It prints the receipt: the number of
characters, the image size, the cost of each, and the saving. It also keeps
the running total. session_end.py makes the final bill from that total.

The settings file stores one of four receipt modes:

  default  One 4 column table for each batch of agents, with one row for each
           agent that returned images. A label row and a BATCH TOTALS row for
           the batch close the same table. The table always has this row, in
           default and in verbose. The totals setting does not control it.
           When the totals setting is on, a second label row and a
           CONVERSATION TOTALS row follow it. That row holds the sums for the
           whole conversation. When the setting is off, the hook keeps that
           second row for the wrap-up only. In the two cases, the running
           total also prints as a separate "Conversation so far" line under
           the table. The BATCH TOTALS row holds the numbers for this batch
           only. The CONVERSATION TOTALS row holds the sums for the whole
           conversation, the same figures as the "Conversation so far" line.
  verbose  The same batch table with the arithmetic in separate columns and a
           Dimensions column. It adds a table of the images for each agent
           that returned more than one image. BATCH TOTALS prints in each
           response, the same as in default. CONVERSATION TOTALS follows it
           when the totals setting is on. In this mode it also prints while
           the totals setting is at its default, auto, which follows verbose.
           The two totals rows give the full model name, such as Haiku 4.5,
           Sonnet 5, Opus 5 or Fable 5. The default mode uses a single letter.
  light    The compact 4 column table with no totals row, whatever the totals
           setting is. The "Conversation so far" line still prints under it.
  quiet    No table in the response. The hook writes the table to
           .claude/tmp/densepack-receipt-last.md. It tells the lead model in
           one line to show the table only when the prompt asked for a report.
           The hook still measures the numbers, and the manifest still gets a
           row for each finished agent. Only the printed table stays out.

The character U+2248 (almost equal to) replaces = in the column names of the
default and light tables, because a token count from characters or pixels is
an estimate. The output of this hook is JSON. json.dumps writes the character
as an ASCII escape, and Claude Code decodes it. This hook prints no raw UTF-8
to a console.
"""

import os
import sys


def _nothing_queued():
    """The first exit. The hook calls this before it imports anything else.
    Return True when no queue exists. That is the case after most tool calls.
    This check uses os.path and not pathlib, because the pathlib import alone
    costs about 15 ms and this check runs after each tool call."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        return False
    return not os.path.exists(os.path.join(
        root, ".claude", "tmp", "densepack-queue.jsonl"))


# The drop scan below imports nothing from common.py. An empty scan adds no
# import time. The hook loads common.py only when a report is on the queue or
# the scan finds a drop file. _nothing_queued() above uses os.path in place of
# pathlib for the same reason.


# A scan claims a to-pack file. It renames the file in place to
# CLAIM_PREFIX<epoch seconds>-<8 hex>-<name>. The file stays in to-pack, and
# no prune deletes anything there. A claim older than CLAIM_STALE_SECONDS
# comes from a scan that stopped before it finished. The next scan gives that
# file its old name back. A file that the hook cannot pack, and that
# _set_aside() cannot move, keeps its bytes under FAILED_PREFIX<name>. The
# scan skips that file.
CLAIM_PREFIX = ".densepack-claim-"
FAILED_PREFIX = ".densepack-failed-"
CLAIM_STALE_SECONDS = 1800
# The folder in to-pack that holds each packed file next to its images.
PACKED_FOLDER = "packed"


def _find_drop_file():
    """Return each file in the to-pack folder or the drop folder as
    (None, [paths]). Return None when the two folders are empty. That is the
    result after most tool calls. The scan uses os.walk on the two folders
    and nothing more. It has no watcher and no hook on Read. The scan returns
    each file. A file that another program holds open does not stop the files
    after it."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        return None
    # The scan packs each file in the "to-pack" folder.
    # A packed file moves into to-pack/packed/. The walk skips that folder
    # and packs each file one time only.
    # The walk also finds a file in the "drop" folder of an older version, or
    # in one of its subfolders. draw_drop_file() gets the model name, because
    # this scan runs before the hook imports common.
    bases = [os.path.join(root, ".claude", "densepack-vault", "to-pack"),
             os.path.join(root, ".claude", "densepack-vault", "drop")]
    # The scan does not follow or return a link. The pack step rejects a
    # link. A link left in the list slows each later tool call.
    # This is common.is_junction, inline, because this scan runs before the
    # hook imports common. os.path.isjunction is new in Python 3.12, and the
    # hooks run on 3.10. On 3.10, os.path reports a junction as a plain folder
    # unless the code reads the reparse tag.
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
                                               or isjunction(os.path.join(folder, d)))
                       and not (folder == base and d == PACKED_FOLDER)]
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
    # Read stdin one time, here, before any exit check. A TaskStop tool call
    # has no report to drain. Without this read, the queue-and-drop check
    # below finds an empty queue and exits before main() gets the stop. Then
    # no file on disk records the stop.
    # main() passes _RAW_STDIN to read_event(). A second read of stdin finds
    # an empty pipe. The code sets stdin to utf-8 first. read_event() does the
    # same before it reads. Without it, Windows gives hook stdin as cp1252,
    # and each UTF-8 quote becomes mojibake with no error.
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    _RAW_STDIN = sys.stdin.read()
    _DROP_HIT = _find_drop_file()
    # A substring check, not json.loads. This line runs before the json
    # import below. _nothing_queued() uses os.path in place of pathlib for
    # the same reason. A false positive costs one regular run of main(). Each
    # batch with a queue already pays that cost. The check must not skip a
    # real TaskStop call. That is the one failure that matters here.
    _TASK_STOP = '"TaskStop"' in _RAW_STDIN
    if _DROP_HIT is None and _nothing_queued() and not _TASK_STOP:
        raise SystemExit(0)
else:
    _DROP_HIT = None
    _RAW_STDIN = None

import json  # noqa: E402  this import comes after the first exit
import re  # noqa: E402
import time  # noqa: E402
try:
    import densepack as _dp  # noqa: E402
except ImportError:
    # Pillow is missing. The hook cannot pack or price anything. A hook that
    # raises here fails on each tool call. bootstrap.py already shows on
    # screen that Pillow is missing.
    raise SystemExit(0)

# The divisor as it prints in the "Characters / N = text tokens" column of a
# receipt. The code builds it from the constant and never types it as a
# literal. The receipt must show the same number that its arithmetic used.
DIV = "%.2f" % _dp.CHARS_PER_TOKEN

from common import (append_lifecycle, code_size, disabled, drain_queue, emit,  # noqa: E402
                    read_event, read_leads, swap_applies,
                    read_totals, receipts_mode, status_shown,
                    tmp_dir, MEASURED_MODELS, vault_dir,
                    resolved_reader, UNKNOWN_READER,
                    totals_shown, write_totals, report_pointer, stub_pointer,
                    STALE_AFTER, DEAD_AFTER, jsonl_rows)

# The one non-ASCII character in the output. The code writes it as an escape
# to keep this source file plain ASCII.
APPROX = "\u2248"
PATCH = 28
RECEIPT_FILE = "densepack-receipt-last.md"

# The one row before the inline legend. It says where the rows came from and
# nothing else. It names no file, because a model that reads that a value is
# in a file opens that file. It gives no order, because an order not to
# verify, next to a tool result, looks like a prompt injection. It is one
# line, because drop_read_gate.main() subtracts its characters from the
# saving of the image.
MARKER_HEADING = ("DensePack copied the rows below out of the file before it "
                  "packed the file into an image. Each row is the exact text behind one "
                  "[#N] tag:")

# The label that each marker row has about its own text. A model has a habit
# of checking numbers. A claim that the model reads one time in a heading does
# not stop that habit. The label is in the row, next to the value, for that
# reason. It states only where the text came from. A model reads a label with
# a warning against the image as an order to trust the row.
MARKER_SOURCE = "copied from the file"


def marker_rows(rows):
    """Return the sidecar rows in the form the message gives them. Each
    "[#1] = value" row states in the row that the text is the exact bytes of
    the file.

    The code does not change the value. The row still holds the exact
    characters of the sidecar. A row with no " = " passes through unchanged.
    legend_sidecar() writes such a row as the escalated-tag header for a {#n}
    or <#n> report. The split on the FIRST " = " keeps a value that contains
    " = " whole, because a tag never contains one.
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


# WORD FILES THAT THE AGENT FINDS IN THE MIDDLE OF A TASK.
#
# prompt_card.py finds a .doc or .docx that a typed message names. That
# hook runs one time, when the prompt arrives. It cannot find a file that
# the agent finds later with Glob, Grep or a shell command. The Read tool of
# Claude Code rejects a binary file before any PreToolUse hook runs, and
# drop_read_gate.py does not get that call. Without this scan, the agent
# spends an extra tool call to pack the file by hand.
#
# This hook runs after EACH tool call and gets the output of that tool. That
# output is the one place where the name of such a file shows. The hook packs
# a path that it finds here at once. The image is ready before the agent asks
# for it, and the read costs one turn, the same as each other file type.
#
# The agent runs that Glob in any case. The pack step inside the same call
# adds no tool call.
WORD_IN_OUTPUT = re.compile(
    r"""((?:[A-Za-z]:[\\/]|[\\/])[^"'<>|\r\n*?]*?\.docx?)\b""",
    re.IGNORECASE)
# Tools with output that can name a file on disk. Read is not in the list. A
# Read of a Word file does not reach this hook. A Read of any other file names
# no new path to scan.
WORD_SCAN_TOOLS = ("Glob", "Grep", "Bash", "LS")
# The number of characters of one tool result that the scan searches. Shell
# output can be megabytes long. A useful path is in a file listing, not at the
# end of a build log.
WORD_SCAN_CHARS = 100_000
# The limit for each tool call. It prevents a long render after one Glob of a
# documents folder. A file past the limit stays unpacked, and the agent can
# still pack it by hand.
WORD_SCAN_MAX = 6


def word_pages_from_tool(event):
    """Pack each .doc and .docx that this tool call shows. Return the pointer
    sentence for them, or "" when the call shows none.

    This function does not raise. On each fault it leaves the file alone. The
    rest of this file uses the same failure mode. The agent still gets the
    rejection from Claude Code and can still pack the file by hand.
    """
    try:
        if str(event.get("tool_name") or "") not in WORD_SCAN_TOOLS:
            return ""
        text = str(event.get("tool_response") or "")[:WORD_SCAN_CHARS]
        # The first filter, before the regex and each stat call.
        if ".doc" not in text.lower():
            return ""
        from pathlib import Path
        import prompt_card
        import densepack as dp
        import drop_read_gate as gate
        from common import ensure_pillow, pack_images
        if not ensure_pillow():
            return ""
    except Exception:  # noqa: BLE001
        return ""
    try:
        return _word_rows(text, event, Path, prompt_card, dp, gate,
                          pack_images)
    except Exception:  # noqa: BLE001
        # One try around the whole walk, not only the file calls. A fault
        # here must not reach the tool call that started this hook.
        return ""


def _word_rows(text, event, Path, prompt_card, dp, gate, pack_images):
    """The pack walk for word_pages_from_tool(). It is a separate function
    because one try in the caller then covers all of it."""
    rows, seen = [], set()
    for match in WORD_IN_OUTPUT.finditer(text):
        if len(rows) >= WORD_SCAN_MAX:
            break
        try:
            path = Path((match.group(1) or "").strip())
            if not path.is_file():
                continue
            key = str(path.resolve()).lower()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        try:
            # This file IS the pointer module that _word_file_sentence()
            # takes. prompt_card imports it only inside its own function.
            # prompt_card.pointer does not exist to pass.
            sentence = prompt_card._word_file_sentence(
                path, event, dp, gate, sys.modules[__name__], pack_images)
        except Exception:  # noqa: BLE001
            continue
        if sentence:
            rows.append(sentence)
    return "\n\n".join(rows)


def image_stem(path):
    """Return the first part of the name of each image of `path`. It is the
    folder of the file in the project, with a dash for each separator, then
    the file name with its extension.

    README.md at the project root gives README.md, and src/README.md gives
    src-README.md. The extension stays. same.py and same.md in one folder
    then never share an image name or a sidecar. Without the extension, a
    turn that reads the two files can give the first Read the image of the
    second file. A file outside the project keeps only the name of its own
    folder. The folder part keeps its last 80 characters and the name keeps
    its first 48. A deep path then still fits in a Windows path.
    """
    from pathlib import Path
    from common import project_dir

    def safe(part):
        # A hyphen joins the folders to the name. A hyphen inside a part
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
        # A file outside the project keeps only the name of its own folder.
        # An image name then never holds the account name or the folder
        # layout of the machine.
        folders = parent.parts[-1:]
    head = "-".join(safe(p) for p in folders if p)[-80:].lstrip("-")
    # The cut keeps the extension. Two long names that differ only in the
    # extension still get two image names.
    stem = safe(src.stem)[:40] + safe(src.suffix)[:8]
    return "%s-%s" % (head, stem) if head else stem


def claimed_stem(path, base=None):
    """Return image_stem(path), unique to this one source file.

    image_stem() gives a readable name, not a unique one. Three cases give
    one stem: a-b/c.py and a_b/c.py, two files outside the project with the
    same folder name, and two long names that match in their first 40
    characters. The second pack then overwrites the images of the first
    file. A claim file next to the images holds the real path of the source.
    The code makes it in one step with O_EXCL. The first file keeps the plain
    stem. Another file with the same stem gets ~2, ~3, up to ~50. After 50
    names, the name gets ~ and 8 hex characters of a sha256 of the path.
    """
    from pathlib import Path
    from common import project_dir, through_link, vault_dir
    # base is image_stem(path) on the Read route and the file name on the
    # to-pack route.
    if base is None:
        base = image_stem(path)
    images = vault_dir() / "images"
    try:
        # A committed link at images/ sends the claim to a folder outside
        # the project. The claim holds the full path of the source.
        if through_link(project_dir(), images):
            return base
        images.mkdir(parents=True, exist_ok=True)
        if through_link(project_dir(), images):
            return base
        me = os.path.normcase(os.path.realpath(str(path)))
    except OSError:
        return base
    # 50 names, not more. A project can commit claim files for each name. A
    # read of thousands of them makes each Read take half a minute. After 50,
    # the name holds 8 hex characters of the path. No committed claim can
    # take that name in advance.
    for n in range(1, 51):
        stem = base if n == 1 else "%s~%d" % (base, n)
        claim = images / ("%s-claim-DensePack.txt" % stem)
        try:
            fd = os.open(str(claim), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            # The code reads only a regular file, and only up to the length
            # of the path. A committed claim can be very large, or a FIFO
            # that blocks.
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
    """Rename each file that the model gets to
    <stem>-image-N-of-M-DensePack.<suffix>, with N from 1. On the Read route,
    stem comes from image_stem().

    image is the first file and more is the rest. `drawn` is each file that
    the pack step wrote to disk. The code removes a page that went into a sheet,
    because the sheet holds it. A file named in keep stays, because the code
    reads the price from it. The suffix stays, and a PDF keeps .pdf. Return
    `(image, more, drawn)` with the new names. A model finds an image by its
    name. The name gives the file and the count and nothing else.
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


# The last note that later_images_note() built, as (images key, note). The
# Read gate drops the note when this session already got it for the same
# images.
LAST_NOTE = None


def later_images_note(src_name, folder, names, at=1, firsts=None, last=None):
    """Return the note next to image `at` of a file that became several
    images. It names the plugin, the file, the folder one time, and this
    image. When `firsts` gives the first lines, it also gives the first and
    last source lines of each image. `last` is the last line of the file.

    A note that names each image in full costs about 1,150 tokens for a 61
    image file, and the hook sends it again on each Read of the file. The names
    differ only in the image number. This note names this image and gives the
    lines of each image by number."""
    global LAST_NOTE
    total = len(names)
    # The project names its own files. The model reads this sentence as the
    # words of the plugin. For that reason, no shell metacharacter and no
    # line break goes in.
    from common import no_metacharacters
    # The file name only. The folder and the image names go through as they
    # are, because the model opens them. A clean of a project folder called
    # "My Project (x86)" gives a path that does not exist. A clean of an image
    # name built from a file name with brackets gives a file that is not
    # there. grep_gate.py uses the same rule for the same reason.
    src_name = no_metacharacters(src_name)
    firsts = list(firsts or [])
    if len(firsts) != total or not all(isinstance(f, int) for f in firsts):
        firsts = []
    # The last line of each image. It is one less than the first line of the
    # next image. For the last image, it is the last line of the file.
    ends = [f - 1 for f in firsts[1:]] + [last if isinstance(last, int) else "end"]
    span = ", lines %d to %s" % (firsts[at - 1], ends[at - 1]) if firsts else ""
    rows = ["DensePack plugin converted %s into %d png images in %s. This is "
            "image %d of %d, %s%s." % (src_name, total, folder, at, total,
                                       names[at - 1], span)]
    # The names that deliver_names() writes differ only in the image number.
    # The name above gives the model each other name. When any name does not
    # match that pattern, the note gives the names in full. The full names
    # prevent a model from opening a file that is not there.
    tail = "-image-1-of-%d-DensePack.png" % total
    stem = names[0][:-len(tail)] if names[0].endswith(tail) else None
    one_pattern = stem and all(n == "%s-image-%d-of-%d-DensePack.png" % (stem, i, total)
                               for i, n in enumerate(names, 1))
    if firsts and one_pattern:
        rows.append("The first and last lines of the images: %s." % ", ".join(
            "#%d=%d-%s" % (i, f, e) for i, (f, e) in enumerate(zip(firsts, ends), 1)))
    else:
        for n, name in enumerate(names, 1):
            if n != at:
                rows.append("Image %d of %d is %s%s." % (
                    n, total, name,
                    ", lines %d to %s" % (firsts[n - 1], ends[n - 1]) if firsts else ""))
    # A review read drop_read_gate.py one image per turn, 8 turns for one
    # file, where a text Read gives the whole file in one call. The model
    # still picks the images it needs, and it Reads them in one turn.
    rows.append("Read all the other images that you need in one turn.")
    full = " ".join(rows)
    LAST_NOTE = ("%s|%s" % (folder, "|".join(names)), full)
    return full


# A .docx is a zip of XML, not text. read_text() returns the container, and
# the null check in draw_drop_file drops it. The Read tool of Claude Code
# rejects the suffix before a hook can return anything. Without this code, a
# Word file never reaches a model. The paragraphs are all the text a model
# uses from a .docx, and the plugin packs them. The code uses the standard
# library only. Most projects hold only a few files of this format. That is
# too few to justify an extra install.
DOCX_BODY = "word/document.xml"
DOCX_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(src):
    """Return the visible text of a .docx, or None when the file does not
    open.

    One line for each paragraph, with tabs and line breaks in place. A list
    item is a paragraph and has its own line. A table row is one line, with
    its cells joined by " | ". The text copy keeps the rows of the table. The
    code drops styles, images and revision marks, because a model uses the
    words. Return None and do not raise. A caller then treats a file that
    does not open the same as any other source that it could not pack."""
    import xml.etree.ElementTree as ET
    import zipfile
    try:
        with zipfile.ZipFile(src) as bundle:
            body = bundle.read(DOCX_BODY)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None

    def para_text(para):
        out = []
        for node in para.iter():
            if node.tag == DOCX_NS + "t":
                out.append(node.text or "")
            elif node.tag == DOCX_NS + "tab":
                out.append("\t")
            elif node.tag == DOCX_NS + "br":
                out.append("\n")
        return "".join(out)

    def walk(element, lines):
        # Document order. A paragraph is one line and a table row is one
        # line. Each other element, such as a content control, holds only
        # paragraphs and tables. The walk goes into it.
        for child in element:
            if child.tag == DOCX_NS + "p":
                lines.append(para_text(child))
            elif child.tag == DOCX_NS + "tbl":
                for row in child.findall(DOCX_NS + "tr"):
                    cells = []
                    for cell in row.findall(DOCX_NS + "tc"):
                        inner = []
                        walk(cell, inner)
                        cells.append(" ".join(part.replace("\n", " ")
                                              for part in inner if part.strip()))
                    lines.append(" | ".join(cells))
            else:
                walk(child, lines)

    lines = []
    body_node = root.find(DOCX_NS + "body")
    walk(body_node if body_node is not None else root, lines)
    return "\n".join(lines)


# The old binary .doc is an OLE2 container, a small filesystem of streams
# inside one file. The words are in the WordDocument stream, but not as one
# run. A piece table in the Table stream gives the byte range of each part of
# the document, and whether that part is 8-bit or UTF-16. A walk of that
# table is the only way to get the text in reading order without the Word
# program. The walk returns 100% of the text of four documents built from
# known text. The code uses the standard library only, like the .docx route.
DOC_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_OLE_FREE, _OLE_END = 0xFFFFFFFE, 0xFFFFFFFF


def _ole_streams(raw):
    """Return {name: bytes} for each stream in an OLE2 file, or {} when the
    file is malformed."""
    import struct
    if len(raw) < 512 or not raw.startswith(DOC_MAGIC):
        return {}
    try:
        ssz = 1 << struct.unpack_from("<H", raw, 0x1E)[0]
        mssz = 1 << struct.unpack_from("<H", raw, 0x20)[0]
        dir_start = struct.unpack_from("<I", raw, 0x30)[0]
        mini_start = struct.unpack_from("<I", raw, 0x3C)[0]
        difat_start = struct.unpack_from("<I", raw, 0x44)[0]
    except struct.error:
        return {}
    if not 128 <= ssz <= 1 << 20:
        return {}

    def sector(n):
        off = 512 + n * ssz
        return raw[off:off + ssz]

    # The sector list has 109 entries in the header, then a chain of sectors.
    fat_sectors = list(struct.unpack_from("<109I", raw, 0x4C))
    nxt, guard = difat_start, 0
    while nxt not in (_OLE_FREE, _OLE_END) and guard < 4096:
        blk = sector(nxt)
        if len(blk) < ssz:
            break
        fat_sectors += list(struct.unpack_from("<%dI" % (ssz // 4 - 1), blk, 0))
        nxt = struct.unpack_from("<I", blk, ssz - 4)[0]
        guard += 1

    fat = []
    for s in fat_sectors:
        if s in (_OLE_FREE, _OLE_END):
            continue
        blk = sector(s)
        if len(blk) < 4:
            continue
        fat += list(struct.unpack_from("<%dI" % (len(blk) // 4), blk, 0))

    def chain(start, table, read, size=None):
        out, n, guard = [], start, 0
        while n not in (_OLE_FREE, _OLE_END) and 0 <= n < len(table) \
                and guard < 1 << 20:
            out.append(read(n))
            n = table[n]
            guard += 1
        data = b"".join(out)
        return data[:size] if size is not None else data

    dirdata = chain(dir_start, fat, sector)
    entries = []
    for off in range(0, len(dirdata) - 127, 128):
        nlen = struct.unpack_from("<H", dirdata, off + 0x40)[0]
        if not 2 <= nlen <= 64:
            continue
        entries.append((
            dirdata[off:off + nlen - 2].decode("utf-16-le", "replace"),
            dirdata[off + 0x42],
            struct.unpack_from("<I", dirdata, off + 0x74)[0],
            struct.unpack_from("<I", dirdata, off + 0x78)[0]))

    # A stream under 4 KB is in the mini stream that the root entry names.
    root = next((e for e in entries if e[1] == 5), None)
    minifat, ministream = [], b""
    if root:
        mc = chain(mini_start, fat, sector)
        if mc:
            minifat = list(struct.unpack_from("<%dI" % (len(mc) // 4), mc, 0))
        ministream = chain(root[2], fat, sector, root[3])

    def mini_sector(n):
        return ministream[n * mssz:(n + 1) * mssz]

    out = {}
    for nm, kind, start, size in entries:
        if kind != 2:
            continue
        if size < 4096 and minifat:
            out[nm] = chain(start, minifat, mini_sector, size)
        else:
            out[nm] = chain(start, fat, sector, size)
    return out


def doc_text(src):
    """Return the visible text of an old binary .doc, or None when the file
    does not open.

    Return None and do not raise. A caller then treats a file that does not
    open the same as any other source that it could not pack."""
    import struct
    from pathlib import Path
    try:
        raw = Path(src).read_bytes()
    except OSError:
        return None
    try:
        wd = _ole_streams(raw).get("WordDocument")
        if not wd or len(wd) < 0x200:
            return None
        streams = _ole_streams(raw)
        flags = struct.unpack_from("<H", wd, 0x0A)[0]
        table = (streams.get("1Table" if flags & 0x0200 else "0Table")
                 or streams.get("0Table") or streams.get("1Table"))
        fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)

        pieces = []
        if table and lcb_clx and fc_clx + lcb_clx <= len(table):
            clx = table[fc_clx:fc_clx + lcb_clx]
            i = 0
            while i < len(clx):
                if clx[i] == 1:        # formatting run, skipped
                    if i + 3 > len(clx):
                        break
                    i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
                elif clx[i] == 2:      # the piece table itself
                    size = struct.unpack_from("<I", clx, i + 1)[0]
                    pt = clx[i + 5:i + 5 + size]
                    n = (len(pt) - 4) // 12
                    cps = list(struct.unpack_from("<%dI" % (n + 1), pt, 0))
                    for k in range(n):
                        fc = struct.unpack_from(
                            "<I", pt, 4 * (n + 1) + 8 * k + 2)[0]
                        chars = cps[k + 1] - cps[k]
                        if fc & 0x40000000:
                            pieces.append(((fc & ~0x40000000) // 2, chars, True))
                        else:
                            pieces.append((fc, chars, False))
                    break
                else:
                    break
        if not pieces:                 # Word 6 and 95 use one plain run
            fc_min, fc_mac = struct.unpack_from("<II", wd, 0x18)
            if fc_mac > fc_min:
                pieces = [(fc_min, fc_mac - fc_min, True)]

        out = []
        for start, chars, eight in pieces:
            if eight:
                out.append(wd[start:start + chars].decode("cp1252", "replace"))
            else:
                out.append(
                    wd[start:start + chars * 2].decode("utf-16-le", "replace"))
        text = "".join(out)
    except (struct.error, IndexError, ValueError):
        return None

    # The control marks of Word. 0x07 ends a cell, 0x0C a page, 0x0D a row.
    # 0x13 to 0x15 wrap a field. 0x01 marks a picture. None of them are words.
    text = text.replace("\r", "\n").replace("\x07", "\n").replace("\x0c", "\n")
    text = "".join(c for c in text if c >= " " or c in "\n\t")
    return text or None


def draw_drop_file(model, src_path, actor=None, name_stem=None, name=None, source=None,
                   out_dir=None, keep_source=False):
    """Pack the file from the to-pack folder into images/, at the pixel size
    of the model, then delete the copy. With out_dir, the images go into that
    folder in place of images/. With keep_source, the file stays in place.
    The to-pack scan uses the two and then moves the file next to its images.
    For a .doc or .docx, the code also writes the packed text next to the
    images as <stem>.txt. The images use the name of that text file as their
    stem and as the file= name in their key row. Return (line, image_path).
    line names the image, and image_path is the Path of the image. Return
    (None, None) when the code packed nothing, because the model has no
    measured size, Pillow is missing, or the pack step failed. A failed pack
    deletes nothing, and the caller handles the file.

    When ident_legend holds identifiers, line holds the rows of the legend
    itself, "[#1] copied from the file = <exact text>", under one heading
    row. This function reads those rows back from the sidecar file that it
    wrote. The value in the message is then the exact characters of the
    record, and no second format needs a separate update. marker_rows() adds
    the label and nothing else. The two pack paths below leave ident_legend
    empty, and the code writes no rows.

    The code still builds the "Tags: <full path>" row, because discard()
    must delete the sidecar that it names. The two callers remove the row
    before the line reaches a model. A model reads the name of that file as
    an instruction to open it.

    This is the one place where this plugin packs a dropped file into an
    image. The scan in this file calls it through _draw_drop_file() and
    uses only the status line. That scan needs nothing more.
    drop_read_gate.py calls this function directly. A regular file with no
    sibling image then still gets a redirect. A call in the SAME hook turn
    rewrites the Read to go straight to the image, with no agent action and
    no retry turn. The sibling-image redirect already works the same way.
    """
    import hashlib
    from pathlib import Path
    if model is None:
        model = resolved_reader() or UNKNOWN_READER
    px = MEASURED_MODELS.get(model)
    if px is None:
        return None, None
    # A test override. When the environment sets DENSEPACK_PX_OVERRIDE, the
    # code packs each drop at that size. A test can then measure another size
    # for cost and accuracy. A normal session does not set the variable, and
    # nothing changes. It is never a settings key and never a default.
    override = os.environ.get("DENSEPACK_PX_OVERRIDE", "").strip()
    if override.isdigit() and 6 <= int(override) <= 16:
        px = int(override)
    src = Path(src_path)
    # The name of the file as it arrived in to-pack. The scan renames a
    # file that it claims. That claim name must never reach an image.
    shown = Path(name) if name else src
    # This function deletes src. A path through a link or a junction can go
    # outside the project. The code does not touch such a path.
    from common import project_dir, through_link
    if through_link(project_dir(), src):
        return None, None
    # No age rule. A copied or moved file keeps an old time, and an age rule
    # deletes it before a model sees it. When the pack step fails, the caller
    # handles the file. The to-pack scan moves it to not-converted/, and the
    # Read gate deletes its own staging copy. Nothing here deletes a file that
    # it could not pack.
    try:
        mtime = src.stat().st_mtime
    except OSError:
        return None, None
    try:
        suffix = src.suffix.lower()
        text = (docx_text(src) if suffix == ".docx"
                else doc_text(src) if suffix == ".doc" else None)
        # A Word file that does not open is usually a renamed text file. Read
        # it as text like any other file, because Read rejects the two
        # suffixes. Without this step, no tool can read it. The null check
        # below still rejects it when it is binary.
        if text is None:
            text = src.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    # The renderer rejects a source that holds its own marks, U+E000 to
    # U+E003. A null byte means binary. The length limit is the one number in
    # the gate. The code reads it from there and does not repeat it here. A
    # change in one place then changes it in all places.
    from drop_read_gate import READ_MAX_BYTES
    if (any(mark in text for mark in "\ue000\ue001\ue002\ue003")
            or "\x00" in text or len(text) > READ_MAX_BYTES):
        return None, None
    digest = hashlib.sha256(
        ("%s|%f" % (src, mtime)).encode("utf-8")).hexdigest()[:12]
    images = Path(out_dir) if out_dir else vault_dir() / "images"
    # A committed link at images/ sends each image outside the project.
    if through_link(project_dir(), images):
        return None, None
    images.mkdir(parents=True, exist_ok=True)
    if through_link(project_dir(), images):
        return None, None
    # The work name holds the digest. Two packs of two files with one stem
    # then never overwrite each other while they run. deliver_names()
    # renames the files that the model gets to
    # <stem>-image-N-of-M-DensePack.png. That is a readable name with no model
    # name and no hash in it.
    # The extension stays in the name. same.py and same.md in to-pack then
    # never overwrite the images of each other.
    safe_stem = (re.sub(r"[^A-Za-z0-9_.-]", "_", shown.stem)[:40]
                 + re.sub(r"[^A-Za-z0-9_.-]", "_", shown.suffix)[:8])
    stem = images / ("%s.%s" % (safe_stem, digest))
    # THE ONE NAMING RULE. A text copy is in the same folder as its images.
    # Its name is the image name without "-image-N-of-M-DensePack.png". The
    # image stem then holds the full name of the text file. A Word file has
    # no text that a model can open. The code writes its packed text next to
    # the images as <stem>.txt, and the key row names that file. A to-pack
    # file is its own text. The scan moves it next to the images under
    # name_stem, and the key row names name_stem. On each other route, the
    # key row names the source file.
    word = suffix in (".doc", ".docx")
    names_stem = name_stem or safe_stem
    if word:
        names_stem += ".txt"
    title = names_stem if (word or out_dir) else shown.name
    code_image = False
    ident_legend = []
    try:
        import densepack as dp
        # reader=model is a second check. px above already comes from
        # MEASURED_MODELS.get(model). A caller that computes px in another
        # way still cannot give this model an image below its scored minimum
        # size.
        # codepack, the banded code renderer, packs a code source. It puts
        # one light background block behind each source line. The model then
        # does not misread identifiers where the stream wraps.
        # tokenize classifies Python, and the plain classifier of codepack
        # classifies each other file. Each file gets the raw text. flatten()
        # removes each indent and blank line. With flatten(), a .tsx, .php,
        # Dockerfile or any suffix outside codepack.CODE_SUFFIXES loses its
        # indentation, and its green line numbers do not match the file.
        import codepack
        suffix = shown.suffix.lower()
        # legend=None. The numbers stay in the image. Marker references cost
        # the model far more output to resolve than the look-alike inks
        # cost. ident_legend stays empty here, and the code writes no
        # sidecar and no marker row. Each file gets the code image for each
        # model, at code_size().
        # Plan the pages with no glyph rendered, then render one time from
        # the plan. The pages are byte for byte the same as the pages from
        # pack_code(), in one process, with no width-search helpers and a
        # fraction of their memory. For a one page file, pack_planned() runs
        # the whole pack_code(), because its fill pass reads pixels.
        size = code_size(px, model)
        plan = codepack.plan_pages(text, size, suffix == ".py", None, None,
                                   model, title)
        written, _target, _lh = codepack.pack_planned(
            text, size, str(stem), plan, python=(suffix == ".py"),
            legend=None, reader=model, title=title)
        code_image = True
    except Exception:
        written = None
    if not written:
        return None, None
    # The pages get their final names here. The line of the scan and the
    # Pages row below then name the files that the model finds. The gate
    # renames them one more time after it builds sheets.
    # The first source line of each image. codepack counts rendered lines
    # from 0. A rendered line is a source line that is not blank.
    # build_flow() skips an empty code line, and dp.flatten() drops a blank
    # prose line.
    kept = [n for n, row in enumerate(text.split("\n"), 1)
            if (row != "" if code_image else row.strip())]
    opens = [codepack.PAGE_FIRST_LINE.get(str(p)) for p, _w, _h in written]
    first_lines = ([kept[k] for k in opens]
                   if all(isinstance(k, int) and k < len(kept) for k in opens) else [])
    # On the Read route, name_stem is image_stem() of the file that the
    # model read. Two files named x.py in two folders, read in one turn,
    # then never get one shared page name.
    first, rest, _all = deliver_names(written[0][0], [p for p, _w, _h in written[1:]],
                                      [p for p, _w, _h in written], names_stem)
    written = [(first,) + tuple(written[0][1:])] + [
        (r,) + tuple(w[1:]) for r, w in zip(rest, written[1:])]
    image = Path(first)
    if word:
        # The text copy of the Word file. It holds the exact text in the
        # images, and the green line numbers match the copy line for line.
        # newline="" keeps each line ending a single \n on Windows too.
        from common import clear_link
        text_copy = images / names_stem
        try:
            clear_link(text_copy)
            with open(str(text_copy), "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        except OSError:
            pass
    if not keep_source:
        try:
            src.unlink()
        except OSError:
            pass
    # The line says what packed the file and what the file is. It does not
    # list the file operations. A model reads a line about a copy and a
    # delete in a folder that it did not name as an attempt to redirect it.
    # The code cleans the image name. The source name is whatever the
    # project committed, and it never reaches the model as words.
    line = "DensePack converted a file from the to-pack folder into %s." % image
    # Each page, not page one alone. A Read returns one file. Without this
    # row, the model sees only the first page of a long file, and the price
    # compares one page with the whole text. The Pages row names the other
    # pages. drop_read_gate.py gives the row to the model as the note and
    # prices each page.
    if len(written) > 1:
        line = line + "\nPages: " + " , ".join(str(p) for p, _w, _h in written[1:])
    # The first source line of each page. The gate can then give a Read that
    # starts at line N the image that holds line N.
    if len(first_lines) > 1:
        line = line + "\nLines: " + " , ".join(str(n) for n in first_lines)

    # The sidecar goes next to the image. The Tags row names it by its full
    # path, because drop_read_gate.discard() deletes the file that the row
    # names when the price shows that the image costs more than the text. The
    # two callers remove the row before a model sees the line.
    #
    # The marker rows follow, in the message. The code reads them back from
    # the sidecar and does not rebuild them from ident_legend. The
    # escalated-tag header that legend_sidecar() writes for a {#n} or <#n>
    # report then reaches the model too, and the file and the message use
    # one format. marker_rows() then labels each row with MARKER_SOURCE. The
    # characters of the value stay unchanged.
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

    # Each pack kind logs a manifest row. Its saving then counts toward the
    # Without DensePack column of the live dashboard. image_tokens here is
    # the visual cost only, patch count times dp.image_cost. A drop goes
    # straight to the image, with no separate pointer read to add. A bash,
    # brief or report pack has that extra read.
    try:
        from subagent_stop import manifest_write
        here = (tmp_dir() / "densepack-lead-session").read_text(
            encoding="utf-8").strip()
        # The file name and the lines of each page. Without them, a row names
        # no file, and the text of a page packed from an uncommitted version
        # of the file has no count.
        # splitlines does not count the final newline of a file as a line.
        last_line = len(text.splitlines())
        starts = list(first_lines) if len(first_lines) == len(written) else [1]
        page_lines = [[a, (starts[i + 1] - 1) if i + 1 < len(starts) else last_line]
                      for i, a in enumerate(starts)]
        manifest_write({
            "packed": True,
            "spawned_by": here,
            "file": shown.name,
            "source": str(source or ""),
            "page_lines": page_lines,
            "chars": len(text),
            # A code image records its kind here, in the same field that
            # each other pack kind writes.
            "kind": "code" if code_image else "drop",
            # The agent that gets this image, and the model that set its
            # size. spawned_by is the session of the LEAD on each route.
            # Without these fields, a drop or code image for a subagent and
            # one for the lead are the same row in the records, and no
            # measure can group by agent. px and model are the values that
            # this pack used, taken above, never derived again.
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
    """Return the image stem of a to-pack file. It is the file name, cleaned,
    with the extension. draw_drop_file() uses the same rule for safe_stem."""
    from pathlib import Path
    own = Path(name)
    return (re.sub(r"[^A-Za-z0-9_.-]", "_", own.stem)[:40]
            + re.sub(r"[^A-Za-z0-9_.-]", "_", own.suffix)[:8])


def _claim_drop_file(src_path):
    """Rename one to-pack file in place to CLAIM_PREFIX<epoch>-<8 hex>-<name>
    and return the new path. Return None when another scan took it first,
    another program holds it open, or the path goes through a link. The file
    stays in to-pack, where no prune deletes anything."""
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
    """Move a claimed to-pack file that the hook could not pack into
    not-converted/ under its own name. The scan then does not try it again
    on each tool call, and the file stays on disk. Return the one line that
    the model gets, or None when the move is not safe."""
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
    # The file name is not in the line, because the project chose that name.
    return ("DensePack could not convert a file from the to-pack folder. It is in "
            ".claude/densepack-vault/not-converted/.")


def _packed_target(src_path, name):
    """Reserve the name of a to-pack file in to-pack/packed/, and return it
    as a Path. Return None when no safe name is free. The file keeps its
    subfolder. to-pack/sub1/x.py goes to to-pack/packed/sub1/x.py. A file
    from the drop folder of an older version goes to to-pack/packed/ too.
    The name is the cleaned name from _name_stem(), because the images use
    the same name as their stem. A name in use, or a name with images still
    there, gets ~2, ~3 before the extension. The code then never overwrites
    a packed file or image. The empty file made with O_EXCL holds the name.
    Two scans at the same time then never take the same name."""
    import glob
    import os
    from pathlib import Path
    from common import project_dir, through_link
    vault = vault_dir()
    parent = os.path.abspath(os.path.dirname(str(src_path)))
    sub = None
    for base in ("to-pack", "drop"):
        rel = os.path.relpath(parent, os.path.abspath(str(vault / base)))
        if rel == os.curdir:
            sub = ""
            break
        if not rel.startswith(os.pardir) and not os.path.isabs(rel):
            sub = rel
            break
    if sub is None:
        return None
    folder = vault / "to-pack" / PACKED_FOLDER
    if sub:
        folder = folder / sub
    if through_link(project_dir(), folder):
        return None
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    if through_link(project_dir(), folder):
        return None
    own = Path(_name_stem(name))
    for n in range(1, 1000):
        target = folder / (own.name if n == 1 else "%s~%d%s" % (own.stem, n, own.suffix))
        if glob.glob(glob.escape(str(target)) + "-image-*"):
            continue
        try:
            fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        except OSError:
            return None
        os.close(fd)
        return target
    return None


def _packed_line(line, target):
    """Return the line of the scan with a first row that names the packed
    paths. They are the image, the file now next to it, and the text copy of
    a Word file. The code drops the Tags and Lines rows. The Pages row and
    the marker rows stay."""
    rows = [row for row in line.split("\n")
            if not row.startswith(("Tags: ", "Lines: "))]
    image = rows[0]
    head = "DensePack converted a file from the to-pack folder into "
    if image.startswith(head) and image.endswith("."):
        image = image[len(head):-1]
    first = ("DensePack converted a file from the to-pack folder into %s. "
             "DensePack moved the file to %s, beside its images."
             % (image, target))
    if target.suffix.lower() in (".doc", ".docx"):
        first += " The text of the Word file is in %s.txt." % target
    rows[0] = first
    return "\n".join(rows)


def _draw_drop_file(model, src_paths):
    """The scan in pointer.py uses only the status line. drop_read_gate.py
    uses the (line, image_path) pair from draw_drop_file() above.

    The scan first moves the claimed file into to-pack/packed/, under the
    name that _packed_target() reserves. It then packs the file there, with
    its images next to it. The scan never deletes the file and never walks
    packed/. It then packs no file twice. A file that the scan cannot pack
    goes to not-converted/.

    The code drops the Tags row here. This scan has no file to delete and no
    use for the sidecar path. A path in the text sends a model to open that
    file. The marker rows below the heading stay, because the model needs
    them.

    The scan packs one file for each tool call, the first of src_paths that
    it can claim. Parallel tool calls start several scans at the same time.
    A scan with a failed claim goes to the next file. No two scans then work
    on one file."""
    import os
    from pathlib import Path
    paths = [src_paths] if isinstance(src_paths, str) else list(src_paths or [])
    for src_path in paths:
        claimed = _claim_drop_file(src_path)
        if claimed is None:
            continue
        name = Path(src_path).name
        target = _packed_target(src_path, name)
        if target is not None:
            try:
                os.replace(str(claimed), str(target))
            except OSError:
                try:
                    os.remove(str(target))
                except OSError:
                    pass
                target = None
        if target is None:
            aside = _set_aside(str(claimed), name)
            if aside:
                return aside
            # The scan could not pack or move the file. The file keeps its
            # bytes in to-pack under a name that the scan skips. The scan
            # never loses the file and does not try it again on each tool
            # call.
            try:
                os.replace(str(claimed), str(claimed.with_name(FAILED_PREFIX + name)))
            except OSError:
                pass
            return None
        line, _image = draw_drop_file(model, str(target), name=name,
                                      name_stem=target.name,
                                      out_dir=str(target.parent), keep_source=True)
        if line:
            return _packed_line(line, target)
        # The pack step failed, and the file goes to not-converted/. When
        # that move fails too, the file stays in packed/. There the scan
        # never loses it and does not try it again on each tool call.
        aside = _set_aside(str(target), name)
        if aside:
            return aside
        return None
    return None


def _rule_already_sent(name):
    """Return True when this session already got the rule called `name`.

    The lead does not need a rule again after it reads it one time. A second
    copy costs tokens, because each character sent stays in the prefix of
    each later turn. In one measured lead transcript, 9 report blocks held
    13,271 characters and 8 outbound brief blocks held 8,877. The rule text
    is most of the two.

    The marker is a file, because each hook run is a new process. The code
    writes it on the first call. The first batch gets the whole rule, and
    each later batch gets one line.
    """
    marker = tmp_dir() / ("densepack-rule-%s" % name)
    if marker.exists():
        return True
    # write_text_atomic moves the file onto the name. A link at that name
    # then gets no write.
    from common import write_text_atomic
    write_text_atomic(marker, "1")
    return False

# Claude Code limits additionalContext, systemMessage and plain stdout to
# 10,000 characters, per the hooks reference. It writes any longer text to a
# file and shows a preview and the path in its place. The receipt stays well
# under that limit. Claude Code then never makes it a preview.
MESSAGE_CHARS = 9000


def group(number):
    return format(int(number), ",")


def model_cell(item):
    """Return the model name, cut to its readable part. The cell shows
    a full id such as claude-opus-5 as Opus 5. An unknown model gets a dash
    and not a guess, because a wrong name on a receipt is worse than no
    name."""
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
        # parts joined with a dot. An 8 digit part is a date, not a version,
        # and the code drops it.
        parts = [p for p in rest.split("-")
                 if p.isdigit() and len(p) < 8]
        return (pretty + " " + ".".join(parts)).strip() if parts else pretty
    return raw


def is_brief(item):
    """Return True for a brief. A brief is the outbound half of the pipeline.
    It is an instruction packed for a subagent before the subagent started,
    not a report packed after one finished. It goes on the receipt, because
    its pack has a cost and a saving. It must never reach the lead as an
    image to read. The lead WROTE that brief, and a second read costs back
    the tokens that the pack saved.
    """
    return item.get("kind") == "brief"


def label_with_model(item):
    """Return one cell with the agent, then the model that wrote the report.
    No code in the plugin calls this function. The default receipt has four
    columns, and the model has its own column, Model."""
    who = label(item)
    model = model_cell(item)
    return who if model == "-" else "%s, %s" % (who, model)


def label(item):
    """Return the agent type, with the asterisk that marks a report that the
    lead already read as text. The lead replaces this with the task that it
    gave the agent."""
    if is_brief(item):
        return "brief to %s" % item["agent_type"]
    if not item.get("images"):
        return item["agent_type"]
    return item["agent_type"] + ("" if item["mode"] == "stub" else "*")


REASON_SAID = {
    "under the saving threshold": "Under the saving threshold, text is cheaper",
    "no prose report": "No prose report, structured output only",
    "mostly code": "Mostly code. DensePack does not pack code",
    "pack failed": "The pack failed. DensePack sent the text",
    "Pillow missing": "Pillow is missing. DensePack sent the text",
}


def reason_said(item):
    return REASON_SAID.get(item.get("reason", ""), item.get("reason", "text"))


# The two reasons that mean the plugin failed. The other reasons in
# REASON_SAID come from a rule in the plugin. The text measured cheaper, the
# report had no prose, or the report was code. Only these two get their own
# line on screen.
BROKEN = ("pack failed", "Pillow missing")


def text_row_default(item):
    """Return the row for an agent with a text reply. It has a raw text cost
    and no DensePack cost. The reason goes in the cell for the image price."""
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
    """Return the size of each image that subagent_stop.py recorded, as
    (width, height)."""
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
    """Return the number of packed entries in the stored totals, reports and
    briefs together. An older totals file has no "packed" key. The code then
    adds the reports count and the briefs count, and an existing session
    keeps working."""
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


# The Model cell on each receipt row. It holds the model family and a number,
# counted for each model in the batch. Two Sonnet agents show as Sonnet-01
# and Sonnet-02, not as two rows called Sonnet.
def numbered_model(item, seen):
    family = model_cell(item)
    if family == "-":
        return "-"
    short = family.split()[0]
    seen[short] = seen.get(short, 0) + 1
    return "%s-%02d" % (short, seen[short])


def default_header(first="Model"):
    """Return the four column names and the divider under them.

    Raw text cost is the cost of the words as text. DensePack cost is the
    cost of the image, with delivery. The Images count is on the verbose
    receipt only, because the saving reads correctly without the file count.
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


# The letters that name each model family. Order does not matter here. Only
# membership matters.
MODEL_LETTERS = (("Haiku", "H"), ("Sonnet", "S"), ("Opus", "O"), ("Fable", "F"))

# The print order of the Model cell in the totals rows: Fable, Opus, Sonnet,
# Haiku. The cell always shows all four, even for a model that ran zero
# agents in this batch. With a fixed order and all four each time, the row
# never moves, and a missing model shows as a zero in its fixed place. One
# line, never a <br> break. The app that shows the receipt does not render
# <br> as a line break.
MODEL_TOTALS_ORDER = (("Fable", "F"), ("Opus", "O"), ("Sonnet", "S"), ("Haiku", "H"))

# The full names that the Model cell of the verbose totals row prints in
# place of the letters. The order is the same, and all four always print.
MODEL_FULL_NAMES = {"Haiku": "Haiku 4.5", "Sonnet": "Sonnet 5",
                    "Opus": "Opus 5", "Fable": "Fable 5"}


def _model_family(item):
    """Return the measured model name of this row: Haiku, Sonnet, Opus or
    Fable. Return None when the model matches none of them. In the same way,
    model_cell shows a dash, not a guess, for an unknown model."""
    pretty = model_cell(item)
    for name, _letter in MODEL_LETTERS:
        if pretty.startswith(name):
            return name
    return None


def model_counts(entries):
    """Return the number of entries that ran on each of the four measured
    models, keyed by the plain family name: Fable, Opus, Sonnet, Haiku."""
    counts = {name: 0 for name, _letter in MODEL_TOTALS_ORDER}
    for item in entries:
        family = _model_family(item)
        if family is not None:
            counts[family] += 1
    return counts


def format_counts(counts, spelled_out):
    """Return counts, from any source, as one plain line in the order Fable,
    Opus, Sonnet, Haiku, with commas. All four print each time.

    Not a <br> tag. The app that shows the receipt does not render a br tag
    as a line break. Four lines joined by <br> then show as one run of joined
    letters. One line with commas shows correctly in all places.
    spelled_out=False prints the count with the single letter, such as 0F.
    spelled_out=True prints the full model name, such as 0 Fable 5, for the
    verbose table.
    """
    if spelled_out:
        return ", ".join("%d %s" % (counts.get(name, 0), MODEL_FULL_NAMES[name])
                         for name, _letter in MODEL_TOTALS_ORDER)
    return ", ".join("%d%s" % (counts.get(name, 0), letter)
                     for name, letter in MODEL_TOTALS_ORDER)


def model_breakdown(entries):
    """Return the count for each model in this batch as one plain line, with
    letters only."""
    return format_counts(model_counts(entries), spelled_out=False)


def model_breakdown_spawns(spawns):
    """Return the same line of model counts for the totals row of the status
    table.

    A spawn row holds the model under a different key from a receipt entry,
    and model_counts cannot read it. The count is the same, and the output
    is the same four letters in the same fixed order.
    """
    counts = {name: 0 for name, _letter in MODEL_TOTALS_ORDER}
    for row in spawns:
        family = _model_family(row)
        if family in counts:
            counts[family] += 1
    return format_counts(counts, spelled_out=False)


def model_breakdown_full(entries):
    """Return the count for each model in this batch as one plain line, with
    full names, for the totals rows of the verbose table."""
    return format_counts(model_counts(entries), spelled_out=True)


def totals_rows_default(packed):
    """Return the two rows at the bottom of the default table: a label row,
    then the sums. Each column sum has the same format as that column in an
    agent row. The sums cover only the packed rows, the rows with real
    numbers in the Characters, Pixels and Saved columns.

    The label is BATCH TOTALS, not CONVERSATION TOTALS. The sums below come
    from `packed`, the rows of this batch only, never the whole
    conversation. The sums for the whole conversation are a separate row,
    CONVERSATION TOTALS. conversation_totals_rows below adds that row when
    the totals setting allows it. The two rows answer different questions,
    and one name on the two rows makes them look the same. The totals
    setting does not control this row. It prints each time the table
    prints."""
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
    """Return the same two rows, sized to the nine columns of the verbose
    table. Dimensions holds a dash. The agent rows use the same mark for a
    value that a totals row does not have. The Model cell gives the full
    name of each model, not the letter that default uses."""
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
    """Return the BATCH TOTALS block for this batch, packed rows only. Return
    nothing when no row of this batch packed. The code builds it here, one
    time. The same two rows then go into the table wherever the receipt
    goes: to a file on disk, to the lead, or to the screen.

    The totals setting never controls it. BATCH TOTALS is part of the
    default and verbose tables, not an extra that the setting adds. Only the
    receipt mode controls whether it shows. light never gets a totals block,
    whatever the totals setting is. That mode is the compact table, and its
    purpose is to keep that form."""
    if not packed or mode == "light":
        return []
    return (totals_rows_verbose(packed) if mode == "verbose"
            else totals_rows_default(packed))


def format_stored_counts(stored, spelled_out):
    """Return the same line of model counts that format_counts prints, built
    from the counts in the totals file and not from a batch of entries.
    `stored` is totals.get("models"), a plain dict of family name to count.
    An older totals file has no such key. A missing or partial dict gives
    zero for each model that it lacks and does not raise. An old totals file
    then still prints a CONVERSATION TOTALS row. Its counts start from zero
    on the update that adds the field."""
    stored = stored or {}
    counts = {name: int(stored.get(name, 0)) for name, _letter in MODEL_TOTALS_ORDER}
    return format_counts(counts, spelled_out)


def totals_rows_conversation_default(totals):
    """Return the CONVERSATION TOTALS label row, the default header, and a
    numbers row with six cells. The rows come from the same stored totals
    that the "Conversation so far" line reads.

    The count cell reads packed_count(totals), the packed reports and briefs
    together. The Images cell reads totals["images"]. Neither cell is a new
    sum over packed entries. The count then covers the same entries as the
    Images, Characters, Pixels and token cells next to it. The "Conversation
    so far" line prints totals["reports"], which counts reports only."""
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
    """Return the same CONVERSATION TOTALS rows, sized to the nine columns of
    the verbose table, with full model names. The code needs
    totals["patch_tokens"], the running sum of the patch cost of each batch.
    It splits the Image tokens column into patches plus the handover fee,
    the same as the agent rows and the BATCH TOTALS rows. An older totals
    file without that field gives zero patches. The whole image cost then
    prints as fee until the field holds a value of its own."""
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
    """Return the CONVERSATION TOTALS block under the rule of the totals
    setting. It shows only when this batch already has a BATCH TOTALS block
    (packed rows exist and the mode is not light), and the caller already
    checked totals_shown(). It is a separate function, like run_totals_rows.
    The code then builds the two blocks the same way wherever the receipt
    goes."""
    if not packed or mode == "light":
        return []
    return (totals_rows_conversation_verbose(totals) if mode == "verbose"
            else totals_rows_conversation_default(totals))


def verbose_header(second="Model"):
    """Return the nine column names and the divider under them. The second
    column is Model on the batch table and Models on the conversation
    table."""
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
    """Return the dimension table of the images for each agent that returned
    more than one image. This is separate from verbose_table. The totals
    block can then go between the agent rows and this detail."""
    lines = []
    for item in entries:
        dims = dims_of(item)
        if len(dims) < 2:
            continue
        lines.append("")
        # No agent id here, because an internal identifier carries no
        # meaning. The agent type of the row names it in place of the id.
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
    """Return each spawn that brief_pack.py logged, across all sessions, in
    file order. The code never drains this file, and each call reads the
    whole file one time."""
    from common import sealed_rows
    return sealed_rows(tmp_dir() / "densepack-delegation.jsonl")


def manifest_entries():
    """Return each row that subagent_stop.py wrote, in file order. The code
    reads the file again on each call and keeps no cache. The delegation
    table can print at any point in a session, and an old copy shows a
    finished agent as still running."""
    from common import sealed_rows
    return sealed_rows(tmp_dir() / "densepack-manifest.jsonl")


def _finished_by_type(session):
    """Return the finished agents of this session, one row for each agent
    id, grouped by agent type, oldest start first. subagent_stop.py can
    write a provisional row for an agent that broke the delivery rule. The
    hook blocked that agent one time until it followed the rule, and then
    wrote a final row. When the two rows exist, the code uses the final row.
    When a harness does not apply the block, no final row comes. The
    provisional row is then the only row, and that agent still counts as one
    that ran."""
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


# The smallest sample for a median that the table prints. Below this, one or
# two outlier runs can move the number a lot. The cell then gives the sample
# size in place of a number that looks final.
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
    """Return each manifest row across all sessions, one for each agent id.
    When a final row and a provisional row exist for an id, the code uses
    the final row. Only the median duration baseline uses this function.
    That estimate needs the largest sample in the manifest, not the few
    finished agents of one session that _finished_by_type returns."""
    by_id = {}
    for row in manifest_entries():
        agent_id = row.get("agent_id") or ""
        current = by_id.get(agent_id)
        if current is None or (current.get("provisional")
                               and not row.get("provisional")):
            by_id[agent_id] = row
    return list(by_id.values())


def duration_medians():
    """Return the median finished duration in seconds, and its sample size,
    for each of the four measured models, such as
    {"Sonnet": (432.0, 68), ...}. A model with no finished runs in the
    manifest maps to (None, 0)."""
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
    """Return the words that the row of a running agent shows in place of a
    real duration. That is a median with its sample size when one exists.
    Otherwise it is a plain statement that the sample is too small. The code
    never builds a number from fewer than MIN_MEDIAN_RUNS finished runs. One
    or two samples do not make a median. A number from them is a guess with
    a decimal point."""
    if family is None:
        return "no estimate, model not measured"
    median, count = medians.get(family, (None, 0))
    if median is None or count < MIN_MEDIAN_RUNS:
        return "no estimate, %d runs measured" % count
    return "median %.1fm over %d runs" % (median / 60.0, count)


def _mmss(seconds):
    """Return a duration as minutes and seconds, or as seconds alone under a
    minute."""
    seconds = float(seconds)
    if seconds < 60:
        return "%.1fs" % seconds
    minutes, rest = divmod(seconds, 60)
    return "%dm %02ds" % (int(minutes), int(round(rest)))


def state_cell(duration, spawned_at=None, now=None, started=True):
    """Return the state of the agent now, in a few words.

    The cell shows Done, Running, a state with minutes such as "Silent 12m",
    or the minutes of the run so far, such as "6m". A column that prints
    "done in 19m 04s" next to "running, 6m so far" mixes time spent with
    time left. This cell gives the state or the minutes spent. The Finished
    cell gives the time taken or the time left. The two kinds of time then
    never share a cell.
    """
    # Done, or the minutes of the run so far. The State cell shows Done or a
    # number of minutes spent. The Finished cell shows the minutes that the
    # agent took, or the minutes left.
    if duration is not None:
        return "Done"
    if spawned_at is None:
        return "Running"
    quiet = (now if now is not None else time.time()) - float(spawned_at)
    if quiet >= DEAD_AFTER and not started:
        # No start marker and no finished run. SubagentStart did not run,
        # and the agent never started. Another PreToolUse hook denied the
        # call after brief_pack.py wrote this row.
        return "Spawn denied, never ran"
    if quiet >= DEAD_AFTER:
        return "No stop record %dm" % int(quiet // 60)
    if quiet >= STALE_AFTER:
        return "Silent %dm" % int(quiet // 60)
    return "%dm" % int(quiet // 60)


def left_cell(duration, spawned_at=None, now=None, family=None,
              medians=None, started=True):
    """Return the time left, or the time that the agent took.

    A finished agent shows its real time in minutes, such as "12m" or
    "under 1m". The State cell of the same row shows Done, and this time
    then never reads as a countdown. A running agent shows the median for its
    model minus the time already spent. That is the only estimate, and it is
    useful only while it is positive. After the median, the correct answer
    is that the estimate is over. The code does not create a larger number
    in its place.
    """
    # Minutes only. The column name is Finished, and a word such as "took"
    # says the same thing twice. A run under a minute shows as under 1m and
    # not as 0m. 0m looks like the agent never ran.
    if duration is not None:
        minutes = int(float(duration) // 60)
        return "%dm" % minutes if minutes else "under 1m"
    if spawned_at is None:
        return "unknown"
    quiet = (now if now is not None else time.time()) - float(spawned_at)
    if quiet >= DEAD_AFTER and not started:
        return "none"
    if quiet >= DEAD_AFTER:
        return "no stop record, check the agent"
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
    """Return the seconds that this agent still has to run. Return None when
    it is finished or when no estimate exists. The total of the table uses
    the LARGEST of these, never the sum, because agents run at the same
    time."""
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


# The longest time after PreToolUse for the matching SubagentStart. In a
# batch of eight agents spawned in one message, each gap was between 1.8 and
# 2.4 seconds, and the order was always the same. 60 seconds is 25 times the
# widest gap and still far less than the spread of that batch, 74 seconds.
# When no agent starts within this time, the spawn had no agent. The row
# stays unmatched and does not take the number of the next agent.
START_WINDOW = 60.0


def _session_agents(session):
    """Return each agent that this session spawned, oldest start first,
    finished or not.

    Each entry is (started, agent_id, manifest row or None). A row of None
    means that the agent still has a start marker on disk. It never stopped.

    With this list, delegation_table() pairs spawn rows with agents by ORDER
    OF START and not by nearest time. Nearest time fails when a batch spawns
    several agents inside the window. Eight agents spawned across 74 seconds
    with the 60 second START_WINDOW print each duration next to the wrong
    job. The order of SubagentStart matches the order of PreToolUse exactly.
    The position is then the identity that the spawn row does not hold.
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
    """Return "1 agent" or "2 agents". The code writes a count and its word
    together here. No table then shows "1 agents"."""
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


# The time of a marker and the time of its spawn row come from the same tool
# call. They are within seconds of each other. The window is wide enough for
# a slow start and far narrower than the gap between two batches.
MARKER_WINDOW = 120.0


def _unstopped_markers(session):
    """Return each start marker still on disk for this session, as
    (at, agent_id), oldest first.

    A marker exists between SubagentStart and SubagentStop. A marker still
    on disk means that the agent never stopped. The code skips read failures
    and does not raise them. This table must never stop a receipt from
    printing.
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
    """Return the Job cell, the short role of the agent.

    A custom agent type IS the role, and it prints as it is. The default
    type, general-purpose, names no role. The cell then holds a dash, and
    the lead replaces it with the role that it gave the agent. Only the lead
    has the role. This hook gets the type and the task, never the role.
    """
    if agent_type in ("general-purpose", "-", "agent", ""):
        return "-"
    return agent_type


def job_cell(job, agent_type):
    """Return a cell with the task and the agent type. No code in the plugin
    calls this function. The Job column of delegation_table() uses
    job_role(). For the default agent type, general-purpose, the cell is
    the task description alone. For any other type, it is the task followed
    by the type in brackets. A custom agent type is useful to see, and
    general-purpose on each row of the table adds nothing. The cell never
    holds the agent id. An internal identifier such as a1b2c3d4e5f6a7b8c
    carries no meaning, and the job description says what happened."""
    if agent_type in ("general-purpose", "-"):
        return job
    return "%s (%s)" % (job, agent_type)


def delegation_table(session):
    """Return the delegation table with the columns Model, Job, Report,
    State and Finished. It lists each agent that this session spawned,
    oldest first, and ends with two total rows. Model is the model family
    with a number, such as Sonnet-01. Job is job_role() of the agent type.
    Report is the description that the lead passed at spawn time. State is
    state_cell(), and Finished is left_cell().

    The row from brief_pack.py has no agent id. The subagent tool assigns no
    id before PreToolUse runs, and no id exists at spawn time. The code
    pairs the index-th spawn with the index-th agent to start, from
    _session_agents(). It accepts the pair only when the agent started
    between 5 seconds before and START_WINDOW seconds after the spawn. No
    agent id prints here, or in any other place that this table goes, even
    when an id exists.

    The Finished cell of a finished row is its real duration_s. The
    Finished cell of a running row is the median duration_s of the other
    finished agents on the same model in the manifest, minus the time
    spent. Below MIN_MEDIAN_RUNS finished runs, it gives the sample size.
    It is never a guess in the form of a number."""
    spawns = [row for row in delegation_entries()
             if str(row.get("session") or "") == str(session or "")]
    spawns.sort(key=lambda r: r.get("time") or 0)
    agents = _session_agents(session)
    medians = duration_medians()
    # A count for each model family. Two Sonnet agents show as Sonnet-01 and
    # Sonnet-02, not as two rows called Sonnet.
    numbering = {}
    # Five columns. Job is the short role that the lead gave the agent.
    # Report is the task that the lead gave it. State shows Done or the run
    # time so far. Finished shows the time it took, or the time left.
    lines = ["| Model | Job | Report | State | Finished |",
             "| --- | --- | --- | --- | --- |"]
    running = 0
    no_record = 0
    longest_left = None
    unknown_left = False
    total_seconds = 0.0
    for index, row in enumerate(spawns):
        agent_type = row.get("subagent_type") or "-"
        # The index-th spawn goes with the index-th agent to start. The code
        # accepts the match only when that agent started within START_WINDOW
        # of this spawn. A spawn row with no agent stays unmatched and does
        # not take the duration of a later agent.
        started = None
        manifest_row = None
        if index < len(agents):
            at, _agent_id, found = agents[index]
            spawn_time = row.get("time")
            if spawn_time is None or -5.0 <= at - float(spawn_time) <= START_WINDOW:
                started = at
                manifest_row = found
        # A manifest row of None means that the agent still has a start
        # marker on disk. It never stopped. It is running or dead, and it
        # must not get the finished duration of another agent.
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
    # The total row has five cells, the same as the agent rows. The Job cell
    # holds the count of spawns. The State cell holds the agent minutes
    # spent, the cost figure of this run. The Finished cell holds the
    # LARGEST remaining time, never the sum. Agents run at the same time,
    # and the run ends when the slowest agent ends.
    # An agent with no stop record is not running. The count must not treat
    # the run as waiting on it. The code counts it separately, and the count
    # of live agents stays true. The run does not wait on a dead agent, and
    # the running count above leaves it out. Its own row already says that
    # it has no stop record.
    if running == 0:
        time_left = ("none, run complete" if not no_record
                     else "check the ones with no record")
    elif unknown_left and longest_left is None:
        time_left = "%s still running, unknown" % plural(running, "agent")
    else:
        base = longest_left if longest_left is not None else 0.0
        # Each running agent is already past the median for its model. No
        # measured number is left to quote. The table never reports elapsed
        # time as time left. "about 0s to all done" next to an agent 15
        # minutes past its median says exactly that.
        if base <= 0:
            left_phrase = "past the median for its model, finish unknown"
        elif base < 60:
            left_phrase = "about %ds to all done" % int(base)
        else:
            left_phrase = "about %dm to all done" % int(round(base / 60.0))
        if unknown_left:
            left_phrase += ", one not measured"
        time_left = "%s still running, %s" % (plural(running, "agent"), left_phrase)
    # Two rows, in the same form as BATCH TOTALS on the receipt: a label row,
    # then the counts. The Job cell holds the agent count. State holds the
    # agent minutes spent. Finished holds the longest remaining time and
    # never a sum, because agents run at the same time.
    lines.append("| **STATUS TOTALS** | | | | |")
    lines.append("| %s | %s | | %s agent minutes | %s |" % (
        model_breakdown_spawns(spawns), len(spawns),
        "%.1f" % (total_seconds / 60.0), time_left))
    return lines


# The words for the case where no row in the delegation log is close enough
# in time. The words never hold the agent id, because an id carries no
# meaning. A plain statement that the task has no log row is more accurate
# than a guess.
NO_LOGGED_JOB = "an agent whose task is not in the log"


def job_for_marker(session, marker_at, window=MARKER_WINDOW):
    """Return the task description for the start marker of an agent that
    did not stop. The code matches the timestamp of the marker against the
    delegation log, the same way delegation_table pairs a spawn with its
    marker.

    A stall message or a no-stop-record message then names the task of the
    agent, not the internal agent id. A string such as a1b2c3d4e5f6a7b8c
    carries no meaning. When no row in the log is close enough in time,
    return NO_LOGGED_JOB, never the id."""
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
    """Return the totals of the whole conversation as a separate small
    table. Only session_end.py uses it, for the wrap-up summary at the start
    of the next session. That summary has no agent table to hold the
    numbers. The batch receipt in pointer.py does not call this. Its batch
    totals are in the same four (or nine) column table, from
    run_totals_rows."""
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
    """Append the "stopped-by-lead" row of the lifecycle record for the
    agent that a TaskStop tool call names. Do nothing when the call names no
    agent.

    task_id is the field that the TaskStop tool takes. shell_id is its
    deprecated alias, and the code reads it the same way. Each one is the
    same agent id that the start marker and subagent_stop.py use as the key
    of their rows. The lane tag comes from the start marker of that agent
    when the marker is still on disk. Here it is still on disk, because a
    stop from the lead never reaches subagent_stop.py, and nothing deleted
    the marker.
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


def swap_missed_as_net(item, event):
    """Return the queue row as a net row when this event is the Agent result
    of its agent and report_swap.py does not swap it. Return the row
    unchanged otherwise.

    subagent_stop.py queues a report of the swap route as a stub, with the
    hash of the agent's final message in swap_digest. report_swap.py runs on
    the same event at the same time and puts the marker line in the result
    only when common.swap_applies() is True. When it is False, the lead has
    the report as text. A stub row then gives the receipt "The stubs above
    are summaries only", which is false, and sends the lead to Read an image
    of text that it already has. As a net row, the receipt names the image
    and says that its saving applies to re-reads.

    A row that drains at another event keeps its mode. This hook cannot see
    that agent's result there. report_swap.py still sends its note at that
    agent's own result."""
    if item.get("mode") != "stub" or not item.get("swap_digest"):
        return item
    if event.get("tool_name") not in ("Agent", "Task"):
        return item
    resp = event.get("tool_response")
    if not isinstance(resp, dict) or str(resp.get("agentId") or "") != str(item.get("agent_id") or ""):
        return item
    if swap_applies(resp, item["swap_digest"]):
        return item
    return dict(item, mode="net")


def main():
    # Read the event before the switch check, because the off switch is for
    # each session and the session id is on the event. _RAW_STDIN is the
    # text that the first exit above already read. read_event() parses it
    # and does not read stdin a second time.
    event = read_event(_RAW_STDIN)
    if disabled(event.get("session_id")):
        return 0

    # A TaskStop tool call needs one thing from this hook: a lifecycle row
    # that says the lead ended this agent, not a silent stop. This runs
    # before the queue and lead-ownership checks below. A TaskStop call has
    # no report to drain and must not depend on those checks. The
    # LIFECYCLE_FILE note in common.py names the fault that this fixes.
    if event.get("tool_name") == "TaskStop":
        record_stop_by_lead(event)

    # The drop scan runs for each session, lead or subagent, before the
    # lead-only queue logic below. A subagent can copy a file into its own
    # drop folder too. The hook emits drop_line at the first return point
    # that this call reaches.
    drop_line = _draw_drop_file(*_DROP_HIT) if _DROP_HIT else None

    # The hook packs a Word file that this tool call shows here, next to the
    # drop scan. The hook adds its line to the same drop_line. With one line,
    # it reaches the agent at each return point of this call, including the
    # early return points of a subagent.
    _word_line = word_pages_from_tool(event)
    if _word_line:
        drop_line = "\n\n".join(p for p in (drop_line, _word_line) if p)

    # Only a lead session drains the queue. This hook runs in each session,
    # subagents included. A subagent that drains the queue takes the
    # pointers and receipts of the lead. bootstrap.py records each session
    # that started as a lead. With no lead on record, each session drains,
    # and the plugin still works on a harness that omits the field. When any
    # lead is on record, this check fails closed. An event with NO session
    # id must not pass. Otherwise a subagent gets the receipt and the
    # delegation table of the lead for agents that it never ran.
    # bootstrap.py runs at SessionStart, and a subagent is not a session. A
    # missing id while leads exist means that this is not a lead.
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
    # A report of the swap route whose swap missed on this Agent result
    # reached the lead as text. See swap_missed_as_net().
    entries = [swap_missed_as_net(item, event) for item in entries]

    # A subagent can spawn its own subagents. Such a report goes to that
    # subagent, never to the lead. The queue is one shared file. Without
    # this filter, the lead drains the row, counts a saving for text that it
    # never read, and holds a row that it cannot label.
    #
    # spawned_by is the session that spawned the agent, as its start marker
    # records it. A row with no spawned_by comes from a harness that omits
    # session_id. The code treats that row as a row of the lead.
    nested = [item for item in entries
              if item.get("spawned_by") and str(item["spawned_by"]) != str(sid or "")]
    entries = [item for item in entries if item not in nested]
    if not entries and not nested:
        if drop_line:
            emit(_drop_only_payload(drop_line))
        return 0

    # Briefs are on the same queue as reports. One receipt then covers the
    # whole pipeline. Each step below that gives the lead an image to
    # READ must skip them. The lead wrote each brief. A second read of its
    # own words as an image costs back the whole saving.
    brief_entries = [item for item in entries if is_brief(item)]
    report_entries = [item for item in entries if not is_brief(item)]

    packed_entries = [item for item in entries if item.get("images")]
    packed_reports = [item for item in report_entries if item.get("images")]
    # run covers the whole batch, briefs included, because the receipt table
    # adds up the whole batch. report_run covers reports only, because the
    # pointer lines above the table are about reports only.
    run = sums(packed_entries)
    report_run = sums(packed_reports)
    totals = read_totals()
    totals["reports"] = totals.get("reports", 0) + len(packed_reports)
    totals["briefs"] = totals.get("briefs", 0) + len(brief_entries)
    # Each packed entry, reports and briefs the same. The CONVERSATION TOTALS
    # count column reads this, because the Images, Characters, Pixels and two
    # token columns next to it are sums over the same entries. A count of
    # reports only, next to sums that include briefs, prints 1 next to 2.
    totals["packed"] = totals.get("packed", 0) + len(packed_entries)
    totals["text_reports"] = (totals.get("text_reports", 0)
                              + len(report_entries) - len(packed_reports))
    for key in ("images", "chars", "pixels", "text_tokens", "image_tokens",
                "patch_tokens"):
        totals[key] = totals.get(key, 0) + run[key]
    # The count for each model for the CONVERSATION TOTALS row. An older
    # totals file has no "models" key. setdefault starts it at zero for each
    # model, and the counts of this batch are the first to go in. An old
    # totals file keeps working and starts to count models from the update.
    stored_models = totals.setdefault("models", {})
    for name, count in model_counts(packed_entries).items():
        stored_models[name] = stored_models.get(name, 0) + count
    write_totals(totals)

    mode = receipts_mode()

    # Name the folder and the naming pattern one time, and do not repeat full
    # paths on each delivery.
    all_stub = all(item["mode"] == "stub" for item in packed_reports)
    if all_stub:
        # common.py builds this for the same reason as the line below it.
        # subagent_stop.py charges the receipt for this exact text. A second
        # copy here can differ from the charged text after an edit.
        head = stub_pointer(report_run["images"], tmp_dir())
    else:
        # One sentence, built in common.py, because subagent_stop.py charges
        # the receipt for exactly this text. Two copies can differ after an
        # edit, and the receipt then prices a line that the lead never got.
        head = report_pointer(report_run["images"], tmp_dir())
    if not packed_reports:
        head = ("DensePack: %d agent report(s) returned as text (%s). DensePack "
                "made no image and billed nothing to DensePack."
                % (len(report_entries),
                   "; ".join(sorted({reason_said(i) for i in report_entries}))))
    if not report_entries:
        head = ("DensePack: no agent report arrived in this batch, only "
                "outbound briefs. The receipt below is the brief saving.")
    if not entries and nested:
        head = ("DensePack: nothing in this batch was yours. Every report in "
                "it came from an agent one of your subagents spawned. "
                "There is no receipt and DensePack charged nothing to you.")
    lines = [head]
    if drop_line:
        lines.append("")
        lines.append(drop_line)
    # A report from an agent that a subagent of the lead spawned gets a name
    # but no charge. The lead never got that text. A count of its saving
    # overstates the total, and the lead cannot label a task that it never
    # gave. The name still matters. It tells the lead that findings reached
    # a subagent. The lead never gets those findings unless that subagent
    # adds them to its own report.
    if nested:
        # Numbered, never by agent id, because an internal identifier
        # carries no meaning. The number here only separates two agents of
        # the same type. It is not a key to find either one.
        lines.append(
            "  %d report(s) came from agents your subagents spawned. Their "
            "text went to those subagents, not to you. The counts below "
            "leave them out. Tell each subagent to add its own subagents' "
            "findings to its report, or you lose those findings: %s"
            % (len(nested),
               ", ".join("%s #%d" % (i.get("agent_type", "agent"), n)
                         for n, i in enumerate(nested, 1))))
    if brief_entries:
        lines.append(
            "  %d brief(s) packed at each model's own size."
            % len(brief_entries))
    for item in report_entries:
        if not item.get("images"):
            lines.append("  %s: text, %s" % (
                item["agent_type"], reason_said(item)))
            continue
        # No "captured by the net" note. The stop hook files EACH report from
        # the final message of the agent. A note here prints on each stub
        # row, and its "no summary heading" claim is usually false. The filed
        # message starts with the same text as the message of the agent,
        # most often the five line summary that the delivery rule requires.
        # The manifest still records captured for each agent for the audit
        # trail.
        lines.append("  %s: %d image(s)" % (
            item["agent_type"], len(item["images"])))
        if item.get("code"):
            lines.append("  DensePack took the code blocks out of that image. Each #=N=# "
                         "marker in it stands where block N belongs. DensePack "
                         "packed the python blocks into banded images, in order, in: "
                         + (", ".join(item.get("code_images") or [])
                            or "no page")
                         + ". Every block at full fidelity here: "
                         + item["code"])
        # Each identifier that the packer took from the image is in a
        # sidecar file, not in this text. The lead sees [#3] in the image
        # and this one line with the name of the file that resolves it. It
        # opens that file only when it needs the value. shared.txt gives the
        # same sed -n rule for the exact text file. The lift is off by
        # default.
        if item.get("legend_file"):
            # Full path, never the bare name.
            lines.append("  Tags: " + str(tmp_dir() / item["legend_file"]))

    # The code builds the table in each mode. Quiet mode writes it to a file
    # and does not print it. The lead shows that file on request.
    with_images = packed_reports
    table = []
    detail = []
    if entries:
        table = (verbose_table(entries) if mode == "verbose"
                 else default_table(entries))
        if mode == "verbose":
            detail = image_detail_lines(entries)
    # BATCH TOTALS is part of the table, not an extra that the totals
    # setting controls. It goes straight onto the end of `table` here. Each
    # place below that prints `table` prints it too, with no condition, when
    # this batch packed at least one report or brief. It is empty when
    # nothing packed, because there is nothing to total.
    table = table + run_totals_rows(packed_entries, mode)
    # CONVERSATION TOTALS is the row that the totals setting controls. It
    # holds the sums of the whole conversation, the same figures as the
    # "Conversation so far" line below. totals_shown() controls this row
    # only, never BATCH TOTALS above.
    conversation_block = (conversation_totals_rows(totals, mode, packed_entries)
                          if totals_shown() else [])
    net_seen = any(item["mode"] != "stub" for item in with_images)
    footnote = ("* returned its full text as well as the image. This row's "
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
        # The lead chooses what to do with this one line, and that is correct
        # here. Quiet mode is the setting that prints no receipt, and a hook
        # field that prints one breaks that setting. The lead loses nothing
        # when it ignores this line, because the table is on disk. The table
        # shows only on request, and the lead answers that request like any
        # other question in the conversation.
        lines.append("")
        lines.append("DensePack receipts are quiet. This batch's table is in %s . "
                     "Show that table only when the prompt asks for a "
                     "report." % receipt_file)
    elif table:
        lines.append("")
        # The hook sends the long form ONCE in each session, and each later
        # batch gets one line. In one measured lead transcript, a copy with each
        # batch put 9 report blocks at 13,271 characters and 8 outbound brief
        # blocks at 8,877. Each of those characters then stayed in the prefix
        # of each later turn. The lead already has the rule for the table,
        # and a second copy adds nothing.
        if _rule_already_sent("receipt"):
            lines.append("Print this table with the rows labeled, the same way "
                         "as the earlier one:")
        else:
            lines.append("The hook already showed this table on screen. The screen has "
                         "the numbers whatever you do. Show it again with the rows labeled, "
                         "which is the one thing this hook cannot do. The hook measures the "
                         "numbers from the source text and the PNG on disk, the two kept next "
                         "to the image for checking. Keep the rows in this order, and label "
                         "each row with the task you assigned that agent. This hook has "
                         "only the agent type, not the task. Rows "
                         "that say No images are agents whose reply stayed text. The table "
                         "lists them to show every agent, and they are not in the "
                         "run totals or the savings:")
        lines += table
        lines += detail
        if net_seen:
            lines.append("")
            lines.append(footnote)
        if conversation_block:
            lines.append("")
            lines.append("Print these two rows as their OWN table, separate from the one above. They are the totals of the whole conversation so far. "
                         "They are the same figures as the line below:")
            lines.append("")
            lines += conversation_block
        lines.append("")
        lines.append("Conversation so far: %s reports, %s images, %s tokens saved."
                     % (totals["reports"], totals["images"],
                        group(totals["text_tokens"] - totals["image_tokens"])))
    # OUTSIDE the receipt branch. Inside it, the table shows only when the
    # report of a finished agent arrives. A lead that spawned four agents
    # and answered before any of them finished then prints nothing, at the
    # exact moment when the list of running models matters most.
    delegation = delegation_table(sid)
    if len(delegation) > 3 and status_shown():
        lines.append("")
        if _rule_already_sent("delegation"):
            lines.append("Print the delegation table below too, as before:")
        else:
            lines.append("Print the delegation table below too, exactly as given: every "
                         "agent you spawned this session, oldest first. Print it "
                         "whether or not any of them finished. The Model column is "
                         "the point of it. It is the only place that shows which model "
                         "ran each agent. A subagent that should only "
                         "diagnose, plan or critique but did heavy building work instead "
                         "shows here, not later. The table lists every spawn:")
        lines += delegation

    # Nothing packed and nothing for the lead to open. A sentence that says
    # so adds its tokens to each later turn and tells the lead nothing. In
    # one session, 26 such sentences cost 3,878 tokens. The table is on disk
    # in any case.
    if not packed_entries and not nested and not (len(delegation) > 3 and status_shown()):
        if drop_line:
            emit(_drop_only_payload(drop_line))
        return 0

    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(lines),
        }
    }
    # systemMessage is the one hook field that Claude Code shows on screen
    # directly (hooks reference, JSON output table). A rule for the lead is
    # not a guarantee, and a hook field on screen is. The WHOLE table goes
    # here for that reason. The lead still gets its own copy in
    # additionalContext, because only the lead has the task of each agent
    # and can label the rows. When the lead prints that copy, the screen
    # shows a labeled table. When it does not, the screen still shows this
    # one.
    code_files = [item["code"] for item in entries if item.get("code")]
    # The code packs the python blocks into images. It does not extract them
    # as text. The line names the pages here in the order of the blocks, and
    # it still names the .txt next to them. A model that needs an exact byte
    # opens the file. A model that only needs to read the code opens the
    # page.
    code_pages = [page for item in entries
                  for page in (item.get("code_images") or [])]
    code_drawn = sum(item.get("code_drawn") or 0 for item in entries)
    code_text = sum(item.get("code_text") or 0 for item in entries)

    # Record that this turn owes a receipt. A stop hook can then hold a reply
    # that lacks one. A reminder does not make the lead relay the one column
    # that no hook can fill, the task of each agent. A gate does. Quiet mode
    # owes nothing, because that setting asks for no table.
    if table and mode != "quiet" and packed_entries:
        try:
            (tmp_dir() / "densepack-receipt-owed.json").write_text(
                json.dumps({
                    "session": str(event.get("session_id") or ""),
                    # The turn of this debt. Without it, a debt from an
                    # interrupted turn blocks the NEXT reply, which owes
                    # nothing, and wastes a turn.
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
        opening = ("DensePack receipt. The hook measured it from the source "
                   "text and the PNG on disk, the two kept beside the image.")
        plural = lambda n, word: "%s %s%s" % (group(n), word, "" if n == 1 else "s")
        closing = ("This batch: %s packed, %d%% saved, %s tokens, delivery "
                   "fee included. Conversation so far: %s, %s, %s tokens saved."
                   % (plural(len(with_images), "report"), run_pct, group(run_saved),
                      plural(totals["reports"], "report"),
                      plural(totals["images"], "image"),
                      group(totals["text_tokens"] - totals["image_tokens"])))
        # Code that the packer removed from an image is in a file, and the
        # lead gets its path. The screen shows that path only when the lead
        # prints it. This line names the path too, because the code is the
        # part of the report that the image does not hold.
        code_line = ("DensePack took the code blocks out of %s. %s packed into banded images: %s. "
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
            # Claude Code limits a hook string to 10,000 characters. It
            # replaces any longer string with a preview and a file path. On
            # a long run, that breaks the guarantee. The code cuts a receipt
            # over the limit to the numbers plus the path of the table that
            # the hook already wrote to a file. The screen still shows the
            # numbers and the path.
            short = [opening, "", closing, "",
                     "The full table for this batch is in %s ." % receipt_file]
            if code_files:
                short += ["", code_line]
            shown = "\n".join(short)
        payload["systemMessage"] = shown
    elif mode != "quiet" and [i for i in entries if i.get("reason") in BROKEN]:
        # A batch where nothing packed has no saving. It has no table to
        # show and in most cases nothing to say. Text that measures cheaper
        # means that the plugin works. It does not mean a failure. A batch
        # that failed is different. With no message here, a whole session can
        # pack nothing, and the screen never shows that Pillow was missing or
        # that the packer raised an error. One line, only on a failure.
        broken = sorted({reason_said(i) for i in entries if i.get("reason") in BROKEN})
        payload["systemMessage"] = (
            "DensePack packed nothing from this batch of %d agent report(s) "
            "and the reports arrived as plain text: %s."
            % (len(entries), "; ".join(broken)))
    emit(payload)
    return 0


def guarded_main():
    """Never let an exception leave this hook.

    With main() outside a try, a fault can change the result of the tool
    call that started the hook. The code writes the error to stderr, and
    the fault still shows. The exit code stays 0, and the call goes through.
    """
    try:
        return main()
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack %s: %s\n" % ("pointer.py", err))
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
