"""The toolbox every other script here reaches into.

HOW THIS FILE FITS, in plain words: DensePack is five small programs that pass
notes to each other through two files, a queue and a totals sheet, both kept in
the project's .claude/tmp folder. This file is the drawer they all share: where
those files live, how to read the message Claude Code pipes in, how to answer
it, and how to find Pillow, the drawing library. No script runs this directly.

ORIGINAL NOTE: Shared plumbing for the DensePack hooks.

Every hook script starts by importing this. It finds the project's scratch folder,
the queue file, and Pillow, wherever the plugin data directory put it.
"""

import json
import os
import re
import sys
from pathlib import Path

# No character floor, by a measured decision. Every report is
# measured and packs whenever the image costs less than the text, the same live
# comparison the DensePack app's own meter applies. STUB_LINES defines when the
# file protocol applies: a report that fits in the stub IS the stub.
MIN_CHARS = 0
STUB_LINES = 10

# The line count alone is gameable: the 15 August 2026 benchmark caught three
# agents returning 6,000 character reports as seven long paragraphs, seven
# literal lines, so the file rule never fired and the delivery saving was
# lost. The character count closes that loophole.
#
# The number is measured, not picked. It was 600 until 19 August 2026, derived
# from the 140 token handover cost alone, and that derivation left out the patch
# count, which is the larger half of an image's cost. The threshold therefore
# sat below the point where packing starts to pay, and a report just above it
# was pulled into a file and blocked for a saving the packer then refused to
# take.
#
# RE-MEASURED 30 August 2026, DensePack floors brief, after LINE_GAP moved
# from 1.0 to 0.85 the same day. Every earlier floor was bisected at the 1.0
# gap: the shipped 634 / 737 / 872 reproduce at a 1.0 gap and the old
# 195 token fee to within 2 characters (635, 739, 874), and a tighter gap
# makes every image cheaper, so every floor fell. Method, the same one
# tests/test_floor_measurement.py re-runs on every suite run: bisect the
# smallest source length where the production pack() at the shipped
# LINE_GAP, fed MATH.md cut to length, priced by densepack.image_cost()
# real patches plus the route's own delivery fee, first beats the text
# priced at CHARS_PER_TOKEN. No live count_tokens call, for the reasons in
# the note above resolved_reader(); CHARS_PER_TOKEN is the yardstick every
# gate already uses.
#
# THE FEE IS MEASURED FROM THE CODE THAT EMITS IT, never assumed: the
# route's own pointer at CHARS_PER_TOKEN. The routes differ because their
# pointers differ:
#
#   report route, subagent_stop.py. common.report_pointer() runs 137
#     characters, 57 tokens at the 2.40 divisor, the shortest pointer, so
#     the lowest floor.
#     Stub mode charges stub_pointer(), 260 characters, instead; the live
#     compare prices whichever mode ships, and the pre-filter stays on the
#     shorter fee for the same cheap-side reason as the bash route.
#   bash route, bash_pack.py, which subread_gate.py's redirect also feeds.
#     pointer_line() runs 159 characters, 66 tokens at the 2.40 divisor:
#     the image path and
#     the exact-text path, nothing else, since 30 August 2026.
#
# A floor here only skips the draw. Every route re-prices the real drawn
# image against the real text before it ships, so these constants may drift
# low safely and must never drift high.
#
# THE FLOOR IS FLAT, settled 30 August 2026, replacing the turn-decay
# curve settled earlier the same day. The image and its pointer both sit
# in the conversation prefix permanently, exactly as the text they replace
# would, so every turn pays image plus pointer on one side or text on the
# other. The one Read that opens the image is paid once and amortises to
# nothing over the session, so it stays out of the compare. Packing wins
# whenever
#
#     image_tokens + pointer_tokens < text_tokens
#
# and that condition does not depend on the turn count at all. The floor
# cannot reach zero, because the pointer is itself text that stays in the
# prefix: content smaller than the pointer describing it can never pay
# back, so the floor bottoms out at the pointer's own size scaled by the
# drawing density.
#
# Measured 30 August 2026 with the production pack() fed MATH.md cut to
# length, priced by densepack.image_cost() against CHARS_PER_TOKEN: an
# image measures 0.11 to 0.14 of its text at 8 px, 0.21 to 0.24 at 10 px,
# 0.30 to 0.33 at 12 px, the ratio worst at short lengths where the
# per-image overhead weighs most, so the multiplier is derived per reader
# by the bisection in tests/test_floor_measurement.py, never assumed.
#
# The two dead models, both 30 August 2026, kept so neither returns. The
# first folded one whole turn's cache read, 4,126 weighted tokens, into
# the fee as if the saving were one-off; its floors sat in the tens of
# thousands and stopped the plugin packing anything. The second divided a
# turn-one fee by the lead turns elapsed, a falling curve; it charged the
# pointer as if it were paid once, when the pointer is re-read every turn
# exactly like the image and the text.

# Flat break-evens from that bisection, image plus pointer against text,
# fable/opus/sonnet in that order. Fees from the emitting code, report 52
# and bash 60 tokens per turn in the prefix.
# RE-BISECTED 31 August 2026, after CHARS_PER_TOKEN fell from 2.65 to the
# measured 2.40. A smaller divisor prices the text side higher, so the image
# becomes cheaper than the text at a shorter length, and every floor bisected
# at 2.65 sat above the real crossing point. The stub and brief floors each sat 5 to 12
# characters high, which is the one direction the note above forbids, and
# they come down here to what tests/test_floor_measurement.py bisects live.
# The bash floors already sat below their crossing point, the safe side, so
# they stay where they are.
STUB_CHARS_BY_READER = {"fable": 177, "opus": 194, "sonnet": 210}
BASH_CHARS_BY_READER = {"fable": 203, "opus": 222, "sonnet": 259}
STUB_CHARS = 177


