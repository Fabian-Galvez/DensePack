"""Packs a text file that a Read names into an image of the same words, and
picks the image that the model gets in place of the text.

HOW THIS FILE FITS. This is a PreToolUse hook on Read, for all agents, the
lead agent and each subagent. Before a Read, the gate lets the Read run on
the real file (read_runs_on_source() and the check in route()). Claude Code
then records a Read of that file, and a later Edit of it passes.
read_image.py runs on PostToolUse and PostToolUseFailure on Read. It calls
route() with post=True and replaces the Read result with the image after the
Read runs. All rules for the image stay in route().

A WORD FILE. The gate still redirects a Read of a .doc or .docx to its
images before the Read runs, because Read cannot open a Word file.

PACK AHEAD. prefetch() and a route() call with prefetch=True pack a file
before its Read. The image is then ready when the Read ends.

WHAT IT DOES. After a Read of a text file, read_image.py calls route() with
post=True. route() copies a text file with no sibling image beside it into
a staging folder and packs the copy through pointer.draw_drop_file(), the
one function in this plugin that packs a dropped file into an image.
read_image.py then replaces the Read result with that image. A .doc or
.docx is packed before the Read, because Read cannot open a Word file. The
agent does not copy the file itself and does not spend a turn on a retry.

MODEL UNKNOWN. When common.actor_reader() cannot name the model of the
agent that reads, drop_and_draw() packs for FALLBACK_READER. A gate that
cannot name a model still gives the image.

FALLBACK, when the automatic pack fails for a real reason (Pillow is
missing, the file is gone, or the pack step raised an error). Before a Read
of a .doc or .docx, the gate rejects the first Read and names the to-pack
folder to copy the file into by hand. A second, identical Read passes. That
retry runs only when the pack step failed. After the Read of any other
file, read_image.py leaves the result as text. A file that packed gives the
image on each Read, and an agent changes it with Edit and not with Write.

EXEMPTIONS. Each one is required, or the plugin blocks itself.
  A file that is already an image. The check uses the suffix of the file,
  never a densepack- name prefix. A name prefix does not show whether a file is a
  picture, because a plugin file can be text too, such as the sidecar
  densepack-bashsrc-*.txt beside each packed image.
  Any file under a scratch folder. This is a .claude folder or a path with
  "sandbox" or "scratch" in it, where working files are. The gate skips
  them. The OS temp root is not exempt. A browser unpacks a download there,
  and the working files of the plugin are all under .claude.
  The drop and image folders of the vault under densepack-vault/. The scan
  in pointer.py can then read what it copied or packed.
  A densepack- named file with NO image beside it. This is the bookkeeping
  of the plugin (settings, manifest, legend sidecar). A densepack- named
  file that DOES have an image beside it is not exempt. This is a
  source-text sidecar such as densepack-briefsrc-<stamp>.txt or
  densepack-src-<agent id>.txt. The packed image beside it,
  densepack-brief-<stamp>-1.png or densepack-img-<agent id>-1.png, already
  holds the same words. The gate gives that image through
  common.sibling_image(). That function matches the name of the file
  against the patterns that the packers write, and it checks that the image
  is on disk.
  A line pull, common.line_pull(). This is a Read of a few lines by offset
  and limit.

NEVER CRASH A CALLER. One try block covers all code. Any fault allows the
Read. All gates in this folder use the same failure mode.

NO FLOOR. A LIVE COMPARISON. This route pays no delivery fee. The Read call
happens in any case. read_image.py replaces its result, or for a Word file
route() rewrites the SAME call. The route adds no call and prints no
pointer line. The report and Bash routes pay a fee of a printed pointer
line plus a Read call per image. A fixed character floor priced for those
routes rejects the image on most files that this route gets. For this
reason there is no floor check before the pack. The gate packs the image,
prices it in real patches, prices the raw Read in text tokens at the same
CHARS_PER_TOKEN divisor that densepack.py holds, and gives the image only
when the image costs less. A file too small for an image loses the
comparison. No code fixes that point, and the point stays correct.
"""

import hashlib
import sys

from common import (BURST_BYTES, actor_key, actor_reader, line_pull,
                    burst_cap, claim_once, disabled, emit, gets_images,
                    no_metacharacters, over_cap, queue_cap_row, quoted_path,
                    read_event, sibling_image, tmp_dir, turn_reads, vault_dir)

# The largest file that a Read converts. A single line of 3 MB held the hook
# for minutes. A bigger file, or one with a null byte, stays text. There is
# no line ceiling. The code plans a file with no glyph rendered and then
# renders it once, and 20,000 short lines do not hold the hook.
#
# One ceiling for all files, for any suffix. The pack runs at about 0.15 s
# per 1,000 characters, at the same rate for a .docx as for plain text.
# 500,000 is then about 75 seconds in the worst case. The code splits a file
# longer than one page across as many pages as it needs. The ceiling only
# limits the wait. The wait comes once per file, not once per Read, because
# the code keeps the pages. A higher ceiling makes the first wait longer in
# proportion.
READ_MAX_BYTES = 500000

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf",
                  ".ipynb")

# The model that drop_and_draw() uses when common.actor_reader() cannot name
# the model of the agent that reads. Never common.resolved_reader() or
# common.UNKNOWN_READER, because the two are the cached model of the LEAD
# agent. A Read by a subagent often runs on a model other than the model of
# the lead agent.
FALLBACK_READER = "sonnet"

# One marker per session and file. A retry can then still reach the real
# bytes before an Edit. The code uses it only when drop_and_draw() below
# cannot make an image.
MARKER = "densepack-dropread-%s-%s"

