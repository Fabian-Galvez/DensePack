"""Stops the lead grinding through hands-on calls it should have delegated.

HOW THIS FILE FITS, in plain words: verify_gate.py stops the lead reading the
two shapes that are always a subagent's job, an image and a repo's source.
Nothing watched the PATTERN: the lead doing call after call of ordinary
reading and inspecting, none of it individually forbidden, all of it landing
in the lead's own context where every later turn re-reads it. This is a
PreToolUse hook on the hands-on tools, the same shape as verify_gate.py. It
counts consecutive hands-on calls by the lead, resets the count whenever the
lead spawns a subagent, and denies the call that takes a streak past the
measured trigger, with a pointer to delegate instead.

WHY THE TRIGGER IS A COUNT AND NOT A SIZE. The lead-waste audit of session
651c3ea9 on 29 August 2026 (calls.tsv, lead_count.py, categorize.py) classed
every one of the lead's 78 tool calls as required-in-lead or delegable: 37.6
per cent of the lead's compounding-weighted context was delegable, EVERY
delegable read was under 11K characters, and the required ones ran to 49,854
characters. A size floor therefore cannot separate them. What separates them
is repetition: the delegable waste arrived as long unbroken runs of hands-on
calls, and the required work arrived in short bursts between spawns.

WHAT COUNTS AS HANDS-ON. A Read, a Grep, a Glob, or a Bash or PowerShell
command made only of inspection programs (the INSPECT list below). Anything
else neither counts nor resets: an Edit or a Write is the lead's own work,
and a command the classifier cannot place is simply not counted, which is
this gate failing open on its own matching logic. A Read of a densepack-*
file never counts either: reading a packed report IS delegating.

WHO THIS FIRES FOR. The lead session only. Two answers decide it. First,
is_subagent(): a subagent doing exactly this reading is the point of the
plugin and must never be slowed by it. Second, the same is_lead() answer
verify_gate.py uses: a session id not recorded by bootstrap.py's
SessionStart is not confirmed as a lead's, and the call goes through
uncounted.

The session id alone was not enough. MEASURED 31 August 2026: a subagent's
PreToolUse carries its LEAD's session_id and its lead's transcript_path,
so is_lead() answered True for a subagent, four live agents shared one
streak, and this gate denied their Read and Grep calls with a message
telling them to spawn a subagent while their briefs forbade it. The event's
agent_id and agent_type name the real actor. is_subagent() reads them.

WHAT A BLOCK DOES. Denies the one call that crossed the trigger, says why,
and RESETS the count, so asking again lets the same call through: a future
required burst longer than any measured one is delayed by one denial, never
walled off. The user can also say "delegation override approved", checked
against the last typed message the same way verify_gate.py checks its own
escape, and /agentpack-off or /densepack-off stand the gate down entirely.

NEVER CRASH A CALLER. Everything is wrapped in one try; anything unexpected
is treated as allow, the same failure mode every other gate here chooses.
"""

import json
import sys

import gate_cost
from common import (disabled, emit, has_edited, read_event, read_leads,
                    settings, tmp_dir, transcript_path, user_said)

# The rule name this gate books its firings under, for the cap in
# gate_cost.py. One name to one rule, so two gates never share a count.
RULE = "delegate"

# Derived from the audit's own distribution, never invented. Counting
# exactly as this gate counts, over calls.tsv's 78 lead calls (29 hands-on
# under this same classifier), resetting only at Agent spawns: the runs made
# only of calls the audit classed required-in-lead were 1, 1, 1, 1, 2, 3 and
# 5 calls long. The longest required burst is 5, so the gate fires at 6, the
# first count no required burst ever reached. The delegable streaks in the
# same session ran the counter to 17 and 10, so at 6 the gate would have
# fired inside both while staying silent through every required burst.
# Re-derive with bench/derive_streak.py against a newer audit's calls.tsv
# before changing this number.
TRIGGER = 6

# The programs whose output is inspection, not action. A Bash or PowerShell
# command counts as hands-on only when EVERY piece of it, split on ; | && ||
# and newlines, starts one of these (an env-var prefix such as VAR=x is
# skipped). One unknown program anywhere and the command is not counted:
# unknown means this gate cannot say the call was a subagent's kind of work,
# and not counting is how it fails open.
INSPECT = {"ls", "cat", "head", "tail", "grep", "rg", "find", "wc", "ps",
           "pwd", "du", "stat", "file", "diff", "sort", "uniq", "tree",
           "which", "type", "echo", "wmic", "dir", "get-childitem",
           "get-content", "select-string", "get-item"}

