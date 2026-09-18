"""Stops a raw Read of a text file worth packing, and redirects it to a
drawn image of the same words instead.

HOW THIS FILE FITS, in plain words: this is a PreToolUse hook on Read, for
every agent, lead and subagent alike. It draws the file the agent asked
for and hands it the image.

WHAT IT DOES. A Read of a text file with no sibling image already sitting
beside it (see sibling_image() in common.py for the file that does have
one) is copied into a staging folder and drawn immediately, in the SAME
hook turn, through pointer.draw_drop_file(): the one place this plugin
turns a dropped file into an image. The Read is then rewritten to that
image, exactly like the sibling-image redirect, so the agent never copies
the file itself and never spends a retry turn waiting.

READING AGENT'S MODEL UNKNOWN. When common.actor_reader() cannot name the
reading agent's model, drop_and_draw() draws for FALLBACK_READER instead.
A gate that cannot decide a reader still redirects.

FALLBACK, when the automatic draw fails for a real reason (Pillow
missing, the file vanished, or the draw itself raised): the first Read is
denied instead, naming the to-draw folder to copy the file into by hand. A
retry of the identical Read passes, so an agent about to Edit the file
still gets the real bytes on its second try. That retry runs only when
the draw itself failed; a file that drew gives the image on every Read,
and an agent changes it with Edit and not with Write.

EXEMPTIONS, each one required or the plugin deadlocks on itself.
  A file already an image: checked by its own suffix. Never by a
  densepack- name prefix; a name prefix is the wrong key for whether a
  file is a picture, because a plugin file can be text too, the exact
  sidecar densepack-bashsrc-*.txt beside every packed image.
  Anything under a scratchpad: a .claude folder or a path holding
  "sandbox" or "scratch", where a working file lives and is never worth
  a gate. The OS temp root is not exempt: a browser unpacks a download
  there, and the plugin's own working files all sit under .claude.
  The vault's own drop and image folders under densepack-vault/, so
  pointer.py's own scan can still read what it just copied or just drew.
  A densepack- named file with NO image beside it, the plugin's own
  bookkeeping (settings, manifest, legend sidecar). A densepack- named
  file that DOES have an
  image beside it, a source-text sidecar such as
  densepack-briefsrc-<stamp>.txt or densepack-src-<agent id>.txt, is not
  exempt: the drawn image right beside it, densepack-brief-<stamp>-1.png
  or densepack-img-<agent id>-1.png, already holds the same words. The
  Read is redirected to that image instead, through
  common.sibling_image(), which matches the file's own name against the
  patterns the packers write and checks the image is really on disk
  before redirecting to it.
  A line pull, common.line_pull(): a Read of a few lines by offset and
  limit.

NEVER CRASH A CALLER. One try around everything; any fault allows the
Read, the same failure mode every gate in this folder chooses.

NO FLOOR, A LIVE COMPARISON INSTEAD. This route pays no delivery fee: the
Read call was already going to happen (drop_and_draw() rewrites the SAME
call, it never adds one) and no pointer line is printed, the redirect
happens inside this one PreToolUse turn. A fixed character floor priced
for the report and Bash routes, whose fee is a printed pointer line plus
a Read call per image, would refuse a redirect on most of what this route
sees. So there is no floor pre-check: draw the image, price it in real
patches, price the raw Read in text tokens at the same CHARS_PER_TOKEN
divisor densepack.py holds, and redirect only when the image is actually
cheaper. A file too small to redirect self-selects out of the comparison;
nothing hardcodes where that point is, so it never goes stale.
"""

import hashlib
import sys

from common import (BURST_BYTES, actor_key, actor_reader, line_pull,
                    burst_cap, claim_once, disabled, emit, gets_images,
                    no_metacharacters, over_cap, queue_cap_row, quoted_path,
                    read_event, sibling_image, tmp_dir, turn_reads, vault_dir)

