"""The SessionStart hook. It runs when a session opens, and again after a
resume, a clear or a compact.

HOW THIS FILE FITS. The hook runs these steps before anything else happens:
- It removes links that a project put in the plugin's working folders.
- It deletes stale flags and old working files, and it records the lead
  session.
- It makes the vault folders.
- It installs Pillow, the image library, with freetype-py and NumPy, in the
  plugin's own private folder. Without Pillow the plugin cannot make an
  image, and each other script does nothing.
- It packs the instruction images. It converts CLAUDE.md, CLAUDE.local.md
  and MEMORY.md into images behind a pointer.
- When the lead gets images, it sends READ_TOOL_LINE, the rules of
  plugin/rules/STYLE-RULES.md, SUBAGENT_BRIEF_LINE and the name of the
  project map image to the model. READ_TOOL_LINE says only that
  DensePack is on. The guidance for images goes beside the first image.
- It shows the savings table from the last conversation, and a warning
  when the Pillow install failed.

The hook installs Pillow once into CLAUDE_PLUGIN_DATA. That folder stays
after a plugin update. Claude Code installs only Node dependencies by itself.
This hook installs the Python dependencies. The hook never blocks a session.
If the Pillow install fails, each other hook does nothing, text reaches the
model as it does without the plugin, and a message on screen tells you.

Four things go on screen through systemMessage, the field that Claude Code
shows directly:
- the note that DensePack set CLAUDE_CODE_THRIFTY_SONIC in settings.json
- the note that DensePack converted an instruction file
- the totals table from the last conversation
- a failed Pillow install
Everything else goes to the lead as context.
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

# Session start deletes working files older than this. Each packed report and
# each packed brief leaves a PNG and a source text file. No other step
# removes them.
#
# The reason for 7 days and for session start only. The lead reads a report
# image again in the session that made it, and sometimes in a session days
# later. A resumed session can also Grep the text copy of an old Bash output.
# For that reason a file younger than 7 days stays. The hook deletes nothing
# during a session. No file disappears while the lead uses it. The prune
# never touches the manifest, the totals or the settings. They are the
# record, not the working copy.
# The densepack-start- markers are on the list because the marker of a
# crashed agent never reaches the code that deletes it on a normal finish. An
# agent runs for much less than 7 days. A running agent never loses its
# marker.
KEEP_HOURS = 7 * 24

# A hook claims a run marker within milliseconds of the event that names it
# and never reads it again. One hour is more than enough. Under the 24 hour
# rule, tens of thousands of markers collect in .claude/tmp, and a listing of
# the folder then takes seconds inside each Bash call.
RAN_MARKER_HOURS = 1
# Card sets in the machine-wide cache stay this long after their last hit.
CARD_KEEP_DAYS = 7
# The bash names and the legend sidecar are working files by the same test as
# each other name here. The vault keeps the permanent copy, and
# prune_old_files() runs only at session start.
PRUNE_PREFIXES = ("densepack-img-", "densepack-brief-", "densepack-briefsrc-",
                  "densepack-src-", "densepack-code-", "densepack-briefcode-",
                  "densepack-report-", "densepack-card-sent",
                  "densepack-start-", "densepack-readonce-",
                  "densepack-ran-",
                  "densepack-bash-", "densepack-bashsrc-",
                  "densepack-bashout-", "densepack-legend-")


def prune_old_files():
    """Delete working files older than KEEP_HOURS. Return the count and the bytes.

    The function ignores a failure on purpose. The operating system does not
    delete a file that another program holds open. Such a file is no reason
    to stop a session.
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
    # images/, drops/ and drop-gate/ under the vault use the same age rule as
    # each other working file. Without it they grow without limit. The next
    # Read of the same file packs a drop image again. Deleting an old one
    # loses nothing. This step does not touch the conversation folders or
    # vault_trim(). Those hold the permanent copy.
    base = vault_dir()
    from common import project_dir, through_link
    for name, deep in (("images", False), ("drops", False), ("drop-gate", True)):
        # A folder that is a link or a junction, or is under one, can lead to
        # your own files. The prune deletes nothing through a link.
        folder = base / name
        if through_link(project_dir(), folder):
            continue
        gone, bytes_gone = sweep([p for p in listing(folder, deep)
                                  if not through_link(folder, p)], None)
        removed += gone
        freed += bytes_gone
    # A hook killed during a pack leaves its per-path folder under drop-gate.
    # This step removes empty folders, deepest first. rmdir fails on a folder
    # that still holds a file. The step touches nothing through a link.
    gate = base / "drop-gate"
    if not through_link(project_dir(), gate):
        for sub in sorted(listing(gate, True), key=lambda p: len(p.parts), reverse=True):
            try:
                # Only a folder untouched for an hour goes. A running pack
                # made its folder moments ago and copies into it next.
                if (sub.is_dir() and not through_link(gate, sub)
                        and sub.stat().st_mtime < time.time() - 3600):
                    sub.rmdir()
            except OSError:
                pass
    # The Read gate stages its copy outside the project, in a
    # densepack-stage-<random> folder of the system temp folder. A hook
    # killed during a pack leaves that folder and its one copy. Only a folder
    # untouched for an hour goes, and nothing through a link.
    import tempfile
    for sub in listing(Path(tempfile.gettempdir())):
        try:
            if (sub.name.startswith("densepack-stage-") and sub.is_dir()
                    and not sub.is_symlink()
                    and sub.stat().st_mtime < time.time() - 3600):
                for f in sub.iterdir():
                    if f.is_file() and not f.is_symlink():
                        f.unlink()
                sub.rmdir()
        except OSError:
            pass
    # The machine-wide card cache. Each edit to a signed renderer file adds a
    # card set. Each cache hit touches its folder. A folder untouched for
    # CARD_KEEP_DAYS belongs to a renderer that nothing runs.
    stale = time.time() - CARD_KEEP_DAYS * 86400
    for folder in listing(CARD_CACHE):
        try:
            if folder.is_dir() and folder.stat().st_mtime < stale:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed, freed


