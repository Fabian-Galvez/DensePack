"""Runs once when a session opens. The doorman.

HOW THIS FILE FITS, in plain words: four jobs before anything else happens.
Make sure Pillow, the drawing library, is installed in the plugin's own private
folder, because without it no image can be drawn and every other script quietly
stands down. Tell the assistant how to treat a condensed-prompt image the user
pastes, so the shortcut and right-click tools work without the user typing an
explanation. Show the user the savings total the last conversation left behind.
Warn the user when the drawing size does not match the model they are running,
or when Pillow could not be installed.

SessionStart hook. Four jobs, all quiet.

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
# behind, and nothing else removes them.
#
# Why one day, and why only at session start. The lead re-reads a report image
# during the session that produced it, and sometimes the session after, so
# anything younger than a day stays. Nothing is deleted mid-session, so a file
# can never disappear while the lead is using it. The manifest, the totals and
# the settings are never touched: they are the record, not the working copy.
# densepack-start- markers are on the list because a crashed agent's marker
# never reaches the code that deletes it on a normal finish. 24 hours is far
# longer than any agent runs, so nothing still working loses its marker.
KEEP_HOURS = 24

# A run marker is claimed within milliseconds of the event that names it and
# is never read again, so an hour is already generous. Under the 24 hour rule
# tens of thousands of markers pile up in .claude/tmp, and a listing of the
# folder then takes seconds inside every Bash call.
RAN_MARKER_HOURS = 1
# Card sets in the machine-wide cache live this long after their last hit.
CARD_KEEP_DAYS = 7
# The bash names and the legend sidecar are working files by the same test as
# every other name here: the vault keeps the copy that survives, and
# prune_old_files() runs only at session start.
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
    # images/, drops/ and drop-gate/ under the vault carry the same age rule
    # as every other working file, or they grow without limit. A drop image
    # is drawn again on the next Read of the same file, so deleting an old
    # one loses nothing. The conversation folders and vault_trim() are left
    # alone: those hold the copy that survives.
    base = vault_dir()
    from common import project_dir, through_link
    for name, deep in (("images", False), ("drops", False), ("drop-gate", True)):
        # A folder that is, or sits under, a link or a junction may point at
        # the user's own files, so nothing through one is deleted.
        folder = base / name
        if through_link(project_dir(), folder):
            continue
        gone, bytes_gone = sweep([p for p in listing(folder, deep)
                                  if not through_link(folder, p)], None)
        removed += gone
        freed += bytes_gone
    # A hook killed mid-draw leaves its per-path folder under drop-gate. Empty
    # folders go, deepest first; rmdir refuses one that still holds a file,
    # and nothing through a link is touched.
    gate = base / "drop-gate"
    if not through_link(project_dir(), gate):
        for sub in sorted(listing(gate, True), key=lambda p: len(p.parts), reverse=True):
            try:
                # Only a folder untouched for an hour: a running draw made
                # its folder moments ago and is about to copy into it.
                if (sub.is_dir() and not through_link(gate, sub)
                        and sub.stat().st_mtime < time.time() - 3600):
                    sub.rmdir()
            except OSError:
                pass
    # The machine-wide card cache. Every edit to a signed renderer file adds
    # a card set. A folder is touched on every hit, so one untouched for
    # CARD_KEEP_DAYS belongs to a renderer nobody runs.
    stale = time.time() - CARD_KEEP_DAYS * 86400
    for folder in listing(CARD_CACHE):
        try:
            if folder.is_dir() and folder.stat().st_mtime < stale:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed, freed


# Sent only when the rules image could not be drawn, Pillow missing or a
# draw failure, so the lead is never pointed at a path with nothing behind
# it.
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
# instructions/. It holds the lead, shared and full rules texts in reading
# order. One image costs one Read call where three cost three.
# Worded as a standing fact, not an order to read now: a reader told to read
# it before anything else spends a whole Read turn on it before the task, and
# some readers refuse such an order as an injected instruction. A session
# that only reads and answers gets nothing from the rules. Kept to one
# sentence, because the start text costs tokens on the first turn and on
# every re-read.
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

    The folder is one for every reader. At SessionStart the event carries
    no model field and the transcript has no assistant line yet, so no
    reader can be named here; the event's keys are cwd, hook_event_name,
    scratchpad_dir, session_id, source and transcript_path.
    """
    # Only an image this plugin draws is named. The Export ships no
    # instruction texts and draws none, so an image found there was planted
    # by the project and must not reach the lead as the plugin's own rules.
    instructions_ship = (Path(__file__).resolve().parent.parent / "instructions").is_dir()
    if pillow_ok and instructions_ship:
        # One folder for every reader: one image at CODE_PX serves them all.
        folder = vault_dir() / "instructions"
        # The .hash beside the image must hold this machine's seal over the
        # current rules text. A project can commit an image and a plain
        # digest; it cannot compute the seal.
        try:
            drawn = ((folder / "allrules-1.png").is_file()
                     and (folder / "allrules.hash").read_text(encoding="utf-8").strip()
                     == sealed_digest(card_digest(joined_text(ALL_LEAD), CODE_PX)))
        except OSError:
            drawn = False
        if drawn:
            return SESSION_POINTER % (folder,)
    return FALLBACK_NOTE


