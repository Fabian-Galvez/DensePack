"""Runs every time a helper agent finishes. The printing press.

HOW THIS FILE FITS, in plain words: the helper is done and left either a report
file or plain text. This script hands the words to densepack.py, which draws
them as one small tightly packed picture, then measures both prices. If the
picture costs fewer tokens than the words, the picture wins and a line goes on
the queue for pointer.py. If the words are cheaper, nothing happens and the
text flows as normal.

SubagentStop hook. Pack the finished report into a dense image.

Two modes, best first:

  Stub mode.  The final message ends with DENSEPACK_REPORT: <path> and the
              file EXISTS, which means this hook wrote it: the hook files the
              agent's long report itself, blocks the stop once, and the agent
              replies with the marker line. The FILE gets packed, and the
              lead's context only ever carries the one marker line plus the
              image. Full saving. No agent is ever asked to write the file:
              permission rules refuse such Writes, so the block-and-retry net
              is the one path.

  Net mode.   The subagent returned a long text and the block was ignored or
              not warranted. The text is packed as a safety net. The image
              still costs less to re-read than the text, but the text already
              reached the lead once, so the saving is partial.

A marker line naming a file that does NOT exist is a dangling pointer and is
never let through: the lead would be handed a path to nothing and the packing
would silently never happen. The hook blocks that stop once and recovers the
report instead.

The one guard is the live measurement: a report packs whenever the image costs
less than the text, the same comparison the DensePack app's meter applies. There
is no character floor.
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
                    report_pack_worth, report_pointer,
                    stub_chars, stub_pointer,
                    emit, ensure_pillow, project_dir, read_event, settings,
                    tmp_dir)

# Each pattern below names one shape of "nothing happened here": a sentence
# about one agent's own scope that a lead can misread as a statement about
# the whole session. separate_scope_notes() moves such a sentence under one
# trailing label rather than deleting it, because deleting information a
# report already gave is its own fault.
#
# Every pattern runs on one sentence at a time, already cut at the last
# period, so the gap in the middle is bounded by [^\n]{0,160} rather than by
# excluding a period: excluding one would block a file name such as
# THIRD-PARTY-NOTICES.md, whose own period sits inside the sentence, not at
# its end.
SCOPE_PATTERNS = [re.compile(p, re.I) for p in (
    r"\bno\b[^\n]{0,160}?\btouch(?:ed)?\b",
    r"\bnothing\b[^\n]{0,160}?\b(?:changed|touched|modified|edited)\b",
    r"\bdid not touch\b",
    r"\b(?:was|were)\s+not\s+(?:touched|changed|modified|edited)\b",
    r"\bleft alone\b",
    r"\buntouched\b",
    r"\bnot touched\b",
)]

# One trailing label, so every report
# that carries a scope sentence gets the same label and a lead skimming many
# reports learns to read it the same way every time.
SCOPE_LABEL = "Scope of this one agent, not a statement about the session:"

# One line, one or more sentences. A period or ? or ! immediately followed by
# whitespace ends a sentence; a period inside a file name such as
# THIRD-PARTY-NOTICES.md is never followed by whitespace, so it never splits.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# A fenced code block, ``` to ```. Compiled once: the ask-again gate and the
# code lift both split on this same shape.
_FENCE = re.compile(r"```[^\n]*\n.*?```", re.S)


def _split_sentences(line):
    """One line broken into its sentences, in order, blanks dropped."""
    return [s for s in _SENTENCE_END.split(line) if s.strip()]


def _is_scope_note(sentence):
    """True when this sentence states that something was NOT touched,
    changed, modified or edited, the shape a lead can misread."""
    return any(pattern.search(sentence) for pattern in SCOPE_PATTERNS)


def separate_scope_notes(text):
    """Move every scope sentence out of the body and under one label.

    Returns (body, notes). notes is the list of sentences moved, in the order
    they appeared, or [] when the report carries none, in which case body is
    the input unchanged. Nothing is dropped: every sentence in notes still
    reads exactly as it did in the body, only relocated.
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

