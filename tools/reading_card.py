"""Tells Claude what a condensed image is, in every project, with no plugin.

HOW THIS FILE FITS, in plain words: the right-click tool packs whatever text
you have selected into a small color coded image, and you paste that image
into Claude. Claude reads an ordinary image without being told anything. A
condensed image is different: it is your PROMPT drawn small, not a picture to
describe, and without a standing instruction Claude can answer by telling you
what it sees rather than doing what it says.

This is a UserPromptSubmit hook installed by install-densepack.ps1 into
~/.claude/hooks. Claude Code runs it before every message you send, in every
project, and prepends what it prints to your message. So the instruction is
already there the first time you paste an image, and you never type it.

It prints nothing when the DensePack PLUGIN is running in the same project. The
plugin ships its own standing reminder that says all this and more, and two copies
would arrive on every message and cost twice. The plugin is the fuller of the
two, so this one yields to it.
"""

import json
import os
import sys

CARD = (
    "A condensed color coded text image is plain text drawn small to save "
    "tokens, not a screenshot to describe. Its letters are black, digits "
    "blue, symbols red, and a green paragraph sign marks a line break. When "
    "one arrives from the user it IS the user's prompt: read the text inside "
    "it and act on it exactly as if it had been typed, unless the user says "
    "otherwise."
)


def plugin_is_running():
    """True when the DensePack plugin already covers this project.

    Its settings file only exists once a DensePack hook has run here, so its
    presence is the cheapest honest signal that the fuller card is arriving
    anyway. A missing CLAUDE_PROJECT_DIR means no project to check, so this
    card speaks.
    """
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        return False
    tmp = os.path.join(root, ".claude", "tmp")
    if os.path.exists(os.path.join(tmp, "densepack-off")):
        return False
    return os.path.exists(os.path.join(tmp, "densepack-settings.json"))


def main():
    try:
        sys.stdin.read()
    except Exception:  # noqa: BLE001
        pass
    if plugin_is_running():
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": CARD,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
