"""Packs a captured shell command's output into a dense image when that
image costs fewer tokens than the raw text, so a long build or test log
does not fill the context window with characters nobody reads twice.

HOW THIS FILE FITS, in plain words: a wrapped shell command runs the real
command, saves everything it printed to a file, and calls this script with
that file's path and the command's exit code. This script decides whether
the output is worth a picture, using the same price check subagent_stop.py
applies to an agent's report, and prints back only what the caller needs to
see.

    python bash_pack.py <output file> <exit code>

It is called by a wrapped shell command, not by a hook, so it takes plain
argv arguments and prints plain text, the same shape any command line tool
uses. Nothing here reads stdin or writes a hookSpecificOutput block.

Two outcomes, decided in this order.

  Under the floor.  The output is shorter than bash_chars(), common.py's
                     bash-route floor for the current reader. Reading it as text
                     already costs less than an image would, so it is
                     printed back unchanged and nothing else happens: no
                     image, no pending row, no manifest row.

  Over the floor.    The output keeps its blank lines and indents and is
                     converted by codepack.pack_code(), so its line numbers
                     are the output's own. Packing is still skipped when the image
                     turns out not to be the cheaper side; the output is
                     then printed unchanged, the same as under the floor,
                     but the attempt is recorded in the manifest.

densepack-pending.jsonl holds one row per image this script has packed, so
another script can read the queue of packed command outputs without
re-reading this one. Read it back with common.py's pending_entries(). Its
fields, one row per packed output:

    image         the PNG's path, as a string
    id            the short hash of the output that named the PNG
    chars         len() of the output text that was packed
    text_tokens   what the raw output would have cost as text
    image_tokens  what the packed image costs instead
    time          time.time(), rounded, when the row was written

Every attempt past the floor, packed or refused, also writes one row to
densepack-manifest.jsonl through subagent_stop.py's own manifest_write(),
the same file and the same field names an agent's report gets, plus a kind
field set to the string bash so a row this script wrote is never mistaken
for an agent's. The agent_id field holds this run's output hash instead of
an agent id, since a command has no agent of its own.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import actor_reader, bash_chars, code_size, disabled, \
    ensure_pillow, font_size, keep_copy, pending_path, READER_SIZES, \
    read_turn_fee, resolved_reader, tmp_dir, TOOL_RESULT_WRAP_TOKENS
from subagent_stop import manifest_write


def draw_size(actor):
    """The pixel size this output must be drawn at, and the reader profile
    that decided it, as (px, reader).

    `actor` is the key that names the agent which ran the command,
    "agent-<agent id>". bash_gate.py reads it off the PreToolUse event with
    common.actor_key() and passes it down the rewritten command line as the
    fourth argument to this script. Empty or None means the lead ran the
    command itself.

    common.actor_reader() is the same lookup drop_read_gate.py uses, so both
    paths answer from one source: the spawn record
    densepack-agentmodel-<agent id>, then Claude Code's own
    agent-<id>.meta.json, and no guess after that.

    The lead's own size answers only when there is no actor key or the
    lookup returns None. An actor that cannot be named never reaches here:
    bash_gate.py stands the whole rewrite down for a subagent whose
    actor_size() is None, so its output arrives as plain text.
    """
    if actor:
        reader = actor_reader(key=actor)
        if reader and reader in READER_SIZES:
            return READER_SIZES[reader], reader
    return font_size(), resolved_reader()


def output_id(content):
    """A short, stable hash of the raw output, so packing the same output
    twice names the same PNG instead of writing a second copy.

    The captured text, before line endings are made uniform: two commands
    whose output differs only in its line endings must not share one name,
    or the second overwrites the first one's exact text.
    """
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:12]


def append_pending(row):
    # Sealed, because common.pending_entries() drops a row without the seal.
    import common
    row = dict(row, seal=common._row_seal(row))
    with pending_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def pack_output(content, session=None, actor=None, exact=None):
    """Do the whole floor, price and pack decision for one output.

    session is kept for the manifest and the callers; the pointer itself
    is the same for every reader, the two paths and nothing else.

    actor names the agent that ran the command and will read the picture,
    and decides the pixel size through draw_size(). None means the lead.

    Returns a dict a caller can act on without re-deriving anything:

        packed   bool, whether an image was written and is still on disk
        text     the untouched output, always present, printed back as is
                 whenever packed is False
        image    the PNG's path, as a string, when packed is True
        legend_file  the sidecar file's own name, from legend_sidecar(),
                 None when there was nothing to lift or packed is False.
                 The values live in that file, not in this dict's text.
        pointer  the one line naming the PNG, the folder and the exact
                 text file, when packed is True
        packed_text  the text actually drawn into the image, tags and all,
                 when packed is True. main() never prints this; it exists
                 so a caller can check an identifier never reached the
                 image without reading pixels.
    """
    # drawn_for and drawn_model are on EVERY row this script writes, packed
    # or refused, because a row that names only font_px cannot say whose
    # floor that number was measured against.
    px, reader = draw_size(actor)
    base = {"kind": "bash", "font_px": px, "drawn_for": str(actor or ""),
            "drawn_model": reader}

    if disabled(session) or len(content) < bash_chars():
        return {"packed": False, "text": content}
    # Output too big to convert in a reasonable time stays text, with the
    # same limits as a Read: 250,000 characters, 6,000 lines, no null byte.
    if len(content) > 250000 or content.count("\n") > 6000 or "\x00" in content:
        return {"packed": False, "text": content}

    ident = output_id(content if exact is None else exact)

    if not ensure_pillow():
        manifest_write(dict(base, agent_id=ident, packed=False,
                            reason="Pillow missing", chars=len(content),
                            ended=round(time.time(), 1)))
        return {"packed": False, "text": content}

    import densepack as dp

    stem = tmp_dir() / ("densepack-bash-%s" % ident)
    # The draw is wrapped the way subagent_stop.py wraps its own. dp.load()
    # raises when no font file is present, and an unwrapped raise here would
    # kill the hook instead of letting the command's output through. The
    # reason logged is the one the manifest and pointer.py carry for a draw
    # that did not finish.
    try:
        # The output goes to the code renderer as it is, with its blank lines
        # and indents. The renderer numbers every line the way a Read's image
        # numbers it: a gap for each blank line, and a red count for an indent.
        # So line 58 of the output is labelled 58, the number grep -n gives.
        flat = content.replace("\r\n", "\n").replace("\r", "\n")
        # Take every identifier out of the image and keep its value as text. A
        # run of letters and digits does not survive being drawn small, the
        # same reason subagent_stop.py and brief_pack.py both lift identifiers
        # before packing.
        flat, ident_legend = dp.lift_identifiers(flat)
        tag_pattern = dp.tag_pattern_from_legend(ident_legend)
        # px, not font_size(): the draw uses the size the manifest row names.
        # The code renderer draws the same bands, ink curve, glyph clearance
        # and marks a Read gets, so Bash output reads the same way. Not
        # python: the classifier by shape colours a command's output.
        import codepack
        written, _target, _lh = codepack.pack_code(
            flat, code_size(px, reader), str(stem),
            python=False, reader=reader)
        # The code renderer names its pages as strings; the rest of this
        # file reads them as paths.
        written = [(Path(p), w, h) for p, w, h in written]
    except Exception:
        manifest_write(dict(base, agent_id=ident, packed=False,
                            reason="pack failed", chars=len(content),
                            ended=round(time.time(), 1)))
        return {"packed": False, "text": content}

    legend_file = dp.legend_sidecar(ident_legend, stem)
    image_path = written[0][0]

    patch_tokens = sum(dp.image_cost(w, h) for _p, w, h in written)
    # The source file's name is fixed by the output's own hash, so it is
    # known here, before the file is written below, and can be named in the
    # pointer that gets priced. A picture carries prose correctly and can
    # lose an exact string. Anything that has to match a file byte for byte,
    # such as an Edit's old_string, comes from the words on disk, never from
    # the image.
    # The words are named, and nothing more is said about them. The rule that
    # exact text comes from the words and not from the picture is in the
    # plugin's instructions, which are sent once. Repeating it on every
    # pointer costs part of the saving on every turn.
    source_name = "densepack-bashsrc-%s.txt" % ident
    # The sidecar holds every lifted identifier, but the pointer does not
    # name it: the exact-text file carries every value verbatim, so a Tags
    # line would be a second path to the same bytes, paid in the prefix on
    # every turn.
    pointer = pointer_line(image_path.name, source_name)
    if len(written) > 1:
        # Every image is named. Without this the reader is charged for the
        # images after the first and never learns they exist.
        import pointer as pointer_module
        pointer = pointer + " " + pointer_module.later_images_note(
            "the command output", str(tmp_dir()),
            [Path(p).name for p, _w, _h in written])
    # Per turn the prefix carries either the text or the image plus its
    # pointer, so those are the two sides priced here. The one Read that
    # opens each image is paid once, and read_turn_fee() below charges it.
    # See read_turn_fee in common.py.
    # Everything the lead is handed in place of the output is priced: the
    # head line and the pointer.
    head = _head(content)
    delivery_tokens = round((len(pointer) + len(head) + 1) / dp.CHARS_PER_TOKEN)
    # The tool result that carries the pointer costs more than its
    # characters, so the wrapper is charged here.
    image_tokens = patch_tokens + delivery_tokens + TOOL_RESULT_WRAP_TOKENS
    text_tokens = round(len(content) / dp.CHARS_PER_TOKEN)
    # The picture must also pay for the Read turn that opens it, sized from
    # the session's context; see read_turn_fee in common.py.
    fee = read_turn_fee(session, actor)

    if text_tokens - image_tokens < fee:
        for path, _w, _h in written:
            Path(path).unlink(missing_ok=True)
        if legend_file:
            (tmp_dir() / legend_file).unlink(missing_ok=True)
        manifest_write(dict(base, agent_id=ident, packed=False,
                            reason="text measured cheaper", chars=len(content),
                            text_tokens=text_tokens, image_tokens=image_tokens,
                            patch_tokens=patch_tokens,
                            delivery_tokens=delivery_tokens, turn_fee=fee,
                            ended=round(time.time(), 1)))
        return {"packed": False, "text": content}

    # The words go on disk beside the picture and into the vault, the same as
    # a report's and a brief's do, so a reader that needs an exact value has
    # a file to fall back on. Rerunning the command is not the same thing,
    # because a command's output changes.
    source_path = tmp_dir() / source_name
    try:
        # newline="" and the captured bytes, so this file is the exact text
        # the pointer says it is. Windows text mode made every LF a CRLF.
        # Written to a new file and moved onto the name: the name is the
        # output's own hash, so a project that chooses what a command prints
        # knows it, and a link planted there would take the write.
        from common import write_text_atomic
        write_text_atomic(source_path, content if exact is None else exact)
        from common import seal_pair
        # One seal over the whole pack, so a Read of this file is answered
        # with images this machine's plugin wrote and with no other.
        seal_pair(source_path, [Path(p).name for p, _w, _h in written])
        # bash_pack.py is run by a wrapped shell command, not by a hook, so no
        # event carries the session id. The lead's own id is on disk, written
        # at session start.
        try:
            here = (tmp_dir() / "densepack-lead-session").read_text(
                encoding="utf-8").strip()
        except OSError:
            here = "unknown-conversation"
        legend_path = tmp_dir() / legend_file if legend_file else None
        # Every image, and the seal beside the text, so a Read of the vault
        # copy is still swapped for its image. The other two packers copy
        # every image already.
        keep_copy(here, images=[str(p) for p, _w, _h in written],
                 texts=[str(source_path), str(source_path) + ".seal"]
                 + ([str(legend_path)] if legend_path is not None else []))
    except OSError:
        source_path = None

    # One row per image, so read_gate.py can hand over every image of a long
    # output and not the first alone.
    for path, _w, _h in written:
        append_pending({"image": str(path), "id": ident,
                        "source": str(source_path) if source_path else "",
                        "chars": len(content), "text_tokens": text_tokens,
                        "image_tokens": image_tokens,
                        "time": round(time.time(), 1)})

    # The session this pack belongs to. spawned_by names it, so a
    # per-session total counts only that session's rows.
    entry = dict(base, agent_id=ident, packed=True, spawned_by=str(session or ""),
                images=[str(p) for p, _w, _h in written],
                dims=["%dx%d" % (w, h) for _p, w, h in written],
                pixels=sum(w * h for _p, w, h in written),
                chars=len(content), text_tokens=text_tokens,
                image_tokens=image_tokens, patch_tokens=patch_tokens,
                delivery_tokens=delivery_tokens,
                ended=round(time.time(), 1))
    if legend_file:
        entry["legend_file"] = legend_file
    manifest_write(entry)

    return {"packed": True, "image": str(image_path), "legend_file": legend_file,
            "pointer": pointer, "head": head, "text": content,
            # The text that was actually drawn, tags and all, kept here for
            # a caller that wants to prove an identifier never reached the
            # image: it never appears in this string, only in legend.
            "packed_text": flat}


def _total(content):
    """How much output there is, so a preview cannot read as the whole of it."""
    # A final newline ends the last line; it does not start another one.
    lines = content.count("\n") + (0 if content.endswith("\n") else 1)
    return "%s characters over %s line%s" % (
        format(len(content), ","), format(lines, ","), "" if lines == 1 else "s")


HEAD_CHARS = 80


def _head(content):
    """The one line the lead sees in place of the output: its size and the
    start of its first non-blank line, so the label can never read as the
    whole of it."""
    first = next((line.strip() for line in content.splitlines() if line.strip()), "")
    if len(first) > HEAD_CHARS:
        first = first[:HEAD_CHARS] + "..."
    return "--- %s, starts: %s ---" % (_total(content), first)


def pointer_line(image_name, source_name):
    """The pointer. Names the image, the folder, and the exact text file.

    THE FOLDER PRINTS EVERY TIME. A subagent is a separate run and never sees
    a sentence sent once per session, so a pointer without the folder sends
    an agent searching the disk for the file.

    The exact text file is named second because a reader that needs a line
    byte for byte must take it from the words on disk, never from the picture.

    NOTHING ELSE RIDES ON IT. The pointer sits in the prefix on every later
    turn, exactly like the image, so it is the floor: content smaller than
    the pointer describing it can never pay back. The rules image every agent
    reads at session start holds the reading rules. The two paths are the
    only part that changes per command.
    """
    # Information, not an order: a pointer that tells a reader what to do reads
    # to some readers as a prompt injection.
    return ("DensePack: command output packed as %s in %s. That image holds the "
            "command's output. Exact text: %s."
            % (image_name, tmp_dir(), source_name))


def utf8_stdout():
    """Makes stdout carry any character the command printed.

    Python picks the console's own encoding, which on Windows is often
    cp1252, and cp1252 cannot encode most of what a command prints. Writing
    such a character raises UnicodeEncodeError and loses the whole command
    output.

    errors="replace" rather than "strict", because a character that cannot be
    carried is worth one replacement mark and never worth the whole output.
    A Python without reconfigure keeps its default encoding rather than
    failing here.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            # newline="" writes "\n" as "\n". Windows text mode made it CRLF.
            stream.reconfigure(encoding="utf-8", errors="replace", newline="")
        except (AttributeError, ValueError):
            pass


