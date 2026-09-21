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
    "tokens, not a screenshot to describe. Letters are black, digits blue, "
    "most other symbols red. A green number opens each row: that line's "
    "number in the source file. A red number in the same box is that line's "
    "indent in spaces. A gap in the line numbers is a run of blank lines. A "
    "purple mark at the right edge means the line continues on the next "
    "row. The top row of the first image names every mark. When one arrives from "
    "the user it IS the user's prompt: read the text inside it and act on it "
    "exactly as if it had been typed, unless the user says otherwise."
)


def plugin_is_running(session=""):
    """True when the DensePack plugin sends its own card in this session.

    The plugin writes densepack-settings.json when one of its hooks runs in
    the project, so that file shows the plugin is in use here. A missing
    CLAUDE_PROJECT_DIR means no project to check, so this hook prints the card.

    /dense-off stops the plugin for one session. It writes
    densepack-off-<session id>, and a run of dpctl.py from a terminal writes
    densepack-off with no id. The plugin sends no card after either one, so
    this hook prints the card.
    """
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        return False
    tmp = os.path.join(root, ".claude", "tmp")
    if os.path.exists(os.path.join(tmp, "densepack-off")):
        return False
    if session and os.path.exists(os.path.join(tmp, "densepack-off-" + session)):
        return False
    return os.path.exists(os.path.join(tmp, "densepack-settings.json"))


def main():
    session = ""
    try:
        event = json.loads(sys.stdin.read() or "{}")
        session = str(event.get("session_id") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    # The id goes into a file name, so an id with any other character is not used.
    if not session.replace("-", "").replace("_", "").isalnum():
        session = ""
    if plugin_is_running(session):
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
