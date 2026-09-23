"""Runs before every message the user sends. It sends the standing reminder,
the short text that goes before a message.

HOW THIS FILE FITS, in plain words: the explanation of a condensed image
lives in the role and shared instruction images bootstrap.py draws at
SessionStart, which every agent reads once at the start of its turn. This
file sends only the opening line, on a message that carries a pasted image
in a session that has not delegated.

It is a UserPromptSubmit hook. Claude Code runs it, pipes the event in, and
prepends whatever comes back in additionalContext to the user's message.

WHY THE OPENING LINE STAYS. A user can paste a condensed image from the
right-click tool on the first message, so the lead has to know what one is
from the first message, before any agent has been spawned. It is sent once
per session, not once per message: the fact does not change between
messages, so a second send buys nothing.

HOW THE MARKER WORKS. card_marker_path() names one file per session,
densepack-card-sent-<session_id>, holding the exact text this hook last
sent. A message whose card matches the marker emits nothing at all.
OPENING never changes while a session has not delegated, so the second
message onward compares equal and sends nothing, without OPENING needing
its own separate one-shot flag. bootstrap.py's
PRUNE_PREFIXES already lists "densepack-card-sent", so a marker outlives
its session by at most KEEP_HOURS the same as every other working file.
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

# The only fact that applies to a session with no agents in it. A user can
# paste a condensed image from the right-click tool on the first message, so
# the lead has to know what one is from the first message. The line also
# states that a packed image is exact and carries its numbers as markers,
# because without that the model spends output tokens reasoning after it
# reads a picture. It quotes the marker row's own shape, the same shape
# pointer.marker_rows() labels every row with. The band behind a source line
# is that line's nesting depth, so the line names no indent marks.
# Both sentences live in style.py, under card.code_scheme and card.opening.
CODE_SCHEME = _S["card.code_scheme"]

OPENING = _S["card.opening"] + "\n" + CODE_SCHEME


def has_delegated(session):
    """True once this session has spawned at least one agent.

    brief_pack.py writes one row per spawn before the agent starts, so the row
    exists by the time the next user message arrives. Read failures count as
    no delegation: the opening line is the safe one to be wrong with.
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
    """Where this session's last-sent card text lives. tmp_dir() is the
    plugin's own per-project working folder, common.py's, not a folder of
    this file's own choosing, and bootstrap.py's PRUNE_PREFIXES already
    lists "densepack-card-sent" so a stale marker is pruned the same as
    every other working file."""
    return tmp_dir() / ("densepack-card-sent-%s" % (session or "no-session-id"))


def track(event):
    """Refresh this conversation's row in the shared tracker file, from the
    totals file this project already keeps. The user message this hook runs
    on is the turn it counts, so this is the one of the two hooks that
    advances the turn count. It never raises: the row is a record for the
    dashboard, never part of the card this hook sends.

    tracker is imported here, not at module scope. In a copy that lacks
    tracker.py, a module-level import raises ModuleNotFoundError before
    main() runs, and every user message loses the whole card. A dashboard
    row must never be able to take the card down, and only an import inside
    the guard keeps that true wherever this file is copied."""
    try:
        import tracker
        tracker.touch(event.get("session_id") or "",
                      event.get("cwd") or os.getcwd(),
                      read_totals(),
                      title=event.get("prompt") or "",
                      advance=True)
    except Exception:  # noqa: BLE001
        pass


# WORD FILES A READ CANNOT REACH. Claude Code's Read refuses a binary file
# during its own input check, before any PreToolUse hook runs, so
# drop_read_gate.py is never called for a .doc or .docx and can never swap
# one for its pages. Measured 17 September 2026: a .md read logs an event in
# that gate, a .doc read logs nothing at all. The name the user typed is the
# one place left to catch these, so they are drawn here instead.
# A path ending .doc or .docx, quoted or bare, as a user types one.
WORD_PATH = re.compile(
    r"""["']?((?:[A-Za-z]:[\\/]|[\\/])[^"'<>|\r\n]*?\.docx?"""
    r"""|[^\s"'<>|]+\.docx?)["']?""",
    re.IGNORECASE)