# The texts every instruction image or Haiku text file is drawn or copied
# from. Read from the instructions folder, which ships with the plugin, never
# from the vault: the vault holds the drawn output, not the source words.
INSTRUCTION_TEXTS = {"lead": "lead.txt", "worker": "worker.txt",
                     "facts": "facts.txt", "shared": "shared.txt",
                     "fullrules": "fullrules.txt",
                     "check": "check.txt", "reader": "reader.txt",
                     "runner": "runner.txt", "tune": "tune.txt"}

# The lead's three texts, joined in reading order and converted as one
# image. Three separate images cost three Read calls, so three turns,
# before the agent touches the task. One image costs one.
ALL_LEAD = ("lead", "shared", "fullrules")

# The worker's two texts, joined the same way and for the same reason.
ALL_WORKER = ("worker", "shared")

# The fact checker's two texts: its own card and the shared card.
ALL_CHECK = ("check", "shared")

# The source reader's two texts: a reader opens the files the brief names.
ALL_READER = ("reader", "shared")

# The command runner's two texts: a runner runs the commands the brief names.
ALL_RUNNER = ("runner", "shared")

# The tuning page, one text on its own: the procedure a lead runs to read
# this user's own records, count what they do, and name the fix for each
# count that misses a measured condition.
ALL_TUNE = ("tune",)

# Every joined page a lead reads, drawn once. The stem names the image file
# and the POINTERS.txt row. Neither page is a card: no spawn names either one.
JOINED_IMAGES = (("allrules", ALL_LEAD), ("tune", ALL_TUNE))

# Every identity card, one folder each under instructions/. A card's folder
# can grow a second page with no code change and no name collision with
# another card. Each row is (card name, image stem, the INSTRUCTION_TEXTS keys
# joined into the page). A card added here is drawn on the next run, and the
# SHA gate in ensure_instruction_image() leaves the pages already on disk
# alone.
CARD_IMAGES = (("worker", "workerrules", ALL_WORKER),
               ("check", "checkrules", ALL_CHECK),
               ("reader", "readerrules", ALL_READER),
               ("runner", "runnerrules", ALL_RUNNER))

# The single role images, each pair (image stem, INSTRUCTION_TEXTS key), drawn
# once into instructions/ for every reader.
ROLE_IMAGES = (("role-worker", "worker"),)


# Every folder the vault layout names. They are made here, ahead of
# draw_instruction_images(), because a folder costs nothing to make whether
# or not Pillow can draw into it, and instructions/haiku holds plain text
# copies that need no drawing at all. to-draw/ is where a user copies a file
# in to have it drawn; images/ is where the drawn result lands.
VAULT_FOLDERS = (
    ("to-draw",),
)


def ensure_vault_folders():
    """Create every vault folder the layout table names, mkdir with
    exist_ok so a folder already there is left alone and its own file
    times never move. Runs before Pillow is even checked: nothing here
    needs it, and a resume, a clear or a compact must find every folder
    already present the same way a first run makes them."""
    from common import project_dir, through_link
    base = vault_dir()
    # A committed vault link would put these folders, and the .gitignore
    # below, in the folder it points at.
    if through_link(project_dir(), base):
        return
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
    reason. The plugin does not rely on the project having an ignore rule.
    """
    from common import project_dir, through_link
    for folder in (vault_dir(), tmp_dir()):
        try:
            if through_link(project_dir(), folder):
                continue
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ".gitignore"
            # lexists is true for a link with no target, and mode "x" opens
            # with O_EXCL, which refuses any link at the name.
            if os.path.lexists(path):
                continue
            with open(path, "x", encoding="utf-8") as fh:
                fh.write("*\n")
        except OSError:
            continue


def instruction_text(filename):
    """The shipped text of one file in the instructions folder, or None when it
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
# and font, because draw_instruction_images() can ask for the same card more
# than once.
_DRAWN = {}

