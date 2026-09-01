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
reasons. 112 characters, measured live on 25 August 2026, sent once per
session, not once per message: the fact does not change between messages, so
a second send buys nothing.

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
and the code discipline rule. All three now live in the role, shared and
code instruction images named by the SessionStart pointer line, read once
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
import sys

from common import (delegation_path, disabled, emit, read_event,
                    resolved_reader, settings, tmp_dir)

READER_SAID = {
    "fable": "Fable 5, 8 px",
    "opus": "Opus 5, 10 px",
    "sonnet": "Sonnet 5, 12 px",
}

# RETIRED 31 August 2026. These two lines were the last
# delegation instruction this hook sent, 120 and 98 characters on the send and
# on every change of the setting after it. One delegation prompt run twice
# measured what the whole class of them bought: 192,692 tokens with the plugin
# off against 896,368 with it on, the gap made of extra lead turns, not of
# extra text. A lead that is already delegating is told nothing about
# delegating now. The maxpack setting still decides what tier_gate.py does; it
# is simply no longer announced. Kept as names, empty, so a reader of an older
# receipt or plan sees what stood here.
TIER_LOCKED = ""
TIER_OPEN = ""

# The only fact that applies to a session with no agents in it. A user can
# paste a condensed image from the right-click tool on the first message, so
# the lead has to know what one is from the first message. Everything else in
# the old full card, the drawing size, who packs a brief, which models may be
# spawned, is about delegating, and now lives in the role image the
# SessionStart pointer line names, read once the lead starts its turn. This
# line is 112 characters, measured live on 25 August 2026.
OPENING = ("You may receive a prompt or an agent report as an image of small "
           "color coded text. Read that text and follow it.")


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


def tier_card(current):
    """Always None. No delegation line reaches a lead from this hook.

    The signature stays because pointer.py, the tests and the input plans
    name it. See the note above TIER_LOCKED for the measurement that
    retired the text it used to return.
    """
    return None


def card_marker_path(session):
    """Where this session's last-sent card text lives. tmp_dir() is the
    plugin's own per-project working folder, common.py's, not a folder of
    this file's own choosing, and bootstrap.py's PRUNE_PREFIXES already
    lists "densepack-card-sent" so a stale marker is pruned the same as
    every other working file."""
    return tmp_dir() / ("densepack-card-sent-%s" % (session or "no-session-id"))


def main():
    # NEVER CRASH A CALLER. This runs before every message in the session.
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        current = settings()
        session = event.get("session_id") or ""
        # Nothing has been delegated yet, so the delegation tier does not
        # apply. The opening line carries the one fact that applies with no
        # agents.
        if not has_delegated(session):
            text = OPENING
        else:
            text = tier_card(current) or ""
        if not text:
            return 0
        # A card that matches the one last sent this session carries no new
        # fact, so nothing is emitted. This is what makes OPENING a once per
        # session send and the tier line a send-on-change one: the compare
        # is the same regardless of which text produced it.
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
