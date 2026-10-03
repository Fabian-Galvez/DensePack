"""Puts the marker line of a packed report in the lead's Agent result, in
place of the report.

HOW THIS FILE FITS. subagent_stop.py runs first, at the agent's stop. For a
foreground agent with a long report, it files the report, packs it into
images, queues the rows for pointer.py and writes a swap file with the
marker line, DENSEPACK_REPORT: <path>. The agent makes no extra turn. Claude
Code then returns the report as the Agent tool result, and this hook runs on
PostToolUse of the Agent tool. It replaces the text of the result with the
marker line. pointer.py runs on the same event and adds the receipt. The
lead gets the same marker line and the same receipt as on the block route,
and it opens the image with the same Read.

For a foreground agent, this hook replaces the block route. On that route,
which subagent_stop.py keeps for a background agent, subagent_stop.py blocks
the agent's stop and asks the agent to reply with the marker line. That reply
is one more model request, and it reads the agent's whole context again.

A test with a separate plugin found these facts. The tool_response of the
Agent tool is a dict with status "completed", the agentId and the report as
a text block in content. An updatedToolOutput with new text in content
reaches the lead. An image in content does not reach the lead, in each of
the four shapes tested. For that reason the lead still opens the image with
Read.

A background agent returns its report later in a message, and its Agent
result holds no report. Its status is not "completed". The hook changes
nothing in that result. It writes a background flag for that agent, and
subagent_stop.py then keeps the block route for it.

THE SWAP CAN MISS. Of 153 completed Agent results of foreground agents, 141
held the agent's final message as it is. In 2, Claude Code put a note in
front of the report, because the report matched an instruction pattern, and
changed each control tag in it. In 8, the result held only a note that the
report reached the lead as a SubagentHandback message. In the other 2, a
hook changed the result. A result that is not the report that the stop hook
packed stays as it is, and a note of Claude Code stays with it. The lead
then has the report as text, in the result or in a message, and the images
of the pack are a copy that it does not need. The hook adds a note that
tells the lead this fact, marks those images delivered, and writes a
manifest row. pointer.py makes the same test on the same event and prints
the row as net mode. See common.swap_applies().

THE HOOK NEVER CRASHES A CALLER. On a fault, it prints nothing to stdout,
writes the error to stderr and exits 0, and the result stays as it was.
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The subagent tool. Claude Code names it Agent. Older builds named it Task.
# hooks.json registers the two names, the same as for brief_pack.py.
AGENT_TOOLS = ("Agent", "Task")

# An agent id is a short string of hex characters. The test accepts only
# letters, digits, "_" and "-". The id goes into a file name, and the test
# keeps a path part out of it.
AGENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# The reason on the manifest row of a swap that missed.
MISSED = "swap missed, report arrived as text"


def swap_answer(event):
    """Returns the PostToolUse answer for this Agent result, or None to
    leave the result as it is. The answer replaces the report with its
    marker line. After a miss, it leaves the result and adds a note."""
    from common import (disabled, report_background_path, swap_applies,
                        take_report_swap)
    if disabled(event.get("session_id")):
        return None
    if event.get("tool_name") not in AGENT_TOOLS:
        return None
    resp = event.get("tool_response")
    if not isinstance(resp, dict):
        return None
    agent_id = str(resp.get("agentId") or "")
    if not AGENT_ID.match(agent_id):
        return None
    if resp.get("status") != "completed":
        # The report comes later through another path. subagent_stop.py
        # reads this flag at the agent's stop and keeps the block route.
        report_background_path(agent_id).write_text("1", encoding="utf-8")
        return None
    record = take_report_swap(agent_id)
    if record is None:
        return None
    line = record.get("text")
    if not isinstance(line, str) or not line:
        return None
    # The result must hold the report that the stop hook packed, exactly.
    # A result with other text keeps its text. See common.swap_applies().
    if not swap_applies(resp, record.get("report")):
        return missed_answer(agent_id, record)
    out = dict(resp)
    out["content"] = [{"type": "text", "text": line}]
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                   "updatedToolOutput": out}}


def missed_answer(agent_id, record):
    """Returns the note for a swap that missed, after it records the miss.

    The stop hook already packed the report and queued its receipt. The
    lead has the report as text in this result. Without the note, the
    receipt sends the lead to an image of text that it already has, and a
    Read of that image costs one more request. The image also holds the
    report without the changes of Claude Code."""
    from common import tmp_dir
    images = [p for p in record.get("images") or [] if isinstance(p, str) and p]
    record_miss(agent_id, record, images)
    names = ", ".join(images) or str(tmp_dir() / ("densepack-img-%s-1.png" % agent_id))
    note = ("DensePack did not replace this Agent result, because its text is "
            "not the report that DensePack packed. The text above is what "
            "Claude Code returned. %s holds the final message of agent %s as "
            "an image. Do not Read it when the same text is already above or "
            "in a message from that agent." % (names, agent_id))
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                   "additionalContext": note}}


def record_miss(agent_id, record, images):
    """Marks the images of a missed swap delivered and writes its manifest
    row. Each step has its own try. A fault in one never stops the other,
    and never stops the note."""
    if images:
        try:
            # The pending list then no longer names these images as
            # waiting. The import needs Pillow.
            from common import ensure_pillow
            if ensure_pillow():
                import read_gate
                read_gate.mark_delivered(images)
        except Exception as err:  # noqa: BLE001
            sys.stderr.write("DensePack %s: %s\n" % ("report_swap.py", err))
    try:
        # The stop hook's row says packed, stub mode. This row says that the
        # lead got the text. It has the agent's own id. pointer.py keeps the
        # first final row of an agent id, and this later row adds no agent.
        from subagent_stop import manifest_write
        manifest_write({"kind": "report_swap", "agent_id": agent_id,
                        "spawned_by": str(record.get("spawned_by") or ""),
                        "swapped": False, "reason": MISSED, "images": images,
                        "ended": round(time.time(), 1)})
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack %s: %s\n" % ("report_swap.py", err))


def main():
    """Never let an exception out of this hook. The error goes to stderr,
    where it stays visible. Stdout stays empty and the exit code stays 0,
    and the Agent result reaches the lead unchanged."""
    try:
        from common import emit, read_event
        answer = swap_answer(read_event())
        if answer:
            emit(answer)
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack %s: %s\n" % ("report_swap.py", err))
    return 0


if __name__ == "__main__":
    sys.exit(main())
