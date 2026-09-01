"""Runs every time a helper agent finishes. The printing press.

HOW THIS FILE FITS, in plain words: the helper is done and left either a report
file or plain text. This script hands the words to densepack.py, which draws
them as one small tightly packed picture, then measures both prices. If the
picture costs fewer tokens than the words, the picture wins and a line goes on
the queue for pointer.py. If the words are cheaper, nothing happens and the
text flows as normal.

ORIGINAL NOTE: SubagentStop hook. Pack the finished report into a dense image.

Two modes, best first:

  Stub mode.  The final message ends with DENSEPACK_REPORT: <path> and the
              file EXISTS, which since 29 August 2026 means this hook wrote
              it: the hook files the agent's long report itself, blocks the
              stop once, and the agent replies with the marker line. The FILE
              gets packed, and the lead's context only ever carries the one
              marker line plus the image. Full saving. No agent is ever asked
              to write the file: 19 of 19 such Writes were refused by
              permissions over benchmark pairs 1 to 7, so the block-and-retry
              net that used to be the fallback is now the one path.

  Net mode.   The subagent returned a long text and the block was ignored or
              not warranted. The text is packed as a safety net. The image
              still costs less to re-read than the text, but the text already
              reached the lead once, so the saving is partial.

A marker line naming a file that does NOT exist is a dangling pointer and is
never let through: 13 of the 19 refused writes ended with the agent printing
one, the lead was handed a path to nothing, and the packing silently never
happened. The hook blocks that stop once and recovers the report instead.

The one guard is the live measurement: a report packs whenever the image costs
less than the text, the same comparison the DensePack app's meter applies. There
is no character floor.
"""

import json
import re
import sys
import time
from pathlib import Path

from common import (MARKER, append_lifecycle, append_queue, disabled,
                    font_size, keep_copy, pending_path, report_pointer,
                    stub_chars, stub_pointer,
                    emit, ensure_pillow, project_dir, read_event, settings,
                    tmp_dir)

# Added 27 August 2026. A subagent was told to stay out of several folders,
# and its report ended by naming every one of them, "no THIRD-PARTY-NOTICES.md
# was touched" among them, one sentence naming that one agent's own scope. The
# lead relayed it to the user as though it described the whole session, and
# the user read it as the notices file itself, when two earlier agents had
# already fixed it. It cost a turn to undo, and a wasted turn destroys the
# saving this plugin exists to create.
#
# This is the fix on the way BACK. subagent_start.py's SCOPE_RULE is the
# matching fix on the way out, telling an agent what to report instead; this
# is the net for the run where a report carries the sentence anyway. The
# sentence is never deleted, because deleting information a report already
# gave is the exact fault being fixed: it is moved under one trailing label
# instead, so the lead reads it as this one agent's scope and not as a
# statement about the session.
#
# Each pattern names one shape of "nothing happened here", taken from the
# phrasing given for this fix and from the sentence that started it: "no
# THIRD-PARTY-NOTICES.md was touched" is the "no X was touched" shape below.
# Every pattern here runs on one sentence at a time, already cut at the last
# period, so the gap in the middle is bounded by [^\n]{0,160} rather than by
# excluding a period: excluding one blocked a file name such as
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

# The exact trailing line the brief for this fix specifies, so every report
# that carries a scope sentence gets the same label and a lead skimming many
# reports learns to read it the same way every time.
SCOPE_LABEL = "Scope of this one agent, not a statement about the session:"

# One line, one or more sentences. A period or ? or ! immediately followed by
# whitespace ends a sentence; a period inside a file name such as
# THIRD-PARTY-NOTICES.md is never followed by whitespace, so it never splits.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(line):
    """One line broken into its sentences, in order, blanks dropped."""
    return [s for s in _SENTENCE_END.split(line) if s.strip()]