MESSAGE = (
    "DensePack tried to pack this file into an image automatically and could "
    "not. This file is %s bytes. Do not Read it raw. "
    "Copy it into .claude/densepack-vault/to-pack/ instead, then "
    "make any other tool call. The scan packs it fresh from the file's "
    "current bytes, and the copy and its images move into "
    ".claude/densepack-vault/to-pack/packed/. Read that image, not this "
    "file. The drop never "
    "modifies this path. Edit it as normal once you have the "
    "information. Use the Read tool on this exact path only when you are "
    "about to Edit it. Repeat this exact Read, and it passes.\n\n"
    "File: %s"
)


def marker_path(session_id, file_path):
    digest = hashlib.sha256(
        str(file_path).replace("\\", "/").lower().encode("utf-8")
    ).hexdigest()[:12]
    return tmp_dir() / (MARKER % (str(session_id)[:8], digest))


def is_image(path):
    """True only by the suffix of the file, never by a densepack- name
    prefix. A plugin file can be text, such as the exact-text sidecar beside
    each packed image. A prefix does not show whether a file is an image."""
    return path.replace("\\", "/").lower().endswith(IMAGE_SUFFIXES)


def is_plugin_own(path):
    """True only for a densepack- named file that has NO image beside it.
    This is the bookkeeping of the plugin, never a source-text sidecar that a
    packed image already covers. See the sibling redirect in route() for that
    other case."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not name.startswith("densepack-"):
        return False
    return sibling_image(path) is None


def is_drop_folder(path):
    """True inside the drop and image folders of the vault. The scan in
    pointer.py can then read what it copied or packed."""
    parts = [p.lower() for p in path.replace("\\", "/").split("/") if p]
    # "drop", "drops" and "drop-gate" stay in the list. A file in one of
    # them still passes.
    return "densepack-vault" in parts and ("drop" in parts or "drops" in parts
                                           or "drop-gate" in parts
                                           or "to-pack" in parts
                                           or "images" in parts)


def _plugin_version():
    """The version in plugin.json beside the scripts, or an empty string."""
    import json
    from pathlib import Path
    try:
        meta = Path(__file__).resolve().parents[1] / ".claude-plugin" / "plugin.json"
        with open(meta, encoding="utf-8") as fh:
            return str(json.load(fh).get("version", ""))
    except (OSError, ValueError):
        return ""


def _source_digest(src):
    """Twelve hex characters of the source bytes and the plugin version."""
    try:
        data = src.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data + _plugin_version().encode("utf-8")).hexdigest()[:12]


def _sidecar_path(src):
    import pointer
    return vault_dir() / "images" / ("%s-images-DensePack.json"
                                     % pointer.claimed_stem(src))


def _write_sidecar(src, digest, image, more_pages, first_lines=()):
    import json
    from pathlib import Path
    names = [Path(image).name] + [Path(p).name for p in more_pages]
    rec = {"digest": digest, "source": str(src), "images": names,
           "seal": _seal(digest, names, _sidecar_path(src).parent)}
    # first_lines[i] is the first source line image i holds.
    if len(first_lines) == len(names):
        rec["first_lines"] = list(first_lines)
    # The code writes a new file and then moves it onto the name. os.replace
    # replaces a committed link at the sidecar name and does not write
    # through it.
    import os
    import tempfile
    from common import project_dir, through_link
    target = _sidecar_path(src)
    # All other writers in the images folder check this. The write below
    # replaces a link at the name, and this check rejects a linked folder
    # above it.
    if through_link(project_dir(), target.parent):
        return
    part = None
    try:
        fd, part = tempfile.mkstemp(dir=str(target.parent), prefix=".densepack-sidecar-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(rec, fh)
        from common import replace_retry
        if not replace_retry(part, target):
            Path(part).unlink(missing_ok=True)
    except OSError:
        if part:
            Path(part).unlink(missing_ok=True)


def _served_images(src):
    """The (image, patch_tokens, tags, drawn) that a new pack returns, when
    the digest of the sidecar matches this source and all images exist. None
    otherwise."""
    import json
    from pathlib import Path
    side = _sidecar_path(src)
    try:
        with open(side, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    digest = _source_digest(src)
    if not digest or rec.get("digest") != digest or not rec.get("images"):
        return None
    folder = side.parent
    # A cloned project can put a false sidecar here. A name with a folder in
    # it, or an absolute path, sends the Read outside the images folder.
    if not _bare_names(rec["images"]):
        return None
    # Anyone can compute the digest, and a false sidecar can match it. The
    # seal needs a key that the project cannot read.
    if not _sealed(rec, src):
        return None
    paths = [str(folder / n) for n in rec["images"]]
    if not all(Path(p).is_file() for p in paths):
        return None
    try:
        import densepack as dp
        from PIL import Image
        import pointer
        patch_tokens = 0
        for p in paths:
            with Image.open(p) as im:
                patch_tokens += dp.image_cost(*im.size)
    except Exception:  # noqa: BLE001
        return None
    tags = ""
    if len(paths) > 1:
        tags = pointer.later_images_note(src.name, str(folder), rec["images"],
                                         firsts=rec.get("first_lines"),
                                         last=_last_line(src))
    return paths[0], patch_tokens, tags, list(paths)


def _bare_names(names):
    """True when each entry is a plain file name that the pack wrote, with
    no folder part, no drive and no parent step."""
    import os
    return isinstance(names, list) and all(
        isinstance(n, str) and n not in ("", ".", "..")
        and os.path.basename(n) == n and "/" not in n and "\\" not in n
        and ":" not in n
        for n in names)


def _seal_key():
    """32 random bytes in the data folder of the plugin, outside the project,
    made once per machine. None when the code cannot write the folder."""
    import common
    return common.seal_key()


def _seal(digest, names, folder):
    """An HMAC over the source digest, each image name and each image's bytes.
    A cloned project cannot compute it, because it cannot read the key."""
    import hmac
    from pathlib import Path
    key = _seal_key()
    if not key or not digest or not _bare_names(names):
        return None
    mac = hmac.new(key, digest.encode("utf-8"), hashlib.sha256)
    try:
        for n in names:
            mac.update(n.encode("utf-8") + b"\0")
            mac.update(Path(folder, n).read_bytes())
    except OSError:
        return None
    return mac.hexdigest()


def _sealed(rec, src):
    """True when the sidecar holds the seal that this machine writes."""
    import hmac
    want = _seal(_source_digest(src), rec.get("images"), _sidecar_path(src).parent)
    got = rec.get("seal")
    return bool(want) and isinstance(got, str) and hmac.compare_digest(want, got)


# The line count that Read returns when a call names an offset and no limit.
READ_DEFAULT_LIMIT = 2000


def _slice_image(path, text, tool_input, event):
    """The images of only the lines that a Read with offset or limit names,
    packed with their real line numbers.

    Each line before the first named line stays empty. The pack skips an
    empty line but keeps the count, and the numbers match the file. The
    lines then go through drop_and_draw() the same as the lines of a
    whole-file Read. The result is one page, several pages joined into one
    sheet when the sheet fits, or the image-1-of-N route with the note of a
    whole-file Read. Returns (image path, note), "text" when the images cost
    no less than the lines as text, or None when the pack fails. With None,
    the whole-file route makes the decision. A page of the whole file holds
    lines that the Read did not name, and it can miss named lines that are
    on the next page."""
    import densepack as dp
    # A file that ends in a line break has no line after it. Without the
    # pop, a range past the end names one line more than the file holds.
    # The code also removes the carriage returns of a CRLF file. With them,
    # each one meets the staged line break and renders as a second break,
    # and the numbers count double.
    ends_in_break = text.endswith("\n")
    lines = [row[:-1] if row.endswith("\r") else row for row in text.split("\n")]
    if ends_in_break:
        lines.pop()
    try:
        first = max(1, int(tool_input.get("offset") or 1))
        count = int(tool_input.get("limit") or READ_DEFAULT_LIMIT)
    except (TypeError, ValueError):
        return None
    last = min(len(lines), first + count - 1)
    if first > last:
        return None
    asked = lines[first - 1:last]
    if not any(row.strip() for row in asked):
        return None
    staged = "\n" * (first - 1) + "\n".join(asked)
    # The last named line keeps its line break when the file has one there.
    # The key then does not show "no newline at end of file" for a line that
    # is not the last line of the file.
    if last < len(lines) or ends_in_break:
        staged += "\n"
    try:
        image, patch_tokens, tags, drawn = drop_and_draw(
            path, event, lines=(first, last, staged))
    except Exception:  # noqa: BLE001
        return None
    if image is None or patch_tokens is None:
        return None
    # The same price test as a whole-file Read. The test compares the pages
    # and the note against the named lines as text. Text wins a tie.
    note_tokens = round(len(tags or "") / dp.CHARS_PER_TOKEN)
    text_tokens = round(len("\n".join(asked).encode("utf-8")) / dp.CHARS_PER_TOKEN)
    if patch_tokens + note_tokens >= text_tokens:
        discard(drawn)
        return "text"
    return image, tags


def _last_line(path):
    """The number of the last line of `path`, for the image note, or None
    when the count fails. The pack of a .doc or .docx uses its paragraphs,
    not its bytes, and this function does not count its lines."""
    from pathlib import Path
    p = Path(path)
    if p.suffix.lower() in (".doc", ".docx"):
        return None
    try:
        return len(p.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return None


def _once_note(tags, event):
    """`tags` without the image note when this session and agent already
    got it for the same images.

    After the first send, the note stays in the conversation. The image
    shows the file name and each line number. A second note bills tokens and
    gives the model no new fact. The code claims the note here, where it
    sends the note, and not where it builds the note. The code deletes a
    pack that costs more than text and does not send its note."""
    import pointer
    last = pointer.LAST_NOTE
    sid = str((event or {}).get("session_id") or "")
    if not sid or not last or not tags or last[1] not in tags:
        return tags
    import hashlib
    from common import claim_once
    who = "%s|%s|%s" % (sid, (event or {}).get("agent_id") or "", last[0])
    if claim_once("note-" + hashlib.sha256(who.encode("utf-8")).hexdigest()[:32]):
        return tags
    return tags.replace(last[1], "").strip()


def _image_at_line(path, offset):
    """(image, note) for the image that holds source line `offset`, when
    that is not image 1. None otherwise. Reads the sidecar that the pack
    wrote."""
    import json
    from pathlib import Path
    import pointer
    side = _sidecar_path(Path(path))
    try:
        line = int(offset or 0)
        with open(side, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError, TypeError):
        return None
    names = rec.get("images") or []
    firsts = rec.get("first_lines") or []
    if line <= 1 or len(names) < 2 or len(firsts) != len(names):
        return None
    if not _bare_names(names) or not all(isinstance(f, int) for f in firsts):
        return None
    # The same seal that _served_images() checks. A false sidecar fails here too.
    if not _sealed(rec, Path(path)):
        return None
    k = sum(1 for first in firsts[1:] if first <= line)
    if k == 0:
        return None
    return (str(side.parent / names[k]),
            pointer.later_images_note(Path(path).name, str(side.parent), names,
                                      at=k + 1, firsts=firsts, last=_last_line(path)))


def drop_and_draw(path, event, lines=None):
    """Copy the current bytes of `path` into a staging folder and pack them
    in the SAME hook call, through pointer.draw_drop_file(), the one function
    in this plugin that packs a dropped file into an image. Returns (image
    path as a string, its real patch cost, the note that the model gets, all
    files that the pack put on disk). The note holds the later-images note
    when the file needs more than one image, and the "[#1] = <exact text>"
    rows of the legend when the pack lifted a value. Otherwise the note is
    empty. It never holds the path of the sidecar. Returns (None, None, None,
    None) when the pack fails, because the file is gone, Pillow is missing,
    or the pack step failed. route() then uses the deny message, which names
    the to-pack folder and lets the agent put the copy there.

    The code reads the patch cost from the pixels of the packed PNG, through
    densepack.image_cost(), the same formula that subagent_stop.py and
    bash_pack.py use to price an image. route() compares it against the text
    tokens of the raw Read, with no delivery fee on this side. See the "NO
    FLOOR. A LIVE COMPARISON." note above the imports.

    The model comes from common.actor_reader(), in one place for all gates.
    It checks the spawn record of this agent, then the agent-<id>.meta.json
    of Claude Code, then the transcript of this event when it is the file of
    this agent. A Read fires inside the turn of the agent that reads, and
    the event names that agent, never the cached model of the lead agent.
    FALLBACK_READER comes LAST. The code never uses the cached model of the
    lead agent and never skips the image. A gate that cannot name a model
    still gives the image.

    `lines` packs a Read of some lines in place of the whole file. It is
    (first, last, staged text). The staged text holds the named lines, and
    each line before them stays empty. The line numbers then match the file.
    The code names the images <stem>-lines-<first>-<last>. The pages go into
    one sheet or into the image-N-of-M route, the same as for a whole-file
    Read, and the note ends at `last`. A slice does not serve or write the
    sidecar of the whole file, because its images hold only the named lines.
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

    # PACKED ONCE, SERVED AGAIN. A sidecar beside the images,
    # <folder>-<file>-images-DensePack.json, records the digest of the source
    # bytes and the plugin version of the images. A Read of the same bytes
    # serves those images and packs nothing. A file read twice in one session
    # packs once, and a folder that starts with its images copied in starts
    # packed. The digest holds the plugin version. A renderer change raises
    # the version, and the code packs the file again.
    served = None if lines else _served_images(src)
    if served is not None:
        return served
    stem = pointer.claimed_stem(path)
    last_line = None
    if lines:
        stem = "%s-lines-%d-%d" % (stem, lines[0], lines[1])
        last_line = lines[1]

    # A wide burst already packs one file per hook. The child processes of
    # the renderer for the width trials then only add load, sixteen files
    # times fifteen children. A single file keeps them, because there you
    # wait on one Read.
    try:
        batch, _turn = turn_reads(event)
        if len(batch) > 2:
            import os
            os.environ["DENSEPACK_SERIAL_DRAW"] = "1"
    except Exception:  # noqa: BLE001
        pass

    # A staging folder of this gate, never the to-pack folder that the scan
    # reads. The PostToolUse scan of pointer.py, from a parallel tool call,
    # can find a copy there, pack it a second time and send the model a scan
    # line about a file it did not name.
    #
    # The folder is outside the project, in the system temp folder. A copy
    # in the project, even under the vault, is in the Grep and Glob results
    # of the model for as long as the pack runs: each match comes twice, from
    # the file and from its copy. A folder prefetch packs for a minute while
    # the model searches the same files. A .gitignore does not hide the copy
    # outside a git repository, and Glob reads no ignore file at all.
    #
    # mkdtemp makes a new folder with a random name for each pack. a/x.py
    # and b/x.py read in one turn never share a copy, and two agents that
    # read one file never delete the copy of the other. No project link can
    # sit at the folder or above it. The file keeps its name.
    import tempfile
    try:
        dest = Path(tempfile.mkdtemp(prefix="densepack-stage-")) / src.name
    except OSError:
        return None, None, None, None

    # actor_key(event) names the agent that reads this picture, or is None
    # for the lead agent. It goes only into the manifest row. The size is
    # already the size of this agent, through the model found above.
    # The code deletes the staging copy and its folder after any result of
    # the pack. A pack that raises an error or returns nothing leaves no
    # file.
    try:
        try:
            if lines:
                dest.write_text(lines[2], encoding="utf-8")
            else:
                shutil.copyfile(str(src), str(dest))
        except OSError:
            return None, None, None, None
        line, image = pointer.draw_drop_file(model, str(dest), actor_key(event),
                                             stem, source=path)
    finally:
        try:
            dest.unlink()
        except OSError:
            pass
        try:
            dest.parent.rmdir()
        except OSError:
            pass
    if image is None:
        return None, None, None, None

    # draw_drop_file() adds extra rows to line after the scan sentence.
    # "Tags: <full path>" comes when it wrote a legend sidecar, "Pages: <p2> ,
    # <p3>" when the file needed more than one page, and the
    # "[#1] copied from the file = <text>" rows of the legend under one
    # heading. The rows after the first are the note. The code never charges
    # the scan sentence to a model that ran no scan.
    #
    # The code reads the Tags row for its path and then DROPS it. The row
    # never goes into note_rows. discard() below needs the path. The model
    # must not see it, because a model that learns a value is in a file reads
    # the file. The marker rows hold the same values in this same message,
    # and the model has no file to open. note_tokens in route() charges each
    # of their characters against the picture before the code keeps the
    # picture.
    rows = line.split("\n")[1:] if line else []
    more_pages = []
    page_lines = []  # the first source line of each page, from the Lines row
    note_rows = []
    legend = None
    priced = None   # the pages that give the price, when they are not image
    for row in rows:
        if row.startswith("Pages: "):
            more_pages = [p.strip() for p in row[len("Pages: "):].split(" , ") if p.strip()]
        elif row.startswith("Tags: "):
            legend = row[len("Tags: "):].strip()
        elif row.startswith("Lines: "):
            page_lines = [int(v) for v in row[len("Lines: "):].split(" , ") if v.strip().isdigit()]
        else:
            note_rows.append(row)
    # All files that this pack put on disk. A discard below must delete the
    # full set. With page one alone, the later pages and the legend sidecar,
    # which hold the same words, stay in the vault for a Read that got no
    # image.
    drawn = [str(image)] + more_pages + ([legend] if legend else [])
    sheeted = False
    if more_pages:
        # All pages in the one Read. The stack ships only when the API keeps
        # it at its rendered size. A shrunk image loses its text.
        try:
            import densepack as dp
            all_png = str(Path(image).with_name(Path(image).stem + "-all.png"))
            # Side by side first. A 392 px page grid holds eight pages in one
            # PNG. The vertical stack holds two, and a PDF bills a flat fee of
            # about 1,577 tokens a page.
            stack = dp.composite_grid([str(image)] + more_pages, all_png)
            if stack is None:
                stack = dp.composite([str(image)] + more_pages, all_png)
        except Exception:  # noqa: BLE001
            stack = None
        if stack is not None and dp.no_downscale(stack[1], stack[2]):
            image = stack[0]
            drawn.append(str(stack[0]))
            more_pages = []
            page_lines = page_lines[:1]
        else:
            # One sheet does not fit under page.edge. The pages go into as
            # many sheets as they need, largest first. A row holds two 756 px
            # pages, and a sheet holds about four pages. The note names
            # sheets, not pages.
            try:
                pages_left = [str(image)] + more_pages
                # The size of each image comes from its file header, read
                # once. The code finds the largest grid that fits from those
                # sizes and builds only that grid. A file of 140 images then
                # opens each image once, not once for each grid it tests.
                from PIL import Image as _Image
                sizes = {}
                for p in pages_left:
                    with _Image.open(p) as im:
                        sizes[p] = im.size
                sheets = []
                opened = []  # the index of the first page on each sheet
                while pages_left:
                    take = len(pages_left)
                    made = None
                    while take > 1:
                        _per_row, grid_w, grid_h = dp.grid_size([sizes[p] for p in pages_left[:take]])
                        if dp.no_downscale(grid_w, grid_h):
                            suffix = "-all.png" if not sheets else "-all%d.png" % (len(sheets) + 1)
                            part = str(Path(image).with_name(Path(image).stem + suffix))
                            made = dp.composite_grid(pages_left[:take], part)
                            if made is not None and dp.no_downscale(made[1], made[2]):
                                break
                            made = None
                        take -= 1
                    if made is None:
                        # a page on its own always fits, because the packer made it fit
                        opened.append(len(sizes) - len(pages_left))
                        sheets.append(pages_left[0])
                        pages_left = pages_left[1:]
                    else:
                        opened.append(len(sizes) - len(pages_left))
                        sheets.append(made[0])
                        drawn.append(str(made[0]))
                        pages_left = pages_left[take:]
                if len(sheets) < 1 + len(more_pages):
                    page_lines = [page_lines[i] for i in opened] if page_lines else []
                    image = sheets[0]
                    more_pages = sheets[1:]
                    sheeted = True
            except Exception:  # noqa: BLE001
                pass
    if more_pages:
        # No PDF. A PDF page bills a flat fee that a PNG page does not, about
        # 1,591 tokens against 1,244 for the same page as a PNG. A Read also
        # needs a pages argument on a PDF of more than ten pages. The note
        # below names the pages past the sheets, and the model reads each of
        # them with its own Read. bound stays None, and the branch below does
        # not run.
        bound = None
        if bound is not None:
            # The price still comes from the PNG pages, which the PDF holds.
            # A PDF has no width and height of its own.
            priced = [str(image)] + more_pages
            image = bound
            drawn.append(bound)
            more_pages = []
    # The names and the note that the model sees. Each delivered file is
    # <folder>-<file>-image-N-of-M-DensePack.png. The note names the plugin,
    # the file, the folder once and each image, in literal words. Some models
    # read a note that tells them to read more pages, or that lists paths to
    # separate images, as a prompt injection, and they do not follow it.
    # The images of a Word file take the name of its text copy, <stem>.txt,
    # which draw_drop_file() wrote beside them. The text then has the name
    # that the key row of the image shows.
    # stem holds -lines-A-B for a line range (drop_and_draw names it that way).
    names_stem = stem
    if src.suffix.lower() in (".doc", ".docx"):
        names_stem += ".txt"
    image, more_pages, drawn = pointer.deliver_names(
        image, more_pages, drawn, names_stem, keep=priced or ())
    digest = None if lines else _source_digest(src)
    if digest:
        _write_sidecar(src, digest, image, more_pages, page_lines)
        # When the code deletes a pack below because it costs more than
        # text, it deletes the sidecar too. Otherwise the next Read serves
        # images that are gone.
        drawn.append(str(_sidecar_path(src)))
    if more_pages:
        names = [Path(image).name] + [Path(p).name for p in more_pages]
        note_rows.append(pointer.later_images_note(
            Path(path).name, str(Path(image).parent), names, firsts=page_lines,
            last=last_line or _last_line(path)))

    try:
        import densepack as dp
        from PIL import Image
        patch_tokens = 0
        for page in priced or ([str(image)] + more_pages):
            with Image.open(page) as im:
                width, height = im.size
            patch_tokens += dp.image_cost(width, height)
    except Exception:
        # A page is on disk, but the code cannot read its price. route()
        # cannot compare a pack without a price. This counts as a pack
        # failure and leads to the same deny message as a missing Pillow or
        # a missing file.
        discard(drawn)
        return None, None, None, None

    tags = "\n".join(note_rows)
    return str(image), patch_tokens, tags, drawn


