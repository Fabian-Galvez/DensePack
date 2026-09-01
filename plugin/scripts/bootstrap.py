"""Runs once when a session opens. The doorman.

HOW THIS FILE FITS, in plain words: four jobs before anything else happens.
Make sure Pillow, the drawing library, is installed in the plugin's own private
folder, because without it no image can be drawn and every other script quietly
stands down. Tell the assistant how to treat a condensed-prompt image the user
pastes, so the shortcut and right-click tools work without the user typing an
explanation. Show the user the savings total the last conversation left behind.
Warn the user when the drawing size does not match the model they are running,
or when Pillow could not be installed.

ORIGINAL NOTE: SessionStart hook. Four jobs, all quiet.

Install Pillow once into CLAUDE_PLUGIN_DATA, which survives plugin updates.
Claude Code auto-installs Node dependencies only, so the Python half is this
hook's job. Never blocks a session. If Pillow cannot be installed, every other
hook degrades to doing nothing and text flows exactly as it would without the
plugin, and the user is told so.

Three things go to the user through systemMessage, the field Claude Code shows
the user directly: last conversation's totals table, a reader mismatch, and a
failed Pillow install. Everything else goes to the lead as context.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (resolved_reader,
                    add_lead, disabled, emit, ensure_pillow, font_size,  # noqa: E402
                    MEASURED_MODELS, read_event, settings, tmp_dir, vault_dir)

# The delegation section of BRIEFING.md sits behind this marker so the three
# /agentpack modes can include it, preface it, or drop it.
DELEGATION_MARK = "<!-- DELEGATION -->"

# {READER} in BRIEFING.md becomes the line below for the size this session
# draws at. The sizes are the measured ones: 8 px was read by two cold Fable 5
# readers at 10 of 10 on 14 August 2026, and 10 px by two cold Opus 5 readers
# at 10 of 10 and 12 of 12 on 18 August 2026, where 8 px gave Opus 1 of 10.
# A larger size is easier to read, so 10 px serves Fable as well.
READER_RULE = {
    "fable": ("This session draws at 8 px, which Fable 5 reads with every answer "
              "exact and Opus 5 and Sonnet 5 do not."),
    "opus": ("This session draws at 10 px, which Opus 5 and Fable 5 both read "
             "with every answer exact. Sonnet 5 dropped a word at this size."),
    "sonnet": ("This session draws at 12 px, which Sonnet 5 read with every "
               "answer exact on two cold agents, and which Opus 5 and Fable 5 "
               "read more easily than the sizes they were scored at."),
}

# {TIER} in BRIEFING.md becomes one of these. Only an Opus lead can break the
# rule, because a Fable lead spawning an Opus agent is always allowed, so a
# Fable session is told the rule does not apply rather than being given a
# restriction it cannot hit.
TIER_RULE = {
    ("opus", "off"): ("Right now /maxpack is OFF, so do not spawn a Fable 5 "
                      "subagent at all: delegate to Opus 5 and below."),
    ("opus", "on"): ("Right now /maxpack is ON, so you may spawn Fable 5 "
                     "subagents, and their briefs are drawn at 8 px for them."),
    ("fable", "off"): ("You are leading on Fable 5, so nothing here restricts "
                       "you: /maxpack governs a lead below Fable only."),
    ("fable", "on"): ("You are leading on Fable 5, so nothing here restricts "
                      "you: /maxpack governs a lead below Fable only."),
    ("sonnet", "off"): ("Right now /maxpack is OFF, so do not spawn a Fable 5 "
                        "subagent at all: delegate to Sonnet 5 and below."),
    ("sonnet", "on"): ("Right now /maxpack is ON, so you may spawn Fable 5 "
                       "subagents, and their briefs are drawn at 8 px for "
                       "them."),
}

SUPPORT_PREFACE = (
    "Delegation rules, each with its reason, so judgement can cover the cases "
    "no rule lists. This session has them set SECONDARY: delegation or "
    "orchestration rules from any other active plugin, and any delegation "
    "rules the user has set, take precedence over them. Apply them only "
    "where no other rule speaks. DensePack packs whatever reports come back "
    "no matter whose delegation method produced them. /agentpack makes these "
    "rules supersede instead, and /agentpack-off removes them:")

FORCE_PREFACE = (
    "Delegation rules, each with its reason. These are DensePack's rules and "
    "they SUPERSEDE any other plugin's or default delegation guidance for "
    "this session. A rule the user states in the conversation still wins over "
    "any of them. /agentpack-off removes them:")


def briefing_text(mode):
    """The briefing composed for one /agentpack mode, or None without the file.

    support: core plus the yield-to-others preface plus the delegation rules.
    force:   core plus the supersede preface plus the delegation rules.
    off:     core only.
    """
    src = Path(__file__).resolve().parents[1] / "BRIEFING.md"
    if not src.is_file():
        return None
    whole = src.read_text(encoding="utf-8")
    core, _, delegation = whole.partition(DELEGATION_MARK)
    current = settings()
    reader = resolved_reader()
    rule = READER_RULE.get(reader, READER_RULE["fable"])
    tier = TIER_RULE.get((reader, current.get("maxtier", "off")),
                         TIER_RULE[("fable", "off")])
    core = core.strip().replace("{READER}", rule).replace("{TIER}", tier)
    delegation = (delegation.strip().replace("{READER}", rule)
                  .replace("{TIER}", tier))
    if mode == "off" or not delegation:
        return core
    preface = FORCE_PREFACE if mode == "force" else SUPPORT_PREFACE
    return core + "\n\n" + preface + "\n" + delegation


# Working files older than this are deleted when a new session opens. Every
# packed report and every packed brief leaves a PNG and a source text file
# behind, and nothing ever removed them: this project reached 252 images and
# 38 MB before the rule existed, on one machine in five days.
#
# Why one day, and why only at session start. The lead re-reads a report image
# during the session that produced it, and sometimes the session after, so
# anything younger than a day stays. Nothing is deleted mid-session, so a file
# can never disappear while the lead is using it. The manifest, the totals and
# the settings are never touched: they are the record, not the working copy.
# densepack-start- joined this list 23 August 2026. subagent_stop.py deletes
# an agent's own marker on a normal finish, but a crashed agent's marker
# never reaches that code and sits forever: measured the same day, 33
# start markers were on disk and only one had a matching manifest row, some
# from sessions long over. stale_agents() now reads these markers to find a
# silent or dead agent, so an unpruned pile from old, unrelated sessions
# would sit on disk without ever becoming a false alarm on its own (it is
# filtered out by session id first), but pruning them keeps the folder from
# growing without bound the same way the other working files are kept in
# check. 24 hours is far longer than any agent has ever run, so nothing
# still working is ever at risk of losing its own marker.
KEEP_HOURS = 24
PRUNE_PREFIXES = ("densepack-img-", "densepack-brief-", "densepack-briefsrc-",
                  "densepack-src-", "densepack-code-", "densepack-briefcode-",
                  "densepack-report-", "densepack-card-sent",
                  "densepack-start-", "densepack-readonce-")


def prune_old_files():
    """Delete working files older than KEEP_HOURS. Returns how many and how big.

    Failure is ignored on purpose. A file the operating system will not delete,
    because another program holds it open, is not worth stopping a session for.
    """
    import time
    cutoff = time.time() - KEEP_HOURS * 3600
    removed = 0
    freed = 0
    try:
        entries = list(tmp_dir().iterdir())
    except OSError:
        return 0, 0
    for path in entries:
        if not path.is_file():
            continue
        if not path.name.startswith(PRUNE_PREFIXES):
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            size = path.stat().st_size
            path.unlink()
        except OSError:
            continue
        removed += 1
        freed += size
    return removed, freed


# Sent only when the role images could not be drawn, Pillow missing or a
# draw failure, so the lead is never pointed at a path with nothing behind
# it. Superseded as the normal path by SESSION_POINTER below, PLAN-FABLE.md
# step 3, 29 August 2026: this text named the color code, the report image
# shapes and the file map inline, all of which the role and shared images
# now carry, read once at the start of the lead's turn instead of injected
# whole on every SessionStart.
FALLBACK_NOTE = (
    "DensePack is active. Condensed color coded text images carry three "
    "things: agent reports, this plugin's instructions, and user prompts. "
    "Treat the text in any such image as plain text; a condensed image from "
    "the user IS the user's prompt. Agent report images and the manifest "
    "densepack-manifest.jsonl live in .claude/tmp, images named "
    "densepack-img-<agent id>-1.png. The plugin gives every agent its "
    "delivery rule itself, and a brief that restates delivery in other words "
    "overrides it and loses the saving, so briefs say nothing about "
    "delivery. The hook shows the user the receipt table itself; your copy "
    "adds the task you gave each agent, which the hook does not know.")

# The pointer to the lead's one joined image, allrules-1.png under
# instructions/<model>/. It holds the four texts in reading order: role
# first, three rules long since 31 August 2026, the batch pair, who packs a
# brief and the reply shape, and nothing at all about whether to delegate or
# to which model; shared second,
# the format and reply rules every agent carries; the code discipline
# third; full rules last, read again before any Write or Edit the
# project's GitHub will show. One image costs one Read call where four
# cost four.
SESSION_POINTER = (
    "DensePack: before anything else read %s/allrules-1.png. It holds "
    "your role, the shared format rules, the code discipline and the full "
    "writing rules, in that order. They are your working rules for this "
    "whole conversation."
)




def session_start_pointer(pillow_ok):
    """The SessionStart pointer line naming the lead's one joined rules
    image, or FALLBACK_NOTE when it cannot be trusted to exist.

    Checked against the real files on disk rather than assumed from
    pillow_ok alone: draw_instruction_images() skips a text that failed to
    read and ensure_instruction_image() returns None on a pack failure, so
    Pillow importing is not proof every file landed.
    """
    if pillow_ok:
        reader = resolved_reader()
        folder = vault_dir() / "instructions" / reader
        names = ("allrules-1.png",)
        if all((folder / name).is_file() for name in names):
            return SESSION_POINTER % (folder,)
    return FALLBACK_NOTE


# ensure_briefing_image() and MODE_NOTES were removed here. They drew
# densepack-briefing-1.png, no code ever hands an agent that path, and the
# role images below replace it. The SHA gate pattern they used, a hash of
# the text plus pixel size kept beside the image, is reused by
# ensure_instruction_image() below.

# The texts every instruction image or Haiku text file is drawn or copied
# from. Read from plugin/instructions/, which ships with the plugin, never
# from the vault: the vault holds the drawn output, not the source words.
INSTRUCTION_TEXTS = {"lead": "lead.txt", "worker": "worker.txt",
                     "facts": "facts.txt", "shared": "shared.txt",
                     "fullrules": "fullrules.txt", "code": "code.txt",
                     "check": "check.txt", "reader": "reader.txt",
                     "runner": "runner.txt", "tune": "tune.txt"}

# The lead's four texts, joined in reading order and drawn as one image.
# Four separate images cost four Read calls, so four turns, before the
# agent touches the task. One image costs one.
ALL_LEAD = ("lead", "shared", "code", "fullrules")

# The worker's three texts, joined the same way and for the same reason.
ALL_WORKER = ("worker", "shared", "code")

# The fact checker's two texts. code.txt is left out: a checker reads the
# repo and writes no shipped code, so the code discipline adds tokens it
# applies no rule from. 31 August 2026.
ALL_CHECK = ("check", "shared")

# The source reader's two texts. code.txt is left out for the reason
# ALL_CHECK leaves it out: a reader opens the files the brief names and
# writes no shipped code. 31 August 2026.
ALL_READER = ("reader", "shared")

# The command runner's two texts. code.txt is left out: a runner runs the
# commands the brief names and edits no source file. 31 August 2026.
ALL_RUNNER = ("runner", "shared")

# The tuning page, one text on its own. It is the procedure a lead runs
# for /tune: read this user's own records, count what they do, and name
# the fix for each count that misses a measured condition. 31 August
# 2026.
ALL_TUNE = ("tune",)

# Every joined page a lead reads, drawn once per model. The stem names the
# image file and the POINTERS.txt row. Neither page is a card: no spawn
# names either one. SessionStart points the lead at allrules, and the
# /tune command points it at tune.
JOINED_IMAGES = (("allrules", ALL_LEAD), ("tune", ALL_TUNE))

# Every identity card, one folder each under the model folder. The lead
# names a card in a brief and subagent_start.py serves every image in that
# card's folder, in filename order, so a card can grow a second page later
# with no code change and no name collision with another card. Each row is
# (card name, image stem, the INSTRUCTION_TEXTS keys joined into the page).
# A card added here is drawn for every model on the next run, and the SHA
# gate in ensure_instruction_image() leaves the pages already on disk alone.
# 31 August 2026.
CARD_IMAGES = (("worker", "workerrules", ALL_WORKER),
               ("check", "checkrules", ALL_CHECK),
               ("reader", "readerrules", ALL_READER),
               ("runner", "runnerrules", ALL_RUNNER))

# Which images each model folder draws, in the vault layout table's order.
# Fable 5 is never a worker, so its folder holds no worker image. Each pair
# is (image stem, INSTRUCTION_TEXTS key). Haiku 4.5 is absent: it has no
# measured pixel size, so nothing is drawn for it, only copied as text
# below.
MODEL_IMAGES = {
    "fable": (),
    "opus": (("role-worker", "worker"),),
    "sonnet": (("role-worker", "worker"),),
}


# Every folder the Vault layout table names, PLAN-FABLE.md step 1,
# 29 August 2026. instructions/<model> also gets made here, ahead of
# draw_instruction_images(), because the Install table lists "create the
# vault folders" and "draw each instruction image" as two separate steps:
# a folder costs nothing to make whether or not Pillow can draw into it,
# and instructions/haiku holds plain text copies that need no drawing at
# all. drop/<model> is where a user copies a file in to have it drawn at
# that model's size; drops/ is where the drawn result lands. Neither
# exists anywhere in the plugin before this step.
VAULT_FOLDERS = (
    ("instructions", "fable"), ("instructions", "opus"),
    ("instructions", "sonnet"), ("instructions", "haiku"),
    ("drop", "fable"), ("drop", "opus"), ("drop", "sonnet"),
    ("drops",),
)


def ensure_vault_folders():
    """Create every vault folder the layout table names, mkdir with
    exist_ok so a folder already there is left alone and its own file
    times never move. Runs before Pillow is even checked: nothing here
    needs it, and a resume, a clear or a compact must find every folder
    already present the same way a first run makes them."""
    base = vault_dir()
    for parts in VAULT_FOLDERS:
        base.joinpath(*parts).mkdir(parents=True, exist_ok=True)


def instruction_text(filename):
    """The shipped text of one plugin/instructions/ file, or None when it
    is missing. Missing is not an error here: a folder still gets whatever
    texts it has."""
    path = Path(__file__).resolve().parents[1] / "instructions" / filename
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def joined_text(keys):
    """The named instruction texts, stripped and joined in reading order
    with a blank line between each. An empty string when no named file
    reads, which is what draw_instruction_images() skips on."""
    parts = [instruction_text(INSTRUCTION_TEXTS[key]) for key in keys]
    return "\n\n".join(part.strip() for part in parts if part)


def ensure_instruction_image(text, px, stem_path):
    """Draw one instruction image at str(stem_path) + "-1.png", gated on a
    SHA-256 of the text plus pixel size, recorded beside the image in
    str(stem_path) + ".hash". An unchanged text draws nothing, the same
    gate ensure_briefing_image() used before it was removed. The size is
    part of the hash, so a model's measured pixel size changing redraws
    that folder's images.
    """
    if not ensure_pillow():
        return None
    digest = hashlib.sha256((text + "|%dpx" % px).encode("utf-8")).hexdigest()
    hash_file = Path(str(stem_path) + ".hash")
    first = Path(str(stem_path) + "-1.png")
    if first.is_file() and hash_file.is_file():
        if hash_file.read_text(encoding="utf-8").strip() == digest:
            return first
    stem_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import densepack as dp
        written, _target, _lh = dp.pack(dp.flatten(text), px, str(stem_path))
    except Exception:
        return None
    if not written:
        return None
    hash_file.write_text(digest, encoding="utf-8")
    return Path(written[0][0])


def write_pointers(path, lines):
    """POINTERS.txt: one line per instruction file, model, purpose and
    path, byte compare first so an unchanged set writes nothing."""
    text = "\n".join(lines) + "\n"
    encoded = text.encode("utf-8")
    if path.is_file() and path.read_bytes() == encoded:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def draw_instruction_images():
    """Draw every role, shared and full rules image for fable, opus and
    sonnet under .claude/densepack-vault/instructions/<model>/, gated on a
    SHA-256 of the text plus pixel size so unchanged text draws nothing.
    Copy the Haiku text files, byte compare first. Write POINTERS.txt,
    byte compare first. Safe to run many times a day: a resume, a clear
    and a compact each fire main() again.
    """
    base = vault_dir() / "instructions"
    lines = []
    for model, images in MODEL_IMAGES.items():
        px = MEASURED_MODELS[model]
        for stem_name, text_key in images:
            text = instruction_text(INSTRUCTION_TEXTS[text_key])
            if text is None:
                continue
            image = ensure_instruction_image(text, px, base / model / stem_name)
            if image is not None:
                lines.append("%s %s %s" % (model, text_key, image))
        for stem_name, keys in JOINED_IMAGES:
            text = joined_text(keys)
            if not text:
                continue
            image = ensure_instruction_image(text, px, base / model / stem_name)
            if image is not None:
                lines.append("%s %s %s" % (model, stem_name, image))
        for card, stem_name, keys in CARD_IMAGES:
            # Fable 5 is never a worker, and worker_folder() in
            # subagent_start.py moves a fable guess to opus, so a fable
            # worker card would never be read by anyone. Fable 5 does draw
            # the other cards: lead.txt sends it the jobs where a wrong
            # answer costs more than the run time, and a fact check is one.
            if model == "fable" and card == "worker":
                continue
            text = joined_text(keys)
            if not text:
                continue
            folder = base / model / card
            folder.mkdir(parents=True, exist_ok=True)
            image = ensure_instruction_image(text, px, folder / stem_name)
            if image is not None:
                lines.append("%s %s %s" % (model, stem_name, image))
    for text_key, dest_name in (("facts", "role-facts.txt"),
                                ("check", "role-check.txt"),
                                ("shared", "shared.txt"),
                                ("code", "code.txt")):
        text = instruction_text(INSTRUCTION_TEXTS[text_key])
        if text is None:
            continue
        dest = base / "haiku" / dest_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        encoded = text.encode("utf-8")
        if not dest.is_file() or dest.read_bytes() != encoded:
            dest.write_bytes(encoded)
        lines.append("haiku %s %s" % (text_key, dest))
    write_pointers(base / "POINTERS.txt", lines)


# One reader pairing is measured to FAIL: Opus 5 answered 1 of 10 questions
# correctly off an 8 px image on 18 August 2026. The SessionStart event carries
# the model id, so that pairing is caught here and named to the user, instead
# of the lead being asked to check its own model and mention a mismatch. The
# other pairings are either measured to work or never measured, and a warning
# on every session about an unmeasured pairing would be noise.
def reader_warning(model):
    if not model:
        return None
    if "opus" not in str(model).lower():
        return None
    if resolved_reader() in ("opus", "sonnet"):
        return None
    return ("DensePack draws report images at 8 px, the size measured for "
            "Fable 5. This session runs %s, which answered 1 of 10 questions "
            "correctly off an 8 px image on 18 August 2026. Run "
            "/opuspack to draw at 10 px, the size two cold Opus 5 "
            "readers read with every answer exact." % model)


# Without Pillow every hook stands down and the plugin saves nothing. That used
# to be silent, so a user could run a whole session believing reports were
# packed. This states it once, at session start, only when the install failed.
PILLOW_WARNING = (
    "DensePack cannot draw images: Pillow is missing and the plugin could not "
    "install it. Agent reports arrive as plain text, nothing is packed and "
    "nothing is saved. Install it with: pip install pillow")


# The delegation steering used to ride here as its own 420 character
# sentence, sent once per session on top of FALLBACK_NOTE. PLAN-FABLE.md
# step 3, 29 August 2026, retired it: lead.txt carries the same ladder,
# Haiku for a bounded lookup, Sonnet for a bounded build or measurement,
# Fable only where a wrong answer costs more than its run time, and
# SESSION_POINTER above sends the lead there before anything else runs.
# delegate_gate.py still enforces the rule after the fact.


def deliver_context(pillow_ok, model):
    parts = []
    shown = []
    marker = tmp_dir() / "densepack-last-session.md"
    if marker.is_file():
        summary = marker.read_text(encoding="utf-8").strip()
        marker.unlink(missing_ok=True)
        # The wrap-up totals reached the user only when the lead chose to
        # relay them, which is the pattern that failed seven times in one
        # session on 19 August 2026. The table now goes in systemMessage, the
        # field Claude Code shows the user directly. A quiet-mode summary
        # carries no table row and stays out of systemMessage, because quiet
        # means print nothing until the user asks.
        if any(line.startswith("|") for line in summary.splitlines()):
            shown.append(summary)
            parts.append("DensePack showed the user this table from the "
                         "conversation that just ended:\n\n" + summary)
        else:
            parts.append(summary)
    # ensure_briefing_image() and MODE_NOTES are retired: no code draws
    # densepack-briefing-1.png any more. The role images under
    # instructions/<model>/ replace it, named by the SessionStart pointer
    # line, PLAN-FABLE.md step 3, 29 August 2026.
    parts.append(session_start_pointer(pillow_ok))

    warning = reader_warning(model)
    if warning:
        shown.append(warning)
        parts.append(warning)
    if not pillow_ok:
        shown.append(PILLOW_WARNING)
        parts.append(PILLOW_WARNING)

    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(parts),
        }
    }
    if shown:
        payload["systemMessage"] = "\n\n".join(shown)
    emit(payload)


def record_lead_session(event):
    # The pointer hook fires in every session, subagents included, and the queue
    # is one shared file. Without this marker a subagent's first tool call can
    # drain the queue and receive the lead's report pointers. SessionStart fires
    # for a lead session and never for a subagent, so the ids gathered here are
    # exactly the sessions entitled to collect. Found 15 August 2026 by a
    # subagent that reported receiving a receipt for work it never did.
    # The marker holds a LIST, not one id: a project open in two windows used to
    # mean the second window to start switched the first one's receipts off for
    # good, silently. Found 19 August 2026.
    sid = event.get("session_id")
    if sid:
        add_lead(sid)


def clear_stale_blocks():
    """A blocked flag lives for one agent turn, and an asked flag for one
    agent's whole life. Either one still on disk at session start belongs to
    an agent that already finished, and leaving it would switch the
    enforcement net off for that agent id.

    densepack-asked-* joined this sweep on 31 August 2026, with the one-ask
    cap in subagent_stop.py. It is the marker that is never consumed during
    a session, so this is the only thing that clears it.

    densepack-floorpass-* joined the same day, with agent_floor.py's batch
    pass. It is keyed on one turn's prompt_id rather than an agent id, so
    it goes stale on its own the moment the turn ends; sweeping it here
    only keeps the folder tidy across sessions."""
    for pattern in ("densepack-blocked-*", "densepack-asked-*",
                    "densepack-floorpass-*"):
        for flag in tmp_dir().glob(pattern):
            try:
                flag.unlink()
            except OSError:
                pass


def install_pillow():
    """True when Pillow imports, installing it once if it does not.

    This ran after the context was delivered until 19 August 2026, so the
    first session on a machine drew no briefing image and nothing could say
    whether the install had worked. It runs first now, and its answer is what
    the session start message reports to the user.
    """
    if ensure_pillow():
        return True
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data:
        return False
    pylibs = Path(data) / "pylibs"
    pylibs.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--target", str(pylibs), "pillow"],
            capture_output=True, timeout=300)
    except Exception:
        return False
    return ensure_pillow()


def main():
    # The event is read before the switch is checked, because the off
    # switch is per session since 31 August 2026 and the id that names
    # the session is on the event.
    event = read_event()
    if disabled(event.get("session_id")):
        return 0
    clear_stale_blocks()
    prune_old_files()
    record_lead_session(event)
    ensure_vault_folders()
    pillow_ok = install_pillow()
    draw_instruction_images()
    deliver_context(pillow_ok, event.get("model"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
