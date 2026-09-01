"""Runs every time a helper agent is born. The briefing.

HOW THIS FILE FITS, in plain words: three small jobs. Write down the time
this helper started, so densepack-manifest.jsonl, the record
subagent_stop.py builds of every agent's duration and cost, can state how
long the helper took. Record the model it will actually run on, for
drop_read_gate.py to read back on this SAME agent's own later Read calls,
FIXED 29 August 2026, see RECORDING THE REAL MODEL below. Then hand the
helper a pointer to its role and shared instruction images instead of the
delivery rule spelled out inline. PLAN-FABLE.md step 4, 29 August 2026: the
inline block (1,200 characters with SCOPE_RULE, 1,037 without) restated
facts that now live in worker.txt and shared.txt, drawn once at
SessionStart and read here by pointer instead of retyped per spawn.

ORIGINAL NOTE: SubagentStart hook. Record the start time, point at the role
and shared images.

WHICH MODEL READS THE POINTER, AND WHY THIS FILE ESTIMATES IT INSTEAD OF
READING IT DIRECTLY. The SubagentStart event carries agent_id, agent_type and
the session that spawned it, never the model the Agent tool call named:
captured live 29 August 2026 from a real event, its keys are session_id,
transcript_path, cwd, prompt_id, agent_id, agent_type, hook_event_name. Two
things narrow the estimate: agent_type_model() reads a pinned model from the
agent type's own frontmatter when it has one, and an unpinned type inherits
the lead's model, the same rule brief_pack.py applies with the tool call's
own model field, a field this event does not carry. Fable 5 has no
workerrules image, because Fable 5 is never a worker, so an estimate that
lands on fable is moved to opus, the size both Fable 5 and Opus 5 read
without a dropped word.

Haiku 4.5 has no measured pixel size and no drawn image: reader_key_for_model
returns None for it and every other unmeasured name, and the pointer below
names the plain text files under instructions/haiku/ instead.

RECORDING THE REAL MODEL, a separate job from the estimate above. worker_folder()
still estimates, because it has to pick between only two folders, opus or
sonnet, and a wrong guess there costs one drawn image, not a stopped gate.
drop_read_gate.py's regression was worse: it used to re-derive a Read-time
model by reading the agent's own transcript live, which raced the write and
returned nothing on a loss, sending the Read down a path that stopped
redirecting altogether. Fixed by reading Claude Code's OWN record instead of
guessing: agent-<agent_id>.meta.json, the file common.stopped_by_user()
already reads a different field from, carries the real model this event's
own fields do not, "sonnet" on a live capture 29 August 2026. Written once
here, in common.AGENT_MODEL_FILE, keyed on transcript_key(event), this
event's own transcript_path stem: see that constant's own comment for why
session_id cannot serve as the key on THIS event.
"""

import json
import sys
import time

from common import (agent_meta_model, agent_type_model, append_lifecycle,
                    disabled, emit, read_event, reader_key_for_model,
                    record_agent_model, resolved_reader, tmp_dir,
                    transcript_key, vault_dir, DEFAULT_CARD,
                    agent_meta_fields, claim_card)

# Added 27 August 2026. A subagent was told to stay out of several folders,
# and its report ended by naming every one of them, "no THIRD-PARTY-NOTICES.md
# was touched" among them, a sentence about that one agent's own scope. The
# lead relayed the sentence as though it described the whole session, and the
# user read it as the notices themselves still being wrong, when two earlier
# agents had already fixed them. It cost a turn to undo, and a wasted turn
# destroys the saving this plugin exists to create.
#
# worker.txt now carries the same instruction ("Name the files you changed
# and the checks you ran. Do not name anything you left alone."), read once
# from the role image this hook points at, so the sentence is not retyped
# here any more, PLAN-FABLE.md step 4, 29 August 2026.

# The role image a subagent reads is the card the lead named in the brief,
# and the worker card when the brief named none. This hook never fires for
# the lead, SessionStart covers that, so only the card folder and the model
# folder vary. %s takes every page in the card folder, comma separated.
POINTER = (
    "OUTPUT FORMAT REQUIREMENT from the user's DensePack plugin: read %s "
    "before your first action. It holds your role, the rules your final "
    "chat message must follow, and the code discipline every coding turn "
    "carries."
)

