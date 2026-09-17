"""Shared plumbing for the DensePack hooks.

Every hook script imports this file. It finds the project's scratch folder,
the queue file and the totals file, reads the event Claude Code pipes in,
writes the answer, and finds Pillow wherever the plugin data directory put
it. No script runs this file directly.
"""

import json
import os
import re
import sys
from pathlib import Path

# /plugin install keeps Pillow, freetype-py and NumPy in the plugin's data
# folder. Every hook imports this module, so the folder goes on the path
# here, before any script imports the renderer. Without it a Read hook on a
# new Linux install found the system Pillow and no freetype-py, and drew
# taller fallback images that a reader misread.
_PYLIBS = os.path.join(os.environ.get("CLAUDE_PLUGIN_DATA") or "", "pylibs")
if os.environ.get("CLAUDE_PLUGIN_DATA") and os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)

# The report floor counts characters, not lines. A report of a few very long
# lines passes a line count and still costs thousands of tokens.
#
# Each floor is the smallest source length where the image plus its pointer
# costs fewer tokens than the text, priced at CHARS_PER_TOKEN. The pointer is
# the route's own line, so each route has its own fee:
#
#   report route, subagent_stop.py. report_pointer() runs 137 characters,
#     57 tokens at the 2.40 divisor. Stub mode charges stub_pointer()
#     instead; the live compare prices whichever mode ships, and the
#     pre-filter stays on the shorter fee.
#   bash route, bash_pack.py.
#     pointer_line() runs 159 characters, 66 tokens at the 2.40 divisor:
#     the image path and the exact-text path, nothing else.
#
# A floor here only skips the conversion. Every route prices the real image
# against the real text before it ships, so these constants may sit low
# safely and must never sit high.
#
# The floor is flat. The image and its pointer both stay in the conversation
# prefix, exactly as the text they replace would, so every turn pays image
# plus pointer on one side or text on the other. The one Read that opens the
# image is paid once and amortises over the session, so it stays out of the
# compare. Packing wins whenever
#
#     image_tokens + pointer_tokens < text_tokens
#
# and that condition does not depend on the turn count. The floor cannot
# reach zero, because the pointer is itself text in the prefix: content
# smaller than its pointer never pays back.
#
# The fee holds no cache read of a whole turn, because the saving is not
# one-off. It is not divided by the turns elapsed, because the pointer is
# re-read every turn exactly like the image and the text.
#
# One floor serves every reader, because every reader gets the same image.
STUB_CHARS = 194
# BASH_CHARS is a cheap pre-filter, not the break-even of the Bash route.
# Output this short cannot clear read_turn_fee() at any session size.
# Refusing it here saves rendering an image that loses.
# Clearing this number does NOT mean the route packs.
# read_turn_fee() at bash_pack.py decides, and it refuses much higher.
# Measured by driving the real hook and reading its own manifest rows:
#   context unknown, 0 turns          17,466 characters
#   30,000 token context, 5 turns      9,098 characters
#   60,000 token context, 10 turns    12,352 characters
#   120,000 token context, 25 turns   14,910 characters
#   200,000 token context, 40 turns   17,930 characters
BASH_CHARS = 5000


def stub_chars():
    """The smallest report worth sending to a file."""
    return STUB_CHARS


def bash_chars():
    """The smallest Bash output worth packing.

    It sits above the report floor because the bash pointer names the
    image, the folder and the exact-text file, 159 characters against
    report_pointer()'s 137.
    """
    return BASH_CHARS


# The brief floor. The fee is brief_pack.POINTER filled with an image path,
# about 245 characters and 92 tokens. It is higher than the report and bash
# pointers because a brief's pointer IS the replacement prompt the agent
# receives. When brief_pack lifts a code block it adds the code file's own
# text to the fee; the pre-filter cannot know that in advance and stays on
# the cheap side, where a wrong guess costs one discarded conversion.
#
# The floor is 1,000 characters. Readers handed a brief image under that
# length failed the task: the gate collapsed, the reader transcribed its own
# brief, or it hunted a legend file. A brief under 1,000 characters costs
# about 250 tokens as text.
BRIEF_FLOOR = 1000


def brief_chars(px=None):
    """The smallest brief worth packing. One floor for every size."""
    return BRIEF_FLOOR

# CODE_PX is the one glyph size every image is made at, for every reader.
# It is the glyph in image pixels, and the image is not scaled after
# hinting, so it is what a reader sees. backend_text() asks FreeType for the
# glyph at that size, so it is hinted at the size it is made at.
#
# font.scale_x condenses every glyph narrower than its size, so a larger
# size buys x-height without widening the row. space.row_px pins the row
# height so the band does not grow with the glyph.
#
# DENSEPACK_CODE_PX overrides it. The size is not a style key, so
# DENSEPACK_STYLE cannot reach it, and a style written for one glyph size
# makes a different image at another, because every width scale is set for
# the size it was written for. The override is not a per-reader setting.
# Every reader gets this one number.
CODE_PX = int(os.environ.get("DENSEPACK_CODE_PX") or 17)

FONT_SIZE = CODE_PX
READER_SIZES = {"fable": CODE_PX, "opus": CODE_PX, "sonnet": CODE_PX}


def font_size():
    """The pixel size every image is drawn at. One size, every reader."""
    return CODE_PX


def code_size(px=None, reader=None):
    """The pixel size the code renderer makes at. CODE_PX, for every reader.

    Both arguments are accepted so every caller still works, and both are
    ignored.
    """
    return CODE_PX


# The readers that get a picture, keyed by the word that appears in the Agent
# tool's `model` field. Every value is CODE_PX. A model whose name is not a
# key here does not read condensed images reliably, so it is sent plain
# text: an unreadable brief costs the whole task, and the saving is not
# worth that trade. size_for_model() and reader_key_for_model() read the
# dict that way.
#
# Haiku 4.5 stays off this dict. Two cold Haiku readers each scored 1 of 10
# on a condensed report, and neither ever answered UNREADABLE, so a caller
# cannot tell a bad read from a good one.
MEASURED_MODELS = {"fable": CODE_PX, "opus": CODE_PX, "sonnet": CODE_PX}

VAULT_DIRNAME = "densepack-vault"

# How much disk the vault may hold before the oldest conversation folders are
# deleted. 200 MB holds roughly ten thousand packed reports at about 19 KB
# each, far more than any run needs. The vault_mb setting changes it.
VAULT_CAP_MB = 200


def size_for_model(model, lead_size=None):
    """The pixel size a brief for this model must be drawn at, or None when
    the model was never measured and must get plain text.

    `model` is the Agent tool's model field. It is often absent, because an
    omitted model means the subagent inherits the parent's, so an absent model
    means the lead's own size. That is what lead_size supplies.
    """
    if model is None or model == "":
        return lead_size if lead_size else font_size()
    name = str(model).lower()
    for key, px in MEASURED_MODELS.items():
        if key in name:
            return px
    return None


def reader_key_for_model(model, lead_reader=None):
    """The reader key, fable, opus or sonnet, for a model name, or None
    when the model gets no image. Mirrors size_for_model, keyed to
    MEASURED_MODELS instead of a pixel size.

    An absent model means the caller inherits the lead's own reader,
    supplied by lead_reader, the same absent-model rule size_for_model
    applies.
    """
    if model is None or model == "":
        return lead_reader if lead_reader else resolved_reader()
    name = str(model).lower()
    for key in MEASURED_MODELS:
        if key in name:
            return key
    return None


def agent_type_model(subagent_type):
    """The model an agent definition pins, or None when it pins none.

    The Agent tool's model field wins when it is set. When it is not, a custom
    agent type can still pin a model in its own frontmatter, and that beats
    inheriting the lead's. Read from .claude/agents/<type>.md, which is where
    Claude Code keeps them. A missing file is not an error: most agent types
    are built in and pin nothing.
    """
    if not subagent_type:
        return None
    path = project_dir() / ".claude" / "agents" / ("%s.md" % subagent_type)
    if not path.is_file():
        return None
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return None
    lines = head.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped.lower().startswith("model:"):
            return stripped.split(":", 1)[1].strip().strip("'\"") or None
    return None
MARKER = "DENSEPACK_REPORT:"


LEAD_MODEL_FILE = "densepack-leadmodel"

# The reader used when the lead's model has not been read yet, which is only
# the SessionStart briefing. Every reader gets the same image, so this only
# names a reader that is known to get one.
UNKNOWN_READER = "opus"


