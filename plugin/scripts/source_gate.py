"""Stops the lead reading a packed report's text instead of its image.

HOW THIS FILE FITS, in plain words: the plugin draws an agent's report as a
small picture and hands the lead a note saying where the picture is. The words
are still on disk next to it. Nothing stopped the lead opening those words with
cat or sed, and when it did the plugin's saving was spent for nothing. This
script blocks that one thing and names the picture to open instead.

WHY IT EXISTS, measured in one session. Fourteen Bash
commands opened packed report text with cat, sed, grep and wc. They put 48,298
characters into the lead's prefix, about 20,064 tokens at the measured 2.41
characters per token for report prose. Drawing those same reports as images
had saved 20,014 tokens in that session. The leak cancelled the whole saving
and left the session 50 tokens worse off than never drawing them at all.

WHAT IT BLOCKS. A Bash command naming densepack-report-<id>.txt,
densepack-src-<id>.txt, densepack-bashsrc-<id>.txt or
densepack-briefsrc-<stamp>.txt when the image for that id exists beside it:
densepack-img-<id>-1.png for an agent's report, densepack-bash-<id>-1.png for
a packed command output, or densepack-brief-<stamp>-1.png for a packed brief.
The image holds the same words.

WHAT IT LETS THROUGH.

  Packing turned off with /dense-off. Nothing was drawn, so the text is
  the only copy.
  No image on disk for that id. The report was never packed, or was refused
  for costing more as a picture.
  A command carrying the word DENSEPACK_SOURCE_OK. Checking the packer against
  its own source is real work. The word is deliberate rather than a flag, so
  it cannot be typed by accident.
  Anything that names the file without reading it, such as ls or a path in an
  argument to the packer itself.

images_for() below resolves every candidate name through
common.sibling_image(), the single place that pairs a source file with its
image, so this gate names the same image common.py names and keeps no
private copy that a new source name can miss.
"""

import hashlib
import re
import shlex
import sys
import time

from common import disabled, emit, read_event, sibling_image, tmp_dir
from subagent_stop import manifest_write

# The basename of any source-text sidecar this plugin writes: densepack-,
# then a lowercase word naming which packer wrote it (report, src, bashsrc,
# briefsrc, or any later one), then a dash, an id or stamp, and .txt. This
# only recognizes the SHAPE of a name; whether a name found this way is
# really one of the plugin's own source files, and which image sits beside
# it, is decided in exactly one place, common.sibling_image(), never here.
FILENAME = re.compile(r"densepack-[a-z]+-[A-Za-z0-9-]+\.txt")

# Commands that read a file's contents. A command that only names the path,
# such as ls or rm, moves no words into the prefix and is left alone.
READERS = ("cat", "head", "tail", "sed", "grep", "awk", "less", "more",
           "type", "wc", "sort", "uniq", "cut", "nl", "strings", "od",
           "Get-Content", "Select-String")

OVERRIDE = "DENSEPACK_SOURCE_OK"

# The two halves of what this gate says. ACTION is what the caller must do and
# rides on every fire. WHY is the reason it was stopped, identical every time,
# and rides on the first fire of a session only, so fixed prose is said
# once rather than re-sent on every fire.
ACTION = (
    "DensePack replaced this command. Read this with the Read tool instead: "
    "%s . To read the words themselves, put DENSEPACK_SOURCE_OK in the "
    "command and run it again. This is the plugin's normal delivery, not an "
    "intrusion."
)

WHY = (
    " It read the words of a report already drawn as an image, and reading "
    "them costs what the image saved: measured 25 August 2026, fourteen such "
    "commands in one session put 48,298 characters back into the prefix and "
    "cancelled the whole session's saving. Read every image you have waiting "
    "in ONE turn, because each Read call is a turn and a turn re-reads the "
    "whole conversation."
)

# Kept so a caller that imports MESSAGE still gets the whole thing.
MESSAGE = ACTION + WHY


