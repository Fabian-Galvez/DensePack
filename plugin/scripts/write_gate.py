"""Holds a Write, Edit or Bash call until the agent has read the full rules
image.

HOW THIS FILE FITS, in plain words: fullrules.txt teaches how a file this
project's GitHub will show must read. An agent that writes such a file
without reading that image first writes to its own guess. This hook denies
the first Write, Edit or Bash write of such a target per agent, once,
naming the image to read; the identical retry passes.

ORIGINAL NOTE: PreToolUse hook on Write and Edit. PLAN-FABLE.md, "Write and
Edit gate", step 6, 29 August 2026.

BASH ADDED 30 August 2026. A Write or Edit call is not the only way a
README or a Repos document lands on disk: `cat > README.md <<'EOF'` and
`echo "..." > Repos/<repo>/doc.md` write the same bytes through the Bash
tool, which this file never watched. hooks.json already runs three hooks
on every Bash call; this adds a fourth to that same "Bash" matcher rather
than opening a new one, so a route with existing hook coverage gets this
check added to it instead of a hook of its own. bash_target_paths() reads
the command text for a redirect, exactly the shape bash_gate.py already
parses to detect one for its own, unrelated reason (skipping a command
whose output already goes to a file). NotebookEdit was checked and left
alone: its tool_input carries notebook_path, always a .ipynb file, which
matches neither a README name nor a .md extension, so no Write-style
gate would ever fire on it; adding a matcher for it would gate nothing.

WHAT COUNTS AS A TARGET, from the Write and Edit gate table: a .md file
with "Repos" as one of its path folders, or any file whose name starts with
README. A scratchpad file, a test fixture, a log, or any other path passes
at no cost. A Bash redirect target is judged the same way, resolved against
the event's own cwd first when the command named a relative path.

THE MARKER is one file per session, holding nothing but its own existence.
A session is what this plugin calls an agent everywhere else a marker is
scoped this way, subread_gate.py's own per-file marker included. Every
writing agent reads the full rules image once; a different session id is
denied again on its own first visible write, because each session gets its
own marker file.

WHICH IMAGE THE REASON NAMES. event_reader() reads the writing agent's own
model from that agent's own transcript, the same lookup the Read gates use,
so a Sonnet subagent in an Opus session is pointed at the sonnet image, the
12 px size it was scored at. Bench pair 39, 30 August 2026, measured the
old way costing: a Sonnet agent squinted at the lead's 10 px opus image,
below its 12 px floor, then rewrote one 11,257 character README three times
through style denies. A reader event_reader() cannot place is pointed at
plugin/instructions/fullrules.txt, the text the images are drawn from,
because an image drawn for another tier sits off that reader's floor.

THE SECOND CHECK IN THIS FILE, added 30 August 2026: the same Write or Edit
call is also held for its wording, on the same targets plus a vault note,
when the user has turned the writing rules on with /stylepack. This is the
write path literal_check.SCOPES calls out: a file here has not reached the
reader or GitHub yet, so a deny costs one retry before the first version is
ever seen, and nothing is scoped down for it the way a chat reply is in
stop_gate.py. All seven checks run, unweakened.

NEVER CRASH A CALLER. One try around everything; any fault allows the
Write or Edit through, because a blocked write is worse than an unread
rule.
"""

import hashlib
import re
import sys
from pathlib import Path

from common import (disabled, emit, event_reader, read_event, resolved_reader,
                    settings, tmp_dir, vault_dir, MEASURED_MODELS,
                    _model_from_transcript)

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import literal_check
except ImportError:
    literal_check = None

# One marker per session, not per file: the gate is read-the-rules-once for
# the agent, not read-the-rules-once-per-target.
MARKER = "densepack-fullrules-%s"

DENY = "Read %s, then retry this exact call."


def marker_path(session_id):
    digest = hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()[:12]
    return tmp_dir() / (MARKER % digest)


def targets_full_rules(path):
    """True for a .md file with Repos as one of its folders, or any file
    named README*. False for a scratchpad file, a test fixture, a log, or
    any other path, which pass at no cost."""
    norm = str(path).replace("\\", "/")
    parts = [p for p in norm.split("/") if p]
    if not parts:
        return False
    name = parts[-1]
    if name.startswith("README"):
        return True
    if not name.lower().endswith(".md"):
        return False
    return "Repos" in parts[:-1]


# A stream join such as 2>&1 or >&2 sends one stream into another; the text
# still reaches the conversation rather than a file, so it is not a write.
# Removed before hunting for a real redirect, the same fix bash_gate.py's own
# STREAM_JOIN makes for its own, unrelated reason.
_STREAM_JOIN = re.compile(r"\d?>&\d")

# A `>` or `>>` not already consumed by a stream join, followed by the token
# it writes to. Quotes around the token are stripped in code, not the regex,
# so `> "Repos/x.md"` and `> Repos/x.md` resolve to the same path.
_REDIRECT = re.compile(r">>?\s*([^\s;|&()<>]+)")