def _model_from_transcript(path, skip_sidechain=False):
    """The model named on the first assistant line of transcript `path`, or
    None when the file is missing, unreadable, or names none.

    Shared by note_lead_model(), which passes skip_sidechain True because it
    wants the LEAD's own line even while a subagent's turn is interleaved
    in the same transcript, and by event_reader() below, which does not
    skip one: a subagent's own transcript file marks every one of its own
    rows isSidechain, so skipping them there would find nothing.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for number, line in enumerate(fh):
                if number > 200:
                    break
                line = line.strip()
                if not line or '"model"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if skip_sidechain and row.get("isSidechain"):
                    continue
                found = (row.get("message") or {}).get("model") or row.get("model")
                if found:
                    return str(found)
    except OSError:
        return None
    return None


def read_lead_models():
    """Every recorded lead model, keyed by the session id it belongs to.

    A name with no session attached cannot be matched to the session asking
    for it, so a file that holds one bare model name reads as empty here and
    the model is detected again. It is a MAP, not one slot, because a
    project is often open in two windows at once, the same reason
    LEADS_FILE below holds a list.
    """
    try:
        raw = (tmp_dir() / LEAD_MODEL_FILE).read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()
            if isinstance(value, str) and value}


def write_lead_models(models):
    """Write the map back, newest sessions kept, oldest dropped."""
    kept = dict(list(models.items())[-LEADS_KEPT:])
    try:
        (tmp_dir() / LEAD_MODEL_FILE).write_text(json.dumps(kept),
                                                 encoding="utf-8")
    except OSError:
        return


def note_lead_model(event):
    """Record the lead's model the first time a hook event names its
    transcript, under the id of the session that fired the event. Cheap: one
    write per session, a lookup after. Any failure leaves the session
    unrecorded, and resolved_reader falls back."""
    if not isinstance(event, dict):
        return
    path = event.get("transcript_path")
    session = str(event.get("session_id") or "").strip()
    if not path or not session:
        return
    models = read_lead_models()
    if session in models:
        return
    found = _model_from_transcript(path, skip_sidechain=True)
    if found:
        models[session] = str(found)
        write_lead_models(models)


def lead_session():
    """The session id whose lead model answers for the work running now.

    A hook event names the session that fired it, and a lead's own event
    names the lead. A subagent's event names the subagent, which records no
    model of its own, so the newest id on the leads list answers for it,
    the same id dpctl.py already reports on. Every id here belongs to a
    session that reached SessionStart, so no finished session's model can
    be picked up by the one running now.
    """
    leads = read_leads()
    if not leads:
        return _EVENT_SESSION or ""
    if _EVENT_SESSION and _EVENT_SESSION in leads:
        return _EVENT_SESSION
    # A script run inside the Bash tool has no hook event in hand, but Claude
    # Code exports the window's own id into that environment, the same id
    # dpctl.py's caller_session() reads. Without this check bash_pack.py,
    # run that way, answers with leads[-1], another window's model.
    env_session = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if env_session and env_session in leads:
        return env_session
    return leads[-1]


def lead_model_name(session=None):
    """The model name recorded for one session, or "" when none is.

    Never another session's name: a name recorded under a different id is
    that session's fact, not this one's. A session with no name recorded
    yet has its own transcript read instead, which is the same detection
    note_lead_model() does, so a caller with no hook event behind it, such
    as dpctl.py, still answers from the running session rather than from
    whatever was left on disk.
    """
    session = str(session or lead_session()).strip()
    if not session:
        return ""
    found = read_lead_models().get(session)
    if found:
        return found
    path = transcript_path(session)
    if path is None:
        return ""
    return _model_from_transcript(path, skip_sidechain=True) or ""


SESSION_FILE = "densepack-session.json"

# The settings a window keeps to itself. Everything else in
# densepack-settings.json stays one value for the whole project.
#
# The test is what a wrong answer costs the window next door.
#
#   reader     Scoped. It names the reader for one window. A wrong reader
#              is the most expensive wrong answer the plugin has.
#   receipts   Global. It prints a savings table in the reply and costs a
#              handful of tokens. A user who turns receipts on wants them
#              wherever they work in this project.
#   totals     Global. One more row in the same table receipts prints.
#   stylecard  Global. It is the writing standard for the project, applied
#              to every reply and every Write. One project has one standard,
#              not one per window.
#   keep       Global. It archives images and report text to disk. No model
#   keep_folder  ever sees it and no run spends anything on it.
#   vault_mb   Global. A disk cap for this project's vault. Housekeeping.
SCOPED_SETTINGS = ("reader",)


def read_session_settings():
    """Every scoped setting pinned by hand, keyed by the session that pinned it.

    A slash command writes one word into densepack-settings.json, and that
    file is one file for the whole project. A word set in one window was therefore read by
    every other window on the same project and by every conversation opened
    after it. It is a MAP for the same reason read_lead_models() is: a project
    is often open in more than one window.

    A word that is not allowed for its setting is dropped, so a hand edited
    file cannot pin a state the commands themselves refuse.
    """
    try:
        raw = (tmp_dir() / SESSION_FILE).read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for session, pinned in data.items():
        if not isinstance(pinned, dict):
            continue
        mine = {str(key): str(value) for key, value in pinned.items()
                if key in SCOPED_SETTINGS and isinstance(value, str)
                and value in SETTINGS_ALLOWED.get(key, ())}
        if mine:
            out[str(session)] = mine
    return out


def session_map_exists():
    """True when densepack-session.json exists on disk, whether or not it
    names the session asking.

    A project that has never pinned a scoped setting has no such file, and
    in that project the flat settings() reader still speaks for the whole
    project, so a spawn with an absent model inherits it. Once the file
    exists anywhere in a project, a flat settings() reader is residue from
    whichever window pinned it last, never a fact about a session absent
    from the map, and brief_pack.py must not answer from it for such a
    session.
    """
    return (tmp_dir() / SESSION_FILE).is_file()


def session_settings(session=None):
    """What one session pinned for itself, or {} when it pinned nothing.

    Only a session that names itself gets an answer. There is no fall back to
    the newest lead here, unlike lead_model_name() above, because the two
    questions cost different amounts when they are answered wrong. A model
    name read from the wrong session still picks a size that is very likely
    right, since the windows on one project usually run the same model. A pin
    is by definition the one case where the answer is NOT what the session
    would have chosen for itself, so handing it to a session that did not ask
    for it is the whole fault this map exists to stop. Unknown means the
    default, and for the reader the default is auto, which reads that
    session's own lead model.
    """
    session = str(session if session else _EVENT_SESSION or "").strip()
    if not session:
        return {}
    return read_session_settings().get(session, {})


def reader_override(session=None):
    """The reader profile one session pinned, or "" when it pinned none."""
    return session_settings(session).get("reader", "")


def event_reader(event):
    """The reader profile, fable, opus or sonnet, for the agent that fired
    THIS event, read from the transcript the event names. None when it
    cannot be read or names an unmeasured model: a caller must not guess.

    resolved_reader() answers "what does the LEAD read", cached once at
    SessionStart from the lead's own transcript, correct for the lead's own
    tool calls and wrong for a subagent's. A PreToolUse Agent event carries
    no field naming the model the spawned subagent will run on.

    A subagent's Read event does NOT carry that subagent's own
    transcript_path; it carries the lead's. So actor_reader() below asks
    this ONLY when the event's own transcript_path is the actor's own file,
    and takes Claude Code's agent-<id>.meta.json for every other subagent
    event.
    """
    if not isinstance(event, dict):
        return None
    path = event.get("transcript_path")
    if not path:
        return None
    found = _model_from_transcript(path)
    if not found:
        return None
    name = found.lower()
    for key in READER_SIZES:
        if key in name:
            return key
    return None


# The per-agent model record. event_reader() above reads a subagent's own
# transcript live, which races the file being written and returns None
# whenever it loses that race. The SubagentStart hook writes the reader
# profile once, at spawn, from Claude Code's own record of what it spawned,
# and a later hook on that SAME agent's own events reads it back instead of
# re-deriving it from a transcript that may not be flushed yet.
#
# Keyed per agent, on actor_key() below, never on event["session_id"]. A
# SubagentStart event carries session_id, transcript_path, cwd, prompt_id,
# agent_id, agent_type and hook_event_name, and its session_id is the
# SPAWNING session, shared by every agent that session spawns.
AGENT_MODEL_FILE = "densepack-agentmodel-%s"


def transcript_key(event):
    """The filename stem of this event's own transcript_path, or None.

    The one identifier proven to name THIS event's own caller and nothing
    shared: see the AGENT_MODEL_FILE note above for why session_id cannot
    stand in for it on a SubagentStart event."""
    if not isinstance(event, dict):
        return None
    path = event.get("transcript_path")
    if not path:
        return None
    try:
        return Path(path).stem
    except (TypeError, ValueError):
        return None


def actor_key(event):
    """The key that names THIS event's own subagent, or None for the lead.

    "agent-<agent_id>", the same stem Claude Code gives that agent's own
    transcript, so the record written at spawn and that agent's own later Read
    events join on one name. The transcript stem alone does not work: a
    SubagentStart event carries the LEAD's transcript_path as often as the
    spawned agent's own, and one file would then hold one model for every
    agent of the session.

    None for the lead, which carries no agent_id. The lead keeps
    event_reader() on its own transcript, which names its own model. A session
    id is never returned, so one agent's record cannot decide another
    agent's reader.
    """
    if not isinstance(event, dict):
        return None
    agent_id = event.get("agent_id")
    if agent_id:
        return "agent-%s" % agent_id
    stem = transcript_key(event)
    return stem if stem and stem.startswith("agent-") else None


def record_agent_model(key, reader_key):
    """Write the reader profile a spawned agent will run on, keyed by its
    own transcript stem. Called once, at SubagentStart, never at Read time:
    a Read hook only looks this up, it never writes it. A write failure is
    silent, the same failure mode every gate in this folder chooses; the
    caller that reads this back treats a missing file as unknown and falls
    back on its own terms, never by crashing or by blocking the spawn."""
    if not key or not reader_key:
        return
    try:
        (tmp_dir() / (AGENT_MODEL_FILE % key)).write_text(
            reader_key, encoding="utf-8")
    except OSError:
        pass


def agent_model(key):
    """The reader profile record_agent_model() wrote for this transcript
    stem, or None: no key, a session that started before this existed, or a
    spawn whose model could not be read. Never guesses and never falls back
    to resolved_reader(), the LEAD's own cached size: a caller with no
    record here has its own further fallback to make, on its own terms."""
    if not key:
        return None
    path = tmp_dir() / (AGENT_MODEL_FILE % key)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    # Only a name this file already knows. drop_read_gate.py joins the answer
    # into a folder path, and record_agent_model() is the only writer, so the
    # set it writes is the whole set a caller may receive.
    return value if value in MEASURED_MODELS else None


def is_subagent(event):
    """True when a subagent fired this event, not the lead.

    A subagent's PreToolUse carries the LEAD's session_id and the lead's
    transcript_path, so neither field separates the two. agent_id and
    agent_type name the real actor. Empty or absent means the lead, so an
    actor this cannot prove keeps the lead's treatment.
    """
    if not isinstance(event, dict):
        return False
    return bool(event.get("agent_id")) or bool(event.get("agent_type"))


def actor_reader(event=None, key=None):
    """The reader profile for the agent that fired THIS event, or None,
    which means MAKE NO IMAGE AND SEND PLAIN TEXT.

    One answer with one meaning for every caller. None covers two cases
    that must be treated alike: an actor running a model outside
    MEASURED_MODELS, haiku among them, and an actor that cannot be
    identified at all. Neither may be guessed at.

    Three sources for a subagent, in this order.

    | Source | Why it comes where it does |
    | --- | --- |
    | The record the SubagentStart hook wrote at spawn | One file read, and it names this one agent |
    | Claude Code's own agent-<id>.meta.json | Written by Claude Code, not derived; it answers when the spawn hook lost its race with that same file, which is most spawns. The answer is written into the record, so this search runs once per agent |
    | This event's own transcript, through event_reader() | Only when transcript_path is this agent's own file, because a subagent's PreToolUse carries the LEAD's transcript_path |

    None when all three fail: an unmeasured model leaves no record,
    reader_key_for_model() returns None for it, and a caller must send
    plain text.

    FOR A SUBAGENT ACTOR. The LEAD keeps resolved_reader() and the
    UNKNOWN_READER fallback documented on that function. Callers pick
    between the two on the actor, not on the file being read.
    """
    if key is None:
        key = actor_key(event)
    if not key:
        # The lead. Its own event carries its own transcript_path.
        return event_reader(event) if event is not None else None
    found = agent_model(key)
    if found:
        return found
    agent_id = key[len("agent-"):]
    # reader_key_for_model(None) answers UNKNOWN_READER, the LEAD's fallback,
    # so each source below is asked only with a model name in hand. Claude
    # Code's meta.json no longer carries a model, so the agent's own
    # transcript and the spawn log answer after it.
    for named in (agent_meta_model(agent_id), _agent_own_model(agent_id),
                  _spawned_model(agent_id, event)):
        found = reader_key_for_model(named) if named else None
        if found:
            # Written back so the next Read by this same agent is one file
            # read and never another walk of every project folder.
            record_agent_model(key, found)
            return found
    if event is not None and transcript_key(event) == key:
        return event_reader(event)
    return None


def _agent_own_model(agent_id):
    """The model this subagent's own transcript, agent-<id>.jsonl, names on
    its first reply, or None before that reply is on disk."""
    path = agent_transcript(agent_id)
    return _model_from_transcript(path) if path else None


def _spawned_model(agent_id, event):
    """The model the Agent call that spawned this subagent asked for, from
    the spawn log brief_pack.py writes, matched on the agent type and the
    description Claude Code records in agent-<id>.meta.json. A spawn that
    named no model inherits the lead's, so the lead's model answers. None
    when no row matches."""
    agent_type, description = agent_meta_fields(agent_id)
    if not description:
        return None
    session = str((event or {}).get("session_id") or "")
    wanted_type = agent_type or "general-purpose"
    match = None
    for row in sealed_rows(delegation_path()):
        if row.get("description") != description:
            continue
        if (row.get("subagent_type") or "general-purpose") != wanted_type:
            continue
        if session and str(row.get("session") or "") != session:
            continue
        match = row
    if not match:
        return None
    model = str(match.get("model") or "")
    if model and model != "inherited":
        return model
    return lead_model_name(session or None) or None


def actor_size(event=None, key=None):
    """The pixel size an image for this actor must be drawn at, or None
    when this actor must be sent plain text instead. See actor_reader()."""
    reader = actor_reader(event, key)
    if not reader:
        return None
    return READER_SIZES.get(reader)


def reader_gets_images(reader):
    """True when this reader profile is sent images.

    Fable, Opus and Sonnet always are. Haiku, any other model and None get
    text. Type /max-off to send Sonnet text.
    """
    if reader == "sonnet":
        return settings().get("maxpack") == "on"
    return reader in ("fable", "opus")


def lead_gets_images(session=None):
    """True when the lead of this session is sent images.

    A lead whose model is named and matches no reader profile, such as
    Haiku, gets text. A lead with no model on record keeps resolved_reader().
    """
    name = lead_model_name(session).lower()
    if (name and settings().get("reader", "auto") == "auto"
            and not any(key in name for key in READER_SIZES)):
        return False
    return reader_gets_images(resolved_reader(session))


def gets_images(event):
    """True when the agent that fired this event is sent images."""
    if is_subagent(event):
        return reader_gets_images(actor_reader(event))
    return lead_gets_images((event or {}).get("session_id"))


def agent_meta_model(agent_id):
    """The real model Claude Code recorded for this agent id at spawn time,
    read from its own agent-<id>.meta.json: stopped_by_user() already reads
    a different field, stoppedByUser, from the same file. None when the id
    is empty, the file cannot be found, or it names no model. Every project
    is searched, the same glob stopped_by_user() uses, because the id alone
    does not say which project spawned it."""
    if not agent_id:
        return None
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return None
    try:
        for meta in root.glob("*/*/subagents/agent-%s.meta.json" % agent_id):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            model = data.get("model") if isinstance(data, dict) else None
            if model:
                return str(model)
    except OSError:
        return None
    return None


def agent_meta_fields(agent_id):
    """The agent type and description Claude Code recorded for this agent id
    at spawn time, read from the agent-<id>.meta.json that agent_meta_model()
    reads the model from. Returns (None, None) when the id is empty or no
    file is found.

    The SubagentStart hook keys the card lookup on these two fields. Its
    own event carries prompt_id and agent_id and no prompt text, and
    reading the agent's live transcript for that text races the write.
    """
    if not agent_id:
        return (None, None)
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return (None, None)
    try:
        for meta in root.glob("*/*/subagents/agent-%s.meta.json" % agent_id):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if isinstance(data, dict):
                return (data.get("agentType"), data.get("description"))
    except OSError:
        return (None, None)
    return (None, None)


# Every identity card a lead may name in a brief. The SubagentStart hook
# serves the images of the named card. A name outside this tuple is unknown
# and the worker card is served in its place.
CARDS = ("worker", "check", "reader", "runner")
DEFAULT_CARD = "worker"

# One file per spawning session, one line per Agent call.
CARD_FILE = "densepack-card-%s.jsonl"

# The line a lead writes to name a card: the word card, then the name, alone
# on its line. The anchors stop the word card inside a sentence selecting a
# role.
CARD_LINE = re.compile(
    r"^[ \t>*-]*card[ \t]*[:=]?[ \t]+([A-Za-z][A-Za-z0-9_-]{0,15})[ \t]*$",
    re.MULTILINE)


def card_in_text(text):
    """The card name a brief gives, or None when the brief names none.

    The last matching line wins: a lead that corrects itself writes the
    correction below the first line. A name outside CARDS returns None and
    the caller falls back to DEFAULT_CARD.
    """
    if not isinstance(text, str):
        return None
    found = None
    for match in CARD_LINE.finditer(text):
        name = match.group(1).lower()
        if name in CARDS:
            found = name
    return found


def card_path(session_id):
    """The card record for one spawning session."""
    return tmp_dir() / (CARD_FILE % (str(session_id or "none")[:8],))


def record_card(session_id, prompt_id, agent_type, description, card):
    """Append this spawn's card name to the session's card record.

    brief_pack.py calls this at PreToolUse, the one point where the raw brief
    is still readable: updatedInput REPLACES the prompt with a pointer, and a
    brief under the pack threshold returns earlier still.

    prompt_id names the lead turn the Agent call was made in and agent_type
    names the helper. claim_card() matches on that pair, because both fields
    are on the SubagentStart event itself. The description is written too and
    read as the sharper match whenever it can be read at all.
    """
    if not card:
        return
    row = json.dumps({"prompt_id": str(prompt_id or ""),
                      "agent_type": str(agent_type or ""),
                      "description": str(description or ""),
                      "card": card})
    path = card_path(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(row + "\n")
    except OSError:
        return


def claim_card(session_id, prompt_id, agent_type, description):
    """Take this spawn's card off the session's card record, or None.

    The entry is removed as it is read, so two spawns of one agent type in
    one turn take the two cards their briefs named, in the order the lead
    wrote them.

    Why the description is not the key. Claude Code writes
    agent-<id>.meta.json while the SubagentStart hook is already running,
    so agent_meta_fields() can read nothing and the spawn would be served
    the worker card its brief did not ask for. prompt_id and agent_type
    are on the event, so neither can arrive late. The description is still
    preferred when it does arrive in time, because it separates two spawns
    of one agent type inside one turn.
    """
    path = card_path(session_id)
    try:
        rows = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    want_turn = str(prompt_id or "")
    want_type = str(agent_type or "")
    want_desc = str(description or "")

    entries = []
    for row in rows:
        try:
            data = json.loads(row)
        except ValueError:
            data = None
        entries.append(data if isinstance(data, dict) else None)

    def usable(index):
        data = entries[index]
        if data is None or data.get("card") not in CARDS:
            return False
        if data.get("agent_type") != want_type:
            return False
        turn = str(data.get("prompt_id") or "")
        return not (turn and want_turn) or turn == want_turn

    picked = None
    if want_desc:
        for index in range(len(entries)):
            if usable(index) and entries[index].get("description") == want_desc:
                picked = index
                break
    if picked is None:
        for index in range(len(entries)):
            if usable(index):
                picked = index
                break
    if picked is None:
        return None

    card = entries[picked].get("card")
    kept = [rows[i] for i in range(len(rows)) if i != picked]
    try:
        path.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
    except OSError:
        pass
    return card


def agent_transcript_mtime(agent_id):
    """The modification time of this agent's own transcript, agent-<id>.jsonl,
    the file Claude Code appends to on every turn the subagent takes. Same
    glob root as agent_meta_model() and stopped_by_user(), because the
    transcript sits in the same subagents folder next to the .meta.json
    file, keyed the same way, one id, every project searched since the id
    alone does not say which project spawned it.

    Used as the progress signal: a stat() call on one file, never a read of
    its contents. The mtime answers the only question a poll needs
    answered, whether the agent wrote anything since the last check. None
    when the id is empty or no such file is found.
    """
    if not agent_id:
        return None
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return None
    try:
        for transcript in root.glob("*/*/subagents/agent-%s.jsonl" % agent_id):
            try:
                return transcript.stat().st_mtime
            except OSError:
                continue
    except OSError:
        return None
    return None


# Read only the last 200,000 bytes of a transcript for last_touched_file()
# below. A stall report needs the most recent tool call, never an earlier
# one, and a transcript can run past a hundred megabytes; reading all of it
# to find the last line costs a read this file's own docstring elsewhere
# says a poll cannot afford. 200,000 bytes holds thousands of lines, far
# more than one agent writes between two tool calls.
TRANSCRIPT_TAIL_BYTES = 200_000

# Tool names whose input carries a file_path this project treats as "this
# agent touched a file". NotebookEdit is not in this list: no subagent
# transcript measured here has used it, and adding an untested name risks
# reading a key that tool does not carry.
FILE_TOOLS = ("Write", "Edit")


def last_touched_file(agent_id):
    """The most recent file this agent wrote or edited, and when: (path,
    unix seconds) from the last Write or Edit tool call in its own
    transcript, or (None, None) when the file cannot be found or names no
    such call. Reads only TRANSCRIPT_TAIL_BYTES from the end of the file,
    on the assumption that a call from the middle of a long run has since
    been followed by newer lines, the normal case; the caller only asks
    this on the rare stalled path, never on every wake.
    """
    if not agent_id:
        return None, None
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return None, None
    path = None
    try:
        for candidate in root.glob("*/*/subagents/agent-%s.jsonl" % agent_id):
            path = candidate
            break
    except OSError:
        return None, None
    if path is None:
        return None, None
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > TRANSCRIPT_TAIL_BYTES:
                fh.seek(size - TRANSCRIPT_TAIL_BYTES)
            raw = fh.read()
    except OSError:
        return None, None
    text = raw.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") != "assistant":
            continue
        content = (row.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            if block.get("name") not in FILE_TOOLS:
                continue
            file_path = (block.get("input") or {}).get("file_path")
            if not file_path:
                continue
            stamp = row.get("timestamp")
            when = None
            if stamp:
                try:
                    from datetime import datetime
                    when = datetime.fromisoformat(
                        stamp.replace("Z", "+00:00")).timestamp()
                except (ValueError, TypeError):
                    when = None
            return file_path, when
    return None, None


def has_edited(session_id):
    """True when a Write or Edit tool call appears anywhere in this
    session's own transcript.

    Answers whether an edit has landed yet in the CURRENT session, not a
    subagent's. Reuses transcript_path and FILE_TOOLS rather than a new
    per-session state file: the transcript already carries this fact.
    """
    path = transcript_path(session_id)
    if path is None:
        return False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") != "assistant":
            continue
        content = (row.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        for block in content:
            if (isinstance(block, dict) and block.get("type") == "tool_use"
                    and block.get("name") in FILE_TOOLS):
                return True
    return False


# THE SONNET BURST. One Sonnet turn holding a few pictures answers in a few
# hundred output tokens; the same turn holding many can answer in thousands,
# and output bills at five times the input rate, so past that point the
# pictures cost more money than the input they saved.
#
# The break is not on patches alone and not on count alone: fewer, larger
# pictures ran to less output than many short ones, and a few very large
# pictures ran to the most. Both bounds are needed, and the bytes of a turn
# are the one the gate can read before it converts anything.
#
# So a turn is inside the cap when it asks for BURST_CAPS files or fewer AND
# their source bytes come to BURST_BYTES or fewer. A turn outside it goes to
# text WHOLE: a few pictures beside many files of text is a turn doing the
# work of both, so the pictures buy nothing there.
#
# Opus and Fable hold no cap, because a cap on either throws away a real
# saving.
BURST_CAPS = {"sonnet": 32}
# The byte budget for one turn. It holds a turn of thirty-two large source
# files, about 656,000 bytes, because the hooks of one turn do not all see
# the whole batch.
BURST_BYTES = 700_000


def burst_cap(model):
    """The most packed pictures one turn may hand this reader profile, or
    None when the profile was measured to need no cap."""
    return BURST_CAPS.get(str(model or "").strip().lower())


def over_cap(paths, cap, budget=BURST_BYTES):
    """True when this turn's batch is too wide to draw: more files than the
    cap, or more source bytes than the budget. A file whose size cannot be
    read counts as nothing, so a name that is already gone never caps a turn
    on its own.

    One file read on its own is never over the cap, whatever its size. Every
    turn measured to burst held several pictures; a single large file was
    not measured, and a limit nothing measured is a limit invented."""
    if len(paths) > cap:
        return True
    if len(paths) < 2:
        return False
    total = 0
    for name in paths:
        try:
            total += Path(name).stat().st_size
        except OSError:
            continue
    return total > budget


def agent_transcript(agent_id):
    """This subagent's own transcript file, agent-<id>.jsonl, or None. Same
    glob root as agent_transcript_mtime(): one id, every project searched,
    because the id alone does not say which project spawned it."""
    if not agent_id:
        return None
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return None
    try:
        for transcript in root.glob("*/*/subagents/agent-%s.jsonl" % agent_id):
            return transcript
    except OSError:
        return None
    return None


# Waiting for the batch does not work. The hooks of a wide batch start
# before the whole assistant message is on disk, and the message does not
# stream at a steady rate: the Read blocks of one message can land seconds
# apart. A quiet window short enough to cost a lone Read nothing ends inside
# those gaps, and one long enough to cover them holds every Read for most of
# a minute.
def turn_reads(event):
    """Every file the assistant message now running asked to Read, in the
    order it asked, and that message's id: (paths, id).

    Claude Code writes each content block of an assistant message to the
    transcript as its own line, all of them carrying one message id, so a
    PreToolUse hook can see the batch its own Read belongs to and the gate
    can decide how many pictures the turn is about to hold before it draws
    the first one. The lines are written as the reply streams and the tools
    start before the last of them lands, so an early hook counts only the
    part of its batch that had arrived; see the note above. Results from
    tools already finished are appended after those lines, so this walks
    backwards past them to the last assistant line and then counts only that
    id's blocks.

    A subagent's PreToolUse carries the LEAD's transcript_path, so a
    subagent is read from its own agent-<id>.jsonl instead; counting the
    lead's batch against a subagent's Read would cap a turn that holds one
    picture.

    ([], "") when the transcript cannot be read, which leaves every caller
    uncapped.
    """
    if not isinstance(event, dict):
        return [], ""
    path = event.get("transcript_path")
    if is_subagent(event):
        path = agent_transcript(event.get("agent_id"))
    if not path:
        return [], ""
    source = Path(path)
    try:
        size = source.stat().st_size
        with source.open("rb") as fh:
            if size > TRANSCRIPT_TAIL_BYTES:
                fh.seek(size - TRANSCRIPT_TAIL_BYTES)
            raw = fh.read()
    except OSError:
        return [], ""
    ident = None
    found = []
    for line in reversed(raw.decode("utf-8", errors="replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") != "assistant":
            if ident is None:
                continue
            break
        message = row.get("message") or {}
        here = message.get("id")
        if ident is None:
            ident = here
        elif here != ident:
            break
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in reversed(content):
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use" or block.get("name") != "Read":
                continue
            asked = (block.get("input") or {}).get("file_path")
            if isinstance(asked, str) and asked:
                found.append(asked)
    found.reverse()
    return found, str(ident or "")


def claim_once(key):
    """True for the first caller to name `key` this session, False after.

    An exclusive create, so the hooks of one batch, which run at the same
    moment, cannot all win it. Used to write one receipt row for a whole
    capped turn instead of one row per read in it.
    """
    marker = tmp_dir() / ("densepack-cap-%s" % re.sub(r"[^A-Za-z0-9_-]", "",
                                                      str(key))[:64])
    try:
        os.close(os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except OSError:
        return False
    return True


def queue_cap_row(event, model, reason, chars):
    """The receipt row for a turn the picture cap sent back as text. Same
    shape subagent_stop.py's queue_text_row() writes: no images, no saving
    and no cost, so pointer.py prints the reason where a picture's price
    would sit and leaves the row out of the run total and out of the receipt
    debt, which is built from packed rows alone."""
    import densepack as dp
    append_queue({
        "agent_id": str((event or {}).get("session_id") or ""),
        "agent_type": "read cap", "font_px": font_size(),
        "model": model, "spawned_by": str((event or {}).get("session_id") or ""),
        "mode": "text", "images": [], "dims": [], "pixels": 0,
        "chars": chars, "text_tokens": round(chars / dp.CHARS_PER_TOKEN),
        "image_tokens": 0, "patch_tokens": 0, "delivery_tokens": 0,
        "reason": reason, "would_cost": 0,
    })


def resolved_reader(session=None):
    """The reader profile in force: the model the lead is running on.

    `session` names one session explicitly. It is left out by every hook,
    which lets lead_session() answer from the event in hand.

    A pinned reader overrides it, for the session that pinned it and for no
    other. The default is "auto", which reads the model
    note_lead_model() recorded for the session running now. A model that was
    never scored on a condensed image resolves to UNKNOWN_READER, the size
    both scored models read, and so does a session with no model recorded and
    no transcript to read one from.
    """
    chosen = settings().get("reader", "auto")
    if chosen in READER_SIZES:
        return chosen
    name = lead_model_name(session).lower()
    if not name:
        return UNKNOWN_READER
    for key in READER_SIZES:
        if key in name:
            return key
    return UNKNOWN_READER


def user_said(session_id, phrase):
    """True when the last line the user actually typed carries `phrase`.

    The escape check every gate without a text field shares. The Read tool
    has no field a caller can write a sentence into, unlike Bash's command or
    Agent's prompt, so a phrase that stands a gate aside rides the
    conversation instead of the call. This walks the session's own transcript
    from the end and stops at the first line that is a real typed message
    rather than a tool result: a tool result's content is a list of blocks
    with no "text" block in it, so it is skipped and the search keeps walking
    back. A transcript that cannot be read is not proof the phrase was said,
    so the answer is False and the gate stays up.
    """
    path = transcript_path(session_id)
    if path is None:
        return False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") != "user" or row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text")
        else:
            continue
        if not text:
            continue
        return phrase in text.lower()
    return False


def transcript_path(session_id):
    """This session's own transcript file, or None.

    Claude Code writes one per session under ~/.claude/projects, in a folder
    named after the project path with every separator replaced by a dash. The
    folder is matched by listing rather than by rebuilding that name, because
    the drive letter's case differs between the two and a rebuilt name misses.
    """
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return None
    wanted = str(session_id or "").strip()
    if not wanted:
        return None
    try:
        for folder in base.iterdir():
            candidate = folder / ("%s.jsonl" % wanted)
            if candidate.is_file():
                return candidate
    except OSError:
        return None
    return None


def read_turn_cost(session_id):
    """What one more turn costs this session, in tokens, or None.

    Claude Code sends the whole conversation at the start of every turn, so a
    Read call to open a packed image is one more send of everything said so
    far. The last usage record in the transcript holds that size.

    Opening a picture is the expensive half of packing: every Read turn
    re-sends the whole conversation, so this figure is what the lead pays
    to open one.
    """
    path = transcript_path(session_id)
    if path is None:
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-400:]):
        if '"assistant"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        usage = (record.get("message") or {}).get("usage") or {}
        if not usage:
            continue
        size = ((usage.get("cache_read_input_tokens", 0) or 0)
                + (usage.get("cache_creation_input_tokens", 0) or 0))
        if size:
            return size
    return None


def report_pointer(image_count, folder):
    """The line a lead receives naming this batch's report images.

    It is deliberately short. What a condensed image is, what the asterisk on
    a receipt row means, and where the manifest lives are all in the briefing
    image the SessionStart hook delivers, and that image stays in context for
    the whole session. Repeating any of it per batch buys the lead nothing and
    is charged every time.
    """
    return ("DensePack: %d report image(s) in %s, named "
            "densepack-img-<agent id>-1.png. Each IS that agent's report. "
            "Its exact text is densepack-src-<agent id>.txt beside it."
            % (image_count, folder))


def stub_pointer(image_count, folder):
    """The line a lead receives when every report in the batch is a stub.

    pointer.py sends this one, not report_pointer(), whenever no report in the
    batch came back as prose, which is the normal case. It is 271 characters
    against report_pointer's 137, because it also states that the stubs are
    summaries and names the manifest.

    subagent_stop.py charges this text for a stub report, so the receipt
    prices the line the lead actually receives. Two copies of one line
    exist, and the receipt must price the one that ships.
    """
    return ("DensePack: %d report image(s) ready in %s, named "
            "densepack-img-<agent id>-1.png. The stubs above are summaries "
            "only; each image IS the full report. Its exact text is "
            "densepack-src-<agent id>.txt beside it. Timings and sizes per "
            "agent are in densepack-manifest.jsonl beside the images."
            % (image_count, folder))


# THE LINE PULL. A reader takes a long number, a hash or a path off the image
# when it reads clean. When one does not read clean, the reader pulls that
# one line from the text by its green line number, Read with offset N and
# limit 1, and never the whole file and never the image a second time. A
# Read whose limit is this small passes every gate untouched, before any
# redirect to an image, so the pull costs one short tool result. The cap
# keeps it a pull and not a read of the file in slices.
LINE_PULL_MAX = 20


def line_pull(tool_input):
    """True for a Read that asks for at most LINE_PULL_MAX lines."""
    try:
        limit = int(tool_input.get("limit") or 0)
    except (TypeError, ValueError, AttributeError):
        return False
    return 0 < limit <= LINE_PULL_MAX


# The working directory the current hook event named, kept so project_dir()
# can walk from the session's own folder rather than from wherever this
# process happens to be running. Set by read_event(), before anything else
# touches the disk. A headless worker can run with no CLAUDE_PROJECT_DIR and
# a working directory under the user's Temp folder; without this the walk
# finds nothing, tmp_dir() creates a stray Temp\.claude, and every later
# worker under Temp adopts it, splitting the plugin's state across two
# folders.
_EVENT_CWD = None

# The session id the event in hand names. Held the same way as the cwd above,
# and for the same reason: a hook reads one event and then calls plain
# functions that have no event to pass on. lead_session() reads it.
_EVENT_SESSION = ""


def note_event_cwd(event):
    """Remember the working directory a hook event names, when it names one."""
    global _EVENT_CWD
    if not isinstance(event, dict):
        return
    cwd = event.get("cwd")
    if isinstance(cwd, str) and cwd and os.path.isdir(cwd):
        _EVENT_CWD = Path(cwd)


def note_event_session(event):
    """Remember the session a hook event names, when it names one."""
    global _EVENT_SESSION
    if not isinstance(event, dict):
        return
    session = event.get("session_id")
    if isinstance(session, str) and session.strip():
        _EVENT_SESSION = session.strip()


def temp_shaped(folder):
    """True for the system temp root itself and for its ancestors.

    A .claude sitting AT the temp root belongs to no project: it is the
    stray a lost worker created, and adopting it splits the plugin's state.
    Folders UNDER the temp root are not temp shaped, because real test
    sandboxes are built there and the walk must keep working for them.
    """
    import tempfile
    try:
        troot = Path(tempfile.gettempdir()).resolve()
        here = Path(folder).resolve()
    except OSError:
        return False
    return here == troot or here in troot.parents


def project_dir():
    """Hooks always receive CLAUDE_PROJECT_DIR. dpctl run from a terminal may
    not, and a terminal can sit anywhere inside the project, so the folder is
    found by walking upward: from the working directory the hook event named,
    when read_event() has seen one, and from this process's own working
    directory otherwise. The event's cwd is the session's, so a worker
    process parked in a scratch folder still resolves to the session's
    project.

    A .claude folder alone is the wrong marker. A repository whose tests
    create a .claude folder would stop the walk there, and a settings file
    written there is one no hook ever reads.

    LEAD_SESSION_FILE is the marker instead. session_start writes it into the
    running session's own .claude/tmp, so the folder holding it is the folder
    the hooks read. A folder with a .claude and no marker is the fallback,
    which is what a first run before any session sees.

    A temp shaped folder is never accepted, marker or not: a .claude at the
    system temp root is the stray described above note_event_cwd, not a
    project.
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    here = _EVENT_CWD if _EVENT_CWD is not None else Path(os.getcwd())
    fallback = None
    for candidate in (here, *here.parents):
        if temp_shaped(candidate):
            continue
        if not (candidate / ".claude").is_dir():
            continue
        if (candidate / ".claude" / "tmp" / LEAD_MODEL_FILE).is_file() or \
                (candidate / ".claude" / "tmp" / "densepack-lead-session").is_file():
            return candidate
        if fallback is None:
            fallback = candidate
    return fallback if fallback is not None else here