# The largest file a Read converts. A 230 KB file of 20,000 short lines and a
# 3 MB single line each held the hook for minutes, so a bigger file, or one
# holding a null byte, stays text. The largest bench sample file is 95 KB and
# 1,934 lines, and codepack.py at 196 KB and 4,070 lines converts in seconds.
#
# One ceiling, every file, whatever the suffix. Drawing runs at about 0.15 s
# per 1,000 characters, measured 17 September 2026 and the same rate for a
# .docx as for plain text, so 500,000 is roughly 75 seconds in the worst case.
# A file longer than one page is split across as many pages as it needs, so
# the ceiling buys a bounded wait and nothing else. The wait is paid once per
# file, not once per Read, because the pages are kept. Raise it and a reader
# waits proportionally longer the first time.
READ_MAX_BYTES = 500000
READ_MAX_LINES = 6000

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf",
                  ".ipynb")

# The reader drop_and_draw() falls back to when common.actor_reader() cannot
# name the reading agent's model. Never common.resolved_reader() or
# common.UNKNOWN_READER, both the LEAD's own cached reader: a subagent's Read
# is as often not the lead's model as it is.
FALLBACK_READER = "sonnet"

# One marker per session and file, so a retry can still reach the real
# bytes before an Edit. Only reached now when
# drop_and_draw() below could not draw an image at all.
MARKER = "densepack-dropread-%s-%s"