def discard(drawn):
    """Delete each page and sidecar of a pack that no model reads.

    common.vault_trim() skips the drop and image folders, and
    bootstrap.prune_old_files() clears them only after a day. A page left
    here holds the words of the file in the project folder until then.
    """
    from pathlib import Path
    for name in drawn or ():
        try:
            Path(name).unlink(missing_ok=True)
        except OSError:
            continue


def is_scratch_or_temp(path):
    """True under a .claude folder or a folder with sandbox or scratch in its
    name. These hold working files, and the gate skips them. The OS temp root
    is not exempt."""
    parts = [p.lower() for p in path.replace("\\", "/").split("/") if p]
    if ".claude" in parts:
        return True
    return any("sandbox" in p or "scratch" in p for p in parts)


def capped(event, model, cap):
    """True when the batch of this turn is too wide for this model to get
    pictures. The Read then goes through as text.

    The full batch is not on disk when its first hooks run. Claude Code
    writes an assistant message one content block to a line as the reply
    streams, and it starts read-only tools while it still writes. The hooks
    that fire first read a short batch, and only the later ones read the
    full batch. A second check after the pack reads the same short batch,
    because a picture already on disk returns at once. A wait until the file
    stops growing fails on the gaps that the note in common.py records. For
    this reason the cap holds each read that starts after its batch is on
    disk, which is most of a wide batch, and up to `cap` pictures still
    reach the turn.
    """
    if cap is None:
        return False
    batch, turn_id = turn_reads(event)
    if not batch or not over_cap(batch, cap):
        return False
    if claim_once("%s-%s" % (event.get("session_id") or "", turn_id)):
        queue_cap_row(
            event, model,
            "%d reads in one turn passed the %s cap of %d files or %s bytes, "
            "and all of them stayed text"
            % (len(batch), model, cap, format(BURST_BYTES, ",")),
            sum(text_bytes(name) for name in batch))
    return True