def machine_state_dir():
    """A folder outside the project for state the plugin later trusts.

    A cloned project can commit anything under its own .claude folder, so a
    file the plugin reads back as its own words lives here instead: under
    CLAUDE_PLUGIN_DATA, or ~/.claude/densepack-state, in one subfolder per
    project, named by a hash of the project's path."""
    import hashlib
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or str(Path.home() / ".claude" / "densepack-state")
    key = hashlib.sha256(str(project_dir().resolve()).lower().encode("utf-8")).hexdigest()[:16]
    folder = Path(base) / "projects" / key
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def tmp_dir():
    root = project_dir()
    out = root / ".claude" / "tmp"
    # Never CREATE a .claude at the temp root or above it. A process whose
    # resolution came to rest there has no project at all; returning the
    # uncreated path makes every write fail into the callers' own try
    # blocks, and doing nothing is the correct failure for a worker with
    # no project. See note_event_cwd above for the stray this stops.
    if not temp_shaped(root):
        out.mkdir(parents=True, exist_ok=True)
    return out


def queue_path():
    return tmp_dir() / "densepack-queue.jsonl"


# Every pattern a packer here writes for a source-text file, paired with the
# image name pattern built from the same id or stamp. Read from where each
# one is written, not guessed:
#   densepack-src-<agent id>.txt    beside densepack-img-<agent id>-1.png
#     (subagent_stop.py, the report's exact text)
#   densepack-report-<agent id>.txt beside densepack-img-<agent id>-1.png
#     (subagent_stop.py's net; same agent id as the src file, same image)
#   densepack-bashsrc-<id>.txt      beside densepack-bash-<id>-1.png
#     (bash_pack.py)
#   densepack-briefsrc-<stamp>.txt  beside densepack-brief-<stamp>-1.png
#     (brief_pack.py; the stamp itself carries hyphens)
# Kept in one place so a gate cannot pair a source file with the wrong image
# by drifting from another gate's copy of this list.
SOURCE_TO_IMAGE = (
    (re.compile(r"^densepack-src-([A-Za-z0-9]+)\.txt$"), "densepack-img-%s-1.png"),
    (re.compile(r"^densepack-report-([A-Za-z0-9]+)\.txt$"), "densepack-img-%s-1.png"),
    (re.compile(r"^densepack-bashsrc-([A-Za-z0-9]+)\.txt$"), "densepack-bash-%s-1.png"),
    (re.compile(r"^densepack-briefsrc-([A-Za-z0-9-]+)\.txt$"), "densepack-brief-%s-1.png"),
)


