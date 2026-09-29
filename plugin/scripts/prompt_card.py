"""Runs before each message you send. It sends the standing reminder, the
short text that goes before a message.

This file sends only the opening line, which explains a condensed image, on
a message with a pasted image, in a session with no delegation.

It is a UserPromptSubmit hook. Claude Code runs it, sends the event to its
stdin, and puts the additionalContext that it returns before your message.

WHY THE OPENING LINE STAYS. You can paste a condensed image from the
right-click tool on the first message. The lead must know what one is from
the first message, before any agent starts. The hook sends it once per
session, not once per message. The fact does not change between messages,
and a second send adds nothing.

HOW THE MARKER WORKS. card_marker_path() names one file per session,
densepack-card-sent-<session_id>, which holds the exact text that this hook
last sent. For a message whose card matches the marker, the hook emits
nothing. OPENING never changes in a session with no delegation. From the
second message on, the card matches and the hook sends nothing, and OPENING
needs no separate one-shot flag. PRUNE_PREFIXES in bootstrap.py already
lists "densepack-card-sent". A marker stays at most KEEP_HOURS after its
session, the same as each other working file.
"""

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

from common import (delegation_path, disabled, emit, lead_model_name,
                    read_event, read_totals, resolved_reader, tmp_dir)

import style

_S = style.load()

# The only fact that applies to a session with no agents. You can paste a
# condensed image from the right-click tool on the first message. The lead
# must know what one is from the first message. The line also states that a
# packed image is exact and holds its numbers as markers. Without that, the
# model uses output tokens to reason after it reads an image. The line
# quotes the shape of the marker row, the same shape that
# pointer.marker_rows() uses for each row label. The band behind a source
# line shows the nesting depth of that line, and the line names no indent
# marks. The two sentences are in style.py, under card.code_scheme and
# card.opening.
CODE_SCHEME = _S["card.code_scheme"]

OPENING = _S["card.opening"] + "\n" + CODE_SCHEME


def has_delegated(session):
    """Return True when this session started at least one agent.

    brief_pack.py writes one row per spawn before the agent starts. The row
    exists when your next message arrives. A read failure counts as no
    delegation. The opening line is the safe side of an error.
    """
    try:
        body = delegation_path().read_text(encoding="utf-8")
    except OSError:
        return False
    for line in body.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if str(row.get("session") or "") == str(session or ""):
            return True
    return False


def card_marker_path(session):
    """Return the path of the last card text that this session sent.

    tmp_dir() in common.py is the per-project working folder of the plugin.
    This file does not choose its own folder. PRUNE_PREFIXES in bootstrap.py
    already lists "densepack-card-sent", and bootstrap.py prunes a stale
    marker the same as each other working file."""
    return tmp_dir() / ("densepack-card-sent-%s" % (session or "no-session-id"))


def track(event):
    """Update the row of this conversation in the shared tracker file, from
    the totals file of this project. The prompt that this hook runs on is
    the turn that it counts, and this hook advances the turn count. It never
    raises. The row is a record for the dashboard, never part of the card
    that this hook sends.

    The function imports tracker here, not at module scope. In a copy of the
    plugin without tracker.py, a module-level import raises
    ModuleNotFoundError before main() runs, and each of your messages loses
    the whole card. A dashboard row must never stop the card. Only an import
    inside the guard keeps that true in each copy of this file."""
    try:
        import tracker
        tracker.touch(event.get("session_id") or "",
                      event.get("cwd") or os.getcwd(),
                      read_totals(),
                      title=event.get("prompt") or "",
                      advance=True)
    except Exception:  # noqa: BLE001
        pass


# WORD FILES THAT A READ CANNOT REACH. The Read tool of Claude Code rejects a
# binary file in its own input check, before any PreToolUse hook runs.
# drop_read_gate.py never runs for a .doc or .docx and cannot replace one
# with its pages. A .md read logs an event in that gate, and a .doc read
# logs nothing. The typed name is the one place left to catch these files,
# and this hook packs them here.
# A path that ends in .doc or .docx, quoted or bare, as you type one.
WORD_PATH = re.compile(
    r"""["']?((?:[A-Za-z]:[\\/]|[\\/])[^"'<>|\r\n]*?\.docx?"""
    r"""|[^\s"'<>|]+\.docx?)["']?""",
    re.IGNORECASE)