# What the plugin's own handover costs, per report. This is NOT an API charge:
# Anthropic bills an image at its patch count and adds nothing. The pointer,
# the line naming this batch's images, is the whole per-turn fee, counted
# from the real line rather than from a constant, so it never goes stale.
# The one Read tool call that opens each image, 80 tokens of envelope, is
# paid once, and read_turn_fee() charges it at the saving test below.
# See read_turn_fee in common.py.


def queue_text_row(base, reason, chars=0, text_tokens=0, would_cost=0):
    """A report that stays text still gets a receipt row, so the user sees
    every agent that returned. Its saving fields are zero and the pointer
    keeps it out of the run total, because nothing was saved or spent on it."""
    entry = dict(base, mode="text", images=[], dims=[], pixels=0, chars=chars,
                 text_tokens=text_tokens, image_tokens=0, patch_tokens=0,
                 delivery_tokens=0, reason=reason, would_cost=would_cost)
    append_queue(entry)


def agent_model(event):
    """The model the subagent ran on, or None.

    SubagentStop carries agent_transcript_path but not the model, and the
    model sits on the first assistant line of that transcript. Only the first
    few lines are read, because the file can be very large and the answer is
    always near the top. Any failure returns None, because a missing name on a
    receipt is a smaller problem than a hook that stops working.
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
    # The manifest is the master record of a session's agents:
    # one line per finished agent, appended as each agent finishes, holding the
    # timings and sizes so the lead and the user can audit every report
    # without re-reading anything. Skipped packs are recorded too, with the
    # reason, because a stat that only counts successes cannot prove the
    # plugin is saving more than it costs.
    # Sealed, because the readers keep only sealed rows; see sealed_rows().
    import common
    record = dict(record, seal=common._row_seal(record))
    with (tmp_dir() / "densepack-manifest.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def marker_record(started, spawned_by):
    """The start marker's JSON. The two block paths below re-create the
    marker so the retry keeps its duration, and they have to keep spawned_by
    with it: common.unfinished_agents() matches a marker to its session
    through that field, and pointer.py charges the saving to the session it
    names. A bare timestamp carries neither.
    """
    return json.dumps({"at": started, "spawned_by": spawned_by or ""})


# One Read turn of a reader's context, the fee an image must beat before it
# saves anything. Below it the picture costs more than the text it replaces.
READ_TURN_TOKENS = 2000


def report_floor_chars(session_id=None):
    """The report length below which no image can save one Read turn.

    The floor is the lead session's own Read turn fee, common.read_turn_fee,
    the same number the saving test below applies, so the first pass and the
    second agree: a flat floor would block agents for the marker line whose
    reports then ship as text under the fee, one wasted turn each.

    text_tokens is len(content) / CHARS_PER_TOKEN and an image saves at
    most every one of them, so a report shorter than READ_TURN_TOKENS
    times CHARS_PER_TOKEN characters can never clear the floor the saving
    test below applies. Asking such an agent for the marker line costs a
    whole extra turn for nothing.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import densepack as dp
    fee = read_turn_fee(session_id) if session_id else READ_TURN_TOKENS
    return int(fee * dp.CHARS_PER_TOKEN)


