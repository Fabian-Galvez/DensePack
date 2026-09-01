"""Refuses to let a reply land while a receipt is owed. The gate.

HOW THIS FILE FITS, in plain words: when subagents finish, pointer.py hands the
lead a receipt table and asks it to print that table with the rows labeled by
the task each agent was given. The lead is the only one that knows those tasks,
so no hook can write those labels.

The lead skipped printing it twice, on 18 August 2026. The fix that day was to
send the user a systemMessage as well, so the numbers reach the user whatever
the lead does. That fixed the user's problem. It did not make the lead comply,
because nothing checked whether it had.

This does. It is a Stop hook: Claude Code fires it when the assistant thinks it
has finished, and hands it last_assistant_message. Returning decision block
with a reason sends the assistant back to work. Proved live on 19 August 2026
with a probe that demanded a nonsense word and got it.

The rule enforced here is narrow on purpose:

  Owed      pointer.py wrote a receipt this turn and named at least one agent.
  Satisfied the reply contains a markdown table row, which is the only shape a
            receipt can take.
  Blocked   a receipt was owed and no table appeared.

Nothing about the CONTENT of the table is checked. The numbers are the hook's
own and are already in front of the user. What is enforced is that the lead
does not silently drop the one part only it can supply.

The loop guard is not optional. Claude Code sets stop_hook_active on the retry,
and this file blocks once per turn and never twice, so a reply always lands.
"""

import json
import re
import sys
import time
from pathlib import Path

from common import (disabled, emit, has_edited, read_event, read_leads,
                    settings, stale_agents, tmp_dir, transcript_path)

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import literal_check
except ImportError:
    literal_check = None
# job_for_marker turns a stale agent's start marker into the task it was
# given, so the messages below can name that instead of the internal agent
# id. Importing pointer.py here is not a loop: pointer.py imports common.py,
# and common.py never imports pointer.py back.
from pointer import job_for_marker  # noqa: E402
import watchdog  # noqa: E402

# pointer.py drops this file when it hands the lead a receipt, and this hook
# deletes it once the turn is settled. Its presence IS the debt.
OWED_FILE = "densepack-receipt-owed.json"

# A markdown table row. The receipt is a table in every mode that prints one,
# so one row of any table is enough to show the lead relayed something. A
# stricter test would fail on a lead that correctly relabelled the rows.
# The RECEIPT, not just any table. This was `^\s*\|.+\|\s*$` until
# 20 August 2026, which one row of any table satisfied, so a reply full of
# other tables cleared the debt while the receipt was never printed. Every
# receipt mode opens its header with "| Packed reports |", and quiet mode
# prints no table and owes nothing, so that header is the whole test.
# The header cell is not the first cell any more: the default table opens
# "| Model | Packed reports | ...". Anchoring this to the start of a line
# made the gate fire on a reply that DID carry the receipt, on 24 August
# 2026, right after the column was renamed.
TABLE_ROW = re.compile(r"\|\s*Packed reports\s*\|", re.M | re.I)

REASON = (
    "STOP. DensePack gave you a receipt for %s this turn and your reply does "
    "not contain it.\n\n"
    "The hook has already shown the user the numbers, so this is not about "
    "the numbers. It is about the one column the hook cannot fill in: what "
    "each agent was actually asked to do. You know that and nothing else "
    "does.\n\n"
    "Print the receipt table and NOTHING ELSE. The text you already sent has "
    "reached the user and is on their screen. Repeating any of it prints it "
    "twice. Keep the rows in the order the hook gave them, keep the numbers "
    "exactly as measured, and label each row with the task you gave that "
    "agent.\n\n"
    "The receipt is here if you need it again: %s"
)


# A silent agent is the one failure the lead cannot notice on its own: nothing
# marks it finished, so it looks exactly like a working one. On 23 August 2026
# a builder went quiet at 18:44 and was called running three times over the
# next 158 minutes. The delegation table shows it now, but a table only helps
# if the lead prints it, so this gate refuses the reply until the lead says so
# in words. The check is not skippable, because a lead that can skip it is the
# lead that reported the dead builder as running.
STALE_REASON = (
    "STOP. The agent assigned to \"%s\" has sent no report for %d minutes. "
    "Do not tell the user it is still running and do not guess how long it "
    "has left. Read when it last wrote a file, run whatever suite covers "
    "its work, and say plainly in your reply that it went silent, what it "
    "left behind, and whether that work stands up. Then finish."
)

# The message for the far side of DEAD_AFTER, where silence has already
# outlasted the longest run this plugin has ever seen finish. This is the
# one case that most needs the lead's attention, because a dead agent this
# plugin has seen die still landed its work first and left files behind, so
# the fix is to look, not to redo the task from nothing.
DEAD_REASON = (
    "STOP. The agent assigned to \"%s\" has no stop record and may have "
    "died: %d minutes quiet, well past the longest run this plugin has "
    "ever seen finish. Check whether it is still in the running agent "
    "list. Read what files it wrote in .claude/tmp and when. Run whatever "
    "suite covers its work before assuming anything is missing, because a "
    "dead agent often finished the work before it died and the result is "
    "usually sitting on disk. Delete any scratch file it left once you "
    "have read it. Then finish."
)

