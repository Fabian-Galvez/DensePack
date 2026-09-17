"""Runs before every message the user sends. The standing reminder.

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

import json
import os
import sys

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
        if has_delegated(session) or not pasted:
            if not warning:
                return 0
            text = warning
        else:
            text = OPENING + ("\n\n" + warning if warning else "")
        # A card that matches the one last sent this session carries no new
        # fact, so nothing is emitted. This is what makes OPENING a once per
        # session send.
        marker = card_marker_path(session)
        try:
            previous = marker.read_text(encoding="utf-8")
        except OSError:
            previous = None
        if text == previous:
            return 0
        emit({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": text,
            }
        })
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