# A message that names a FOLDER instead of the files inside it. Without this
# the Word files there are drawn by nothing, the agent has to go and find
# them itself, and the read costs an extra tool call for no reason. Only an
# absolute path is followed, so an ordinary word is never stat'd, and only
# the folder itself is listed, never a walk below it: the cost is one
# directory listing. A message that names the files themselves never reaches
# here, so the common path is exactly as fast as it was.
ABS_PREFILTER = re.compile(r"""(?:[A-Za-z]:[\\/]|(?:^|[\s"'])[\\/])""")
ABS_TOKEN = re.compile(r"""(?:[A-Za-z]:[\\/]|[\\/])""")
WORD_SUFFIXES = (".doc", ".docx")
# Ceilings, so a message that happens to name a large folder cannot turn one
# prompt into a long render. The rest stay text, the same stop every other
# floor in this plugin makes.
MAX_FOLDERS = 4
MAX_WORD_FILES = 8


def folder_word_files(prompt, seen):
    """Every .doc and .docx sitting directly in a folder this message names.

    `seen` is the resolved-path set word_pages() already filled, so a file
    named outright is never drawn twice. Never raises: an unreadable folder
    is skipped and the reader still gets Claude Code's own refusal.
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
    """The pointer sentence for every .doc and .docx this message reaches,
    drawn now, or "" when it reaches none. A message reaches one by naming
    the file, or by naming a folder that holds one. Never raises: a file
    that will not open, or a draw that costs more than the words, is left
    out and the reader still gets Claude Code's own refusal."""
    prompt = str(event.get("prompt") or "")
    # The cheap pre-filter, ahead of every import and every stat call. A
    # message with no ".doc" in it and no absolute path in it cannot name a
    # Word file or a folder holding one.
    if ".doc" not in prompt.lower() and not ABS_PREFILTER.search(prompt):
        return ""
    try:
        import densepack as dp
        import drop_read_gate as gate
        import pointer
        from common import ensure_pillow, pack_images
    except Exception:  # noqa: BLE001
        return ""
    # Without freetype-py or NumPy the renderer falls back to Pillow and
    # draws a different, harder image, so the file stays text instead. The
    # same stop drop_read_gate.py makes.
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
    # Only when the message named no file of its own. A message that named
    # one has already said what it wants, and listing folders on top of that
    # would draw pages nobody asked for.
    paths = named or folder_word_files(prompt, seen)
    for path in paths:
        sentence = _word_file_sentence(path, event, dp, gate, pointer,
                                       pack_images)
        if sentence:
            rows.append(sentence)
    return "\n\n".join(rows)


def _word_file_sentence(path, event, dp, gate, pointer, pack_images):
    """One file's pointer sentence, or None when it stays text."""
    # The words a Read would have delivered, which is what the pages are
    # weighed against. The container's own size says nothing: a .docx is a
    # zip and a .doc an OLE2 filesystem, both mostly machinery.
    suffix = path.suffix.lower()
    try:
        words = (pointer.docx_text(str(path)) if suffix == ".docx"
                 else pointer.doc_text(str(path)))
    except Exception:  # noqa: BLE001
        return None
    if not words:
        return None
    size = len(words.encode("utf-8"))
    # The same floor drop_read_gate.py keeps: a small file costs more to
    # draw than it saves.
    if size < 1000:
        return None
    # NEVER HAND THE USER'S OWN FILE TO drop_and_draw(). That function moves
    # the source it is given, and a file named in a prompt is the user's
    # only copy: handing it over deletes it. A copy under the plugin's own
    # working folder is drawn instead. The copy's name is derived from the
    # source path, so a second mention of the same file finds the pages
    # already drawn rather than drawing them again.
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
    # REFUSE WHEN WORSE, on this file's own measurement, the same
    # comparison drop_read_gate.py makes: the sentence ships in the same
    # message as the pages, so it counts against them.
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