# Appended to STALE_REASON or DEAD_REASON when watchdog.py caught this same
# agent first and left a record with more than a duration. Named here once
# rather than folded into either message above, since which of the two
# fires does not change what the watchdog itself found.
WATCHDOG_DETAIL = (
    " watchdog.py flagged this %d minutes ago, inside the prompt cache's "
    "five minute life, from no growth in its transcript. Its last file "
    "was %s%s."
)

STYLE_REASON = (
    "STOP. Your reply breaks a writing rule this session has turned on with "
    "/stylepack, LITERAL SENTENCES ONLY.%s\n\n"
    "Rewrite each flagged sentence and send the corrected reply. Do not "
    "explain the correction and do not mention this message."
)

# Matches the two shapes DENSEPACK-FAILURES.md measured: "now uses" (the
# auth-token cell's "verify_token function in auth.py now... Uses
# hmac.compare_digest()") and "write the implementation" (the csv-sum
# cell's "Let me use bash to write the implementation:" heredoc that never
# ran). Not every mention of "fix" or "implementation": only the phrasing a
# lead uses to claim the change already landed.
EDIT_CLAIM = re.compile(
    r"implementation (?:is |)complete"
    r"|i(?:'ve| have) (?:now |)(?:fixed|implemented|resolved|patched)"
    r"|successfully (?:fixed|implemented|patched|resolved)"
    r"|(?:the )?(?:fix|bug|issue) (?:is|has been) (?:now |)"
    r"(?:fixed|resolved|complete)"
    r"|now uses|now correctly|now handles|now returns|now validates"
    r"|(?:here's|here is) the (?:implementation|fix|updated code|patch)"
    r"|writ(?:e|ing) the implementation"
    r"|the following (?:code|script|function) (?:implements|fixes)",
    re.I,
)

EDIT_CLAIM_REASON = (
    "STOP. This reply claims a fix, an edit, or an implementation, but no "
    "Write or Edit tool call has succeeded in this session. A subagent's "
    "report, or a bash heredoc, is not a landed change.\n\n"
    "Call Write or Edit on the file this reply describes, so the change is "
    "actually on disk, then send the reply again."
)


def spawned_any(session_id):
    """True when this session spawned a subagent."""
    try:
        path = transcript_path(session_id)
        if not path or not path.is_file():
            return False
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if '"name": "Task"' in line or '"name": "Agent"' in line:
                    return True
        return False
    except OSError:
        return False


def edit_claim_block(event):
    """The reason to send a reply back for claiming a fix it never made, or
    None.

    Measured from DENSEPACK-FAILURES.md, run 20260830-011603:
    auth-token__densepack__haiku__3 closed in 9.3 seconds claiming
    verify_token "now... Uses hmac.compare_digest()" while auth.py on disk
    still read the seed's NotImplementedError, because the lead treated a
    subagent's one-line placeholder report as a finished edit.
    csv-sum__densepack__haiku__3 closed with a bash heredoc it never ran,
    Bash being disallowed in that harness, and sales.py was untouched too.
    Neither session ever called Write or Edit. has_edited(session) is the
    one check that tells the difference between a claim that landed and one
    that did not.
    """
    reply = event.get("last_assistant_message") or ""
    if not EDIT_CLAIM.search(reply):
        return None
    session = str(event.get("session_id") or "")
    # A lead that spawned a subagent may report an edit the worker
    # landed, and has_edited only sees this session's transcript. The
    # forced ladder makes a delegated edit the normal case, so a
    # session that spawned anything is never blocked here.
    if has_edited(session) or spawned_any(session):
        return None
    return EDIT_CLAIM_REASON


def owed_path():
    return tmp_dir() / OWED_FILE


def style_block(event):
    """The reason to send a reply back for its wording, or None.

    Only runs when the user turned the writing rules on with /stylepack. The
    rules are one user's, not everyone's, so a plugin that enforced them by
    default would be imposing a style nobody asked for.

    Scoped to "chat": a reply has already streamed to the reader by the time
    this hook runs, so sending it back costs a second whole reply for
    one sentence. literal_check.SCOPES keeps only the faults worth that
    cost, a lost fact or an active misleading, here. Length, passive voice
    and a gerund used as a noun are style preferences and stay off this
    path; the write path below keeps all seven, unweakened.
    """
    if literal_check is None:
        return None
    if settings().get("stylecard", "off") != "on":
        return None
    hits = literal_check.find(event.get("last_assistant_message") or "",
                               scope="chat")
    if not hits:
        return None
    return STYLE_REASON % literal_check.note(hits)


