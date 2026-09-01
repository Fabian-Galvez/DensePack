"""Stops a Fable subagent being sent to do bulk implementation.

HOW THIS FILE FITS, in plain words: this is a PreToolUse hook on the same two
tools brief_pack.py watches, Agent and Task. brief_pack.py makes a brief
cheaper to deliver. This checks whether the brief should go to Fable at all,
before delivery is even a question.

It reads a brief that is about to be sent to a Fable subagent and denies the
call when the brief asks that agent to own, edit, build or write files. It
allows a brief that asks Fable to read, review, verify, diagnose, criticise or
plan.

THE TEST IT APPLIES.

A call to Fable is measured to cost about 18 minutes whatever it is asked, so
it is worth spending only where a wrong answer would cost more than that.
Three jobs clear that bar: working out what is wrong, saying who should fix
it, and judging whether a fix worked. All three RETURN WORDS. Fable is the
wrong tier when what it is asked to return is edited files, because a cheaper
model can carry out a plan Fable already wrote and reach the same result for
less.

So the question this hook asks of a Fable brief is: does it tell the agent to
own, edit, build or write files? If it does, the brief is for a builder and
the tier is wrong. The call is denied and the reason says so. The brief can
then be sent again with a different model, or rewritten to ask Fable for a
plan instead of code.

WHAT IT DELIBERATELY ALLOWS.

A brief that asks Fable to read, review, verify, diagnose, criticise or plan.
Those are its job. A brief carrying the word write only inside "write a plan"
or "write up" is allowed, because that is words, not code.

WHY THIS IS A HOOK, NOT ONLY A WRITTEN RULE.

A rule stated only in a doc is not enough, because whoever is delegating has
to remember it at the exact moment they are busy delegating. This checks
instead, on every call to a Fable subagent.

TWO WAYS TO SWITCH IT OFF.

For every call, this session or every session: /agentpack-off turns off every
delegation rule this plugin enforces, this one included, through the same
agentpack setting every other script here reads from common.py. A setting of
support or force keeps the gate active; only off stands it down. That way a
block from this gate is never a block a user cannot clear, because the same
switch that turns off the other delegation rules turns off this one.
/densepack-off, the one switch for the whole plugin, stands this down too.

For one call only, when a brief to Fable genuinely should build something,
the LEAD puts the exact phrase

    tier override approved

in the brief. The hook then stands aside for that call.

WHO MAY CLEAR IT. The lead only. The phrase rides in the brief text and the
spawner writes its own brief, so a subagent that saw the phrase could write
it into its next brief and send Fable a build job unchecked. A subagent's
denial therefore omits the paragraph naming it, and the phrase in a
subagent's brief does not stand this gate aside. is_subagent() tells the two
apart.

NEVER CRASH A CALLER. Everything that decides whether to deny a call is
wrapped in one try in guarded_main(). Anything unexpected inside it is
treated as allow, because a gate that broke on unexpected input would stop a
stranger working entirely, and that is a worse failure than one call getting
through unjudged.
"""
import re
import sys

from common import disabled, emit, read_event, settings

# Phrases that mean the agent is being asked to produce edited files. Ported
# from the personal version of this gate, where every pattern here was added
# because a real brief got past the version before it: briefs that named a
# file to produce ("Build one JavaScript module", "One file named geometry.js
# in your folder") slipped through a list that only looked for "you own" and
# "implement". Naming a file the agent has to produce is the plainest sign
# there is that it is being asked to build.
BUILD = [
    r"\byou own\b",
    r"\band own\b",
    r"\byours alone\b",
    r"\bfile ownership\b",
    r"\byour build folder\b",
    r"\bthe only place you write\b",
    r"\bwhat to build\b",
    r"\bfiles to deliver\b",
    r"\bimplement\b",
    r"\bbuild\b[^.\n]{0,40}\b(?:module|file|app|engine|tool|editor|suite|script|shell|page)\b",
    r"\bbuild (?:the|a|an|it|out|me)\b",
    r"\bone file named\b",
    r"\bwrite (?:the|a|an) (?:code|module|file|function|script|test|suite|app)\b",
    r"\bedit (?:the|this|index\.html)\b",
    r"\badd (?:the|a|an) (?:function|button|control|section|handler|test)\b",
    r"\bmust pass\b.*\btests\b",
    r"\bdeliverable\b[\s\S]{0,400}?\bwhat you (?:changed|built|added)\b",
]
# Phrases that mean the agent is being asked for words, which is its job.
PLAN = [
    r"\bwrite the plan\b",
    r"\bthe plan is the deliverable\b",
    r"\bdo not (?:write|edit|change) (?:any )?(?:code|files?)\b",
    r"\bread[- ]only\b",
    r"\bchange no file\b",
    r"\bbe the critic\b",
    r"\breport what you find\b",
]
ESCAPE = "tier override approved"