def sibling_image(path):
    """The packed image a source-text file sits beside, or None.

    Matched on the file's OWN NAME against SOURCE_TO_IMAGE, never on a bare
    "densepack-" prefix: a prefix match alone says yes for every plugin
    file, images and bookkeeping files included, which answers a different
    question than "does a drawn image already carry these words". Returns
    the image's path only when that file actually exists on disk, in the
    same folder as the source file; a source file whose image was refused
    or never drawn has nothing to redirect to, and the raw read is the only
    copy of the words left.
    """
    text = str(path).replace("\\", "/")
    name = text.rsplit("/", 1)[-1]
    folder = Path(text).parent
    # The packers write these pairs only in .claude/tmp, and keep copies go to
    # the vault. A pair anywhere else is a project's own files, and a project
    # could pair harmless text with an image that says something else.
    here = os.path.normcase(os.path.abspath(str(folder)))
    if not any(here == base or here.startswith(base + os.sep)
               for base in (os.path.normcase(os.path.abspath(str(tmp_dir()))),
                            os.path.normcase(os.path.abspath(str(vault_dir()))))):
        return None
    for pattern, image_fmt in SOURCE_TO_IMAGE:
        match = pattern.match(name)
        if not match:
            continue
        candidate = folder / (image_fmt % match.group(1))
        if candidate.is_file():
            return str(candidate)
    return None


