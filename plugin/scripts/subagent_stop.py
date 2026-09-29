"""The SubagentStop hook. It runs each time a helper agent finishes.

HOW THIS FILE FITS. The helper is done and left a report file or plain text.
This script gives the words to densepack.py, which packs them as one small,
tightly packed image, and then measures the two prices. If the image saves
more tokens than one Read turn costs, the hook keeps the image and puts a
line on the queue for pointer.py. Otherwise the hook does nothing and the
text reaches the lead as normal.

The hook packs the finished report into a dense image. It has two modes,
best first.

  Stub mode.  The lead's context holds only the one marker line,
              DENSEPACK_REPORT: <path>, plus the image. This is the full
              saving. The hook files the agent's long report itself, and it
              never asks an agent to write the file. Permission rules reject
              such Writes. Stub mode has two routes.

              The swap route, for a foreground agent. The hook packs the
              report at the agent's first stop and does not block. It writes
              a swap file with the marker line. report_swap.py, a PostToolUse
              hook on the Agent tool, puts that line in the lead's Agent
              result in place of the report. The agent makes no extra turn.
              When Claude Code changes the text of the result, the swap misses.
              The lead then has the text, and the receipt shows the pack as
              net mode. report_swap.py gives the numbers.

              The block route, for a background agent. Its report reaches the
              lead in a message, not in an Agent result, and no hook can
              change that message. The hook blocks the stop once, and the
              agent replies with the marker line. The final message then ends
              with the marker line, and the file EXISTS, because this hook
              wrote it. The hook packs the FILE on that second stop. The
              reply is one more model request, and it reads the agent's whole
              context again.

  Net mode.   The subagent returned a long text, and the agent ignored the
              block or the hook had no reason to block. The hook still packs
              the text. The image still costs less to read again than the
              text, but the text already reached the lead once. The saving is
              partial.

A marker line that names a file that does NOT exist is a dangling pointer.
The hook never lets it through. Otherwise the lead gets a path to nothing,
and the pack never happens, with no message. The hook blocks that stop once
and recovers the report. Such a message never takes the swap route.

Three checks decide whether a report packs. A report that fails one stays
text. The first two checks run on the first pass.
- The lead must get images, and report_pack_worth() must find that a pack
  pays in dollars. The swap route pays for the lead's Read turn only. The
  block route also pays for the agent's extra turn, at the agent's rates.
- The report must be at least report_floor_chars() long. That character
  floor comes from the session's own Read turn fee, not from a fixed number.
- After the pack, the token saving must be more than read_turn_fee(), the
  cost of the Read turn that opens the image.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

from common import (MARKER, append_lifecycle, append_queue, code_size, disabled,
                    font_size, keep_copy, lead_gets_images, lead_model_name,
                    pending_path, read_turn_fee,
                    report_background_path, report_digest, report_pack_worth,
                    report_pointer, report_swap_path, stub_chars, stub_pointer,
                    write_report_swap,
                    emit, ensure_pillow, project_dir, read_event, settings,
                    tmp_dir)

# Each pattern below matches one form of "nothing happened here". That is a
# sentence about one agent's own scope that a lead can misread as a
# statement about the whole session. separate_scope_notes() moves such a
# sentence under one trailing label and does not delete it. Deleting
# information that a report gave is a fault of its own.
#
# Each pattern runs on one sentence at a time, already cut at the last
# period. For that reason [^\n]{0,160} limits the gap in the middle, and the
# pattern does not exclude a period. An excluded period blocks a file name
# such as THIRD-PARTY-NOTICES.md, whose own period is inside the sentence,
# not at its end.
SCOPE_PATTERNS = [re.compile(p, re.I) for p in (
    r"\bno\b[^\n]{0,160}?\btouch(?:ed)?\b",
    r"\bnothing\b[^\n]{0,160}?\b(?:changed|touched|modified|edited)\b",
    r"\bdid not touch\b",
    r"\b(?:was|were)\s+not\s+(?:touched|changed|modified|edited)\b",
    r"\bleft alone\b",
    r"\buntouched\b",
    r"\bnot touched\b",
)]

# One trailing label. Each report with a scope sentence gets the same label,
# and a lead that skims many reports reads it the same way each time.
SCOPE_LABEL = "Scope of this one agent, not a statement about the session:"

# One line, one or more sentences. A period or ? or ! directly followed by
# whitespace ends a sentence. In a file name such as THIRD-PARTY-NOTICES.md,
# whitespace never follows the period, and the name never splits.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# A fenced code block, ``` to ```. Compiled once, because the ask-again gate
# and the code lift split on this same shape.
_FENCE = re.compile(r"```[^\n]*\n.*?```", re.S)


def _split_sentences(line):
    """One line broken into its sentences, in order, blanks dropped."""
    return [s for s in _SENTENCE_END.split(line) if s.strip()]


def _is_scope_note(sentence):
    """True when this sentence states that something was NOT touched,
    changed, modified or edited, the shape a lead can misread."""
    return any(pattern.search(sentence) for pattern in SCOPE_PATTERNS)


def separate_scope_notes(text):
    """Move each scope sentence out of the body and under one label.

    Returns (body, notes). notes is the list of moved sentences, in their
    original order, or [] when the report has none. With no notes, body is
    the input unchanged. The function drops nothing. Each sentence in notes
    reads exactly as it did in the body, only in a new place.
    """
    kept_lines = []
    notes = []
    for line in text.splitlines():
        sentences = _split_sentences(line)
        if not sentences:
            kept_lines.append(line)
            continue
        keep = []
        moved = False
        for sentence in sentences:
            if _is_scope_note(sentence):
                notes.append(sentence.strip())
                moved = True
            else:
                keep.append(sentence)
        if not moved:
            kept_lines.append(line)
            continue
        rebuilt = " ".join(keep).strip()
        if rebuilt:
            kept_lines.append(rebuilt)
    if not notes:
        return text, notes
    body = "\n".join(kept_lines).rstrip()
    block = SCOPE_LABEL + "\n" + "\n".join(notes)
    body = (body + "\n\n" + block) if body else block
    return body, notes


# What the plugin's own handover costs, per report. This is NOT an API
# charge. Anthropic bills an image at its patch count and adds nothing. The
# pointer, the line that names this batch's images, is the whole per-turn
# fee. The code counts it from the real line, not from a constant, and the
# count stays current. The one Read tool call that opens each image, 80
# tokens of envelope, costs once, and read_turn_fee() charges it at the
# saving test below. See read_turn_fee in common.py.


def queue_text_row(base, reason, chars=0, text_tokens=0, would_cost=0):
    """A report that stays text still gets a receipt row, and you see each
    agent that returned. Its saving fields are zero, and the pointer keeps it
    out of the run total, because it saved and spent nothing."""
    entry = dict(base, mode="text", images=[], dims=[], pixels=0, chars=chars,
                 text_tokens=text_tokens, image_tokens=0, patch_tokens=0,
                 delivery_tokens=0, reason=reason, would_cost=would_cost)
    append_queue(entry)


def agent_model(event):
    """Return the model that the subagent ran on, or None.

    SubagentStop has agent_transcript_path but not the model. The model is
    on the first assistant line of that transcript. The function reads only
    the first few lines, because the file can be very large and the answer
    is always near the top. Any failure returns None, because a missing name
    on a receipt is a smaller problem than a hook that stops working.
    """
    path = event.get("agent_transcript_path")
    if not path:
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for number, line in enumerate(fh):
                if number > 60:
                    break
                line = line.strip()
                if not line or '"model"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                found = (row.get("message") or {}).get("model") or row.get("model")
                if found:
                    return str(found)
    except OSError:
        return None
    return None


def manifest_write(record):
    # The manifest is the master record of a session's agents. It has one
    # line per finished agent, added as each agent finishes. Each line holds
    # the timings and sizes, and the lead and you can check each report
    # without reading anything again. The manifest also records skipped
    # packs, with the reason, because a count of successes alone cannot prove
    # that the plugin saves more than it costs.
    # Each row has a seal, because the code that reads the manifest keeps
    # only sealed rows. See sealed_rows().
    import common
    record = dict(record, seal=common._row_seal(record))
    with (tmp_dir() / "densepack-manifest.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def marker_record(started, spawned_by):
    """Return the start marker's JSON. The two block paths below make the
    marker again, and the retry keeps its duration. They must keep
    spawned_by with it. common.unfinished_agents() matches a marker to its
    session through that field, and pointer.py charges the saving to the
    session that it names. A bare timestamp has neither.
    """
    return json.dumps({"at": started, "spawned_by": spawned_by or ""})


# One Read turn of the model's context, the fee that an image must beat
# before it saves anything. Below it, the image costs more than the text it
# replaces.
READ_TURN_TOKENS = 2000


def report_floor_chars(session_id=None):
    """Return the report length below which no image can save one Read turn.

    The floor is the lead session's own Read turn fee, common.read_turn_fee.
    The saving test below uses the same number, and the first pass and the
    second agree. A flat floor blocks some agents for the marker line, and
    their reports then reach the lead as text under the fee. Each such block
    wastes one turn.

    text_tokens is len(content) / CHARS_PER_TOKEN, and an image saves at
    most all of them. A report shorter than READ_TURN_TOKENS times
    CHARS_PER_TOKEN characters can never pass the floor that the saving test
    below uses. A request to such an agent for the marker line costs a whole
    extra turn for nothing.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import densepack as dp
    fee = read_turn_fee(session_id) if session_id else READ_TURN_TOKENS
    return int(fee * dp.CHARS_PER_TOKEN)