# EVERY CARD ANY PROCESS ON THIS MACHINE HAS DRAWN. One folder per digest
# under ~/.claude/densepack-cards, holding the card's page files. Without it
# a new project folder draws the whole card set from nothing, which takes
# minutes at session start. The digest carries the text, the size and the
# font, so a card that matches is the same bytes and a copy is the same page.
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
    is renamed onto the digest in one step, so a process reading the cache
    while another writes it never copies a half-written page. A digest
    folder that already exists stays as it is,
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


# DENSEPACK_ variables that change no pixel of an image. They stay out of the
# image cache key, so setting one never converts the instruction images again.
NOT_PIXEL_SETTINGS = {"DENSEPACK_STYLE", "DENSEPACK_CODE_PX", "DENSEPACK_HELPER_MEMORY_MB",
                      "DENSEPACK_SERIAL_DRAW", "DENSEPACK_DASHBOARD_NETWORK", "DENSEPACK_ARENA",
                      "DENSEPACK_ARENA_ROOT", "DENSEPACK_CONTEXT_TOKENS"}


def renderer_signature():
    """A short digest of everything that decides a card's pixels besides its
    text and size: the bytes of style.py, codepack.py and freetype_glyph.py
    in the folder this plugin runs from, and every DENSEPACK_ environment
    variable. Part of card_digest(), so an edit to style.py changes the
    digest and the machine cache never serves an old card to a new folder."""
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
        # so neither belongs here: with the second one in, a process that set
        # it and one that did not would draw the same card set twice.
        for key in sorted(os.environ):
            if (key.startswith("DENSEPACK_") and key not in NOT_PIXEL_SETTINGS
                    and not key.startswith("DENSEPACK_BENCH_")):
                h.update(("%s=%s;" % (key, os.environ[key])).encode("utf-8"))
        _RENDERER_SIG = h.hexdigest()[:16]
    return _RENDERER_SIG


def card_digest(text, px):
    """The SHA-256 that names one drawn card: its text, its pixel size, the
    font's name and byte size, and the bytes of the style file in force.

    The font's NAME and size, not its path: the hooks run from whichever
    folder Claude Code loads the plugin from, and the same font at two paths
    would give two digests and draw every card again.

    The style file is part of the digest because the cards come from a
    machine-wide cache: a recipe that moves a glyph must draw a new card,
    not serve the one drawn under the old recipe.
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


def sealed_digest(digest):
    """What the .hash file beside an instruction image holds: the digest
    sealed with this machine's key. A project can compute the plain digest
    and commit it with its own image; it cannot compute the seal."""
    from common import _row_seal
    return _row_seal({"card_digest": digest}) or digest


def ensure_instruction_image(text, px, stem_path):
    """Draw one instruction image at str(stem_path) + "-1.png", gated on a
    SHA-256 of the text, the pixel size and the font file, recorded beside
    the image in str(stem_path) + ".hash". An unchanged text draws nothing.
    The size is part of the hash, so a size change redraws the image. The
    font file is part of the hash, so a font change redraws every image even
    when the text has not changed.
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
        if hash_file.read_text(encoding="utf-8").strip() == sealed_digest(digest):
            return first
    # ONE DRAW PER DIGEST. The same text at the same size draws the same
    # bytes, so a digest already drawn in this process, or found in the
    # machine cache, is copied rather than drawn again. A drawn page takes
    # about 20 seconds and a file copy takes none. Copying also keeps every
    # folder a consumer already reads from.
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
            hash_file.write_text(sealed_digest(digest), encoding="utf-8")
            return first
    stem_path.parent.mkdir(parents=True, exist_ok=True)
    _drop_old_pages(stem_path)
    try:
        # The rules image draws through the code renderer: one renderer for
        # everything.
        import codepack
        # Real newlines: flatten() with the pilcrow mark would make
        # pack_code() draw the word "[pilcrow]" at every line end.
        written, _target, _lh = codepack.pack_code(
            dp.flatten(text, "\n"), px, str(stem_path), python=False, legend=None, title="rules")
    except Exception:
        return None
    if not written:
        return None
    hash_file.write_text(sealed_digest(digest), encoding="utf-8")
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
    """Draw every role, joined and card image under
    .claude/densepack-vault/instructions/, gated on a SHA-256 of the text
    plus pixel size so unchanged text draws nothing.
    Copy the Haiku text files, byte compare first. Write POINTERS.txt,
    byte compare first. Safe to run many times a day: a resume, a clear
    and a compact each fire main() again.
    """
    # The Export ships no instruction texts, so it makes, writes and deletes nothing here.
    if not (Path(__file__).resolve().parent.parent / "instructions").is_dir():
        return
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
    # The folders fable, opus and sonnet under instructions/ hold card sets
    # nothing reads, so they are removed.
    for old in ("fable", "opus", "sonnet"):
        shutil.rmtree(base / old, ignore_errors=True)


