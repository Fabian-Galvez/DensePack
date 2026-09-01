"""Stops the lead reading an image or a repo's source into its own context.

HOW THIS FILE FITS, in plain words: DensePack saves by keeping a subagent's
reading and editing out of the lead's context, so the lead pays only for a
short report. Nothing stopped the lead doing that reading itself. This is a
PreToolUse hook on the Read tool, the same shape as tier_gate.py: it looks
at a call the lead is about to make and denies the ones that do a
subagent's job instead of delegating it.

WHY IT EXISTS, measured in a real session on 27 August 2026. The subagents
that session spawned burned about 478,000 tokens between them and returned
reports of a few hundred tokens each, the trade this plugin is built to
make. The lead's own context reached 137,000 tokens in the same session and
is re-read at the start of every turn, which is the cost that never goes
away on its own. Most of that context came from the lead doing the work
itself: reading source files, running measurement scripts, and above all
opening six window screenshots with the Read tool. A subagent's Read call
never reaches the lead. The lead's own Read call becomes the lead's
context, for the rest of the session.

WHAT IT BLOCKS.

  Hard: the lead using Read on an image file, meaning .png, .jpg, .jpeg,
  .gif, .webp or .bmp. An image is the most expensive single thing the lead
  can put in its own context, and once it is there it never leaves: every
  later turn re-sends it. The answer to a picture is a question, and a
  subagent can read the picture and hand that answer back as a few words
  of text.

  Soft: the lead using Read on a file inside a repo's own src or tests
  tree, anywhere under Repos\\<any repo>. The lead's job is to write briefs
  and read reports. Verification, meaning working out whether a number in a
  file is right, belongs in a subagent's context, and the number comes back
  in the report. Reading the source directly to check it is the subagent's
  job, done in the wrong context.

WHAT IT NEVER BLOCKS. Anything DensePack itself wrote or drew, named
densepack-<something>: the report and briefing images pointer.py and
read_gate.py already point the lead at, and the settings, manifest and
totals files under .claude/tmp. Blocking one of those would stop the lead
taking the exact saving this plugin exists to hand over. Also never
blocked, whatever folder it sits in: a report file, a settings file, a
memory file, CLAUDE.md or HANDOFF.md. Those are what the lead is supposed
to read; the soft rule above is what the lead is supposed to hand off
instead.

FIXED 29 August 2026, FIXES-PENDING.md section 3. The densepack- exemption
above used to be keyed on the name alone, which let the lead Read a
source-text sidecar such as densepack-src-<agent id>.txt or
densepack-briefsrc-<stamp>.txt raw, even where the packed image beside it,
densepack-img-<agent id>-1.png or densepack-brief-<stamp>-1.png, already
held the same words: the same leak source_gate.py already stops on the
Bash side. Before either the hard or soft rule is judged, and before the
name exemption below, common.sibling_image() checks the file's own name
against the patterns the packers write; when the image it names exists on
disk, the Read is redirected there instead of allowed through as text.

WHO THIS FIRES FOR. The lead session only, never a subagent. Two answers
decide it, and the session id alone was not one of them. MEASURED 31 August
2026: a subagent's PreToolUse carries its LEAD's session_id, so the
read_leads() test below answered True for a subagent and both messages here
told a subagent to send a subagent. is_subagent() is checked first now: the
event's agent_id and agent_type name the real actor, present on a
subagent's call and empty on the lead's.

Second, bootstrap.py's SessionStart hook is the one event a subagent never
fires, and it is what records a session's id as a lead's, in
common.add_lead(), read back by common.read_leads(). This gate fails OPEN
on that question, which is the opposite of most gates here: an id it cannot
confirm as a lead's is treated as NOT the lead, and the Read goes through
unjudged. A subagent doing the exact reading this gate exists to push the
lead toward must never be stopped doing it, and that is worse than the rare
miss where a lead's own call goes unblocked because its session was never
recorded.

THE ESCAPE. The Read tool carries no field a caller can write a sentence
into, unlike Bash's command or Agent's prompt, so the phrase that stands
this gate aside cannot ride the call itself. It rides the conversation
instead: the user types "read override approved" and the next matching
Read goes through. The check reads the last line the user actually typed,
off the session's own transcript, the same file common.transcript_path()
already finds for read_cost_line(). A transcript that cannot be read is not
proof the phrase was said, so the gate stays up.

TWO WAYS TO SWITCH IT OFF. /agentpack-off turns off every delegation rule
this plugin enforces, this one included, through the same agentpack setting
tier_gate.py answers to. /densepack-off, the one switch for the whole
plugin, stands this down too. The sibling-image redirect in main(), added
29 August 2026, is NOT a delegation rule and does not check agentpack: only
/densepack-off stands it down. It answers "does a drawn image already hold
these exact words", the same question source_gate.py answers on the Bash
side, never "should this reading be the lead's job".

NEVER CRASH A CALLER. Everything that decides whether to deny a call is
wrapped in one try. Anything unexpected inside it is treated as allow, the
same failure mode every other gate in this folder chooses.
"""