def _is_scope_note(sentence):
    """True when this sentence states that something was NOT touched,
    changed, modified or edited, the shape that misled the lead on 27 August
    2026."""
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
# the line naming this batch's images, is the whole per-turn fee, COUNTED
# from the real line, not guessed: it was a 60 token constant until
# 20 August 2026, when the real line measured 365 characters. That day the
# divisor was 4 and 365 characters read as 91 tokens; at the 2.40 measured on
# 31 August 2026 the same line is 152 tokens. The code never stored either
# figure, so nothing had to change here, but a reader comparing this comment
# against a receipt should know which divisor each number came from. Every
# receipt built on the old 60 token constant understated the cost. The one
# Read tool call that opens each image, 80 tokens of envelope, is paid
# once and amortises out of the per-turn compare; see THE FLOOR IS FLAT in
# common.py.


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
    with (tmp_dir() / "densepack-manifest.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def marker_record(started, spawned_by):
    """The start marker's JSON, the shape subagent_start.py writes. The two
    block paths below re-create the marker so the retry keeps its duration,
    and they have to keep spawned_by with it: common.unfinished_agents()
    matches a marker to its session through that field, and pointer.py charges
    the saving to the session it names. A bare timestamp, which those two
    paths wrote before, carries neither.
    """
    return json.dumps({"at": started, "spawned_by": spawned_by or ""})


def main():
    # The event is read before the switch is checked, because the off
    # switch is per session since 31 August 2026 and the id that names
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
        # JSON since 21 August 2026, a bare timestamp before it. Both are read,
        # so an agent that started under the older hook still gets its duration.
        # The isinstance test is required, not defensive: a bare timestamp is
        # itself valid JSON, so json.loads returns a float rather than raising,
        # and calling .get on that float raised AttributeError. Three steps of
        # test_chain caught it on 21 August 2026.
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
    # The lifecycle record's closing row for this agent. common.py's
    # LIFECYCLE_FILE note explains why watchdog.py and stop_gate.py need
    # this beside the "spawned" row subagent_start.py already wrote: a
    # normal finish reaching this line is proof of its own, but a lead
    # that stopped this same agent through TaskStop never reaches here,
    # which is exactly the case the third writer, pointer.py, covers.
    append_lifecycle(agent_id, "ended", lane)
    timing = {"ended": round(ended, 1)}
    if started:
        timing["started"] = round(started, 1)
        timing["duration_s"] = round(ended - started, 1)

    # spawned_by names the session that started this agent. pointer.py charges
    # a row to the lead only when the lead started it, so a report delivered
    # to a subagent is no longer counted as the lead's saving.
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

    # Stub mode: the marker names the report file this hook wrote before it
    # blocked. A marker naming a file that does not exist is a DANGLING
    # pointer, and marker_found stays False for it on purpose: every path
    # below then treats the message as an unfiled report, the marker lines
    # are stripped so the bad path can never be packed into an image, and
    # the block below keeps the pointer out of the lead's context. Until
    # 29 August 2026 a dangling marker passed straight through: 13 of 19
    # agents whose report Write was refused printed one, the lead held a
    # path to nothing, and the packing silently never happened.
    mode, content = "net", text
    # Filled by lift_identifiers below when the report is packed. Empty
    # on every path that never reaches the packer.
    ident_legend = []
    marker_found = False
    dangling = None
    for line in reversed(text.strip().splitlines()):
        if line.strip().startswith(MARKER):
            candidate = Path(line.strip()[len(MARKER):].strip())
            if candidate.is_file():
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

    # The net, added 15 August 2026 as the fallback for an agent that ignored
    # the file rule, and since 29 August 2026 the one delivery path there is:
    # no agent is asked to write a file any more, because the permission
    # classifier refused that Write 19 times in 19 attempts over benchmark
    # pairs 1 to 7 and a read-only agent has no Write tool at all. When a
    # long prose report arrives as the final message, this hook writes the
    # text to the report file ITSELF, blocks the stop once, and asks the
    # agent to reply with only the marker line. One block per agent: an agent
    # that sends prose a second time is accepted as text and packed as the
    # re-read copy. On a harness that ignores block decisions the behavior
    # also falls back to that. `content` rather than `text`, so a report that
    # arrived beside a dangling marker line is filed with the marker lines
    # already stripped and the bad path never reaches the file or the image.
    import re as _re
    blocked_flag = tmp_dir() / ("densepack-blocked-%s" % agent_id)

    # ONE ASK PER AGENT, FOR THE WHOLE OF ITS LIFE. blocked_flag cannot
    # carry that on its own: it is unlinked at the end of every stop,
    # because both `captured` below and the filed-report recovery read it
    # as "this stop followed a block", which makes it a per-stop signal
    # rather than a memory. An agent that stops more than once, which is
    # any background agent still taking messages, was therefore asked
    # again at every stop.
    #
    # MEASURED 31 August 2026: one agent was asked eight times in one
    # session and paid a turn for each repeat, and no densepack-blocked
    # file survived anywhere on disk to show it had ever been asked. The
    # marker below is never consumed, so the ask happens once and a
    # decline is taken as final: that agent's plain reply is its report
    # from then on, filed and packed as text like any other. Both markers
    # are swept by bootstrap.py at SessionStart.
    asked_flag = tmp_dir() / ("densepack-asked-%s" % agent_id)
    if (not marker_found and len(content) > stub_chars()
            and not blocked_flag.exists() and not asked_flag.exists()):
        code_chars = sum(len(b) for b in
                         _re.findall(r"```[^\n]*\n.*?```", content, _re.S))
        if code_chars <= len(content) * 0.5:
            target = tmp_dir() / ("densepack-report-%s.txt" % agent_id)
            target.write_text(content, encoding="utf-8")
            blocked_flag.write_text("1", encoding="utf-8")
            asked_flag.write_text("1", encoding="utf-8")
            if started:
                start_file.write_text(marker_record(started, spawned_by),
                                      encoding="utf-8")
            # Top-level decision and reason, which is the shape Claude Code's
            # hooks reference gives for Stop and SubagentStop under "Stop
            # decision control", read from the reference itself on 19 August
            # 2026. hookSpecificOutput carries additionalContext for these two
            # events and is not a decision, so nothing goes there. Verified
            # live the same day: a subagent told by its task to put the whole
            # report in its final message was blocked here, replied with the
            # marker line, and the manifest recorded captured true.
            # The wording matters. An earlier version read "DensePack saved
            # your report to X. Reply with exactly this one line". A read only
            # agent with no write tool refused it, because being asked to
            # reply with a path to a file it had not written read as being
            # asked to claim it had written one. It was right to refuse. The
            # message now says who wrote the file and what the line is for,
            # and it names the way out for an agent whose own instructions
            # forbid a pointer line, so the plugin never puts an agent in a
            # position where obeying it means saying something untrue.
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
    # A second reason the net exists, seen 24 August 2026. A Fable agent was
    # told to write its report to the file the marker names. Claude Code's
    # permission classifier denied that Write, so the agent returned its whole
    # 12,506 character report as its final message instead. The net packed it.
    # An agent can be unable to write the file through no fault of its own, so
    # the net is the ordinary path for some agents, not the exception.
    #
    # Second pass, no marker line. The agent replied normally rather than with
    # the pointer, which the block message allows and which some agents' own
    # instructions require. The file this hook wrote on the first pass holds
    # the real report, and the second reply can be far shorter than it. On 24
    # August 2026 an agent argued against the pointer line in 1,130 characters
    # and its 10,998 character answer was packed over and never reached the
    # lead, while the receipt reported a 17 per cent saving on the argument.
    # Pack the filed report whenever it is the longer of the two, so the net
    # can never cost the report it was added to protect.
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

    # Code does not survive condensing, so it never gets condensed. A report
    # that is MOSTLY code is left as plain text, no image at all. A report that
    # is mostly prose with some code blocks gets packed with each block lifted
    # out: the image carries a #=N=# marker where block N belonged, and the
    # blocks travel beside the image in a numbered plain text file the lead
    # reads at full fidelity. The marker shape never occurs in normal text, so
    # the lead can reassemble the report mechanically.
    import re as _re
    fences = _re.findall(r"```[^\n]*\n.*?```", content, _re.S)
    code_file = None
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

    # The scope net, run after code is lifted out so a code comment is never
    # scanned or moved: only the report's own prose can carry the sentence
    # this looks for. Follows the agentpack setting like the plugin's other
    # delegation rules; /agentpack-off leaves content exactly as the agent
    # wrote it. Applied here, once, before both downstream copies are made:
    # the plain text file below and the image the pack() call below draws
    # from the same content, so a report that stays text and one that gets
    # drawn into an image both carry the moved sentence in the same place.
    if settings().get("agentpack") != "off":
        content, _scope_notes = separate_scope_notes(content)

    source = tmp_dir() / ("densepack-src-%s.txt" % agent_id)
    source.write_text(content, encoding="utf-8")
    stem = tmp_dir() / ("densepack-img-%s" % agent_id)

    try:
        flat = dp.flatten(content)
        # Take every identifier out of the image and keep its value as text.
        # A run of letters and digits does not survive being drawn small: three
        # Fable agents and one Opus agent read one back wrong in the same place
        # on 25 August 2026, even drawn half again as large. A value that never
        # enters the image cannot be misread.
        flat, ident_legend = dp.lift_identifiers(flat)
        tag_pattern = dp.tag_pattern_from_legend(ident_legend)
        written, _target, _lh = dp.pack(flat, font_size(), str(stem),
                                        tag_pattern=tag_pattern)
    except Exception:
        manifest_write(dict(base, packed=False, reason="pack failed",
                            chars=len(content)))
        queue_text_row(base, "pack failed", chars=len(content),
                       text_tokens=round(len(content) / dp.CHARS_PER_TOKEN))
        return 0

    # The API charges an image its patch count and nothing else: ceil(width /
    # 28) times ceil(height / 28), no added fee, no minimum beyond the formula
    # itself. Checked 18 August 2026 against Anthropic's vision docs, section
    # "Resolution and token cost", which gives 1000 x 1000 px = 1296 tokens and
    # 200 x 200 px = 64:
    # https://platform.claude.com/docs/en/build-with-claude/vision
    # The handover cost below is this pipeline's own overhead, not the API's:
    # the pointer line that names the images is 137 characters, which is 57
    # tokens at the 2.40 divisor measured 31 August 2026, and each read call
    # costs about 80. An earlier comment here said 34 tokens, worked out when
    # the divisor was 4. It is counted from the pointer's own text
    # below, never from a constant, because a constant went stale once and
    # claimed 60. Text delivery pays neither, so the handover cost is added to
    # the image side. That way the receipt states the true delivered cost and
    # the pack-or-skip comparison cannot pack at a loss.
    patch_tokens = sum(dp.image_cost(w, h) for _p, w, h in written)
    # Which of the two pointer lines this report will arrive under. pointer.py
    # sends the longer stub line when no report in the batch came back as
    # prose, and the shorter one otherwise. Charging report_pointer() for a
    # stub left 134 characters out of every stub receipt until 21 August
    # 2026. That was 34 tokens at the divisor of 4 in force then, and is 56
    # at the 2.40 measured on 31 August 2026.
    pointer = (stub_pointer(len(written), tmp_dir()) if mode == "stub"
               else report_pointer(len(written), tmp_dir()))
    # The legend carries every identifier the image no longer holds. It goes
    # to a sidecar file now, PLAN-FABLE.md step 7, 29 August 2026, not into
    # the message: the pointer gains one short tag line naming the file
    # instead of the whole "tag = value" block, and that file name is still
    # this plugin's own text, so it is still charged below and the
    # comparison still refuses to pack at a loss.
    legend_file = dp.legend_sidecar(ident_legend, stem)
    if legend_file:
        pointer = pointer + "\nTags: " + legend_file
    # Per turn the conversation prefix carries either the text or the
    # image plus its pointer, so those are the two sides priced here. The
    # one Read that opens each image is paid once and amortises out of the
    # compare; see THE FLOOR IS FLAT in common.py.
    delivery_tokens = round(len(pointer) / dp.CHARS_PER_TOKEN)
    image_tokens = patch_tokens + delivery_tokens
    text_tokens = round(len(content) / dp.CHARS_PER_TOKEN)

    if image_tokens >= text_tokens:
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

    # Built from base, not field by field. base already holds agent_id,
    # agent_type, font_px, model, spawned_by and the timings, and the hand written
    # copy that used to be here listed four of those six. It dropped spawned_by, so
    # a packed row reached pointer.py with no spawner and every nested report was
    # charged to the lead anyway. tests/test_nested.py caught it on
    # 21 August 2026. Anything added to base from now on reaches the queue.
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
    # The legend file name goes in the entry, not only into the pricing
    # above. Charged to the lead from 25 August 2026 and never sent until
    # this field existed: the lead read a bare tag where a hex id or a comma
    # grouped number stood, with nothing to resolve it against. pointer.py
    # prints "Tags: <name>" beside the image line from this field, and the
    # values themselves stay in the sidecar file, opened only when needed.
    if legend_file:
        entry["legend_file"] = legend_file
    manifest_write(dict(entry, packed=True))
    append_queue(entry)

    # Every report image joins the list of images waiting to be read, so one
    # Read call can fetch a whole batch. Only command output joined it until
    # 25 August 2026, so read_gate.py never saw a report and three reports
    # cost three turns.
    #
    # Measured that day, running the same work with the plugin on and then
    # off: three reports of 2,768 characters each saved 1,779 tokens of text
    # between them and forced three extra Read turns. One turn re-reads the
    # whole conversation, about 615,000 tokens at that point, so the three
    # turns cost about 1,845,000. Batching is what makes a small report worth
    # drawing at all.
    try:
        with pending_path().open("a", encoding="utf-8") as fh:
            for path in entry["images"]:
                fh.write(json.dumps({
                    "image": str(path), "id": entry["agent_id"],
                    "source": str(source) if source else "",
                    "chars": entry["chars"],
                    "text_tokens": entry["text_tokens"],
                    "image_tokens": entry["image_tokens"],
                    "time": round(time.time(), 1)}) + "\n")
    except OSError:
        pass

    # /setpack keep both: .claude/tmp is scratch and gets cleaned, so a user who
    # wants the images or the report text keeps copies in a folder of their
    # own. Copied here, at creation, so nothing is lost if the session ends
    # before the pointer hook fires. A copy failure never breaks delivery.
    legend_path = tmp_dir() / legend_file if legend_file else None
    keep_copy(event.get("session_id") or spawned_by,
              images=[path for path, _w, _h in written],
              texts=[source] + ([code_file] if code_file is not None else [])
              + ([legend_path] if legend_path is not None else []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
