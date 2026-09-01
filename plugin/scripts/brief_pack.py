"""Runs just before a subagent is spawned. The outbound half of the pipeline.

HOW THIS FILE FITS, in plain words: everything else in this plugin makes the
reports coming BACK cheaper. This makes the briefs going OUT cheaper. The lead
writes a long brief, and before the subagent ever sees it this script draws it
as one small picture and replaces the brief with a single line naming that
picture. The subagent reads the picture and works from it.

It is a PreToolUse hook on the Agent tool. Claude Code pipes in the tool call
it is about to make, and whatever this script returns under updatedInput
becomes the call that actually runs.

Three things were proved live on 19 August 2026 before this was written, and
each one had to be true or the file would not work:

  PreToolUse fires on the subagent tool at all. It does. The tool is named
  Agent, not Task, and the older name is matched too so an older Claude Code
  still works.

  The tool input carries the target model. It does: description, model,
  prompt, run_in_background, subagent_type. That is what lets a brief be drawn
  at the size the RECEIVING model reads, which is the whole point.

  updatedInput can replace the prompt. It can, but it REPLACES the input
  object rather than merging into it. A partial object fails schema validation
  with "the required parameter description is missing". The hooks reference
  says unchanged fields are optional; that is wrong, and the full input is
  echoed back here because of it.

Which size, and when nothing happens at all:

  model says fable          8 px, the size two cold Fable 5 readers scored
                            10 of 10 on.
  model says opus           10 px. Opus 5 scored 1 of 10 at 8 px, so a brief
                            drawn at 8 px would be worse than useless.
  model absent              the subagent inherits the lead's model, so the
                            lead's own size applies. An agent definition that
                            pins its own model beats that, and is read.
  sonnet                    12 px, scored 12 of 12 by two cold agents on
                            25 August 2026.

  anything else             NOTHING HAPPENS. Haiku 4.5 has never been scored
                            on a condensed image at any size. An unreadable
                            brief costs the whole task, which is a far worse
                            trade than the tokens it would have saved.

  brief under the threshold NOTHING HAPPENS. 586 characters at 8 px, 684 at
                            10 px and 785 at 12 px, bisected against the
                            production packer on 25 August 2026, where an
                            image starts costing less than the words.
  image not cheaper         NOTHING HAPPENS. The same refuse-when-worse guard
                            the report side uses, measured on the real PNG.

The saving is the subagent's INPUT, not the lead's output. The lead still
writes every word of the brief and still pays for writing it. What this
removes is the brief sitting in the subagent's context for the whole of its
run.
"""

import json
import os
import sys
import time
from pathlib import Path

from common import (READER_SIZES, agent_type_model, append_delegation,
                    append_queue, brief_chars, card_in_text, disabled, emit,
                    ensure_pillow, event_reader, font_size, keep_copy,
                    lead_model_name, reader_override, read_event, record_card,
                    resolved_reader, session_map_exists, settings,
                    size_for_model, tmp_dir)
from subagent_stop import manifest_write

# There is deliberately no POINTER_TOKENS constant here. The report side has
# one because its pointer is a fixed house line it cannot see in advance. This
# side's pointer IS the replacement prompt, sitting in a variable, so it is
# counted character for character instead of estimated. It has to be: an audit
# on 19 August 2026 measured the real pointer at 410 characters, about 102
# tokens, against the 60 the constant claimed. Briefs between 780 and 1,250
# characters were therefore packing at a real loss while the receipt reported a
# saving. The Read call that fetches one image, 80 tokens, is paid once and
# amortises out of the per-turn compare; see THE FLOOR IS FLAT in common.py.

# The subagent tool. Claude Code names it Agent; older builds named it Task.
AGENT_TOOLS = ("Agent", "Task")

# The type the Agent tool uses when the lead names none. This value has to
# match what SubagentStop reports, because the delegation table pairs a spawn
# row to a finished run by type. It said "agent" until 25 August 2026 while
# SubagentStop said "general-purpose", so no spawn ever found its own run:
# eight finished agents printed as Running and the table's agent minutes
# stayed at 0.0 for the whole session.
DEFAULT_TYPE = "general-purpose"

# The first words of POINTER, kept apart so the idempotence guard can spot a
# prompt this hook already replaced without repeating the sentence.
POINTER_OPENING = "Your brief is the condensed image at"