# No reader warning: every reader gets one image at one size, so there is no
# pairing to warn about.
def reader_warning(model):
    return None


# Without Pillow every hook stands down and the plugin saves nothing. Silence
# would let a user run a whole session believing reports were packed, so this
# states it once, at session start, only when the install failed.
PILLOW_WARNING = (
    "DensePack cannot make images: Pillow, freetype-py or NumPy is missing and the plugin could not "
    "install it. Agent reports arrive as plain text, nothing is packed and "
    "nothing is saved. Install them with: python3 -m pip install --user pillow freetype-py numpy "
    "(on Debian and Ubuntu, add --break-system-packages)")



# Claude Code's auto mode tells the agent to read files with cat, head or sed
# in Bash. A Bash read stays text, so this line names the tools that save.
READ_TOOL_LINE = (
    "DensePack is on. It saves tokens only when you read files with the Read "
    "tool and change them with the Edit tool: a Bash read (cat, head, sed, "
    "type) saves nothing, and Write does not work after an image read.")


def lead_reads_images(model):
    """True when a lead on this model is sent images: the model named at
    session start, or the recorded lead when the event names none."""
    from common import READER_SIZES, lead_gets_images, reader_gets_images
    if isinstance(model, dict):
        model = model.get("id") or model.get("display_name")
    name = str(model or "").lower()
    if not name:
        return lead_gets_images()
    return reader_gets_images(next((k for k in READER_SIZES if k in name), None))


BASH_FIRST_NOTE = (
    "DensePack set CLAUDE_CODE_THRIFTY_SONIC to 0 in ~/.claude/settings.json. "
    "Auto mode then stops telling Claude to read files with Bash, which "
    "DensePack cannot convert. It applies from your next session.")


def deliver_context(pillow_ok, model, bash_first_set=False, packed_note=None):
    parts = []
    shown = []
    if bash_first_set:
        shown.append(BASH_FIRST_NOTE)
    if packed_note:
        shown.append(packed_note)
    if pillow_ok and lead_reads_images(model):
        parts.append(READ_TOOL_LINE)
    # The last session's table comes from outside the project, so a cloned
    # project cannot put its own words here.
    from common import machine_state_dir
    marker = machine_state_dir() / "densepack-last-session.md"
    if marker.is_file():
        summary = marker.read_text(encoding="utf-8").strip()
        marker.unlink(missing_ok=True)
        # The wrap-up totals go in systemMessage, the field Claude Code shows
        # the user directly, because a lead left to relay them skips them. A
        # quiet-mode summary carries no table row and stays out of
        # systemMessage, because quiet means print nothing until the user asks.
        if any(line.startswith("|") for line in summary.splitlines()):
            shown.append(summary)
            parts.append("DensePack showed the user this table from the "
                         "conversation that just ended:\n\n" + summary)
        else:
            parts.append(summary)

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
    # is one shared file. Without this marker a subagent's first tool call could
    # drain the queue and receive the lead's report pointers. SessionStart fires
    # for a lead session and never for a subagent, so the ids gathered here are
    # exactly the sessions entitled to collect. The marker holds a LIST, not one
    # id, so a project open in two windows keeps both windows' receipts.
    sid = event.get("session_id")
    if sid:
        add_lead(sid)


def clear_stale_blocks():
    """A blocked flag lives for one agent turn, and an asked flag for one
    agent's whole life. Either one still on disk at session start belongs to
    an agent that already finished, and leaving it would switch the
    enforcement net off for that agent id.

    densepack-asked-* is the one-ask marker subagent_stop.py never consumes
    during a session, so this is the only thing that clears it.

    densepack-floorpass-* is keyed on one turn's prompt_id rather than an
    agent id, so it goes stale on its own the moment the turn ends; sweeping
    it here only keeps the folder tidy across sessions."""
    for pattern in ("densepack-blocked-*", "densepack-asked-*",
                    "densepack-floorpass-*"):
        for flag in tmp_dir().glob(pattern):
            try:
                flag.unlink()
            except OSError:
                pass


# The floor is the major of the Pillow this plugin was measured with, 12.
# There is no ceiling: a later major still installs, an earlier one does not.
PILLOW_SPEC = "pillow>=12"
FREETYPE_SPEC = "freetype-py>=2"  # ships a wheel with libfreetype inside, so --only-binary holds
NUMPY_SPEC = "numpy>=2"  # codepack.py blends each glyph with it