HANDS_ON_TOOLS = ("Read", "Grep", "Glob")
SHELL_TOOLS = ("Bash", "PowerShell")
AGENT_TOOLS = ("Agent", "Task")

# The per-session counter. One JSON object mapping session id to its current
# streak, trimmed to the sessions still on the lead list so it cannot grow
# without bound.
STREAK_FILE = "densepack-handson.json"

ESCAPE = "delegation override approved"

# TRIMMED 31 August 2026. The middle of this message
# used to name the delegation ladder and send the lead to BRIEFING.md for it,
# 244 characters of instruction inside a refusal. One delegation prompt run
# twice measured what that class of text buys: 192,692 tokens with the plugin
# off against 896,368 with it on, the gap made of extra lead turns. What is
# left is the count that fired, the escape, and the two switches. The gate
# still acts on its own arithmetic; it no longer teaches.
MESSAGE = (
    "DensePack stopped this call. It is hands-on call number %d in a row, "
    "Read, Grep, Glob or an inspection command, with no subagent spawned "
    "between them. In the audited session no run of required lead calls "
    "went past 5. The count is reset, so asking again lets this exact call "
    "through. The user can say \"%s\" to work hands-on, and /agentpack-off "
    "turns this off."
)


def analysis_shaped(command):
    """True when every piece of this shell command starts an INSPECT program.

    Split on the joiners a compound command uses, then judged piece by
    piece. Any piece the classifier cannot place makes the whole command
    not-hands-on, which is the open failure this gate promises.
    """
    if not isinstance(command, str) or not command.strip():
        return False
    text = command
    for joiner in ("&&", "||", "|", "\n"):
        text = text.replace(joiner, ";")
    pieces = [p.strip() for p in text.split(";") if p.strip()]
    if not pieces:
        return False
    for piece in pieces:
        head = ""
        for word in piece.split():
            if "=" in word and not word.startswith(("-", "/")):
                continue
            head = word.lower().lstrip("$(")
            break
        if head not in INSPECT:
            return False
    return True


def is_lead(session_id, leads):
    """The same answer verify_gate.py gives: unprovable means not the lead."""
    return bool(session_id) and bool(leads) and str(session_id) in leads


def is_subagent(event):
    """True when a subagent made this call, not the lead.

    MEASURED 31 August 2026 by dumping the raw hook event: a subagent's
    PreToolUse carries the LEAD's session_id AND the lead's
    transcript_path, so is_lead() above answers True for a subagent. Four
    agents were live on one session id, all raising one streak, and this
    gate denied their Read and Grep calls with a message telling them to
    spawn a subagent while their briefs forbade spawning.

    The event does name the actor. agent_id ("a912b7bc2a885d1b4") and
    agent_type ("general-purpose") are both present on a subagent's call,
    the same two fields subagent_start.py reads at spawn. Either one
    empty or absent means the lead, so an actor this cannot prove stays
    gated, never silently exempt.

    This belongs beside is_lead() in common.py. It sits in the gate files
    while another change holds common.py open.
    """
    return bool(event.get("agent_id")) or bool(event.get("agent_type"))


def is_plugin_file(path):
    normal = str(path).replace("\\", "/").lower()
    name = normal.rsplit("/", 1)[-1]
    # A read inside the vault's instructions folder is one the write gate
    # itself ordered; counting it deadlocks that gate against this one.
    # Measured in this project 31 August 2026: two extra turns on the
    # lead before the mandated rules read got through.
    if "densepack-vault/instructions/" in normal:
        return True
    return name.startswith("densepack-")