import re
import sys

import gate_cost

from common import (disabled, emit, read_event, read_leads, settings,
                    sibling_image, user_said)

# Matched on a case-insensitive suffix, after the separators are turned to
# forward slashes, so a Windows path and a POSIX one are judged the same way.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

# A repo's own source or test tree, anywhere under Repos\<repo name>.
# Matched with a separator on both sides of src and tests, so a folder that
# only CONTAINS those letters, such as srcbackup or testsuite, does not
# count. [/\\] rather than os.sep, because the Read tool takes either
# separator on Windows and the event's own path is not normalised first.
SRC_TREE = re.compile(r"[/\\][Rr]epos[/\\][^/\\]+[/\\](?:src|tests)(?:[/\\]|$)")

# Exact file names never blocked by the soft rule, whatever folder they sit
# in, matched on the lower-cased base name.
EXCEPT_NAMES = ("claude.md", "handoff.md", "memory.md")

# Words that, found anywhere in the lower-cased base name, mean this is a
# report or a settings file rather than source to verify. "report" also
# catches a plain report.md or bug_report.txt outside this plugin's own
# naming, which the DENSEPACK_OWN check below does not reach.
EXCEPT_WORDS = ("report", "settings")

# The phrase that stands the gate aside for one Read. Deliberate rather than
# a flag, so it cannot be typed by accident, the same approach tier_gate.py
# and agent_floor.py take for their own escapes.
ESCAPE = "read override approved"

IMAGE_MESSAGE = (
    "DensePack stopped this Read. An image is the most expensive single "
    "thing the lead can put in its own context, and once it is read here it "
    "never leaves: every later turn in this session re-sends it. Send a "
    "subagent the question about this picture instead, and read the answer "
    "back as a few words of text in its report.\n\n"
    "File: %s\n\n"
    "To read this exact image anyway, say \"%s\" and ask for the Read "
    "again.\n\n"
    "This check follows the agentpack setting. /agentpack-off turns it off "
    "along with every other delegation rule."
)

SRC_MESSAGE = (
    "DensePack stopped this Read. The lead writes briefs and reads reports. "
    "Checking a repo's own source or test file is verification, and "
    "verification belongs in a subagent's context, not the lead's. Send a "
    "subagent to read this file and answer the question; the number comes "
    "back in its report instead of being worked out again here.\n\n"
    "File: %s\n\n"
    "To read this exact file anyway, say \"%s\" and ask for the Read "
    "again.\n\n"
    "This check follows the agentpack setting. /agentpack-off turns it off "
    "along with every other delegation rule."
)


def is_lead(session_id, leads):
    """True only when this session's id is on record as a lead's.

    See THE HEADER: unlike every other gate in this folder, an answer this
    function cannot prove true is treated as false, not true. A missing
    session id or an empty leads list means allow, never block.
    """
    return bool(session_id) and bool(leads) and str(session_id) in leads


def is_plugin_file(path):
    """True for anything DensePack itself drew or wrote.

    Every image and note this plugin hands the lead by design carries this
    prefix: a report or briefing image, or a settings, manifest or totals
    file under .claude/tmp. Blocking one of these would stop the lead taking
    the exact saving this plugin exists to hand over.
    """
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name.startswith("densepack-")


def is_excepted(path):
    """True for anything the soft rule must never block, whatever folder it
    sits in: DensePack's own files, a report or settings file by name, a
    memory file, CLAUDE.md, HANDOFF.md, or anything under .claude."""
    if is_plugin_file(path):
        return True
    norm = path.replace("\\", "/").lower()
    parts = norm.split("/")
    name = parts[-1]
    if name in EXCEPT_NAMES:
        return True
    if ".claude" in parts:
        return True
    return any(word in name for word in EXCEPT_WORDS)


def is_image(path):
    return path.replace("\\", "/").lower().endswith(IMAGE_SUFFIXES)