def pack_images(src):
    """Every image of this source text's pack, in order, from the seal.

    SOURCE_TO_IMAGE names image 1 alone, so a redirect that stops there hands
    a reader one image of a long output and says nothing about the rest. The
    list comes from the sealed record and never from a folder listing: a
    project can drop a file named like image 2 beside a real pack.
    """
    folder = Path(str(src)).parent
    return [str(folder / name) for name in sealed_pack(src)
            if (folder / name).is_file()]


def sealed_sibling_image(path):
    """sibling_image(), and only where this machine's plugin wrote the pair.

    A redirect hands the reader the image in place of the text, so a project
    that commits both under .claude/tmp could have a Read of harmless words
    answered with an image that shows other words. The gates that only refuse
    a raw read still use sibling_image(): refusing a planted file is safe.
    """
    image = sibling_image(path)
    if image is None or not pair_sealed(path, Path(image).name):
        return None
    return image


# 22 minutes of no activity on the agent's own transcript. Short enough that
# a stall is caught in the same sitting, long enough that a slow but working
# agent is not called dead. Read through last_activity() below, this
# measures silence, not total run time.
STALE_AFTER = 1320.0

# The point where silence stops meaning "slow" and starts meaning "dead".
# Taken from the manifest's own history across every model measured, not
# invented: Sonnet median 7.2 minutes over 68 runs and longest 48.2, Haiku
# median 3.0 over 7, Fable median 11.3 over 16, Opus median 15.1 over 35.
# 48.2 minutes is the longest run that ever actually finished, on any model,
# in that spread. No completed agent has gone quiet this long and come back,
# so silence past it is stronger evidence of a crash than of a slow agent.
DEAD_AFTER = 48.2 * 60.0


def stopped_by_user(agent_id):
    """True when Claude Code recorded that the user stopped this agent.

    It writes agent-<id>.meta.json beside each subagent transcript, about 170
    bytes, holding the agent type, the description, the model and
    stoppedByUser. An agent that returns nothing was stopped until a file says
    otherwise, and this is that file. A missing or unreadable file returns
    False, so a real silence is still reported.
    """
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return False
    try:
        for meta in root.glob("*/*/subagents/agent-%s.meta.json" % agent_id):
            try:
                return bool(json.loads(meta.read_text(encoding="utf-8"))
                            .get("stoppedByUser"))
            except (ValueError, OSError):
                return False
    except OSError:
        return False
    return False


# The gap stoppedByUser above cannot close. Claude Code sets that field only
# for a literal user interrupt, so a LEAD that stops one of its own
# background subagents through the TaskStop tool leaves nothing behind: no
# SubagentStop event fires and agent-<id>.meta.json never gets
# stoppedByUser, and silence alone would call that agent dead.
#
# LIFECYCLE_FILE is one append-only jsonl row per moment in a subagent's
# life, written by the hooks that already run at each of those moments, so
# no new process has to be started to keep it. The SubagentStart hook
# appends "spawned", subagent_stop.py appends "ended", and pointer.py, the
# one hook Claude Code fires after every tool call including TaskStop,
# appends "stopped-by-lead" when the tool call it just saw was TaskStop.
# unfinished_agents() below reads it next to stopped_by_user(), so a
# lead-ordered stop is excluded from silence the same way a user-ordered one
# is.
#
# Not listed in bootstrap.py's PRUNE_PREFIXES. densepack-manifest.jsonl
# beside it is never pruned by age, "the record, not the working copy", and
# this file is the same kind of record, so it grows the same way.
LIFECYCLE_FILE = "densepack-lifecycle.jsonl"


def lifecycle_path():
    return tmp_dir() / LIFECYCLE_FILE


def append_lifecycle(agent_id, event, lane=""):
    """Append one row: this moment, this agent, this event, this lane tag.

    Never rewritten, so a crash mid-write loses at most the row being
    added, the same append-only shape the pending queue uses. A write
    failure is silent, the same failure mode every marker write in this
    file chooses: a lost lifecycle row is a smaller problem than a hook
    that stops working.
    """
    agent_id = str(agent_id or "")
    if not agent_id:
        return
    import time as _time
    row = {"at": _time.time(), "agent_id": agent_id,
          "lane": str(lane or ""), "event": str(event or "")}
    try:
        with lifecycle_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def last_lifecycle_event(agent_id):
    """The most recent lifecycle row for this agent id, or None.

    Read once per candidate, the same cost stopped_by_user() already pays,
    never on the hot path that scans every live agent.
    """
    agent_id = str(agent_id or "")
    if not agent_id:
        return None
    path = lifecycle_path()
    if not path.is_file():
        return None
    last = None
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and str(row.get("agent_id")) == agent_id:
                    last = row
    except OSError:
        return None
    return last


def stopped_by_lead(agent_id):
    """True when the last recorded lifecycle event for this agent is a
    lead-ordered stop through the TaskStop tool.

    Checked in unfinished_agents() beside stopped_by_user(): a stop this
    plugin itself recorded means the silence already has an explanation and
    is not a stall in progress.
    """
    row = last_lifecycle_event(agent_id)
    return bool(row) and row.get("event") == "stopped-by-lead"


def jsonl_rows(path):
    """Every JSON line in a file, skipping any line that will not parse.
    A read failure returns nothing: this reader must never be the reason
    a reply cannot land."""
    out = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out


def unfinished_agents(session, now=None):
    """Every agent this session spawned that has no manifest row yet,
    whether or not it has gone quiet, most-recently-started-first isn't
    tracked here: callers sort by whatever they measure. Returns
    (agent_id, started), started being the marker's own timestamp.

    This is the shared scan behind stale_agents() below, which wants only
    the ones quiet past STALE_AFTER, and behind any caller that wants the
    full live set to know when NONE are left. One scan, so the callers
    never drift into two different ideas of "still running".

    Matched by the start marker each agent writes on SubagentStart
    (densepack-start-<agent id>), never by start time. A spawn row from
    PreToolUse carries no agent id, so pairing it to a finished run by
    matching timestamps pairs the wrong rows whenever two or more agents
    are in flight at once. The marker carries the real agent id in its own
    filename, so this reads that instead and never has to guess a pairing.

    A manifest row for the id, at any state including a provisional one
    written by the report-file net's first pass, means the agent already
    reached SubagentStop at least once and is not silent. A marker whose own
    recorded session does not match, or that cannot be parsed, is left out
    rather than attributed by guesswork, since a wrong guess moves the alarm
    onto the wrong agent.

    An agent the user stopped is left out too: Claude Code's own record of
    that (stopped_by_user) means the silence has an explanation already and
    is not a stall in progress. An agent the LEAD stopped through the
    TaskStop tool is left out the same way, read from this plugin's own
    lifecycle record (stopped_by_lead), since Claude Code's own record only
    covers a literal user interrupt.
    """
    out = []
    for agent_id, started in _spawned_without_report(session):
        # An agent the user stopped is not a silent one. Checked last, because
        # it reads a file per candidate and almost every marker is filtered out
        # above without touching the disk.
        if stopped_by_user(agent_id):
            continue
        if stopped_by_lead(agent_id):
            continue
        out.append((agent_id, started))
    return out


def user_stopped_agents(session):
    """Every agent this session spawned that Claude Code marked stopped by
    the user and that never wrote a manifest row, as (agent_id, started).

    unfinished_agents() leaves these out on purpose, so no stall is ever
    reported for them, and no SubagentStop fires for a stopped agent, so
    nothing else tells the lead either. An interrupt of ONE lead tool call
    marks EVERY background agent stoppedByUser at that same instant, so
    several agents can die at the moment a user rejects one call. A caller
    reads this once per agent and tells the lead.
    """
    return [(agent_id, started)
            for agent_id, started in _spawned_without_report(session)
            if stopped_by_user(agent_id)]


def _spawned_without_report(session):
    """The one scan behind unfinished_agents() and user_stopped_agents():
    every start marker this session wrote whose agent has no manifest row,
    as (agent_id, started), before any stop record is consulted."""
    session = str(session or "")
    if not session:
        return []

    finished_ids = {str(r["agent_id"]) for r in
                    sealed_rows(tmp_dir() / "densepack-manifest.jsonl")
                    if str(r.get("spawned_by") or "") == session
                    and r.get("agent_id")}

    try:
        markers = sorted(tmp_dir().glob("densepack-start-*"))
    except OSError:
        return []

    prefix_len = len("densepack-start-")
    out = []
    for path in markers:
        agent_id = path.name[prefix_len:]
        if not agent_id:
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        started = None
        marker_session = None
        if isinstance(record, dict):
            marker_session = str(record.get("spawned_by") or "")
            try:
                started = float(record.get("at") or 0) or None
            except (TypeError, ValueError):
                started = None
        else:
            # A bare number, the older marker format or a marker
            # subagent_stop.py rewrote while an agent waits out the
            # report-file net's block-and-retry. Neither carries a session
            # tag, so this marker is only ever claimed through a manifest row
            # that already proves whose it is, in finished_ids above, never
            # guessed here.
            try:
                started = float(record)
            except (TypeError, ValueError):
                started = None
        if started is None:
            continue
        if agent_id in finished_ids:
            continue
        if marker_session != session:
            continue
        out.append((agent_id, started))
    return out


def last_activity(agent_id, started):
    """The timestamp of the newest evidence this agent has done anything:
    its own transcript file's mtime when that file exists and is newer than
    started, otherwise started itself.

    Quiet is measured as silence, not total elapsed run time. A working
    agent can run past STALE_AFTER simply by taking that long, a healthy
    fact for a real task, not a stall. A transcript grows on every tool
    call and every message the agent sends, so its mtime is the plain
    record of the last time this agent did anything, read with one stat()
    call rather than a parse of the file's contents.
    """
    mtime = agent_transcript_mtime(agent_id)
    if mtime is not None and mtime > started:
        return mtime
    return started


def stale_agents(session, now=None):
    """Every agent this session spawned that has been INACTIVE past
    STALE_AFTER with no manifest row, most-quiet-first. Returns (agent_id,
    seconds quiet, dead, started), where quiet is time since last_activity()
    above, not time since the agent started, dead is True once that silence
    has passed DEAD_AFTER, and started is the marker's own timestamp, so a
    caller can look up the job that agent was given without recomputing the
    start time from "now minus quiet" and drifting a little from the real
    marker.

    Built on unfinished_agents() above, the one scan of the start markers
    and the manifest; this function adds the activity check and the
    STALE_AFTER filter on top of it.
    """
    import time as _time
    when = _time.time() if now is None else now
    out = []
    for agent_id, started in unfinished_agents(session, now=when):
        quiet = when - last_activity(agent_id, started)
        if quiet <= STALE_AFTER:
            continue
        out.append((agent_id, quiet, quiet > DEAD_AFTER, started))
    out.sort(key=lambda row: -row[1])
    return out


