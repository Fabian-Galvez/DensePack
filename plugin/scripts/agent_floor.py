"""Stops a subagent being spawned to carry less work than it costs.

HOW THIS FILE FITS, in plain words: moving work into a subagent saves tokens,
because the subagent's tool calls, their arguments and their printed output
never enter the lead's conversation. Only the brief going out and the report
coming back do. Spawning is not free: the lead spends one turn to spawn and
one to read the report, and a turn re-reads the whole conversation. An agent
that carries one or two commands costs more than it saves.

THE ARITHMETIC, measured over 8 real transcripts on 25 August 2026. 7,453
assistant turns, 3,067,274,386 tokens, 2,357 Bash calls, and one turn re-reads
411,549 tokens on average.

  two lead turns                                  823,098 tokens
  a packed brief, a packed report and the call      1,870 tokens
  what one moved command removes                  340,000 tokens, mean
  break-even                                         2.42 commands
  the first whole number that pays                      3 commands

Simulated at half the shell work moved: 2 commands an agent LOSES 5.77 per
cent, 4 saves 10.77, 6 saves 15.93, 10 saves 19.98, 20 saves 22.93. The floor
is three and the direction is always the larger batch.

WHAT IT CAN AND CANNOT TEST. A hook sees the brief before the subagent starts.
It cannot know how many commands that agent will run. Brief length is the one
field that correlates with the count: measured over 285 real agent runs in the
archived transcripts, a brief under 1,000 characters was followed by fewer
than three tool calls 30 times out of 44. So the gate fires 44 times and is
wrong 14 of those, a false positive rate of 31.8 per cent.

A gate wrong one time in three must be clearable, so it is. A brief the LEAD
writes holding the words "floor override approved" passes untouched, and the
denial the lead reads says so.

WHO MAY CLEAR IT. The lead only. The override rides in the brief text and the
spawner writes its own brief, so a subagent that saw the phrase could write it
into its next brief and spawn under the floor unchecked. A subagent's denial
therefore omits the phrase, and the phrase in a subagent's brief does not
clear the gate. is_subagent() below tells the two apart.

WHAT IT NEVER TOUCHES. /densepack-off stands it down with the rest of the
plugin, the same switch every other rule here answers to.
"""

import sys

import gate_cost
from common import disabled, emit, read_event, tmp_dir

# The rule name this gate books its firings under, for the cap in
# gate_cost.py. One name to one rule, so two gates never share a count.
RULE = "agent-floor"

# The smallest brief that has, in this project's own history, been followed by
# three or more tool calls more often than not. Measured, not chosen.
# This floor stays flat while the packing floors in common.py fall with lead
# turns, and the difference is what each one prices. A packing floor prices a
# fee paid once against a saving that repeats each lead turn, so it falls.
# This floor prices the chance a brief carries enough instruction for its
# agent to do real work, and that chance is the same at turn fifty as at turn
# one. Re-measure it by re-counting briefs against the commands that followed
# them, never by putting it on the turn curve.
# Counter-evidence, measured 30 August 2026 in the INDEX benchmark's pair 1
# ON run: two briefs of 761 and 787 characters were refused here, the lead
# added the override words rather than more instruction, and the two agents
# those briefs then spawned ran 18 and 19 commands each to a perfect
# correctness score. The two refusal turns cost 22,317 weighted tokens,
# summed from that transcript's own usage records, for no gain. Two runs do
# not outweigh the 44 this floor was counted from, but the next re-count
# folds them in.
FLOOR_CHARS = 1000

# The words that clear the gate. Deliberate rather than a flag, so it cannot
# be typed by accident, the same approach source_gate.py uses.
OVERRIDE = "floor override approved"

MESSAGE = (
    "DensePack stopped this spawn. The brief is %d characters, under the "
    "%d character floor, and a brief that short has carried fewer than three "
    "commands 30 times out of 44 in this project's own history. An agent "
    "costs the lead two turns whatever it does, 823,098 tokens on the "
    "measured mean, and break-even sits at 2.42 commands. Two commands an "
    "agent loses 5.77 per cent of a conversation; six saves 15.93; twenty "
    "saves 22.93."
)

# Appended for the LEAD only, and never for a subagent. The phrase clears
# this gate and it rides in the brief text, which the spawner writes. A
# subagent handed the words in a denial can put them in its own next brief
# and spawn under the floor unchecked, so the denial it reads must not
# carry them. SEEN LIVE 31 August 2026: this gate denied a subagent's spawn
# and gave it the override in the same sentence.
OVERRIDE_LINE = (
    " Or add the words \"%s\" to the brief to send it as it stands."
)


def brief_of(tool_input):
    """The brief text, whichever field this tool carries it in."""
    for field in ("prompt", "description", "task", "input"):
        value = tool_input.get(field)
        if isinstance(value, str) and value:
            return value
    return ""


