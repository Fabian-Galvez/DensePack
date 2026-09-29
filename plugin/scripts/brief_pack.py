"""The PreToolUse hook on the Agent tool. It runs before Claude Code starts a
subagent.

HOW THIS FILE FITS. The rest of this plugin lowers the cost of the reports
that return to the lead. This file lowers the cost of the briefs that the
lead sends to a subagent. When the lead writes a long brief, this script
packs it as a small image before the subagent sees it and replaces the
brief with a single line that names that image. The subagent reads the
image and works from it.

Claude Code gives the hook the tool call that it is about to make, and the
call that runs is whatever this script returns under updatedInput.

This file works because three facts about Claude Code are true.

  PreToolUse runs on the subagent tool. The tool name is Agent, not Task.
  The hook also matches the older name, and an older Claude Code still
  works.

  The tool input holds the target model. Its fields are description, model,
  prompt, run_in_background and subagent_type. The hook can then pack a
  brief for the RECEIVING model, which is the purpose of this file.

  updatedInput can replace the prompt. It REPLACES the input object and does
  not merge into it. A partial object fails schema validation with "the
  required parameter description is missing". The hooks reference says that
  unchanged fields are optional. That is wrong, and for that reason the hook
  returns the full input.

The list below shows the receiver that the hook packs for, and the cases
where the hook does nothing.

  model named               the model that the call names.
  model absent              an agent definition that sets its own model
                            comes first. Otherwise the subagent inherits the
                            model of the agent that calls it.

  receiver unidentified     NOTHING HAPPENS. An unreadable brief costs the
                            whole task. That loss is far worse than the
                            tokens that the pack saves.

  brief under the threshold NOTHING HAPPENS. Under brief_chars() the words
                            cost less than an image.
  image not cheaper         NOTHING HAPPENS. This is the same guard against a
                            loss that the report side uses, measured on the
                            real PNG.

The saving is the subagent's INPUT, not the lead's output. The lead still
writes each word of the brief and still pays for it. The pack removes the
brief text from the subagent's context for its whole run.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

from common import (READER_SIZES, agent_type_model, append_delegation,
                    append_queue, brief_chars, card_in_text, disabled, emit,
                    ensure_pillow, event_reader, font_size, keep_copy,
                    lead_model_name, reader_gets_images, reader_key_for_model,
                    reader_override, read_event, record_card,
                    resolved_reader, session_map_exists, settings,
                    size_for_model, tmp_dir)
from subagent_stop import manifest_write

# This file has no POINTER_TOKENS constant on purpose. The report side has
# one, common.POINTER_TOKENS, because report_pack_worth() prices a report
# before its pointer, a fixed house line, exists. This side's pointer IS the
# replacement prompt, held in a variable. The code counts it character for
# character and does not estimate it. A fixed estimate counts too low and
# lets a brief pack at a real loss while the receipt reports a saving.
#
# THE READ FEE. This route charges a different fee than the report route.
# subagent_stop.py charges read_turn_fee for the
# Read turn that opens the image. This route charges read_call_fee() in its
# place, the cost of the one API call that Reads the image, at the cache
# read share of the model of the agent. Without the riders below, the agent
# reads the brief image on its own first turn, a call that an unpacked
# brief never costs. When the agent Reads the image in the same message as
# the files that the brief names, the route charges nothing, because that
# message adds no call. The length floor of this route is
# common.BRIEF_FLOOR alone, and a brief of 1,000 characters or more can
# pack. A charge of read_turn_fee raises that floor by more than ten times.

# Claude Code names the subagent tool Agent, and older builds named it Task.
AGENT_TOOLS = ("Agent", "Task")

# The type that the Agent tool uses when the lead names none. This value must
# match the type that SubagentStop reports, because a spawn row pairs with a
# finished run by type.
DEFAULT_TYPE = "general-purpose"

# The first words of POINTER, kept apart. The idempotence guard uses them to
# find a prompt that this hook already replaced, without a copy of the whole
# sentence.
POINTER_OPENING = "Your brief is the condensed image at"

# The pointer holds no color code and no reading rule. Those are in
# shared.txt, which SessionStart packs once and each agent reads before its
# first action. The image comes first, because a pointer that names the text
# file of the brief with no rule makes some agents open the text file and
# not the image.
POINTER = (
    "Your brief is the condensed image at %s. Read it with the Read tool "
    "and treat its text as your instructions, in full.%s"
)

# One short sentence after the image names the text file of the brief, and
# the agent then finds it in one Grep call. The wording matches the
# last-choice wording of the session intro, and DensePack still swaps a Read
# of that file for the image.
TEXT_NOTE = (
    " The brief's text is %s . Grep it only when you need an exact string the image "
    "cannot give you."
)

# THE READ CALL THAT A SWAPPED BRIEF COSTS. The agent spends one API call
# only to Read the image. That call reads the agent's whole prefix again
# from cache and bills its own output. A measurement over 11 agents on Opus
# 5.5 gave a prefix of 29,749 to 30,134 tokens and an output of 16 to 195
# tokens. Output bills 5 times input on each current model. A cache read
# bills 0.1 of input on most models (0.05 on Opus 5.5, 0.025 on Fable 5.1).
# 0.1 is the worst case. The code counts the saving at the cheapest write,
# 1.25 times input, and counts no later read. A brief swaps only when it
# saves tokens in the worst case.
READ_CALL_PREFIX = 30000
READ_CALL_OUTPUT = 100
READ_SHARE_WORST = 0.1
OUTPUT_TO_INPUT = 5
WRITE_CHEAPEST = 1.25


# The agent Reads the image of the brief in its first message of Reads, next
# to the files that the brief names, and the image then adds no turn. The
# note names at most RIDE_MAX_FILES files, each of RIDE_MAX_BYTES or less. A
# file that the brief only mentions then cannot add a large Read that the
# agent does not need.
RIDE_MAX_FILES = 5
RIDE_MAX_BYTES = 100000
PATH_TOKEN = re.compile(r"""[A-Za-z]:[\\/][^\s'"`<>|,;()*?]+|(?:\.{1,2}[\\/])?[\w.-]+(?:[\\/][\w.-]+)+\.\w+""")
RIDE_NOTE = (" In your first message, Read it in the same message as these files the "
             "brief names: %s.")


def named_files(brief, cwd):
    """Return up to RIDE_MAX_FILES small files that the brief names and that
    exist, as absolute paths, in the order that the brief names them."""
    found = []
    for raw in PATH_TOKEN.findall(brief):
        token = raw.rstrip(".:)]'\"`")
        try:
            path = Path(token)
            if not path.is_absolute():
                path = Path(cwd or os.getcwd()) / path
            if path.is_file() and path.stat().st_size <= RIDE_MAX_BYTES:
                full = str(path.resolve())
                if full not in found:
                    found.append(full)
        except (OSError, ValueError):
            continue
        if len(found) >= RIDE_MAX_FILES:
            break
    return found


def read_call_fee(model_name):
    """Return the Read call's cost in input-token units. The cost uses the
    cache read share of the model that the agent runs on, or the worst share
    when the name does not give the model version."""
    name = str(model_name or "").lower()
    share = (0.025 if re.search(r"(fable|mythos)[-_ ]?5[-_.]1", name)
             else 0.05 if re.search(r"opus[-_ ]?5[-_.]5", name)
             else READ_SHARE_WORST)
    return READ_CALL_PREFIX * share + READ_CALL_OUTPUT * OUTPUT_TO_INPUT


# Follows the pointer when the hook moved the code blocks of the brief to a
# separate file.
CODE_NOTE = (
    " DensePack moved the code blocks to %s , numbered. Each #=N=# marker "
    "in the image stands where block N belongs."
)

# Follows CODE_NOTE on the same pointer when codepack.py packs python blocks
# with bands.
CODE_IMAGE_NOTE = (
    " DensePack packed the python blocks into banded images, in order, in %s . Read those pages "
    "with the Read tool and open the text file only for an exact byte."
)


def passthrough():
    """Print nothing. Claude Code then runs the tool call exactly as written."""
    return 0


def main():
    # The hook reads the event before it checks the switch. The off switch is
    # per session, and the session id is in the event.
    event = read_event()
    if disabled(event.get("session_id")):
        return passthrough()
    if event.get("tool_name") not in AGENT_TOOLS:
        return passthrough()

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return passthrough()
    brief = tool_input.get("prompt")
    if not isinstance(brief, str) or not brief.strip():
        return passthrough()

    # The hook records the card that the lead named before it packs the
    # brief. This hook is the only one that gets the raw brief. updatedInput
    # at the end of this function REPLACES the prompt with a pointer, and a
    # brief under the pack threshold returns through passthrough() before
    # that point. The record goes here, where the two paths pass. A failure
    # here must never cost the spawn. The call has its own try, and nothing
    # below depends on it.
    try:
        record_card(event.get("session_id"),
                    event.get("prompt_id"),
                    tool_input.get("subagent_type") or DEFAULT_TYPE,
                    tool_input.get("description"),
                    card_in_text(brief))
    except Exception:  # noqa: BLE001
        pass

    # The hook logs each spawn here, before the pack checks below, because
    # passthrough() below is the common path. Most briefs are too short to
    # pack, and a log of only the spawns whose brief packs misses most of
    # them. The record names the model that each agent runs on. A failure
    # here must never cost the spawn. The call has its own try, and nothing
    # below depends on it.
    try:
        model_seen = (tool_input.get("model")
                     or agent_type_model(tool_input.get("subagent_type"))
                     or "inherited")
        append_delegation({
            "time": time.time(),
            "session": str(event.get("session_id") or ""),
            "model": model_seen,
            "subagent_type": tool_input.get("subagent_type") or DEFAULT_TYPE,
            "description": tool_input.get("description") or "",
        })
    except Exception:  # noqa: BLE001
        pass

    # The hook must never pack a prompt that already IS a pointer. A plain
    # pointer is about 410 characters, and a pointer with a code note
    # measured 602. A pointer with riders and long paths can be longer than
    # BRIEF_FLOOR, and a second pass then packs an image of a sentence about
    # an image.
    if brief.lstrip().startswith(POINTER_OPENING):
        return passthrough()

    current = settings()

    # The model field comes first. When it is absent, the agent definition's
    # own frontmatter comes next. Only when the frontmatter names no model
    # does the subagent inherit the CALLER's model, never a guess at it.
    model = tool_input.get("model") or agent_type_model(
        tool_input.get("subagent_type"))
    # A custom agent type with no frontmatter file can set a model that this
    # resolver cannot find. Only the default type provably inherits the
    # caller. An unidentified receiver gets text.
    if not model and (
            tool_input.get("subagent_type") or DEFAULT_TYPE) != DEFAULT_TYPE:
        return passthrough()
    if model:
        px = size_for_model(model, font_size())
    else:
        # A subagent that spawns a further subagent reaches this branch. The
        # cached model of the top-level lead is not the model of the caller.
        # event_reader() reads the model of the agent that makes THIS call,
        # from its own transcript. See its docstring in common.py.
        # reader_override() returns a value when the session pinned its own
        # "reader" setting. When no step of the chain below finds a model,
        # the hook cannot identify the receiver, and it gets text. The
        # UNKNOWN_READER fallback of resolved_reader() is a guess and must
        # never replace a measurement here.
        # The chain below runs in order and stops at the first hit. Each
        # step names ITS OWN fact about the caller. No step guesses.
        own_reader = event_reader(event)
        pinned = None if own_reader else reader_override(
            event.get("session_id"))
        # reader_override() is the calling session's own pin in
        # densepack-session.json. The code resolves a session named in that
        # map here, and that session never reaches the step below that gives
        # text when the map exists.
        inherited = (None if (own_reader or pinned)
                     else lead_model_name(event.get("session_id")))
        if own_reader:
            px = READER_SIZES.get(own_reader)
        elif pinned:
            px = READER_SIZES.get(pinned)
        elif inherited:
            # The "reader" pin sets what the LEAD reads. It does not set a
            # spawn's model. A spawn with no model inherits the CALLER's
            # model. The session's own lead model comes next. The flat pin
            # applies only as the last choice, and only in a project with no
            # per-session map at all.
            px = size_for_model(inherited, font_size())
        elif not session_map_exists():
            # The flat "reader" setting applies to the whole project only in
            # a project that never pinned a per-session "reader". There the
            # flat pin IS the project's one declared lead identity. The code
            # does not use resolved_reader() here because its UNKNOWN
            # fallback is a guess.
            declared = str(settings().get("reader", "")).lower()
            px = READER_SIZES.get(declared)
        else:
            # When densepack-session.json exists anywhere in the project, the
            # per-session map is the scoped source of truth for "reader". A
            # flat settings value is old data from the window that pinned it
            # last. A caller that is not in the map, and that event_reader()
            # and lead_model_name() above do not name, is unresolved and gets
            # text.
            px = None
    if px is None:
        return passthrough()
    # The receiver is the first name that the chain above matched. Sonnet
    # gets an image brief, and /max-off sends it text.
    receiver = (model or event_reader(event)
                or reader_override(event.get("session_id"))
                or lead_model_name(event.get("session_id"))
                or settings().get("reader", ""))
    if not reader_gets_images(reader_key_for_model(receiver)):
        return passthrough()

    # brief_chars() gives the same floor for each px, because each size is
    # CODE_PX, the one image size for all models.
    if len(brief) < brief_chars(px):
        return passthrough()

    if not ensure_pillow():
        return passthrough()

    # Without the key the hook cannot seal anything, and DensePack then never
    # swaps a Read of the brief's text for its image. The brief goes as text.
    from common import seal_key
    if seal_key() is None:
        return passthrough()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import densepack as dp
    except Exception:  # noqa: BLE001
        import traceback; traceback.print_exc()
        return passthrough()

    # A pack does not keep code exact. The rule of the report side applies
    # here too. A brief that is mostly code stays text. A brief with some
    # code has its blocks moved to a file beside the image.
    import re

    content = brief
    fences = re.findall(r"```[^\n]*\n.*?```", content, re.S)

    # The stamp names three files. The session id is the SAME for each agent
    # in a session, and parallel spawns are the normal case. The session id
    # and the clock alone can give two spawns one stamp, and the second then
    # overwrites the image of the first. The process id separates concurrent
    # hooks, and the first free number separates two hooks that share the
    # two values.
    base_stamp = "%s-%d-%d" % (str(event.get("session_id", "x"))[:8],
                               os.getpid(), int(time.time() * 1000) % 100000000)
    stamp = base_stamp
    bump = 0
    while (tmp_dir() / ("densepack-brief-%s-1.png" % stamp)).exists():
        bump += 1
        stamp = "%s-%d" % (base_stamp, bump)
    code_file = None
    code_images = []
    if fences:
        code_chars = sum(len(b) for b in fences)
        if code_chars > len(content) * 0.5:
            return passthrough()
        parts = ["Code blocks lifted out of the packed brief %s." % stamp,
                 "Each #=N=# marker in the image stands where block N belongs.",
                 ""]
        for n, block in enumerate(fences, 1):
            content = content.replace(block, "#=%d=#" % n, 1)
            parts.extend(["#=%d=#" % n, block, ""])
        code_file = tmp_dir() / ("densepack-briefcode-%s.txt" % stamp)
        code_file.write_text("\n".join(parts), encoding="utf-8")
        # codepack.py packs a python block with bands, at the size of this
        # brief, and the subagent reads it from the image. A block with any
        # other fence label stays text only.
        import codepack
        code_images, _drawn = codepack.pack_fenced(
            fences, px, str(tmp_dir() / ("densepack-briefcode-%s" % stamp)))

    source = tmp_dir() / ("densepack-briefsrc-%s.txt" % stamp)
    # newline="" keeps the brief's own line endings. This file is then the
    # exact text that the pointer says it is.
    with open(source, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    stem = tmp_dir() / ("densepack-brief-%s" % stamp)

    try:
        # When densepack.LIFT_IDENTIFIERS is on, the lift takes each
        # identifier out of the image and keeps its value as text. The lift
        # is off by default, and the text then stays unchanged. A model can
        # misread a run of small letters and digits in an image, and a brief
        # holds paths, agent ids and file names that the agent must use
        # exactly. The brief keeps real newlines, because the pilcrow mark of
        # flatten() renders as the word "[pilcrow]" at each line end.
        packed_text, ident_legend = dp.lift_identifiers(dp.flatten(content, "\n"))
        # The code renderer packs the brief, with black letters, blue digits,
        # red marks and a key row. When the lift is on, the tags stay. The
        # sidecar holds a path or an id exactly, and the image shows [#N] in
        # its place.
        import codepack
        from common import code_size
        # reader_name reaches the manifest row only. pack_code packs one
        # image for all models.
        reader_name = resolved_reader() or "opus"
        written, _target, _lh = codepack.pack_code(
            packed_text, code_size(px, reader_name), str(stem), python=False,
            legend=None, reader=reader_name, title="brief")
    except Exception:  # noqa: BLE001
        import traceback; traceback.print_exc()
        return passthrough()
    if not written:
        return passthrough()

    # The queue is JSON, and each path must be a string here, or nothing
    # reaches the receipt.
    paths = [str(p) for p, _w, _h in written]
    note = CODE_NOTE % code_file if code_file else ""
    if code_images:
        note += CODE_IMAGE_NOTE % " , ".join(code_images)
    if len(paths) > 1:
        note = (" The brief continues in %s , in order.%s"
                % (" , ".join(paths[1:]), note))
    pointer = POINTER % (paths[0], note) + TEXT_NOTE % source
    riders = named_files(brief, event.get("cwd"))
    if riders:
        pointer += RIDE_NOTE % ", ".join(riders)
    # The legend goes to a sidecar file, the same as on the report side. The
    # pointer IS the replacement prompt. It gets one short tag line that
    # names the file. The agent opens the legend file only when it needs one
    # value, and no brief repeats all values.
    legend_file = dp.legend_sidecar(ident_legend, stem)
    if legend_file:
        # The full path, never the bare name. An agent that gets only the
        # file name searches the whole disk for it.
        pointer = pointer + "\nTags: " + str(tmp_dir() / legend_file)

    # With the seal, DensePack swaps a Read of the text of the brief for the
    # image beside it only where the local plugin wrote the pair. One seal
    # covers the whole pack, and each image that a model gets is one that
    # the local plugin wrote.
    from common import seal_pair
    seal_pair(source, [Path(p).name for p, _w, _h in written])

    patch_tokens = sum(dp.image_cost(w, h) for _p, w, h in written)

    # The code counts, and does not estimate, each token that the image side
    # costs the subagent for each turn. These are the pointer, which is the
    # prompt that the subagent gets, and the text of the code file when the
    # hook moved the code blocks to it. The subagent reads that file in
    # full, and it then stays in its context the same as the brief.
    # This per-turn count does NOT include the Read calls that open the image
    # and the code file. When there are no riders, the guard below charges
    # the Read call of the image once, with read_call_fee(). It charges
    # nothing for the code file. See THE READ FEE note at the head of this
    # file.
    delivery_tokens = round(len(pointer) / dp.CHARS_PER_TOKEN)
    if code_file:
        code_text = code_file.read_text(encoding="utf-8")
        delivery_tokens += round(len(code_text) / dp.CHARS_PER_TOKEN)
    image_tokens = patch_tokens + delivery_tokens

    # The text side is the cost for the subagent without this hook. That is
    # the ORIGINAL brief, not the version without its code blocks.
    text_tokens = round(len(brief) / dp.CHARS_PER_TOKEN)

    # The guard against a loss, the same as on the report side. A brief that
    # costs more as an image stays words, and the hook deletes each file that
    # it packed for the brief. subagent_stop.py unlinks its rejected PNGs on
    # the same branch. An orphan here stays in .claude/tmp with nothing that
    # names it.
    # The code also charges the Read call that the swap adds. The brief swaps
    # only when the tokens that it saves, at the cheapest write, pay for that
    # call.
    # An agent with no model of its own runs on the caller's model.
    runs_on = tool_input.get("model") or lead_model_name(event.get("session_id"))
    # With riders, the agent reads the brief in a message of Reads that it
    # makes anyway. The swap adds no call and needs only a real saving.
    fee = 0 if riders else read_call_fee(runs_on)
    if (text_tokens - image_tokens) * WRITE_CHEAPEST <= fee:
        for path, _w, _h in written:
            Path(path).unlink(missing_ok=True)
        source.unlink(missing_ok=True)
        if code_file:
            code_file.unlink(missing_ok=True)
        for page in code_images:
            Path(page).unlink(missing_ok=True)
        if legend_file:
            (tmp_dir() / legend_file).unlink(missing_ok=True)
        return passthrough()

    # The receipt shows the saving of the brief next to the reports, and the
    # whole pipeline is then in one place.
    # The code makes the archive copy before the queue row. An agent can
    # leave a brief image unread, and .claude/tmp is scratch space. This
    # copy is the permanent one, in one subfolder for each conversation.
    legend_path = tmp_dir() / legend_file if legend_file else None
    # The seal goes with them. Without it, a Read of the vault copy finds no
    # sealed pair and returns the whole text.
    keep_copy(event.get("session_id"), images=paths,
              texts=[source, Path(str(source) + ".seal")]
              + ([legend_path] if legend_path is not None else []))

    append_queue({
        "kind": "brief",
        "agent_id": "brief-%s" % stamp,
        "agent_type": tool_input.get("subagent_type") or DEFAULT_TYPE,
        "model": model or "inherited",
        "font_px": px,
        "mode": "brief",
        "packed": True,
        "images": paths,
        # "WxH" strings, the form that dims_of() in pointer.py parses. A list
        # of pairs here gives an empty Dimensions cell in each verbose
        # receipt, with no error.
        "dims": ["%dx%d" % (w, h) for _p, w, h in written],
        "pixels": sum(w * h for _p, w, h in written),
        "chars": len(content),
        "text_tokens": text_tokens,
        "image_tokens": image_tokens,
        "patch_tokens": patch_tokens,
        "delivery_tokens": delivery_tokens,
        "started": time.time(),
        "ended": time.time(),
    })

    # The queue row above goes to the receipt table only. The brief also
    # writes a manifest row, in the same form that bash packs and agent
    # reports write. Its chars, text_tokens and image_tokens then count in
    # the manifest totals, like each other packed kind.
    manifest_write({
        "packed": True,
        "spawned_by": str(event.get("session_id") or ""),
        "agent_id": "brief-%s" % stamp,
        "chars": len(content),
        "text_tokens": text_tokens,
        "image_tokens": image_tokens,
        "ended": time.time(),
    })

    # updatedInput REPLACES the input object. Each field that the tool needs
    # must be here. For that reason the code copies the original and does not
    # build a new object. A partial object fails schema validation on the
    # missing description.
    new_input = dict(tool_input)
    new_input["prompt"] = pointer
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": new_input,
        }
    })
    return 0


def guarded():
    """Never let an exception out of this hook.

    Only exit 2 blocks a PreToolUse call. An unhandled error still lets the
    spawn run with the original brief, but it prints a full Python traceback
    on stderr for a saving that is optional. Doing nothing is always a
    correct answer here. Any failure returns 0 and does nothing.
    """
    try:
        return main()
    except Exception:  # noqa: BLE001
        return 0


if __name__ == "__main__":
    sys.exit(guarded())
