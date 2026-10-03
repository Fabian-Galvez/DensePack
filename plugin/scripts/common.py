"""Shared helpers for the DensePack hooks.

Each hook script imports this file. It finds the project's scratch folder,
the queue file and the totals file, reads the event that Claude Code sends
on stdin, writes the answer, and finds Pillow in the plugin data folder. No
script runs this file directly.
"""

import json
import os
import re
import sys
from pathlib import Path

# /plugin install puts Pillow, freetype-py and NumPy in the plugin's data
# folder. Each hook imports this module. This module adds the folder to the
# path before a script imports the renderer. Without the folder, a Read hook
# on a new Linux install finds the system Pillow and no freetype-py. It then
# packs taller fallback images, and the model can misread them.
def _find_pylibs():
    """Returns the pylibs folder of the plugin's data folder, or "".

    The hooks get CLAUDE_PLUGIN_DATA. The slash commands run dpctl.py from the
    Bash tool, which gets no CLAUDE_PLUGIN_DATA and no CLAUDE_PLUGIN_ROOT. For
    those, the function looks where Claude Code keeps the data folder of this
    plugin: plugins/data/densepack-<marketplace> in the Claude Code config
    folder. Without this, a slash command on a computer whose Python has no
    Pillow of its own printed nothing."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        return os.path.join(data, "pylibs")
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    import glob
    found = [p for p in glob.glob(os.path.join(config, "plugins", "data", "densepack-*", "pylibs"))
             if os.path.isdir(p)]
    return max(found, key=os.path.getmtime) if found else ""


_PYLIBS = _find_pylibs()
if _PYLIBS and os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)

# The report floor counts characters, not lines. A report of a few very long
# lines passes a line count and still costs thousands of tokens.
#
# Each floor is the smallest source length where the image plus its pointer
# costs fewer tokens than the text, priced at CHARS_PER_TOKEN. The pointer is
# the route's own line. Each route has its own fee:
#
#   report route, subagent_stop.py. report_pointer() is 158 characters
#     plus the folder path, 66 tokens at the 2.40 divisor before the path.
#     Stub mode charges stub_pointer() instead. The live compare prices the
#     mode that ships. The pre-filter uses the shorter fee.
#   old bash route, now removed.
#     pointer_line() is 161 characters plus the folder path, 67 tokens at
#     the 2.40 divisor before the path. It contains the image name, the
#     folder and the exact-text file name and nothing else.
#
# A floor here only skips the conversion. Each route prices the real image
# against the real text before it ships. These constants can be low with no
# risk. They must never be high.
#
# The floor is flat. The image and its pointer stay in the conversation
# prefix, the same as the text they replace. Each turn pays for the image
# plus the pointer, or for the text. The one Read that opens the image costs
# tokens once and amortizes over the session. The compare does not include
# it.
# Packing saves tokens when
#
#     image_tokens + pointer_tokens < text_tokens
#
# and that condition does not depend on the turn count. The floor cannot
# reach zero, because the pointer is itself text in the prefix. Content
# smaller than its pointer never saves tokens.
#
# The fee does not include a cache read of a whole turn, because the saving
# repeats each turn. The fee does not divide by the turns elapsed, because
# the model reads the pointer again each turn, the same as the image and
# the text.
#
# One floor applies to all models, because each model gets the same image.
STUB_CHARS = 194


def stub_chars():
    """Returns the smallest report worth sending to a file."""
    return STUB_CHARS


# The brief floor. The fee is the pointer that brief_pack.py builds from
# POINTER and TEXT_NOTE. It is 208 characters plus the image path and the
# text path, 87 tokens at the 2.40 divisor before the paths. It is higher
# than the report and bash pointers because a brief's pointer IS the
# replacement prompt that the agent gets. When brief_pack moves a code
# block to a separate code file, it adds the text of that file to the fee.
# The pre-filter runs before that step and does not count that text. It uses
# the low fee, and a wrong guess costs one discarded conversion.
#
# The floor is 1,000 characters. A model that gets a brief image below that
# length can fail the task. It can break the gate, transcribe its own brief,
# or search for a legend file. A brief below 1,000 characters costs about
# 250 tokens as text.
BRIEF_FLOOR = 1000


def brief_chars(px=None):
    """Returns the smallest brief worth packing. One floor applies to all
    glyph sizes."""
    return BRIEF_FLOOR


# CODE_PX is the one glyph size for all images and all models. It is the
# glyph in image pixels. The code does not scale the image after hinting,
# and the model sees the glyph at this size. backend_text() gets the glyph
# from FreeType at this size, and FreeType hints it at the same size.
#
# font.scale_x makes each glyph narrower than its size. A larger size then
# gives more x-height, and the row keeps its width. space.row_px fixes the
# row height, and the band height does not increase with the glyph.
#
# DENSEPACK_CODE_PX overrides CODE_PX. The size is not a style key, and
# DENSEPACK_STYLE cannot change it. A style for one glyph size makes a
# different image at another size, because each width scale in a style
# matches one glyph size. The override is not a per-model setting. All
# models get this one number.
CODE_PX = int(os.environ.get("DENSEPACK_CODE_PX") or 17)

FONT_SIZE = CODE_PX
READER_SIZES = {"fable": CODE_PX, "opus": CODE_PX, "sonnet": CODE_PX}


def font_size():
    """Returns the pixel size of all images. One size applies to all
    models."""
    return CODE_PX


def code_size(px=None, reader=None):
    """Returns the pixel size of the code renderer, CODE_PX, for all models.

    The function accepts the two arguments and ignores them. A caller that
    passes them keeps working.
    """
    return CODE_PX


# The models that get an image, keyed by the word in the Agent tool's `model`
# field. Each value is CODE_PX. A model whose name is not a key here does not
# read condensed images reliably. DensePack sends that model plain text. An
# unreadable brief costs the whole task, and the saving is not worth that
# cost. size_for_model() and reader_key_for_model() read the dict this way.
#
# Haiku 4.5 is not in this dict. Haiku with no prior context scores 1 of 10
# on a condensed report, and it does not answer UNREADABLE. A caller cannot
# tell a bad read from a good one.
MEASURED_MODELS = {"fable": CODE_PX, "opus": CODE_PX, "sonnet": CODE_PX}

VAULT_DIRNAME = "densepack-vault"

# The disk space that the vault can use before the trim deletes the oldest
# conversation folders. 200 MB holds about ten thousand packed reports at
# about 19 KB each, far more than one run needs. The vault_mb setting
# changes it.
VAULT_CAP_MB = 200


def size_for_model(model, lead_size=None):
    """Returns the pixel size for a brief to this model. Returns None when
    the model is not in MEASURED_MODELS. That model gets plain text.

    `model` is the Agent tool's model field. It is often absent, because a
    subagent with no model inherits the parent's model. An absent model
    means the lead's own size, and lead_size gives that size.
    """
    if model is None or model == "":
        return lead_size if lead_size else font_size()
    name = str(model).lower()
    for key, px in MEASURED_MODELS.items():
        if key in name:
            return px
    return None


def reader_key_for_model(model, lead_reader=None):
    """Returns the reader key, fable, opus or sonnet, for a model name.
    Returns None when the model gets no image. It works like
    size_for_model, but returns the MEASURED_MODELS key in place of a pixel
    size.

    An absent model means the caller inherits the lead's reader key, which
    lead_reader gives. size_for_model uses the same absent-model rule.
    """
    if model is None or model == "":
        return lead_reader if lead_reader else resolved_reader()
    name = str(model).lower()
    for key in MEASURED_MODELS:
        if key in name:
            return key
    return None


def agent_type_model(subagent_type):
    """Returns the model that an agent definition sets, or None when it sets
    none.

    The Agent tool's model field comes first when it is set. When it is not
    set, a custom agent type can set a model in its own frontmatter, and that
    model comes before the lead's model. The function reads
    .claude/agents/<type>.md, where Claude Code keeps agent definitions. A
    missing file is not an error. Most agent types come with Claude Code and
    set no model.
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

# The reader key that resolved_reader() returns when the lead has no
# recorded model, or a model that matches no key in READER_SIZES. Each model
# gets the same image. This value only names a model that gets an image.
UNKNOWN_READER = "opus"


def _model_from_transcript(path, skip_sidechain=False):
    """Returns the model named on the first assistant line of transcript
    `path`. Returns None when the file is missing or unreadable, or names no
    model.

    note_lead_model() and event_reader() call this function.
    note_lead_model() passes skip_sidechain True to get the LEAD's own line,
    even when a subagent's turn sits between lead lines in the same
    transcript. event_reader() does not skip sidechain rows. A subagent's own
    transcript file marks all its rows isSidechain, and a skip there finds
    nothing.
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
                # Claude Code 2.1.288 writes an attachment that names the
                # model before the first assistant line. At the first tool
                # call of a session, it is the only line that names it.
                attachment = row.get("attachment")
                if not found and isinstance(attachment, dict) \
                        and attachment.get("type") == "model":
                    found = (attachment.get("identity") or {}).get("modelId")
                if found:
                    return str(found)
    except OSError:
        return None
    return None


def read_lead_models():
    """Returns all recorded lead models, keyed by session id.

    The code cannot match a name with no session to the calling session. A
    file that holds one bare model name gives an empty map here, and the
    hook detects the model again. It is a MAP, not one slot, because a
    project is often open in two windows at the same time. LEADS_FILE below
    holds a list for the same reason.
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
    """Writes the map to its file. It keeps the newest sessions and drops the
    oldest."""
    kept = dict(list(models.items())[-LEADS_KEPT:])
    try:
        (tmp_dir() / LEAD_MODEL_FILE).write_text(json.dumps(kept),
                                                 encoding="utf-8")
    except OSError:
        return


def note_lead_model(event):
    """Records the lead's model the first time a hook event names its
    transcript, keyed by the id of the session that sent the event. It costs
    one write per session and one lookup after that. A failure leaves the
    session unrecorded, and resolved_reader uses its fallback."""
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
    """Returns the session id whose lead model applies to the work running
    now.

    A hook event names the session that sent it, and a lead's own event
    names the lead. A subagent's event names the subagent, which records no
    model of its own. The newest id on the leads list then applies to it.
    dpctl.py reports on the same id. Each id here belongs to a session that
    reached SessionStart. The session running now cannot get the model of a
    finished session.
    """
    leads = read_leads()
    if not leads:
        return _EVENT_SESSION or ""
    if _EVENT_SESSION and _EVENT_SESSION in leads:
        return _EVENT_SESSION
    # A script that runs inside the Bash tool has no hook event. Claude Code
    # exports the window's own id into that environment. dpctl.py's
    # caller_session() reads the same id. Without this check, a script run
    # that way returns leads[-1], the model of another window.
    env_session = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if env_session and env_session in leads:
        return env_session
    return leads[-1]