def why_already_sent(session):
    """True when this session has already been told why the gate fires.

    A marker file, the same mechanism pointer.py and bash_pack.py use, because
    every hook run is a fresh process. A session that cannot be identified is
    told every time, which is the safe failure: a repeated reason costs
    characters, a missing one leaves a reader that does not know what happened.
    """
    if not session:
        return False
    marker = tmp_dir() / ("densepack-sourcewhy-%s" % str(session)[:16])
    if marker.exists():
        return True
    # Moved onto the name, so a link planted at it takes no write.
    from common import write_text_atomic
    if not write_text_atomic(marker, "1"):
        return False
    return False


def images_for(command):
    """The packed image for every source-text file this command would read.

    Every densepack- named .txt file the command text mentions is looked
    up by common.sibling_image(), against the copy of a source file's own
    name, resolved inside this project's own tmp_dir() because every source
    file this plugin writes lives there and nowhere else, whatever path form
    the command used to name it. A name with no image on disk is left out,
    because there is nothing to read instead and blocking would leave the
    caller with no way to the words at all.
    """
    out = []
    for match in FILENAME.finditer(command):
        candidate = tmp_dir() / match.group(0)
        image = sibling_image(str(candidate))
        if image and image not in out:
            out.append(image)
    return out


# Every character a shell acts on. A file path holding one of these is shown
# with an underscore in its place rather than quoted, because quoting does
# not hold: Git Bash can expand a backtick inside single quotes.
META = set("`$\"'<>|&;()!*?[]{}~\n\r")


def _no_metacharacters(path):
    """A path the reader can still use, with nothing a shell would act on.

    The separators are turned to forward slashes first. Windows accepts a
    forward slash path everywhere, and the Read tool takes one, so the path
    stays usable while the backslash, which a shell treats as an escape,
    leaves. Anything else on META becomes an underscore; only a project
    folder deliberately named with one is affected, and the id in the file
    name is unchanged because SOURCE matches letters and digits only.
    """
    from common import no_metacharacters
    return no_metacharacters(path)


# ONE LINE, and only one. sed -n '92p' prints line 92 and nothing else, so it
# puts nothing back into the conversation and the image keeps its saving.
#
# The size is one because a reader with no way to fetch a single line pulls
# the whole exact-text file with the Read tool, answers worse than plain text
# and spends more tokens.
#
# A range stays blocked, whatever its span. sed -n '1,60p' on a report is the
# report, and head and tail skim rather than address, so neither is a way to
# reach one known line.
ONE_LINE = r"sed\s+-n\s+['\"]?\d+p"

# A RANGE. Freely on command output. On a report, src or briefsrc sidecar it
# is taught once and then let through.
#
# Command output is different from a REPORT, where the words exist only in
# that file and a range is the whole report. The thing a command printed is
# still on disk at its own path, so blocking a range does not keep anything
# out of the conversation. It only forces a bigger read of the original file.
#
# A reader can need many exact strings out of a report or a briefsrc sidecar,
# and a range denied on every call leaves it no allowed route at all.
# A range on a report, src or briefsrc sidecar is therefore denied once per session
# per file, with the same teaching any other blocked read gets, and a marker
# goes down; the repeat of a range on that same file passes straight through,
# because asking again after being told about the image is a real reason for
# the raw bytes, paid for knowingly.
RANGE = r"sed\s+-n\s+['\"]?\d+\s*,\s*\d+p"
BASHSRC = re.compile(r"densepack-bashsrc-[A-Za-z0-9]+\.txt")

# One marker per session and sidecar name: its presence means a range read of
# that file was already taught once this session, so the next one passes.
# Pruned with the other working files by bootstrap.py.
RANGE_MARKER = "densepack-rangeonce-%s-%s"


def range_marker(session, source_name):
    digest = hashlib.sha256(source_name.encode("utf-8")).hexdigest()[:12]
    return tmp_dir() / (RANGE_MARKER % (str(session or "")[:16], digest))


def bounded_read(command, session=None):
    """True when the command asks for named lines rather than the file.

    One line from anything, always. A range from command output, always. A
    range from a report, src or briefsrc sidecar the first time it is asked
    for in a session is not bounded, so the caller is denied and taught; the
    marker that denial leaves behind makes every later range on that same
    file bounded, so the repeat passes.
    """
    if re.search(ONE_LINE, command) is not None:
        return True
    if re.search(RANGE, command) is None:
        return False
    if BASHSRC.search(command) is not None:
        return True
    names = FILENAME.findall(command)
    if not names:
        return False
    if all(range_marker(session, name).exists() for name in names):
        return True
    # Moved onto the name, so a link planted at one takes no write.
    from common import write_text_atomic
    for name in names:
        write_text_atomic(range_marker(session, name), "1")
    return False