# The source texts for each instruction image and each Haiku text file. The
# hook reads them from an instructions folder in the plugin, never from the
# vault. DensePack 2.0 ships no instructions folder, so this code makes no card.
INSTRUCTION_TEXTS = {"lead": "lead.txt", "worker": "worker.txt",
                     "facts": "facts.txt", "shared": "shared.txt",
                     "fullrules": "fullrules.txt",
                     "check": "check.txt", "reader": "reader.txt",
                     "runner": "runner.txt", "tune": "tune.txt"}

# The lead's three texts, joined in reading order and packed as one image.
# Three separate images cost three Read calls, and three turns, before the
# agent starts the task. One image costs one.
ALL_LEAD = ("lead", "shared", "fullrules")

# The worker's two texts, joined the same way and for the same reason.
ALL_WORKER = ("worker", "shared")

# The fact checker's two texts, its own card and the shared card.
ALL_CHECK = ("check", "shared")

# The source reader's two texts. A source reader opens the files that the
# brief names.
ALL_READER = ("reader", "shared")

# The command runner's two texts. A runner runs the commands that the brief
# names.
ALL_RUNNER = ("runner", "shared")

# The tuning page is one text on its own. It holds the procedure that a lead
# follows to read your own records, count what they do and name the fix for
# each count that misses a measured condition.
ALL_TUNE = ("tune",)

# Each joined page that a lead reads, packed once. The stem names the image
# file and the POINTERS.txt row. Neither page is a card. No spawn names
# either one.
JOINED_IMAGES = (("allrules", ALL_LEAD), ("tune", ALL_TUNE))

# Each identity card, with one folder each under instructions/. A card's
# folder can get a second page with no code change and no name collision with
# another card. Each row is (card name, image stem, the INSTRUCTION_TEXTS keys
# joined into the page). The next run packs a card added here. The SHA gate
# in ensure_instruction_image() does not change the pages already on disk.
CARD_IMAGES = (("worker", "workerrules", ALL_WORKER),
               ("check", "checkrules", ALL_CHECK),
               ("reader", "readerrules", ALL_READER),
               ("runner", "runnerrules", ALL_RUNNER))

# The single role images, each pair (image stem, INSTRUCTION_TEXTS key),
# packed once into instructions/ for all models.
ROLE_IMAGES = (("role-worker", "worker"),)


# The vault folders that session start makes. They come before
# draw_instruction_images() because a folder costs nothing to make, with or
# without Pillow. You copy a file into to-pack/ to have it packed.
# DensePack then moves the file into to-pack/packed/ beside its images.
VAULT_FOLDERS = (
    ("to-pack",),
    ("to-pack", "packed"),
)