MESSAGE = (
    "DensePack tried to draw this file as an image automatically and could "
    "not. This file is %s bytes. Do not Read it raw. "
    "Copy it into .claude/densepack-vault/to-draw/ instead, then "
    "make any other tool call: the scan draws it fresh from the file's "
    "current bytes, the image lands in .claude/densepack-vault/images/, and "
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
    """True inside the vault's drop and image folders, so the scan in
    pointer.py can still read what it just copied or just drew."""
    parts = [p.lower() for p in path.replace("\\", "/").split("/") if p]
    # "drop", "drops" and "drop-gate" stay in the list so a file left in one
    # of them still passes.
    return "densepack-vault" in parts and ("drop" in parts or "drops" in parts
                                           or "drop-gate" in parts
                                           or "to-draw" in parts
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
    # A new file of its own, then moved onto the name. os.replace replaces a
    # committed link at the sidecar name instead of writing through it.
    import os
    import tempfile
    from common import project_dir, through_link
    target = _sidecar_path(src)
    # Every other writer in the images folder checks this. The write below
    # replaces a link at the name, and this refuses a linked folder above it.
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
    """The (image, patch_tokens, tags, drawn) a fresh draw would return,
    when the sidecar's digest matches this source and every image exists;
    None otherwise."""
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
    # A cloned project can plant this sidecar. A name with a folder in it,
    # or an absolute path, would send the Read outside the images folder.
    if not _bare_names(rec["images"]):
        return None
    # The digest alone is public arithmetic, so a planted sidecar can match
    # it. The seal needs a key the project cannot read.
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
        tags = pointer.later_images_note(src.name, str(folder), rec["images"])
    return paths[0], patch_tokens, tags, list(paths)


def _bare_names(names):
    """True when every entry is a plain file name the draw itself wrote:
    no folder part, no drive and no parent step."""
    import os
    return isinstance(names, list) and all(
        isinstance(n, str) and n not in ("", ".", "..")
        and os.path.basename(n) == n and "/" not in n and "\\" not in n
        and ":" not in n
        for n in names)


def _seal_key():
    """32 random bytes kept in the plugin's data folder, outside the project,
    made once per machine. None when the folder cannot be written."""
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
    """True when the sidecar carries the seal this machine would write."""
    import hmac
    want = _seal(_source_digest(src), rec.get("images"), _sidecar_path(src).parent)
    got = rec.get("seal")
    return bool(want) and isinstance(got, str) and hmac.compare_digest(want, got)


def _image_at_line(path, offset):
    """(image, note) for the image that holds source line `offset`, when
    that is not image 1; None otherwise. Reads the sidecar the draw wrote."""
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
    # The same seal _served_images() checks, so a planted sidecar is refused here too.
    if not _sealed(rec, Path(path)):
        return None
    k = sum(1 for first in firsts[1:] if first <= line)
    if k == 0:
        return None
    return (str(side.parent / names[k]),
            pointer.later_images_note(Path(path).name, str(side.parent), names, at=k + 1))


def drop_and_draw(path, event):
    """Copy `path`'s current bytes into a staging folder and draw them in
    the SAME hook turn, through pointer.draw_drop_file(), the one place this
    plugin turns a dropped file into an image. Returns (image path as a
    string, its real patch cost, the note the reader receives, every file
    the draw put on disk). The note holds the later-images note when the
    file needed more than one image, and the legend's own "[#1] = <exact
    text>" rows when anything was lifted; it is empty otherwise and never
    holds the sidecar's path. Returns (None, None, None, None) when nothing
    could be drawn: the file vanished, Pillow is missing, or the draw itself
    failed; main() then falls back to the deny-and-instruct message, which
    names the to-draw folder and lets the agent place the copy itself.

    The patch cost is read back off the drawn PNG's own pixels, through
    densepack.image_cost(), the identical formula subagent_stop.py and
    bash_pack.py price an image with. main() compares it against the raw
    Read's text tokens, with no delivery fee added on this side: see the
    "NO FLOOR, A LIVE COMPARISON INSTEAD" note above the imports.

    The reader comes from common.actor_reader(), in one place for every
    gate: this agent's own spawn record, then Claude Code's own
    agent-<id>.meta.json, then this event's transcript when it is this
    agent's own file. A Read fires from inside the reading agent's own
    turn, so the event names that agent, never the lead's cached model.
    FALLBACK_READER is tried LAST, never the lead's own cached reader and
    never a skipped redirect: a gate that cannot decide a reader still
    redirects.
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

    # DRAWN ONCE, SERVED AGAIN. A sidecar beside the images,
    # <folder>-<file>-images-DensePack.json, records the digest of the source
    # bytes and the plugin version the images were drawn under. A Read of
    # the same bytes serves those images and draws nothing, so a file read
    # twice in one session draws once, and a folder that starts with its
    # images copied in starts drawn. The plugin version is in the digest so
    # a renderer change, which bumps the version, redraws.
    served = _served_images(src)
    if served is not None:
        return served

    # A wide burst draws one file a hook already, so the renderer's own
    # child processes for the widening trials would only pile up: sixteen
    # files times fifteen children. One file at a time keeps them, because
    # that is where a person waits on one Read.
    try:
        batch, _turn = turn_reads(event)
        if len(batch) > 2:
            import os
            os.environ["DENSEPACK_SERIAL_DRAW"] = "1"
    except Exception:  # noqa: BLE001
        pass

    # A staging folder of this gate's own, never the scanned to-draw folder:
    # pointer.py's PostToolUse scan, fired by a parallel tool call, would find
    # a copy there, draw it a second time and send the reader a scan line
    # about a file it never asked for. The scan does not walk drop-gate/, so
    # a copy here is invisible to it.
    from common import project_dir, through_link
    drop_dir = vault_dir() / "drop-gate"
    try:
        drop_dir.mkdir(parents=True, exist_ok=True)
        # One subfolder per source path, so a/x.py and b/x.py read in one turn
        # never share a copy and never mix pages. The file keeps its own name.
        import os
        # The process id too: two agents reading one file at once each delete
        # their copy when done, and a shared copy was deleted mid-conversion.
        dest = drop_dir / (hashlib.sha256(
            os.path.normcase(os.path.abspath(str(src))).encode("utf-8")).hexdigest()[:12]
            + "-%d" % os.getpid()) / src.name
        # A link at drop-gate, at the per-path folder, or at any folder above
        # would carry the copy to a file outside the project. through_link()
        # walks every folder from the per-path one up to the project, so the
        # check runs before mkdir can follow a planted link and again after.
        if through_link(project_dir(), dest.parent):
            return None, None, None, None
        dest.parent.mkdir(exist_ok=True)
        if through_link(project_dir(), dest.parent):
            return None, None, None, None
        # Any link at the name itself, not a symlink alone: a second hard
        # link is a real directory entry and takes the copy into the file it
        # shares. The folder name is a hash of the source path, which a
        # project can work out, so the name is guessable.
        from common import clear_link
        clear_link(dest)
        shutil.copyfile(str(src), str(dest))
    except OSError:
        return None, None, None, None

    # actor_key(event) names the agent that will read this picture, or is
    # None for the lead. It only reaches the manifest row; the size is
    # already this agent's own, through the model resolved above.
    # The staging copy and its per-path folder go whatever the draw does:
    # a draw that raises or returns nothing leaves nothing behind.
    try:
        line, image = pointer.draw_drop_file(model, str(dest), actor_key(event),
                                             pointer.claimed_stem(path))
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

    # draw_drop_file() appends extra rows to line after the scan sentence:
    # "Tags: <full path>" when it wrote a legend sidecar, "Pages: <p2> ,
    # <p3>" when the file needed more than one page, and the legend's own
    # "[#1] copied from the file = <text>" rows under one heading. The rows
    # after the first are the note; the scan sentence is never charged to a
    # reader that ran no scan.
    #
    # The Tags row is read for its path and then THROWN AWAY, never put in
    # note_rows. discard() below needs the path; the reader must not see it,
    # because a model told a value sits in a file reads the file. The marker
    # rows carry the same values in this same message, so there is nothing
    # left to open, and note_tokens in main() charges every one of their
    # characters against the picture before the picture is kept.
    rows = line.split("\n")[1:] if line else []
    more_pages = []
    page_lines = []  # the first source line of every page, from the Lines row
    note_rows = []
    legend = None
    priced = None   # the pages the price is read from, when it is not image
    for row in rows:
        if row.startswith("Pages: "):
            more_pages = [p.strip() for p in row[len("Pages: "):].split(" , ") if p.strip()]
        elif row.startswith("Tags: "):
            legend = row[len("Tags: "):].strip()
        elif row.startswith("Lines: "):
            page_lines = [int(v) for v in row[len("Lines: "):].split(" , ") if v.strip().isdigit()]
        else:
            note_rows.append(row)
    # Every file this draw put on disk. A discard below must take the whole
    # set: page one alone would leave later pages and the legend sidecar,
    # which hold the same words, sitting in the vault for a Read that was
    # never redirected.
    drawn = [str(image)] + more_pages + ([legend] if legend else [])
    sheeted = False
    if more_pages:
        # Every page in the one Read. The stack ships only when the API would
        # leave it at the size it was drawn; a shrunk image loses the text it
        # carries.
        try:
            import densepack as dp
            all_png = str(Path(image).with_name(Path(image).stem + "-all.png"))
            # Side by side first: a 392 px page grid holds eight pages in one
            # PNG, where the vertical stack holds two and a PDF bills about
            # 1,577 tokens a page flat.
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
            # One sheet did not fit under page.edge, so the pages go into as
            # many sheets as it takes, largest first. A 756 px page sits two
            # to a row, so a sheet holds about four pages, and the note names
            # sheets, not pages.
            try:
                pages_left = [str(image)] + more_pages
                # Each image's size comes from its file header, read once.
                # The largest grid that fits is found from those sizes, and
                # only that grid is built, so a file of 140 images opens each
                # image once instead of once for every grid tried.
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
                        # a page on its own always fits, the packer drew it to
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
        # No PDF: a PDF page bills a flat fee that a PNG page does not, about
        # 1,591 tokens against 1,244 for the same page as a PNG, and a Read
        # asks for a pages argument on a PDF of more than ten pages. Pages
        # past what the sheets hold ride as the note below and cost the
        # reader its own Reads. bound stays None, so the branch below is not
        # taken.
        bound = None
        if bound is not None:
            # The price is still read off the PNG pages, which is what the
            # PDF carries; a PDF has no width and height of its own.
            priced = [str(image)] + more_pages
            image = bound
            drawn.append(bound)
            more_pages = []
    # The reader facing names and the note: every delivered file is
    # <folder>-<file>-image-N-of-M-DensePack.png, and the note names the
    # plugin, the file, the folder once and every image, in literal words. A
    # note that tells a reader to read more pages, or that lists paths to
    # separate images, reads to some readers as a prompt injection and is
    # not followed.
    image, more_pages, drawn = pointer.deliver_names(
        image, more_pages, drawn, pointer.claimed_stem(path), keep=priced or ())
    digest = _source_digest(src)
    if digest:
        _write_sidecar(src, digest, image, more_pages, page_lines)
        # A draw thrown away below for costing more than text takes its
        # sidecar with it, or the next Read serves images that are gone.
        drawn.append(str(_sidecar_path(src)))
    if more_pages:
        names = [Path(image).name] + [Path(p).name for p in more_pages]
        note_rows.append(pointer.later_images_note(
            Path(path).name, str(Path(image).parent), names))

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

    common.vault_trim() skips the drop and image folders, and
    bootstrap.prune_old_files() clears them only after a day, so a page left
    here holds the file's own words in the project folder until then.
    """
    from pathlib import Path
    for name in drawn or ():
        try:
            Path(name).unlink(missing_ok=True)
        except OSError:
            continue


def is_scratch_or_temp(path):
    """True under a .claude folder or a sandbox or scratch named folder:
    working files, never worth a gate. The OS temp root is not exempt."""
    parts = [p.lower() for p in path.replace("\\", "/").split("/") if p]
    if ".claude" in parts:
        return True
    return any("sandbox" in p or "scratch" in p for p in parts)


def capped(event, model, cap):
    """True when this turn's batch is too wide for this reader to be handed
    pictures, so the Read goes through as text.

    The batch is not all on disk when the first hooks of it run. Claude Code
    writes an assistant message one content block to a line as the reply
    streams, and it starts read-only tools while it is still writing, so the
    hooks that fire first see a short batch and only the later ones see the
    whole one. A second look after the drawing sees the same short batch,
    because a picture already on disk is returned at once, and waiting for
    the file to stop growing fails on the gaps the note in common.py records.
    So the cap holds every read that starts after its batch has landed,
    which is most of a wide one, and up to `cap` pictures still reach the
    turn.
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
        # here does: an unscored reader misreads facts from an image.
        #
        # This asks about the ACTOR, never the file. Sonnet gets images
        # images, and a Haiku lead gets text.
        if not gets_images(event):
            return 0

        # Sealed: a redirect hands the reader the image in place of the text,
        # so only a pair this machine's plugin wrote is swapped.
        from common import pack_images, sealed_sibling_image
        image = sealed_sibling_image(path)
        if image is not None:
            tool_input["file_path"] = image
            answer = {"hookEventName": "PreToolUse", "updatedInput": tool_input}
            # A long output is several images, and image 1 alone would read
            # as the whole of it.
            names = pack_images(path)
            if len(names) > 1:
                # _Path, because main() binds Path further down and a bare
                # Path here is an unbound local: the branch raised, the
                # catch-all swallowed it, and the Read went out as raw text.
                from pathlib import Path as _Path
                import pointer
                answer["additionalContext"] = pointer.later_images_note(
                    _Path(path).name, str(_Path(image).parent),
                    [_Path(n).name for n in names])
            emit({"hookSpecificOutput": answer})
            return 0
        if is_drop_folder(path):
            return 0
        if is_scratch_or_temp(path):
            return 0
        # A Read of more than LINE_PULL_MAX lines is a whole read and is not
        # exempt, or a reader could read a file as text in a few wide slices.
        # The pull of a few lines passes at the top of main(), through
        # common.line_pull().

        # THE PICTURE CAP. A reader whose profile carries a measured cap,
        # common.BURST_CAPS and common.BURST_BYTES, draws pictures only for
        # a turn inside that cap and reads a wider turn as text whole. The
        # test is on the whole batch the assistant message asked for, not on
        # this Read alone, so every hook in the batch reads the same answer
        # off the same transcript and no counter file is needed. A very wide
        # Sonnet turn of pictures saves input tokens and costs more in output
        # than it saves, so only sonnet has a cap.
        model = actor_reader(event) or FALLBACK_READER
        cap = burst_cap(model)
        if capped(event, model, cap):
            return 0

        from pathlib import Path
        try:
            size = Path(path).stat().st_size
        except OSError:
            return 0
        # A .docx is a zip of XML, so neither its size nor its bytes say what
        # a Read delivers: the container is mostly styles and parts, and it
        # carries the nulls the check below refuses. Pull the paragraphs out
        # first and weigh those, the same text pointer.py draws.
        # A .docx that will not open as a zip is not a Word file at all, most
        # often a text file somebody renamed. It falls through to the plain
        # text route below, because Read refuses the suffix either way and
        # leaving it would make a readable file unreadable.
        drawn_text = None
        if Path(path).suffix.lower() == ".docx":
            import pointer
            drawn_text = pointer.docx_text(path) or None
            if drawn_text:
                size = len(drawn_text.encode("utf-8"))
        # A file under 1 KB passes as text: converting a 483 byte file took
        # 2.5 s and 469 MB to save 10 tokens.
        if size < 1000:
            return 0
        if size > READ_MAX_BYTES:
            return 0
        if drawn_text is None:
            try:
                raw = Path(path).read_bytes()
            except OSError:
                return 0
            if b"\x00" in raw or raw.count(b"\n") > READ_MAX_LINES:
                return 0
        elif drawn_text.count("\n") > READ_MAX_LINES:
            return 0
        # A file the font cannot draw, such as Chinese, Japanese or Korean
        # text, converts to empty boxes nobody can read, so it stays text.
        # freetype_glyph and style load in a fraction of codepack's time and
        # need no NumPy, so a Read the saved images serve does not pay for them.
        import freetype_glyph
        import style
        font = (style.load().get("font.regular") or [""])[0]
        text = (drawn_text if drawn_text is not None
                else raw.decode("utf-8", "replace"))
        if not freetype_glyph.font_covers(text, font):
            return 0
        # The renderer's own line marks are U+E000 to U+E003 and it refuses a
        # source holding one, so such a file stays text rather than a deny.
        if any(mark in text for mark in "\ue000\ue001\ue002\ue003"):
            return 0

        # NO FLOOR HERE. See the module note above the imports: this route
        # pays no delivery fee, so there is no fixed character count below
        # which packing loses, and stub_chars() answered a question priced
        # for the other routes. drop_and_draw() always attempts the draw;
        # the comparison right below it is what decides, on this file's own
        # measured price, the same way subagent_stop.py decides with no
        # floor of its own.
        # Without freetype-py or NumPy the renderer falls back to Pillow and
        # draws a different, harder image, so the file stays text instead.
        from common import ensure_pillow
        if not ensure_pillow():
            return 0
        image, patch_tokens, tags, drawn = drop_and_draw(path, event)
        if image is not None:
            import densepack as dp
            text_tokens = round(size / dp.CHARS_PER_TOKEN)
            # The note ships in the same message as the picture, so it is
            # part of what the picture costs. A file whose note costs more
            # than the file's own text loses the comparison and is read as
            # text, which is the whole guarantee, per file, on that file's own
            # measurement. No floor and no cap: the count decides.
            note_tokens = round(len(tags or "") / dp.CHARS_PER_TOKEN)
            if patch_tokens is not None and patch_tokens + note_tokens >= text_tokens:
                # Measured cheaper as text. This route's own fee is zero,
                # so the comparison is the image's real patches against the
                # text tokens the raw Read would have cost, nothing added
                # either side. The picture nobody should read is deleted
                # and the Read proceeds exactly as written.
                # Every page and the legend sidecar go with it, not page
                # one alone: they hold the same words.
                discard(drawn)
                return 0
            # A Read that starts past image 1 gets the image that holds its
            # first line, so a Read of lines 400 to 460 does not get lines 1
            # to 318 again.
            at = _image_at_line(path, tool_input.get("offset"))
            if at is not None:
                image, tags = at
            tool_input["file_path"] = image
            # tags carries the exact text of every id, hash and long number
            # draw_drop_file() lifted, in this same message, so a reader
            # quotes a value instead of reading it off pixels and without
            # opening anything. Empty when the file held nothing to lift and
            # fitted one image.
            answer = {
                "hookEventName": "PreToolUse",
                "updatedInput": tool_input,
            }
            # One line saying what arrived, and nothing telling the reader
            # what to do about it. A line that tells the reader to answer from
            # the picture, or that a doubtful value is one Read away, makes
            # the reader check values it read right, and each check costs a
            # turn. The redirect carries the marker rows and the image note,
            # when there are any, and no path to any file.
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
        # Moved onto the name, so a link planted at it takes no write.
        from common import write_text_atomic
        if not write_text_atomic(marker, "1"):
            return 0

        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                # The project names its own files, so nothing that acts inside
                # a double-quoted word reaches this message, and a path
                # holding brackets or spaces still names the real file.
                "permissionDecisionReason": MESSAGE % (
                    format(size, ","), quoted_path(path)),
            }
        })
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