def install_pillow():
    """True when Pillow imports, installing it once if it does not.

    It runs before the context is delivered, so the first session on a
    machine can draw its images, and its answer is what the session start
    message reports to the user.
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
             # --upgrade, because pip skips a package already in --target:
             # after a Python upgrade the old NumPy stays and fails to import.
             "--upgrade",
             # --only-binary means pip takes a built wheel or nothing, so a
             # source distribution can never run its own setup code at
             # install time, and the floor keeps the install on the major
             # this plugin was measured with.
             "--only-binary", ":all:",
             "--target", str(pylibs), PILLOW_SPEC, FREETYPE_SPEC, NUMPY_SPEC],
            # "-m" puts the working folder first on sys.path. The hook's
            # working folder is the user's project, so pip runs from the
            # plugin's own data folder, where a project cannot plant a module.
            cwd=str(pylibs), capture_output=True, timeout=300)
    except Exception:
        return False
    return ensure_pillow()


def drop_links():
    """Remove every symbolic link and junction directly inside .claude/tmp.

    A cloned project can commit .claude/tmp/densepack-totals.json as a link to
    a file in the user's home, and the next write to that name would
    overwrite the file it points at. Removing a link removes only the link.
    A .claude or .claude/tmp that is itself a link is left alone: the scan
    would reach the folder it points at, and disabled() stands down for it."""
    from common import project_dir, through_link
    if through_link(project_dir(), tmp_dir()):
        return
    from common import is_junction, project_dir as _proj, through_link as _link
    # Every vault folder the plugin writes into, not .claude/tmp alone: a
    # planted name in any of them takes a write the same way.
    vault = vault_dir()
    for folder in (tmp_dir(), vault / "images", vault / "instructions",
                   vault / "drop-gate", vault / "not-converted",
                   vault / "to-draw", vault / "drop"):
        if _link(_proj(), folder):
            continue
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    os.unlink(entry.path)
                elif is_junction(entry.path):
                    os.rmdir(entry.path)
                # A second hard link is a real directory entry, so only the
                # link count tells it from an ordinary file, and a write to
                # the name would land in the file it shares. os.stat, not the
                # entry's own: on Windows a DirEntry serves the folder scan's
                # cached data, where the link count always reads 1.
                #
                # The link is BROKEN, not unlinked: both names carry the same
                # count, so unlinking would as often delete the plugin's own
                # image as the planted twin. A copy moved onto the name keeps
                # the content and leaves the other name pointing elsewhere.
                elif (entry.is_file(follow_symlinks=False)
                        and os.stat(entry.path).st_nlink > 1):
                    # mkstemp, never a name built from this one: a part name
                    # a project can work out would take the copy through a
                    # link planted there, and the move would then put that
                    # link onto the plugin's own name.
                    import shutil as _shutil
                    import tempfile as _tempfile
                    fd, part = _tempfile.mkstemp(dir=str(folder),
                                                 prefix=".densepack-unlink-")
                    os.close(fd)
                    try:
                        _shutil.copyfile(entry.path, part)
                        os.replace(part, entry.path)
                    except OSError:
                        # A file another process holds open refuses the move
                        # on Windows. The copy goes, or the to-draw scan
                        # converts it into an image nobody asked for.
                        try:
                            os.unlink(part)
                        except OSError:
                            pass
            except OSError:
                pass


def main():
    # The event is read before the switch is checked, because the off
    # switch is per session and the id that names
    # the session is on the event.
    event = read_event()
    # Links go first, off or on. A project that commits the off flag beside a
    # linked settings file would otherwise keep the link until /densepack
    # writes the settings through it.
    drop_links()
    if disabled(event.get("session_id")):
        return 0
    clear_stale_blocks()
    prune_old_files()
    record_lead_session(event)
    ensure_vault_folders()
    pillow_ok = install_pillow()
    draw_instruction_images()
    packed_note = None
    if pillow_ok:
        # CLAUDE.md, CLAUDE.local.md and MEMORY.md reach every call as text.
        # pack_instructions turns each into images behind a pointer, from the
        # next session on, because Claude Code loads them before this hook.
        try:
            import pack_instructions
            packed_note = pack_instructions.converted_note(
                pack_instructions.convert_all(event, "opus"))
        except Exception as err:  # noqa: BLE001
            sys.stderr.write("DensePack pack_instructions: %s\n" % err)
    from common import bash_first_off
    deliver_context(pillow_ok, event.get("model"), bash_first_off(), packed_note)
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
        sys.stderr.write("DensePack %s: %s\n" % ("bootstrap.py", err))
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