def ensure_vault_folders():
    """Create each vault folder that the layout table names. mkdir with
    exist_ok does not change a folder that exists or its file times. This
    runs before the Pillow check. Nothing here needs Pillow, and a resume, a
    clear or a compact must find each folder present, the same as a first
    run makes them."""
    from common import project_dir, through_link
    base = vault_dir()
    # A committed vault link puts these folders, and the .gitignore below, in
    # the folder that the link names.
    if through_link(project_dir(), base):
        return
    for parts in VAULT_FOLDERS:
        base.joinpath(*parts).mkdir(parents=True, exist_ok=True)
    ignore_working_folders()


def ignore_working_folders():
    """Put a .gitignore holding one star in the vault and in .claude/tmp.

    The two folders hold verbatim session content. That content is the words
    of each file whose Read DensePack redirected, the output of each Bash
    command, and the legend sidecar beside each image. The two folders are
    inside your project. Without this file, a first commit adds them to the
    repository. pip writes the same one-line file into a new virtual
    environment for the same reason. The plugin does not rely on an ignore
    rule in the project.
    """
    from common import project_dir, through_link
    for folder in (vault_dir(), tmp_dir()):
        try:
            if through_link(project_dir(), folder):
                continue
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ".gitignore"
            # lexists is true for a link with no target, and mode "x" opens
            # with O_EXCL, which fails on any link at the name.
            if os.path.lexists(path):
                continue
            with open(path, "x", encoding="utf-8") as fh:
                fh.write("*\n")
        except OSError:
            continue


def instruction_text(filename):
    """Return the shipped text of one file in the instructions folder, or None
    when the file is missing. A missing file is not an error here. A folder
    still gets the texts that it has."""
    path = Path(__file__).resolve().parents[1] / "instructions" / filename
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def joined_text(keys):
    """Return the named instruction texts, stripped and joined in reading
    order with a blank line between each. Return an empty string when none
    of the named files reads. draw_instruction_images() skips an empty
    string."""
    parts = [instruction_text(INSTRUCTION_TEXTS[key]) for key in keys]
    return "\n\n".join(part.strip() for part in parts if part)


# Each card that this process packed, keyed on the digest of its text, size
# and font, because draw_instruction_images() can request the same card more
# than once.
_DRAWN = {}

# EACH CARD THAT ANY LOCAL PROCESS PACKED. One folder per digest
# under ~/.claude/densepack-cards holds the card's page files. Without it, a
# new project folder packs the whole card set from nothing. That takes
# minutes at session start. The digest holds the text, the size and the
# font. A card that matches has the same bytes, and a copy is the same page.
CARD_CACHE = Path.home() / ".claude" / "densepack-cards"


def _cached_card(digest):
    """The first page of a cached card for this digest, or None."""
    first = CARD_CACHE / digest / "card-1.png"
    if not first.is_file():
        return None
    # A hit touches the folder. prune_old_files() uses that time to tell a
    # card set in use from the card set of a renderer that no longer exists.
    try:
        os.utime(first.parent, None)
    except OSError:
        pass
    return first