def stub_chars():
    """The smallest report worth sending to a file, for the reader in use."""
    return STUB_CHARS_BY_READER.get(resolved_reader(), STUB_CHARS)


def bash_chars():
    """The smallest Bash output worth packing, for the reader in use.

    It sits above stub_chars() because the bash pointer names the image,
    the folder and the exact-text file, 159 characters against
    report_pointer()'s 137.
    """
    return BASH_CHARS_BY_READER.get(resolved_reader(),
                                    BASH_CHARS_BY_READER["fable"])


# The brief thresholds, keyed by drawing size rather than by profile name,
# because a brief is packed for the agent it is sent to, not for the lead:
# spawning a Fable agent draws that agent's brief at 8 px, so the 8 px
# threshold applies whoever leads. The fee is brief_pack.POINTER filled
# with an image path, 245 characters, 92 tokens: higher than the report
# and bash pointers because a brief's pointer IS the replacement prompt
# the agent receives, so these floors sit above the other routes'. The
# path inside the pointer varies a few characters with the session id, so
# the fee is priced at a short one and the floor stays on the cheap side
# of the variance. When brief_pack lifts a code block it adds the code
# file's own text to the fee; the pre-filter cannot know that in advance
# and stays on the cheap side, where a wrong guess costs one discarded
# draw.
# RE-BISECTED 30 August 2026, the same flat model and the same run as the
# report floors above: image plus pointer against text, the Read paid once
# and amortised out.
# Re-bisected 31 August 2026 with the rest, when CHARS_PER_TOKEN fell to
# 2.40. These were 307, 344 and 381, each a few characters above the real
# crossing point once the text side cost more.
BRIEF_CHARS_BY_PX = {8: 302, 10: 335, 12: 369}


def brief_chars(px):
    """The smallest brief worth packing at this drawing size."""
    return BRIEF_CHARS_BY_PX.get(px, STUB_CHARS)

# 8 px Consolas with color coding, measured 14 August 2026: two cold Fable readers
# each scored 10 of 10 exact answers off a real 10,446 character report, including a
# quoted issue number and verbatim paths. 8 px saves 76 percent against 64 at 9 px.
# Opus 5 needs 10 px, measured 18 August 2026 the same way: at 6 and 7 px every
# answer came back UNREADABLE, at 8 px 1 of 10, at 9 px 6 of 10, at 10 px two cold
# Opus readers scored 10 of 10 and 12 of 12 (paths, a hex checksum and a JSON line
# character for character). 10 px still saves 59 percent before the handover cost.
# The reader profile is a setting, so a Pro plan lead on Opus 5 gets images it can
# read; /fablepack and /opuspack switch it.
# Haiku 4.5 gets no profile here, measured 31 August 2026 the same way: at 12 px,
# the largest size this dict holds, two cold Haiku readers scored 1 of 10 and
# 1 of 10 and neither ever said UNREADABLE. The MEASURED_MODELS note below
# carries the answers, and bench/HAIKU-READER-FLOOR.md carries all twenty.
FONT_SIZE = 8
READER_SIZES = {"fable": 8, "opus": 10, "sonnet": 12}


def font_size():
    """The pixel size every image is drawn at, from the reader profile."""
    return READER_SIZES.get(resolved_reader(), FONT_SIZE)


# Which model reads which size, keyed by the word that appears in the Agent
# tool's `model` field. A model that is not on this list has never been scored
# on a condensed image, so it is sent plain text: an unreadable brief costs the
# whole task, and the saving is not worth that trade.
#
# Each size is the smallest at which that model copied twelve exact values out
# of one packed PNG and nothing else: a 36 character hex id, a comma grouped
# seven digit number, four file names, three plain numbers, a percentage and a
# phrase.
#
#   Fable 5    8 px   10 of 10, two cold readers, 14 August 2026
#   Opus 5     10 px  10 of 10 and 12 of 12, 18 August 2026
#   Sonnet 5   12 px  12 of 12 twice, 25 August 2026. At 11 px it swapped two
#                     answers, at 10 px it dropped a word from two, at 8 px it
#                     invented a file name and changed 22,520,080 into
#                     22,810,090.
#   Haiku 4.5  none   1 of 10 and 1 of 10, two cold readers, 31 August 2026.
#                     Scored at 12 px, the largest size any reader holds, on a
#                     7,546 character archived report of this repo's own. It
#                     missed the comma grouped numbers, the file path, the chat
#                     id, the 36 character session id, the heading and the line
#                     number. It read 82,164 as 287,093 and as 94,887, and it
#                     wrote a session id of the right shape and the wrong
#                     characters. It never once answered UNREADABLE, so a
#                     caller cannot tell a bad read from a good one.
#
# Haiku 4.5 stays off this dict on evidence. It was tested and it failed, and
# bench/HAIKU-READER-FLOOR.md holds all twenty answers. Nothing changed for
# Haiku on 31 August 2026: it was already served plain text, and it stays there.
MEASURED_MODELS = {"fable": 8, "opus": 10, "sonnet": 12}

VAULT_DIRNAME = "densepack-vault"