def lead_model_name(session=None):
    """Returns the model name recorded for one session, or "" when there is
    none.

    It never returns the name of another session. A name recorded with a
    different id belongs to that session, not this one. For a session with
    no recorded name, the function reads that session's own transcript, the
    same detection that note_lead_model() does. A caller with no hook event,
    such as dpctl.py, then gets the model of the running session and not an
    old name left on disk.
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

# The settings that apply to one window only. All other settings in
# densepack-settings.json keep one value for the whole project.
#
# The test is what a wrong value costs another window on the same project.
#
#   reader     Scoped. It names the model profile for one window. A wrong
#              reader value is the most expensive error in the plugin.
#              Only brief_pack.py reads the per-window value, through
#              reader_override(). resolved_reader() reads the value for the
#              whole project from settings().
#   receipts   Global. It prints a savings table in the reply and costs a
#              few tokens. Receipts that are on in one window print in each
#              window of the project.
#   totals     Global. One more row in the same table that receipts prints.
#   stylecard  Global. It is the writing standard for the project. The
#              plugin applies it to each reply and each Write. One project
#              has one standard, not one per window.
#   keep       Global. It archives images and report text to disk. No model
#   keep_folder  sees it, and no run spends tokens on it.
#   vault_mb   Global. A disk cap for this project's vault. It is a
#              maintenance setting.
SCOPED_SETTINGS = ("reader",)


def read_session_settings():
    """Returns all scoped settings set by hand, keyed by the session that set
    them.

    A slash command writes one word into densepack-settings.json, and that
    file is one file for the whole project. All other windows on the same
    project and all later conversations read a word that one window sets in
    that file. It is a MAP for the same reason as read_lead_models(). A
    project is often open in more than one window.

    The function drops a word that is not allowed for its setting. A hand
    edited file then cannot set a value that the commands reject.
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
    """Returns True when densepack-session.json exists on disk, whether or
    not it names the calling session.

    A project that never set a scoped setting has no such file. In that
    project the reader value in the flat settings() applies to the whole
    project, and a spawn with an absent model inherits it. When the file
    exists in a project, the reader value in the flat settings() is an old
    value from the window that set it last. It is never a fact about a
    session absent from the map. brief_pack.py must not use it for such a
    session.
    """
    return (tmp_dir() / SESSION_FILE).is_file()


def session_settings(session=None):
    """Returns the settings that one session set for itself, or {} when it
    set none.

    Only a session that names itself gets a result. This function does not
    use the newest lead, unlike lead_model_name() above, because a wrong
    result costs different amounts for the two lookups. A model name from
    the wrong session still gives the right size in most cases, because the
    windows on one project usually run the same model. A setting set by hand
    is the one case where the value is NOT the session's default. A session
    that did not set the value must not get it. This map exists to prevent
    that fault. An unknown session gets the default. For the reader setting
    the default is auto, which reads that session's own lead model.
    """
    session = str(session if session else _EVENT_SESSION or "").strip()
    if not session:
        return {}
    return read_session_settings().get(session, {})


def reader_override(session=None):
    """Returns the reader profile that one session set, or "" when it set
    none."""
    return session_settings(session).get("reader", "")


def event_reader(event):
    """Returns the reader profile, fable, opus or sonnet, for the agent that
    sent THIS event. The function reads it from the transcript that the
    event names. Returns None when the transcript is unreadable or names an
    unmeasured model. A caller must not guess.

    resolved_reader() returns the LEAD's profile, from the lead model that
    note_lead_model() records once per session. It is correct for the
    lead's own tool calls and wrong for a subagent's. A PreToolUse Agent
    event has no field that names the model of the new subagent.

    A subagent's Read event does NOT contain that subagent's own
    transcript_path. It contains the lead's. actor_reader() below calls
    this function ONLY when the event's own transcript_path is the actor's
    own file. For all other subagent events, it uses Claude Code's
    agent-<id>.meta.json.
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
# transcript while Claude Code writes it. When the read comes first,
# event_reader() returns None. actor_reader() writes the reader profile to
# this record the first time it finds the model of an agent. A later hook
# on that SAME agent's own events reads this record. It does not derive the
# profile again from a transcript that Claude Code does not always flush in
# time.
#
# actor_key() below gives the key for each agent. The key is never
# event["session_id"]. A SubagentStart event contains session_id,
# transcript_path, cwd, prompt_id, agent_id, agent_type and hook_event_name.
# Its session_id is the SPAWNING session, and all agents of that session
# share it.
AGENT_MODEL_FILE = "densepack-agentmodel-%s"


def transcript_key(event):
    """Returns the filename stem of this event's own transcript_path, or
    None.

    It is the one identifier that names THIS event's own caller and nothing
    shared. The AGENT_MODEL_FILE note above says why session_id cannot
    replace it on a SubagentStart event."""
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
    """Returns the key that names THIS event's own subagent, or None for the
    lead.

    The key is "agent-<agent_id>", the same stem that Claude Code gives
    that agent's own transcript. The record in AGENT_MODEL_FILE and the
    later Read events of that agent then use one name. The transcript stem
    alone does not work. A SubagentStart event contains the LEAD's
    transcript_path as often as the new agent's own. One file can then hold
    one model for all agents of the session.

    It returns None for the lead, which has no agent_id. The lead uses
    event_reader() on its own transcript, which names its own model. The
    function never returns a session id. One agent's record then cannot set
    the reader profile of another agent.
    """
    if not isinstance(event, dict):
        return None
    agent_id = event.get("agent_id")
    if agent_id:
        return "agent-%s" % agent_id
    stem = transcript_key(event)
    return stem if stem and stem.startswith("agent-") else None


def record_agent_model(key, reader_key):
    """Writes the reader profile of an agent, keyed by its own transcript
    stem. actor_reader() calls it the first time it finds the model of an
    agent. A write failure is silent, the same failure mode as each gate in
    this folder. The caller that reads the record treats a missing file as
    unknown and uses its own fallback. It never crashes."""
    if not key or not reader_key:
        return
    try:
        (tmp_dir() / (AGENT_MODEL_FILE % key)).write_text(
            reader_key, encoding="utf-8")
    except OSError:
        pass


def agent_model(key):
    """Returns the reader profile that record_agent_model() wrote for this
    transcript stem. Returns None for no key, for a session that started
    before this code existed, or for a spawn with an unreadable model. It
    never guesses and never uses resolved_reader(), the LEAD's own
    profile. A caller with no record here uses its own fallback."""
    if not key:
        return None
    path = tmp_dir() / (AGENT_MODEL_FILE % key)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    # Only a name in MEASURED_MODELS passes. drop_read_gate.py joins the
    # result into a folder path. record_agent_model() is the only writer. A
    # caller gets only the values that record_agent_model() writes.
    return value if value in MEASURED_MODELS else None


def is_subagent(event):
    """Returns True when a subagent sent this event, not the lead.

    A subagent's PreToolUse contains the LEAD's session_id and the lead's
    transcript_path. Neither field separates the two. agent_id and
    agent_type name the real actor. Empty or absent fields mean the lead.
    An actor that this check cannot identify gets the lead's treatment.
    """
    if not isinstance(event, dict):
        return False
    return bool(event.get("agent_id")) or bool(event.get("agent_type"))


def actor_reader(event=None, key=None):
    """Returns the reader profile for the agent that sent THIS event, or
    None. None means MAKE NO IMAGE AND SEND PLAIN TEXT.

    The result has one meaning for all callers. None covers two cases that
    get the same treatment. One is an actor that runs a model outside
    MEASURED_MODELS, such as haiku. The other is an actor that the code
    cannot identify. The code must not guess in either case.

    For the lead, which has no agent key, the function returns
    event_reader() on the transcript that the event names. It does not use
    resolved_reader() or UNKNOWN_READER.

    For a subagent, the function checks five sources, in this order. It
    returns the first result that is a key in MEASURED_MODELS.

    | Source | Why it comes in this place |
    | --- | --- |
    | The record in AGENT_MODEL_FILE, through agent_model() | One file read, and it names this one agent. An earlier call of this function wrote it |
    | Claude Code's agent-<id>.meta.json, through agent_meta_model() | Claude Code writes this file at spawn. The code checks it first, but the current meta.json contains no model, and this source then gives nothing |
    | The agent's own transcript, agent-<id>.jsonl, through _agent_own_model() | It names the model on the agent's first reply. It gives nothing before that reply is on disk |
    | The spawn log of brief_pack.py, through _spawned_model() | It matches the agent type and the description from meta.json. For a spawn that named no model, it gives the lead's model |
    | This event's own transcript, through event_reader() | Only when transcript_path is this agent's own file, because a subagent's PreToolUse contains the LEAD's transcript_path |

    When source 2, 3 or 4 gives a result, the function writes it to the
    record. The search of the project folders then runs once per agent.

    It returns None when all five fail. An unmeasured model leaves no
    record, reader_key_for_model() returns None for it, and a caller must
    send plain text.
    """
    if key is None:
        key = actor_key(event)
    if not key:
        # The lead. Its own event contains its own transcript_path.
        return event_reader(event) if event is not None else None
    found = agent_model(key)
    if found:
        return found
    agent_id = key[len("agent-"):]
    # reader_key_for_model(None) returns the LEAD's reader profile, from
    # lead_reader or resolved_reader(). The loop below calls it only with a
    # model name. Claude Code's meta.json no longer contains a model. The
    # agent's own transcript and the spawn log come after it.
    for named in (agent_meta_model(agent_id), _agent_own_model(agent_id),
                  _spawned_model(agent_id, event)):
        found = reader_key_for_model(named) if named else None
        if found:
            # The code writes the result to the record. The next Read by
            # this same agent is then one file read and not another walk of
            # all project folders.
            record_agent_model(key, found)
            return found
    if event is not None and transcript_key(event) == key:
        return event_reader(event)
    return None


def _agent_own_model(agent_id):
    """Returns the model that this subagent's own transcript,
    agent-<id>.jsonl, names on its first reply. Returns None before that
    reply is on disk."""
    path = agent_transcript(agent_id)
    return _model_from_transcript(path) if path else None


def _spawned_model(agent_id, event):
    """Returns the model that the Agent call for this subagent named. The
    function reads the spawn log that brief_pack.py writes and matches the
    agent type and the description that Claude Code records in
    agent-<id>.meta.json. A spawn that named no model inherits the lead's,
    and the function returns the lead's model. Returns None when no row
    matches."""
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
    """Returns the pixel size of an image for this actor. Returns None when
    this actor must get plain text. See actor_reader()."""
    reader = actor_reader(event, key)
    if not reader:
        return None
    return READER_SIZES.get(reader)


def reader_gets_images(reader):
    """Returns True when this reader profile gets images.

    Fable and Opus always get images. Sonnet gets images while the maxpack
    setting is on. Haiku, all other models and None get text. Type /max-off
    to send Sonnet text.
    """
    if reader == "sonnet":
        return settings().get("maxpack") == "on"
    return reader in ("fable", "opus")


def lead_gets_images(session=None):
    """Returns True when the lead of this session gets images.

    A lead whose model has a name that matches no reader profile, such as
    Haiku, gets text. A lead with no known model also gets text.
    """
    name = lead_model_name(session).lower()
    # A lead with no known model gets text. Haiku and other models that no
    # test measured must never get images, and an unknown name can be one
    # of them. A reader setting other than "auto" names the model itself.
    if not name and settings().get("reader", "auto") == "auto":
        return False
    if (name and settings().get("reader", "auto") == "auto"
            and not any(key in name for key in READER_SIZES)):
        return False
    return reader_gets_images(resolved_reader(session))


def gets_images(event):
    """Returns True when the agent that sent this event gets images."""
    if is_subagent(event):
        return reader_gets_images(actor_reader(event))
    return lead_gets_images((event or {}).get("session_id"))


def agent_meta_model(agent_id):
    """Returns the real model that Claude Code recorded for this agent id at
    spawn time. The function reads it from the agent's own
    agent-<id>.meta.json. stopped_by_user() reads a different field,
    stoppedByUser, from the same file. Returns None when the id is empty,
    the file is missing, or the file names no model. The function searches
    all projects with the same glob as stopped_by_user(), because the id
    alone does not name the project that spawned the agent."""
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
    """Returns the agent type and description that Claude Code recorded for
    this agent id at spawn time. The function reads them from the same
    agent-<id>.meta.json as agent_meta_model(). Returns (None, None) when
    the id is empty or the file is missing.

    _spawned_model() matches the spawn log of brief_pack.py on these two
    fields. A hook event of the agent contains no prompt text, and a read of
    the agent's live transcript for that text can come before Claude Code
    writes the text.
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