def main():
    utf8_stdout()
    if len(sys.argv) < 3:
        sys.stderr.write(
            "usage: bash_pack.py <output file> <exit code> "
            "[session id] [actor key]\n")
        return 1
    output_path, exit_code = sys.argv[1], sys.argv[2]
    # bash_gate.py passes the session id it read off the hook event. A rewrite
    # that passes only two arguments leaves the session None.
    session = sys.argv[3] if len(sys.argv) > 3 else None
    # The agent that ran the command, "agent-<agent id>", or "" for the lead.
    # bash_gate.py appends it. A rewrite that passes three arguments or two
    # leaves actor None, and the lead's size answers.
    actor = sys.argv[4] if len(sys.argv) > 4 else None

    try:
        # newline="" keeps the output's own line endings, so output that stays
        # text comes back byte for byte: no CR added, no lone CR made a break.
        with open(output_path, encoding="utf-8", errors="replace", newline="") as fh:
            exact = fh.read()
    except OSError:
        return 1
    # The image counts lines, so it gets universal newlines, as read_text gave.
    content = exact.replace("\r\n", "\n").replace("\r", "\n")

    # Nothing can be sealed without the key, and every reader drops an
    # unsealed row, so a packed output would reach nobody. Text goes through.
    from common import seal_key
    result = ({"packed": False, "text": content} if seal_key() is None
              else pack_output(content, session=session, actor=actor, exact=exact))
    if not result["packed"]:
        sys.stdout.write(exact)
        return 0

    # A bare number read to a reader as a stray character, so it carries a label.
    print("Exit code: %s" % exit_code)
    # The head line carries the output's real size, so a reader cannot take
    # it for the whole result and skip the image.
    print(result["head"])
    print(result["pointer"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