# How much disk the vault may hold before the oldest conversation folders are
# deleted. 200 MB holds roughly ten thousand packed reports at the 19 KB a real
# one measured, which is far more than any run needs and small enough that
# nobody notices it. /vaultpack <megabytes> changes it.
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
    """The instructions folder key, fable, opus or sonnet, for a model
    name, or None when the model has never been measured and gets no
    image. Mirrors size_for_model, keyed to MEASURED_MODELS instead of a
    pixel size, for a caller that needs the folder name rather than the
    font size: PLAN-FABLE.md step 4, 29 August 2026.

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

# The size drawn when the lead's model has not been read yet, which is only
# the SessionStart briefing. 10 px is the safe default: Opus scored 1 of 10 at
# 8 px and 10 of 10 at 10 px, and Fable reads 10 px more easily than the 8 px
# it was scored at. An unknown lead therefore gets the size both models read.
UNKNOWN_READER = "opus"


def _model_from_transcript(path, skip_sidechain=False):
    """The model named on the first assistant line of transcript `path`, or
    None when the file is missing, unreadable, or names none.

    Shared by note_lead_model(), which passes skip_sidechain True because it
    wants the LEAD's own line even while a subagent's turn is interleaved
    in the same transcript, and by event_reader() below, which does not
    skip one: a subagent's own transcript file marks every one of its own
    rows isSidechain, captured live 29 August 2026 from a real
    agent-<id>.jsonl file, five rows in a row, isSidechain True on every
    one. Skipping them there would find nothing and always fall through.
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

    The file held one bare model name before 31 August 2026, written once
    and never overwritten, with no session id on it and nothing clearing it
    between sessions. A name from 25 August was still being read on 31
    August, and dpctl.py reported a 10 px Opus reader inside a Fable
    session. A name with no session attached cannot be matched to the
    session asking for it, so a file in the old shape reads as empty here
    and the model is detected again. It is a MAP, not one slot, because a
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
# The test is what a wrong answer costs the window next door, audited setting
# by setting on 31 August 2026.
#
#   reader     Scoped. It sets the pixel size every image is drawn at. A
#              window pinned to fable draws 8 px, and a lead that was never
#              measured at 8 px reads those images wrong or not at all. One
#              agent was seen opening a packed image in Pillow to zoom in.
#              A wrong size is the most expensive wrong answer the plugin has.
#
#   agentpack  Should be scoped, NOT SCOPED YET. It decides whether the
#              delegation rules supersede other plugins' rules, yield to them,
#              or stand down, so it changes which model does the work in the
#              window that reads it and therefore what that window spends. A
#              user who stands the rules down in one window to work by hand
#              has said nothing about the next one.
#   maxtier    Should be scoped, NOT SCOPED YET. It decides whether an Opus 5
#              lead may spawn Fable 5 subagents. It is a statement about ONE
#              lead, and left global it hands a neighbouring lead a permission
#              nobody gave it.
#
#              Both were scoped and then put back on 31 August 2026. Nine
#              suites set them project wide at about twenty call sites and
#              then drive hooks under a dozen different made up session ids,
#              so scoping them turns eight suites red until every one of those
#              call sites is rewritten to name a session. The machinery below
#              already takes them: adding either word to SCOPED_SETTINGS is
#              the whole change, once those suites have been rewritten and
#              run. Shipping it unverified would have been worse than leaving
#              it named here.
#
#   receipts   Global. It prints a savings table in the reply and costs a
#              handful of tokens. A user who turns receipts on wants them
#              wherever they work in this project.
#   totals     Global. One more row in the same table receipts prints.
#   status     Global. The delegation table's automatic print, the same
#              family as receipts.
#   stylecard  Global. It is the writing standard for this repository, sent
#              once per session. One repository has one standard, not one per
#              window.
#   keep       Global. It archives images and report text to disk. No model
#   keep_folder  ever sees it and no run spends anything on it.
#   vault_mb   Global. A disk cap for this project's vault. Housekeeping.
SCOPED_SETTINGS = ("reader",)


def read_session_settings():
    """Every scoped setting pinned by hand, keyed by the session that pinned it.

    /fablepack, /opuspack, /agentpack-off and /maxpack wrote one word into
    densepack-settings.json until 31 August 2026, and that file is one file
    for the whole project. A word set in one window was therefore read by
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


def write_session_settings(pinned):
    """Write the map back, newest sessions kept, oldest dropped."""
    kept = dict(list(pinned.items())[-LEADS_KEPT:])
    try:
        (tmp_dir() / SESSION_FILE).write_text(json.dumps(kept),
                                              encoding="utf-8")
    except OSError:
        return


def session_map_exists():
    """True when densepack-session.json exists on disk, whether or not it
    names the session asking.

    A project that has never pinned a scoped setting has no such file, and
    in that project the flat settings() reader still speaks for the whole
    project, the one thing SCOPED_SETTINGS did not exist to change:
    test_sonnet_lead.py's isolated project pins "sonnet" only in the flat
    file and a spawn with an absent model must still inherit it there.
    Once the file exists anywhere in a project, a flat settings() reader is
    residue from whichever window pinned it last, never a fact about a
    session absent from the map, and brief_pack.py answering from it for
    such a session is the bug test_briefpack.py's "an omitted model with an
    unresolved caller gets text" step exists to catch. FIXED 31 August
    2026.
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


def set_session_setting(session, key, value):
    """Pin one scoped setting for one session. An empty session pins nothing.

    A run with no session behind it, dpctl.py from a terminal, cannot say who
    it is pinning for, and a pin that cannot be attributed is the fault this
    replaced. It is refused rather than written project wide, and False comes
    back so the caller can say so.
    """
    session = str(session or "").strip()
    if (not session or key not in SCOPED_SETTINGS
            or value not in SETTINGS_ALLOWED.get(key, ())):
        return False
    pinned = read_session_settings()
    mine = dict(pinned.get(session, {}))
    mine[key] = value
    pinned[session] = mine
    write_session_settings(pinned)
    return True


def clear_session_setting(session, key):
    """Put one setting back to its default for one session only."""
    session = str(session or "").strip()
    if not session:
        return False
    pinned = read_session_settings()
    mine = dict(pinned.get(session, {}))
    if key not in mine:
        return False
    del mine[key]
    if mine:
        pinned[session] = mine
    else:
        del pinned[session]
    write_session_settings(pinned)
    return True


def clear_session_settings(session):
    """Drop every pin one session made. No other session's pins are touched."""
    session = str(session or "").strip()
    if not session:
        return False
    pinned = read_session_settings()
    if session not in pinned:
        return False
    del pinned[session]
    write_session_settings(pinned)
    return True