# All identity cards that a lead can name in a brief. brief_pack.py records
# the named card with record_card(). A name outside this tuple is unknown,
# and record_card() writes no row for it.
CARDS = ("worker", "check", "reader", "runner")
DEFAULT_CARD = "worker"

# One file per spawning session, one line per Agent call.
CARD_FILE = "densepack-card-%s.jsonl"

# The line that a lead writes to name a card. The line contains the word
# card, then the name, and nothing else. The anchors prevent the word card
# inside a sentence from choosing a role.
CARD_LINE = re.compile(
    r"^[ \t>*-]*card[ \t]*[:=]?[ \t]+([A-Za-z][A-Za-z0-9_-]{0,15})[ \t]*$",
    re.MULTILINE)


def card_in_text(text):
    """Returns the card name that a brief gives, or None when the brief
    names none.

    The last matching line applies. A lead that corrects itself writes the
    correction below the first line. The function skips a name outside
    CARDS. When no name is in CARDS, it returns None, and record_card()
    then writes no row.
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
    """Returns the path of the card record for one spawning session."""
    return tmp_dir() / (CARD_FILE % (str(session_id or "none")[:8],))


def record_card(session_id, prompt_id, agent_type, description, card):
    """Appends this spawn's card name to the session's card record.

    brief_pack.py calls this at PreToolUse, the one point where the raw
    brief is still readable. updatedInput REPLACES the prompt with a
    pointer. A brief below the pack threshold makes brief_pack.py return at
    an even earlier point.

    prompt_id names the lead turn of the Agent call, and agent_type names
    the helper. claim_card() matches on that pair, because the two fields
    are on the SubagentStart event itself. The function also writes the
    description. claim_card() uses it as the closer match when it can read
    it.
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
    """Removes this spawn's card from the session's card record and returns
    it. Returns None when no entry matches.

    The function removes the entry when it reads it. Two spawns of one
    agent type in one turn then get the two cards that their briefs named,
    in the order that the lead wrote them.

    Why the description is not the key. Claude Code writes
    agent-<id>.meta.json while the SubagentStart hook runs.
    agent_meta_fields() can then read nothing, and the spawn can get the
    worker card that its brief did not name. prompt_id and agent_type are
    on the event, and neither can arrive late. The function still prefers
    the description when it arrives in time, because it separates two
    spawns of one agent type inside one turn.
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
    """Returns the modification time of this agent's own transcript,
    agent-<id>.jsonl. Claude Code appends to that file on each turn of the
    subagent. The glob root is the same as in agent_meta_model() and
    stopped_by_user(), because the transcript is in the same subagents
    folder next to the .meta.json file, with the same key. The function
    searches all projects, because the id alone does not name the project
    that spawned the agent.

    The caller uses it as the progress signal. It is a stat() call on one
    file, never a read of its contents. A poll needs one fact, whether the
    agent wrote something since the last check, and the mtime gives that
    fact. Returns None when the id is empty or the file is missing.
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


# last_touched_file() below reads only the last 200,000 bytes of a
# transcript. A stall report needs the most recent tool call, never an
# earlier one. A transcript can be larger than a hundred megabytes. A full
# read to find the last line is too slow for a poll. 200,000 bytes holds
# thousands of lines, far more than one agent writes between two tool calls.
TRANSCRIPT_TAIL_BYTES = 200_000

# The tool names whose input contains a file_path that this project counts
# as "this agent touched a file". NotebookEdit is not in this list, because
# the code has no test data for its input. An untested name can make the
# code read a key that the tool does not have.
FILE_TOOLS = ("Write", "Edit")


def last_touched_file(agent_id):
    """Returns the most recent file that this agent wrote or edited, and the
    time, as (path, unix seconds). The values come from the last Write or
    Edit tool call in its own transcript. Returns (None, None) when the
    file is missing or names no such call. The function reads only
    TRANSCRIPT_TAIL_BYTES from the end of the file. It assumes that newer
    lines follow a call from the middle of a long run, which is the normal
    case. The caller uses this function only on the rare stalled path,
    never on each wake.
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
    """Returns True when a Write or Edit tool call is in this session's own
    transcript.

    It checks for an edit in the CURRENT session, not in a subagent's. It
    uses transcript_path and FILE_TOOLS in place of a new per-session state
    file, because the transcript already contains this fact.
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


# THE SONNET BURST. A Sonnet turn with a few images gets a reply of a few
# hundred output tokens. The same turn with many images can get a reply of
# thousands. Output costs five times the input rate. Past that point the
# images cost more money than the input they saved.
#
# The limit does not depend on patches alone or on count alone. Fewer,
# larger images give less output than many short ones, and a few very large
# images give the most. The cap needs the two bounds. The bytes of a turn
# are the bound that the gate can read before it converts a file.
#
# A turn is inside the cap when it contains BURST_CAPS reads or fewer AND
# their source bytes total BURST_BYTES or fewer. A turn outside the cap gets
# text for ALL its files. A few images next to many text files is a turn
# that does the work of the two modes, and the images save nothing there.
#
# Opus and Fable have no cap, because a cap on either model discards a real
# saving.
BURST_CAPS = {"sonnet": 32}
# The byte budget for one turn. It allows a turn of thirty-two large source
# files, about 656,000 bytes, because the hooks of one turn do not all read
# the whole batch.
BURST_BYTES = 700_000


def burst_cap(model):
    """Returns the largest number of packed images that one turn can give
    this reader profile. Returns None when the profile has no cap."""
    return BURST_CAPS.get(str(model or "").strip().lower())


def over_cap(paths, cap, budget=BURST_BYTES):
    """Returns True when this turn's batch is too wide to pack. The batch
    has more files than the cap or more source bytes than the budget. A
    file with an unreadable length counts as zero bytes. A name whose file
    is gone then never caps a turn alone.

    One file read alone is never over the cap, whatever its length. Each turn
    that burst in the measurements contained several images. The
    measurements did not include a single large file. A limit with no
    measurement is a guess."""
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
    """Returns this subagent's own transcript file, agent-<id>.jsonl, or
    None. The glob root is the same as in agent_transcript_mtime(). The
    function searches all projects for one id, because the id alone does
    not name the project that spawned the agent."""
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