def _cache_card(digest, first_page):
    """Copy the pages of a new card into the machine cache. A failure costs
    only the pack time of the next folder.

    The pages go first into a folder that carries this process id in its
    name. One rename then moves that folder onto the digest. A process that
    reads the cache while another writes it never copies a half-written
    page. A digest folder that exists stays as it is, because the same
    digest is the same bytes.
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
# image cache key. Setting one never packs the instruction images again.
NOT_PIXEL_SETTINGS = {"DENSEPACK_STYLE", "DENSEPACK_CODE_PX", "DENSEPACK_HELPER_MEMORY_MB",
                      "DENSEPACK_SERIAL_DRAW", "DENSEPACK_DASHBOARD_NETWORK", "DENSEPACK_ARENA",
                      "DENSEPACK_ARENA_ROOT", "DENSEPACK_CONTEXT_TOKENS"}


def renderer_signature():
    """Return a short digest of all inputs, besides text and size, that set a
    card's pixels. The inputs are the bytes of style.py, codepack.py,
    freetype_glyph.py, densepack.py and common.py in the folder this plugin
    runs from, and each DENSEPACK_ environment variable except the names in
    NOT_PIXEL_SETTINGS and the DENSEPACK_BENCH_ names. card_digest()
    includes this digest. An edit to style.py changes the digest, and the
    machine cache never serves an old card to a new folder."""
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
        # hashes. DENSEPACK_CODE_PX is the px that the digest already holds.
        # Neither belongs here. With DENSEPACK_CODE_PX in the key, a process
        # that sets it and a process that does not pack the same card set
        # twice.
        for key in sorted(os.environ):
            if (key.startswith("DENSEPACK_") and key not in NOT_PIXEL_SETTINGS
                    and not key.startswith("DENSEPACK_BENCH_")):
                h.update(("%s=%s;" % (key, os.environ[key])).encode("utf-8"))
        _RENDERER_SIG = h.hexdigest()[:16]
    return _RENDERER_SIG


def card_digest(text, px):
    """Return the SHA-256 that names one packed card. The inputs are its
    text, its pixel size, the font's name and byte size, and the bytes of
    the style file in use.

    The digest uses the font's NAME and size, not its path. The hooks run
    from the folder that Claude Code loads the plugin from. The same font at
    two paths gives two digests and packs each card again.

    The style file is part of the digest because the cards come from a
    machine-wide cache. A recipe that moves a glyph must pack a new card. It
    must not serve the card packed under the old recipe.
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
    """Remove each page that an earlier pack of this card left beside the
    stem. Without this step, a card that shrank from three pages to two
    keeps an old third page, and the cache copies that page to each
    folder."""
    for old in Path(stem_path).parent.glob(Path(stem_path).name + "-*.png"):
        try:
            old.unlink()
        except OSError:
            pass


def sealed_digest(digest):
    """Return the text of the .hash file beside an instruction image. That
    text is the digest, sealed with the local seal key. A project can
    compute the plain digest and commit it with its own image. It cannot
    compute the seal."""
    from common import _row_seal
    return _row_seal({"card_digest": digest}) or digest