# Sent only when the two files POINTER would name are not on disk, a
# SessionStart that has not run yet in this project or a draw that failed.
# The lead sees the same guard in bootstrap.py's FALLBACK_NOTE.
FALLBACK = (
    "OUTPUT FORMAT REQUIREMENT from the user's DensePack plugin. Your "
    "final chat message IS your report; never write your report to a "
    "file. Start with a summary of five lines or fewer, then the full "
    "report. Every line after the summary is a finding."
)

# The image folder a worker guess must never land on: Fable 5 is never a
# worker, so instructions/fable/ holds no workerrules-1.png. 10 px is the
# size both Fable 5 and Opus 5 read with every answer exact, so a guess that
# would have picked fable is moved here instead.
WORKER_FALLBACK = "opus"


def worker_folder(event):
    """The model key (opus or sonnet) whose folder this subagent's pointer
    should name, or None when the model is unmeasured and gets text.

    reader_key_for_model() resolves a pinned agent type first, then the
    lead's own reader when the type pins nothing, the same absent-model rule
    brief_pack.py applies with size_for_model(). fable is remapped to
    WORKER_FALLBACK because no workerrules image exists there.
    """
    pinned = agent_type_model(event.get("agent_type"))
    key = reader_key_for_model(pinned, resolved_reader())
    if key is None:
        return None
    return WORKER_FALLBACK if key == "fable" else key


def card_folder(event):
    """The card folder name this subagent's pointer should serve.

    brief_pack.py wrote the name at PreToolUse, where the raw brief was still
    readable. The claim is keyed on prompt_id and agent_type, the lead turn
    and the helper type, because both are on this event and neither can
    arrive late. agent-<id>.meta.json is read only for the description, which
    separates two spawns of one agent type inside one turn: it is written
    while this hook runs, so it is often not there yet and is never required.
    DEFAULT_CARD is returned when the brief named no card, when it named a
    card outside CARDS, and when no record is found at all.
    """
    _type, description = agent_meta_fields(event.get("agent_id"))
    card = claim_card(event.get("session_id"), event.get("prompt_id"),
                      event.get("agent_type"), description)
    return card or DEFAULT_CARD




LANE_WORDS = 4


def lane_tag(event):
    """A short tag naming what this spawn is for, or "".

    The leading words of the spawn's own description, which is the field
    card_folder() above already relies on to separate two spawns of one
    agent type inside one turn. That description is written to
    agent-<id>.meta.json while this hook is running and is often not there
    yet, the race this file documents above, so agent_type answers when it
    is missing. An empty tag never reaches a roster line.
    """
    _type, description = agent_meta_fields(event.get("agent_id"))
    text = str(description or "").strip()
    if not text:
        text = str(event.get("agent_type") or "").strip()
    return " ".join(text.split()[:LANE_WORDS])


def sibling_line(session, own_agent_id):
    """One line naming the spawns already live beside this one, or "".

    Read off the lane tag of every start marker still on disk for the SAME
    spawning session, skipping this agent's own marker, which main() has
    already written by the time this runs. Same session because a sibling
    is another spawn of one parent; an agent further down the chain is not
    one, the same distinction "spawned_by" was added for.

    A marker on disk means an agent that has not reported yet, because
    subagent_stop.py clears its own and bootstrap.py sweeps what is left at
    SessionStart. No siblings means no line at all rather than an empty
    header, so a solo spawn pays nothing for this.
    """
    try:
        markers = sorted(tmp_dir().glob("densepack-start-*"))
    except OSError:
        return ""
    prefix = len("densepack-start-")
    tags = []
    for path in markers:
        if path.name[prefix:] == str(own_agent_id):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        if str(record.get("spawned_by") or "") != str(session or ""):
            continue
        tag = str(record.get("lane") or "").strip()
        if tag:
            tags.append(tag)
    if not tags:
        return ""
    return "Working beside you: %s" % ", ".join(tags)