# A wait for the batch does not work. The hooks of a wide batch start before
# the whole assistant message is on disk. The message does not stream at a
# steady rate. The Read blocks of one message can reach the disk seconds
# apart. A quiet window short enough to cost a lone Read nothing ends inside
# those gaps. A window long enough to cover the gaps delays each Read for
# most of a minute.
def turn_reads(event):
    """Returns all files that the running assistant message reads, in
    order, and that message's id, as (paths, id).

    Claude Code writes each content block of an assistant message to the
    transcript as its own line, and all these lines have one message id. A
    PreToolUse hook can then read the batch of its own Read. The gate can
    count the images of the turn before it packs the first one. Claude Code
    writes the lines while the reply streams, and the tools start before
    the last line reaches the disk. An early hook counts only the part of
    its batch that is on disk. See the note above. Claude Code appends the
    results of finished tools after those lines. This function walks
    backward past them to the last assistant line and then counts only the
    blocks with that id.

    A subagent's PreToolUse contains the LEAD's transcript_path. The
    function reads a subagent's own agent-<id>.jsonl in its place. A count
    of the lead's batch for a subagent's Read can cap a turn with one
    image.

    Returns ([], "") when the transcript is unreadable. No caller then gets
    a cap.
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
    """Returns True for the first caller that names `key` in this session,
    and False after that.

    It uses an exclusive create. The hooks of one batch run at the same
    time, and only one of them gets True. The caller uses it to write one
    receipt row for a whole capped turn, not one row for each read in it.
    """
    marker = tmp_dir() / ("densepack-cap-%s" % re.sub(r"[^A-Za-z0-9_-]", "",
                                                      str(key))[:64])
    try:
        os.close(os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except OSError:
        return False
    return True


def queue_cap_row(event, model, reason, chars):
    """Queues the receipt row for a turn that the image cap sent as text.
    The row has the same shape as the row of subagent_stop.py's
    queue_text_row(): no images, no saving and no cost. pointer.py then
    prints the reason in the place of an image's price. It does not add the
    row to the run total or to the receipt debt, which counts packed rows
    only."""
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
    """Returns the active reader profile, which is the model of the lead.

    `session` names one session explicitly. When it is None,
    lead_model_name() uses lead_session().

    A reader value in densepack-settings.json overrides the lead model. The
    function reads that value through settings(), which is one file for
    the whole project. The value then applies to all sessions of the
    project, not only to the session that set it. This function does not
    read the per-session values of read_session_settings(). brief_pack.py
    reads those through reader_override(). The default is "auto". With
    "auto", the function reads the model that note_lead_model() recorded
    for the session. A model that matches no key in READER_SIZES gives
    UNKNOWN_READER. A session with no recorded model and no transcript also
    gives UNKNOWN_READER.
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
    """Returns True when the last typed line contains `phrase`.

    All gates without a text field use this escape check. The Read tool has
    no field for a sentence, unlike Bash's command or Agent's prompt. A
    phrase that deactivates a gate must then come in the conversation and
    not in the call. This function walks the session's own transcript from
    the end. It stops at the first line that is a real typed message and
    not a tool result. A tool result's content is a list of blocks with no
    "text" block in it. The search skips it and keeps walking backward. An
    unreadable transcript is not proof of the phrase. The function then
    returns False, and the gate stays active.
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
    """Returns this session's own transcript file, or None.

    Claude Code writes one per session in ~/.claude/projects, in a folder
    named after the project path with each separator replaced by a dash.
    The function finds the folder by a listing and does not build that name
    again. The case of the drive letter differs between the two, and a
    rebuilt name does not match.
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
    """Returns the cost of one more turn for this session, in tokens, or
    None.

    Claude Code sends the whole conversation at the start of each turn. A
    Read call to open a packed image is one more send of the whole
    conversation. The last usage record in the transcript contains that
    number.

    The open of an image is the expensive half of packing. Each Read turn
    sends the whole conversation again. This number is what the lead pays
    to open one image.
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
    """Returns the line that names this batch's report images for a lead.

    It is short on purpose. The line stays in the prefix of each later
    turn, and each extra word costs tokens on each of those turns. It names
    the folder, the image names and the exact-text file, and nothing else.
    """
    return ("DensePack: %d report image(s) in %s, named "
            "densepack-img-<agent id>-1.png. Each IS that agent's report. "
            "Its exact text is densepack-src-<agent id>.txt beside it."
            % (image_count, folder))


def stub_pointer(image_count, folder):
    """Returns the line that a lead gets when all reports in the batch are
    stubs.

    pointer.py sends this line, not report_pointer(), when no report in the
    batch is prose, which is the normal case. It is 281 characters before
    the folder path, and report_pointer() is 158, because it also says that
    the stubs are summaries and names the manifest.

    subagent_stop.py charges this text for a stub report. The receipt then
    prices the line that the lead gets. Two copies of one line exist, and
    the receipt must price the one that ships.
    """
    return ("DensePack: %d report image(s) ready in %s, named "
            "densepack-img-<agent id>-1.png. The stubs above are summaries "
            "only. Each image IS the full report. Its exact text is "
            "densepack-src-<agent id>.txt beside it. Timings and sizes per "
            "agent are in densepack-manifest.jsonl beside the images."
            % (image_count, folder))


# THE REPORT SWAP. A foreground agent returns its report as the Agent tool
# result. subagent_stop.py packs a long report at the agent's first stop and
# writes one swap file for that agent. report_swap.py, a PostToolUse hook on
# the Agent tool, then puts the swap line in the result in place of the
# report. On the block route, which a background agent still takes, the
# stop hook blocks the agent and asks it to reply with the marker line.
# That reply is one more model request, and it reads the agent's whole
# context again. The swap line is the same marker line, and the lead gets
# the same result, receipt and Read path on the two routes.
#
# The names start with densepack-report-, and bootstrap.py prunes them with
# the report files after KEEP_HOURS. report_swap.py deletes a swap file when
# it reads it. The background flag stays until the prune.
REPORT_SWAP_FILE = "densepack-report-swap-%s.json"
REPORT_BACKGROUND_FILE = "densepack-report-background-%s"


def report_swap_path(agent_id):
    """Returns the swap file of one agent."""
    return tmp_dir() / (REPORT_SWAP_FILE % agent_id)


def report_background_path(agent_id):
    """Returns the flag that report_swap.py writes when the Agent result of
    this agent holds no report. A background agent returns its report
    later in a message, and no Agent result carries it. subagent_stop.py
    then keeps the block route for that agent."""
    return tmp_dir() / (REPORT_BACKGROUND_FILE % agent_id)


def report_swap_line(report_file):
    """Returns the line that the lead gets in place of the report. It is
    the marker line that the agent wrote on the block route, and
    stub_pointer() tells the lead what it means."""
    return "%s %s" % (MARKER, report_file)


def report_digest(text):
    """Returns a hash of the report text with all whitespace removed.
    report_swap.py compares the Agent result with the report that the stop
    hook packed. A result with other text, such as a note that the report
    arrived as a message, keeps its text. Claude Code can join text blocks
    with or without a newline, and the hash ignores that difference."""
    import hashlib
    return hashlib.sha256("".join(str(text or "").split()).encode(
        "utf-8", "replace")).hexdigest()


def agent_result_text(resp):
    """Returns the text of an Agent tool result, or None when it has no
    text. Claude Code puts the report in content as a list of text blocks.
    A plain string also counts."""
    content = resp.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    return "".join(str(block.get("text") or "") for block in content
                   if isinstance(block, dict) and block.get("type") == "text")


def swap_applies(resp, digest):
    """Returns True when report_swap.py puts the marker line in this Agent
    result. The result must be complete, and its text must be the report
    that the stop hook packed, with the hash `digest`.

    Claude Code can change the text before PostToolUse. It can put a note
    in front of a report that matched an instruction pattern, and it can
    change each control tag in it. It can also return only a note that the
    report came as a SubagentHandback message. The swap then misses. The
    test stays strict on purpose, because a swap removes the note of Claude
    Code. report_swap.py gives the counts.

    report_swap.py and pointer.py run on the same event at the same time,
    and neither can wait for the other. Each one runs this test, and the two
    agree on whether the swap happened."""
    if not isinstance(resp, dict) or resp.get("status") != "completed":
        return False
    got = agent_result_text(resp)
    return got is not None and isinstance(digest, str) and report_digest(got) == digest


def write_report_swap(agent_id, report_text, report_file, images=(), spawned_by=""):
    """Writes the sealed swap file of one agent. Returns True on success.

    report_swap.py accepts only a sealed file. A cloned project can commit
    a swap file in .claude/tmp, and without the seal its text reaches the
    lead as the result of an Agent call.

    The record also names the images of the pack and the session that
    started the agent. When the swap misses, report_swap.py marks those
    images delivered and writes a manifest row for that session."""
    record = {"agent_id": str(agent_id), "text": report_swap_line(report_file),
              "report": report_digest(report_text),
              "images": [str(p) for p in images],
              "spawned_by": str(spawned_by or "")}
    seal = _row_seal(record)
    if seal is None:
        return False
    record["seal"] = seal
    return write_text_atomic(report_swap_path(agent_id), json.dumps(record))


def take_report_swap(agent_id):
    """Returns the sealed swap record of one agent and deletes its file.
    Returns None when no file exists or its seal is not valid. The file is
    for one Agent result only. The function deletes it on each read."""
    import hmac
    path = report_swap_path(agent_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("agent_id") != str(agent_id):
        return None
    want = _row_seal(record)
    if want is None or not (isinstance(record.get("seal"), str)
                            and hmac.compare_digest(want, record["seal"])):
        return None
    return record


# THE LINE PULL. The model copies a long number, a hash or a path from the
# image when the image is clear. When the text is not clear, the model gets
# that one line from the text by its green line number, with a Read of
# offset N and limit 1. It never reads the whole file and never reads the
# image a second time. A Read with a limit this small passes all gates with
# no change, before a redirect to an image. The pull then costs one short
# tool result. The cap keeps it a pull and not a read of the file in parts.
LINE_PULL_MAX = 20


def line_pull(tool_input):
    """Returns True for a Read with a limit of LINE_PULL_MAX lines or
    fewer."""
    try:
        limit = int(tool_input.get("limit") or 0)
    except (TypeError, ValueError, AttributeError):
        return False
    return 0 < limit <= LINE_PULL_MAX


# The working directory that the current hook event named. project_dir()
# walks from the session's own folder and not from the working directory of
# this process. read_event() sets it before other code touches the disk. A
# headless worker can run with no CLAUDE_PROJECT_DIR and a working directory
# in the system Temp folder. Without this value the walk finds nothing,
# tmp_dir() makes a stray Temp\.claude, and each later worker in Temp uses
# it. The plugin's state then splits across two folders.
_EVENT_CWD = None

# The session id that the current event names. It works the same way as the
# cwd above, for the same reason. A hook reads one event and then calls
# plain functions that have no event to pass on. lead_session() reads it.
_EVENT_SESSION = ""


def note_event_cwd(event):
    """Stores the working directory that a hook event names, when it names
    one."""
    global _EVENT_CWD
    if not isinstance(event, dict):
        return
    cwd = event.get("cwd")
    if isinstance(cwd, str) and cwd and os.path.isdir(cwd):
        _EVENT_CWD = Path(cwd)


def note_event_session(event):
    """Stores the session that a hook event names, when it names one."""
    global _EVENT_SESSION
    if not isinstance(event, dict):
        return
    session = event.get("session_id")
    if isinstance(session, str) and session.strip():
        _EVENT_SESSION = session.strip()


def temp_shaped(folder):
    """Returns True for the system temp root itself and for its ancestors.

    A .claude AT the temp root belongs to no project. A worker that did not
    find its project made it, and a walk that uses it splits the plugin's
    state. Folders BELOW the temp root are not temp shaped, because real
    test sandboxes are there, and the walk must keep working for them.
    """
    import tempfile
    try:
        troot = Path(tempfile.gettempdir()).resolve()
        here = Path(folder).resolve()
    except OSError:
        return False
    return here == troot or here in troot.parents


def project_dir():
    """Hooks always get CLAUDE_PROJECT_DIR. dpctl run from a terminal does
    not always get it, and a terminal can open in a subfolder of the
    project. The function walks upward to find the folder. It starts from
    the working directory that the hook event named, when read_event() read
    one, and from this process's own working directory otherwise. The
    event's cwd is the session's. A worker process in a scratch folder then
    still gets the session's project.

    A .claude folder alone is the wrong marker. A repository whose tests
    make a .claude folder can stop the walk there, and no hook reads a
    settings file written there.

    The marker is LEAD_MODEL_FILE ("densepack-leadmodel") or
    "densepack-lead-session" in .claude/tmp. write_lead_models() writes the
    first file, and add_lead() writes the second. The first folder with one
    of these files is the folder that the hooks read. A folder with a
    .claude and no marker is the fallback. A first run before a session
    gets that fallback. With no .claude folder on the walk, the function
    returns the start folder.

    The function never accepts a temp shaped folder, with or without a
    marker. A .claude at the system temp root is the stray folder that the
    comment above note_event_cwd describes, not a project.
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
    """Returns a folder outside the project for state that the plugin reads
    later as its own.

    A cloned project can commit files in its own .claude folder. A file
    that the plugin reads as its own text is here instead. The folder is
    in CLAUDE_PLUGIN_DATA, or ~/.claude/densepack-state, in one
    subfolder per project, named by a hash of the project's path."""
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
    # project_dir() ends there has no project. The function returns the path
    # and does not make the folder. Each write then fails inside the
    # caller's own try block, and no action is the correct failure for a
    # worker with no project. The comment above note_event_cwd describes the
    # stray folder that this check prevents.
    if not temp_shaped(root):
        out.mkdir(parents=True, exist_ok=True)
    return out