def ensure_instruction_image(text, px, stem_path):
    """Pack one instruction image at str(stem_path) + "-1.png". A SHA-256 of
    the text, the pixel size and the font file gates the pack. The function
    records that SHA-256 beside the image in str(stem_path) + ".hash". An
    unchanged text packs nothing. The size is part of the hash. A size
    change packs the image again. The font file is part of the hash. A font
    change packs each image again, even when the text is the same.
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
    # ONE PACK PER DIGEST. The same text at the same size packs the same
    # bytes. For a digest that this process already packed, or that the
    # machine cache holds, the function copies the pages and does not pack
    # them again. A packed page takes about 20 seconds, and a file copy takes
    # almost no time. Copying also keeps each folder that a consumer already
    # reads from.
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
        # The rules image goes through the code renderer. One renderer serves
        # all images.
        import codepack
        # The text keeps its real newlines, because flatten() with the
        # pilcrow mark makes pack_code() render the word "[pilcrow]" at each
        # line end.
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
    """Write POINTERS.txt, with one line per instruction file for model,
    purpose and path. A byte compare comes first. An unchanged set writes
    nothing."""
    text = "\n".join(lines) + "\n"
    encoded = text.encode("utf-8")
    if path.is_file() and path.read_bytes() == encoded:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def draw_instruction_images():
    """Pack each role, joined and card image under
    .claude/densepack-vault/instructions/. A SHA-256 of the text plus the
    pixel size gates each image. Unchanged text packs nothing.
    Copy the Haiku text files, with a byte compare first. Write
    POINTERS.txt, with a byte compare first. The function is safe to run
    many times a day. A resume, a clear and a compact each run main() again.
    """
    # A copy of the plugin with no instructions folder has no texts to pack.
    # There this function makes, writes and deletes nothing.
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
    # The folders fable, opus and sonnet under instructions/ hold the card
    # sets of an earlier version, and nothing reads them. This step removes
    # them.
    for old in ("fable", "opus", "sonnet"):
        shutil.rmtree(base / old, ignore_errors=True)


# reader_warning() returns no warning, because all models get one image at
# one size and no mismatch of model and size can happen.
def reader_warning(model):
    return None


# Without Pillow, each hook does nothing and the plugin saves nothing. With
# no message, you can run a whole session and think that DensePack packed the
# reports. This warning states the fact once, at session start, and only when
# the install failed.
PILLOW_WARNING = (
    "DensePack cannot make images. Pillow, freetype-py or NumPy is missing. DensePack could not "
    "install it. DensePack packs nothing and saves nothing. To install them, run "
    '%s"%s" -m pip install --user pillow freetype-py numpy '
    "(on Debian and Ubuntu, add --break-system-packages)" % ("& " if os.name == "nt" else "", sys.executable))


# READ_TOOL_LINE is the intro that the lead and each subagent get. It says only
# that DensePack is on. The guidance for images goes beside the first image
# instead: common.FIRST_IMAGE_NOTE says why. The note gives no search rule, so
# the agent searches as it does without DensePack.
READ_TOOL_LINE = "DensePack is on."

# No sentence here tells the model how many files to read or when. The
# plugin changes how a file arrives, not what the model does. An order to
# read all files in one turn makes the model Read more files than it needs,
# and the session costs more.

# The lead alone gets this line. subagent_start.py sends subagents READ_TOOL_LINE.
# If the lead repeats the image rules in a brief, the subagent reads whole
# files, which costs more, so only the lead gets this line.
SUBAGENT_BRIEF_LINE = (
    "Subagents get this same note from DensePack. Write a subagent's task as "
    "you would without DensePack: do not tell it that files arrive as images, "
    "and do not ask it to check the images.")

# DensePack 2.0: the rules for less code and plain replies, as text in the start note. The same rules as an image
# were followed less well in the benches of 10 October 2026.
RULES_TEXT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules", "STYLE-RULES.md")


def rules_text():
    """The rules with the line that turns them on, or None when the plugin has no rules file. The lead gets
    them in the start note, and subagent_start.py gives them to each subagent."""
    if not os.path.isfile(RULES_TEXT):
        return None
    with open(RULES_TEXT, encoding="utf-8") as f:
        return ("DENSEPACK RULES ACTIVE. Follow these rules for all code, tests and replies until the "
                "session ends.\n\n" + f.read().strip())


def rules_line(cwd=None):
    """The start-note text that turns the rules on, then the folder map of the project, or None when the
    plugin has no rules file."""
    text = rules_text()
    if text is None:
        return None
    # Only the lead gets this line: subagent_start.py gives each subagent the same rules.
    text += ("\n\nEach subagent gets these same rules from DensePack when it starts, so a subagent's task "
             "does not need to repeat them.")
    import projectmap
    folder_map = projectmap.build(cwd or os.getcwd())
    if not folder_map:
        return text
    image = map_image(folder_map)
    if image is None:
        return text + "\n\n" + folder_map
    return text + ("\n\nPROJECT MAP: the image %s lists each folder of this project, its source and config files, "
                   "and the names each file defines. Read it with the Read tool in your first turn, before any "
                   "other command." % image)


def map_image(folder_map):
    """Draw the project map as one image in the vault and return its path, or None when it does not draw. The
    image costs about half the tokens of the same text, so the map can name what each file defines."""
    try:
        import pack_instructions
        paths, _cost = pack_instructions.draw(folder_map, "project-map", vault_dir() / "instructions" / "map",
                                              "opus")
        return str(paths[0]) if len(paths) == 1 else None
    except Exception as err:  # noqa: BLE001 - the text map is the fallback
        sys.stderr.write("DensePack project map image: %s\n" % err)
        return None


def lead_reads_images(model):
    """Return True when DensePack sends images to a lead on this model. The
    model is the one that session start names, or the recorded lead when the
    event names none."""
    from common import (READER_SIZES, lead_gets_images, lead_model_name,
                        reader_gets_images)
    if isinstance(model, dict):
        model = model.get("id") or model.get("display_name")
    name = str(model or "").lower()
    if not name:
        # At session start Claude Code 2.1.288 names no model, and the
        # transcript does not exist yet. lead_gets_images() gives text for an
        # unknown model, and the session then gets no note. The note follows
        # the reader setting here, as in DensePack 1.3.3. Each Read still
        # gives text until DensePack knows the model.
        if not lead_model_name():
            return reader_gets_images(resolved_reader())
        return lead_gets_images()
    return reader_gets_images(next((k for k in READER_SIZES if k in name), None))


BASH_FIRST_NOTE = (
    "DensePack set CLAUDE_CODE_THRIFTY_SONIC to 0 in ~/.claude/settings.json. "
    "Auto mode then stops telling Claude to read files with Bash. The setting "
    "applies from your next session. DensePack converts Bash and PowerShell "
    "output of 400 characters or more, but a shell read still costs a little "
    "more than a Read.")
WINDOWS_BASH_NOTE = (
    "DensePack set EMBEDDED_SEARCH_TOOLS to 1 and CLAUDE_CODE_USE_POWERSHELL_TOOL to 0 in "
    "~/.claude/settings.json. From your next session, Claude Code runs commands and searches in Git Bash, "
    "and DensePack packs all of that output.")


def deliver_context(pillow_ok, model, bash_first_set=False, packed_note=None, cwd=None):
    parts = []
    shown = []
    if bash_first_set and "CLAUDE_CODE_THRIFTY_SONIC" in bash_first_set:
        shown.append(BASH_FIRST_NOTE)
    if bash_first_set and "EMBEDDED_SEARCH_TOOLS" in bash_first_set:
        shown.append(WINDOWS_BASH_NOTE)
    from common import windows_bash_keys_missing, WINDOWS_BASH_KEYS
    missing = windows_bash_keys_missing()
    if missing:
        shown.append("DensePack could not write ~/.claude/settings.json. Add these lines to its \"env\" block, "
                     "then restart Claude Code: " + ", ".join('"%s": "%s"' % (k, WINDOWS_BASH_KEYS[k]) for k in missing)
                     + ". With them, Claude Code runs commands and searches in Git Bash, and DensePack packs "
                     "all of that output.")
    if packed_note:
        shown.append(packed_note)
    if pillow_ok and lead_reads_images(model):
        parts.append(READ_TOOL_LINE)
        rules = rules_line(cwd)
        if rules:
            parts.append(rules)
        parts.append(SUBAGENT_BRIEF_LINE)
    # The last session's table comes from outside the project. A cloned
    # project cannot put its own words here.
    from common import machine_state_dir
    marker = machine_state_dir() / "densepack-last-session.md"
    if marker.is_file():
        summary = marker.read_text(encoding="utf-8").strip()
        marker.unlink(missing_ok=True)
        # The wrap-up totals go in systemMessage, the field that Claude Code
        # shows on screen, because a lead that must relay them skips them. A
        # quiet-mode summary has no table row and stays out of systemMessage,
        # because quiet mode prints nothing until you ask.
        if any(line.startswith("|") for line in summary.splitlines()):
            shown.append(summary)
            parts.append("DensePack showed this table on screen from the "
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
    # The pointer hook runs in each session, subagents included, and the
    # queue is one shared file. Without this marker, a subagent's first tool
    # call can empty the queue and get the lead's report pointers.
    # SessionStart runs for a lead session and never for a subagent. The ids
    # that this function records are exactly the sessions allowed to collect.
    # The marker holds a LIST, not one id. A project open in two windows
    # keeps the receipts of the two windows.
    sid = event.get("session_id")
    if sid:
        add_lead(sid)


def clear_stale_blocks():
    """A blocked flag lasts for one agent turn. An asked flag lasts for the
    whole run of one agent. A flag still on disk at session start belongs to
    an agent that finished. A flag left in place disables the enforcement
    check for that agent id.

    densepack-asked-* is the one-ask marker that subagent_stop.py never
    removes during a session. This function is the only step that clears it.

    The key of densepack-floorpass-* is one turn's prompt_id, not an agent
    id. The flag becomes stale when the turn ends. This sweep only keeps the
    folder clean across sessions."""
    for pattern in ("densepack-blocked-*", "densepack-asked-*",
                    "densepack-floorpass-*"):
        for flag in tmp_dir().glob(pattern):
            try:
                flag.unlink()
            except OSError:
                pass


# The floor is 12, the Pillow major that the plugin's measurements used.
# There is no ceiling. A later major still installs, and an earlier one does not.
PILLOW_SPEC = "pillow>=12"
FREETYPE_SPEC = "freetype-py>=2"  # ships a wheel with libfreetype inside, which --only-binary needs
NUMPY_SPEC = "numpy>=2"  # codepack.py blends each glyph with it


def install_pillow():
    """Return True when Pillow imports. Otherwise install Pillow, freetype-py
    and NumPy into the pylibs folder of CLAUDE_PLUGIN_DATA, and return True
    when Pillow then imports.

    It runs before the hook sends the context. The first session on a
    machine can then pack its images, and the session start message shows
    its result on screen.
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
             # --upgrade, because pip skips a package already in --target.
             # After a Python upgrade, the old NumPy stays and fails to import.
             "--upgrade",
             # --only-binary means pip takes a built wheel or nothing. A
             # source distribution then never runs its own setup code at
             # install time. The floor keeps the install on the major that
             # the plugin's measurements used.
             "--only-binary", ":all:",
             "--target", str(pylibs), PILLOW_SPEC, FREETYPE_SPEC, NUMPY_SPEC],
            # "-m" puts the working folder first on sys.path. The hook's
            # working folder is your project. For that reason pip runs from
            # the plugin's own data folder, where a project cannot plant a
            # module.
            cwd=str(pylibs), capture_output=True, timeout=300)
    except Exception:
        return False
    return ensure_pillow()


