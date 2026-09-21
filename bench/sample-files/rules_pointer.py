"""Sends the rules pointer right before the first spawn, Write or Edit.

HOW THIS FILE FITS, in plain words: the plugin draws its rules as one image,
allrules-1.png, and a lead has to read that image before it spawns an agent
or writes a document. Until 7 September 2026 bootstrap.py sent the one line
naming that image at session start, and prompt_card.py sent the card about
pictures on the first message. Both arrived before the model knew its task,
and Opus read them and thought about them: with the plugin on it opened a
thinking block on 7 of 11 runs of a read-and-answer task, with the plugin
off on none, and the thinking cost more than the picture saved. The record
is bench/session-2026-09-07/SESSION-2026-09-07.md.

This hook runs before the Agent, Task, Write and Edit tools and sends the
same line once per session, at the moment it is needed. A session that only
reads and answers never receives it.

A Write or an Edit gets the line only when its file is a Markdown document
or a README, which is what the line itself names. Before 8 September 2026
any Write got it, so a task that wrote answers.txt received an instruction
to open a rules picture it had no use for: Sonnet named that line as an
attempt to redirect it, and on three of twenty runs of the sixteen file
bench it wrote no answers at all. The record is
bench/session-2026-09-07/SESSION-2026-09-07.md.
"""
import sys

from common import disabled, emit, read_event, tmp_dir

TOOLS = ("Agent", "Task", "Write", "Edit")
FILE_TOOLS = ("Write", "Edit")
DOC_SUFFIXES = (".md", ".markdown")


def targets_document(tool_input):
    """True when a Write or an Edit names a Markdown document or a README."""
    path = str((tool_input or {}).get("file_path") or "")
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.startswith("README") or name.lower().endswith(DOC_SUFFIXES)


def main():
    event = read_event()
    if disabled(event.get("session_id")):
        return 0
    tool = event.get("tool_name")
    if tool not in TOOLS:
        return 0
    if tool in FILE_TOOLS and not targets_document(event.get("tool_input")):
        return 0
    session = str(event.get("session_id") or "")
    marker = tmp_dir() / ("densepack-rules-pointer-%s" % session)
    if marker.exists():
        return 0
    from bootstrap import session_start_pointer
    text = session_start_pointer(True)
    try:
        marker.write_text("sent", encoding="utf-8")
    except OSError:
        pass
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": text,
    }})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack rules_pointer.py: %s\n" % err)
        sys.exit(0)