def queue_path():
    return tmp_dir() / "densepack-queue.jsonl"


# All patterns that a packer here writes for a source-text file, each with
# the image name pattern built from the same id or stamp. Each pattern comes
# from the code that writes the file:
#   densepack-src-<agent id>.txt    beside densepack-img-<agent id>-1.png
#     (subagent_stop.py, the report's exact text)
#   densepack-report-<agent id>.txt beside densepack-img-<agent id>-1.png
#     (subagent_stop.py block-and-retry path, same agent id and image as
#     the src file)
#   densepack-bashsrc-<id>.txt      beside densepack-bash-<id>-1.png
#     (the old bash route)
#   densepack-briefsrc-<stamp>.txt  beside densepack-brief-<stamp>-1.png
#     (brief_pack.py, where the stamp itself contains hyphens)
# The list is in one place. A gate then cannot pair a source file with the
# wrong image because of a different copy of this list in another gate.
SOURCE_TO_IMAGE = (
    (re.compile(r"^densepack-src-([A-Za-z0-9]+)\.txt$"), "densepack-img-%s-1.png"),
    (re.compile(r"^densepack-report-([A-Za-z0-9]+)\.txt$"), "densepack-img-%s-1.png"),
    (re.compile(r"^densepack-bashsrc-([A-Za-z0-9]+)\.txt$"), "densepack-bash-%s-1.png"),
    (re.compile(r"^densepack-briefsrc-([A-Za-z0-9-]+)\.txt$"), "densepack-brief-%s-1.png"),
)


def sibling_image(path):
    """Returns the packed image next to a source-text file, or None.

    The function matches the file's OWN NAME against SOURCE_TO_IMAGE, never
    a bare "densepack-" prefix. A prefix match alone matches all plugin
    files, images and bookkeeping files too. That match checks a different
    fact than "a packed image already contains these words". The function
    returns the image's path only when that file exists on disk, in the
    same folder as the source file. A source file whose image the pack step
    rejected or never packed has no image to redirect to. The raw read is
    then the only source of the words.
    """
    text = str(path).replace("\\", "/")
    name = text.rsplit("/", 1)[-1]
    folder = Path(text).parent
    # The packers write these pairs only in .claude/tmp, and the keep setting
    # puts copies in the vault. A pair in another folder is a project's own
    # files. A project can pair harmless text with an image that shows other
    # text.
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
    """Returns all images of this source text's pack, in order, from the
    seal.

    SOURCE_TO_IMAGE names only image 1. A redirect that stops there gives
    the model one image of a long output and says nothing about the rest.
    The list comes from the sealed record and never from a folder listing,
    because a project can put a file named like image 2 next to a real
    pack.
    """
    folder = Path(str(src)).parent
    return [str(folder / name) for name in sealed_pack(src)
            if (folder / name).is_file()]


def sealed_sibling_image(path):
    """Returns sibling_image(), but only when the local plugin wrote and
    sealed the pair.

    A redirect gives the model the image in place of the text. A project
    that commits the two files in .claude/tmp can then make a Read of
    harmless words return an image that shows other words. The gates that
    only reject a raw read still use sibling_image(), because a rejection of
    a planted file is safe.
    """
    image = sibling_image(path)
    if image is None or not pair_sealed(path, Path(image).name):
        return None
    return image


# 22 minutes of no activity on the agent's own transcript. It is short
# enough to catch a stall in the same sitting, and long enough to not call a
# slow but working agent dead. last_activity() below reads it. It measures
# silence, not total run time.
STALE_AFTER = 1320.0

# The point where silence stops meaning "slow" and starts meaning "dead".
# Over 126 measured subagent runs, the median run took 3.0 minutes on Haiku,
# 7.2 on Sonnet, 11.3 on Fable and 15.1 on Opus. The longest run that
# finished took 48.2 minutes, on Sonnet. No finished agent was quiet this
# long and then continued. Silence past this point is stronger evidence of
# a crash than of a slow agent.
DEAD_AFTER = 48.2 * 60.0


def stopped_by_user(agent_id):
    """Returns True when Claude Code recorded a manual stop of this agent.

    Claude Code writes agent-<id>.meta.json next to each subagent
    transcript. The file is about 170 bytes and contains the agent type,
    the description and stoppedByUser. The current file has no model. When
    an agent returns nothing, this file says whether a manual stop ended
    it. A missing or unreadable file gives False, and the hook still
    reports a real silence.
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


# The case that stoppedByUser above does not cover. Claude Code sets that
# field only for a manual interrupt. A LEAD that stops one of its own
# background subagents with the TaskStop tool leaves no trace. No
# SubagentStop event fires, and agent-<id>.meta.json never gets
# stoppedByUser. Silence alone then marks that agent as dead.
#
# LIFECYCLE_FILE has one append-only jsonl row for each recorded point in a
# subagent's life. The hooks that already run at those points write the
# rows, and no new process has to start to keep the file. subagent_stop.py
# appends "ended". pointer.py is the one hook that Claude Code fires after
# each tool call, TaskStop included. It appends "stopped-by-lead" when the
# tool call was TaskStop. unfinished_agents() below reads the file next to
# stopped_by_user(). A stop by the lead then does not count as silence, the
# same as a manual stop.
#
# This file is not in bootstrap.py's PRUNE_PREFIXES. The prune never
# deletes densepack-manifest.jsonl next to it by age, because the manifest
# is "the record, not the working copy". This file is the same kind of
# record, and it grows the same way.
LIFECYCLE_FILE = "densepack-lifecycle.jsonl"


def lifecycle_path():
    return tmp_dir() / LIFECYCLE_FILE


def append_lifecycle(agent_id, event, lane=""):
    """Appends one row with the time, the agent, the event and the lane tag.

    The code never rewrites the file. A crash in a write then loses at most
    the row that it adds, the same append-only shape as the pending queue.
    A write failure is silent, the same failure mode as each marker write
    in this file. A lost lifecycle row is a smaller problem than a hook that
    stops working.
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
    """Returns the most recent lifecycle row for this agent id, or None.

    The caller reads it once per candidate, the same cost as
    stopped_by_user(), and never on the hot path that scans all live
    agents.
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
    """Returns True when the last recorded lifecycle event for this agent is
    a stop by the lead with the TaskStop tool.

    unfinished_agents() checks it next to stopped_by_user(). A stop that
    this plugin recorded explains the silence, and the silence is not a
    stall.
    """
    row = last_lifecycle_event(agent_id)
    return bool(row) and row.get("event") == "stopped-by-lead"


def jsonl_rows(path):
    """Returns all JSON lines in a file and skips a line that does not
    parse. A read failure returns an empty list. This function must never
    be the reason that a reply fails."""
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
    """Returns all agents that this session spawned and that have no
    manifest row yet, quiet or not, as (agent_id, started). started is the
    marker's own timestamp. The function does not sort by start time.
    Callers sort by the value that they measure.

    This is the shared scan for stale_agents() below, which needs only the
    agents quiet past STALE_AFTER. It is also the scan for each caller that
    needs the full live set to check when NONE are left. With one scan, the
    callers never get two different meanings of "still running".

    The function matches by the start marker, densepack-start-<agent id>,
    never by start time. A spawn row from PreToolUse contains no agent id.
    A pairing of that row with a finished run by timestamps pairs the wrong
    rows when two or more agents run at the same time. The marker contains
    the real agent id in its own filename. This function reads that id and
    never guesses a pairing.

    A manifest row for the id, whatever its state, means the agent reached
    SubagentStop at least once and is not silent. A provisional row from
    the first pass of the block-and-retry step in subagent_stop.py counts
    too. The function does not return a marker whose recorded session does
    not match, or that does not parse. It does not guess the session,
    because a wrong guess moves the alarm to the wrong agent.

    It also does not return a manually stopped agent. Claude Code's own
    record of that stop (stopped_by_user) explains the silence, and the
    silence is not a stall. In the same way, it does not return an agent
    that the LEAD stopped with the TaskStop tool. That fact comes from this
    plugin's own lifecycle record (stopped_by_lead), because Claude Code's
    own record covers only a manual interrupt.
    """
    out = []
    for agent_id, started in _spawned_without_report(session):
        # A manually stopped agent is not a silent one. This check comes
        # last, because it reads a file per candidate. The scan above
        # removes almost all markers before this check.
        if stopped_by_user(agent_id):
            continue
        if stopped_by_lead(agent_id):
            continue
        out.append((agent_id, started))
    return out


def user_stopped_agents(session):
    """Returns all agents that this session spawned, that Claude Code
    marked as manually stopped, and that never wrote a manifest row, as
    (agent_id, started).

    unfinished_agents() does not return these on purpose, and no stall report
    names them. No SubagentStop fires for a stopped agent, and no other
    code tells the lead. An interrupt of ONE lead tool call marks ALL
    background agents stoppedByUser at the same time. One rejected call can
    then stop several agents. A caller reads this once per agent and tells
    the lead.
    """
    return [(agent_id, started)
            for agent_id, started in _spawned_without_report(session)
            if stopped_by_user(agent_id)]


def _spawned_without_report(session):
    """The one scan for unfinished_agents() and user_stopped_agents().
    Returns each start marker of this session whose agent has no manifest
    row, as (agent_id, started), before a check of the stop records."""
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
            # A bare number is the older marker format, or a marker that
            # subagent_stop.py rewrote while an agent waits for the
            # block-and-retry step. Neither contains a session tag. Only a
            # manifest row in finished_ids above can claim this marker,
            # because that row shows its session. This code never guesses.
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
    """Returns the timestamp of the newest sign of activity for this agent.
    That is the mtime of its own transcript file when that file exists and
    is newer than started. Otherwise it is started itself.

    The check measures silence, not total run time. A working agent can
    run past STALE_AFTER on a long task, and that is not a stall. A
    transcript grows on each tool call and each message of the agent. Its
    mtime is the record of the last activity of this agent. One stat() call
    reads it, with no parse of the file's contents.
    """
    mtime = agent_transcript_mtime(agent_id)
    if mtime is not None and mtime > started:
        return mtime
    return started


def stale_agents(session, now=None):
    """Returns all agents that this session spawned that are INACTIVE past
    STALE_AFTER with no manifest row, the most quiet first. Each item is
    (agent_id, seconds quiet, dead, started). quiet is the time since
    last_activity() above, not the time since the agent started. dead is
    True when that silence is longer than DEAD_AFTER. started is the
    marker's own timestamp. A caller can then find the job of that agent
    without a new start time from "now minus quiet", which differs a little
    from the real marker.

    It uses unfinished_agents() above, the one scan of the start markers
    and the manifest. This function adds the activity check and the
    STALE_AFTER filter.
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
    """Appends one permanent row per subagent spawn. brief_pack.py writes it
    before the spawn, and the file exists even when the brief never packs.
    No code deletes a line from it. The function seals the row, because the
    functions that read the file keep only sealed rows. See sealed_rows()."""
    entry = dict(entry, seal=_row_seal(entry))
    with delegation_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def pending_path():
    return tmp_dir() / "densepack-pending.jsonl"