# A message that names a FOLDER and not the files inside it. Without this
# check, nothing packs the Word files there. The agent must find them, and
# the read costs an extra tool call. The hook follows only an absolute path,
# and it never runs stat on an ordinary word. It lists only the folder
# itself and never walks below it. The cost is one directory listing. A
# message that names the files never gets here, and the common path keeps
# its speed.
ABS_PREFILTER = re.compile(r"""(?:[A-Za-z]:[\\/]|(?:^|[\s"'])[\\/])""")
ABS_TOKEN = re.compile(r"""(?:[A-Za-z]:[\\/]|[\\/])""")
WORD_SUFFIXES = (".doc", ".docx")
# Limits. A message that names a large folder cannot make one prompt a long
# render. The other files stay text, the same stop as each other floor in
# this plugin.
MAX_FOLDERS = 4
MAX_WORD_FILES = 8


def folder_word_files(prompt, seen):
    """Return each .doc and .docx directly in a folder that this message
    names.

    `seen` is the resolved-path set that word_pages() already filled. A file
    named directly is never packed twice. The function never raises. It
    skips an unreadable folder, and the model still gets the rejection from
    Claude Code.
    """
    found, folders = [], 0
    for token in re.split(r"""["'\s,;]+""", prompt):
        if folders >= MAX_FOLDERS or len(found) >= MAX_WORD_FILES:
            break
        if not token or not ABS_TOKEN.match(token):
            continue
        try:
            folder = Path(token)
            if not folder.is_dir():
                continue
        except OSError:
            continue
        folders += 1
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if len(found) >= MAX_WORD_FILES:
                break
            try:
                if entry.suffix.lower() not in WORD_SUFFIXES:
                    continue
                if not entry.is_file():
                    continue
                key = str(entry.resolve()).lower()
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            found.append(entry)
    return found


def word_pages(event):
    """Return the pointer sentence for each .doc and .docx that this message
    reaches, packed now, or "" when it reaches none.

    A message reaches a file when it names the file or a folder that holds
    it. The function never raises. It skips a file that does not open, or a
    pack that costs more than the text, and the model still gets the
    rejection from Claude Code."""
    prompt = str(event.get("prompt") or "")
    # The cheap pre-filter, before each import and each stat call. A message
    # with no ".doc" and no absolute path cannot name a Word file or a folder
    # that holds one.
    if ".doc" not in prompt.lower() and not ABS_PREFILTER.search(prompt):
        return ""
    try:
        import densepack as dp
        import drop_read_gate as gate
        import pointer
        from common import ensure_pillow, pack_images
    except Exception:  # noqa: BLE001
        return ""
    # Without freetype-py or NumPy, the renderer uses Pillow and renders a
    # different image that is harder to read. The file then stays text. This
    # is the same stop as in drop_read_gate.py.
    if not ensure_pillow():
        return ""
    rows, seen, named = [], set(), []
    for match in WORD_PATH.finditer(prompt):
        raw = (match.group(1) or "").strip()
        try:
            path = Path(raw)
            if not path.is_file():
                continue
            key = str(path.resolve()).lower()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        named.append(path)
    # Only when the message named no file. A message that named one already
    # names what you want. A folder listing on top of that packs pages that
    # nobody asked for.
    paths = named or folder_word_files(prompt, seen)
    for path in paths:
        sentence = _word_file_sentence(path, event, dp, gate, pointer,
                                       pack_images)
        if sentence:
            rows.append(sentence)
    return "\n\n".join(rows)