def reader_override(session=None):
    """The reader profile one session pinned, or "" when it pinned none."""
    return session_settings(session).get("reader", "")


def event_reader(event):
    """The reader profile, fable, opus or sonnet, for the agent that fired
    THIS event, read from that agent's OWN transcript. None when it cannot
    be read or names an unmeasured model: a caller must not guess and must
    not fall back to the largest scored size, because an image too small
    costs correctness and an image too large costs tokens.

    resolved_reader() answers "what does the LEAD read", cached once at
    SessionStart from the lead's own transcript and never updated, correct
    for the lead's own tool calls and wrong for a subagent's: bash_pack.py
    and subagent_stop.py accept that same limitation for the reports and
    briefs they draw, because a PreToolUse Agent event carries no field
    naming the model the spawned subagent will run on, so there is nothing
    truer to read yet at the time those files draw.

    A Read event is different. It fires AFTER the subagent exists, and
    Claude Code hands every hook event, lead's or subagent's, its own
    transcript_path: a subagent's own agent-<id>.jsonl, never the lead's.
    That file's first assistant line names the model actually running,
    which is the fact JOB 1 needed, DensePack brief 29 August 2026: the
    drop folders are one per model precisely so a Read redirected through
    them draws at the READING agent's own floor, and the lead's cached
    model was landing there instead, 10 px under a Sonnet subagent's
    measured 12 px floor.
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


# The per-agent model record, added 29 August 2026 for the regression JOB 1
# left behind: event_reader() above reads a subagent's own transcript live,
# which races the file being written and returns None whenever it loses that
# race, and a caller that treated None as "give up" stopped redirecting
# altogether. This is the deterministic replacement: subagent_start.py
# writes the reader profile once, at spawn, from Claude Code's own record of
# what it spawned, and a later hook on that SAME agent's own events reads it
# back instead of re-deriving it from a transcript that may not be flushed
# yet.
#
# Keyed on the transcript's own filename stem, never on event["session_id"]:
# captured live 29 August 2026 from a real SubagentStart event, its own keys
# are session_id, transcript_path, cwd, prompt_id, agent_id, agent_type and
# hook_event_name, and subagent_start.py's existing code already treats
# session_id on THAT event as the SPAWNING session ("spawned_by"), shared by
# every agent it spawns, never this one agent's own identity. transcript_path
# is the field proven to name this one caller and no other, lead or
# subagent: event_reader() above already relies on the same fact for a
# subagent's own later Read events, so the same file's stem joins a spawn
# record to that agent's own reads without needing session_id to mean
# anything more specific than it does.
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
    return value or None


def is_subagent(event):
    """True when a subagent fired this event, not the lead.

    MEASURED 31 August 2026: a subagent's PreToolUse carries the LEAD's
    session_id and the lead's transcript_path, so neither field separates
    the two. agent_id and agent_type name the real actor, the same fields
    subagent_start.py reads at spawn. Empty or absent means the lead, so
    an actor this cannot prove keeps the lead's treatment.

    This is the shared home. delegate_gate.py, verify_gate.py,
    agent_floor.py and tier_gate.py each carry a private copy written
    before common.py was free to edit, and each says so in its own
    docstring; they can be collapsed onto this one in a later pass.
    """
    if not isinstance(event, dict):
        return False
    return bool(event.get("agent_id")) or bool(event.get("agent_type"))


def actor_reader(event=None, key=None):
    """The measured reader profile for the agent that fired THIS event, or
    None, which means DRAW NOTHING AND SEND PLAIN TEXT.

    One answer with one meaning for every caller. None covers two cases
    that must be treated alike: an actor running a model never scored on a
    condensed image, haiku or anything outside MEASURED_MODELS, and an
    actor that cannot be identified at all. Neither may be guessed at and
    neither may fall back to a pixel size. event_reader() states that
    contract in its own docstring, "a caller must not guess and must not
    fall back to the largest scored size", and the MEASURED_MODELS note
    above states it again.

    MEASURED 31 August 2026: the serving gates guessed anyway.
    bash_pack.py drew at font_size(), which is the LEAD's size, so an
    agent under a /fablepack lead was served 8 px whatever it was running,
    and drop_read_gate.py fell back to its own FALLBACK_READER at sonnet's
    12 px. Haiku readers in delegated legs were served those images and
    misread facts from them.

    Two sources, live first and deterministic second. event_reader() reads
    the agent's own transcript, which is exact once that file holds the
    agent's first assistant line and returns None while it does not yet.
    The record subagent_start.py writes once at spawn is written earlier
    than that line, so it answers whenever the live read returns None.
    record_agent_model() only ever stores a measured key, so an unmeasured
    spawn leaves no record and arrives here as None, which is already the
    right answer.

    FOR A SUBAGENT ACTOR. The LEAD keeps resolved_reader() and the
    UNKNOWN_READER fallback documented on that function, which is a
    separate and deliberate decision this does not touch. Callers pick
    between the two on the actor, not on the file being read.
    """
    live = event_reader(event) if event is not None else None
    if live:
        return live
    if key is None:
        key = transcript_key(event)
    return agent_model(key)


def actor_size(event=None, key=None):
    """The pixel size an image for this actor must be drawn at, or None
    when this actor must be sent plain text instead. See actor_reader()."""
    reader = actor_reader(event, key)
    if not reader:
        return None
    return READER_SIZES.get(reader)


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

    subagent_start.py keys the card lookup on these two fields. Its own event
    carries prompt_id and agent_id and no prompt text, and reading the
    agent's live transcript for that text races the write, the regression
    that stopped drop_read_gate.py redirecting.
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


# Every identity card a lead may name in a brief. Each name is a folder under
# instructions/<model>/ in the vault, and subagent_start.py serves every image
# in the named folder. A name outside this tuple is unknown and the worker
# card is served in its place. 31 August 2026.
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
    agent-<id>.meta.json while this hook is already running: on the live spawn
    of 31 August 2026 the hook started at 00:09:47.603Z and the file landed at
    00:09:48, so agent_meta_fields() read nothing and the spawn was served the
    worker card its brief had not asked for. prompt_id and agent_type are on
    the event, so neither can arrive late. The description is still preferred
    when it does arrive in time, because it separates two spawns of one agent
    type inside one turn.
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

    Used by watchdog.py as the progress signal: a stat() call on one file,
    never a read of its contents. Reading the file to find the last message
    the way cache_watch.py does for the lead's own transcript costs more
    than this loop can afford at a 2 to 3 minute wake, and the mtime answers
    the only question a poll needs answered, whether the agent wrote
    anything since the last wake. None when the id is empty or no such file
    is found.
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

    Shared by stop_gate.py and delegate_gate.py, both of which need to know
    whether an edit has landed yet in the CURRENT session, not a subagent's.
    Reuses transcript_path and FILE_TOOLS rather than a new per-session state
    file: the transcript already carries this fact, so no gate needs to
    write one down.

    Measured from DENSEPACK-FAILURES.md, run 20260830-011603:
    auth-token__densepack__haiku__3 and csv-sum__densepack__haiku__3 both
    closed with a claimed fix, and delegate_gate.py forced a delegation
    ladder in other cells before any code was written, while Write and Edit
    had not run at all. A session where this returns False is a session
    that has not yet touched the one file it must change.
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


def resolved_reader(session=None):
    """The reader profile in force: the model the lead is running on.

    `session` names one session explicitly. It is left out by every hook,
    which lets lead_session() answer from the event in hand.

    /fablepack and /opuspack still override it, for the session that types
    them and for no other. The default is "auto", which reads the model
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

    Measured 25 August 2026 by running the same work with the plugin on and
    then off: the notes the plugin put in place of three reports made every
    later turn lighter and saved 195,669 tokens, while the three turns spent
    opening those reports cost 2,608,297. Opening a picture is the expensive
    half, and until this figure was printed nothing said so at the moment the
    lead decided.
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