def read_streaks():
    try:
        data = json.loads((tmp_dir() / STREAK_FILE).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_streaks(streaks, leads):
    kept = {sid: n for sid, n in streaks.items() if sid in leads}
    (tmp_dir() / STREAK_FILE).write_text(json.dumps(kept), encoding="utf-8")


def hands_on(tool, tool_input):
    """True when this call is the kind the streak counts."""
    if tool in HANDS_ON_TOOLS:
        if tool == "Read" and is_plugin_file(tool_input.get("file_path") or ""):
            return False
        return True
    if tool in SHELL_TOOLS:
        return analysis_shaped(tool_input.get("command"))
    return False


def single_prompt_session(session_id):
    """True when the session transcript holds one user prompt or fewer."""
    try:
        path = transcript_path(session_id)
        if not path or not path.is_file():
            return False
        seen = 0
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("type") == "user" and not row.get("isMeta"):
                    seen += 1
                    if seen > 1:
                        return False
        return True
    except OSError:
        return False


def main():
    # NEVER CRASH A CALLER. This runs before every hands-on call and every
    # spawn in the session.
    try:
        # The event is read FIRST so the off switch can be asked about the
        # session that fired it. The switch has been per session since 31
        # August 2026, and disabled() with no id in hand falls back to
        # lead_session(), which is read_leads()[-1]: in a project open in
        # two windows that is the OTHER window. SEEN LIVE: a leg running
        # /densepack-off still got delegation prompts, because this gate
        # asked the neighbouring session's flag. Nothing above this line
        # touches the session, so the master switch is still the first
        # thing that can stop the gate.
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        # Only after the master switch, never before it.
        if settings().get("agentpack") == "off":
            return 0

        tool = event.get("tool_name") or ""
        sid = str(event.get("session_id") or "")
        leads = read_leads()

        # Stand down silently for a subagent. This sits ahead of the spawn
        # branch below because a subagent shares the lead's session id, so
        # its own work must neither raise the lead's streak nor reset it.
        if is_subagent(event):
            return 0

        if tool in AGENT_TOOLS:
            # A spawn is the act this gate exists to produce. Reset the
            # streak whoever spawned, so a stale count can never outlive
            # the delegation that answers it.
            if sid:
                streaks = read_streaks()
                streaks[sid] = 0
                write_streaks(streaks, leads)
                gate_cost.clear_direct(sid, leads)
            return 0

        if not is_lead(sid, leads):
            return 0

        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        if not hands_on(tool, tool_input):
            return 0

        streaks = read_streaks()
        count = streaks.get(sid, 0)
        if not isinstance(count, int) or count < 0:
            count = 0
        count += 1

        # MECHANISM 1, the priced stand-down. Every counted call is also
        # priced, packed or plain, against what a spawn costs. The reasoning
        # and the source line of every constant are in gate_cost.py.
        direct = gate_cost.add_direct(
            sid, gate_cost.command_price(gate_cost.would_pack(tool, tool_input)),
            leads)

        if count < TRIGGER:
            streaks[sid] = count
            write_streaks(streaks, leads)
            return 0

        # The streak is long enough, but length is not price. When the work
        # this streak holds costs the lead less than the 824,968 tokens one
        # spawn costs whatever it does, delegating loses, so the gate stands
        # down for this call without saying anything. The count keeps rising,
        # so the gate still fires the moment the work grows past the spawn.
        if gate_cost.cheaper_direct(direct):
            streaks[sid] = count
            write_streaks(streaks, leads)
            return 0

        # MECHANISM 2, the intervention cap. Two firings in one session on
        # this rule are all the lead is told. A third costs another whole
        # lead turn re-reading the conversation and changes nothing.
        if gate_cost.capped(sid, RULE):
            streaks[sid] = count
            write_streaks(streaks, leads)
            return 0

        # The transcript walk costs a file read, so it happens only at the
        # trigger, never on the calls below it.
        if user_said(sid, ESCAPE):
            streaks[sid] = 0
            write_streaks(streaks, leads)
            gate_cost.clear_direct(sid, leads)
            return 0

        # The gate exists to stop delegable reading compounding across a
        # long orchestration, not to keep a lead away from the one file it
        # must still change. Before any Write or Edit has landed this
        # session, a long read streak is the lead finding that file, so the
        # gate stands down instead of pushing it into a delegation ladder.
        # Measured in DENSEPACK-FAILURES.md: 19 of 76 densepack cells hit
        # the 300 second cap and none of them ever reached the ticket's
        # code. Once has_edited(sid) is True the gate is back to full
        # strength for the rest of the session.
        if not has_edited(sid):
            streaks[sid] = 0
            write_streaks(streaks, leads)
            gate_cost.clear_direct(sid, leads)
            return 0

        streaks[sid] = 0
        write_streaks(streaks, leads)
        gate_cost.clear_direct(sid, leads)
        gate_cost.record_fire(sid, RULE)
        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": MESSAGE % (count, ESCAPE),
            }
        })
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