def escape_used(session_id):
    """True when the last line the user actually typed carried the escape
    phrase.

    The Read tool has no field a caller can write a sentence into, unlike
    Bash's command or Agent's prompt, so the phrase that stands this gate
    aside rides the conversation instead of the call. The transcript walk
    itself is common.user_said(), shared with delegate_gate.py so the two
    gates cannot drift apart on what counts as a typed message.
    """
    return user_said(session_id, ESCAPE)


def is_subagent(event):
    """True when a subagent made this call, not the lead.

    MEASURED 31 August 2026: a subagent's PreToolUse carries the LEAD's
    session_id and transcript_path, so is_lead() above answers True for a
    subagent and both messages here then tell a subagent to send a
    subagent. agent_id and agent_type name the real actor, the same two
    fields subagent_start.py reads at spawn. Empty or absent means the
    lead, so an unprovable actor stays gated.

    Twin of delegate_gate.is_subagent(). Both belong in common.py, and
    sit here while another change holds common.py open.
    """
    return bool(event.get("agent_id")) or bool(event.get("agent_type"))


def main():
    # NEVER CRASH A CALLER. This runs before every Read in the session.
    try:
        # The event is read FIRST so the off switch can be asked about the
        # session that fired it. The switch has been per session since 31
        # August 2026, and disabled() with no id in hand falls back to
        # lead_session(), which in a project open in two windows answers
        # for the OTHER window. Nothing above this line touches the
        # session, so the master switch is still the first thing that can
        # stop the gate, ahead of every per feature setting below.
        event = read_event()
        if disabled(event.get("session_id")):
            return 0

        if (event.get("tool_name") or "") != "Read":
            return 0
        if is_subagent(event):
            return 0
        if not is_lead(event.get("session_id"), read_leads()):
            return 0

        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        path = tool_input.get("file_path")
        if not isinstance(path, str) or not path:
            return 0

        # Checked before the agentpack switch below, and before the name
        # exemption further down: a source-text sidecar with a drawn image
        # beside it is redirected to that image, never let through raw on
        # the strength of its name. This is a packing-hygiene fix, the same
        # kind source_gate.py already makes on the Bash side and
        # drop_read_gate.py makes for every Read, neither of which checks
        # agentpack either: reading the text instead of the image it
        # already cost tokens to draw is not a delegation question, and
        # must not be silenced by /agentpack-off. FOUND 29 August 2026: an
        # earlier version of this fix sat below the agentpack check, so a
        # session with /agentpack-off set (this one, live, when the
        # coordinator re-tested) returned before the event was even read,
        # and the redirect never ran for the lead at all.
        image = sibling_image(path)
        if image is not None:
            tool_input["file_path"] = image
            emit({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": tool_input,
                }
            })
            return 0

        # Everything below this line is a delegation rule and follows
        # agentpack, same as before.
        if settings().get("agentpack") == "off":
            return 0

        if is_excepted(path):
            return 0
        if is_image(path):
            message = IMAGE_MESSAGE
            source_read = False
        elif SRC_TREE.search(path) is not None:
            message = SRC_MESSAGE
            source_read = True
        else:
            return 0

        if escape_used(event.get("session_id")):
            return 0

        # THE PRICED STAND-DOWN, for a source or test file only. An image
        # keeps its unconditional deny: once read it never leaves the
        # lead's context, so every later turn in the session re-sends it,
        # and that is not one call's worth of cost. A source file is not
        # like that. Priced as the packed image this plugin would draw for
        # it, one Read costs 81,660 tokens at the Opus reader's 10 px
        # against the 824,968 one spawn costs whatever the agent then
        # does. MEASURED in the benchmark leg: this deny bought an extra
        # 54,225 token request to avoid a packed read worth a fraction of
        # that, which is the plugin spending more than it saves.
        #
        # The total is per session and cumulative, so this is not a licence
        # to read the whole tree. Bulk verification crosses the spawn price
        # and the deny comes back, which is the case this gate was built
        # for. Same mechanism and the same constants as delegate_gate.py,
        # and every constant's source line is cited in gate_cost.py.
        if source_read:
            direct = gate_cost.add_direct(
                event.get("session_id"),
                gate_cost.command_price(
                    gate_cost.would_pack("Read", tool_input)),
                read_leads())
            if gate_cost.cheaper_direct(direct):
                return 0

        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": message % (path, ESCAPE),
            }
        })
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