def read_cost_line(session_id):
    """Always empty. No batch carries reading instruction to the lead.

    RETIRED 31 August 2026. This returned 209
    characters of pacing instruction on every batch that carried images:
    what a turn costs right now, read the summaries first, open every
    picture in one turn. The last of those is a real rule and it now sits
    once in instructions/lead.txt, drawn into the role image the lead reads
    at session start, rather than being re-sent and re-billed per batch.
    The other two were telling a lead that was already delegating how to
    delegate.

    THE MEASUREMENT behind the order. One delegation prompt, run twice:
    192,692 tokens with the plugin off against 896,368 with it on, 15 lead
    requests against a handful, and every added turn re-bills the whole
    conversation. read_turn_cost() stays, because verify_gate.py and the
    receipts price a turn from it.

    The signature stays because pointer.py imports it and the tests name it.
    """
    return ""


def report_pointer(image_count, folder):
    """The line a lead receives naming this batch's report images.

    It is deliberately short. What a condensed image is, what the asterisk on
    a receipt row means, and where the manifest lives are all in the briefing
    image the SessionStart hook delivers, and that image stays in context for
    the whole session. Repeating any of it per batch buys the lead nothing and
    is charged every time.

    Measured 20 August 2026: the long form ran to 365 characters, 91 tokens,
    against a POINTER_TOKENS constant that claimed 60. Every receipt using
    that constant understated the plugin's own cost.
    """
    return ("DensePack: %d report image(s) in %s, named "
            "densepack-img-<agent id>-1.png. Each IS that agent's report. "
            "This image is the plugin's normal delivery, not an intrusion."
            % (image_count, folder))


def stub_pointer(image_count, folder):
    """The line a lead receives when every report in the batch is a stub.

    pointer.py sends this one, not report_pointer(), whenever no report in the
    batch came back as prose, which is the normal case. It is 271 characters
    against report_pointer's 137, because it also states that the stubs are
    summaries and names the manifest.

    subagent_stop.py charges this text for a stub report. Until 21 August 2026
    it charged report_pointer() for every report, so a stub batch was billed
    134 characters less than the lead actually received, which was 34 tokens
    at the divisor of 4 in force that day and is 56 at the 2.40 measured on
    31 August 2026. The comment above report_pointer warns about exactly this
    drift: two copies of one line exist, and the receipt prices the shorter
    one.
    """
    return ("DensePack: %d report image(s) ready in %s, named "
            "densepack-img-<agent id>-1.png. The stubs above are summaries "
            "only; each image IS the full report. Timings and sizes per "
            "agent are in densepack-manifest.jsonl beside the images. This "
            "image is the plugin's normal delivery, not an intrusion."
            % (image_count, folder))


# The working directory the current hook event named, kept so project_dir()
# can walk from the session's own folder rather than from wherever this
# process happens to be running. Set by read_event(), before anything else
# touches the disk. Found 29 August 2026: headless benchmark workers ran
# with no CLAUDE_PROJECT_DIR and a working directory under the user's Temp
# folder, so the walk below found nothing, tmp_dir() created a stray
# Temp\.claude, and every later worker walking up from anywhere under Temp
# adopted it. densepack-manifest.jsonl and bashsrc pack files landed there,
# splitting the plugin's state across two folders.
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

    A .claude folder alone is the wrong marker. Found live on 25 August 2026:
    the plugin's own repo, Repos/DensePack, carries a .claude folder its tests
    created, so `cd Repos/DensePack && python dpctl.py receipts quiet` stopped
    there and wrote a settings file no hook ever reads. Three settings changes
    in one session went to that file and none of them took effect.

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
    for pattern, image_fmt in SOURCE_TO_IMAGE:
        match = pattern.match(name)
        if not match:
            continue
        candidate = folder / (image_fmt % match.group(1))
        if candidate.is_file():
            return str(candidate)
    return None