def text_bytes(path):
    """The bytes that a raw Read of `path` returns, or 0 when the measure
    fails. Only the receipt row uses it. A missing file costs the row a
    number and costs the read nothing."""
    from pathlib import Path
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


# ONE PACK PER FILE. prompt_card.py starts a pack of the files of a folder in
# the background, and the Reads of those files by the model can arrive while
# that pack still runs. A Read of a file in a pack waits for that pack and
# gets its images. It does not pack the same file a second time. A lock older
# than DRAW_LOCK_STALE seconds comes from a pack that did not finish.
DRAW_LOCK_STALE = 300


def _draw_lock(path):
    import hashlib
    from pathlib import Path
    from common import tmp_dir
    try:
        key = str(Path(path).resolve()).lower()
    except OSError:
        key = str(path).lower()
    return tmp_dir() / ("densepack-packing-%s" % hashlib.sha256(
        key.encode("utf-8")).hexdigest()[:16])


def draw_once(path, event):
    """drop_and_draw(), with one pack of a file at a time."""
    import os
    import time
    lock = _draw_lock(path)
    held = False
    deadline = time.time() + DRAW_LOCK_STALE
    while not held:
        try:
            os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            held = True
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > DRAW_LOCK_STALE:
                    lock.unlink()
                    continue
            except OSError:
                continue
            if time.time() > deadline:
                break
            time.sleep(0.1)
        except OSError:
            break
    try:
        return drop_and_draw(path, event)
    finally:
        if held:
            try:
                lock.unlink()
            except OSError:
                pass