def pending_entries():
    """Returns all rows that the hooks appended, in file order. The
    function reads the file on each call and does not cache it, because the
    file can get a new row between two calls in one session.

    The function drops a row without a valid local seal, the same rule as
    drain_queue(). A cloned project can commit a row that names its own
    image inside .claude, and read_gate.py can then show that image to the
    lead. With no key, no row has a seal, and the function keeps no row."""
    return sealed_rows(pending_path())


# The sessions allowed to collect report pointers. SessionStart adds its own
# id here. A subagent never fires SessionStart. A subagent is then never on
# the list and cannot take the lead's images. It is a LIST because a project
# is often open in two windows at the same time. With a single slot, the
# second window to start replaces the first one with no message. Ten is far
# more than one person runs, and the limit prevents growth of the file.
LEADS_FILE = "densepack-lead-sessions.json"
LEADS_KEPT = 10


def read_leads():
    """Returns all sessions allowed to collect, newest last. The older
    single-id file still counts. An upgrade in the middle of a session then
    keeps the lead."""
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
    # The code also updates the old single-id file. A downgrade then still
    # works.
    write_text_atomic(tmp_dir() / "densepack-lead-session", str(session_id))
    return leads


OFF_FLAG = "densepack-off"
QUIET_FLAG = "densepack-quiet"  # receipts quiet, the default. dpctl.py reads it.


def off_flag_path(session=None):
    """Returns the path of the off switch file for one session,
    densepack-off-<session id>.

    A project open in two windows shares one .claude/tmp. One bare switch
    file set in one window can stop packing in the two windows. The other
    window then pays full price, and nothing on screen says why. The name
    contains the session for the same reason that read_lead_models() is a
    map and LEADS_FILE is a list. One project runs in more than one window.

    With no session id, the function returns the bare name on purpose.
    dpctl.py run from a terminal belongs to no window, and an
    on-against-off test needs the whole project off.
    """
    session = str(session or "").strip()
    if not session:
        return tmp_dir() / OFF_FLAG
    return tmp_dir() / ("%s-%s" % (OFF_FLAG, session))


def _off_file_set(session):
    """Returns True when the session id is not empty and its own off file is
    on disk."""
    session = str(session or "").strip()
    return bool(session) and (tmp_dir() / ("%s-%s" % (OFF_FLAG, session))).exists()


def disabled(session=None):
    """Returns True when the off switch is on. The switch is for clean
    on-against-off token tests.

    While the file .claude/tmp/densepack-off-<session id> exists, each hook
    in that session stops. It adds no instructions, packs nothing and
    prints no receipts. When the file is gone, the plugin works again.
    The switch needs no settings edit and no restart. An A B test is then
    two runs of the same task with the flag changed between them.
    /dense-off writes the flag, and /densepack removes it.

    A bare densepack-off with no session in its name stops all sessions. A
    file with no session cannot belong to one session, and it stops them
    all. dpctl.py on deletes each bare file that it finds. An old bare file
    then cannot stay active after a /densepack.

    A subagent's hook events name the session that owns the agent, not the
    agent. When the hooks of a lead stop, the hooks of its agents stop too.

    For an event that names no session, the function uses the session that
    the last event named, and then lead_session(). The reader profile
    lookup uses the same order.

    A project whose .claude or .claude/tmp is a link stops all hooks,
    because each write goes to the folder that the link names.
    """
    if through_link(project_dir(), tmp_dir()):
        return True
    if (tmp_dir() / OFF_FLAG).exists():
        return True
    if session is not None:
        return _off_file_set(session)
    return _off_file_set(_EVENT_SESSION) or _off_file_set(lead_session())