def _word_file_sentence(path, event, dp, gate, pointer, pack_images):
    """Return the pointer sentence of one file, or None when it stays text."""
    # The text that a Read returns. The code compares the pages against this
    # text. The size of the container shows nothing. A .docx is a zip and a
    # .doc is an OLE2 filesystem, and the two are mostly structure.
    suffix = path.suffix.lower()
    try:
        words = (pointer.docx_text(str(path)) if suffix == ".docx"
                 else pointer.doc_text(str(path)))
    except Exception:  # noqa: BLE001
        return None
    if not words:
        return None
    size = len(words.encode("utf-8"))
    # The same floor as in drop_read_gate.py. A small file costs more to
    # pack than it saves.
    if size < 1000:
        return None
    # THE PACK USES A COPY WITH A FIXED NAME. drop_and_draw() copies the
    # bytes that it gets into a staging folder and leaves the file in place.
    # The code packs a copy in the plugin working folder, and the name of
    # that copy comes from a hash of the source path. A second mention of
    # the same file then finds the pages already packed and does not pack
    # them again.
    stem = hashlib.sha256(str(path.resolve()).lower().encode("utf-8"))
    copy = tmp_dir() / ("densepack-word-%s%s" % (stem.hexdigest()[:12],
                                                 suffix))
    try:
        done = [Path(name) for name in pack_images(str(copy))]
    except Exception:  # noqa: BLE001
        done = []
    if done:
        return _sentence(path, done[0].parent, [p.name for p in done])
    try:
        shutil.copy2(str(path), str(copy))
    except OSError:
        return None
    try:
        image, patch_tokens, tags, drawn = gate.drop_and_draw(str(copy),
                                                              event)
    except Exception:  # noqa: BLE001
        return None
    if image is None:
        return None
    # REJECT WHEN WORSE, on the measurement of this file, the same test as
    # in drop_read_gate.py. The sentence goes in the same message as the
    # pages, and it counts against them.
    text_tokens = round(size / dp.CHARS_PER_TOKEN)
    note_tokens = round(len(tags or "") / dp.CHARS_PER_TOKEN)
    if patch_tokens is not None and patch_tokens + note_tokens >= text_tokens:
        try:
            gate.discard(drawn)
        except Exception:  # noqa: BLE001
            pass
        return None
    try:
        names = [Path(name).name for name in pack_images(str(copy))]
    except Exception:  # noqa: BLE001
        names = []
    return _sentence(path, Path(image).parent, names or [Path(image).name])


# THE FILE NAMES OF THE FOLDER. For a message about the files in a folder,
# the agent uses its first turn on a listing, a Glob or an ls, only to get
# the names. Each turn sends the whole conversation again. A message that
# names a folder, or says "this folder", gets the file names of that folder
# here. The first turn of the agent can then Read the files. The hook sends
# the names alone. Each Read still returns image 1 and its own note, and
# the agent chooses a later image after it reads image 1.
THIS_FOLDER = re.compile(r"\b(?:this|the current|the project)\s+(?:folder|directory)\b",
                         re.IGNORECASE)
# The hook does not list a folder with more files than this. The agent
# searches such a folder and does not read it whole.
LIST_MAX_FILES = 200


