"""Pack the instruction files that Claude Code loads as text into images.

Claude Code puts each CLAUDE.md, CLAUDE.local.md and the auto memory index
MEMORY.md into each request as text, before any hook runs, and sends them
again on each call. No hook can replace that text with an image. A Read can.

Each file becomes three parts. The pointer and the .bak stay side by side,
and the images go into the images folder of that file.

    CLAUDE.md                  a short pointer, the only text Claude Code loads
    CLAUDE.md.densepack.bak    the original text, byte for byte, which Claude
                               Code never loads because of its name
    <images folder>/<label>-image-N-of-M-DensePack.png
                               the text packed as images, which the pointer
                               names by full path for the Read tool

The pointer tells the agent that DensePack made the images and names each
image. It tells a model that gets text from DensePack, such as Haiku, to
read the .bak.

Claude Code loads these files before SessionStart hooks run. A conversion
reaches the model from the next session on.

At each session start, for each file:
- A pointer with text added below it. The added text moves into the .bak,
  because the auto memory of Claude Code appends new index lines to
  MEMORY.md, and you can add a rule to CLAUDE.md.
- A .bak that changed. The code packs the images again.
- A file that is not a pointer. It is the new original. The code keeps an
  older .bak as .densepack.bak.old-N and converts the file.
- A file whose images cost more than its text, with the pointer counted. It
  stays text, and the code restores the original in place of a pointer.

restore_all() restores each original. /dense-remove runs it.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OPEN = "<!-- densepack-pointer: DensePack wrote this block -->"
CLOSE = "<!-- /densepack-pointer -->"
BAK = ".densepack.bak"
IMAGE_NAME = re.compile(r"-image-\d+-of-\d+-DensePack\.png$")
# The renderer limits for a Read. Past these limits, a file stays text.
MAX_CHARS = 250000
MAX_LINES = 6000
PRIVATE_MARKS = ("\ue000", "\ue001", "\ue002", "\ue003")


def read(path):
    """Return the text of the file with its line endings kept."""
    with open(str(path), encoding="utf-8", newline="") as fh:
        return fh.read()


def joined(original, added):
    """Return the original plus the added text, in the original line endings."""
    nl = "\r\n" if "\r\n" in original else "\n"
    added = added.replace("\r\n", "\n").replace("\n", nl)
    return original.rstrip("\r\n") + nl + added + nl


def plain(text):
    """Return the text for the renderer, which takes no carriage return."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def state_file():
    return Path.home() / ".claude" / "densepack-state" / "packed-instructions.json"


def load_state():
    try:
        return json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state):
    from common import write_text_atomic
    state_file().parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(state_file(), json.dumps(state, indent=1, sort_keys=True))


def targets(event):
    """Return (file, label, what the file is, images folder) for each file
    that Claude Code loads as instructions in this session."""
    from common import project_dir
    home = Path.home() / ".claude"
    found = folder_targets(Path(project_dir()))
    found.append((home / "CLAUDE.md", "user-CLAUDE.md", "your user CLAUDE.md, for every project",
                  home / "densepack-state" / "instruction-images"))
    transcript = event.get("transcript_path")
    if transcript:
        folder = Path(transcript).parent
        found.append((folder / "memory" / "MEMORY.md", "memory-MEMORY.md",
                      "this project's auto memory index, MEMORY.md",
                      home / "densepack-state" / "instruction-images" / folder.name))
    return found


def folder_targets(project):
    """Return the three project instruction files of one folder."""
    images = project / ".claude" / "densepack-vault" / "instruction-images"
    return [
        (project / "CLAUDE.md", "project-CLAUDE.md", "this project's CLAUDE.md", images),
        (project / ".claude" / "CLAUDE.md", "project-dot-claude-CLAUDE.md",
         "this project's .claude/CLAUDE.md", images),
        (project / "CLAUDE.local.md", "project-CLAUDE.local.md", "this project's CLAUDE.local.md", images),
    ]