def prefetch_one(args):
    """route() for one file before its Read. The Read then finds its images
    already packed. One job of prefetch()."""
    event, path, n = args
    ev = dict(event)
    ev.update({"hook_event_name": "PreToolUse", "tool_name": "Read",
               "tool_input": {"file_path": path},
               "tool_use_id": "prepack-%d" % n})
    route(ev, prefetch=True)


def prefetch(event, paths):
    """Pack these files at once, split across processes, before the model
    names them in a Read. prompt_card.py calls this for the files of a folder
    that the message names. Each Read then serves images already on disk and
    does not pack its own file while the model waits. The function skips a
    file that the Read keeps as text, and it skips a batch past
    BURST_BYTES."""
    import os
    from common import BURST_BYTES
    jobs = []
    total = 0
    for n, path in enumerate(paths):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if 1000 <= size <= READ_MAX_BYTES:
            jobs.append((event, str(path), n))
            total += size
    if not jobs or total > BURST_BYTES:
        return
    workers = min(len(jobs), os.cpu_count() or 1)
    if workers < 2:
        for job in jobs:
            prefetch_one(job)
        return
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=workers) as pool:
        list(pool.map(prefetch_one, jobs))


# READ-BEFORE-EDIT. Claude Code lets Edit change a file only after a Read of
# that same file. A Read that this gate sends to the image is a Read of the
# PNG, and Claude Code then rejects an Edit of the source. For this reason a
# Read that Claude Code can run on the real file runs on it. read_image.py
# then replaces its result with the image, in the same result. The Read on
# the real file costs nothing, because the API bills only what reaches the
# model. This gate still redirects a .doc or .docx, because Read rejects a
# Word file.
def read_runs_on_source(path):
    """True when the Read runs on the real file and read_image.py replaces
    its result after the Read."""
    from pathlib import Path
    return Path(path).suffix.lower() not in (".doc", ".docx")