def main():
    event = read_event()
    if disabled(event.get("session_id")):
        return 0
    agent_id = event.get("agent_id") or "unknown"

    # The start file records the time AND the session that spawned this agent.
    # The spawning session matters because a subagent can spawn subagents of
    # its own. Such a report is delivered to its own parent, not to the lead,
    # yet the queue is one shared file, so the lead used to drain that row and
    # charge itself a saving for text it never read. Measured 21 August 2026:
    # the lead was handed a receipt row it could not label, because it never
    # assigned that task. The field recorded here lets pointer.py tell
    # its own agents apart from agents further down the chain.
    #
    # The value is JSON now and used to be a bare timestamp. subagent_stop.py
    # reads both, so an agent that started before this change still gets its
    # duration.
    # The roster reads "lane" back off these same markers, so one spawn's
    # tag is written here and every later sibling sees it. Both readers of
    # this file, common.unfinished_agents() and pointer.py, take only "at"
    # and "spawned_by" off the dict and ignore anything else, so the extra
    # key costs them nothing.
    lane = lane_tag(event)
    start_file = tmp_dir() / ("densepack-start-%s" % agent_id)
    start_file.write_text(json.dumps({
        "at": time.time(),
        "spawned_by": str(event.get("session_id") or ""),
        "lane": lane,
    }), encoding="utf-8")

    # The lifecycle record's first row for this agent. See common.py's
    # LIFECYCLE_FILE note for what the other two rows are and why a lead
    # stopping this same agent later through TaskStop needed a third one.
    append_lifecycle(agent_id, "spawned", lane)

    # REGRESSION FIX, 29 August 2026: drop_read_gate.py used to re-derive
    # this same agent's model by reading its own transcript live, at Read
    # time, which raced the file being written and returned nothing on a
    # loss, so the Read stopped redirecting at all. Recorded here instead,
    # once, from Claude Code's own agent-<agent_id>.meta.json, which this
    # header's WHICH MODEL READS THE POINTER section already says this
    # event itself never carries. Keyed on transcript_key(event), this
    # event's own transcript_path stem, never on event["session_id"]: see
    # common.AGENT_MODEL_FILE for why session_id on THIS event names the
    # spawning session instead of this one agent, the same fact
    # "spawned_by" above already relies on.
    real_model = agent_meta_model(agent_id)
    if real_model:
        reader = reader_key_for_model(real_model)
        if reader:
            record_agent_model(transcript_key(event), reader)

    # Launches the background stall watchdog, once per session, reusing this
    # hook's own firing rather than a second trigger. See watchdog.py's own
    # header for what it checks and why it exists at all: this hook already
    # runs on every spawn and already writes the per-session state above, so
    # it is where a watchdog for that state has to start from.
    try:
        import watchdog
        watchdog.maybe_launch(event.get("session_id"))
    except Exception:  # noqa: BLE001
        pass

    key = worker_folder(event)
    if key is None:
        base = vault_dir() / "instructions" / "haiku"
        role_path = base / "role-facts.txt"
        shared_path = base / "shared.txt"
        code_path = base / "code.txt"
        pages = [role_path]
        ready = (role_path.is_file() and shared_path.is_file()
                 and code_path.is_file())
    else:
        # One folder per card, so a card can hold several pages and no card
        # can be handed another card's image by a name collision. Every png
        # in the folder is served, in filename order, which is the order the
        # draw numbers them. An unknown card names no folder, so the worker
        # folder is served in its place.
        base = vault_dir() / "instructions" / key
        folder = base / card_folder(event)
        if not folder.is_dir():
            folder = base / DEFAULT_CARD
        pages = sorted(folder.glob("*.png"))
        ready = bool(pages)

    if ready:
        instructions = POINTER % (", ".join(str(page) for page in pages),)
    else:
        instructions = FALLBACK

    # THE SIBLING ROSTER. One line, riding an injection that already
    # happens, so an agent knows who else is working before its first
    # action instead of finding out from a collision. Nothing is added
    # when it is the only spawn in flight.
    roster = sibling_line(event.get("session_id"), agent_id)
    if roster:
        instructions = instructions + "\n" + roster

    emit({
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": instructions,
        }
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