def drop_links():
    """Remove each symbolic link and junction directly inside .claude/tmp
    and inside each vault folder that the plugin writes into. Break each
    second hard link there with a copy.

    A cloned project can commit .claude/tmp/densepack-totals.json as a link
    to a file in your home folder. The next write to that name then
    overwrites the file that the link names. Removing a link removes only
    the link. The function does nothing when .claude or .claude/tmp is
    itself a link. A scan there reaches the folder that the link names, and
    disabled() stops the hooks for it. The function also skips a vault
    folder that is a link or is under one."""
    from common import project_dir, through_link
    if through_link(project_dir(), tmp_dir()):
        return
    from common import is_junction, project_dir as _proj, through_link as _link
    # Each vault folder that the plugin writes into, not .claude/tmp alone. A
    # planted name in any of them receives a write the same way.
    vault = vault_dir()
    for folder in (tmp_dir(), vault / "images", vault / "instructions",
                   vault / "drop-gate", vault / "not-converted",
                   vault / "to-pack", vault / "to-pack" / "packed",
                   vault / "drop"):
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
                # A second hard link is a real directory entry. Only the link
                # count tells it from an ordinary file. A write to the name
                # goes into the file that it shares. The code uses os.stat,
                # not the entry's own stat. On Windows a DirEntry returns the
                # cached data of the folder scan, where the link count is
                # always 1.
                #
                # The code BREAKS the link and does not unlink it. The two
                # names have the same count. An unlink deletes the plugin's
                # own image as often as the planted twin. A copy moved onto
                # the name keeps the content, and the other name then refers
                # to a different file.
                elif (entry.is_file(follow_symlinks=False)
                        and os.stat(entry.path).st_nlink > 1):
                    # mkstemp, never a name built from this one. A project
                    # can predict a built part name and plant a link there.
                    # The copy then goes through that link, and the move
                    # puts that link onto the plugin's own name.
                    import shutil as _shutil
                    import tempfile as _tempfile
                    fd, part = _tempfile.mkstemp(dir=str(folder),
                                                 prefix=".densepack-unlink-")
                    os.close(fd)
                    try:
                        _shutil.copyfile(entry.path, part)
                        os.replace(part, entry.path)
                    except OSError:
                        # On Windows the move fails on a file that another
                        # process holds open. The code deletes the copy.
                        # Otherwise the to-pack scan packs it into an
                        # unwanted image.
                        try:
                            os.unlink(part)
                        except OSError:
                            pass
            except OSError:
                pass


