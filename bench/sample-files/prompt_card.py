"""Runs before every message the user sends. The standing reminder.

HOW THIS FILE FITS, in plain words: this used to repeat what a condensed
image is on every message, in a long form once per session and a short form
after that. PLAN-FABLE.md step 3, 29 August 2026, moved that explanation into
the role and shared instruction images bootstrap.py draws at SessionStart,
which every agent reads once at the start of its turn. This file now sends
only the two facts that cannot live in a static image: the opening line for a
session that has not delegated yet, and the delegation tier line, because
/maxpack can flip mid conversation and a static image cannot know that.

It is a UserPromptSubmit hook. Claude Code runs it, pipes the event in, and
prepends whatever comes back in additionalContext to the user's message.

WHY THE OPENING LINE STAYS. A user can paste a condensed image from the
right-click tool on the first message, so the lead has to know what one is
from the first message, before any agent has been spawned and before the
SessionStart pointer's role image would ordinarily be read for delegation
reasons. 112 characters when it was measured live on 25 August 2026; 441
since 4 September 2026, when the marker row shape and its provenance moved
into it, counted by tests/test_opening_card.py. Sent once per session, not
once per message: the fact does not change between messages, so a second
send buys nothing.

WHY THE TIER LINE STAYS AS TEXT. Only an Opus or Sonnet lead can break this
rule, and /maxpack can lift or restore it at any point in the conversation.
The SessionStart pointer's role image is read once, at the start, and cannot
carry a fact that changes after that, so the tier line is text, sent again
only when it differs from the last card this session sent: the first
message after delegation begins, and again on a /maxpack toggle. A session
measured across 88 sessions sent the tier line 55 times against one real
toggle; sending only on a change makes that one send.

WHAT LEFT. The full card (703 characters, about 176 tokens, once per
session), the short card (128 characters, about 32 tokens, every message
after), and CODE_CARD (112 characters, sent on every message regardless of
delegation) explained the color code, the drawing size, who packs a brief,
and the delivery rule. All three now live in the role and shared
instruction images named by the SessionStart pointer line, read once
per agent per turn, so repeating any of it here on every user message bought
nothing more. CODE_CARD's removal was the largest of the three savings
measured 30 August 2026: 37 sends in one session for 5,328 fresh tokens and
607,248 re-sent as cache reads, for a line the agent already reads in its
own rules image.

HOW THE MARKER WORKS. card_marker_path() names one file per session,
densepack-card-sent-<session_id>, holding the exact text this hook last
sent. A message whose card matches the marker emits nothing at all. This
also covers ITEM 2: OPENING never changes while a session has not
delegated, so the second message onward compares equal and sends nothing,
without OPENING needing its own separate one-shot flag. bootstrap.py's
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
# the lead has to know what one is from the first message. Everything else in
# the old full card, the drawing size, who packs a brief, which models may be
# spawned, is about delegating, and now lives in the role image the
# SessionStart pointer line names, read once the lead starts its turn. The
# line also states that a packed image is exact and carries its numbers as
# markers, because the turns audit of 3 September 2026 counted 1,211 of pair
# 52's 1,460 extra output tokens and 1,128 of the Python pair's 1,239 as
# thinking, 82.9 and 91.0 per cent, so the gap is the model reasoning after
# it reads a picture. It quotes the marker row's own shape, ADDED
# 4 September 2026 after pair 58: naming the shape here and labelling every
# row in pointer.marker_rows() are one fix, and a card that described the
# markers as "listed beside the image" pointed at a file. This line is 254
# characters, 104 more than the 312 it held before, paid once a session,
# measured 4 September 2026 by tests/test_pointer_card.py, which fails when
# the count drifts.
# MEASURED 4 September 2026, bench/nestband-2026-09-04.md. The band behind a
# source line is that line's nesting depth, so the section sign and the right
# arrow are gone from every picture and this line stops naming them. Four
# readers answered four indent questions the same off bands as off the marks,
# and two of them read a depth 3 line's 12 leading spaces back off the band
# alone. The line is shorter than the one it replaces.
# Both sentences live in style.py, under card.code_scheme and card.opening,
# so tools/tuner.py edits the card in the same window it edits the picture.
# The defaults there are the text this file held before.
CODE_SCHEME = _S["card.code_scheme"]

OPENING = _S["card.opening"] + "\n" + CODE_SCHEME


def has_delegated(session):
    """True once this session has spawned at least one agent.

    brief_pack.py writes one row per spawn before the agent starts, so the row
    exists by the time the next user message arrives. Read failures count as
    no delegation: the opening line is the safe one to be wrong with, because
    the tier line follows on the next message either way.
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


# The Opus-at-8-px warning that lived here until 12 September 2026 went
# with the per-reader sizes. One page at one size leaves no pairing to
# warn about.


def track(event):
    """Refresh this conversation's row in the shared tracker file, from the
    totals file this project already keeps. The user message this hook runs
    on is the turn it counts, so this is the one of the two hooks that
    advances the turn count. It never raises: the row is a record for the
    dashboard, never part of the card this hook sends.

    tracker is imported here, not at module scope. MEASURED 4 September 2026:
    the plugin cache carried no tracker.py, the module-level import raised
    ModuleNotFoundError before main() ran, and every user message lost the
    whole card, including the four mark legend lines codepack stopped drawing
    into the picture the night before. A dashboard row must never be able to
    take the card down, and only an import inside the guard keeps that true
    wherever this file is copied."""
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
        # Since 7 September 2026 at night the card goes out only on a message
        # that carries a pasted image, the one case where the model has a
        # picture and no key row or pointer sentence to explain it. Sent on
        # every first message it made Opus think before a read-and-answer
        # task, 7 of 11 runs against 0 with the plugin off; a code page
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