def swap_route(event, agent_id):
    """Return True when this agent's report reaches the lead as its Agent
    tool result. report_swap.py can then put the marker line there, and the
    hook needs no block. Return False for the block route.

    Claude Code writes agent-<id>.meta.json beside the agent's transcript at
    spawn. Its requestShape field is "foreground" or "background". A
    foreground agent returns its report as the Agent result, and the
    PostToolUse hook on the Agent tool runs after this hook. A background
    agent returns its report later in a message. report_swap.py also writes
    a background flag when an Agent result holds no report, and the flag
    wins over the meta file. A meta file with no requestShape comes from an
    older Claude Code, and such a version can lack the updatedToolOutput
    field that the swap uses. The hook then keeps the block route.
    """
    try:
        if report_background_path(agent_id).exists():
            return False
        path = Path(str(event.get("agent_transcript_path") or ""))
        if not path.name.endswith(".jsonl"):
            return False
        meta = path.with_name(path.name[:-len(".jsonl")] + ".meta.json")
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("requestShape") == "foreground"


def main():
    # The hook reads the event before it checks the switch. The off switch is
    # per session, and the session id is in the event.
    event = read_event()
    if disabled(event.get("session_id")):
        return 0
    text = event.get("last_assistant_message") or ""
    agent_id = event.get("agent_id") or "unknown"
    agent_type = event.get("agent_type") or "agent"

    ended = time.time()
    started = None
    spawned_by = ""
    lane = ""
    start_file = tmp_dir() / ("densepack-start-%s" % agent_id)
    if start_file.is_file():
        raw = ""
        try:
            raw = start_file.read_text(encoding="utf-8").strip()
        except OSError:
            raw = ""
        # JSON, or a bare timestamp from an older hook. The code reads the
        # two forms. The isinstance test is required, not defensive. A bare
        # timestamp is valid JSON too. json.loads returns a float and does
        # not raise, and .get on that float raises AttributeError.
        record = None
        try:
            record = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            record = None
        if isinstance(record, dict):
            try:
                started = float(record.get("at") or 0) or None
            except (TypeError, ValueError):
                started = None
            spawned_by = str(record.get("spawned_by") or "")
            lane = str(record.get("lane") or "")
        else:
            try:
                started = float(raw)
            except ValueError:
                started = None
        start_file.unlink(missing_ok=True)
    # The lifecycle record's closing row for this agent, beside the
    # "spawned" row from its start. A normal finish that reaches this line is
    # its own proof. When a lead stops this agent through TaskStop, the code
    # never reaches here. pointer.py covers that case.
    append_lifecycle(agent_id, "ended", lane)
    timing = {"ended": round(ended, 1)}
    if started:
        timing["started"] = round(started, 1)
        timing["duration_s"] = round(ended - started, 1)

    # spawned_by names the session that started this agent. pointer.py charges
    # a row to the lead only when the lead started the agent. A report sent to
    # a subagent does not count as the lead's saving.
    base = {"agent_id": agent_id, "agent_type": agent_type, "font_px": font_size(),
            "model": agent_model(event), "spawned_by": spawned_by}
    base.update(timing)

    # An agent that answers in structured data has no prose report. There is
    # nothing to pack. The hook writes no empty source file.
    if not text.strip():
        manifest_write(dict(base, packed=False, reason="no prose report"))
        queue_text_row(base, "no prose report")
        return 0

    if not ensure_pillow():
        manifest_write(dict(base, packed=False, reason="Pillow missing"))
        queue_text_row(base, "Pillow missing", chars=len(text))
        return 0

    # Without the key the hook cannot seal anything, and each function that
    # reads rows drops an unsealed row. A packed report then reaches nobody.
    # The text goes to the lead as it is.
    from common import seal_key
    if seal_key() is None:
        manifest_write(dict(base, packed=False, reason="no seal key"))
        queue_text_row(base, "no seal key", chars=len(text))
        return 0

    # Stub mode. The marker names the report file that this hook wrote before
    # it blocked. A marker that names a file that does not exist is a
    # DANGLING pointer, and marker_found stays False for it on purpose. Each
    # path below then treats the message as an unfiled report. The code
    # strips the marker lines, and the bad path never goes into an image. The
    # block below keeps the pointer out of the lead's context.
    mode, content = "net", text
    # lift_identifiers below fills this when the hook packs the report and
    # the lift is on. It stays empty on each other path.
    ident_legend = []
    marker_found = False
    dangling = None
    for line in reversed(text.strip().splitlines()):
        if line.strip().startswith(MARKER):
            candidate = Path(line.strip()[len(MARKER):].strip())
            # Only this agent's own report file counts. Any other path lets a
            # subagent's last line copy a file from anywhere on disk.
            own = tmp_dir() / ("densepack-report-%s.txt" % agent_id)
            if (candidate.is_file() and os.path.normcase(os.path.abspath(candidate))
                    == os.path.normcase(os.path.abspath(own))):
                marker_found = True
                mode = "stub"
                content = candidate.read_text(encoding="utf-8", errors="replace")
            else:
                dangling = candidate
                content = "\n".join(
                    row for row in text.splitlines()
                    if not row.strip().startswith(MARKER)).strip()
            break
    if dangling is not None:
        # This goes on the manifest and queue rows for the audit trail. A
        # count of the runs where an agent invented a pointer then needs no
        # transcript.
        base["dangling"] = str(dangling)

    # The net. The hook asks no agent to write a file, because the
    # permission classifier rejects that Write and a read-only agent has no
    # Write tool at all. When a long prose report arrives as the final
    # message, this hook writes the text to the report file ITSELF.
    #
    # A foreground agent takes the swap route. The hook packs the report at
    # this first stop and writes a swap file. report_swap.py then puts the
    # marker line in the lead's Agent result in place of the report. The
    # agent makes no extra turn.
    #
    # A background agent, and a message with a dangling marker line, take
    # the block route. The hook blocks the stop once and asks the agent to
    # reply with only the marker line. One block per agent. The hook takes
    # prose that an agent sends a second time as text and packs it as the
    # copy to read again. A harness that ignores block decisions gets the
    # same result.
    #
    # The code uses `content`, not `text`. A report that arrived beside a
    # dangling marker line goes into the file with the marker lines already
    # stripped, and the bad path never reaches the file or the image.
    blocked_flag = tmp_dir() / ("densepack-blocked-%s" % agent_id)
    # A message with a dangling marker line keeps the block route. On the
    # swap route, a pack that fails or costs more than its text leaves no
    # swap file. The lead then gets the message as it is, with the path to
    # nothing on its last line. The block route asks the agent for the
    # marker line of the real report file, and the lead never gets the bad
    # path. Such a message is rare.
    swap = dangling is None and swap_route(event, agent_id)
    # The report file of the swap route. It stays None on each other path.
    swap_file = None

    # ONE ASK PER AGENT, FOR ITS WHOLE RUN. blocked_flag cannot hold that
    # alone. The code unlinks it at the end of each stop, because `captured`
    # below and the filed-report recovery read it as "this stop followed a
    # block". That makes it a per-stop signal, not a record. Without the
    # marker below, an agent that stops more than once, such as a background
    # agent that still takes messages, gets the ask again at each stop and
    # pays a turn for each repeat.
    #
    # The code never removes the marker below. The ask happens once, and the
    # hook takes a decline as final. From then on, that agent's plain reply
    # is its report, filed and packed as text like any other. bootstrap.py
    # removes the two markers at SessionStart.
    asked_flag = tmp_dir() / ("densepack-asked-%s" % agent_id)
    # Before the first pass packs or asks for anything, it checks whether a
    # pack pays in dollars, with common.report_pack_worth. For a report that
    # cannot pay, the reply is the report, filed as text. The swap route
    # makes no agent turn, and the check prices the lead's Read turn only.
    # The block route still makes the agent's extra turn, and the check
    # prices that turn too, at the agent's model and context.
    import densepack as dp
    # The lead reads the report, and the lead's model sets the format. A
    # Sonnet lead gets images while the maxpack setting is on, which is the
    # default. A Haiku lead always gets text.
    worth = lead_gets_images(event.get("session_id")) and report_pack_worth(
        len(content) / dp.CHARS_PER_TOKEN, lead_model_name(event.get("session_id")),
        event.get("session_id"), agent_model(event),
        event.get("agent_transcript_path"), agent_turn=not swap)
    if (not marker_found and dangling is None and not blocked_flag.exists()
            and (not worth or len(content) < report_floor_chars(event.get("session_id")))):
        # The reply is the report. No marker, no second turn. A dangling
        # pointer and a plain reply after a block keep their own handling
        # below. The hook files the reply itself, as densepack-reply-<agent
        # id>.txt in tmp and in the vault. A later brief can name it, and the
        # hook never asks the agent to write anything.
        reply_file = tmp_dir() / ("densepack-reply-%s.txt" % agent_id)
        try:
            reply_file.write_text(content, encoding="utf-8")
            keep_copy(base.get("spawned_by") or None, texts=[str(reply_file)])
        except OSError:
            pass
        manifest_write(dict(base, packed=False,
                            reason="under the saving threshold",
                            chars=len(content), floor=report_floor_chars(event.get("session_id"))))
        queue_text_row(base, "under the saving threshold",
                       chars=len(content),
                       text_tokens=round(len(content) / dp.CHARS_PER_TOKEN))
        return 0
    if (not marker_found and len(content) > stub_chars()
            and not blocked_flag.exists() and not asked_flag.exists()):
        code_chars = sum(len(b) for b in _FENCE.findall(content))
        if code_chars <= len(content) * 0.5:
            target = tmp_dir() / ("densepack-report-%s.txt" % agent_id)
            # newline="" keeps the report's own line endings. The filed copy
            # is the exact text.
            with open(target, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            # The asked flag goes on each route. A later stop of the same
            # agent, after a message that resumes it, then takes the net and
            # gets no second swap or block.
            asked_flag.write_text("1", encoding="utf-8")
            if swap:
                # THE SWAP ROUTE. The report goes to the pack below at this
                # stop, as the filed report of stub mode. The code sets no
                # blocked flag and emits no block. The swap file is written
                # after the pack, and only a pack that pays gets one.
                mode, marker_found, swap_file = "stub", True, target
            else:
                # THE BLOCK ROUTE.
                blocked_flag.write_text("1", encoding="utf-8")
                if started:
                    start_file.write_text(marker_record(started, spawned_by),
                                          encoding="utf-8")
                # Top-level decision and reason. Claude Code's hooks
                # reference gives this shape for Stop and SubagentStop under
                # "Stop decision control". hookSpecificOutput holds
                # additionalContext for these two events and is not a
                # decision. Nothing goes there.
                # The wording matters. A read-only agent with no write tool
                # rejects a request to reply with a path to a file that it
                # did not write, because the request reads as an order to
                # claim that it wrote one. The message says who wrote the
                # file and what the line is for. It also names the exit for
                # an agent whose own instructions forbid a pointer line. The
                # plugin never asks an agent to say something untrue.
                emit({
                    "decision": "block",
                    "reason": ("This plugin, not you, already wrote your "
                               "report to %s . You needed no file tool, and this "
                               "plugin does not ask you to claim you wrote it. Reply "
                               "with exactly this one line and nothing else, "
                               "which names that file for the lead: %s %s . If "
                               "your own instructions forbid a pointer line, "
                               "reply normally instead. The file exists "
                               "either way, and the lead reads it."
                               % (target, MARKER, target)),
                })
                # A blocked agent has no row of its own yet. On a harness
                # that ignores the block, it never gets one, and the run
                # shows no trace of an agent that ran. This row is
                # provisional, and the real row follows on the second pass.
                # Code that counts agents from this file can drop the
                # provisional rows and not count a captured agent twice.
                manifest_write(dict(base, packed=False, provisional=True,
                                    reason="net fired, asked for the marker line",
                                    chars=len(content)))
                return 0
    # A dangling marker that the net above could not make into a filed
    # report. The message was only the pointer line, or it was too short or
    # too code-heavy to file. The lead must never get a path to nothing.
    # The hook blocks the stop once and asks the agent for the report itself,
    # as plain text. It uses the same one-block-per-agent flag as the net.
    # The two blocks can never chain, and a harness that ignores blocks gets
    # only the audit row below. A message with a dangling marker line never
    # takes the swap route. See `swap` above.
    if dangling is not None and not blocked_flag.exists():
        blocked_flag.write_text("1", encoding="utf-8")
        if started:
            start_file.write_text(marker_record(started, spawned_by),
                                  encoding="utf-8")
        emit({
            "decision": "block",
            "reason": ("Your final message names %s, but no such file "
                       "exists, and the lead must not get a path to "
                       "nothing. Do not write that file and do not repeat "
                       "the DENSEPACK_REPORT line. Reply with your full "
                       "report as plain text. The plugin files and packs it "
                       "itself." % dangling),
        })
        manifest_write(dict(base, packed=False, provisional=True,
                            reason="dangling pointer, asked for the report",
                            chars=len(content)))
        return 0
    # An agent cannot write a file when Claude Code's permission classifier
    # denies the Write. The agent then returns its whole report as its final
    # message, and the net packs it. For some agents the net is the ordinary
    # path, not the exception.
    #
    # Second pass, no marker line. The agent replied normally and not with
    # the pointer. The block message allows that, and some agents' own
    # instructions require it. The file that this hook wrote on the first
    # pass holds the real report, and the second reply can be far shorter.
    # Without this step, an agent that argues against the pointer line in a
    # short reply loses its long answer to a pack of the short one. The hook
    # packs the filed report when it is the longer of the two. The net then
    # never loses the report that it protects.
    if blocked_flag.exists() and not marker_found:
        filed = tmp_dir() / ("densepack-report-%s.txt" % agent_id)
        if filed.is_file():
            saved = filed.read_text(encoding="utf-8", errors="replace")
            if len(saved) > len(content):
                mode, content, marker_found = "stub", saved, True

    # Still nothing but a dangling pointer. The one block was already used,
    # or a harness ignored it, and no report text exists on disk or in the
    # message. There is nothing to pack and no true path to name. The
    # manifest records the loss, the receipt shows the agent, and the hook
    # never makes an image or a stub for the path that the message named.
    if not content.strip():
        blocked_flag.unlink(missing_ok=True)
        manifest_write(dict(base, packed=False,
                            reason="pointer to a file that was never written"))
        queue_text_row(base, "pointer to a file that was never written")
        return 0

    # A stub that arrives after a block means that the hook wrote the file,
    # not the agent. The image holds the raw report with no summary heading.
    # The manifest and the pointer note tell the lead, and the lead never
    # expects a summary that is not there. The swap route files the report
    # the same way, with no block.
    captured = (marker_found and blocked_flag.exists()) or swap_file is not None
    blocked_flag.unlink(missing_ok=True)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import densepack as dp

    # This step moves each fenced block in a report into a text file. An
    # exact byte is then always available. Further down, codepack.py also
    # packs a python fence with bands, after the check finds the report worth
    # packing. The pages go in the manifest beside this text file.
    # A report that is MOSTLY code stays plain text, with no image at all. The
    # hook packs a report that is mostly prose with some code blocks, with
    # each block moved to the text file. The image has a #=N=# marker where
    # block N was. The blocks go beside the image in a numbered plain text
    # file that the lead reads at full fidelity. The marker form never occurs
    # in normal text, and the lead can rebuild the report mechanically.
    fences = _FENCE.findall(content)
    code_file = None
    code_images = []
    code_drawn = 0
    if fences:
        code_chars = sum(len(b) for b in fences)
        if code_chars > len(content) * 0.5:
            manifest_write(dict(base, packed=False, reason="mostly code",
                                chars=len(content)))
            queue_text_row(base, "mostly code", chars=len(content),
                           text_tokens=round(len(content) / dp.CHARS_PER_TOKEN))
            return 0
        parts = ["Code blocks lifted out of the packed report %s." % agent_id,
                 "Each #=N=# marker in the image stands where block N belongs.", ""]
        for n, block in enumerate(fences, 1):
            content = content.replace(block, "#=%d=#" % n, 1)
            parts.append("#=%d=#" % n)
            parts.append(block)
            parts.append("")
        code_file = tmp_dir() / ("densepack-code-%s.txt" % agent_id)
        code_file.write_text("\n".join(parts), encoding="utf-8")

    source = tmp_dir() / ("densepack-src-%s.txt" % agent_id)
    # newline="" keeps the report's own line endings. This file is then the
    # exact text that the pointer says it is.
    with open(source, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    stem = tmp_dir() / ("densepack-img-%s" % agent_id)

    try:
        # The text keeps its real newlines, because flatten() with the
        # pilcrow mark makes pack_code() render the word "[pilcrow]" at each
        # line end.
        flat = dp.flatten(content, "\n")
        # When densepack.LIFT_IDENTIFIERS is on, take each identifier out of
        # the image and keep its value as text. A model cannot misread a
        # value that never enters the image. The lift is off by default, and
        # the text then stays unchanged.
        flat, ident_legend = dp.lift_identifiers(flat)
        # A report goes through the code renderer. When the lift is on, the
        # sidecar holds each id exactly.
        import codepack
        from common import resolved_reader
        reader_name = resolved_reader() or "fable"
        written, _target, _lh = codepack.pack_code(
            flat, code_size(font_size(), reader_name), str(stem), python=False,
            legend=None, reader=reader_name, title="report")
    except Exception:
        manifest_write(dict(base, packed=False, reason="pack failed",
                            chars=len(content)))
        queue_text_row(base, "pack failed", chars=len(content),
                       text_tokens=round(len(content) / dp.CHARS_PER_TOKEN))
        return 0

    # The API charges an image its patch count and nothing else. The count is
    # ceil(width / 28) times ceil(height / 28), with no added fee and no
    # minimum beyond the formula itself. Anthropic's vision docs, section
    # "Resolution and token cost", give 1000 x 1000 px = 1296 tokens and
    # 200 x 200 px = 64.
    # https://platform.claude.com/docs/en/build-with-claude/vision
    # The handover cost below is this pipeline's own overhead, not the API's.
    # It is the pointer line that names the images, counted from the
    # pointer's own text below and never from a constant, plus each read
    # call. Text delivery pays neither, and the code adds the handover cost
    # to the image side. The receipt then states the true delivered cost,
    # and the pack-or-skip comparison cannot pack at a loss.
    # With the seal, DensePack swaps a Read of the report's text for the
    # image beside it only where the local plugin wrote the pair. One seal
    # covers the whole pack. Each image that a model gets is one that the
    # local plugin wrote. In stub mode the filed report has the same words
    # and the same images, and it gets a seal too.
    #
    # In net mode the words of this pack come from this stop's message, not
    # from the filed report. A filed report from an earlier stop of the same
    # agent, such as a stop before a message resumed it, holds other words.
    # This pack writes over the images of that earlier pack, because the two
    # have the same names. A seal on the filed report then sends a Read of
    # its path, the path of the earlier marker line, to the images of this
    # later reply. The code deletes that seal, and such a Read returns the
    # filed report's own text.
    from common import seal_pair
    pack = [Path(p).name for p, _w, _h in written]
    seal_pair(source, pack)
    filed_report = tmp_dir() / ("densepack-report-%s.txt" % agent_id)
    if filed_report.is_file():
        if mode == "stub":
            seal_pair(filed_report, pack)
        else:
            Path(str(filed_report) + ".seal").unlink(missing_ok=True)

    # The swap file of the swap route. It holds the marker line and a hash of
    # the agent's final message, the text that Claude Code puts in the Agent
    # result. The code writes it before it prices the pointer. When the write
    # fails, the report reaches the lead as text in the Agent result, which
    # is net mode, and the receipt then prices the net pointer. The record
    # also names the images. When the swap misses, report_swap.py marks them
    # delivered, and read_gate.py never puts them into a later Read.
    if swap_file is not None and not write_report_swap(
            agent_id, text, swap_file, images=[str(p) for p, _w, _h in written],
            spawned_by=spawned_by):
        mode, swap_file, captured = "net", None, False

    patch_tokens = sum(dp.image_cost(w, h) for _p, w, h in written)
    # The pointer line, of the two, that this report arrives under. pointer.py
    # sends the longer stub line when no report in the batch returned as
    # prose, and the shorter line otherwise. The receipt charges the line
    # that the lead gets.
    pointer = (stub_pointer(len(written), tmp_dir()) if mode == "stub"
               else report_pointer(len(written), tmp_dir()))
    # The legend holds each identifier that the image no longer holds. It
    # goes to a sidecar file, not into the message. The pointer gets one
    # short tag line that names the file, not the whole "tag = value" block.
    # That file name is still this plugin's own text. The code still charges
    # it below, and the comparison still does not pack at a loss.
    legend_file = dp.legend_sidecar(ident_legend, stem)
    if legend_file:
        # The full path, never the bare name. brief_pack.py uses the same
        # rule. An agent then never searches the disk for a legend named
        # without its folder.
        pointer = pointer + "\nTags: " + str(tmp_dir() / legend_file)
    # Per turn, the conversation prefix holds the text or the image plus its
    # pointer. Those are the two sides that this code prices. The one Read
    # that opens each image costs once, and the fee below charges it. See
    # read_turn_fee in common.py.
    delivery_tokens = round(len(pointer) / dp.CHARS_PER_TOKEN)
    image_tokens = patch_tokens + delivery_tokens
    text_tokens = round(len(content) / dp.CHARS_PER_TOKEN)

    # The Read that opens the image is a whole extra lead turn, not only an
    # 80-token envelope. Each image Read reads the growing context again and
    # can open a new thinking block, about 2,000 tokens a turn. The lead
    # reads a text report inline, and it pays none of that. The hook packs a
    # report only when its token saving is more than one Read turn. Below
    # that, the image costs more than the text it replaces.

    # The fee is this session's own, from its context. The flat
    # READ_TURN_TOKENS stays as the measure for the stub floor.
    if text_tokens - image_tokens < read_turn_fee(event.get("session_id")):
        for path, _w, _h in written:
            Path(path).unlink(missing_ok=True)
        if legend_file:
            (tmp_dir() / legend_file).unlink(missing_ok=True)
        # Without its swap file, the report reaches the lead as text in the
        # Agent result.
        if swap_file is not None:
            report_swap_path(agent_id).unlink(missing_ok=True)
        manifest_write(dict(base, packed=False, reason="text measured cheaper",
                            chars=len(content), text_tokens=text_tokens,
                            image_tokens=image_tokens,
                            patch_tokens=patch_tokens,
                            delivery_tokens=delivery_tokens))
        queue_text_row(base, "under the saving threshold", chars=len(content),
                       text_tokens=text_tokens, would_cost=image_tokens)
        return 0

    # Built from base, not field by field, and spawned_by and each other base
    # field reach the queue. A hand-written copy that dropped spawned_by
    # charges each nested report to the lead. Anything added to base reaches
    # the queue.
    # codepack.py packs a python block with bands, at the same size as the
    # report itself, and the model reads the block from the image. A block
    # with any other fence label stays text only. The .txt keeps each block in
    # the two cases, and a model that needs an exact byte still has one.
    # The pack happens here, after the check finds the report worth packing.
    # A pack before an earlier return leaves these pages on disk with nothing
    # that names them.
    if code_file is not None:
        import codepack
        code_images, code_drawn = codepack.pack_fenced(
            fences, code_size(font_size()),
            str(tmp_dir() / ("densepack-code-%s" % agent_id)))

    entry = dict(base)
    entry.update({
        "mode": mode,
        "images": [str(p) for p, _w, _h in written],
        "dims": ["%dx%d" % (w, h) for _p, w, h in written],
        "pixels": sum(w * h for _p, w, h in written),
        "chars": len(content),
        "text_tokens": text_tokens,
        "image_tokens": image_tokens,
        "patch_tokens": patch_tokens,
        "delivery_tokens": delivery_tokens,
    })
    entry.update(timing)
    if captured:
        entry["captured"] = True
    if code_file is not None:
        entry["code"] = str(code_file)
        entry["code_images"] = code_images
        entry["code_drawn"] = code_drawn
        entry["code_text"] = len(fences) - code_drawn
    # The legend file name goes in the entry, not only into the pricing
    # above. The lead then has a file to resolve a bare tag against.
    # pointer.py prints "Tags: <name>" beside the image line from this field.
    # The values stay in the sidecar file, and the lead opens it only when
    # needed.
    if legend_file:
        entry["legend_file"] = legend_file
    manifest_write(dict(entry, packed=True))
    # The queue row of the swap route carries the hash of the agent's final
    # message. pointer.py runs on the Agent result at the same time as
    # report_swap.py. It makes the same test, common.swap_applies(), and
    # when the swap misses it prints this row as net mode. The lead then has
    # the text, and the receipt does not call the text above a stub.
    append_queue(dict(entry, swap_digest=report_digest(text))
                 if swap_file is not None else entry)

    # Each report image goes on the pending list. One Read call can then get
    # a whole batch. Each Read is a turn, and one turn reads the whole
    # conversation again. Reports read one Read at a time can cost more than
    # their text saved. The batch makes a small report worth packing at all.
    try:
        # Each row has a seal, because common.pending_entries() drops a row
        # without one.
        import common
        with pending_path().open("a", encoding="utf-8") as fh:
            for path in entry["images"]:
                row = {
                    "image": str(path), "id": entry["agent_id"],
                    "source": str(source) if source else "",
                    "chars": entry["chars"],
                    "text_tokens": entry["text_tokens"],
                    "image_tokens": entry["image_tokens"],
                    "time": round(time.time(), 1)}
                row["seal"] = common._row_seal(row)
                fh.write(json.dumps(row) + "\n")
    except OSError:
        pass

    # The keep setting. .claude/tmp is scratch space that the prune cleans.
    # If you want the images or the report text, the keep setting puts copies
    # in a folder of your own. The copy happens here, at creation, and you
    # lose nothing if the session ends before the pointer hook runs. A copy
    # failure never stops delivery.
    legend_path = tmp_dir() / legend_file if legend_file else None
    # The seal goes with them. Without it, a Read of the vault copy finds no
    # sealed pair and returns the whole text.
    keep_copy(event.get("session_id") or spawned_by,
              images=[path for path, _w, _h in written],
              texts=[source, Path(str(source) + ".seal")]
              + ([code_file] if code_file is not None else [])
              + ([legend_path] if legend_path is not None else []))
    return 0


def guarded_main():
    """Never let an exception out of this hook.

    main() runs inside a try. A fault in main() cannot change the result of
    the event that started the hook. The function writes the error to
    stderr, where the fault stays visible. The exit code stays 0.
    """
    try:
        return main()
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack %s: %s\n" % ("subagent_stop.py", err))
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