def main():
    # The hook reads the event before it checks the switch. The off switch is
    # per session, and the session id is in the event.
    event = read_event()
    # Links go first, with DensePack off or on. Otherwise a project that
    # commits the off flag beside a linked settings file keeps the link until
    # /densepack writes the settings through it.
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
        # CLAUDE.md, CLAUDE.local.md and MEMORY.md reach each call as text.
        # pack_instructions packs each one into images behind a pointer. The
        # change applies from the next session, because Claude Code loads
        # them before this hook runs. For this reason the pack runs in a
        # process of its own, and the session does not wait for it. The note
        # of the last pack shows now.
        try:
            import pack_instructions
            packed_note = pack_instructions.take_background_note()
            pack_instructions.start_background(event)
        except Exception as err:  # noqa: BLE001
            sys.stderr.write("DensePack pack_instructions: %s\n" % err)
    from common import bash_first_off
    deliver_context(pillow_ok, event.get("model"), bash_first_off(), packed_note, event.get("cwd"))
    return 0


def guarded_main():
    """Never let an exception out of this hook.

    main() runs inside a try. A fault in main() cannot change the result of
    the event that started the hook. The function writes the error to
    stderr, where the fault stays visible. The exit code stays 0.
    """
    try:
        return main()
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack %s: %s\n" % ("bootstrap.py", err))
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
