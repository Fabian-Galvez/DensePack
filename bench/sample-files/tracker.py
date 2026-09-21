#!/usr/bin/env python
"""One row a conversation, in one JSON file every project shares.

WHAT THIS FILE IS FOR, in plain words: the dashboard used to work out the
whole machine's conversation list by parsing every transcript on every
request, which took most of a minute on this machine. This file is the
saved state that replaces that work. prompt_card.py and stop_gate.py each
refresh the row of the conversation they just ran in, from the totals file
the plugin already keeps beside them, so the row is current by the time the
page asks for it.

The file sits at .claude/densepack-tracker.json under the user's home
folder, one level above the projects folder, because a row is about a
conversation and conversations happen in many project folders. It is a
plain JSON object keyed by session id, so a reader can open it without
this module.

Every field:

    session         the conversation's own id
    project         the folder the conversation is working in
    title           the first prompt's first 88 characters
    started         when the first row was written, epoch seconds
    updated         when the row was last refreshed, epoch seconds
    turns           messages the user has sent
    tokens_saved    text tokens the packs replaced, less what they cost
    dollars_saved   the same saving in dollars, or null
    model           the lead's model, when a reader has recorded one
    images          images drawn
    records         packs recorded, one manifest record each
    totals          the whole totals file, whatever it already knows

dollars_saved and model are left alone here. This folder holds no price
card, and inventing a rate for one would put a second source of truth
beside bench/session_cost.py. tools/live_dashboard.py owns both fields: its
back-fill writes them from the transcripts, and the page prices a live row
as it renders it.
"""
import json
import os
import pathlib
import re
import time

TITLE_CHARS = 88
TRACKER_NAME = "densepack-tracker.json"
# Claude Code names a project folder after its working directory with every
# character that is not a letter or a digit turned into a dash. The row
# carries that name rather than the raw path, so a row a hook writes and a
# row the dashboard back-fills from the projects folder name the same
# folder in the same string.
NOT_IN_A_FOLDER_NAME = re.compile(r"[^A-Za-z0-9]")


def project_name(cwd):
    """The project folder name Claude Code gives a working directory."""
    return NOT_IN_A_FOLDER_NAME.sub("-", str(cwd or ""))


def tracker_path():
    """The one tracker file. DENSEPACK_TRACKER points a test at its own."""
    named = os.environ.get("DENSEPACK_TRACKER", "").strip()
    if named:
        return pathlib.Path(named)
    return pathlib.Path.home() / ".claude" / TRACKER_NAME


def read_tracker(path=None):
    """Every row, keyed by session id. An unreadable or half written file
    reads as no rows at all, the same failure mode common.read_totals()
    takes, so a hook never raises on the way out."""
    path = tracker_path() if path is None else pathlib.Path(path)
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return rows if isinstance(rows, dict) else {}


def save_tracker(rows, path=None):
    """Write every row, through a temporary file and one rename, so a
    reader never sees a half written file."""
    path = tracker_path() if path is None else pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Last writer wins. Two hooks finishing inside the same
    # millisecond can lose one refresh; the next turn writes it again. A
    # lock file here would cost every hook a wait for a row nobody reads
    # until the page is open.
    temp = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
    temp.write_text(json.dumps(rows), encoding="utf-8")
    os.replace(temp, path)
    return path


def touch(session, project, totals, title=None, advance=False, path=None,
          now=None):
    """Write or refresh one conversation's row and return it.

    totals is the project's own totals file, already read by the caller.
    title is set once, on the row's first write, and kept afterwards, so a
    later turn's prompt never renames a conversation. advance is True for
    the hook that runs on a user message and False for the one that runs
    at the end of a turn, so a turn is counted once.
    """
    if not session:
        return None
    rows = read_tracker(path)
    stamp = time.time() if now is None else now
    row = rows.get(str(session))
    if not isinstance(row, dict):
        row = {"session": str(session), "started": stamp, "turns": 0,
               "title": "", "dollars_saved": None, "model": ""}
    if project:
        row["project"] = project_name(project)
    if title and not row.get("title"):
        row["title"] = " ".join(str(title).split())[:TITLE_CHARS]
    if advance:
        row["turns"] = int(row.get("turns") or 0) + 1
    row["updated"] = stamp
    row["images"] = int(totals.get("images") or 0)
    row["records"] = int(totals.get("packed") or 0)
    row["tokens_saved"] = (int(totals.get("text_tokens") or 0)
                           - int(totals.get("image_tokens") or 0))
    row["totals"] = totals
    rows[str(session)] = row
    save_tracker(rows, path)
    return row


def demo():
    """One row written, refreshed and counted, in a temporary file."""
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder) / TRACKER_NAME
        totals = {"images": 3, "packed": 2, "text_tokens": 900,
                  "image_tokens": 300}
        first = touch("sess-1", "C:/work", totals, title="x" * 200,
                      advance=True, path=path)
        assert first["turns"] == 1, first
        assert len(first["title"]) == TITLE_CHARS, first["title"]
        assert first["tokens_saved"] == 600, first
        assert first["images"] == 3 and first["records"] == 2, first
        assert first["project"] == "C--work", first["project"]
        again = touch("sess-1", "C:/work", totals, title="another prompt",
                      path=path)
        assert again["turns"] == 1, again
        assert again["title"] == "x" * TITLE_CHARS, again["title"]
        assert again["started"] == first["started"], again
        rows = read_tracker(path)
        assert list(rows) == ["sess-1"], rows
        touch("sess-2", "C:/other", totals, advance=True, path=path)
        assert len(read_tracker(path)) == 2
    print("tracker demo ok")


if __name__ == "__main__":
    demo()
