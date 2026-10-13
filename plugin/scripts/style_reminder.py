"""Adds one line before the next model call: follow the rules of the start note.

The start note carries the rules once, at session start, and each later request
reads them from the prompt cache. In a long session the agent stops following
them, because they sit far back. This line points back to them for about 15
tokens and no extra request: PostToolBatch and UserPromptSubmit hooks add
context to a request that Claude Code already sends.

No line when DensePack is off or the rules file is gone, because then the start
note has no rules to point at.
"""

import json
import os
import sys

from common import disabled, emit

RULES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "rules", "STYLE-RULES.md")
LINE = "Follow the DensePack rules from the session start in this reply."


def main():
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    name = event.get("hook_event_name")
    if name not in ("PostToolBatch", "UserPromptSubmit"):
        return 0
    if disabled(event.get("session_id")) or not os.path.isfile(RULES_FILE):
        return 0
    emit({"hookSpecificOutput": {"hookEventName": name, "additionalContext": LINE}})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        sys.exit(0)