def _drawable_text(path):
    """(size, `drawn_text`, text) for a file whose words a whole-file Read
    packs, or None when the Read keeps it as text. The Read keeps a file as
    text when it is under 1 KB, over READ_MAX_BYTES, binary, in a script the
    font cannot render, or holds the line marks of the renderer. The size of
    a .doc or .docx comes from the words it holds, which are `drawn_text`.
    route() and draws_on_read() call it, and a Read and a Grep get the same
    answer."""
    from pathlib import Path
    try:
        size = Path(path).stat().st_size
    except OSError:
        return None
    # A .docx is a zip of XML. Its size and its bytes do not show what a
    # Read delivers. The container is mostly styles and parts, and it holds
    # the nulls that the check below rejects. The code first gets the
    # paragraphs and measures them, the same text that pointer.py packs.
    # A .docx that does not open as a zip is not a Word file. Most often it
    # is a renamed text file. It goes to the plain text route below, because
    # Read rejects the suffix in any case. Without this route, a readable
    # file becomes unreadable.
    drawn_text = None
    suffix = Path(path).suffix.lower()
    if suffix in (".docx", ".doc"):
        import pointer
        drawn_text = (pointer.docx_text(path) if suffix == ".docx"
                      else pointer.doc_text(path)) or None
        if drawn_text:
            size = len(drawn_text.encode("utf-8"))
    # A file under 1 KB passes as text. The pack of a 483 byte file took
    # 2.5 s and 469 MB to save 10 tokens.
    if size < 1000:
        return None
    if size > READ_MAX_BYTES:
        return None
    if drawn_text is None:
        try:
            raw = Path(path).read_bytes()
        except OSError:
            return None
        if b"\x00" in raw:
            return None
    # A file that the font cannot render, such as Chinese, Japanese or Korean
    # text, becomes empty boxes that no model can read. It stays text.
    # freetype_glyph and style load in a fraction of the time of codepack and
    # need no NumPy. A Read that the saved images serve does not pay the load
    # time of codepack.
    import freetype_glyph
    import style
    font = (style.load().get("font.regular") or [""])[0]
    text = (drawn_text if drawn_text is not None
            else raw.decode("utf-8", "replace"))
    if not freetype_glyph.font_covers(text, font):
        return None
    # The line marks of the renderer are U+E000 to U+E003, and the renderer
    # rejects a source that holds one. Such a file stays text and gets no
    # deny.
    if any(mark in text for mark in "\ue000\ue001\ue002\ue003"):
        return None
    return size, drawn_text, text