def bash_target_paths(command, cwd=None):
    """Every path a Bash command's own `>` or `>>` writes to, resolved
    against `cwd` when the command named a relative one.

    Reads the same shape bash_gate.py already parses (a heredoc's own `<<`
    is not touched; the file this writes to is still named after a plain
    `>`). A command with no redirect returns an empty list, the safe
    failure: nothing here denies a call it cannot show writes to a file.
    """
    if not isinstance(command, str) or not command:
        return []
    stripped = _STREAM_JOIN.sub("", command)
    out = []
    for match in _REDIRECT.finditer(stripped):
        token = match.group(1).strip("'\"")
        if not token or token in ("&1", "&2"):
            continue
        path = Path(token)
        if not path.is_absolute() and cwd:
            path = Path(cwd) / token
        out.append(str(path))
    return out


def targets_style_check(path):
    """True for a file the reader or GitHub will read once this call lands:
    the same README or Repos-document targets as targets_full_rules().
    False for a scratchpad file, a test fixture, a log, or any other path,
    which pass at no cost."""
    return targets_full_rules(path)


WRITE_STYLE_DENY = (
    "DENY. %s breaks a writing rule this session has turned on with "
    "/stylepack, LITERAL SENTENCES ONLY.%s\n\n"
    "Rewrite the flagged text and retry the call. Do not explain the "
    "correction and do not mention this message."
)


def style_deny(event, path):
    """The reason to deny a Write or Edit whose content breaks a writing
    rule, or None.

    Only runs when the user turned the writing rules on with /stylepack,
    and only on a file the reader or GitHub will read: see
    targets_style_check(). Every one of literal_check's seven checks applies
    here, scope="write", because this file has not reached anyone yet and a
    deny costs one retry, not a second whole reply the way a chat block
    does in stop_gate.py.
    """
    if literal_check is None:
        return None
    if settings().get("stylecard", "off") != "on":
        return None
    if not targets_style_check(path):
        return None
    tool_input = event.get("tool_input") or {}
    content = tool_input.get("content")
    if content is None:
        content = tool_input.get("new_string")
    if not isinstance(content, str) or not content:
        return None
    hits = literal_check.find(content, scope="write")
    if not hits:
        return None
    return WRITE_STYLE_DENY % (path, literal_check.note(hits))


def rules_image(event):
    """The full rules path the deny reason names: the writing agent's own
    reader from its transcript, the lead's when the transcript cannot be
    read, and the fullrules text file for a model the transcript names but
    no scored size covers, because that writer cannot read any tier's
    image."""
    reader = event_reader(event)
    if reader is None:
        path = event.get("transcript_path") if isinstance(event, dict) else None
        named = _model_from_transcript(path) if path else None
        if not named:
            reader = resolved_reader()
    if reader in MEASURED_MODELS:
        return vault_dir() / "instructions" / reader / "allrules-1.png"
    return Path(__file__).resolve().parents[1] / "instructions" / "fullrules.txt"


def _deny_unread(event, sid):
    """Write this session's marker and emit the read-first deny, once.

    Shared by the Write/Edit path and the Bash path below: both name a
    target this session has never been gated on, and both are denied the
    same way, pointed at the same image.
    """
    marker = marker_path(sid)
    if marker.exists():
        return False
    # Written before the deny goes out: a fault after this line lets the
    # call through with the marker already down, which only means this one
    # agent was never gated. The reverse order could deny the same agent
    # forever if emit() itself failed.
    try:
        marker.write_text("1", encoding="utf-8")
    except OSError:
        return False
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY % rules_image(event),
        }
    })
    return True


def main():
    # NEVER CRASH A CALLER. This runs before every Write, every Edit, and
    # every Bash call.
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0

        tool = event.get("tool_name") or ""
        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0

        if tool == "Bash":
            # A Write or Edit is not the only way a README or a Repos
            # document lands on disk: `cat > README.md <<'EOF'` and
            # `echo "..." > Repos/<repo>/doc.md` write the same bytes
            # through Bash, which the file_path check below never sees.
            # Only the read-the-rules-once gate runs here, not style_deny:
            # that check reads tool_input["content"] or ["new_string"],
            # neither of which a Bash call carries, and pulling the written
            # text back out of arbitrary shell quoting is not this file's
            # job.
            command = tool_input.get("command")
            sid = str(event.get("session_id") or "")
            if sid:
                for candidate in bash_target_paths(command, event.get("cwd")):
                    if targets_full_rules(candidate):
                        _deny_unread(event, sid)
                        return 0
            return 0

        if tool not in ("Write", "Edit"):
            return 0

        path = tool_input.get("file_path")
        if not isinstance(path, str) or not path:
            return 0

        if targets_full_rules(path):
            sid = str(event.get("session_id") or "")
            if sid and _deny_unread(event, sid):
                return 0

        # The rules-image gate above did not deny this call, so check the
        # second thing this file gates: the wording of what is about to be
        # written. Independent of the marker above, so a session that has
        # already read the rules image is still held for a style fault.
        reason = style_deny(event, path)
        if reason:
            emit({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            })
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