AGENT_TOOLS = ("Agent", "Task")

# TRIMMED 31 August 2026. This refusal used to carry a
# three row tier table and two paragraphs teaching which jobs are worth a
# Fable call, 902 characters. One delegation prompt run twice measured what
# that class of text buys: 192,692 tokens with the plugin off against 896,368
# with it on, the gap made of extra lead turns. The price that decides the
# refusal stays, one sentence of it; the lesson goes.
MESSAGE = (
    "DensePack: this brief asks a Fable subagent to edit files, and Fable is "
    "not the tier for that. A Fable call is measured to cost about 18 minutes "
    "whatever it is asked, and a cheaper model carries out the same plan for "
    "the same result.\n\n"
    "Send this same brief with a different model, or keep Fable and ask it "
    "for a plan that changes no file.\n\n"
    "What tripped this: %s\n\n"
    "%s"
    "This check follows the agentpack setting. /agentpack-off turns it off."
)

# Filled into MESSAGE for the LEAD only, and left empty for a subagent. The
# phrase stands this gate aside and it rides in the brief text, which the
# spawner writes. A subagent handed the words in a denial can put them in
# its own next brief and send Fable a build job unchecked, so a subagent's
# denial must not carry them.
OVERRIDE_PARAGRAPH = (
    "To send this exact brief to Fable anyway, put the phrase "
    "\"%s\" in the brief and this check stands aside for "
    "that one call.\n\n"
)


def is_subagent(event):
    """True when a subagent made this call, not the lead.

    MEASURED 31 August 2026: a subagent's PreToolUse carries the LEAD's
    session_id and the lead's transcript_path, so neither field separates
    the two. agent_id and agent_type name the real actor. Empty or absent
    means the lead, so an actor this cannot prove keeps the lead's
    treatment. Twin of the helper in delegate_gate.py, verify_gate.py and
    agent_floor.py; all four belong in common.py once that file is free.
    """
    return bool(event.get("agent_id")) or bool(event.get("agent_type"))


def verdict(prompt, honour_override=True):
    """Returns a list of the phrases that tripped the gate, or None to allow.

    honour_override is False for a subagent. The escape rides in the brief
    text and the spawner writes its own brief, so honouring it for a
    subagent would let an agent wave this gate aside for itself.
    """
    low = (prompt or "").lower()
    if honour_override and ESCAPE in low:
        return None
    if any(re.search(p, low) for p in PLAN):
        return None
    hits = [p for p in BUILD if re.search(p, low)]
    if not hits:
        return None
    return hits


def passthrough():
    """Say nothing. Claude Code then runs the tool call exactly as written."""
    return 0


def main():
    event = read_event()
    if disabled(event.get("session_id")):
        return passthrough()
    if settings().get("agentpack") == "off":
        return passthrough()

    if event.get("tool_name") not in AGENT_TOOLS:
        return passthrough()

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return passthrough()

    model = str(tool_input.get("model") or "").lower()
    if "fable" not in model:
        return passthrough()

    spawner_is_agent = is_subagent(event)
    hits = verdict(tool_input.get("prompt"),
                   honour_override=not spawner_is_agent)
    if hits is None:
        return passthrough()

    escape = "" if spawner_is_agent else OVERRIDE_PARAGRAPH % ESCAPE
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": MESSAGE % (", ".join(hits[:3]),
                                                   escape),
        }
    })
    return 0


def guarded_main():
    """Never let an exception out of this hook. See the file header: an
    unjudged call through is a correct outcome here, a crash is not."""
    try:
        return main()
    except Exception:  # noqa: BLE001
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
