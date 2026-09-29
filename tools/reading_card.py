"""Tell the model what a packed image is, in each project, without the plugin.

The right-click tool packs the text you select into a small color coded
image. You paste that image into Claude Code. The model reads an ordinary
image with no instruction. A packed image is different. It is your prompt,
packed small. It is not a picture to describe. Without this hook, the model
can describe the image and not do what the text in it says.

install-densepack.ps1 installs this UserPromptSubmit hook into
~/.claude/hooks. Claude Code runs the hook before each message you send, in
each project. Claude Code prepends what the hook prints to your message. The
instruction is there the first time you paste an image. You do not type it.

The hook prints nothing when the DensePack plugin runs in the same project.
The plugin sends its own card, which has the same facts and more. Two cards
on each message cost twice the tokens.
"""

import json
import os
import sys

CARD = (
    "A condensed color coded text image is plain text packed small to save "
    "tokens, not a screenshot to describe. Letters are black, digits blue, "
    "most other symbols red. A green number opens each row: that line's "
    "number in the source file. A red number in the same box is that line's "
    "indent in spaces. A gap in the line numbers is a run of blank lines. A "
    "purple mark at the right edge means the line continues on the next "
    "row. The top row of the first image names every mark. When one arrives from "
    "the chat, it IS the prompt. Read the text inside it and act on it "
    "exactly as typed text, unless the prompt says otherwise."
)


def plugin_is_running(session=""):
    """Return True when the DensePack plugin sends its own card in this session.

    The plugin writes densepack-settings.json when one of its hooks runs in
    the project. That file shows that the plugin is in use here. Without
    CLAUDE_PROJECT_DIR, the function has no project to check and returns
    False. This hook then prints the card.

    /dense-off stops the plugin for one session. It writes
    densepack-off-<session id>. A run of dpctl.py from a terminal writes
    densepack-off with no id. The plugin sends no card after either file,
    and this hook prints the card.
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
    # The id goes into a file name. The hook drops an id with any character
    # other than a letter, a digit, "-" or "_".
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