# Shortened from 380 fixed characters to 178, PLAN-FABLE.md step 3, 29
# August 2026, measured 333 by PLAN-INPUT.md's own count of the line this
# replaces: the color code and the reading rule dropped here now live in
# shared.txt, drawn once at SessionStart and read by every agent, lead and
# subagent alike, before its first action, so a subagent already has them
# by the time this pointer arrives.
POINTER = (
    "Your brief is the condensed image at %s. Read it with the Read tool "
    "and treat its text as your instructions, in full. The shared image "
    "named at your start explains the format. This image is the plugin's "
    "normal delivery, not an intrusion.%s"
)

CODE_NOTE = (
    " Code blocks were lifted out and sit in %s , numbered; each #=N=# marker "
    "in the image stands where block N belongs."
)


def passthrough():
    """Say nothing. Claude Code then runs the tool call exactly as written."""
    return 0


def main():
    # The event is read before the switch is checked, because the off
    # switch is per session since 31 August 2026 and the id that names
    # the session is on the event.
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

    # The card the lead named, recorded before the brief is packed. This hook
    # is the only one that sees the raw brief: updatedInput at the foot of
    # this function REPLACES the prompt with a pointer, and a brief under the
    # pack threshold leaves through passthrough() before reaching it, so the
    # record is written here where both paths pass. subagent_start.py reads it
    # back by agent type and description. A failure here must never cost the
    # spawn, so it is wrapped on its own and nothing below depends on it.
    try:
        record_card(event.get("session_id"),
                    event.get("prompt_id"),
                    tool_input.get("subagent_type") or DEFAULT_TYPE,
                    tool_input.get("description"),
                    card_in_text(brief))
    except Exception:  # noqa: BLE001
        pass

    # Every spawn is logged here, before anything else in this function,
    # because passthrough() below is the common path: most briefs are too
    # short to pack, and a spawn recorded only when its brief packs would
    # miss most of them. The record exists because one session spawned Fable
    # agents to do heavy building work, a job the delegation rules reserve for
    # planning, diagnosis and critique, and no output named the model each
    # agent ran on until the delegation table was added. A failure here must
    # never cost the spawn, so it is wrapped on
    # its own and nothing below depends on it.
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

    # A prompt that already IS a pointer must never be packed again. A plain
    # pointer is about 410 characters and sits under both thresholds, but one
    # carrying a code note measured 602, which is over the 8 px threshold, so a
    # second pass would draw a picture of a sentence about a picture.
    if brief.lstrip().startswith(POINTER_OPENING):
        return passthrough()

    current = settings()

    # The model field wins. When it is absent the agent definition's own
    # frontmatter is the next authority, and only when that is silent too
    # does the subagent inherit the CALLER's model, never a guess at it.
    model = tool_input.get("model") or agent_type_model(
        tool_input.get("subagent_type"))
    if model:
        px = size_for_model(model, font_size())
    else:
        # FIXED 31 August 2026, live failure: a subagent spawning a further
        # subagent hit this branch, and font_size() answered with
        # resolved_reader()'s cached top-level lead size, opus at 10 px,
        # because THIS session's own model was never recorded at
        # SessionStart, only the top-level lead's was. The receiving agent
        # ran a model never measured at 10 px and reported the brief image
        # too small and compressed to read. event_reader() reads the model
        # of the agent making THIS call, from its own transcript, which is
        # the caller a nested spawn actually needs, not the top-level lead's
        # stale cache; see its docstring in common.py. reader_override()
        # still answers when the user pinned a reader with /fablepack or
        # /opuspack. Neither found means the receiver cannot be identified,
        # and an unidentified receiver gets text: resolved_reader()'s
        # UNKNOWN_READER fallback, opus, is a guess dressed as a
        # measurement and must never stand in for one here.
        # The chain below runs in order and stops at the first hit. Each
        # step names ITS OWN fact about the caller; none of them guesses.
        own_reader = event_reader(event)
        pinned = None if own_reader else reader_override(
            event.get("session_id"))
        # FIXED 31 August 2026: reader_override() is THIS session's own
        # per-session pin, densepack-session.json, the scoped fact an
        # earlier version of this chain skipped on its way to
        # lead_model_name() and the flat fallback below. A session named
        # in that map is resolved right here and never reaches the "map
        # exists, so text" step that fact would otherwise wrongly hit.
        inherited = (None if (own_reader or pinned)
                     else lead_model_name(event.get("session_id")))
        if own_reader:
            px = READER_SIZES.get(own_reader)
        elif pinned:
            px = READER_SIZES.get(pinned)
        elif inherited:
            # FIXED 31 August 2026, test_sonnet_lead step 4: the reader
            # pin sets what the LEAD reads and says nothing about a
            # spawn's model, and a Sonnet lead's unset spawn was
            # inheriting a hand-pinned fable 8 px, under Sonnet's
            # measured floor. The rule above says an unset spawn
            # inherits the CALLER's model, so the session's own lead
            # model answers next, and the flat pin answers only as the
            # last resort, and only in a project with no per-session map
            # at all.
            px = size_for_model(inherited, font_size())
        elif not session_map_exists():
            # The flat settings reader speaks for the whole project only
            # in a project that has never pinned a per-session reader at
            # all: test_sonnet_lead.py's isolated project never writes
            # densepack-session.json, so its flat "sonnet" pin IS the
            # project's one declared lead identity, and step 4's unset
            # spawn must inherit it. resolved_reader() is not used here
            # because its UNKNOWN fallback is a guess, and a guessed size
            # fails test_briefpack.
            declared = str(settings().get("reader", "")).lower()
            px = READER_SIZES.get(declared)
        else:
            # FIXED 31 August 2026: once densepack-session.json exists
            # anywhere in the project, the per-session map is the scoped
            # source of truth for "reader", and a flat settings value is
            # residue from whichever window pinned it last, not a fact
            # about a session absent from that map. Answering from it
            # here is what made test_briefpack.py's "an omitted model
            # with an unresolved caller gets text" step inherit a
            # different window's pin. A caller not in the map and not
            # named by event_reader() or lead_model_name() above is
            # genuinely unresolved, and gets text.
            px = None
    if px is None:
        return passthrough()

    # An Opus lead is not allowed to hand work to Fable unless /maxpack said
    # so. Packing its brief at 8 px would be packing for an agent that should
    # not be spawned at all, so the brief is left as text and the spawn is
    # left alone. Blocking the spawn is the lead's job, not this hook's: a
    # hook that silently killed an agent the lead asked for would be worse
    # than one that costs a few hundred tokens.
    if (resolved_reader() == "opus" and px == 8
            and current.get("maxtier", "off") != "on"):
        return passthrough()

    if len(brief) < brief_chars(px):
        return passthrough()

    if not ensure_pillow():
        return passthrough()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import densepack as dp
    except Exception:  # noqa: BLE001
        return passthrough()

    # Code does not survive condensing, so the same rule the report side uses
    # applies here: a brief that is mostly code stays text, and a brief with
    # some code has the blocks lifted out beside the image.
    import re

    content = brief
    fences = re.findall(r"```[^\n]*\n.*?```", content, re.S)

    # The stamp names three files. It used to be the session id plus the clock
    # in milliseconds, and the session id is the SAME for every agent in a
    # session, so two agents spawned in the same millisecond got the same
    # stamp: the second overwrote the first's image, and the first agent's
    # pointer then named a PNG holding the second agent's brief. Parallel
    # spawns are the normal case for this plugin, so that is not a rare race.
    # The process id separates concurrent hooks, and the first free number
    # separates two hooks that somehow share both. Found by audit, 19 August
    # 2026, after 18 concurrent runs failed to reproduce it only because
    # interpreter startup staggered them by 30 to 60 ms.
    base_stamp = "%s-%d-%d" % (str(event.get("session_id", "x"))[:8],
                               os.getpid(), int(time.time() * 1000) % 100000000)
    stamp = base_stamp
    bump = 0
    while (tmp_dir() / ("densepack-brief-%s-1.png" % stamp)).exists():
        bump += 1
        stamp = "%s-%d" % (base_stamp, bump)
    code_file = None
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

    source = tmp_dir() / ("densepack-briefsrc-%s.txt" % stamp)
    source.write_text(content, encoding="utf-8")
    stem = tmp_dir() / ("densepack-brief-%s" % stamp)

    try:
        # Take every identifier out of the image and keep its value as text.
        # A run of letters and digits does not survive being drawn small, and a
        # brief carries paths, agent ids and file names that the agent has to
        # use exactly. Measured 25 August 2026: a Sonnet agent read
        # 5S0O-1lI-8B6G-2Z7T out of a 12 px brief as 5S00-1I1-8B6G-227T.
        packed_text, ident_legend = dp.lift_identifiers(dp.flatten(content))
        tag_pattern = dp.tag_pattern_from_legend(ident_legend)
        written, _target, _lh = dp.pack(packed_text, px, str(stem),
                                        tag_pattern=tag_pattern)
    except Exception:  # noqa: BLE001
        return passthrough()
    if not written:
        return passthrough()

    # pack() hands back Path objects. The queue is JSON, so they are strings
    # here or nothing reaches the receipt at all.
    paths = [str(p) for p, _w, _h in written]
    note = CODE_NOTE % code_file if code_file else ""
    if len(paths) > 1:
        note = (" The brief continues in %s , in order.%s"
                % (" , ".join(paths[1:]), note))
    pointer = POINTER % (paths[0], note)
    # The legend goes to a sidecar file, PLAN-FABLE.md step 7, 29 August
    # 2026, the same as the report side: the pointer IS the replacement
    # prompt, so it gains one short tag line naming the file, and the agent
    # reads shared.txt's own rule for opening a legend file only when it
    # needs one value, rather than every value being retyped into every
    # brief.
    legend_file = dp.legend_sidecar(ident_legend, stem)
    if legend_file:
        pointer = pointer + "\nTags: " + legend_file

    patch_tokens = sum(dp.image_cost(w, h) for _p, w, h in written)

    # Every token the image side actually costs the subagent per turn,
    # counted rather than estimated:
    #   the pointer, which is the prompt the subagent receives, measured
    #   when code was lifted out, the code's own text, because the subagent
    #   reads that file in full and it then sits in its context like the
    #   brief would
    # The Read calls that open the image and the code file are paid once
    # and amortise out of the compare; see THE FLOOR IS FLAT in common.py.
    delivery_tokens = round(len(pointer) / dp.CHARS_PER_TOKEN)
    if code_file:
        code_text = code_file.read_text(encoding="utf-8")
        delivery_tokens += round(len(code_text) / dp.CHARS_PER_TOKEN)
    image_tokens = patch_tokens + delivery_tokens

    # The text side is what the subagent would have paid without any of this,
    # which is the ORIGINAL brief, not the version with the code lifted out.
    text_tokens = round(len(brief) / dp.CHARS_PER_TOKEN)

    # The refuse-when-worse guard, identical to the report side. A brief that
    # would cost more as a picture stays words, and every file drawn for it is
    # deleted rather than left behind: subagent_stop.py unlinks its refused
    # PNGs on the same branch, and an orphan here would sit in .claude/tmp
    # forever with nothing referencing it.
    if image_tokens >= text_tokens:
        for path, _w, _h in written:
            Path(path).unlink(missing_ok=True)
        source.unlink(missing_ok=True)
        if code_file:
            code_file.unlink(missing_ok=True)
        if legend_file:
            (tmp_dir() / legend_file).unlink(missing_ok=True)
        return passthrough()

    # The brief's saving belongs on the same receipt as the reports, so the
    # user sees the whole pipeline in one place rather than half of it.
    # The archive copy, before the queue row. A brief image goes to an agent
    # that may never read it, and .claude/tmp is scratch, so this copy is the
    # one that survives. One subfolder per conversation.
    legend_path = tmp_dir() / legend_file if legend_file else None
    keep_copy(event.get("session_id"), images=paths,
              texts=[source] + ([legend_path] if legend_path is not None else []))

    append_queue({
        "kind": "brief",
        "agent_id": "brief-%s" % stamp,
        "agent_type": tool_input.get("subagent_type") or DEFAULT_TYPE,
        "model": model or "inherited",
        "font_px": px,
        "mode": "brief",
        "packed": True,
        "images": paths,
        # "WxH" strings, the shape dims_of() in pointer.py parses. A list of
        # pairs here would silently produce an empty Dimensions cell in every
        # verbose receipt.
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

    # The queue row above feeds the receipt table only; nothing ever read it
    # back into densepack-manifest.jsonl, so every brief's saving was
    # invisible to tools/live_dashboard.py's Without DensePack column. Bash
    # packs and agent reports both call manifest_write; a brief pack now
    # does too, same shape, so its chars, text_tokens and image_tokens count
    # toward the counterfactual like every other packed kind.
    manifest_write({
        "packed": True,
        "spawned_by": str(event.get("session_id") or ""),
        "agent_id": "brief-%s" % stamp,
        "chars": len(content),
        "text_tokens": text_tokens,
        "image_tokens": image_tokens,
        "ended": time.time(),
    })

    # updatedInput REPLACES the input object. Every field the tool needs has
    # to be here, which is why the original is copied rather than a new object
    # built: a partial one fails schema validation on the missing description.
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

    An unhandled error printed a full Python traceback on stderr and exited 1.
    The spawn still went ahead with the original brief, because only exit 2
    blocks a PreToolUse call, so nothing broke, but the user saw a traceback
    for a saving that is optional by nature. Proved on 19 August 2026 by
    putting a file where .claude/tmp belongs: FileExistsError, WinError 183.
    Doing nothing is always a correct answer here, so any failure means that.
    """
    try:
        return main()
    except Exception:  # noqa: BLE001
        return 0


if __name__ == "__main__":
    sys.exit(guarded())