def delegation_path():
    return tmp_dir() / "densepack-delegation.jsonl"


def append_delegation(entry):
    """One permanent row per subagent spawn, written by brief_pack.py before
    the spawn happens, so the file exists even when the brief never packs.
    Never drained: nothing deletes a line from it. Sealed, because the
    readers keep only sealed rows; see sealed_rows()."""
    entry = dict(entry, seal=_row_seal(entry))
    with delegation_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def pending_path():
    return tmp_dir() / "densepack-pending.jsonl"


def pending_entries():
    """Every row bash_pack.py has appended, in file order. Read fresh every
    call rather than cached, because the file can gain a row between two
    calls in one session.

    A row without this machine's seal is dropped, the same rule as
    drain_queue(): a cloned project could commit a row naming its own image
    inside .claude, and read_gate.py would put that image in front of the lead.
    With no key at all nothing could be sealed, so every row is kept."""
    return sealed_rows(pending_path())


# The sessions allowed to collect report pointers. SessionStart adds its own
# id here; a subagent never fires SessionStart, so a subagent is never on the
# list and cannot take the lead's images. It is a LIST because a project is
# often open in two windows at once: a single slot meant the second window to
# start silently switched the first one off. Ten is far more than anyone runs
# and keeps the file from growing.
LEADS_FILE = "densepack-lead-sessions.json"
LEADS_KEPT = 10


def read_leads():
    """Every session allowed to collect, newest last. The older single-id
    file still counts, so an upgrade mid-session does not lose the lead."""
    out = []
    path = tmp_dir() / LEADS_FILE
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                out = [str(v) for v in data if isinstance(v, (str, int))]
        except (json.JSONDecodeError, OSError):
            out = []
    old = tmp_dir() / "densepack-lead-session"
    if old.is_file():
        try:
            one = old.read_text(encoding="utf-8").strip()
            if one and one not in out:
                out.append(one)
        except OSError:
            pass
    return out


def add_lead(session_id):
    leads = [s for s in read_leads() if s != str(session_id)]
    leads.append(str(session_id))
    leads = leads[-LEADS_KEPT:]
    write_text_atomic(tmp_dir() / LEADS_FILE, json.dumps(leads))
    # The old single-id file is kept in step, so a downgrade still works.
    write_text_atomic(tmp_dir() / "densepack-lead-session", str(session_id))
    return leads


OFF_FLAG = "densepack-off"
QUIET_FLAG = "densepack-quiet"  # receipts quiet, the default. dpctl.py reads it.


def off_flag_path(session=None):
    """The off switch file one session writes, densepack-off-<session id>.

    A project open in two windows shares one .claude/tmp, so one bare
    switch file set in either window would stop packing in both, and the
    other window would go on paying full price with nothing on screen to
    say why. The name carries the session for the same reason
    read_lead_models() is a map and LEADS_FILE is a list, which is that
    one project runs in more than one window.

    With no session id in hand the bare name comes back, and that is
    deliberate. dpctl.py run from a terminal speaks for no window, and an
    on-against-off test wants the whole project stood down.
    """
    session = str(session or "").strip()
    if not session:
        return tmp_dir() / OFF_FLAG
    return tmp_dir() / ("%s-%s" % (OFF_FLAG, session))


def _off_file_set(session):
    """True when a session id is known and its own off file is on disk."""
    session = str(session or "").strip()
    return bool(session) and (tmp_dir() / ("%s-%s" % (OFF_FLAG, session))).exists()


def disabled(session=None):
    """The off switch, for clean on-against-off token tests.

    Create the file .claude/tmp/dense-off-<session id> and every hook in
    that session stands down: no instructions injected, no packing, no
    receipts. Delete the file and the plugin is back. No settings edit and no
    restart, so an A B test is two runs of the same task with the flag flipped
    between them. /dense-off writes the flag, /densepack removes it.

    A bare densepack-off with no session on it stops every session. A file
    with no session attached cannot be read as belonging to one, so it
    stops them all. dpctl.py on deletes any bare file it finds, so one left
    behind cannot outlive a /densepack.

    A subagent's hook events name the session that owns the agent, not the
    agent, so a lead that stands itself down stands its agents down with it.

    An event that names no session at all falls through to the session the
    last event named, and then to lead_session(), which is the resolution the
    reader already uses.

    A project whose .claude or .claude/tmp is a link stands every hook down:
    each write would land in the folder the link points at.
    """
    if through_link(project_dir(), tmp_dir()):
        return True
    if (tmp_dir() / OFF_FLAG).exists():
        return True
    if session is not None:
        return _off_file_set(session)
    return _off_file_set(_EVENT_SESSION) or _off_file_set(lead_session())


# The control settings behind the slash commands. One JSON file, defaults
# filled in when it is missing or partial, unknown values ignored so a
# hand-edited file can never crash a hook.
#
#   receipts   default: one 6 column table per batch of agents, plus a batch
#                       totals row at the bottom of that same table when
#                       the totals setting is on.
#              verbose: the arithmetic split into columns, a Dimensions column,
#                       a table per agent that returned several images, and
#                       the totals row's model line spelled out in full.
#              light:   the same 6 column table with no totals row at all,
#                       whatever the totals setting holds.
#              quiet:   no table in the response. The hook files the table and
#                       tells the lead to show it only if the user asked.
#              Image pointers always deliver, they are function, not reporting.
#   totals     Governs the CONVERSATION TOTALS row only, never the BATCH
#              TOTALS row above it, which prints in every default and
#              verbose table regardless of this setting.
#              auto: the mode decides, wrap-up only in default, every response
#              in verbose. on: every response. off: wrap-up only. Never
#              applies to light or quiet, which show no totals row in any
#              state.
#   keep       off, images, reports, or both: which files keep_copy() copies
#              into this conversation's vault folder as each agent finishes.
#              keep_folder (default <project>/densepack-archive) is used only
#              by keep_promote(), which dpctl.py's keep verb calls.
SETTINGS_FILE = "densepack-settings.json"
#   stylecard  on: every reply and every Write or Edit is held to the writing
#              rules. prompt_card.py never reads this setting.
#              off: the default. The checks stand down. Leave it off on a
#              machine that already runs the same card as a personal hook in
#              ~/.claude/hooks, where two copies would arrive twice.
#
# There is deliberately no setting for the standing reminder itself. It states
# what a condensed image is, and that is what makes the delivery mechanism
# legible. A user who could switch that off while packing kept running would
# get images with nothing explaining them. /dense-off is the only switch
# that stops it, and it stops everything.
#
# receipts defaults to quiet. A table in the lead's context on every batch is
# paid for in the prefix of every later turn.
SETTINGS_DEFAULTS = {"receipts": "quiet",
                     "totals": "auto", "keep": "both", "keep_folder": "",
                     # stylecard defaults to off: the writing check is opt-in.
                     "reader": "auto", "stylecard": "off",
                     "maxpack": "on",
                     "vault_mb": VAULT_CAP_MB}
SETTINGS_ALLOWED = {"reader": ("auto", "fable", "opus", "sonnet"),
                    "stylecard": ("on", "off"),
                    "maxpack": ("on", "off"),
                    "receipts": ("default", "verbose", "light", "quiet"),
                    "totals": ("auto", "on", "off"),
                    "keep": ("off", "images", "reports", "both")}

# Older words for the receipts setting. full was the measured table, line was
# one line of totals, off was silence, so each maps onto one of the four
# modes. The alias keeps old settings files working.
RECEIPTS_ALIASES = {"full": "verbose", "line": "default", "off": "quiet"}


def settings(session=None):
    """Every setting in force. session is accepted and not used yet.

    The per session layer lives in read_session_settings() and is not wired
    in here. See SCOPED_SETTINGS above.
    """
    out = dict(SETTINGS_DEFAULTS)
    path = tmp_dir() / SETTINGS_FILE
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        # Valid JSON is not always an object. A hand-edited [] or null must
        # mean defaults, never a crash in every hook.
        if not isinstance(data, dict):
            data = {}
        # OPEN, for the author to decide. This file sits in the project, so a
        # clone can commit one, and a committed vault_mb of 0 makes the plugin
        # trim its own kept copies while "quiet" hides every later pack.
        # Sealing the file closes that and was measured to work, and it also
        # makes every hand-written settings file inert, which four test files
        # and any tooling rely on. See docs/PUBLISH-2026-09-15-0437.md.
        for key, allowed in SETTINGS_ALLOWED.items():
            value = data.get(key)
            if key == "receipts" and isinstance(value, str):
                value = RECEIPTS_ALIASES.get(value, value)
            if isinstance(value, str) and value in allowed:
                out[key] = value
        folder = data.get("keep_folder")
        # The settings file sits in the project, so a cloned project can
        # plant it. The keep folder therefore stays a path inside the project.
        # A leading slash is its own test: since Python 3.13 ntpath.isabs is
        # False for "/Users/x", and joining it onto the project keeps the
        # drive and replaces the root, which lands anywhere on that drive.
        # A NUL raises ValueError in mkdir, which no caller catches.
        if (isinstance(folder, str) and not os.path.isabs(folder)
                and not folder.startswith(("/", "\\")) and "\x00" not in folder
                and not Path(folder).drive and ".." not in Path(folder).parts):
            out["keep_folder"] = folder
        # The vault cap is a number, not a word from a list, so the loop above
        # cannot carry it.
        cap = data.get("vault_mb")
        if isinstance(cap, int) and not isinstance(cap, bool) and cap >= 0:
            out["vault_mb"] = cap
    return out