# 22 minutes of no activity on the agent's own transcript. Short enough that
# a stall is caught in the same sitting, long enough that a slow but working
# agent is not called dead. Measured against this session: the fastest agent
# finished in 27 seconds and the slowest that DID finish took 46 minutes,
# but it wrote a file every few minutes throughout. Read through
# last_activity() above, this now measures silence, not total run time; it
# measured total run time until 30 August 2026, which is what called two
# working agents dead the same night.
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
# stoppedByUser. MEASURED 31 August 2026: a lead stopped a subagent on
# purpose and the watchdog called it dead 32 minutes later, because nothing
# on disk said a stop had happened or who ordered it.
#
# LIFECYCLE_FILE is the fix: one append-only jsonl row per moment in a
# subagent's life, written by the three places that already run at each of
# those moments, so no new process has to be started to keep it.
# subagent_start.py appends "spawned", subagent_stop.py appends "ended",
# and pointer.py, the one hook Claude Code already fires after every tool
# call including TaskStop, appends "stopped-by-lead" when the tool call it
# just saw was TaskStop. unfinished_agents() below reads it next to
# stopped_by_user(), so a lead-ordered stop is excluded from silence the
# same way a user-ordered one already is.
#
# Not listed in bootstrap.py's PRUNE_PREFIXES. densepack-manifest.jsonl
# beside it is deliberately never pruned by age, "the record, not the
# working copy", and this file is the same kind of record for the same
# reason, so it is left to grow the same way rather than given a cap
# nothing measured.
LIFECYCLE_FILE = "densepack-lifecycle.jsonl"


def lifecycle_path():
    return tmp_dir() / LIFECYCLE_FILE