def is_subagent(event):
    """True when a subagent made this call, not the lead.

    MEASURED 31 August 2026: a subagent's PreToolUse carries the LEAD's
    session_id and the lead's transcript_path, so neither field separates
    the two. agent_id and agent_type name the real actor, the same fields
    subagent_start.py reads at spawn. Empty or absent means the lead, so
    an actor this cannot prove keeps the lead's treatment.

    Twin of delegate_gate.is_subagent() and verify_gate.is_subagent().
    All three belong in common.py once that file is free.
    """
    return bool(event.get("agent_id")) or bool(event.get("agent_type"))


def batch_pass_path(event):
    """The marker for ONE turn's batch of spawns, or None.

    Keyed on prompt_id, which common.record_card() documents as the field
    that "names the lead turn the Agent call was made in", and which
    claim_card() and stop_gate.py already key on for the same reason. That
    is the exact scope the override should cover: the plan the lead had
    already declared when it said the words, and not one turn further. A
    new turn carries a new prompt_id and meets a fresh floor.

    None when the harness supplies no prompt_id, the same belt stop_gate.py
    keeps for that case. None means the floor applies as normal, so a
    missing field can only ever make this gate stricter, never looser.
    """
    prompt_id = str(event.get("prompt_id") or "").strip()
    safe = "".join(c for c in prompt_id if c.isalnum() or c in "-_")
    if not safe:
        return None
    return tmp_dir() / ("densepack-floorpass-%s" % safe)


def should_stop(brief, honour_override=True):
    """True when this brief is under the floor and carries no override.

    honour_override is False for a subagent. The override rides in the
    brief text and the spawner writes its own brief, so honouring it for a
    subagent would let an agent wave this gate aside for itself. The
    phrase counts only when the lead wrote it.
    """
    if not brief:
        return False
    if honour_override and OVERRIDE in brief:
        return False
    return len(brief) < FLOOR_CHARS


# NOTHING IS SENT ON AN ALLOWED SPAWN. This hook used to append a pointer
# line, "the delegation rules are in your role image", to the first spawn of
# every session, and before that 652 characters of restated ladder text. Both
# are retired, 31 August 2026, on the measurement below.
#
# THE MEASUREMENT. One delegation prompt, run twice. With the plugin off the
# lead orchestrated five readers in few turns for 192,692 tokens. With the
# plugin on the same prompt cost 896,368, because the lead took 15 requests
# instead, and every extra turn re-bills the whole growing context. The
# plugin's delegation instruction, this pointer among it, bought none of the
# extra turns back. A lead that is already delegating needs no telling.
#
# What is left here is the floor itself: a priced refusal that either fires
# on its own arithmetic or says nothing at all. Silence is now the whole of
# the allowed path.


def main():
    # NEVER CRASH A CALLER. This runs before every Agent and Task call.
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        if (event.get("tool_name") or "") not in ("Agent", "Task"):
            return 0
        tool_input = event.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            return 0
        brief = brief_of(tool_input)
        spawner_is_agent = is_subagent(event)
        sid = str(event.get("session_id") or "")
        batch = batch_pass_path(event) if not spawner_is_agent else None

        # MECHANISM 3, the batch pass. The override used to clear exactly
        # one spawn, so a lead that said the words for a plan of several
        # short briefs was refused again on the very next one and paid a
        # turn each time. MEASURED 31 August 2026: 100,145 tokens on two
        # such retries, both spawns from the same declared plan.
        #
        # The scope is the ONE TURN the words were said in, never the
        # session. A session-wide yield would be a second /agentpack-off
        # arrived at by accident, and the lead already has that switch
        # when it wants it. A new turn carries a new prompt_id and meets a
        # fresh floor.
        #
        # A subagent reaches none of this: batch is None for one, so it
        # can neither set the marker nor spend one the lead set, which
        # leaves the lead-only override containment exactly as it was.
        if batch is not None and OVERRIDE in brief:
            try:
                batch.write_text("1", encoding="utf-8")
            except OSError:
                pass

        if should_stop(brief, honour_override=not spawner_is_agent):
            if batch is not None and batch.exists():
                return 0
            # MECHANISM 2, the intervention cap. Two refusals in one session
            # are all this floor gets to say. The third costs another whole
            # lead turn, 411,549 tokens on the mean at line 12 above, and the
            # INDEX pair 1 counter-evidence at line 59 shows what a refused
            # spawner does with a third telling: it pastes the override and
            # spawns anyway. Reasoning and state in gate_cost.py.
            if gate_cost.capped(sid, RULE):
                return 0
            gate_cost.record_fire(sid, RULE)
            reason = MESSAGE % (len(brief), FLOOR_CHARS)
            if not spawner_is_agent:
                reason += OVERRIDE_LINE % OVERRIDE
            emit({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason}})
            return 0
        # The spawn is going ahead, so this hook says nothing. See the note
        # above POINTER's retirement.
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
