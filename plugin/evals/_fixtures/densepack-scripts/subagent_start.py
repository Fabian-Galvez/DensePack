"""Sends each subagent the same intro the lead gets at session start.

HOW THIS FILE FITS, in plain words: SessionStart context reaches only the
main session. A subagent starts with a fresh context, so without this hook it
gets images with no word that their text is the file's text, or that Grep is
the last resort. Sonnet 5.5 subagents then checked the images with Bash and
Grep, 1 to 3 extra calls in 6 of 8 image runs (28 September 2026).

SubagentStart hook. It answers with hookSpecificOutput.additionalContext,
which Claude Code puts before the subagent's first prompt. A subagent whose
model is known to get text (Sonnet with /max-off) gets nothing: it never sees
an image. A model not yet known at spawn gets the intro, because most agents
run on a model that gets images.

NEVER CRASH A CALLER. Any fault sends nothing and the spawn goes on.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import actor_reader, disabled, emit, read_event, reader_gets_images  # noqa: E402


def intro_for(event):
    """The intro text for this subagent, or None when it gets text."""
    if not isinstance(event, dict) or disabled(event.get("session_id")):
        return None
    try:
        reader = actor_reader(event)
    except Exception:  # noqa: BLE001
        reader = None
    if reader is not None and not reader_gets_images(reader):
        return None
    from bootstrap import READ_TOOL_LINE
    return READ_TOOL_LINE


def main():
    try:
        text = intro_for(read_event())
        if text:
            emit({"hookSpecificOutput": {"hookEventName": "SubagentStart",
                                         "additionalContext": text}})
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
