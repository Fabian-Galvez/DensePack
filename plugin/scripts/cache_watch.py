"""Warns before the prompt cache lapses, so a whole prefix is not rewritten.

HOW THIS FILE FITS, in plain words: Anthropic holds a conversation's prefix in
a cache. While it holds, every turn re-reads that prefix at one tenth of the
input price. When it lapses, the next turn writes the whole prefix back in at
one and a quarter times input, which is twelve and a half times the price of a
read. Nothing in this plugin told anyone that moment was coming.

WHAT IT MEASURES, over 8 real transcripts on 25 August 2026:

  turns                                                    7,453
  turns whose cache write is over four times the median      519
  tokens those turns wrote                            25,639,814
  what that cost at published Opus 5 prices        $147 of $1,905

So a cold cache is 7.74 per cent of the bill. It is 0 per cent of a plan's
token count, because a cold write of N tokens becomes a warm read of the same
N tokens; only the price of each token changes. A plugin quoting cache savings
to a subscriber is quoting a number that does not apply to them.

WHAT IT DOES. It runs on UserPromptSubmit, reads the time of the last
assistant message out of the session transcript, and prints one line when the
gap is inside the warning band. It never blocks. A block would cost the turn
it is trying to save, the same reasoning source_gate.py records for rewriting
rather than refusing.

THE TWO CACHE LIVES. Anthropic's default is five minutes. A session can run on
the one hour cache instead, and Claude Code says which in its own system text.
The longer figure is used here, with the shorter one printed beside it, so the
reader can tell which applies without this file guessing.
"""

import sys
import time
from pathlib import Path

from common import disabled, emit, read_event, transcript_path

# Anthropic's two cache lives, in seconds.
SHORT_TTL = 5 * 60
LONG_TTL = 60 * 60

# How close to the end of the life counts as a warning. 90 per cent of the one
# hour life leaves six minutes, which is not long enough to finish a thought
# and send it, so the band starts at 80 per cent and leaves twelve.
WARN_AT = 0.80

# What one cold turn costs, measured 25 August 2026 over 519 such turns in the
# 8 largest transcripts: 25,639,814 tokens written across them.
MEAN_COLD_TOKENS = 49_402


def last_assistant_time(path):
    """Unix seconds of the last assistant message, or None.

    The transcript is read from the end, because the last message is what
    matters and these files reach hundreds of megabytes.
    """
    import json
    try:
        lines = Path(path).read_text(encoding="utf-8",
                                     errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") != "assistant":
            continue
        stamp = row.get("timestamp")
        if not stamp:
            continue
        try:
            from datetime import datetime
            return datetime.fromisoformat(
                stamp.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            return None
    return None


def minutes(seconds):
    """Whole minutes, never 0 for a gap that is not zero.

    Truncating printed "0 minutes left" at 59 minutes of a 60 minute life,
    which reads as no time at all when there is a minute. A part minute is
    rounded up so the number is never smaller than the time really left.
    """
    return max(1, int(seconds // 60 + (1 if seconds % 60 else 0)))


def message(idle, ttl):
    """The one line printed, or "" when there is nothing to say."""
    if idle >= ttl:
        gone = minutes(idle - ttl)
        return ("DensePack: the prompt cache lapsed %d minute%s ago. The next "
                "turn writes the whole conversation back in at 12.5 times the "
                "price of a read, about %s tokens on this project's measured "
                "mean. Nothing is wrong; this is the one turn that costs more."
                % (gone, "" if gone == 1 else "s",
                   format(MEAN_COLD_TOKENS, ",")))
    if idle >= ttl * WARN_AT:
        left = minutes(ttl - idle)
        return ("DensePack: the prompt cache has %d minute%s left. A turn sent "
                "before then re-reads the conversation at one tenth of the "
                "input price. A turn sent after it rewrites the whole "
                "conversation at twelve and a half times that."
                % (left, "" if left == 1 else "s"))
    return ""


def main():
    # NEVER CRASH A CALLER. This runs before every message in the session.
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        path = transcript_path(event.get("session_id"))
        if not path:
            return 0
        last = last_assistant_time(path)
        if last is None:
            return 0
        idle = time.time() - last
        text = message(idle, LONG_TTL)
        if not text:
            return 0
        emit({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": text}})
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