def main():
    # The event is read before the switch is checked, because the off
    # switch is per session and the id that names
    # the session is on the event.
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
        # JSON, or a bare timestamp from an older hook. Both are read. The
        # isinstance test is required, not defensive: a bare timestamp is
        # itself valid JSON, so json.loads returns a float rather than
        # raising, and calling .get on that float would raise AttributeError.
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
    # "spawned" row written at its start. A normal finish reaching this line
    # is proof of its own, but a lead that stopped this same agent through
    # TaskStop never reaches here, which is the case pointer.py covers.
    append_lifecycle(agent_id, "ended", lane)
    timing = {"ended": round(ended, 1)}
    if started:
        timing["started"] = round(started, 1)
        timing["duration_s"] = round(ended - started, 1)

    # spawned_by names the session that started this agent. pointer.py charges
    # a row to the lead only when the lead started it, so a report delivered
    # to a subagent is not counted as the lead's saving.
    base = {"agent_id": agent_id, "agent_type": agent_type, "font_px": font_size(),
            "model": agent_model(event), "spawned_by": spawned_by}
    base.update(timing)

    # An agent that answers in structured data has no prose report. Nothing to
    # pack, so write nothing rather than littering an empty source file.
    if not text.strip():
        manifest_write(dict(base, packed=False, reason="no prose report"))
        queue_text_row(base, "no prose report")
        return 0

    if not ensure_pillow():
        manifest_write(dict(base, packed=False, reason="Pillow missing"))
        queue_text_row(base, "Pillow missing", chars=len(text))
        return 0

    # Nothing can be sealed without the key, and every reader drops an
    # unsealed row, so a packed report would reach nobody. Text goes through.
    from common import seal_key
    if seal_key() is None:
        manifest_write(dict(base, packed=False, reason="no seal key"))
        queue_text_row(base, "no seal key", chars=len(text))
        return 0

    # Stub mode: the marker names the report file this hook wrote before it
    # blocked. A marker naming a file that does not exist is a DANGLING
    # pointer, and marker_found stays False for it on purpose: every path
    # below then treats the message as an unfiled report, the marker lines
    # are stripped so the bad path can never be packed into an image, and
    # the block below keeps the pointer out of the lead's context.
    mode, content = "net", text
    # Filled by lift_identifiers below when the report is packed and the
    # lift is on. Empty on every other path.
    ident_legend = []
    marker_found = False
    dangling = None
    for line in reversed(text.strip().splitlines()):
        if line.strip().startswith(MARKER):
            candidate = Path(line.strip()[len(MARKER):].strip())
            # Only this agent's own report file counts. Any other path would
            # let a subagent's last line copy a file from anywhere on disk.
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
        # On the manifest and queue rows for the audit trail, so a run where
        # an agent invented a pointer can be counted without a transcript.
        base["dangling"] = str(dangling)

    # The net, the one delivery path there is. No agent is asked to write a
    # file, because the permission classifier refuses that Write and a
    # read-only agent has no Write tool at all. When a
    # long prose report arrives as the final message, this hook writes the
    # text to the report file ITSELF, blocks the stop once, and asks the
    # agent to reply with only the marker line. One block per agent: an agent
    # that sends prose a second time is accepted as text and packed as the
    # re-read copy. On a harness that ignores block decisions the behavior
    # also falls back to that. `content` rather than `text`, so a report that
    # arrived beside a dangling marker line is filed with the marker lines
    # already stripped and the bad path never reaches the file or the image.
    blocked_flag = tmp_dir() / ("densepack-blocked-%s" % agent_id)

    # ONE ASK PER AGENT, FOR THE WHOLE OF ITS LIFE. blocked_flag cannot
    # carry that on its own: it is unlinked at the end of every stop,
    # because both `captured` below and the filed-report recovery read it
    # as "this stop followed a block", which makes it a per-stop signal
    # rather than a memory. An agent that stops more than once, which is
    # any background agent still taking messages, would be asked again at
    # every stop and pay a turn for each repeat.
    #
    # The
    # marker below is never consumed, so the ask happens once and a
    # decline is taken as final: that agent's plain reply is its report
    # from then on, filed and packed as text like any other. Both markers
    # are swept by bootstrap.py at SessionStart.
    asked_flag = tmp_dir() / ("densepack-asked-%s" % agent_id)
    # The first pass asks whether a pack pays in
    # dollars across the lead's and the agent's rates, common.report_pack_worth,
    # before it asks the agent for anything; a report that cannot pay is
    # the reply, filed as text, and the agent is never asked to reply again.
    import densepack as dp
    # The lead reads the report, so the lead's model decides: a Sonnet lead
    # gets text until /maxpack, and a Haiku lead always gets text.
    worth = lead_gets_images(event.get("session_id")) and report_pack_worth(
        len(content) / dp.CHARS_PER_TOKEN, lead_model_name(event.get("session_id")),
        event.get("session_id"), agent_model(event),
        event.get("agent_transcript_path"))
    if (not marker_found and dangling is None and not blocked_flag.exists()
            and (not worth or len(content) < report_floor_chars(event.get("session_id")))):
        # The reply is the report. No marker, no second turn. A dangling
        # pointer and a plain reply after a block keep their own handling
        # below. The hook files the reply itself, densepack-reply-<agent
        # id>.txt in tmp and in the vault, so a later brief can name it and
        # the agent is never asked to write anything.
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
            # newline="" keeps the report's own line endings, so the filed
            # copy is the exact text.
            with open(target, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            blocked_flag.write_text("1", encoding="utf-8")
            asked_flag.write_text("1", encoding="utf-8")
            if started:
                start_file.write_text(marker_record(started, spawned_by),
                                      encoding="utf-8")
            # Top-level decision and reason, which is the shape Claude Code's
            # hooks reference gives for Stop and SubagentStop under "Stop
            # decision control". hookSpecificOutput carries additionalContext
            # for these two events and is not a decision, so nothing goes
            # there.
            # The wording matters. A read only agent with no write tool
            # refuses a request to reply with a path to a file it had not
            # written, because that reads as being asked to claim it wrote
            # one. The message says who wrote the file and what the line is
            # for, and it names the way out for an agent whose own
            # instructions forbid a pointer line, so the plugin never puts an
            # agent in a position where obeying it means saying something
            # untrue.
            emit({
                "decision": "block",
                "reason": ("This plugin, not you, has already written your "
                           "report to %s . You needed no file tool and you "
                           "are not being asked to claim you wrote it. Reply "
                           "with exactly this one line and nothing else, "
                           "which points the lead at that file: %s %s . If "
                           "your own instructions forbid a pointer line, "
                           "reply normally instead; the file is written "
                           "either way and the lead will read it."
                           % (target, MARKER, target)),
            })
            # A blocked agent has no row of its own yet, and on a harness that
            # ignores the block it never gets one, so the run would show no
            # trace of an agent that ran. The row is marked provisional and the
            # real row follows on the second pass, so anything counting agents
            # from this file can drop the provisional ones instead of counting
            # a captured agent twice.
            manifest_write(dict(base, packed=False, provisional=True,
                                reason="net fired, asked for the marker line",
                                chars=len(content)))
            return 0
    # A dangling marker the net above could not turn into a filed report:
    # the message was only the pointer line, or too short or too code-heavy
    # to file. Nothing may hand the lead a path to nothing, so the stop is
    # blocked once and the agent is asked for the report itself, as plain
    # text. The same one-block-per-agent flag as the net, so the two blocks
    # can never chain and a harness that ignores blocks degrades to the
    # audit row below.
    if dangling is not None and not blocked_flag.exists():
        blocked_flag.write_text("1", encoding="utf-8")
        if started:
            start_file.write_text(marker_record(started, spawned_by),
                                  encoding="utf-8")
        emit({
            "decision": "block",
            "reason": ("Your final message points at %s, but no such file "
                       "exists, and the lead must not be handed a path to "
                       "nothing. Do not write that file and do not repeat "
                       "the DENSEPACK_REPORT line. Reply with your full "
                       "report as plain text; the plugin files and packs it "
                       "itself." % dangling),
        })
        manifest_write(dict(base, packed=False, provisional=True,
                            reason="dangling pointer, asked for the report",
                            chars=len(content)))
        return 0
    # An agent can be unable to write a file through no fault of its own,
    # when Claude Code's permission classifier denies the Write, so it
    # returns its whole report as its final message and the net packs it.
    # The net is the ordinary path for some agents, not the exception.
    #
    # Second pass, no marker line. The agent replied normally rather than with
    # the pointer, which the block message allows and which some agents' own
    # instructions require. The file this hook wrote on the first pass holds
    # the real report, and the second reply can be far shorter than it: an
    # agent that argues against the pointer line in a short reply would
    # otherwise have its long answer packed over. Pack the filed report
    # whenever it is the longer of the two, so the net can never cost the
    # report it exists to protect.
    if blocked_flag.exists() and not marker_found:
        filed = tmp_dir() / ("densepack-report-%s.txt" % agent_id)
        if filed.is_file():
            saved = filed.read_text(encoding="utf-8", errors="replace")
            if len(saved) > len(content):
                mode, content, marker_found = "stub", saved, True

    # Still nothing but a dangling pointer: the one block was already spent,
    # or a harness ignored it, and no report text exists anywhere, on disk or
    # in the message. There is nothing to pack and nothing true to point at,
    # so the manifest records the loss, the receipt shows the agent, and no
    # image or stub is ever made for the path the message named.
    if not content.strip():
        blocked_flag.unlink(missing_ok=True)
        manifest_write(dict(base, packed=False,
                            reason="pointer to a file that was never written"))
        queue_text_row(base, "pointer to a file that was never written")
        return 0

    # A stub arriving after a block means the hook wrote the file, not the
    # agent, so the image holds the raw report with no summary heading. The
    # lead is told, through the manifest and the pointer note, so it never
    # expects a summary that is not there.
    captured = marker_found and blocked_flag.exists()
    blocked_flag.unlink(missing_ok=True)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import densepack as dp

    # Every fenced block inside a report is lifted out to a text file here,
    # so an exact byte is always available. A python fence also draws banded
    # further down, through codepack.py, once the report is judged worth
    # packing; the pages go in the manifest beside this text file.
    # A report that is MOSTLY code is left as plain text, no image at all. A
    # report that is mostly prose with some code blocks gets packed with each block lifted
    # out: the image carries a #=N=# marker where block N belonged, and the
    # blocks travel beside the image in a numbered plain text file the lead
    # reads at full fidelity. The marker shape never occurs in normal text, so
    # the lead can reassemble the report mechanically.
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
    # newline="" keeps the report's own line endings, so this file is the
    # exact text the pointer says it is.
    with open(source, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    stem = tmp_dir() / ("densepack-img-%s" % agent_id)

    try:
        # Real newlines: flatten() with the pilcrow mark would make
        # pack_code() draw the word "[pilcrow]" at every line end.
        flat = dp.flatten(content, "\n")
        # Take every identifier out of the image and keep its value as text,
        # when densepack.LIFT_IDENTIFIERS is on. A value that never enters the
        # image cannot be misread. The lift is off by default, so the text
        # passes through unchanged.
        flat, ident_legend = dp.lift_identifiers(flat)
        # A report draws through the code renderer; when the lift is on, an
        # id travels exactly in the sidecar.
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

    # The API charges an image its patch count and nothing else: ceil(width /
    # 28) times ceil(height / 28), no added fee, no minimum beyond the formula
    # itself. Anthropic's vision docs, section "Resolution and token cost",
    # give 1000 x 1000 px = 1296 tokens and 200 x 200 px = 64:
    # https://platform.claude.com/docs/en/build-with-claude/vision
    # The handover cost below is this pipeline's own overhead, not the API's:
    # the pointer line that names the images, counted from the pointer's own
    # text below and never from a constant, plus each read call. Text
    # delivery pays neither, so the handover cost is added to the image side.
    # That way the receipt states the true delivered cost and the
    # pack-or-skip comparison cannot pack at a loss.
    # Sealed, so a Read of the report's text is swapped for the image beside
    # it only where this machine's plugin wrote the pair. The filed report
    # carries the same words and the same image, so it is sealed too.
    # One seal over the whole pack, so every image a reader is handed is one
    # this machine's plugin wrote. The filed report carries the same words
    # and the same images, so it is sealed too.
    from common import seal_pair
    pack = [Path(p).name for p, _w, _h in written]
    seal_pair(source, pack)
    filed_report = tmp_dir() / ("densepack-report-%s.txt" % agent_id)
    if filed_report.is_file():
        seal_pair(filed_report, pack)

    patch_tokens = sum(dp.image_cost(w, h) for _p, w, h in written)
    # Which of the two pointer lines this report will arrive under. pointer.py
    # sends the longer stub line when no report in the batch came back as
    # prose, and the shorter one otherwise, so the receipt charges the line
    # the lead actually receives.
    pointer = (stub_pointer(len(written), tmp_dir()) if mode == "stub"
               else report_pointer(len(written), tmp_dir()))
    # The legend carries every identifier the image no longer holds. It goes
    # to a sidecar file, not into the message: the pointer gains one short tag
    # line naming the file instead of the whole "tag = value" block, and that
    # file name is still this plugin's own text, so it is still charged below
    # and the comparison still refuses to pack at a loss.
    legend_file = dp.legend_sidecar(ident_legend, stem)
    if legend_file:
        # The full path, never the bare name, the same rule brief_pack.py
        # follows, so an agent never searches the disk for a legend named
        # without its folder.
        pointer = pointer + "\nTags: " + str(tmp_dir() / legend_file)
    # Per turn the conversation prefix carries either the text or the
    # image plus its pointer, so those are the two sides priced here. The
    # one Read that opens each image is paid once, and the fee below
    # charges it. See read_turn_fee in common.py.
    delivery_tokens = round(len(pointer) / dp.CHARS_PER_TOKEN)
    image_tokens = patch_tokens + delivery_tokens
    text_tokens = round(len(content) / dp.CHARS_PER_TOKEN)

    # The Read that opens the image is a whole extra lead turn, not only an
    # 80-token envelope: each image Read re-reads the growing context and can
    # open a fresh thinking block, about 2,000 tokens a turn. A text report is
    # read inline and pays none of that. So a report only earns packing when
    # its token saving clears one Read turn; below that the image costs more
    # than the text it replaces.

    # The fee is this session's own, from its context; the flat
    # READ_TURN_TOKENS stays as the stub floor's yardstick.
    if text_tokens - image_tokens < read_turn_fee(event.get("session_id")):
        for path, _w, _h in written:
            Path(path).unlink(missing_ok=True)
        if legend_file:
            (tmp_dir() / legend_file).unlink(missing_ok=True)
        manifest_write(dict(base, packed=False, reason="text measured cheaper",
                            chars=len(content), text_tokens=text_tokens,
                            image_tokens=image_tokens,
                            patch_tokens=patch_tokens,
                            delivery_tokens=delivery_tokens))
        queue_text_row(base, "under the saving threshold", chars=len(content),
                       text_tokens=text_tokens, would_cost=image_tokens)
        return 0

    # Built from base, not field by field, so spawned_by and every other base
    # field reach the queue: a hand written copy that dropped spawned_by
    # would charge every nested report to the lead. Anything added to base
    # reaches the queue.
    # A python block draws banded and is read off the picture, at the same
    # size the report itself draws at. Every other fence label goes out as
    # text only, and the .txt keeps every block either way, so a reader that
    # needs an exact byte still has one.
    # Drawn here, after the report is judged worth packing: every earlier
    # return would have left these pages on disk with nothing naming them.
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
    # above, so the lead has something to resolve a bare tag against.
    # pointer.py prints "Tags: <name>" beside the image line from this field,
    # and the values themselves stay in the sidecar file, opened only when
    # needed.
    if legend_file:
        entry["legend_file"] = legend_file
    manifest_write(dict(entry, packed=True))
    append_queue(entry)

    # Every report image joins the list of images waiting to be read, so one
    # Read call can fetch a whole batch. Each Read is a turn, and one turn
    # re-reads the whole conversation, so reports read one Read at a time can
    # cost more than their text saved. Batching is what makes a small report
    # worth drawing at all.
    try:
        # Sealed, because common.pending_entries() drops a row without the seal.
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

    # The keep setting: .claude/tmp is scratch and gets cleaned, so a user who
    # wants the images or the report text keeps copies in a folder of their
    # own. Copied here, at creation, so nothing is lost if the session ends
    # before the pointer hook fires. A copy failure never breaks delivery.
    legend_path = tmp_dir() / legend_file if legend_file else None
    # The seal goes with them: without it a Read of the vault copy finds no
    # sealed pair and comes back as the whole text.
    keep_copy(event.get("session_id") or spawned_by,
              images=[path for path, _w, _h in written],
              texts=[source, Path(str(source) + ".seal")]
              + ([code_file] if code_file is not None else [])
              + ([legend_path] if legend_path is not None else []))
    return 0


def guarded_main():
    """Never let an exception out of this hook.

    main() outside any try would let a fault change the outcome of the tool
    call that fired the hook. The error is written to stderr so the fault is
    still visible. The exit code stays 0, which lets the call through.
    """
    try:
        return main()
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack %s: %s\n" % ("subagent_stop.py", err))
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