def reads_a_file(command, session=None):
    """True when the command runs something that prints a file's contents.

    Matched on a word boundary so that a path holding the letters cat, such as
    a folder named catalog, does not count as the cat command. A bounded read
    is not one of these: it prints the lines it names and nothing else.
    """
    if bounded_read(command, session):
        return False
    for name in READERS:
        if re.search(r"(^|[\s;|&(])%s([\s]|$)" % re.escape(name), command):
            return True
    return False


def record_bypass(command, session):
    """One row in densepack-manifest.jsonl, the running record of every pack
    and every skipped pack, for an override read of packed words.

    The override is legitimate work, so nothing here blocks or warns. But
    the row has to exist: the manifest's own charter, written above
    subagent_stop.manifest_write(), says a stat that only counts successes
    cannot prove the plugin is saving more than it costs, and without the
    row an override moves characters into the conversation with no record
    anywhere. The chars field
    holds the byte size of every sidecar the command names whose image
    exists, the words the override chose to read at full price.
    """
    try:
        if not reads_a_file(command, session):
            return
        total = 0
        names = []
        for match in FILENAME.finditer(command):
            candidate = tmp_dir() / match.group(0)
            if sibling_image(str(candidate)):
                try:
                    total += candidate.stat().st_size
                except OSError:
                    continue
                names.append(match.group(0))
        if not names:
            return
        manifest_write({
            "kind": "source_ok",
            "packed": False,
            "reason": "DENSEPACK_SOURCE_OK read the words beside a packed"
                      " image",
            "chars": total,
            "sources": names,
            "spawned_by": session or "",
            "ended": time.time(),
        })
    except Exception:  # noqa: BLE001
        return


def main():
    # NEVER CRASH A CALLER. This runs before every Bash command in the
    # session. A fault here must let the command through, not stop the work.
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        if (event.get("tool_name") or "") != "Bash":
            return 0
        command = str((event.get("tool_input") or {}).get("command") or "")
        if not command:
            return 0
        if OVERRIDE in command:
            record_bypass(command, event.get("session_id"))
            return 0
        if not reads_a_file(command, event.get("session_id")):
            return 0
        images = images_for(command)
        if not images:
            return 0
        # Rewritten, never refused. A refusal comes back as a tool result and
        # the lead has to answer it, so a refusal costs the same turn the
        # command would have cost. The command was going to take one turn
        # either way; replacing what it prints costs nothing extra and keeps
        # the words out of the prefix.
        #
        # updatedInput REPLACES the whole input object rather than merging
        # into it, so every field the event carried is sent back. A partial
        # object fails validation with "the required parameter is missing".
        # The path is stripped of shell metacharacters BEFORE it is quoted,
        # because quoting is not enough here: Git Bash can run a backtick
        # inside SINGLE quotes.
        #
        #   echo 'read this: proj`whoami`x .'   printed   read this: projrootx .
        #
        # A project folder's name is chosen by a person and is free to hold a
        # backtick, a dollar sign or a backslash, and every image path in this
        # message starts with that folder. json.dumps was worse still, because
        # it wraps in double quotes, which every shell expands. Taking the
        # characters out removes the question: a name holding one is shown
        # with an underscore in its place, and the file is still found by the
        # id, which SOURCE already restricts to letters and digits.
        replacement = dict(event.get("tool_input") or {})
        safe = " , ".join(_no_metacharacters(p) for p in images[:3])
        # The reason goes out on this session's first fire and on none after
        # it. The path and the override token go out every time, because they
        # are what the caller acts on.
        text = ACTION % safe
        if not why_already_sent(event.get("session_id")):
            text += WHY
        replacement["command"] = "echo %s" % shlex.quote(text)
        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": replacement,
            }
        })
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