def predraw(event, paths):
    """Start drop_read_gate.prefetch() on these files in a process of its
    own, detached, and return at once. Never raises."""
    import subprocess
    import tempfile
    try:
        fd, job = tempfile.mkstemp(prefix="densepack-prepack-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"event": event, "paths": [str(p) for p in paths]}, fh)
        here = os.path.dirname(os.path.abspath(__file__))
        code = ("import json, os, sys; sys.path.insert(0, %r); "
                "import drop_read_gate as g; j = json.load(open(%r)); "
                "os.remove(%r); g.prefetch(j['event'], j['paths'])"
                % (here, job, job))
        flags = {}
        if os.name == "nt":
            # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP. The pack helpers
            # share a hidden console, and no window opens.
            flags["creationflags"] = 0x08000000 | 0x00000200
        else:
            flags["start_new_session"] = True
        subprocess.Popen([sys.executable, "-c", code], cwd=here,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, **flags)
    except Exception:  # noqa: BLE001
        pass


# A named folder must be this many parts deep, with the root as one part.
# C:\Users\me and /home/me pass. "/", "\", "C:\", /tmp and C:\Windows do not.
# A lone "/" in a table row or in "a / b" resolves to the drive root. Without
# this limit, the file names of the root went to the model on 6 of 10
# messages in one session.
MIN_FOLDER_PARTS = 3


def named_folder(token):
    """Return the folder that `token` names. Return None when it is not a
    folder, or when it is a drive root or a folder one level under a root.
    Never raises."""
    try:
        path = Path(token)
        if not path.is_dir():
            return None
        if len(path.resolve().parts) < MIN_FOLDER_PARTS:
            return None
        return path
    except (OSError, ValueError, RuntimeError):
        return None


def folder_files(event):
    """Return the file names of each folder that this message is about, one
    sentence per folder, or "" when it is about none. Never raises."""
    prompt = str(event.get("prompt") or "")
    folders = []
    if THIS_FOLDER.search(prompt):
        here = named_folder(event.get("cwd") or os.getcwd())
        if here is not None:
            folders.append(here)
    for token in re.split(r"""[\s"',;]+""", prompt):
        if token and ABS_TOKEN.match(token) and len(folders) < MAX_FOLDERS:
            found = named_folder(token)
            if found is not None:
                folders.append(found)
    rows, seen = [], set()
    for folder in folders:
        try:
            key = str(folder.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            names = sorted(e.name for e in folder.iterdir()
                           if e.is_file() and not e.name.startswith("."))
        except OSError:
            continue
        if not names or len(names) > LIST_MAX_FILES:
            continue
        # The pack runs in the background, all at once. The model starts at
        # once, and its Reads find their images ready or wait for the one
        # pack.
        predraw(event, [folder / n for n in names])
        try:
            from common import no_metacharacters
            names = [no_metacharacters(n) for n in names]
        except Exception:  # noqa: BLE001
            pass
        rows.append("The folder %s holds these %d files: %s." % (
            str(folder), len(names), ", ".join(names)))
    return "\n".join(rows)


def _sentence(path, folder, names):
    """Return the note for the model. It names the file and its pages and
    tells the model to open them. The file name goes through
    no_metacharacters for the same reason as in
    pointer.later_images_note(), because it reaches the model as text from
    the plugin."""
    try:
        from common import no_metacharacters
        shown = no_metacharacters(path.name)
    except Exception:  # noqa: BLE001
        shown = path.name
    return ("DensePack packed %s into %d condensed image%s in %s: %s. Claude "
            "Code's Read rejects the file itself. Read %s and never the "
            "file." % (shown, len(names), "" if len(names) == 1 else "s",
                       str(folder), ", ".join(names),
                       "that image" if len(names) == 1
                       else "those images in order"))


def main():
    # A fault never blocks the message. This hook runs before each message
    # in the session.
    event = {}
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        session = event.get("session_id") or ""
        warning = None
        # A session that delegated gets no opening line, because the opening
        # line holds the one fact that applies with no agents. The hook
        # sends the card only on a message with a pasted image. That is the
        # one case where the model has an image and no key row or pointer
        # sentence to explain it. On each first message, the card makes
        # Opus think before a read-and-answer task. A code page has its own
        # key row, and a packed output has its own pointer.
        pasted = "[Image" in str(event.get("prompt") or "")
        drawn = "\n\n".join(part for part in (word_pages(event),
                                                folder_files(event)) if part)
        if has_delegated(session) or not pasted:
            text = warning or ""
        else:
            text = OPENING + ("\n\n" + warning if warning else "")
        # A card that matches the last one sent in this session holds no new
        # fact, and the hook emits nothing. This test makes OPENING a once
        # per session send. A Word file packed this turn is a new fact each
        # time. It goes next to the card and never through this test.
        marker = card_marker_path(session)
        try:
            previous = marker.read_text(encoding="utf-8")
        except OSError:
            previous = None
        if text == previous:
            text = ""
        if not text and not drawn:
            return 0
        emit({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "\n\n".join(
                    part for part in (text, drawn) if part),
            }
        })
        if text:
            try:
                marker.write_text(text, encoding="utf-8")
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        return 0
    finally:
        # Each path above returns early on some turns. The hook updates the
        # row here, at the end of the run, and not next to one of them.
        track(event)
    return 0


if __name__ == "__main__":
    sys.exit(main())