def told_path(session):
    """The stalled agents this session has already been blocked over."""
    return tmp_dir() / ("densepack-stall-told-%s.json" % (session or "x")[:8])


def main():
    # The event is read before the switch is checked, because the off
    # switch is per session since 31 August 2026 and the id that names
    # the session is on the event.
    event = read_event()
    if disabled(event.get("session_id")):
        return 0

    # One block per turn, whatever the reason. Claude Code sets
    # stop_hook_active on the retry, and a gate that blocks again there would
    # mean no reply ever lands.
    retried = bool(event.get("stop_hook_active"))

    # Before anything else, because a silent agent matters more than a receipt.
    if not retried:
        session = str(event.get("session_id") or "")
        stale = stale_agents(session)
        # Once per agent, not once per reply. A stale row never clears itself,
        # so a gate that fired on every turn would block every reply for the
        # rest of the session, including the one that reports the stall. The
        # names already told about are kept in a file beside the logs.
        told = told_path(session)
        try:
            seen = set(json.loads(told.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            seen = set()
        fresh = [row for row in stale if row[0] not in seen]
        if fresh:
            who, quiet, dead, started = fresh[0]
            seen.add(who)
            try:
                told.write_text(json.dumps(sorted(seen)), encoding="utf-8")
            except OSError:
                pass
            # The job, never the raw agent id: a string like
            # afd9d9266a2192de6 means nothing to a reader, the task it was
            # given does.
            job = job_for_marker(session, started)
            template = DEAD_REASON if dead else STALE_REASON
            reason = template % (job, int(quiet // 60))
            # watchdog.py may have caught this same agent earlier, while its
            # cache was still warm, with more to say than a duration: which
            # file it last touched and how long ago. Read only for the one
            # agent about to be reported, never for the rest of the batch.
            wrow = watchdog.stall_row(session, who)
            if wrow:
                ago_min = int((time.time() - float(wrow.get("detected_at")
                                                     or time.time())) // 60)
                last_file = wrow.get("last_file") or "no file this session"
                file_ago = wrow.get("last_file_ago_seconds")
                file_ago_text = (" (%d minutes before that)" %
                                  (file_ago // 60)) if file_ago else ""
                reason += WATCHDOG_DETAIL % (ago_min, last_file, file_ago_text)
            emit({"decision": "block", "reason": reason})
            return 0

    # A session that never claims a fix is never touched here, whether or
    # not it happened to call Write or Edit: a read-only question owes
    # nothing. Only a reply that claims one, with no edit behind it, blocks.
    if not retried:
        reason = edit_claim_block(event)
        if reason:
            emit({"decision": "block", "reason": reason})
            return 0

    path = owed_path()
    if not path.is_file():
        if not retried:
            reason = style_block(event)
            if reason:
                emit({"decision": "block", "reason": reason})
        return 0

    # Only the session that was handed the receipt owes it. A second window on
    # the same project must not be blocked for the first window's debt.
    session = str(event.get("session_id") or "")
    try:
        owed = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        path.unlink(missing_ok=True)
        return 0
    if owed.get("session") and session and owed["session"] != session:
        return 0
    # Fail closed once any lead is on record, the same fix pointer.py needed.
    # The test used to read "leads and session and session not in leads", so an
    # event carrying NO session id slipped through and a subagent was blocked
    # for a receipt it was never given.
    leads = read_leads()
    if leads and (not session or session not in leads):
        return 0

    # The debt belongs to ONE turn. A turn that was interrupted, or that ended
    # without this hook running, leaves the file behind, and blocking the next
    # reply for it costs the user a whole turn on a reply that owes nothing.
    # Measured on 19 August 2026: a debt from an earlier turn blocked "what is
    # 2 plus 2".
    turn = str(event.get("prompt_id") or "")
    owed_turn = str(owed.get("prompt_id") or "")
    if turn and owed_turn and turn != owed_turn:
        path.unlink(missing_ok=True)
        return 0

    # The belt for that brace, in case a harness supplies no prompt_id. A debt
    # older than one hour is from a turn nobody is going to finish.
    written = owed.get("written")
    if isinstance(written, (int, float)) and time.time() - written > 3600:
        path.unlink(missing_ok=True)
        return 0

    reply = event.get("last_assistant_message") or ""
    if TABLE_ROW.search(reply):
        # The receipt is there. The wording may still not be, and one block
        # per turn means this is the only chance to say so.
        path.unlink(missing_ok=True)
        if not retried:
            reason = style_block(event)
            if reason:
                emit({"decision": "block", "reason": reason})
        return 0

    # On the retry the debt is cleared either way, so a reply always lands
    # even if the lead ignores the block a second time.
    if retried:
        path.unlink(missing_ok=True)
        return 0

    agents = owed.get("agents") or []
    named = ", ".join(str(a) for a in agents[:4]) or "this batch"
    emit({
        "decision": "block",
        "reason": REASON % (named, tmp_dir() / "densepack-receipt-last.md"),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