def write_settings(changes):
    merged = settings()
    merged.update(changes)
    on_disk = merged
    # A new file of its own, then moved onto the name. os.replace replaces a
    # committed link instead of writing through it to the file it points at.
    import tempfile
    fd, part = tempfile.mkstemp(dir=str(tmp_dir()), prefix=".densepack-settings-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(on_disk, indent=2))
        # Retried: on Windows a replace onto a file another hook holds open
        # raises, and a slash command must not fail on that.
        if not replace_retry(part, tmp_dir() / SETTINGS_FILE):
            Path(part).unlink(missing_ok=True)
    except OSError:
        Path(part).unlink(missing_ok=True)
        raise
    return merged


def vault_dir(session_id=None):
    """The automatic copy folder, one subfolder per conversation.

    .claude/tmp is scratch and a new session deletes what is old in it. An
    image handed to an agent that never opened it, or a report nobody read
    before the session ended, is data gone. This folder is the copy that
    survives, and the subfolder is named by the conversation so a user can
    match it to the conversation and pull a report back out.
    """
    base = project_dir() / ".claude" / VAULT_DIRNAME
    if session_id is None:
        return base
    return base / (str(session_id) if session_id else "no-session-id")


# Anything a shell would act on inside a double-quoted word, and the
# characters that would end a line of plugin prose.
SHELL_META = set("`$\"'<>|&;()!*?[]{}~\n\r")


def quoted_path(text):
    """A path that stays usable inside a double-quoted shell word.

    Only the backtick, the dollar sign, the double quote, the backslash and a
    line break act inside double quotes, so only those go. Brackets, braces,
    a tilde and a space are literal there, and a Windows path holds them:
    "Program Files (x86)" must still name the file the reader asked for.
    """
    out = str(text).replace("\\", "/")
    return "".join("_" if ch in "`$\"\n\r" else ch for ch in out)


def no_metacharacters(text):
    """A path or name the reader can still use, with nothing a shell acts on.

    A project names its own files, and a deny message that spells a path into
    a command would otherwise hand the reader `cat "notes-$(id).md"` to run.
    Separators become forward slashes, which Windows and the Read tool both
    accept, and every other shell character becomes an underscore.
    """
    out = str(text).replace("\\", "/")
    return "".join("_" if ch in SHELL_META else ch for ch in out)


def clear_link(path):
    """Remove any link at this name before anything writes to it.

    A project can plant a name the plugin writes as a symbolic link, a
    junction or a second hard link, and the write lands in the file it
    shares. A hard link is a real directory entry, so only the link count
    tells it from an ordinary file. densepack.clear_link() calls this, and so
    does every writer that cannot move a new file onto the name instead.
    """
    name = str(path)
    try:
        if os.path.islink(name) or is_junction(name):
            if os.path.isdir(name) and not os.path.islink(name):
                os.rmdir(name)
            else:
                os.unlink(name)
            return
        if os.path.isfile(name) and os.stat(name).st_nlink > 1:
            os.unlink(name)
    except OSError:
        pass


BASH_FIRST_KEY = "CLAUDE_CODE_THRIFTY_SONIC"


def bash_first_off(enable=True):
    """Set, or with enable=False clear, CLAUDE_CODE_THRIFTY_SONIC=0 in the
    env block of ~/.claude/settings.json. True when the file changed.

    Auto mode and bypassPermissions mode inject a message that tells Claude
    to read files with cat, head or sed in Bash, and a Bash read stays text.
    The variable at 0 stops that message; Bash itself stays available.
    Proved 16 September 2026: an auto mode session with it set carries no
    auto_mode attachment in its transcript. A value the user set is kept,
    a file with a BOM is left alone because Claude Code then ignores the
    whole file, and nothing is written when the file does not parse.
    """
    import json
    path = Path.home() / ".claude" / "settings.json"
    try:
        raw = path.read_bytes() if path.is_file() else b"{}"
        if raw.startswith(b"\xef\xbb\xbf"):
            return False
        data = json.loads(raw.decode("utf-8") or "{}")
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or not isinstance(data.get("env", {}), dict):
        return False
    env = data.get("env", {})
    if enable:
        if BASH_FIRST_KEY in env:
            return False
        env[BASH_FIRST_KEY] = "0"
    else:
        if env.get(BASH_FIRST_KEY) != "0":
            return False
        del env[BASH_FIRST_KEY]
    data["env"] = env
    path.parent.mkdir(parents=True, exist_ok=True)
    return write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def write_text_atomic(path, text):
    """Write text to a new file in the same folder, then move it onto `path`.

    A plain write follows whatever sits at the name: a symbolic link, a
    junction or a second hard link, all of which a project can plant, and the
    bytes land in the file it shares. os.replace puts a new file in place of
    the name instead, so nothing is written through a link.
    """
    import tempfile
    folder = os.path.dirname(os.path.abspath(str(path))) or "."
    part = None
    try:
        # Inside the try: a folder that is missing or unusable raises here,
        # and every other failure in this function answers False.
        fd, part = tempfile.mkstemp(dir=folder, prefix=".densepack-write-")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        if not replace_retry(part, path):
            Path(part).unlink(missing_ok=True)
            return False
    except OSError:
        if part:
            Path(part).unlink(missing_ok=True)
        return False
    return True


def replace_retry(src, dst, tries=40, wait=0.05):
    """os.replace, retried while Windows holds the destination open.

    Python's open() passes no FILE_SHARE_DELETE, so a replace onto a file
    another hook is reading raises PermissionError. densepack.py carries the
    same helper for images; this one is for the small state files."""
    import time as _time
    for attempt in range(tries):
        try:
            os.replace(str(src), str(dst))
            return True
        except PermissionError:
            if attempt == tries - 1:
                return False
            _time.sleep(wait)
        except OSError:
            return False
    return False


def pair_seal(src, names):
    """The seal over one source-text file and EVERY image of its pack.

    Image 1 alone is not enough: the gates hand the reader every image of the
    pack, so a project that commits image 2 would have it delivered inside a
    pack the plugin vouches for."""
    return _row_seal({"pair_src": os.path.basename(str(src)),
                      "pair_images": [str(n) for n in names]})


def seal_pair(src, names):
    """Record the text and image pack this machine's plugin wrote."""
    if isinstance(names, str):
        names = [names]
    names = [os.path.basename(str(n)) for n in names]
    seal = pair_seal(src, names)
    if seal is None:
        return
    write_text_atomic(Path(str(src) + ".seal"),
                      json.dumps({"images": names, "seal": seal}))


def sealed_pack(src):
    """Every image name sealed for this source text, in order, or none."""
    import hmac
    try:
        raw = Path(str(src) + ".seal").read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        rec = json.loads(raw)
    except ValueError:
        # 0.4.41 wrote a bare HMAC over one image name. A pack already on
        # disk keeps being served, rather than being converted a second time.
        old = sibling_image(src)
        if old is None:
            return []
        name = os.path.basename(old)
        want = _row_seal({"pair_src": os.path.basename(str(src)),
                          "pair_image": name})
        if want and hmac.compare_digest(want, raw.strip()):
            return [name]
        return []
    if not isinstance(rec, dict):
        return []
    names = rec.get("images")
    # Bare names only: a name carrying a folder, a drive or a parent step
    # would reach outside the folder the source text sits in.
    if not (isinstance(names, list) and names and all(
            isinstance(n, str) and n and os.path.basename(n) == n
            and n not in (".", "..") and ":" not in n for n in names)):
        return []
    want = pair_seal(src, names)
    if want is None or not (isinstance(rec.get("seal"), str)
                            and hmac.compare_digest(want, rec["seal"])):
        return []
    return names


def pair_sealed(src, image_name):
    """True when this machine's plugin wrote the pair.

    A cloned project can commit a text file and an image under .claude/tmp
    with the packers' own names, and a Read of that text would otherwise be
    swapped for the project's image, which can show other words."""
    return os.path.basename(str(image_name)) in sealed_pack(src)


def is_junction(path):
    """True for a Windows junction, on every Python the hooks run on.

    os.path.isjunction arrived in 3.12 and run_hook.sh accepts 3.10, where a
    junction would otherwise read as a plain folder and every link guard in
    this plugin would pass it. The reparse tag tells a junction from a cloud
    storage placeholder, which is also a reparse point and is not a link.
    """
    if hasattr(os.path, "isjunction"):
        return os.path.isjunction(path)
    import stat as _stat
    try:
        tag = os.lstat(path).st_reparse_tag
    except (OSError, ValueError, AttributeError):
        return False
    return tag == getattr(_stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)


def through_link(root, path):
    """True when `path`, or a folder between `root` and `path`, is a symbolic
    link or a Windows junction. A cloned project can commit a vault folder
    as a link to the home folder, and every delete or copy in the vault would
    then reach the files it points at, so those callers refuse such a path."""
    # normcase on both sides: abspath does not fold case, and a root and a
    # path that differ only in the drive letter would end the walk at once
    # and miss every link below.
    root = os.path.normcase(os.path.abspath(str(root)))
    p = os.path.normcase(os.path.abspath(str(path)))
    while len(p) > len(root) and p.startswith(root):
        if os.path.islink(p) or is_junction(p):
            return True
        p = os.path.dirname(p)
    return False


def vault_cap_bytes():
    try:
        return int(settings().get("vault_mb", VAULT_CAP_MB)) * 1024 * 1024
    except (TypeError, ValueError):
        return VAULT_CAP_MB * 1024 * 1024


def vault_folders():
    """Every conversation folder in the vault, oldest first, with its size.

    Skips the install-state folders: instructions/, the drop folders,
    to-draw/ and images/. instructions/ holds the rules images bootstrap.py
    makes at session start; to-draw/ is the standing folder a user copies a
    file into to have it converted, and images/ is where the converted
    images land. They are install state, not a conversation's working copy,
    and must survive the cap eviction below the same way prune_old_files()
    already leaves them alone.
    """
    base = vault_dir()
    # A cloned project can commit the vault, or .claude, as a link to any
    # folder, and vault_trim() deletes what this list returns.
    if not base.is_dir() or through_link(project_dir(), base):
        return []
    out = []
    for folder in base.iterdir():
        if not folder.is_dir() or through_link(base, folder):
            continue
        if folder.name in ("instructions", "drop", "drops", "drop-gate",
                           "to-draw", "images"):
            continue
        size = 0
        newest = 0.0
        for f in folder.rglob("*"):
            if f.is_file():
                try:
                    stat = f.stat()
                except OSError:
                    continue
                size += stat.st_size
                newest = max(newest, stat.st_mtime)
        out.append((newest, folder, size))
    out.sort()
    return out


def vault_trim(keep_session=None):
    """Delete whole conversation folders, oldest first, until the vault fits
    under its cap. Whole folders, never single files, so what survives is
    always a complete conversation. The conversation running right now is
    never deleted."""
    import shutil
    rows = vault_folders()
    total = sum(size for _t, _f, size in rows)
    cap = vault_cap_bytes()
    # The newest folder is the conversation in progress. It is never deleted,
    # whatever the cap says and whatever the caller passes, because dpctl.py
    # trims the moment the cap changes and knows no session id of its own.
    newest = rows[-1][1].name if rows else None
    removed = []
    for _t, folder, size in rows:
        if total <= cap:
            break
        if folder.name == newest:
            continue
        if keep_session and folder.name == str(keep_session):
            continue
        try:
            shutil.rmtree(folder)
        except OSError:
            continue
        total -= size
        removed.append(folder.name)
    # Every other folder is gone and the vault is still over. One conversation
    # on its own can do that: the folder in progress was skipped above and
    # nothing else was left to delete.
    #
    # The oldest files inside that folder go, in pairs, so an image and the
    # words beside it leave together and a surviving image always still has
    # its source text. Reported separately from the folders, because losing
    # part of a live conversation is a different event from retiring an old
    # one.
    if total > cap and newest:
        folder = vault_dir(newest)
        files = []
        for path in sorted(folder.glob("*")):
            if not path.is_file():
                continue
            try:
                files.append((path.stat().st_mtime, path))
            except OSError:
                continue
        files.sort()
        for _when, path in files:
            if total <= cap:
                break
            try:
                size = path.stat().st_size
                path.unlink()
            except OSError:
                continue
            total -= size
            removed.append("%s/%s" % (newest, path.name))
    return removed


def keep_copy(session_id, images=(), texts=()):
    """Copy packed images and their source text into the vault.

    Runs on every pack, in both directions, whatever the keep setting is:
    the keep setting chooses what a user KEEPS permanently, and this is the working
    copy the plugin falls back on. Costs disk and no tokens, because nothing
    it writes enters the conversation.

    A copy failure never breaks delivery: the caller's work is already done.
    """
    import shutil
    folder = vault_dir(session_id)
    if through_link(project_dir(), folder):
        return None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for path in list(images) + list(texts):
            if path and Path(path).is_file():
                shutil.copy2(path, folder)
    except OSError:
        return None
    vault_trim(keep_session=session_id)
    return folder


def keep_promote(session_id):
    """Copy one conversation's vault folder into the keep folder, which
    nothing deletes automatically. dpctl.py's keep verb calls it.
    Returns the destination, or None when that conversation is not in the
    vault."""
    import shutil
    src = vault_dir(session_id)
    if not src.is_dir() or through_link(project_dir(), src):
        return None
    conf = settings()
    base = (project_dir() / conf["keep_folder"] if conf["keep_folder"]
            else project_dir() / "densepack-archive")
    if through_link(project_dir(), base):
        return None
    dest = base / str(session_id)
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, dest)
    except OSError:
        return None
    return dest


def receipts_mode():
    """The quiet flag predates the settings file and still wins: it was the
    documented off switch for receipts, and a user who set it must not start
    seeing tables because a newer file disagrees."""
    if (tmp_dir() / "densepack-quiet").exists():
        return "quiet"
    return settings()["receipts"]


def totals_shown():
    """True when the CONVERSATION TOTALS row belongs under this batch's
    table, alongside the BATCH TOTALS row that prints regardless of this
    setting.

    Default mode holds the whole conversation's own totals row back for the
    wrap-up, verbose prints it every time, and the totals setting on or off
    overrides the mode either way. Quiet and light print no totals row of
    any kind, so this answer never reaches them.
    """
    choice = settings()["totals"]
    if choice == "on":
        return True
    if choice == "off":
        return False
    return receipts_mode() == "verbose"


def status_shown():
    """False. The reply carries no status table."""
    return False