# The control settings for the slash commands. One JSON file. The code fills
# in defaults when the file is missing or partial, and it ignores unknown
# values. A hand-edited file then can never crash a hook.
#
#   receipts   default: one 6 column table per batch of agents, plus a batch
#                       totals row at the bottom of that same table when
#                       the totals setting is on.
#              verbose: the arithmetic in separate columns, a Dimensions
#                       column, a table per agent that returned several
#                       images, and the totals row's model line in full.
#              light:   the same 6 column table with no totals row,
#                       whatever the value of the totals setting.
#              quiet:   no table in the response. The hook saves the table to
#                       a file and tells the lead to show it only if the
#                       prompt asked.
#              Image pointers always go to the lead. They are function,
#              not reporting.
#   totals     Controls the CONVERSATION TOTALS row only, never the BATCH
#              TOTALS row above it. The BATCH TOTALS row prints in each
#              default and verbose table, whatever the value of this setting.
#              auto: the mode sets it, wrap-up only in default, each
#              response in verbose. on: each response. off: wrap-up only.
#              It never applies to light or quiet, which never show a
#              totals row.
#   keep       off, images, reports, or both. It names the files that
#              keep_copy() copies into this conversation's vault folder when
#              each agent finishes. Only keep_promote() uses keep_folder
#              (default <project>/densepack-archive). dpctl.py's keep verb
#              calls keep_promote().
SETTINGS_FILE = "densepack-settings.json"
#   stylecard  on: the writing rules apply to each reply and each Write or
#              Edit. prompt_card.py never reads this setting.
#              off: the default. The checks stop. With the same card
#              already in ~/.claude/hooks as a personal hook, "on" makes
#              the card arrive twice.
#
# No setting deactivates the standing reminder, on purpose. It says what a
# condensed image is, and the delivery then makes sense to the model. A
# switch for it can leave the model with images and no explanation while
# packing continues. /dense-off is the only switch that stops it, and it
# stops all of DensePack.
#
# receipts defaults to quiet. A table in the lead's context on each batch
# costs tokens in the prefix of each later turn.
SETTINGS_DEFAULTS = {"receipts": "quiet",
                     "totals": "auto", "keep": "both", "keep_folder": "",
                     # stylecard defaults to off. The writing check is opt-in.
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
# one line of totals, and off was silence. Each maps to one of the four
# modes. The alias keeps old settings files working.
RECEIPTS_ALIASES = {"full": "verbose", "line": "default", "off": "quiet"}


def settings(session=None):
    """Returns all active settings. The function accepts session and
    ignores it.

    The per session layer is in read_session_settings(), and this function
    does not call it. See SCOPED_SETTINGS above.
    """
    out = dict(SETTINGS_DEFAULTS)
    path = tmp_dir() / SETTINGS_FILE
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        # Valid JSON is not always an object. A hand-edited [] or null must
        # mean defaults, never a crash in each hook.
        if not isinstance(data, dict):
            data = {}
        # This file is in the project, and a cloned project can commit one.
        # A committed vault_mb of 0 makes the plugin delete its own kept
        # copies in that project, and "quiet" hides the receipt tables. The
        # two settings act only inside the project's .claude folder. The file
        # has no seal, because with a seal the plugin ignores each
        # hand-written settings file.
        for key, allowed in SETTINGS_ALLOWED.items():
            value = data.get(key)
            if key == "receipts" and isinstance(value, str):
                value = RECEIPTS_ALIASES.get(value, value)
            if isinstance(value, str) and value in allowed:
                out[key] = value
        folder = data.get("keep_folder")
        # The settings file is in the project, and a cloned project can
        # plant it. The keep folder must be a path inside the project. A
        # leading slash has its own test. Since Python 3.13, ntpath.isabs is
        # False for "/Users/x". A join of that path onto the project keeps
        # the drive and replaces the root, and the result can be a folder
        # anywhere on that drive. A NUL raises ValueError in mkdir, which no
        # caller catches.
        if (isinstance(folder, str) and not os.path.isabs(folder)
                and not folder.startswith(("/", "\\")) and "\x00" not in folder
                and not Path(folder).drive and ".." not in Path(folder).parts):
            out["keep_folder"] = folder
        # The vault cap is a number, not a word from a list. The loop above
        # does not handle it.
        cap = data.get("vault_mb")
        if isinstance(cap, int) and not isinstance(cap, bool) and cap >= 0:
            out["vault_mb"] = cap
    return out


def write_settings(changes):
    merged = settings()
    merged.update(changes)
    on_disk = merged
    # The code writes a new file and then moves it onto the name. os.replace
    # replaces a committed link and does not write through it to its target.
    import tempfile
    fd, part = tempfile.mkstemp(dir=str(tmp_dir()), prefix=".densepack-settings-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(on_disk, indent=2))
        # The code retries. On Windows, a replace onto a file that another
        # hook has open raises an error, and a slash command must not fail
        # on that.
        if not replace_retry(part, tmp_dir() / SETTINGS_FILE):
            Path(part).unlink(missing_ok=True)
    except OSError:
        Path(part).unlink(missing_ok=True)
        raise
    return merged


def vault_dir(session_id=None):
    """Returns the automatic copy folder, with one subfolder per
    conversation.

    .claude/tmp is scratch space, and a new session deletes old files in
    it. Without a copy, an image that an agent never opened, or a report
    that nobody read before the session ended, is lost. This folder keeps
    the copy. The subfolder has the name of the conversation, and a report
    is then easy to find by its conversation.
    """
    base = project_dir() / ".claude" / VAULT_DIRNAME
    if session_id is None:
        return base
    return base / (str(session_id) if session_id else "no-session-id")


# The characters that a shell acts on, and the characters that end a line of
# plugin prose.
SHELL_META = set("`$\"'<>|&;()!*?[]{}~\n\r")


def quoted_path(text):
    """Returns a path that works inside a double-quoted shell word.

    Only the backtick, the dollar sign, the double quote, the backslash and
    a line break act inside double quotes. The function changes only those.
    Brackets, braces, a tilde and a space are literal there, and a Windows
    path can contain them. "Program Files (x86)" must still name the file
    that the model asked for.
    """
    out = str(text).replace("\\", "/")
    return "".join("_" if ch in "`$\"\n\r" else ch for ch in out)


def no_metacharacters(text):
    """Returns a path or name that the model can still use, with no
    character that a shell acts on.

    A project names its own files. Without this function, a deny message
    that puts a path into a command can give the model
    `cat "notes-$(id).md"` to run. Separators become forward slashes, which
    Windows and the Read tool accept. Each other shell character becomes an
    underscore.
    """
    out = str(text).replace("\\", "/")
    return "".join("_" if ch in SHELL_META else ch for ch in out)


def clear_link(path):
    """Removes a link at this name before code writes to it.

    A project can plant a name that the plugin writes as a symbolic link, a
    junction or a second hard link. The write then goes into the file that
    the link shares. A hard link is a real directory entry. Only the link
    count separates it from an ordinary file. densepack.clear_link() calls
    this function, and so does each writer that cannot move a new file onto
    the name.
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
    """Sets CLAUDE_CODE_THRIFTY_SONIC=0 in the env block of
    ~/.claude/settings.json, or clears it with enable=False. Returns True
    when the file changed.

    Auto mode and bypassPermissions mode inject a message that tells Claude
    to read files with cat, head or sed in Bash, and a Bash read stays text.
    The variable at 0 stops that message. Bash itself stays available. An
    auto mode session with the variable set has no auto_mode attachment in
    its transcript. The function keeps a value that is already in the env
    block. It leaves a file with a BOM alone, because Claude Code then
    ignores the whole file. It writes nothing when the file does not parse.
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
    """Writes text to a new file in the same folder, then moves it onto
    `path`.

    A plain write follows the object at the name. That object can be a
    symbolic link, a junction or a second hard link, and a project can plant
    each of them. The bytes then go into the file that the link shares.
    os.replace puts a new file in place of the name, and no write goes
    through a link.
    """
    import tempfile
    folder = os.path.dirname(os.path.abspath(str(path))) or "."
    part = None
    try:
        # This call is inside the try. A missing or unusable folder raises
        # an error here, and each other failure in this function returns
        # False.
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
    """Calls os.replace and retries while Windows keeps the destination
    open.

    Python's open() passes no FILE_SHARE_DELETE. A replace onto a file that
    another hook reads then raises PermissionError. densepack.py has the
    same helper for images. This one is for the small state files."""
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
    """Returns the seal over one source-text file and ALL images of its
    pack.

    Image 1 alone is not enough. The gates give the model all images of the
    pack. A project that commits image 2 can then get it into a pack that
    the plugin seals."""
    return _row_seal({"pair_src": os.path.basename(str(src)),
                      "pair_images": [str(n) for n in names]})


def seal_pair(src, names):
    """Records the seal of the text and image pack that the local plugin
    wrote."""
    if isinstance(names, str):
        names = [names]
    names = [os.path.basename(str(n)) for n in names]
    seal = pair_seal(src, names)
    if seal is None:
        return
    write_text_atomic(Path(str(src) + ".seal"),
                      json.dumps({"images": names, "seal": seal}))


def sealed_pack(src):
    """Returns all image names sealed for this source text, in order, or an
    empty list."""
    import hmac
    try:
        raw = Path(str(src) + ".seal").read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        rec = json.loads(raw)
    except ValueError:
        # Version 0.4.41 wrote a bare HMAC over one image name. The gates
        # still use a pack that is already on disk and do not convert it a
        # second time.
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
    # Bare names only. A name with a folder, a drive or a parent step can
    # reach outside the folder of the source text.
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
    """Returns True when the local plugin wrote and sealed the pair.

    A cloned project can commit a text file and an image in .claude/tmp
    with the packers' own names. Without this check, a gate can replace a
    Read of that text with the project's image, which can show other
    words."""
    return os.path.basename(str(image_name)) in sealed_pack(src)


def is_junction(path):
    """Returns True for a Windows junction, on each Python version that the
    hooks run on.

    os.path.isjunction came in 3.12, and run_hook.sh accepts 3.10. On 3.10
    a junction can look like a plain folder, and each link guard in this
    plugin can pass it. The reparse tag separates a junction from a cloud
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
    """Returns True when `path`, or a folder between `root` and `path`, is a
    symbolic link or a Windows junction. A cloned project can commit a vault
    folder as a link to the home folder. Each delete or copy in the vault
    can then reach the files of the link target. Those callers reject such
    a path."""
    # normcase on the two sides. abspath does not fold case. A root and a
    # path that differ only in the case of the drive letter can end the walk
    # at the start and miss each link below.
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


# A conversation folder in the vault has a Claude Code session id (a UUID)
# or "no-session-id" as its name. vault_folders() lists only these folders.
SESSION_FOLDER = re.compile(
    r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{12}|no-session-id)$")


def vault_folders():
    """Returns each conversation folder in the vault with its size, oldest
    first.

    vault_dir() names a conversation folder with a Claude Code session id
    (a UUID) or with "no-session-id". This list holds only folders with
    such a name. vault_trim() deletes folders from this list only. It never
    touches instructions/, to-pack/, images/, not-converted/, a folder from
    an older version or a folder made by hand.
    """
    base = vault_dir()
    # A cloned project can commit the vault, or .claude, as a link to a
    # folder anywhere on disk. vault_trim() deletes the folders that this
    # list returns.
    if not base.is_dir() or through_link(project_dir(), base):
        return []
    out = []
    for folder in base.iterdir():
        if not folder.is_dir() or through_link(base, folder):
            continue
        if not SESSION_FOLDER.match(folder.name):
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
    """Deletes session folders from vault_folders(), oldest first, until the
    vault is at or below its cap. The first pass deletes whole folders. It
    never deletes the newest folder, which is the conversation in progress,
    or the folder of keep_session. When the vault is still over the cap, a
    second pass deletes single files from the newest folder, one file at a
    time, oldest mtime first. Returns the names of the deleted folders and
    files."""
    import shutil
    rows = vault_folders()
    total = sum(size for _t, _f, size in rows)
    cap = vault_cap_bytes()
    # The newest folder is the conversation in progress. The trim never
    # deletes it, whatever the cap and whatever the caller passes, because
    # dpctl.py trims when the cap changes and has no session id of its own.
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
    # The vault is still over the cap. The loop above skipped the newest
    # folder and the keep_session folder, and one conversation alone can be
    # larger than the cap.
    #
    # This pass deletes the files at the top of the newest folder, one file
    # at a time, oldest mtime first, until the vault is at or below the cap.
    # It does not delete an image and its text as a pair. The list names
    # these files apart from the folders, because the loss of part of a live
    # conversation is a different event from the removal of an old one.
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
    """Copies packed images and their source text into the vault.

    It runs on each pack, in the two directions, whatever the keep setting
    is. The keep setting names the files to KEEP permanently, and this is
    the working copy that the plugin uses as a fallback. It costs disk
    space and no tokens, because nothing that it writes enters the
    conversation.

    A copy failure never stops delivery, because the caller's work is
    already done.
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
    """Copies one conversation's vault folder into the keep folder, which
    no code deletes automatically. dpctl.py's keep verb calls it. Returns
    the destination, or None when that conversation is not in the vault."""
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
    """Returns the receipts mode. The quiet flag is older than the settings
    file and still comes first. It was the documented off switch for
    receipts, and a project with the flag must not start to show tables
    because a newer file has a different value."""
    if (tmp_dir() / "densepack-quiet").exists():
        return "quiet"
    return settings()["receipts"]


def totals_shown():
    """Returns True when the CONVERSATION TOTALS row goes below this batch's
    table, next to the BATCH TOTALS row that prints whatever this setting
    is.

    Default mode keeps the conversation's totals row for the wrap-up, and
    verbose prints it each time. The totals setting on or off overrides the
    mode in the two directions. Quiet and light print no totals row, and
    this result never applies to them.
    """
    choice = settings()["totals"]
    if choice == "on":
        return True
    if choice == "off":
        return False
    return receipts_mode() == "verbose"


def status_shown():
    """Returns False. The reply has no status table."""
    return False


def read_event(raw=None):
    """Returns the hook event on stdin and stores the session that it
    names.

    The off switch is per session. A hook then reads the event first and
    passes the session id that it finds to disabled().

    raw, when given, is stdin already read as text. pointer.py's fast
    PostToolUse exit reads stdin to check for a TaskStop tool call before
    it does other work. It reads stdin once itself and passes the text
    here. This function then does not read a second time from a pipe that
    the first read emptied.
    """
    if raw is None:
        # Windows pipes hook stdin as cp1252 by default. That turns each
        # UTF-8 quote in a report into mojibake, and the mojibake then goes
        # into the image. A crash does not show the fault, because cp1252
        # decodes all bytes with no error. Only the packed image shows it.
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
    # The code stores the event's cwd FIRST, before note_lead_model calls
    # tmp_dir(). The first disk access then uses the session's own folder and
    # not this process's working directory.
    note_event_cwd(event)
    note_event_session(event)
    # Each hook event names the session transcript, and the lead's model is
    # on its first assistant line. The code records it here, and no other
    # hook has to record it. Nobody has to tell the plugin which model reads
    # its images. The code writes the record once per session, with that
    # session's own id.
    #
    # A session that is off records nothing, as the switch says. The code
    # stored the id one line above. The check here then does not read the
    # value of another session.
    if not disabled(event.get("session_id")):
        note_lead_model(event)
    return event


# THE PERMISSION RULE. A PreToolUse hook that changes a tool call with
# updatedInput makes Claude Code check the permission of the NEW call, not of
# the call that the agent made. Tests on Claude Code 2.1.288 show this.
#
#   A Read outside the project, changed to a file inside it, ran in default
#   mode with no prompt. The same Read unchanged asked first.
#   A Read of a file that an "ask" rule names, changed to another file, ran
#   with no prompt in default mode.
#   A "deny" rule held in each mode. Claude Code checks it before the hook
#   runs, and the hook never saw the denied Read.
#   A Read that the user or a rule refuses fires no PostToolUseFailure.
#
# A mode that asks before some Reads (default, acceptEdits, plan) or refuses
# them (dontAsk) gets no changed call from any hook of this plugin. Auto and
# bypassPermissions ask before no Read, so a change there skips no prompt.
# Each mode still asks when a rule names the tool, so a hook never changes a
# call to a tool that an "ask" rule names. A missing or unknown mode counts as
# a mode that asks.
REWRITE_MODES = ("auto", "bypassPermissions")


def _managed_settings_paths():
    if sys.platform == "darwin":
        return [Path("/Library/Application Support/ClaudeCode/managed-settings.json")]
    if os.name == "nt":
        return [Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "ClaudeCode" / "managed-settings.json"]
    return [Path("/etc/claude-code/managed-settings.json")]


def ask_rule_names(tool):
    """True when a settings file holds an "ask" rule for `tool`, such as
    "Read" or "Read(./notes.txt)". The code does not match the pattern of
    the rule against a path. Any ask rule for the tool counts. A settings
    file that exists but does not parse also counts, because its rules are
    unknown."""
    files = [Path.home() / ".claude" / "settings.json"]
    try:
        root = project_dir()
        files += [root / ".claude" / "settings.json",
                  root / ".claude" / "settings.local.json"]
    except Exception:  # noqa: BLE001
        return True
    files += _managed_settings_paths()
    for path in files:
        try:
            if not path.is_file():
                continue
            raw = path.read_bytes()
            data = json.loads(raw.decode("utf-8-sig") or "{}")
        except (OSError, ValueError):
            return True
        if not isinstance(data, dict):
            return True
        rules = (data.get("permissions") or {}).get("ask") or []
        if not isinstance(rules, list):
            return True
        for rule in rules:
            name = str(rule).strip()
            if name == tool or name.startswith(tool + "("):
                return True
    return False


def may_rewrite(event, tool=None):
    """True when a PreToolUse hook may change the call with updatedInput.
    See THE PERMISSION RULE above."""
    if str(event.get("permission_mode") or "") not in REWRITE_MODES:
        return False
    return not ask_rule_names(tool or str(event.get("tool_name") or ""))


def emit(payload):
    """Prints a hook's JSON output with the same encoding rules as the
    input."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    print(json.dumps(payload))


def ensure_pillow():
    """Makes Pillow importable, from the plugin data dir when the bootstrap
    put it there.

    Returns True when PIL imports. False means each hook does nothing,
    which is the correct failure mode. Text still goes to the model, and
    nothing breaks.
    """
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        pylibs = Path(data) / "pylibs"
        if pylibs.is_dir():
            sys.path.insert(0, str(pylibs))
    try:
        import PIL  # noqa: F401
        import freetype  # noqa: F401  The glyph backend. Without it, the fallback renderer makes a different image.
        import numpy  # noqa: F401  codepack.py blends each glyph into the image with it
        return True
    except ImportError:
        return False


_SEAL_KEYS = {}


def seal_key():
    """Returns the seal key. The function reads it from disk once per
    process and home folder.

    sealed_rows() computes the seal of each row that it reads, and the
    manifest holds thousands of rows. A read of the key file for each row
    makes one table take seconds."""
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
    """Returns 32 random bytes kept in ~/.claude/densepack-state, outside
    the project. The function makes them once per machine. Returns None
    when the function cannot write to that folder.

    The key is in one fixed folder, not in CLAUDE_PLUGIN_DATA, because
    dpctl.py and densepack.py run without CLAUDE_PLUGIN_DATA and must use the
    same key that the hooks check."""
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
            # A key file of the wrong length is broken. The code makes it
            # again.
            try:
                path.unlink()
            except OSError:
                return None
        # The bytes go into a file of this process's own, and the code then
        # links that file onto the key's name in one step. A process that
        # stops in the middle leaves no empty key. When two processes run at
        # the same time, the key of the first link stays.
        tmp = path.with_name("sidecar.key.%d.%s" % (os.getpid(), os.urandom(4).hex()))
        try:
            # Mode 0600. Only this OS account can read the key.
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(os.urandom(32))
            try:
                os.link(tmp, path)
            except FileExistsError:
                pass
            except OSError:
                # A file system with no hard links. On Windows, rename rejects
                # an existing name. On other systems, the loop reads the first
                # key again below.
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
    """Returns an HMAC over one queue row. A cloned project cannot compute
    it. A row that the project commits then never reaches the model as the
    plugin's words."""
    import hashlib
    import hmac
    key = seal_key()
    if not key:
        return None
    body = json.dumps({k: v for k, v in entry.items() if k != "seal"}, sort_keys=True)
    return hmac.new(key, body.encode("utf-8"), hashlib.sha256).hexdigest()


def sealed_rows(path):
    """Returns the rows of jsonl_rows() that the local plugin wrote and
    sealed.

    A cloned project can commit each of these files in .claude/tmp. A
    row that the project wrote can then reach a receipt, a table or an
    image list as the plugin's own. With no key, no row has a seal, and the
    function keeps no row. A hook environment that moves the home folder
    must not deactivate the seal. The plugin then uses text, which loses a
    saving and no words."""
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
    # Without this check, the loop below drops all rows when there is no
    # key, and the drain deletes the file that holds them. The rows stay on
    # disk for a session that has a key again. The packers stop until then.
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
        # A row with no valid seal does not come from the local plugin.
        # With no key, no row has a seal, and the loop keeps no row. A hook
        # environment that moves the home folder must not deactivate the
        # seal.
        import hmac
        want = _row_seal(row)
        if want is None:
            continue
        if (isinstance(row.get("seal"), str)
                            and hmac.compare_digest(want, row["seal"])):
            entries.append(row)
    path.unlink(missing_ok=True)
    return entries


# The cost of one extra lead turn, in the cache write tokens of the pack
# compare. A packed Bash output or report reaches the lead as a pointer, and
# the lead spends a Read turn to open the image. That turn reads the whole
# context again at the cache read rate and writes one short call.
#
# Claude Code writes the one hour cache at 2x input. A cache read is 0.025x
# input on Fable 5.1, 0.05x on Opus 5.5 and 0.1x on the other models.
# Against one write token, a read is then 0.0125 on Fable, 0.025 on Opus
# and 0.05 on the other models. READ_SHARE holds the Fable and Opus values,
# and READ_OVER_WRITE holds the value for the other models. An output
# token, 5x input, is 2.5 against one write token. The five minute
# multipliers, 1.25x and 0.08, do not apply.
#
# The Read call that opens an image writes about 150 output tokens. The
# tool result with the pointer costs about 185 tokens more than the
# pointer's own characters.
READ_OVER_WRITE = 0.05
FABLE_READ_OVER_WRITE = 0.0125
# Opus 5.5 bills input $4, cache write $8, cache read $0.20 and output $20
# per million tokens. A read is then 0.05x input, and 0.025 against one
# write token. The usage in the result record of a claude -p run, times
# these prices, equals the costUsd of that run exactly.
OPUS_READ_OVER_WRITE = 0.025
READ_SHARE = {"fable": FABLE_READ_OVER_WRITE, "opus": OPUS_READ_OVER_WRITE}
OUT_OVER_WRITE = 2.5
READ_CALL_OUTPUT_TOKENS = 150
TOOL_RESULT_WRAP_TOKENS = 185
# The first turn prefix of a plain claude -p run. The code uses it when the
# transcript is unreadable.
CONTEXT_WHEN_UNKNOWN = 59863


def context_tokens(session_id, tail_bytes=400000, path=None):
    """Returns the tokens that this session reads again on its next turn.
    That is the sum of input, cache read and cache write in the last
    assistant usage. Returns 0 when unknown. DENSEPACK_CONTEXT_TOKENS in
    the environment sets the value directly. The test suites run the
    scripts with no transcript on disk, and a benchmark can fix the context
    that it measures at. path names another transcript to read, a
    subagent's own, in place of the session's."""
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
    """Returns the count of assistant messages in this session's transcript
    so far, or 0 when unknown."""
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
    """Returns the write rate tokens that an image must save to pay for the
    Read turn that opens it. The function computes the fee from the
    session's own context and then divides it by the saving of the later
    turns. Each later turn reads the image again in place of the text at
    the read rate. The function assumes that the turns still to come equal
    the turns so far. Without that divisor, a lead far into a long session
    does not pack a report that it then reads again many times."""
    # The subagent opens a pack made for it. Its own transcript then sets
    # the fee. actor is its agent id.
    path = agent_transcript(actor) if actor else None
    context = context_tokens(session_id, path=path)
    if not context and not os.environ.get("DENSEPACK_CONTEXT_TOKENS", "").strip().isdigit():
        context = CONTEXT_WHEN_UNKNOWN
    try:
        reader = actor_reader(actor) if actor else resolved_reader(session_id)
    except Exception:  # noqa: BLE001
        reader = None
    read_share = READ_SHARE.get(reader, READ_OVER_WRITE)
    fee = context * read_share + READ_CALL_OUTPUT_TOKENS * OUT_OVER_WRITE
    return int(fee / (1 + turns_so_far(session_id, path=path) * read_share))


# Dollars per million tokens, input and output. A cache write is 2.0 x
# input, because Claude Code writes one hour entries. read_rate() below
# gives the cache read share of each model.
RATES = {"fable": (10.0, 50.0), "opus": (4.0, 20.0), "sonnet": (2.0, 10.0), "haiku": (1.0, 5.0)}
# The cache read as a share of the input price: Fable 5.1 0.025, Opus 5.5
# 0.05, other models 0.1.
READ_RATE = {"fable": 0.025, "opus": 0.05}


def read_rate(model):
    """The cache read price of model as a share of its input price."""
    name = str(model or "").lower()
    for key, rate in READ_RATE.items():
        if key in name:
            return rate
    return 0.1


# A report's image costs about half its text in tokens.
IMAGE_OVER_TEXT = 0.5
POINTER_TOKENS = 60
# The agent's second reply on the block route, when it follows the pointer
# line. The reply is the line and a short thought. When the agent refuses
# and repeats its report, the cost is the whole report again. Only a
# background agent takes the block route. See report_pack_worth().
AGENT_REPLY_TOKENS = 100


def rates_for(model):
    name = str(model or "").lower()
    for key, pair in RATES.items():
        if key in name:
            return pair
    return RATES["sonnet"]


def report_pack_worth(text_tokens, lead_model, lead_session, agent_model=None,
                      agent_transcript=None, agent_turn=False):
    """Returns True when a pack of a subagent's report saves money, in
    dollars.

    A pack costs the lead the Read turn that opens the image. That turn
    reads the lead's whole context again at its read rate and writes one
    short call. A pack saves the lead the difference between the text and
    the image, once at the write rate and again at the read rate on each
    later turn. The function assumes that the turns still to come equal the
    turns so far.

    The swap route has no extra agent turn. subagent_stop.py packs the
    report at the agent's first stop, and report_swap.py puts the marker
    line in the Agent result in place of the report. On the block route,
    the stop hook blocks the agent and asks for the marker line, and each
    pack pays for that turn. That turn reads the agent's whole context again
    at the agent's read rate and adds a short reply. For a report of 6,561
    characters from an Opus 5.5 agent, that turn made the cost $0.0114
    against a saving of $0.0110, and the report stayed text. Without that
    turn, the cost is $0.0056.

    agent_turn is True only for the block route, which a background agent
    takes. The function then charges the extra turn at the model and the
    context of the agent."""
    from pathlib import Path
    lead_in, lead_out = rates_for(lead_model)
    saved_tokens = text_tokens * (1 - IMAGE_OVER_TEXT) - POINTER_TOKENS
    if saved_tokens <= 0:
        return False
    lead_ctx = context_tokens(lead_session)
    if not lead_ctx and not os.environ.get("DENSEPACK_CONTEXT_TOKENS", "").strip().isdigit():
        lead_ctx = CONTEXT_WHEN_UNKNOWN
    turns = turns_so_far(lead_session)
    lead_read = read_rate(lead_model) * lead_in
    saving = saved_tokens * (2.0 * lead_in + turns * lead_read) / 1e6
    cost = (lead_ctx * lead_read + READ_CALL_OUTPUT_TOKENS * lead_out) / 1e6
    if agent_turn:
        agent_in, agent_out = rates_for(agent_model or lead_model)
        agent_ctx = 0
        if agent_transcript and not os.environ.get("DENSEPACK_CONTEXT_TOKENS", "").strip().isdigit():
            agent_ctx = context_tokens(lead_session, path=Path(agent_transcript))
        agent_read = read_rate(agent_model or lead_model) * agent_in
        cost += (agent_ctx * agent_read + AGENT_REPLY_TOKENS * agent_out) / 1e6
    return saving > cost