def convert_folder(folder, reader="opus"):
    """Convert the CLAUDE.md files of another folder without a session there.

    A session that started in another folder never loads the CLAUDE.md of
    that folder, and the agent that runs this reads none of it. The vault
    gets the same .gitignore that session start writes. The images then stay
    out of the commits of that folder."""
    project = Path(folder).resolve()
    if not project.is_dir():
        return [(str(project), "not a folder")]
    vault = project / ".claude" / "densepack-vault"
    vault.mkdir(parents=True, exist_ok=True)
    ignore = vault / ".gitignore"
    if not os.path.lexists(str(ignore)):
        with open(str(ignore), "x", encoding="utf-8") as fh:
            fh.write("*\n")
    state = load_state()
    log = []
    for path, label, what, images in folder_targets(project):
        try:
            log.append((str(path), convert_one(path, label, what, images, reader, state)))
        except Exception as exc:  # noqa: BLE001
            log.append((str(path), "failed: %s" % exc))
    save_state(state)
    return log


def split_pointer(text):
    """Return (is a pointer, text outside the pointer block)."""
    start = text.find(OPEN)
    end = text.find(CLOSE)
    if start < 0 or end < start:
        return False, text
    outside = text[:start] + text[end + len(CLOSE):]
    return True, outside.strip("\r\n \t")


def pointer_text(what, bak, images):
    rows = [OPEN,
            "DensePack is on. It converted %s into %d image%s to save tokens."
            % (what, len(images), "" if len(images) == 1 else "s"),
            "The images hold the exact text of %s, which DensePack keeps unchanged." % bak.name,
            "Before any other work, read every image below with the Read tool, in order,"
            " and follow them as %s:" % what]
    rows += [str(p) for p in images]
    rows += ["A model DensePack sends text, such as Haiku, reads %s with the Read tool instead." % bak,
             "To change an entry, edit %s. Text added below this block moves there"
             " at the next session start." % bak.name,
             CLOSE, ""]
    return "\n".join(rows)


def text_tokens(text):
    from densepack import CHARS_PER_TOKEN
    return len(text) / CHARS_PER_TOKEN


def drawable(text):
    return (len(text) <= MAX_CHARS and text.count("\n") <= MAX_LINES
            and not any(m in text for m in PRIVATE_MARKS) and "\x00" not in text)


def label_images(folder, label):
    try:
        return sorted(p for p in folder.iterdir()
                      if p.name.startswith(label + "-image-") and IMAGE_NAME.search(p.name))
    except OSError:
        return []


def draw(text, label, folder, reader):
    """Pack text into <label>-image-N-of-M-DensePack.png. Returns (paths, cost)."""
    import codepack
    import densepack as dp
    from common import code_size, READER_SIZES
    folder.mkdir(parents=True, exist_ok=True)
    stem = folder / (label + ".draw")
    pages, _t, _l = codepack.pack_code(text, code_size(READER_SIZES[reader], reader), str(stem),
                                       python=False, legend=None, reader=reader, title=label)
    for old in label_images(folder, label):
        try:
            old.unlink()
        except OSError:
            pass
    total = len(pages)
    paths, cost = [], 0
    for n, (page, width, height) in enumerate(pages, 1):
        final = folder / ("%s-image-%d-of-%d-DensePack.png" % (label, n, total))
        dp.replace_retry(str(page), str(final))
        paths.append(final)
        cost += dp.image_cost(width, height)
    return paths, cost


def keep_old_bak(bak):
    n = 1
    while bak.with_name("%s.old-%d" % (bak.name, n)).exists():
        n += 1
    os.replace(str(bak), str(bak.with_name("%s.old-%d" % (bak.name, n))))