def read_event(raw=None):
    """The hook event on stdin, with the session it names put in hand.

    The off switch is per session, so a hook reads the event first and
    passes the session id it finds to disabled().

    raw, when given, is stdin already read as text. pointer.py's cheap
    PostToolUse exit has to peek at stdin for a TaskStop tool call before it
    knows whether there is anything to do, so it reads stdin once itself and
    hands the text here instead of this function reading a second time from
    a pipe the first read already drained.
    """
    if raw is None:
        # Windows pipes hook stdin as cp1252 unless told otherwise, which turns
        # every UTF-8 quote in a report into mojibake that then gets baked
        # into the image. Found by reading a packed image, not by a crash,
        # because cp1252 decodes anything without complaint.
        try:
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
        try:
            event = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            return {}
    else:
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
    if not isinstance(event, dict):
        return {}
    # The event's cwd is remembered FIRST, before note_lead_model touches
    # tmp_dir(), so the very first disk access already resolves against the
    # session's own folder rather than this process's working directory.
    note_event_cwd(event)
    note_event_session(event)
    # Every hook event names the session transcript, and the lead's model sits
    # on its first assistant line. Recording it here means no hook has to
    # remember to, and the plugin never has to be told which model reads its
    # images. Written once per session, under that session's own id.
    #
    # A session that has been stood down records nothing at all, which is what
    # the switch promises. The id was put in hand one line above, so the
    # question can be asked here without reading another session's answer.
    if not disabled(event.get("session_id")):
        note_lead_model(event)
    return event


def emit(payload):
    """Print a hook's JSON output with the same encoding discipline as the input."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    print(json.dumps(payload))


def ensure_pillow():
    """Make Pillow importable, from the plugin data dir if the bootstrap put it there.

    Returns True when PIL imports. A False means every hook degrades to doing
    nothing, which is the correct failure mode: text still flows, nothing breaks.
    """
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        pylibs = Path(data) / "pylibs"
        if pylibs.is_dir():
            sys.path.insert(0, str(pylibs))
    try:
        import PIL  # noqa: F401
        import freetype  # noqa: F401  the glyph backend; without it the image is not the benched one
        import numpy  # noqa: F401  codepack.py blends each glyph into the image with it
        return True
    except ImportError:
        return False


_SEAL_KEYS = {}


def seal_key():
    """The seal key, read from disk once per process and home folder.

    sealed_rows() seals every row it reads, and the manifest holds thousands:
    reading the key file for each row made one table take seconds."""
    try:
        home = str(Path.home())
    except Exception:  # noqa: BLE001
        return None
    if home not in _SEAL_KEYS:
        key = _load_seal_key()
        if key is None:
            return None
        _SEAL_KEYS[home] = key
    return _SEAL_KEYS[home]


def _load_seal_key():
    """32 random bytes kept in ~/.claude/densepack-state, outside the project,
    made once per machine. None when that folder cannot be written.

    One fixed folder, not CLAUDE_PLUGIN_DATA: bash_pack.py runs inside the
    Bash tool's shell, which has no CLAUDE_PLUGIN_DATA, and it must seal with
    the same key the hooks check."""
    try:
        home = Path.home()
        if not home.is_absolute():
            return None
        folder = home / ".claude" / "densepack-state"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "sidecar.key"
    except Exception:  # noqa: BLE001
        return None
    for _attempt in range(2):
        try:
            key = path.read_bytes()
        except OSError:
            key = None
        if key is not None and len(key) == 32:
            return key
        if key is not None:
            # A key file of the wrong size is broken; make it again.
            try:
                path.unlink()
            except OSError:
                return None
        # The bytes go into a file of this process's own, which then links
        # onto the key's name in one step. A process that dies midway leaves
        # no empty key, and two processes racing keep the one that linked first.
        tmp = path.with_name("sidecar.key.%d.%s" % (os.getpid(), os.urandom(4).hex()))
        try:
            # 0600: only this user reads the key.
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(os.urandom(32))
            try:
                os.link(tmp, path)
            except FileExistsError:
                pass
            except OSError:
                # A file system with no hard links. rename refuses an existing
                # name on Windows; elsewhere the first key is read back below.
                if not path.exists():
                    os.rename(tmp, path)
        except OSError:
            return None
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return None


def _row_seal(entry):
    """An HMAC over one queue row. A cloned project cannot compute it, so a
    row it commits never reaches the reader as the plugin's words."""
    import hashlib
    import hmac
    key = seal_key()
    if not key:
        return None
    body = json.dumps({k: v for k, v in entry.items() if k != "seal"}, sort_keys=True)
    return hmac.new(key, body.encode("utf-8"), hashlib.sha256).hexdigest()


def sealed_rows(path):
    """jsonl_rows() keeping only the rows this machine's plugin wrote.

    A cloned project can commit any of these files under .claude/tmp, and a
    row it wrote would reach a receipt, a table or an image list as the
    plugin's own. With no key nothing can be sealed, so no row is kept: a
    hook environment that moves the home folder must not turn the seal off.
    The plugin then falls back to text, which loses a saving and no words."""
    import hmac
    out = []
    for row in jsonl_rows(path):
        if not isinstance(row, dict):
            continue
        want = _row_seal(row)
        if want is None:
            continue
        if (isinstance(row.get("seal"), str)
                and hmac.compare_digest(want, row["seal"])):
            out.append(row)
    return out


def append_queue(entry):
    entry = dict(entry, seal=_row_seal(entry))
    with queue_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def totals_path():
    return tmp_dir() / "densepack-totals.json"


def read_totals():
    path = totals_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_totals(totals):
    write_text_atomic(totals_path(), json.dumps(totals))


def drain_queue():
    path = queue_path()
    if not path.is_file():
        return []
    # With no key every row below is dropped, and draining would delete the
    # file that holds them. The rows stay on disk for a session that has a
    # key again, and the packers stand down meanwhile.
    if seal_key() is None:
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        # A row with no valid seal was not written by this machine's plugin.
        # With no key nothing can be sealed, so no row is kept: a hook
        # environment that moves the home folder must not turn the seal off.
        import hmac
        want = _row_seal(row)
        if want is None:
            continue
        if (isinstance(row.get("seal"), str)
                            and hmac.compare_digest(want, row["seal"])):
            entries.append(row)
    path.unlink(missing_ok=True)
    return entries


# What one extra lead turn costs, in the cache write tokens the pack compare
# is priced in. A packed Bash output or report reaches the lead as a pointer,
# and the lead spends a Read turn opening the picture. That turn re-reads the
# whole context at the cache read rate and writes one short call.
#
# Claude Code writes the one hour cache at 2x input. A cache read is 0.1x
# input on every model except Fable 5.1 and Mythos 5.1, where it is 0.025x.
# So against one write token a read is 0.05, or 0.0125 on Fable, and an
# output token, 5x input, is 2.5. The five minute multipliers, 1.25x and
# 0.08, do not apply.
#
# The Read call that opens a picture writes about 150 output tokens, and the
# tool result carrying the pointer costs about 185 tokens beyond the
# pointer's own characters.
READ_OVER_WRITE = 0.05
FABLE_READ_OVER_WRITE = 0.0125
OUT_OVER_WRITE = 2.5
READ_CALL_OUTPUT_TOKENS = 150
TOOL_RESULT_WRAP_TOKENS = 185
# A plain claude -p leg's first turn prefix, used when the transcript cannot
# be read.
CONTEXT_WHEN_UNKNOWN = 59863


def context_tokens(session_id, tail_bytes=400000, path=None):
    """The tokens this session re-reads on its next turn: the last assistant
    usage's input, cache read and cache write added up. 0 when unknown.
    DENSEPACK_CONTEXT_TOKENS in the environment states it outright: the
    test suites run the scripts with no transcript on disk, and a benchmark
    can pin the context it measures at. path names another transcript to
    read, a subagent's own, in place of the session's."""
    stated = os.environ.get("DENSEPACK_CONTEXT_TOKENS", "").strip()
    if stated.isdigit():
        return int(stated)
    path = path or transcript_path(session_id)
    if path is None:
        return 0
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            fh.seek(max(0, size - tail_bytes))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return 0
    for line in reversed(tail.splitlines()):
        try:
            message = json.loads(line).get("message") or {}
        except (ValueError, AttributeError):
            continue
        usage = message.get("usage")
        if isinstance(usage, dict) and message.get("role") == "assistant":
            return int(usage.get("input_tokens") or 0) \
                + int(usage.get("cache_read_input_tokens") or 0) \
                + int(usage.get("cache_creation_input_tokens") or 0)
    return 0


def turns_so_far(session_id, tail_bytes=2000000, path=None):
    """Assistant messages in this session's transcript so far, 0 when unknown."""
    stated = os.environ.get("DENSEPACK_TURNS_SO_FAR", "").strip()
    if stated.isdigit():
        return int(stated)
    path = path or transcript_path(session_id)
    if path is None:
        return 0
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            fh.seek(max(0, size - tail_bytes))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return 0
    ids = set()
    for line in tail.splitlines():
        if '"role":"assistant"' in line or '"role": "assistant"' in line:
            try:
                message = json.loads(line).get("message") or {}
            except (ValueError, AttributeError):
                continue
            if message.get("id"):
                ids.add(message["id"])
    return len(ids)


def read_turn_fee(session_id, actor=None):
    """Write rate tokens a picture must save before the Read turn that opens
    it is paid for. Sized from the session's own context, then divided by
    what the later turns give back: every later turn re-reads the picture
    in place of the text at the read rate, and the turns still to come are
    taken as the turns run so far. Without that divisor a lead deep in a
    long session refuses to pack a report it then re-reads many times."""
    # A pack made for a subagent is opened by that agent, so its own
    # transcript sets the fee; actor is its agent id.
    path = agent_transcript(actor) if actor else None
    context = context_tokens(session_id, path=path)
    if not context and not os.environ.get("DENSEPACK_CONTEXT_TOKENS", "").strip().isdigit():
        context = CONTEXT_WHEN_UNKNOWN
    try:
        reader = actor_reader(actor) if actor else resolved_reader(session_id)
    except Exception:  # noqa: BLE001
        reader = None
    read_share = FABLE_READ_OVER_WRITE if reader == "fable" else READ_OVER_WRITE
    fee = context * read_share + READ_CALL_OUTPUT_TOKENS * OUT_OVER_WRITE
    return int(fee / (1 + turns_so_far(session_id, path=path) * read_share))


# Dollars a million tokens, input and output. A cache write is 2.0 x input,
# because Claude Code writes one hour entries, and a cache read 0.1 x input.
RATES = {"fable": (10.0, 50.0), "opus": (5.0, 25.0), "sonnet": (2.0, 10.0), "haiku": (1.0, 5.0)}
# A report's image costs about half its text in tokens.
IMAGE_OVER_TEXT = 0.5
POINTER_TOKENS = 60
# The agent's second reply when it complies with the pointer line: the line
# and a little thought. When it refuses and repeats its report the cost is
# the whole report again.
AGENT_REPLY_TOKENS = 100


def rates_for(model):
    name = str(model or "").lower()
    for key, pair in RATES.items():
        if key in name:
            return pair
    return RATES["sonnet"]


def report_pack_worth(text_tokens, lead_model, lead_session, agent_model=None, agent_transcript=None):
    """Whether packing a subagent's report pays, in dollars across two models.

    Packing costs the agent one more turn, its whole context re-read at its
    read rate plus a short reply, and costs the lead the Read turn that opens
    the picture. It saves the lead the text over the picture at the write
    rate once and at the read rate on every later turn, the turns to come
    taken as the turns run so far."""
    from pathlib import Path
    lead_in, lead_out = rates_for(lead_model)
    agent_in, agent_out = rates_for(agent_model or lead_model)
    saved_tokens = text_tokens * (1 - IMAGE_OVER_TEXT) - POINTER_TOKENS
    if saved_tokens <= 0:
        return False
    lead_ctx = context_tokens(lead_session)
    if not lead_ctx and not os.environ.get("DENSEPACK_CONTEXT_TOKENS", "").strip().isdigit():
        lead_ctx = CONTEXT_WHEN_UNKNOWN
    turns = turns_so_far(lead_session)
    agent_ctx = 0
    if agent_transcript and not os.environ.get("DENSEPACK_CONTEXT_TOKENS", "").strip().isdigit():
        agent_ctx = context_tokens(lead_session, path=Path(agent_transcript))
    saving = saved_tokens * (2.0 * lead_in + turns * 0.1 * lead_in) / 1e6
    cost = ((agent_ctx * 0.1 * agent_in + AGENT_REPLY_TOKENS * agent_out)
            + (lead_ctx * 0.1 * lead_in + READ_CALL_OUTPUT_TOKENS * lead_out)) / 1e6
    return saving > cost