def append_lifecycle(agent_id, event, lane=""):
    """Append one row: this moment, this agent, this event, this lane tag.

    Never rewritten, so a crash mid-write loses at most the row being
    added, the same append-only shape watchdog_path() and the pending queue
    already use. A write failure is silent, the same failure mode every
    marker write in this file already chooses: a lost lifecycle row is a
    smaller problem than a hook that stops working.
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


def _manifest_rows(path):
    """Every JSON line in a file, skipping any line that will not parse.
    Read here rather than imported, because the readers that build the
    tables live in pointer.py and importing that from here would make a
    loop. A read failure returns nothing: this check must never be the
    reason a reply cannot land."""
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

    This is the shared scan stale_agents() below and watchdog.py both need:
    stale_agents() wants only the ones quiet past STALE_AFTER, watchdog.py
    wants the full live set so it knows when NONE are left and it can stop
    polling. One scan, read once here, so the two never drift into two
    different ideas of "still running".

    Matched by the start marker each agent writes on SubagentStart
    (densepack-start-<agent id>, see subagent_start.py), never by start
    time. A spawn row from PreToolUse carries no agent id, so pairing it to
    a finished run by matching timestamps pairs the wrong rows whenever two
    or more agents are in flight at once: in one session that paired three
    finished agents to the wrong spawn and reported them silent, and left
    two agents that had actually died unmatched and unreported. The marker
    carries the real agent id in its own filename, so this reads that
    instead and never has to guess a pairing.

    A manifest row for the id, at any state including a provisional one
    written by the report-file net's first pass, means the agent already
    reached SubagentStop at least once and is not silent. A marker whose own
    recorded session does not match, or that cannot be parsed, is left out
    rather than attributed by guesswork, since a wrong guess moves the alarm
    onto the wrong agent, which is the exact fault being fixed here.

    An agent the user stopped is left out too: Claude Code's own record of
    that (stopped_by_user) means the silence has an explanation already and
    is not a stall in progress. An agent the LEAD stopped through the
    TaskStop tool is left out the same way, read from this plugin's own
    lifecycle record (stopped_by_lead) since Claude Code's own record only
    ever covers a literal user interrupt.
    """
    session = str(session or "")
    if not session:
        return []

    finished_ids = {str(r["agent_id"]) for r in
                    _manifest_rows(tmp_dir() / "densepack-manifest.jsonl")
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
            # A bare number, either the format used before 21 August 2026 or
            # a marker subagent_stop.py rewrote while an agent waits out the
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
        # An agent the user stopped is not a silent one. Checked last, because
        # it reads a file per candidate and almost every marker is filtered out
        # above without touching the disk.
        if stopped_by_user(agent_id):
            continue
        if stopped_by_lead(agent_id):
            continue
        out.append((agent_id, started))
    return out


def last_activity(agent_id, started):
    """The timestamp of the newest evidence this agent has done anything:
    its own transcript file's mtime when that file exists and is newer than
    started, otherwise started itself.

    FIXED 30 August 2026. stale_agents() used to measure quiet as "now minus
    started", total elapsed run time, not silence. Two working agents were
    reported dead tonight for exactly that reason: both had files on disk
    the whole time and a transcript still growing, and both ran past
    STALE_AFTER simply by taking that long, a healthy fact for a real task,
    not a stall. A transcript grows on every tool call and every message
    the agent sends, so its mtime is the plain record of the last time this
    agent did anything at all, and is read here with one stat() call rather
    than a parse of the file's contents.
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
    STALE_AFTER filter on top of it. watchdog.py calls the same
    last_activity() so a slow but working agent reads as alive in both
    places, never flagged by one and cleared by the other.
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
    the spawn happens, so the file exists even for the far more common case
    where the brief never packs. Never drained: pointer.py and dpctl.py read
    the whole file back to build the delegation table, and nothing deletes a
    line from it."""
    with delegation_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def pending_path():
    return tmp_dir() / "densepack-pending.jsonl"


def pending_entries():
    """Every row bash_pack.py has appended, in file order. Read fresh every
    call, the same as pointer.py's delegation_entries(), rather than cached,
    because the file can gain a row between two calls in one session."""
    path = pending_path()
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# The sessions allowed to collect report pointers. SessionStart adds its own
# id here; a subagent never fires SessionStart, so a subagent is never on the
# list and cannot take the lead's images. It is a LIST because a project is
# often open in two windows at once: a single slot meant the second window to
# start silently switched the first one off. Ten is far more than anyone runs
# and keeps the file from growing.
LEADS_FILE = "densepack-lead-sessions.json"
LEADS_KEPT = 10


def read_leads():
    """Every session allowed to collect, newest last. The single-id file the
    plugin wrote before 19 August 2026 still counts, so an upgrade mid-session
    does not lose the lead."""
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
    (tmp_dir() / LEADS_FILE).write_text(json.dumps(leads), encoding="utf-8")
    # The old single-id file is kept in step, so a downgrade still works.
    (tmp_dir() / "densepack-lead-session").write_text(str(session_id),
                                                     encoding="utf-8")
    return leads


OFF_FLAG = "densepack-off"


def off_flag_path(session=None):
    """The off switch file one session writes, densepack-off-<session id>.

    The switch was a single bare file from 15 August 2026 to 31 August. A
    project open in two windows shares one .claude/tmp, so /densepack-off
    typed in either window stopped packing in both, and the other window went
    on paying full price with nothing on screen to say why. Measured 31 August
    2026: a parallel session ran the command and a second session lost packing
    for over an hour of agent work. The name carries the session for the same
    reason read_lead_models() is a map and LEADS_FILE is a list, which is that
    one project runs in more than one window.

    With no session id in hand the bare name comes back, and that is
    deliberate. dpctl.py run from a terminal speaks for no window, and the A B
    test the switch was built for wants the whole project stood down.
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
    """The off switch, added 15 August 2026 for clean on-against-off token tests.

    Create the file .claude/tmp/densepack-off-<session id> and every hook in
    that session stands down: no instructions injected, no packing, no
    receipts. Delete the file and the plugin is back. No settings edit and no
    restart, so an A B test is two runs of the same task with the flag flipped
    between them. /densepack-off writes the flag, /densepack removes it.

    A bare densepack-off with no session on it still stops every session. It
    is what versions before 31 August 2026 wrote, and a file with no session
    attached cannot be read as belonging to one, so it is honoured the way
    those versions honoured it. dpctl.py on deletes any bare file it finds, so
    one left behind cannot outlive a /densepack.

    A subagent's hook events name the session that owns the agent, not the
    agent, so a lead that stands itself down stands its agents down with it.
    Measured 31 August 2026: densepack-leadmodel, the map note_lead_model()
    writes from every hook event it sees, held four ids after a day that ran
    dozens of subagents, and all four were windows.

    An event that names no session at all falls through to the session the
    last event named, and then to lead_session(), which is the resolution the
    reader size already uses.
    """
    if (tmp_dir() / OFF_FLAG).exists():
        return True
    if session is not None:
        return _off_file_set(session)
    return _off_file_set(_EVENT_SESSION) or _off_file_set(lead_session())


# The control settings behind the slash commands, added 16 August 2026.
# One JSON file, defaults filled in when it is missing or partial, unknown
# values ignored so a hand-edited file can never crash a hook.
#
#   agentpack  force:   the delegation rules supersede other plugins' and any
#                       default guidance. This is the default, so the rules
#                       apply in every conversation with no command typed.
#                       /agentpack sets it explicitly.
#              support: the delegation rules are on but SECONDARY. Rules from
#                       other active plugins and rules the user set take
#                       precedence. /agentpack puts them back to force.
#              off:     /agentpack-off, no delegation rules at all. Packing,
#                       delivery and receipts all keep working.
#   receipts   default: one 6 column table per batch of agents, plus a batch
#                       totals row at the bottom of that same table when
#                       the totals setting is on.
#              verbose: the arithmetic split into columns, a Dimensions column,
#                       a table per agent that returned several images, and
#                       the totals row's model line spelled out in full.
#              light:   the same 6 column table with no totals row at all,
#                       ever, regardless of /setpack totals on. What the plugin
#                       printed before the totals row was added.
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
#   status     on: the delegation table (model, agent, job, runtime) is
#                  appended after every batch. The default.
#              off: /setpack status off. The table stops appending. Every spawn
#                  is still recorded; only the automatic print stops.
#   keep       off, images, reports, or both: copy those files into keep_folder
#              (default <project>/densepack-archive) as each agent finishes.
SETTINGS_FILE = "densepack-settings.json"
#   maxtier    off: while the reader is opus, the lead never spawns a Fable 5
#              subagent. The default, and the safe one: a Pro plan has no
#              Fable at all, and a Max plan user who asked for Opus did not
#              ask to be billed for Fable. Nothing else is restricted.
#              on:  /maxpack, the lead may spawn Fable 5 subagents while it
#              orchestrates on Opus 5. That is the whole effect. It does NOT
#              switch cross-model image reporting on, because that is on
#              always and is not a setting.
#   stylecard  on: the standing reminder carries the writing rules.
#              Off by default because the same card is usually installed
#              as your own hook in ~/.claude/hooks, and two copies
#              would arrive twice. /stylepack turns it on for a machine that
#              does not have the personal one.
#
# There is deliberately no setting for the standing reminder itself. It states
# what a condensed image is and which size is in force, and both are what
# makes the delivery mechanism legible. A user who could switch that off
# while packing kept running would get images with nothing explaining them.
# /densepack-off is the only switch that stops it, and it stops everything.
# receipts and status default to the quiet pair as of 26 August 2026.
#
# Both used to put a table into the lead's context on every batch, and the
# lead paid for that table in the prefix of every later turn. The 41.87 per
# cent figure in HANDOFF.md was measured with both already switched off, so
# the defaults were costing money the headline number never counted.
# /setpack receipts default and /setpack status on turn them back on.
SETTINGS_DEFAULTS = {"agentpack": "force", "receipts": "quiet",
                     "totals": "auto", "keep": "both", "keep_folder": "",
                     # stylecard defaults to on as of 26 August 2026. A
                     # separate style hook, style_card.py, pasted 1,530
                     # characters into EVERY message and was removed that day.
                     # This block is 758 characters and prompt_card.py sends a
                     # full card once per session, keyed on the card's own
                     # hash, so the rules cost once instead of per message.
                     "reader": "auto", "maxtier": "off", "stylecard": "on",
                     "vault_mb": VAULT_CAP_MB,
                     "status": "off"}
SETTINGS_ALLOWED = {"agentpack": ("support", "force", "off"),
                    "reader": ("auto", "fable", "opus", "sonnet"),
                    "maxtier": ("off", "on"),
                    "stylecard": ("on", "off"),
                    "receipts": ("default", "verbose", "light", "quiet"),
                    "totals": ("auto", "on", "off"),
                    "status": ("on", "off"),
                    "keep": ("off", "images", "reports", "both")}

# The old words /setpack receipts default took. full was the measured table, line was
# one line of totals, off was silence, so each maps onto one of the four
# modes. The alias keeps old settings files and old habits working.
RECEIPTS_ALIASES = {"full": "verbose", "line": "default", "off": "quiet"}


def settings(session=None):
    """Every setting in force. session is accepted and not used yet.

    The per session layer is built and proved in tests/test_reader_scope.py
    and is not wired in here. See SCOPED_SETTINGS above for what it is for and
    what still has to happen before it can be turned on.
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
        for key, allowed in SETTINGS_ALLOWED.items():
            value = data.get(key)
            if key == "receipts" and isinstance(value, str):
                value = RECEIPTS_ALIASES.get(value, value)
            if isinstance(value, str) and value in allowed:
                out[key] = value
        folder = data.get("keep_folder")
        if isinstance(folder, str):
            out["keep_folder"] = folder
        # The vault cap is a number, not a word from a list, so the loop above
        # cannot carry it. Every other setting was a word until 25 August 2026,
        # which is why the loader read strings only and silently kept the
        # default cap whatever the file said.
        cap = data.get("vault_mb")
        if isinstance(cap, int) and not isinstance(cap, bool) and cap >= 0:
            out["vault_mb"] = cap
    return out


def write_settings(changes):
    merged = settings()
    merged.update(changes)
    (tmp_dir() / SETTINGS_FILE).write_text(json.dumps(merged, indent=2),
                                           encoding="utf-8")
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


def vault_cap_bytes():
    try:
        return int(settings().get("vault_mb", VAULT_CAP_MB)) * 1024 * 1024
    except (TypeError, ValueError):
        return VAULT_CAP_MB * 1024 * 1024


def vault_folders():
    """Every conversation folder in the vault, oldest first, with its size.

    Skips instructions/, drop/ and drops/, PLAN-FABLE.md step 1, 29 August
    2026. instructions/ holds the role, shared and full rules images
    bootstrap.py draws at session start; drop/<model> is the standing
    folder a user copies a file into to have it drawn, and drops/ is
    where that drawing lands. All three are install state, not a
    conversation's working copy, and must survive the cap eviction below
    the same way prune_old_files() already leaves them alone.
    """
    base = vault_dir()
    if not base.is_dir():
        return []
    out = []
    for folder in base.iterdir():
        if not folder.is_dir():
            continue
        if folder.name in ("instructions", "drop", "drops"):
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
    # nothing else was left to delete, so the cap held for every conversation
    # except the one actually filling the disk. Found by Fable 5 on
    # 25 August 2026, reading common.py against its own cap.
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
    /setpack keep both chooses what a user KEEPS permanently, and this is the working
    copy the plugin falls back on. Costs disk and no tokens, because nothing
    it writes enters the conversation.

    A copy failure never breaks delivery: the caller's work is already done.
    """
    import shutil
    folder = vault_dir(session_id)
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
    nothing deletes automatically. This is what /setpack keep both <conversation> does.
    Returns the destination, or None when that conversation is not in the
    vault."""
    import shutil
    src = vault_dir(session_id)
    if not src.is_dir():
        return None
    conf = settings()
    base = (Path(conf["keep_folder"]) if conf["keep_folder"]
            else project_dir() / "densepack-archive")
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

    Set 18 August 2026, redefined 24 August 2026 to stop gating BATCH
    TOTALS: default mode holds the whole conversation's own totals row back
    for the wrap-up, verbose prints it every time, and /setpack totals on or
    /setpack totals off overrides the mode either way. Quiet and light print no
    totals row of any kind, so this answer never reaches them.
    """
    choice = settings()["totals"]
    if choice == "on":
        return True
    if choice == "off":
        return False
    return receipts_mode() == "verbose"


def status_shown():
    """True when the delegation table (model, agent, job, runtime) is
    appended automatically after a batch. /setpack status off sets this off; the
    table itself is still recorded either way, in densepack-delegation.jsonl,
    only the automatic print stops."""
    return settings()["status"] == "on"


def read_event(raw=None):
    """The hook event on stdin, with the session it names put in hand.

    Six hooks used to check disabled() on their first line and read their
    event after it: bootstrap, brief_pack, pointer, session_end, stop_gate and
    subagent_stop. The off switch was one bare file then and needed no session
    id. It is per session since 31 August 2026, so those hooks read the event
    first and pass the id they find on it.

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
        return True
    except ImportError:
        return False


def append_queue(entry):
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
    totals_path().write_text(json.dumps(totals), encoding="utf-8")


def drain_queue():
    path = queue_path()
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    path.unlink(missing_ok=True)
    return entries
