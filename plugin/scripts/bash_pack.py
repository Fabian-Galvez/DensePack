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

  Over the floor.    The output is flattened, its identifiers are lifted
                     out so a hash or a long number cannot be misread
                     small, and it is packed with the production pack() in
                     densepack.py. Packing is still skipped when the image
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

from common import bash_chars, disabled, ensure_pillow, font_size, \
    keep_copy, pending_path, tmp_dir
from subagent_stop import manifest_write


def output_id(content):
    """A short, stable hash of the raw output, so packing the same output
    twice names the same PNG instead of writing a second copy."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def append_pending(row):
    with pending_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def numbered(content):
    """The command's output with each line's own number in front of it.

    A packed image is a picture of the words and carries no position, so a
    reader asked for line 44 has nothing to count. Measured 26 August 2026 on
    twenty questions asking for one exact line each: without numbers the
    plugin side answered 15 of 20 and every miss took the line whose grep line
    number matched the number asked for, never a character read wrong.

    Blank lines are dropped by dp.flatten, so they are dropped here too and
    the numbers match what is drawn.

    Only the picture is numbered. densepack-bashsrc-<id>.txt keeps the command
    output byte for byte, because that file exists so a value can be copied
    exactly, and a number in front of it would not be exact.
    """
    lines = []
    n = 0
    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not " ".join(line.split()):
            continue
        n += 1
        lines.append("%d|%s" % (n, line))
    return "\n".join(lines)


def pack_output(content, session=None):
    """Do the whole floor, price and pack decision for one output.

    session is kept for the manifest and the callers; the pointer itself
    is the same for every reader since 30 August 2026, the two paths and
    nothing else.

    Returns a dict a caller can act on without re-deriving anything:

        packed   bool, whether an image was written and is still on disk
        text     the untouched output, always present, printed back as is
                 whenever packed is False
        image    the PNG's path, as a string, when packed is True
        legend_file  the sidecar file's own name, from legend_sidecar(),
                 None when there was nothing to lift or packed is False.
                 PLAN-FABLE.md step 7, 29 August 2026: the values live in
                 that file now, not in this dict's text.
        pointer  the one line naming the PNG, the folder and the exact
                 text file, when packed is True
        packed_text  the text actually drawn into the image, tags and all,
                 when packed is True. main() never prints this; it exists
                 so a caller can check an identifier never reached the
                 image without reading pixels.
    """
    base = {"kind": "bash", "font_px": font_size()}

    if disabled(session) or len(content) < bash_chars():
        return {"packed": False, "text": content}

    ident = output_id(content)

    if not ensure_pillow():
        manifest_write(dict(base, agent_id=ident, packed=False,
                            reason="Pillow missing", chars=len(content),
                            ended=round(time.time(), 1)))
        return {"packed": False, "text": content}

    import densepack as dp

    stem = tmp_dir() / ("densepack-bash-%s" % ident)
    # The draw is wrapped the way subagent_stop.py wraps its own. dp.load()
    # raises when no font file on the chain is present, which happens on a
    # POSIX machine that carries neither the bundled DejaVu pair nor a system
    # monospace font, and an unwrapped raise here would kill the hook instead
    # of letting the command's output through. The reason logged is the one
    # the manifest and pointer.py already carry for a draw that did not
    # finish.
    try:
        flat = dp.flatten(numbered(content))
        # Take every identifier out of the image and keep its value as text. A
        # run of letters and digits does not survive being drawn small, the
        # same reason subagent_stop.py and brief_pack.py both lift identifiers
        # before packing.
        flat, ident_legend = dp.lift_identifiers(flat)
        tag_pattern = dp.tag_pattern_from_legend(ident_legend)
        written, _target, _lh = dp.pack(flat, font_size(), str(stem),
                                        tag_pattern=tag_pattern)
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
    # pointer that gets priced. The line matters: a picture drawn at 10 px
    # carries prose correctly and loses an exact string, measured on this
    # project's own reading scores. Anything that has to match a file byte
    # for byte, such as an Edit's old_string, comes from the words on disk,
    # never from the image.
    # The words are named, and nothing more is said about them. The rule that
    # exact text comes from the words and not from the picture is in the
    # plugin's instructions, which are sent once. Repeating it on every
    # pointer costs 0.28 percentage points of the whole saving, measured over
    # the 8 largest transcripts on 25 August 2026.
    source_name = "densepack-bashsrc-%s.txt" % ident
    # The sidecar still holds every lifted identifier, but the pointer no
    # longer names it, since 30 August 2026: the exact-text file carries
    # every value verbatim, so the Tags line was a second path to the same
    # bytes, paid in the prefix on every turn.
    pointer = pointer_line(image_path.name, source_name)
    # Per turn the prefix carries either the text or the image plus its
    # pointer, so those are the two sides priced here. The one Read that
    # opens each image is paid once and amortises out of the compare; see
    # THE FLOOR IS FLAT in common.py.
    delivery_tokens = round(len(pointer) / dp.CHARS_PER_TOKEN)
    image_tokens = patch_tokens + delivery_tokens
    text_tokens = round(len(content) / dp.CHARS_PER_TOKEN)

    if image_tokens >= text_tokens:
        for path, _w, _h in written:
            Path(path).unlink(missing_ok=True)
        if legend_file:
            (tmp_dir() / legend_file).unlink(missing_ok=True)
        manifest_write(dict(base, agent_id=ident, packed=False,
                            reason="text measured cheaper", chars=len(content),
                            text_tokens=text_tokens, image_tokens=image_tokens,
                            patch_tokens=patch_tokens,
                            delivery_tokens=delivery_tokens,
                            ended=round(time.time(), 1)))
        return {"packed": False, "text": content}

    # The words go on disk beside the picture and into the vault, the same as
    # a report's and a brief's do. Without this the command output existed
    # only as pixels: a reader that needed an exact value from it had nothing
    # to fall back on, and rerunning the command is not the same thing,
    # because a command's output changes. Found by Fable 5 on 25 August 2026,
    # which read every keep_copy caller and found this direction missing.
    source_path = tmp_dir() / source_name
    try:
        source_path.write_text(content, encoding="utf-8")
        # bash_pack.py is run by a wrapped shell command, not by a hook, so no
        # event carries the session id. The lead's own id is on disk, written
        # at session start.
        try:
            here = (tmp_dir() / "densepack-lead-session").read_text(
                encoding="utf-8").strip()
        except OSError:
            here = "unknown-conversation"
        legend_path = tmp_dir() / legend_file if legend_file else None
        keep_copy(here, images=[str(image_path)],
                 texts=[str(source_path)]
                 + ([str(legend_path)] if legend_path is not None else []))
    except OSError:
        source_path = None

    append_pending({"image": str(image_path), "id": ident,
                    "source": str(source_path) if source_path else "",
                    "chars": len(content), "text_tokens": text_tokens,
                    "image_tokens": image_tokens,
                    "time": round(time.time(), 1)})

    # The reader this pack belongs to. Every bash pack wrote a blank
    # spawned_by until 26 August 2026, so the manifest could not say which
    # session a packed command came from and any per-session total counted
    # every session's rows. Measured that day: 789 of 939 packed rows carried
    # no session at all.
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
            "pointer": pointer, "text": content,
            # The text that was actually drawn, tags and all, kept here for
            # a caller that wants to prove an identifier never reached the
            # image: it never appears in this string, only in legend.
            "packed_text": flat}


def _total(content):
    """How much output there is, so a preview cannot read as the whole of it."""
    return "%s characters over %s lines" % (
        format(len(content), ","), format(content.count("\n") + 1, ","))


def pointer_line(image_name, source_name):
    """The pointer. Names the image, the folder, and the exact text file.

    THE FOLDER PRINTS EVERY TIME, and dropping it to save characters has been
    tried and measured. On the on side of a 100 tool call comparison on
    25 August 2026 the folder was sent once per session and left off after
    that; a subagent is a separate run, it never saw the sentence that carried
    the folder, and three of four agents ran find / for 120 seconds each
    looking for a file whose path this line used to hold. 360 seconds of a 900
    second run went into that search. The 89 characters are cheaper.

    The exact text file is named second because a reader that needs a line
    byte for byte must take it from the words on disk, never from the picture.

    NOTHING ELSE RIDES ON IT, since 30 August 2026. The pointer sits in the
    prefix on every later turn, exactly like the image, so it is the floor:
    content smaller than the pointer describing it can never pay back. The
    clauses it used to carry, the sed line pull, the drawn line numbers,
    "Both hold the complete output" and the Tags line, are all teaching the
    rules image every agent reads at session start already holds. The two
    paths are the only part that changes per command.

    ONE EXCEPTION ADDED 31 August 2026: a fixed sentence
    stating the substitution is the plugin's own delivery, not tampering, the
    same sentence every other pointer route now carries. Two readers had
    refused legitimate work over an unexplained image in place of the file
    they asked for. The floor moved by that sentence's own characters; COSTS.md
    and the fee tests read this function to price it, never a copied number.
    """
    return ("DensePack: command output packed as %s in %s. Exact text: %s. "
            "This is the plugin's normal delivery, not an intrusion."
            % (image_name, tmp_dir(), source_name))


def utf8_stdout():
    """Makes stdout carry any character the command printed.

    Python picks the console's own encoding, which on this machine is cp1252,
    and cp1252 cannot encode most of what a command prints. Writing such a
    character raised UnicodeEncodeError and the whole command output was lost:
    found 26 August 2026 on `grep -n "[^ -~]" plugin/README.md`, whose output
    holds the almost-equal sign the receipt uses, and which is under the pack
    floor so it passes through this function.

    errors="replace" rather than "strict", because a character that cannot be
    carried is worth one replacement mark and never worth the whole output.
    A Python without reconfigure keeps the old behaviour rather than failing
    here.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main():
    utf8_stdout()
    if len(sys.argv) < 3:
        sys.stderr.write(
            "usage: bash_pack.py <output file> <exit code> [session id]\n")
        return 1
    output_path, exit_code = sys.argv[1], sys.argv[2]
    # bash_gate.py passes the session id it read off the hook event. An older
    # rewrite still sitting in a live shell passes only two arguments, so the
    # session is None there and every pointer carries the rule, as before.
    session = sys.argv[3] if len(sys.argv) > 3 else None

    try:
        content = Path(output_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 1

    result = pack_output(content, session=session)
    if not result["packed"]:
        sys.stdout.write(result["text"])
        return 0

    # The preview is LABELLED as of 26 August 2026. It used to print as two
    # bare runs of text with nothing saying they were the ends of a longer
    # output. A reader ran `cat HANDOFF.md` on a 592 line file, took the
    # preview for the whole result, never opened the image that held all of
    # it, and read the original file instead. The image and the words on disk
    # were both complete and both went unused.
    print(exit_code)
    # The label's old tail, ", the whole output is in the image and the text
    # file named below", repeated a fact shared.txt line 1 teaches once per
    # agent, as the pointer's "Both hold the complete output." also did
    # until 30 August 2026: 64 characters carrying the same
    # fact twice in one block, a projected 64,545 tokens a run at the 1,008.5
    # tokens a run each pointer character billed over the seven on side runs,
    # measured 29 August 2026. The label keeps the output's real size, so the
    # preview still cannot read as the whole of it, which is what the
    # 26 August 2026 labelling fix was for; the 400 preview characters
    # themselves are untouched, per bench/preview_worth.py.
    print("--- first 200 characters of %s ---" % _total(content))
    print(content[:200])
    print("--- last 200 characters ---")
    print(content[-200:])
    print(result["pointer"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