# THE FOLDER'S FILE NAMES. A message about the files in a folder makes the
# agent spend its first turn on a listing, a Glob or an ls, only to learn
# the names, and every turn resends the whole conversation. A message that
# names a folder, or says "this folder", gets that folder's file names
# here, so the agent's first turn can Read the files. It is the names
# alone: each Read still returns image 1 and its own note, and the agent
# picks any later image after it has seen image 1, as it always has.
THIS_FOLDER = re.compile(r"\b(?:this|the current|the project)\s+(?:folder|directory)\b",
                         re.IGNORECASE)
# A folder holding more files than this is searched, not read whole.
LIST_MAX_FILES = 200


def predraw(event, paths):
    """Start drop_read_gate.prefetch() on these files in a process of its
    own, detached, and return at once. Never raises."""
    import subprocess
    import tempfile
    try:
        fd, job = tempfile.mkstemp(prefix="densepack-predraw-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"event": event, "paths": [str(p) for p in paths]}, fh)
        here = os.path.dirname(os.path.abspath(__file__))
        code = ("import json, os, sys; sys.path.insert(0, %r); "
                "import drop_read_gate as g; j = json.load(open(%r)); "
                "os.remove(%r); g.prefetch(j['event'], j['paths'])"
                % (here, job, job))
        flags = {}
        if os.name == "nt":
            # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP: a hidden console the
            # drawing helpers share, so no window opens.
            flags["creationflags"] = 0x08000000 | 0x00000200
        else:
            flags["start_new_session"] = True
        subprocess.Popen([sys.executable, "-c", code], cwd=here,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, **flags)
    except Exception:  # noqa: BLE001
        pass


def folder_files(event):
    """The file names of every folder this message is about, one sentence
    per folder, or "" when it is about none. Never raises."""
    prompt = str(event.get("prompt") or "")
    folders = []
    if THIS_FOLDER.search(prompt):
        folders.append(Path(event.get("cwd") or os.getcwd()))
    for token in re.split(r"""[\s"',;]+""", prompt):
        if token and ABS_TOKEN.match(token) and len(folders) < MAX_FOLDERS:
            try:
                if Path(token).is_dir():
                    folders.append(Path(token))
            except OSError:
                continue
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
        # Drawn in the background, all at once, so the reader starts at once
        # and its Reads find their images ready or wait for the one draw.
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
    """What the reader is told: the file, its pages, and to open them. The
    file name goes through no_metacharacters for the same reason
    pointer.later_images_note() does, because it reaches the reader as the
    plugin's own words."""
    try:
        from common import no_metacharacters
        shown = no_metacharacters(path.name)
    except Exception:  # noqa: BLE001
        shown = path.name
    return ("DensePack drew %s as %d condensed image%s in %s: %s. Claude "
            "Code's Read refuses the file itself. Read %s and never the "
            "file." % (shown, len(names), "" if len(names) == 1 else "s",
                       str(folder), ", ".join(names),
                       "that image" if len(names) == 1
                       else "those images in order"))


def main():
    # NEVER CRASH A CALLER. This runs before every message in the session.
    event = {}
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        session = event.get("session_id") or ""
        warning = None
        # A session that has delegated is sent nothing but the warning. The
        # opening line carries the one fact that applies with no agents.
        # The card goes out only on a message that carries a pasted image,
        # the one case where the model has a picture and no key row or
        # pointer sentence to explain it. Sent on every first message, it
        # makes Opus think before a read-and-answer task; a code page
        # carries its own key row and a packed output its own pointer.
        pasted = "[Image" in str(event.get("prompt") or "")
        drawn = "\n\n".join(part for part in (word_pages(event),
                                                folder_files(event)) if part)
        if has_delegated(session) or not pasted:
            text = warning or ""
        else:
            text = OPENING + ("\n\n" + warning if warning else "")
        # A card that matches the one last sent this session carries no new
        # fact, so nothing is emitted. This is what makes OPENING a once per
        # session send. A Word file drawn this turn is a new fact every time,
        # so it rides beside the card and never through this test.
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
        # Every path above returns early on some turns, so the row is
        # refreshed here, at the end of the run, rather than beside any one
        # of them.
        track(event)
    return 0


if __name__ == "__main__":
    sys.exit(main())