def draws_on_read(path, event):
    """True when a whole-file Read of `path` returns an image.

    The same checks that route() makes before it packs, in the same order.
    The file is not an image and not a file of the plugin, the model gets
    images, the folder is not a to-pack, vault or scratch folder, and
    _drawable_text() passes. The function skips the pack and its price test,
    because a check must not pack. It also skips the burst cap, because the
    cap counts the Reads of this turn, and a Grep is not a Read.
    grep_gate.py calls it before it lets a Grep return a whole file as text.
    A .doc or .docx returns False, because a Grep reads its zip bytes, never
    its words, and the Grep does not bypass the image. Never raises."""
    try:
        from pathlib import Path
        if is_image(path) or is_plugin_own(path):
            return False
        if Path(path).suffix.lower() in (".doc", ".docx"):
            return False
        if not gets_images(event):
            return False
        if is_drop_folder(path) or is_scratch_or_temp(path):
            return False
        if _drawable_text(path) is None:
            return False
        from common import ensure_pillow
        return bool(ensure_pillow())
    except Exception:  # noqa: BLE001
        return False


def route(event, prefetch=False, post=False):
    """The answer of this gate to a Read event. Returns the hook output to
    emit, or None to let the Read run as written. prefetch is a pack before
    the Read, from prefetch(), which prompt_card.py starts. It packs and
    seals the images that the Read gets, and it never rejects the Read. post
    is the call from read_image.py after the Read ran. That call gets the
    image that replaces the result. Never raises."""
    try:
        if disabled(event.get("session_id")):
            return None

        if (event.get("tool_name") or "") != "Read":
            return None

        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            return None
        path = tool_input.get("file_path")
        if not isinstance(path, str) or not path:
            return None
        # THE LINE PULL, common.line_pull(). A Read of a few lines by their
        # green number passes before the sibling redirect below. A pull from
        # a sidecar then returns text and never the image again.
        if line_pull(tool_input):
            return None

        if is_image(path):
            return None
        if is_plugin_own(path):
            return None
        # Before the Read, let it run on the real file. Claude Code then
        # allows a later Edit. read_image.py gives the image after the Read
        # runs. A prefetch still packs ahead, and the image is ready when the
        # Read ends. A .doc or .docx continues below, because Read cannot
        # open a Word file.
        if not post and not prefetch and read_runs_on_source(path):
            return None

        # IMAGES ONLY TO MEASURED MODELS. The two routes below give this
        # actor a packed image, the sibling redirect right after this check
        # and drop_and_draw() further down. An agent on a model that no bench
        # scored on a condensed image, or on a model with no name, must get
        # the raw text. A return of None here does that. An unscored model
        # misreads facts from an image.
        #
        # This check is about the ACTOR, never the file. Sonnet gets images,
        # and a Haiku lead agent gets text.
        if not gets_images(event):
            return None

        # Sealed. A redirect gives the model the image in place of the text.
        # The code replaces only a pair that the plugin on this machine wrote.
        from common import pack_images, sealed_sibling_image
        image = sealed_sibling_image(path)
        if image is not None:
            tool_input["file_path"] = image
            answer = {"hookEventName": "PreToolUse", "updatedInput": tool_input}
            # A long output is several images. Without the note, a model reads
            # image 1 as the full output.
            names = pack_images(path)
            if len(names) > 1:
                # _Path, because route() binds Path further down, and a bare
                # Path here is an unbound local. The branch then raises, the
                # catch-all hides the error, and the Read returns raw text.
                from pathlib import Path as _Path
                import pointer
                note = pointer.later_images_note(
                    _Path(path).name, str(_Path(image).parent),
                    [_Path(n).name for n in names])
                answer["additionalContext"] = (note if prefetch
                                               else _once_note(note, event))
            return {"hookSpecificOutput": answer}
        if is_drop_folder(path):
            return None
        if is_scratch_or_temp(path):
            return None
        # A Read of more than LINE_PULL_MAX lines is a whole read and is not
        # exempt. Otherwise a model can read a file as text in a few wide
        # slices. The pull of a few lines passes at the top of route(),
        # through common.line_pull().

        # THE PICTURE CAP. A model whose profile holds a measured cap,
        # common.BURST_CAPS and common.BURST_BYTES, gets pictures only for a
        # turn inside that cap and reads a wider turn fully as text. The test
        # uses the full batch of the assistant message, not this Read alone.
        # Each hook in the batch then reads the same answer from the same
        # transcript, and the code needs no counter file. A very wide Sonnet turn
        # of pictures saves input tokens but costs more in output than it
        # saves. Only sonnet has a cap for this reason.
        model = actor_reader(event) or FALLBACK_READER
        cap = burst_cap(model)
        if capped(event, model, cap):
            return None

        from pathlib import Path
        drawable = _drawable_text(path)
        if drawable is None:
            return None
        size, drawn_text, text = drawable

        # NO FLOOR HERE. See the module note above the imports. This route
        # pays no delivery fee, and no fixed character count marks where the
        # pack loses. stub_chars() gives a price for the other routes.
        # drop_and_draw() always tries the pack. The comparison right below
        # it sets the result from the measured price of this file, the same
        # as the check in subagent_stop.py, which has no floor of its own.
        # Without freetype-py or NumPy the renderer uses Pillow and makes a
        # different, harder image. The file then stays text.
        from common import ensure_pillow
        if not ensure_pillow():
            return None
        # A Read of some lines gets a picture of those lines alone, or the
        # lines as text when that costs less. See _slice_image().
        if drawn_text is None and (tool_input.get("offset") or tool_input.get("limit")):
            sliced = _slice_image(path, text, tool_input, event)
            if sliced == "text":
                return None
            if sliced is not None:
                tool_input["file_path"], tags = sliced
                answer = {"hookEventName": "PreToolUse",
                          "updatedInput": tool_input}
                if tags and not prefetch:
                    tags = _once_note(tags, event)
                    if tags:
                        answer["additionalContext"] = tags
                return {"hookSpecificOutput": answer}
        image, patch_tokens, tags, drawn = draw_once(path, event)
        if image is not None:
            import densepack as dp
            text_tokens = round(size / dp.CHARS_PER_TOKEN)
            # The note ships in the same message as the picture, and it is
            # part of the cost of the picture. A file whose note costs more
            # than its text loses the comparison, and the model reads it as
            # text. This is the full guarantee, per file, on the measure of
            # that file. No floor and no cap. The count sets the result.
            note_tokens = round(len(tags or "") / dp.CHARS_PER_TOKEN)
            if patch_tokens is not None and patch_tokens + note_tokens >= text_tokens:
                # Measured cheaper as text. The fee of this route is zero.
                # The comparison is the real patches of the image against the
                # text tokens of the raw Read, with nothing added on either
                # side. The code deletes the picture, and the Read runs
                # exactly as written.
                # All pages and the legend sidecar go with it, not page one
                # only, because they hold the same words.
                discard(drawn)
                return None
            # A Read that starts past image 1 gets the image that holds its
            # first line. A Read of lines 400 to 460 then does not get lines
            # 1 to 318 again.
            at = _image_at_line(path, tool_input.get("offset"))
            if at is not None:
                image, tags = at
            tool_input["file_path"] = image
            # tags holds the exact text of each id, hash and long number that
            # draw_drop_file() lifted, in this same message. A model then
            # quotes a value and does not read it from pixels or open a file.
            # Empty when the file held nothing to lift and fitted one image.
            answer = {
                "hookEventName": "PreToolUse",
                "updatedInput": tool_input,
            }
            # One line that states what arrived, and no instruction to the
            # model. A line that tells the model to answer from the picture,
            # or that a doubtful value is one Read away, makes the model check
            # values it read correctly, and each check costs a turn. The
            # redirect holds the marker rows and the image note, when there
            # are any, and no path to any file.
            if tags and not prefetch:
                tags = _once_note(tags, event)
            if tags:
                answer["additionalContext"] = tags
            return {"hookSpecificOutput": answer}

        sid = str(event.get("session_id") or "")
        if not sid or prefetch:
            return None

        marker = marker_path(sid, path)
        if marker.exists():
            return None
        # The code writes the marker before it sends the deny. A fault after
        # this line lets the Read through with the marker already on disk.
        # The only effect is that this file gets no redirect. The reverse
        # order can deny the same file forever.
        # The code moves the marker onto the name, and a false link at the
        # name gets no write.
        from common import write_text_atomic
        if not write_text_atomic(marker, "1"):
            return None

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                # The project names its own files. No character that acts
                # inside a double-quoted word reaches this message, and a path
                # with brackets or spaces still names the real file.
                "permissionDecisionReason": MESSAGE % (
                    format(size, ","), quoted_path(path)),
            }
        }
    except Exception:  # noqa: BLE001
        return None


def main():
    # NEVER CRASH A CALLER. This runs before each Read in each session.
    try:
        out = route(read_event())
        if out:
            emit(out)
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