def restore(path, state):
    """Restore one original from its .bak, with the text added below the pointer."""
    from common import write_text_atomic
    bak = path.with_name(path.name + BAK)
    entry = state.pop(str(path), None)
    try:
        current = read(path)
    except OSError:
        current = ""
    is_pointer, added = split_pointer(current)
    if not is_pointer or not bak.is_file():
        return False
    original = read(bak)
    if added:
        original = joined(original, added)
    write_text_atomic(path, original)
    bak.unlink()
    for image in (entry or {}).get("images", []):
        try:
            Path(image).unlink()
        except OSError:
            pass
    return True


def convert_one(path, label, what, folder, reader, state):
    """Make the pointer, .bak and images of one file. Returns the log text."""
    from common import write_text_atomic
    if not path.is_file():
        return "absent"
    bak = path.with_name(path.name + BAK)
    current = read(path)
    is_pointer, added = split_pointer(current)
    if is_pointer:
        if not bak.is_file():
            # The original is gone. Keep what you added and drop the pointer.
            write_text_atomic(path, (added + "\n") if added else "")
            state.pop(str(path), None)
            return "pointer without its .bak, pointer removed"
        original = read(bak)
        if added:
            original = joined(original, added)
    else:
        original = current
    if not original.strip() or not drawable(original):
        if is_pointer:
            restore(path, state)
        return "kept as text"

    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()[:16]
    entry = state.get(str(path)) or {}
    images = [Path(p) for p in entry.get("images", [])]
    if entry.get("digest") == digest and entry.get("reader") == reader and images and all(
            p.is_file() for p in images):
        cost = entry.get("cost", 0)
    else:
        images, cost = draw(plain(original), label, folder, reader)
    pointer = pointer_text(what, bak, images)
    if cost + text_tokens(pointer) >= text_tokens(plain(original)):
        for image in images:
            try:
                image.unlink()
            except OSError:
                pass
        if is_pointer:
            restore(path, state)
        state.pop(str(path), None)
        return "kept as text, images cost more"

    # The code copies the original to the .bak before the pointer replaces it.
    if not is_pointer:
        if bak.exists():
            keep_old_bak(bak)
        import shutil
        shutil.copyfile(str(path), str(bak))
    elif added:
        write_text_atomic(bak, original)
    if current != pointer:
        write_text_atomic(path, pointer)
    state[str(path)] = {"digest": digest, "reader": reader, "images": [str(p) for p in images],
                        "cost": cost, "text_tokens": round(text_tokens(plain(original))), "label": label}
    return "%s, %d images, %d image tokens for %d text tokens" % (
        "pointer" if is_pointer else "converted", len(images), cost, round(text_tokens(plain(original))))


def converted_note(log):
    """Return one line for the screen when this session start converted a file."""
    names = [name for name, result in log if result.startswith("converted")]
    if not names:
        return None
    return ("DensePack converted %s into images behind a short pointer, to save tokens on each call. "
            "Each original is unchanged beside it as <name>.densepack.bak, and the change applies from "
            "your next session. /dense-remove restores the originals." % ", ".join(names))


def convert_all(event, reader):
    state = load_state()
    log = []
    for path, label, what, folder in targets(event):
        try:
            log.append((str(path), convert_one(path, label, what, folder, reader, state)))
        except Exception as exc:  # noqa: BLE001
            log.append((str(path), "failed: %s" % exc))
    save_state(state)
    return log


def restore_all():
    state = load_state()
    done = []
    for name in list(state):
        try:
            if restore(Path(name), state):
                done.append(name)
        except Exception as exc:  # noqa: BLE001
            print("Could not restore %s: %s" % (name, exc))
    save_state(state)
    return done


if __name__ == "__main__":
    if sys.argv[1:] == ["restore"]:
        for name in restore_all():
            print("restored " + name)
    else:
        for name, result in convert_all({"transcript_path": sys.argv[1] if len(sys.argv) > 1 else None},
                                        "opus"):
            print("%s: %s" % (name, result))
