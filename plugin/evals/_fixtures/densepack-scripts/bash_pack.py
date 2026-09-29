"""Packs the captured output of a shell command into a dense image when that
image costs fewer tokens than the raw text. A long build or test log then
does not fill the context window with characters that nobody reads twice.

hooks.json does not register bash_gate.py, the hook that writes the wrapped
command for this script. bash_image.py returns Bash output as an image in the
same tool result.

A wrapped shell command runs the real command, saves all its output to a
file, and calls this script with the file path and the exit code of the
command. This script checks whether the output is worth an image. It uses
the same price check that subagent_stop.py uses for the report of an agent.
It prints only what the caller needs to see.

    python bash_pack.py <output file> <exit code>

A wrapped shell command calls this script, not a hook. The script takes plain
argv arguments and prints plain text, the same shape as each command line
tool. It does not read stdin or write a hookSpecificOutput block.

Two outcomes, in this order.

  Under the floor.  The output is shorter than bash_chars(), the bash-route
                     floor in common.py for the current model. The output
                     as text costs less than an image, and the script
                     prints it unchanged. Nothing else happens. No image,
                     no pending row, no manifest row.

  Over the floor.    The output keeps its blank lines and indents, and
                     codepack.pack_code() converts it. Its line numbers are
                     the line numbers of the output. When the image is not
                     the cheaper side, the script skips the pack and prints
                     the output unchanged, the same as under the floor. The
                     manifest records the attempt.

densepack-pending.jsonl holds one row per image that this script packed.
Another script can read the queue of packed command outputs without reading
this one. common.pending_entries() reads it. Its fields, one row per packed
output:

    image         the PNG path, as a string
    id            the short hash of the output that named the PNG
    chars         len() of the output text that the script packed
    text_tokens   the cost of the raw output as text
    image_tokens  the cost of the packed image
    time          time.time(), rounded, when the script wrote the row

Each attempt past the floor, packed or rejected, also writes one row to
densepack-manifest.jsonl through manifest_write() in subagent_stop.py. It is
the same file, with the same field names, as for the report of an agent,
plus a kind field set to the string bash. A row from this script then never
looks like a row for an agent. The agent_id field holds the output hash of
this run in place of an agent id, because a command has no agent.
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
    """Return the pixel size for this output and the model profile that sets
    it, as (px, reader).

    `actor` is the key that names the agent that ran the command,
    "agent-<agent id>". bash_gate.py reads it from the PreToolUse event with
    common.actor_key() and passes it on the rewritten command line as the
    fourth argument to this script. Empty or None means that the lead ran
    the command.

    drop_read_gate.py uses the same lookup, common.actor_reader(). The two
    paths use one source. First the spawn record
    densepack-agentmodel-<agent id>, then the agent-<id>.meta.json file of
    Claude Code, and no guess after that.

    The function uses the size of the lead only when there is no actor key
    or the lookup returns None. An actor without a name never gets here.
    bash_gate.py skips the whole rewrite for a subagent whose actor_size()
    is None, and its output arrives as plain text.
    """
    if actor:
        reader = actor_reader(key=actor)
        if reader and reader in READER_SIZES:
            return READER_SIZES[reader], reader
    return font_size(), resolved_reader()


def output_id(content):
    """Return a short, stable hash of the raw output. Two packs of the same
    output name the same PNG and do not write a second copy.

    The hash uses the captured text before the line endings change. Two
    commands whose output differs only in its line endings must not share
    one name. Otherwise the second overwrites the exact text of the first.
    """
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:12]


def append_pending(row):
    # The row gets a seal. common.pending_entries() drops a row without it.
    import common
    row = dict(row, seal=common._row_seal(row))
    with pending_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def pack_output(content, session=None, actor=None, exact=None):
    """Make the whole floor, price and pack decision for one output.

    session is for the manifest and the callers. The pointer is the same
    for each model. It holds the two paths and nothing else.

    actor names the agent that ran the command and reads the image. It sets
    the pixel size through draw_size(). None means the lead.

    Returns a dict that a caller can use without computing anything again:

        packed   bool, whether the function wrote an image that is still
                 on disk
        text     the unchanged output, always present, printed as is
                 when packed is False
        image    the PNG path, as a string, when packed is True
        legend_file  the name of the sidecar file, from legend_sidecar(),
                 None when there was nothing to lift or packed is False.
                 The values are in that file, not in the text of this dict.
        pointer  the one line that names the PNG, the folder and the exact
                 text file, when packed is True
        packed_text  the text in the image, with its tags, when packed is
                 True. main() never prints this. A caller can use it to
                 check that an identifier never reached the image without
                 reading pixels.
    """
    # drawn_for and drawn_model are on EACH row that this script writes,
    # packed or rejected. A row that names only font_px does not show the
    # model floor for that number.
    px, reader = draw_size(actor)
    base = {"kind": "bash", "font_px": px, "drawn_for": str(actor or ""),
            "drawn_model": reader}

    if disabled(session) or len(content) < bash_chars():
        return {"packed": False, "text": content}
    # Output too big to convert in a reasonable time stays text. The limits
    # are the same as for a Read, 250,000 characters, 6,000 lines and no
    # null byte.
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
    # A try covers the pack, the same as in subagent_stop.py. dp.load()
    # raises when no font file is present. Without the try, the raise stops
    # the script, and the command output does not get through. The logged
    # reason is the same one that the manifest and pointer.py use for a pack
    # that did not finish.
    try:
        # The output goes to the code renderer as it is, with its blank lines
        # and indents. The renderer numbers each line the same way as the
        # image of a Read, with a gap for each blank line and a red count for
        # an indent. Line 58 of the output has the label 58, the number that
        # grep -n gives.
        flat = content.replace("\r\n", "\n").replace("\r", "\n")
        # Take each identifier out of the image and keep its value as text. A
        # small image can lose a run of letters and digits. For the same
        # reason, subagent_stop.py and brief_pack.py lift identifiers before
        # they pack.
        flat, ident_legend = dp.lift_identifiers(flat)
        tag_pattern = dp.tag_pattern_from_legend(ident_legend)
        # px, not font_size(). The pack uses the size that the manifest row
        # names. The code renderer uses the same bands, ink curve, glyph
        # clearance and marks as for a Read, and Bash output looks the same.
        # python=False. With python=True, the shape classifier colors the
        # output of a command.
        import codepack
        written, _target, _lh = codepack.pack_code(
            flat, code_size(px, reader), str(stem),
            python=False, reader=reader)
        # The code renderer names its pages as strings. The rest of this
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
    # The hash of the output sets the name of the source file. The name is
    # known here, before the code below writes the file, and the priced
    # pointer can name it. An image holds prose correctly and can lose an
    # exact string. Text that must match a file byte for byte, such as the
    # old_string of an Edit, comes from the text on disk, never from the
    # image.
    # The pointer names the text file and says nothing more about it. The
    # rule that exact text comes from the text file and not from the image
    # is in the plugin instructions, which the plugin sends once. The same rule on
    # each pointer costs part of the saving on each turn.
    source_name = "densepack-bashsrc-%s.txt" % ident
    # The sidecar holds each lifted identifier, but the pointer does not name
    # it. The exact-text file holds each value verbatim. A Tags line is a
    # second path to the same bytes, and the prefix pays for it on each turn.
    pointer = pointer_line(image_path.name, source_name)
    if len(written) > 1:
        # The pointer names each image. Without this, the model pays for the
        # images after the first and gets no note that they exist.
        import pointer as pointer_module
        pointer = pointer + " " + pointer_module.later_images_note(
            "the command output", str(tmp_dir()),
            [Path(p).name for p, _w, _h in written])
    # On each turn, the prefix holds the text, or the image with its
    # pointer. The code prices those two sides here. The one Read that opens
    # each image costs once, and read_turn_fee() below charges it. See
    # read_turn_fee in common.py.
    # The code prices all text that the lead gets in place of the output,
    # the head line and the pointer.
    head = _head(content)
    delivery_tokens = round((len(pointer) + len(head) + 1) / dp.CHARS_PER_TOKEN)
    # The tool result that holds the pointer costs more than its
    # characters. The code charges the wrapper here.
    image_tokens = patch_tokens + delivery_tokens + TOOL_RESULT_WRAP_TOKENS
    text_tokens = round(len(content) / dp.CHARS_PER_TOKEN)
    # The image must also pay for the Read turn that opens it. The fee
    # depends on the context size of the session. See read_turn_fee in
    # common.py.
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

    # The text goes on disk next to the image and into the vault, the same
    # as for a report and a brief. A model that needs an exact value then
    # has a file to read. A second run of the command is not the same,
    # because the output of a command changes.
    source_path = tmp_dir() / source_name
    try:
        # newline="" and the captured bytes. This file is then the exact
        # text that the pointer names. Windows text mode made each LF a
        # CRLF. The write goes to a new file that then moves onto the name.
        # The name is the hash of the output. A project that controls what
        # a command prints can compute the name, and a link at that name
        # can take a direct write.
        from common import write_text_atomic
        write_text_atomic(source_path, content if exact is None else exact)
        from common import seal_pair
        # One seal covers the whole pack. A Read of this file then returns
        # only images that the plugin on this machine wrote.
        seal_pair(source_path, [Path(p).name for p, _w, _h in written])
        # A wrapped shell command runs bash_pack.py, not a hook. No event
        # holds the session id. The session start hook writes the id of the
        # lead to disk.
        try:
            here = (tmp_dir() / "densepack-lead-session").read_text(
                encoding="utf-8").strip()
        except OSError:
            here = "unknown-conversation"
        legend_path = tmp_dir() / legend_file if legend_file else None
        # Each image, and the seal next to the text. A Read of the vault copy
        # then still gets its image. The other two packers already copy each
        # image.
        keep_copy(here, images=[str(p) for p, _w, _h in written],
                 texts=[str(source_path), str(source_path) + ".seal"]
                 + ([str(legend_path)] if legend_path is not None else []))
    except OSError:
        source_path = None

    # One row per image. read_gate.py can then return each image of a long
    # output and not the first alone.
    for path, _w, _h in written:
        append_pending({"image": str(path), "id": ident,
                        "source": str(source_path) if source_path else "",
                        "chars": len(content), "text_tokens": text_tokens,
                        "image_tokens": image_tokens,
                        "time": round(time.time(), 1)})

    # The session of this pack. spawned_by names it, and a per-session total
    # counts only the rows of that session.
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
            # The text in the image, with its tags. A caller can use it to
            # show that an identifier never reached the image. The
            # identifier is never in this string, only in the legend.
            "packed_text": flat}


def _total(content):
    """Return the output size. A preview then does not look like all of it."""
    # A final newline ends the last line. It does not start another line.
    lines = content.count("\n") + (0 if content.endswith("\n") else 1)
    return "%s characters over %s line%s" % (
        format(len(content), ","), format(lines, ","), "" if lines == 1 else "s")


HEAD_CHARS = 80


def _head(content):
    """Return the one line that the lead sees in place of the output. The
    line holds the output size and the start of the first non-blank line.
    The label then never looks like the whole output."""
    first = next((line.strip() for line in content.splitlines() if line.strip()), "")
    if len(first) > HEAD_CHARS:
        first = first[:HEAD_CHARS] + "..."
    return "--- %s, starts: %s ---" % (_total(content), first)


def pointer_line(image_name, source_name):
    """Return the pointer. It names the image, the folder and the exact text
    file.

    THE FOLDER PRINTS EACH TIME. A subagent is a separate run and never gets
    a sentence sent once per session. Without the folder, an agent searches
    the disk for the file.

    The pointer names the exact text file second. A model that needs a line
    byte for byte must take it from the text on disk, never from the image.

    NOTHING ELSE GOES ON IT. The pointer stays in the prefix on each later
    turn, the same as the image, and it sets the floor. Content smaller than
    its pointer never saves tokens. The rules image that each agent reads at
    session start holds the reading rules. The two paths are the only part
    that changes per command.
    """
    # Information, not an order. Some models read a pointer that tells them
    # what to do as a prompt injection.
    return ("DensePack: command output packed as %s in %s. That image holds the "
            "command's output. Exact text: %s."
            % (image_name, tmp_dir(), source_name))


def utf8_stdout():
    """Makes stdout accept each character that the command printed.

    Python uses the encoding of the console, which on Windows is often
    cp1252. cp1252 cannot encode most of what a command prints. A write of
    such a character raises UnicodeEncodeError and loses the whole command
    output.

    errors="replace" and not "strict". A character that the stream cannot
    encode gets one replacement mark and never costs the whole output. A
    Python without reconfigure keeps its default encoding and does not fail
    here.
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
    # bash_gate.py passes the session id from the hook event. With only two
    # arguments, the session is None.
    session = sys.argv[3] if len(sys.argv) > 3 else None
    # The agent that ran the command, "agent-<agent id>", or "" for the lead.
    # bash_gate.py adds it. With three arguments or two, actor is None, and
    # the code uses the size of the lead.
    actor = sys.argv[4] if len(sys.argv) > 4 else None

    try:
        # newline="" keeps the line endings of the output. Output that stays
        # text returns byte for byte. The read adds no CR and does not change
        # a lone CR to a break.
        with open(output_path, encoding="utf-8", errors="replace", newline="") as fh:
            exact = fh.read()
    except OSError:
        return 1
    # The image counts lines, and it gets universal newlines, as read_text gave.
    content = exact.replace("\r\n", "\n").replace("\r", "\n")

    # Without the key, the code cannot seal a row. Each script that reads the
    # queue drops an unsealed row, and a packed output reaches no one. The
    # text goes through.
    from common import seal_key
    result = ({"packed": False, "text": content} if seal_key() is None
              else pack_output(content, session=session, actor=actor, exact=exact))
    if not result["packed"]:
        sys.stdout.write(exact)
        return 0

    # A model can read a bare number as a stray character. The number gets a
    # label.
    print("Exit code: %s" % exit_code)
    # The head line holds the real size of the output. The model cannot take
    # it for the whole result and skip the image.
    print(result["head"])
    print(result["pointer"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
