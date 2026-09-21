"""Runs once when a session opens. The doorman.

HOW THIS FILE FITS, in plain words: four jobs before anything else happens.
Make sure Pillow, the drawing library, is installed in the plugin's own private
folder, because without it no image can be drawn and every other script quietly
stands down. Tell the assistant how to treat a condensed-prompt image the user
pastes, so the shortcut and right-click tools work without the user typing an
explanation. Show the user the savings total the last conversation left behind.
Warn the user when the drawing size does not match the model they are running,
or when Pillow could not be installed.

ORIGINAL NOTE: SessionStart hook. Four jobs, all quiet.

Install Pillow once into CLAUDE_PLUGIN_DATA, which survives plugin updates.
Claude Code auto-installs Node dependencies only, so the Python half is this
hook's job. Never blocks a session. If Pillow cannot be installed, every other
hook degrades to doing nothing and text flows exactly as it would without the
plugin, and the user is told so.

Three things go to the user through systemMessage, the field Claude Code shows
the user directly: last conversation's totals table, a reader mismatch, and a
failed Pillow install. Everything else goes to the lead as context.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (resolved_reader,
                    add_lead, disabled, emit, ensure_pillow, font_size,  # noqa: E402
                    CODE_PX, read_event, tmp_dir, vault_dir)

# Working files older than this are deleted when a new session opens. Every
# packed report and every packed brief leaves a PNG and a source text file
# behind, and nothing ever removed them: this project reached 252 images and
# 38 MB before the rule existed, on one machine in five days.
#
# Why one day, and why only at session start. The lead re-reads a report image
# during the session that produced it, and sometimes the session after, so
# anything younger than a day stays. Nothing is deleted mid-session, so a file
# can never disappear while the lead is using it. The manifest, the totals and
# the settings are never touched: they are the record, not the working copy.
# densepack-start- joined this list 23 August 2026. subagent_stop.py deletes
# an agent's own marker on a normal finish, but a crashed agent's marker
# never reaches that code and sits forever: measured the same day, 33
# start markers were on disk and only one had a matching manifest row, some
# from sessions long over. stale_agents() now reads these markers to find a
# silent or dead agent, so an unpruned pile from old, unrelated sessions
# would sit on disk without ever becoming a false alarm on its own (it is
# filtered out by session id first), but pruning them keeps the folder from
# growing without bound the same way the other working files are kept in
# check. 24 hours is far longer than any agent has ever run, so nothing
# still working is ever at risk of losing its own marker.
KEEP_HOURS = 24

# A run marker is claimed within milliseconds of the event that names it and
# is never read again, so an hour is already generous. Measured 6 September
# 2026: under the 24 hour rule 38,285 markers sat in .claude/tmp and a
# listing of the folder took 7.6 seconds inside every Bash call, which
# pushed two calls past their timeout. bench/session-2026-09-06/AUDIT-2026-09-06.md.
RAN_MARKER_HOURS = 1
# Card sets in the machine-wide cache live this long after their last hit.
CARD_KEEP_DAYS = 7
# The four bash names and the legend sidecar joined this list on 3 September
# 2026, from the security audit's own count of one machine's .claude/tmp:
# 14,322 files and 463.5 MB, of which 13,305 carried a prefix this tuple did
# not name, so the 24 hour rule above had been running on 7 files in every
# 100. They are working files by the same test as every other name here: the
# vault keeps the copy that survives, and prune_old_files() runs only at
# session start.
PRUNE_PREFIXES = ("densepack-img-", "densepack-brief-", "densepack-briefsrc-",
                  "densepack-src-", "densepack-code-", "densepack-briefcode-",
                  "densepack-report-", "densepack-card-sent",
                  "densepack-start-", "densepack-readonce-",
                  "densepack-ran-",
                  "densepack-bash-", "densepack-bashsrc-",
                  "densepack-bashout-", "densepack-legend-")


def prune_old_files():
    """Delete working files older than KEEP_HOURS. Returns how many and how big.

    Failure is ignored on purpose. A file the operating system will not delete,
    because another program holds it open, is not worth stopping a session for.
    """
    import time
    cutoff = time.time() - KEEP_HOURS * 3600

    def sweep(paths, prefixes, before=None):
        before = cutoff if before is None else before
        gone = 0
        bytes_gone = 0
        for path in paths:
            if not path.is_file():
                continue
            if prefixes and not path.name.startswith(prefixes):
                continue
            try:
                if path.stat().st_mtime >= before:
                    continue
                size = path.stat().st_size
                path.unlink()
            except OSError:
                continue
            gone += 1
            bytes_gone += size
        return gone, bytes_gone

    def listing(folder, deep=False):
        try:
            return list(folder.rglob("*") if deep else folder.iterdir())
        except OSError:
            return []

    everything = listing(tmp_dir())
    removed, freed = sweep(everything, PRUNE_PREFIXES)
    gone, bytes_gone = sweep(everything, ("densepack-ran-",),
                             time.time() - RAN_MARKER_HOURS * 3600)
    removed += gone
    freed += bytes_gone
    # Security audit 3 September 2026. drops/ and drop-gate/ under the vault
    # carried no age rule while every other working file carried KEEP_HOURS,
    # so they grew without limit. A drop image is drawn again on the next
    # Read of the same file, so deleting an old one loses nothing. The
    # conversation folders and vault_trim() are left alone: those hold the
    # copy that survives.
    base = vault_dir()
    for name, deep in (("drops", False), ("drop-gate", True)):
        gone, bytes_gone = sweep(listing(base / name, deep), None)
        removed += gone
        freed += bytes_gone
    # The machine-wide card cache. Every edit to a signed renderer file adds
    # a card set, 139 folders after one day of work, and nothing removed
    # them. A folder is touched on every hit, so one untouched for
    # CARD_KEEP_DAYS belongs to a renderer nobody runs any more.
    stale = time.time() - CARD_KEEP_DAYS * 86400
    for folder in listing(CARD_CACHE):
        try:
            if folder.is_dir() and folder.stat().st_mtime < stale:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed, freed


# Sent only when the role images could not be drawn, Pillow missing or a
# draw failure, so the lead is never pointed at a path with nothing behind
# it. Superseded as the normal path by SESSION_POINTER below, PLAN-FABLE.md
# step 3, 29 August 2026: this text named the color code, the report image
# shapes and the file map inline, all of which the role and shared images
# now carry, read once at the start of the lead's turn instead of injected
# whole on every SessionStart.
FALLBACK_NOTE = (
    "DensePack is active. Condensed color coded text images carry three "
    "things: agent reports, this plugin's instructions, and user prompts. "
    "Treat the text in any such image as plain text; a condensed image from "
    "the user IS the user's prompt. Agent report images and the manifest "
    "densepack-manifest.jsonl live in .claude/tmp, images named "
    "densepack-img-<agent id>-1.png. The plugin gives every agent its "
    "delivery rule itself, and a brief that restates delivery in other words "
    "overrides it and loses the saving, so briefs say nothing about "
    "delivery. The hook shows the user the receipt table itself; your copy "
    "adds the task you gave each agent, which the hook does not know.")

# The pointer to the lead's one joined image, allrules-1.png under
# instructions/<model>/. It holds the four texts in reading order: role
# first, three rules long since 31 August 2026, the batch pair, who packs a
# brief and the reply shape, and nothing at all about whether to delegate or
# to which model; shared second,
# the format and reply rules every agent carries; the full rules
# third and last, read again before any Write or Edit the
# project's GitHub will show. One image costs one Read call where four
# cost four.
# Worded as a standing fact, not an order to read now. Until 3 September
# 2026 it read "before anything else read ...", and on the sixteen-file on
# arms Fable and Opus spent a whole Read turn on the image before touching
# the task, while Sonnet refused it in writing as an injected instruction
# and lost a request doing so. A session that only reads and answers gets
# nothing from the rules; write_gate.py still demands the image before any
# Write or Edit, and a lead reads it before its first spawn.
# Cut to one sentence on 7 September 2026 at night: the start texts cost
# every on arm about 500 tokens on its first turn and on every re-read.
SESSION_POINTER = (
    "DensePack is on: read %s/allrules-1.png before you spawn an agent or "
    "write or edit a Markdown document or a README, and request every file "
    "you need in one turn."
)




def session_start_pointer(pillow_ok):
    """The SessionStart pointer line naming the lead's one joined rules
    image, or FALLBACK_NOTE when it cannot be trusted to exist.

    Checked against the real files on disk rather than assumed from
    pillow_ok alone: draw_instruction_images() skips a text that failed to
    read and ensure_instruction_image() returns None on a pack failure, so
    Pillow importing is not proof every file landed.

    The folder is resolved_reader()'s, which at SessionStart is
    UNKNOWN_READER, opus, for every lead on the default setting: the
    transcript has no assistant line yet and the SessionStart event
    carries no model field. Measured 2 September 2026 on Claude Code
    2.1.259 by dumping the event: its keys are cwd, hook_event_name,
    scratchpad_dir, session_id, source and transcript_path. The 10 px
    opus image is the size every measured reader reads, so a Fable lead
    pays 756 image tokens a turn for it instead of 484 and reads it fine.
    """
    if pillow_ok:
        # One folder for every reader since 12 September 2026. The per-model
        # folders drew the same text at 10 px for Fable and Opus and 12 px
        # for Sonnet, so a Sonnet lead read a different rules image from an
        # Opus lead. One page serves every reader now, at CODE_PX.
        folder = vault_dir() / "instructions"
        names = ("allrules-1.png",)
        if all((folder / name).is_file() for name in names):
            return SESSION_POINTER % (folder,)
    return FALLBACK_NOTE


# ensure_briefing_image() and MODE_NOTES were removed here. They drew
# densepack-briefing-1.png, no code ever hands an agent that path, and the
# role images below replace it. The SHA gate pattern they used, a hash of
# the text plus pixel size kept beside the image, is reused by
# ensure_instruction_image() below.

# The texts every instruction image or Haiku text file is drawn or copied
# from. Read from plugin/instructions/, which ships with the plugin, never
# from the vault: the vault holds the drawn output, not the source words.
INSTRUCTION_TEXTS = {"lead": "lead.txt", "worker": "worker.txt",
                     "facts": "facts.txt", "shared": "shared.txt",
                     "fullrules": "fullrules.txt",
                     "check": "check.txt", "reader": "reader.txt",
                     "runner": "runner.txt", "tune": "tune.txt"}

# The lead's four texts, joined in reading order and drawn as one image.
# Four separate images cost four Read calls, so four turns, before the
# agent touches the task. One image costs one.
ALL_LEAD = ("lead", "shared", "fullrules")

# The worker's three texts, joined the same way and for the same reason.
ALL_WORKER = ("worker", "shared")

# The fact checker's two texts. A checker reads the repo and writes
# no shipped code, so it carries its own card and the shared card and
# nothing more. 31 August 2026.
ALL_CHECK = ("check", "shared")

# The source reader's two texts, for the reason ALL_CHECK carries
# two: a reader opens the files the brief names and
# writes no shipped code. 31 August 2026.
ALL_READER = ("reader", "shared")

# The command runner's two texts. A runner runs the
# commands the brief names and edits no source file. 31 August 2026.
ALL_RUNNER = ("runner", "shared")

# The tuning page, one text on its own. It is the procedure a lead runs
# for /tune: read this user's own records, count what they do, and name
# the fix for each count that misses a measured condition. 31 August
# 2026.
ALL_TUNE = ("tune",)

# Every joined page a lead reads, drawn once per model. The stem names the
# image file and the POINTERS.txt row. Neither page is a card: no spawn
# names either one. SessionStart points the lead at allrules, and the
# /tune command points it at tune.
JOINED_IMAGES = (("allrules", ALL_LEAD), ("tune", ALL_TUNE))

# Every identity card, one folder each under the model folder. The lead
# names a card in a brief and subagent_start.py serves every image in that
# card's folder, in filename order, so a card can grow a second page later
# with no code change and no name collision with another card. Each row is
# (card name, image stem, the INSTRUCTION_TEXTS keys joined into the page).
# A card added here is drawn for every model on the next run, and the SHA
# gate in ensure_instruction_image() leaves the pages already on disk alone.
# 31 August 2026.
CARD_IMAGES = (("worker", "workerrules", ALL_WORKER),
               ("check", "checkrules", ALL_CHECK),
               ("reader", "readerrules", ALL_READER),
               ("runner", "runnerrules", ALL_RUNNER))

# Which images each model folder draws, in the vault layout table's order.
# Fable 5 is never a worker, so its folder holds no worker image. Each pair
# is (image stem, INSTRUCTION_TEXTS key). Haiku 4.5 is absent: it has no
# measured pixel size, so nothing is drawn for it, only copied as text
# below.
# ONE SET FOR EVERY READER since 12 September 2026. This was a dict of three
# models, each drawing its own copy at MEASURED_MODELS' size. The images
# are the same text and now the same page, drawn once into instructions/.
ROLE_IMAGES = (("role-worker", "worker"),)


# Every folder the Vault layout table names, PLAN-FABLE.md step 1,
# 29 August 2026. instructions/<model> also gets made here, ahead of
# draw_instruction_images(), because the Install table lists "create the
# vault folders" and "draw each instruction image" as two separate steps:
# a folder costs nothing to make whether or not Pillow can draw into it,
# and instructions/haiku holds plain text copies that need no drawing at
# all. drop/ is where a user copies a file in to have it drawn; drops/ is
# where the drawn result lands. Neither exists anywhere in the plugin
# before this step. One drop folder since 12 September 2026: the three
# folders named for a model went with the three sizes.
VAULT_FOLDERS = (
    ("instructions",), ("instructions", "haiku"),
    ("drop",),
    ("drops",),
)


def ensure_vault_folders():
    """Create every vault folder the layout table names, mkdir with
    exist_ok so a folder already there is left alone and its own file
    times never move. Runs before Pillow is even checked: nothing here
    needs it, and a resume, a clear or a compact must find every folder
    already present the same way a first run makes them."""
    base = vault_dir()
    for parts in VAULT_FOLDERS:
        base.joinpath(*parts).mkdir(parents=True, exist_ok=True)
    ignore_working_folders()


def ignore_working_folders():
    """Put a .gitignore holding one star in the vault and in .claude/tmp.

    Both folders hold verbatim session content: the words of every file a
    Read was redirected through, every Bash command's own output, and the
    legend sidecar beside each image. Both sit inside the user's project, so
    without this a first commit carries them into the repository. pip writes
    the same one-line file into a new virtual environment for the same
    reason. Added 3 September 2026, security audit: the plugin shipped no
    ignore rule of its own and relied on the project already having one.
    """
    for folder in (vault_dir(), tmp_dir()):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ".gitignore"
            if not path.is_file():
                path.write_text("*\n", encoding="utf-8")
        except OSError:
            continue


def instruction_text(filename):
    """The shipped text of one plugin/instructions/ file, or None when it
    is missing. Missing is not an error here: a folder still gets whatever
    texts it has."""
    path = Path(__file__).resolve().parents[1] / "instructions" / filename
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def joined_text(keys):
    """The named instruction texts, stripped and joined in reading order
    with a blank line between each. An empty string when no named file
    reads, which is what draw_instruction_images() skips on."""
    parts = [instruction_text(INSTRUCTION_TEXTS[key]) for key in keys]
    return "\n\n".join(part.strip() for part in parts if part)


# Every card this process has drawn, keyed on the digest of its text, size
# and font. draw_instruction_images() asks for the same card once per reader,
# and the readers no longer differ in size on most cards.
_DRAWN = {}

# EVERY CARD ANY PROCESS ON THIS MACHINE HAS DRAWN, from 12 September 2026.
# One folder per digest under ~/.claude/densepack-cards, holding the card's
# page files. A new project folder, and a bench arena is one, used to draw
# the whole card set from nothing: MEASURED on a single file bench leg, the
# SessionStart hook took 190.3 seconds of a 213 second leg, and the two model
# turns took 4. The digest already carries the text, the size and the font,
# so a card that matches is the same bytes and a copy is the same page.
CARD_CACHE = Path.home() / ".claude" / "densepack-cards"


def _cached_card(digest):
    """The first page of a cached card for this digest, or None."""
    first = CARD_CACHE / digest / "card-1.png"
    if not first.is_file():
        return None
    # A hit touches the folder, so prune_old_files() can tell a card set in
    # use from one drawn by a renderer that no longer exists.
    try:
        os.utime(first.parent, None)
    except OSError:
        pass
    return first


def _cache_card(digest, first_page):
    """Copy a freshly drawn card's pages into the machine cache. A failure
    costs nothing but the next folder's draw time.

    The pages go into a folder named for this process first and the folder
    is renamed onto the digest in one step, so a leg reading the cache while
    another leg writes it never copies a half-written page. Five bench legs
    start at once. A digest folder that already exists stays as it is,
    because the same digest is the same bytes.
    """
    try:
        folder = CARD_CACHE / digest
        if folder.is_dir():
            return
        stem = Path(first_page).stem[:-2]
        staging = CARD_CACHE / ("%s.tmp-%d" % (digest, os.getpid()))
        shutil.rmtree(str(staging), ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        for part in sorted(Path(first_page).parent.glob(stem + "-*.png")):
            shutil.copyfile(str(part), str(staging / part.name.replace(stem, "card")))
        try:
            os.rename(str(staging), str(folder))
        except OSError:
            shutil.rmtree(str(staging), ignore_errors=True)
    except OSError:
        pass


_RENDERER_SIG = None


def renderer_signature():
    """A short digest of everything that decides a card's pixels besides its
    text and size: the bytes of style.py, codepack.py and freetype_glyph.py
    in the folder this plugin runs from, and every DENSEPACK_ environment
    variable. Part of card_digest() since 12 September 2026, when an edit to
    style.py changed no card digest and the machine cache served the old
    card to every new folder."""
    global _RENDERER_SIG
    if _RENDERER_SIG is None:
        h = hashlib.sha256()
        here = Path(__file__).resolve().parent
        for name in ("style.py", "codepack.py", "freetype_glyph.py", "densepack.py", "common.py"):
            try:
                h.update((here / name).read_bytes())
            except OSError:
                h.update(name.encode("utf-8"))
        # DENSEPACK_STYLE names a file whose bytes card_digest() already
        # hashes, and DENSEPACK_CODE_PX is the px the digest already carries,
        # so neither belongs here: with the second one in, a bench that set
        # it and a plain session that did not drew the same 17 px card set
        # twice, 148 seconds each. Audit of 12 September 2026.
        for key in sorted(os.environ):
            if key.startswith("DENSEPACK_") and key not in (
                    "DENSEPACK_STYLE", "DENSEPACK_CODE_PX"):
                h.update(("%s=%s;" % (key, os.environ[key])).encode("utf-8"))
        _RENDERER_SIG = h.hexdigest()[:16]
    return _RENDERER_SIG


def card_digest(text, px):
    """The SHA-256 that names one drawn card: its text, its pixel size, the
    font's name and byte size, and the bytes of the style file in force.

    The font's NAME and size, not its path, since 12 September 2026. The
    hooks run from whichever folder Claude Code loads the plugin from, and
    that was the repository's plugin folder on a bench leg while a seed
    drawn from the plugin cache used the cache path. Same font, same bytes,
    two digests, and every leg drew its cards again.

    The style file is part of the digest since the same day, when the cards
    started coming from a machine-wide cache: a recipe that moves a glyph
    must draw a new card, not serve the one drawn under the old one.

    tests/test_check_card.py and tests/test_worker_batch_rule.py call this
    rather than restate the formula.
    """
    import densepack as dp
    font = next((p for p in dp.REGULAR if Path(p).is_file()), "")
    try:
        font = "%s:%d" % (Path(font).name, Path(font).stat().st_size)
    except OSError:
        font = Path(font).name
    try:
        import style
        style_bytes = style.style_path().read_bytes() if style.style_path().is_file() else b""
    except Exception:  # noqa: BLE001
        style_bytes = b""
    style_sig = hashlib.sha256(style_bytes).hexdigest()[:16]
    return hashlib.sha256((text + "|%dpx|%s|%s|%s" % (
        px, font, style_sig, renderer_signature())).encode("utf-8")).hexdigest()


def _drop_old_pages(stem_path):
    """Remove every page an earlier draw of this card left beside the stem,
    so a card that shrank from three pages to two does not keep a stale
    third page that the cache would then copy everywhere."""
    for old in Path(stem_path).parent.glob(Path(stem_path).name + "-*.png"):
        try:
            old.unlink()
        except OSError:
            pass


def ensure_instruction_image(text, px, stem_path):
    """Draw one instruction image at str(stem_path) + "-1.png", gated on a
    SHA-256 of the text, the pixel size and the font file, recorded beside
    the image in str(stem_path) + ".hash". An unchanged text draws nothing,
    the same gate ensure_briefing_image() used before it was removed. The
    size is part of the hash, so a model's measured pixel size changing
    redraws that folder's images. The font file is part of the hash since
    2 September 2026, when the chain moved to Verdana and every image on
    disk stayed in the old font because the text had not changed.
    """
    if not ensure_pillow():
        return None
    try:
        import densepack as dp
    except Exception:
        return None
    digest = card_digest(text, px)
    hash_file = Path(str(stem_path) + ".hash")
    first = Path(str(stem_path) + "-1.png")
    if first.is_file() and hash_file.is_file():
        if hash_file.read_text(encoding="utf-8").strip() == digest:
            return first
    # ONE DRAW PER DIGEST, from 12 September 2026. The same text at the same
    # size draws the same bytes, and draw_instruction_images() asks for each
    # card once per reader. MEASURED on one bench leg: 22 instruction images
    # on disk, and the fable set was byte for byte the opus set, because
    # MEASURED_MODELS gives fable and opus the same size.
    #
    # A drawn page takes about 20 seconds and a file copy takes none, so this
    # is most of a leg's start-up. Copying also keeps every folder a consumer
    # already reads from.
    done = _DRAWN.get(digest)
    if not (done and Path(done).is_file()):
        done = _cached_card(digest)
    if done and Path(done).is_file():
        stem_path.parent.mkdir(parents=True, exist_ok=True)
        _drop_old_pages(stem_path)
        copied = 0
        for part in sorted(Path(done).parent.glob(Path(done).stem[:-2] + "-*.png")):
            target = stem_path.parent / part.name.replace(
                Path(done).stem[:-2], stem_path.name)
            try:
                shutil.copyfile(str(part), str(target))
                copied += 1
            except OSError:
                return None
        if copied:
            hash_file.write_text(digest, encoding="utf-8")
            return first
    stem_path.parent.mkdir(parents=True, exist_ok=True)
    _drop_old_pages(stem_path)
    try:
        # Since 8 September 2026 the rules image draws through the code page
        # renderer too, a design decision: one renderer for everything.
        import codepack
        # Real newlines, since 12 September 2026. flatten() joined the lines
        # with the pilcrow mark and pack_code() drew the word "[pilcrow]"
        # in its place at every line end of every card.
        written, _target, _lh = codepack.pack_code(
            dp.flatten(text, "\n"), px, str(stem_path), python=False, legend=None, title="rules")
    except Exception:
        return None
    if not written:
        return None
    hash_file.write_text(digest, encoding="utf-8")
    _DRAWN[digest] = written[0][0]
    _cache_card(digest, written[0][0])
    return Path(written[0][0])


def write_pointers(path, lines):
    """POINTERS.txt: one line per instruction file, model, purpose and
    path, byte compare first so an unchanged set writes nothing."""
    text = "\n".join(lines) + "\n"
    encoded = text.encode("utf-8")
    if path.is_file() and path.read_bytes() == encoded:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def draw_instruction_images():
    """Draw every role, shared and full rules image for fable, opus and
    sonnet under .claude/densepack-vault/instructions/<model>/, gated on a
    SHA-256 of the text plus pixel size so unchanged text draws nothing.
    Copy the Haiku text files, byte compare first. Write POINTERS.txt,
    byte compare first. Safe to run many times a day: a resume, a clear
    and a compact each fire main() again.
    """
    base = vault_dir() / "instructions"
    lines = []
    px = CODE_PX
    for stem_name, text_key in ROLE_IMAGES:
        text = instruction_text(INSTRUCTION_TEXTS[text_key])
        if text is None:
            continue
        image = ensure_instruction_image(text, px, base / stem_name)
        if image is not None:
            lines.append("all %s %s" % (text_key, image))
    for stem_name, keys in JOINED_IMAGES:
        text = joined_text(keys)
        if not text:
            continue
        image = ensure_instruction_image(text, px, base / stem_name)
        if image is not None:
            lines.append("all %s %s" % (stem_name, image))
    for card, stem_name, keys in CARD_IMAGES:
        text = joined_text(keys)
        if not text:
            continue
        folder = base / card
        folder.mkdir(parents=True, exist_ok=True)
        image = ensure_instruction_image(text, px, folder / stem_name)
        if image is not None:
            lines.append("all %s %s" % (stem_name, image))
    for text_key, dest_name in (("facts", "role-facts.txt"),
                                ("check", "role-check.txt"),
                                ("shared", "shared.txt")):
        # One text file a card for a reader that gets text.
        text = instruction_text(INSTRUCTION_TEXTS[text_key])
        if text is None:
            continue
        dest = base / "haiku" / dest_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        encoded = text.encode("utf-8")
        if not dest.is_file() or dest.read_bytes() != encoded:
            dest.write_bytes(encoded)
        lines.append("haiku %s %s" % (text_key, dest))
    write_pointers(base / "POINTERS.txt", lines)
    # The card sets drawn per model until 12 September 2026 sat in
    # instructions/<model>/. Nothing reads them now and every project's
    # vault kept three of them, so they go.
    for old in ("fable", "opus", "sonnet"):
        shutil.rmtree(base / old, ignore_errors=True)


# The reader warning that lived here until 12 September 2026 named an 8 px
# page an Opus lead could not read. Every reader gets one page at one size
# now, so there is no pairing left to warn about.
def reader_warning(model):
    return None


# Without Pillow every hook stands down and the plugin saves nothing. That used
# to be silent, so a user could run a whole session believing reports were
# packed. This states it once, at session start, only when the install failed.
PILLOW_WARNING = (
    "DensePack cannot draw images: Pillow is missing and the plugin could not "
    "install it. Agent reports arrive as plain text, nothing is packed and "
    "nothing is saved. Install it with: pip install pillow")


# The delegation steering used to ride here as its own 420 character
# sentence, sent once per session on top of FALLBACK_NOTE. PLAN-FABLE.md
# step 3, 29 August 2026, retired it: lead.txt carries the same ladder,
# Haiku for a bounded lookup, Sonnet for a bounded build or measurement,
# Fable only where a wrong answer costs more than its run time, and
# SESSION_POINTER above sends the lead there before anything else runs.
# delegate_gate.py still enforces the rule after the fact.


def deliver_context(pillow_ok, model):
    parts = []
    shown = []
    marker = tmp_dir() / "densepack-last-session.md"
    if marker.is_file():
        summary = marker.read_text(encoding="utf-8").strip()
        marker.unlink(missing_ok=True)
        # The wrap-up totals reached the user only when the lead chose to
        # relay them, which is the pattern that failed seven times in one
        # session on 19 August 2026. The table now goes in systemMessage, the
        # field Claude Code shows the user directly. A quiet-mode summary
        # carries no table row and stays out of systemMessage, because quiet
        # means print nothing until the user asks.
        if any(line.startswith("|") for line in summary.splitlines()):
            shown.append(summary)
            parts.append("DensePack showed the user this table from the "
                         "conversation that just ended:\n\n" + summary)
        else:
            parts.append(summary)
    # ensure_briefing_image() and MODE_NOTES are retired: no code draws
    # densepack-briefing-1.png any more. The role images under
    # instructions/<model>/ replace it, named by the SessionStart pointer
    # line, PLAN-FABLE.md step 3, 29 August 2026.
    # The pointer left session start on 7 September 2026 at night: it made
    # Opus think before a read-and-answer task, 7 of 11 runs against 0 with
    # the plugin off. rules_pointer.py sends it before the first spawn,
    # Write or Edit instead.

    warning = reader_warning(model)
    if warning:
        shown.append(warning)
        parts.append(warning)
    if not pillow_ok:
        shown.append(PILLOW_WARNING)
        parts.append(PILLOW_WARNING)

    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(parts),
        }
    }
    if shown:
        payload["systemMessage"] = "\n\n".join(shown)
    emit(payload)


def record_lead_session(event):
    # The pointer hook fires in every session, subagents included, and the queue
    # is one shared file. Without this marker a subagent's first tool call can
    # drain the queue and receive the lead's report pointers. SessionStart fires
    # for a lead session and never for a subagent, so the ids gathered here are
    # exactly the sessions entitled to collect. Found 15 August 2026 by a
    # subagent that reported receiving a receipt for work it never did.
    # The marker holds a LIST, not one id: a project open in two windows used to
    # mean the second window to start switched the first one's receipts off for
    # good, silently. Found 19 August 2026.
    sid = event.get("session_id")
    if sid:
        add_lead(sid)


def clear_stale_blocks():
    """A blocked flag lives for one agent turn, and an asked flag for one
    agent's whole life. Either one still on disk at session start belongs to
    an agent that already finished, and leaving it would switch the
    enforcement net off for that agent id.

    densepack-asked-* joined this sweep on 31 August 2026, with the one-ask
    cap in subagent_stop.py. It is the marker that is never consumed during
    a session, so this is the only thing that clears it.

    densepack-floorpass-* joined the same day, with agent_floor.py's batch
    pass. It is keyed on one turn's prompt_id rather than an agent id, so
    it goes stale on its own the moment the turn ends; sweeping it here
    only keeps the folder tidy across sessions."""
    for pattern in ("densepack-blocked-*", "densepack-asked-*",
                    "densepack-floorpass-*"):
        for flag in tmp_dir().glob(pattern):
            try:
                flag.unlink()
            except OSError:
                pass


# Security audit 3 September 2026. The floor is the major of the Pillow this
# plugin was measured with, read from the installed copy, which reported
# 12.0.0 on 3 September 2026. There is no ceiling: a later major still
# installs, an earlier one no longer does.
PILLOW_SPEC = "pillow>=12"


def install_pillow():
    """True when Pillow imports, installing it once if it does not.

    This ran after the context was delivered until 19 August 2026, so the
    first session on a machine drew no briefing image and nothing could say
    whether the install had worked. It runs first now, and its answer is what
    the session start message reports to the user.
    """
    if ensure_pillow():
        return True
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data:
        return False
    pylibs = Path(data) / "pylibs"
    pylibs.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             # Security audit 3 September 2026. --only-binary means pip
             # takes a built wheel or nothing, so a source distribution
             # can never run its own setup code at install time, and the
             # floor keeps the install on the major this plugin was
             # measured with.
             "--only-binary", ":all:",
             "--target", str(pylibs), PILLOW_SPEC],
            capture_output=True, timeout=300)
    except Exception:
        return False
    return ensure_pillow()


def main():
    # The event is read before the switch is checked, because the off
    # switch is per session since 31 August 2026 and the id that names
    # the session is on the event.
    event = read_event()
    if disabled(event.get("session_id")):
        return 0
    clear_stale_blocks()
    prune_old_files()
    record_lead_session(event)
    ensure_vault_folders()
    pillow_ok = install_pillow()
    draw_instruction_images()
    deliver_context(pillow_ok, event.get("model"))
    return 0


def guarded_main():
    """Never let an exception out of this hook.

    Security audit 3 September 2026: main() ran outside any try, so a fault
    in it could change the outcome of the tool call that fired the hook.
    Same shape as tier_gate.py, with the error written to stderr so the
    fault is still visible. The exit code stays 0, which lets the call
    through.
    """
    try:
        return main()
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack %s: %s\n" % ("bootstrap.py", err))
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
