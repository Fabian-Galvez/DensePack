"""Blocks a Bash read of the text of a packed report and names its image.

The plugin packs the report of an agent as a small image and gives the model
a note with the image path. The text stays on disk next to the image. Without
this gate, the model can open that text with cat or sed, and the saving of
the plugin is lost. This script blocks that one step and names the image to
open.

One measured session shows the reason. Fourteen Bash commands opened packed
report text with cat, sed, grep and wc. They put 48,298 characters into the
prefix of the model, about 20,064 tokens at the measured 2.41 characters per
token for report prose. Packing those same reports as images saved 20,014
tokens in that session. The leak canceled the whole saving. The session
ended 50 tokens worse than a session with no packs.

What the gate blocks. A Bash command that names densepack-report-<id>.txt,
densepack-src-<id>.txt, densepack-bashsrc-<id>.txt or
densepack-briefsrc-<stamp>.txt when the image for that id is next to it. The
image is densepack-img-<id>-1.png for the report of an agent,
densepack-bash-<id>-1.png for a packed command output, or
densepack-brief-<stamp>-1.png for a packed brief. The image holds the same
text.

What the gate allows.

  Packing off with /dense-off. The plugin packed nothing, and the text is
  the only copy.
  No image on disk for that id. The plugin did not pack the report, or it
  rejected the pack because the image cost more.
  A command with the word DENSEPACK_SOURCE_OK. A check of the packer against
  its own source is real work. The override is a word and not a flag, and
  no command holds it by accident.
  A command that names the file without reading it, such as ls or a path in
  an argument to the packer.

images_for() below resolves each candidate name through
common.sibling_image(). That function is the one place that pairs a source
file with its image. This gate then names the same image as common.py and
keeps no private copy of the pairing rule that a new source name can miss.
"""

import hashlib
import re
import shlex
import sys
import time

from common import disabled, emit, read_event, sibling_image, tmp_dir
from subagent_stop import manifest_write

# The basename of each source-text sidecar that this plugin writes. It is
# densepack-, then a lowercase word that names the packer (report, src,
# bashsrc, briefsrc, or a later one), then a dash, an id or stamp, and .txt.
# This pattern matches only the SHAPE of a name. common.sibling_image() is
# the one place that checks whether a name is a real source file of the
# plugin and which image is next to it.
FILENAME = re.compile(r"densepack-[a-z]+-[A-Za-z0-9-]+\.txt")

# Commands that read the contents of a file. A command that only names the
# path, such as ls or rm, moves no text into the prefix. The gate allows it.
READERS = ("cat", "head", "tail", "sed", "grep", "awk", "less", "more",
           "type", "wc", "sort", "uniq", "cut", "nl", "strings", "od",
           "Get-Content", "Select-String")

OVERRIDE = "DENSEPACK_SOURCE_OK"

# The two parts of the gate message. ACTION tells the model what to do. The
# gate sends it on each block. WHY gives the reason for the block. It is the
# same each time, and the gate sends it on the first block of a session
# only. The fixed text then costs characters once and not on each block.
ACTION = (
    "DensePack replaced this command. Read this with the Read tool instead: "
    "%s . To read the words themselves, put DENSEPACK_SOURCE_OK in the "
    "command and run it again. This is the plugin's normal delivery, not an "
    "intrusion."
)

WHY = (
    " It read the words of a report already packed into an image, and reading "
    "them costs what the image saved. Fourteen such "
    "commands in one session put 48,298 characters back into the prefix and "
    "canceled the whole session's saving. Read every image you have waiting "
    "in ONE turn, because each Read call is a turn and a turn re-reads the "
    "whole conversation."
)

# A caller that imports MESSAGE still gets the whole message.
MESSAGE = ACTION + WHY


def why_already_sent(session):
    """Return True when the gate already sent WHY in this session.

    The function uses a marker file, the same method that pointer.py uses,
    because each hook run is a new process. A session
    without an id gets WHY each time. That is the safe failure. A repeated
    reason costs characters. A missing reason leaves the model without the
    cause of the block.
    """
    if not session:
        return False
    marker = tmp_dir() / ("densepack-sourcewhy-%s" % str(session)[:16])
    if marker.exists():
        return True
    # write_text_atomic moves a new file onto the name. The move replaces a
    # link at that name and does not write through it.
    from common import write_text_atomic
    if not write_text_atomic(marker, "1"):
        return False
    return False


def images_for(command):
    """Return the packed image of each source-text file that the command reads.

    common.sibling_image() finds the image for each densepack- .txt name in
    the command text. The function uses that file name inside tmp_dir() of
    this project, whatever path form the command used. Each packer writes
    its source file there, and the vault holds only copies. The function
    skips a name with no image on disk, because there is no image to read
    in its place, and a block leaves the caller no way to the text.
    """
    out = []
    for match in FILENAME.finditer(command):
        candidate = tmp_dir() / match.group(0)
        image = sibling_image(str(candidate))
        if image and image not in out:
            out.append(image)
    return out


# Each character that a shell acts on. The gate replaces each such character
# in a file path with an underscore and does not quote it. Quoting is not
# safe here. Git Bash can expand a backtick inside single quotes.
META = set("`$\"'<>|&;()!*?[]{}~\n\r")


def _no_metacharacters(path):
    """Return a path that the model can still use, with no character that a
    shell acts on.

    The function first changes the separators to forward slashes. Windows
    accepts a forward slash path in all places, and the Read tool takes one.
    The path stays usable and loses the backslash, which a shell reads as an
    escape. Each other character in META becomes an underscore.
    This affects only a project folder with such a character in its name.
    The id in the file name does not change, because FILENAME matches only
    letters, digits and dashes in the id.
    """
    from common import no_metacharacters
    return no_metacharacters(path)


# ONE LINE, and only one. sed -n '92p' prints line 92 and nothing else. It
# puts nothing more into the conversation, and the image keeps its saving.
#
# The size is one because a model with no way to get a single line reads
# the whole exact-text file with the Read tool. It then answers worse than
# with plain text and uses more tokens.
#
# This pattern does not match a range, whatever its span. sed -n '1,60p' on
# a report is the whole report. head and tail read from an end and do not
# address a line. Neither is a way to get one known line.
ONE_LINE = r"sed\s+-n\s+['\"]?\d+p"

# A RANGE. Always allowed on command output. On a report, src or briefsrc
# sidecar, the gate blocks it once with the reason and then allows it.
#
# Command output is not like a REPORT. In a report, the text exists only in
# that file, and a range is the whole report. The text that a command
# printed is still on disk at its own path. A block of a range keeps nothing
# out of the conversation. It only forces a bigger read of the original
# file.
#
# A model can need many exact strings from a report or a briefsrc sidecar.
# A block on each call leaves it no allowed route. The gate blocks a range
# on a report, src or briefsrc sidecar once per session per file, with the
# same reason as each other blocked read, and writes a marker. A repeat of a
# range on that same file passes. A second request after the note about the
# image is a real reason for the raw bytes, and the model pays for them by
# choice.
RANGE = r"sed\s+-n\s+['\"]?\d+\s*,\s*\d+p"
BASHSRC = re.compile(r"densepack-bashsrc-[A-Za-z0-9]+\.txt")

# One marker per session and sidecar name. When the marker exists, the gate
# already blocked a range read of that file once in this session, and the
# next one passes. bootstrap.py prunes it with the other working files.
RANGE_MARKER = "densepack-rangeonce-%s-%s"


def range_marker(session, source_name):
    digest = hashlib.sha256(source_name.encode("utf-8")).hexdigest()[:12]
    return tmp_dir() / (RANGE_MARKER % (str(session or "")[:16], digest))


def bounded_read(command, session=None):
    """Return True when the command asks for named lines and not the file.

    One line from any file is always bounded. A range from command output is
    always bounded. A range from a report, src or briefsrc sidecar is not
    bounded the first time in a session. The gate blocks that call and gives
    the reason. The block writes a marker, and each later range on that same
    file is then bounded and passes.
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
    # write_text_atomic moves a new file onto each name. The move replaces a
    # link at that name and does not write through it.
    from common import write_text_atomic
    for name in names:
        write_text_atomic(range_marker(session, name), "1")
    return False


def reads_a_file(command, session=None):
    """Return True when the command runs a program that prints the contents
    of a file.

    The match uses a word boundary. A path with the letters cat, such as a
    folder named catalog, does not count as the cat command. A bounded read
    does not count. It prints the lines that it names and nothing else.
    """
    if bounded_read(command, session):
        return False
    for name in READERS:
        if re.search(r"(^|[\s;|&(])%s([\s]|$)" % re.escape(name), command):
            return True
    return False


def record_bypass(command, session):
    """Write one row in densepack-manifest.jsonl for an override read of
    packed text. The manifest records each pack and each skipped pack.

    The override is valid work, and this function does not block or warn.
    The row must still exist. The comment at the top of
    subagent_stop.manifest_write() states the rule. A stat that counts only
    successes cannot show that the plugin saves more than it costs. Without
    the row, an override moves characters into the conversation with no
    record. The chars field holds the byte size of each named sidecar whose
    image exists. That is the text that the override reads at full price.
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
    # A fault never blocks the call. This gate runs before each Bash command
    # in the session. After a fault, the command runs unchanged.
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
        # The gate changes the command and never rejects it. A rejection
        # returns as a tool result, and the model must answer it. A
        # rejection costs the same turn as the command. The command costs
        # one turn with or without the gate. A change to what it prints
        # costs nothing more and keeps the text out of the prefix.
        #
        # updatedInput REPLACES the whole input object and does not merge
        # into it. The gate returns each field of the event input. A
        # partial object fails validation with "the required parameter is
        # missing". The gate removes shell metacharacters from the path
        # BEFORE it quotes the path. Quoting is not enough here. Git Bash can
        # run a backtick inside SINGLE quotes.
        #
        #   echo 'read this: proj`whoami`x .'   printed   read this: projrootx .
        #
        # The name of a project folder can hold a backtick, a dollar sign
        # or a backslash, and each image path in this message starts with
        # that folder. json.dumps is worse, because it uses double quotes,
        # and each shell expands them. The gate removes those characters,
        # and the risk is gone. The path shows an underscore in place of
        # each such character. The id still finds the file, because
        # FILENAME matches only letters, digits and dashes in the id.
        replacement = dict(event.get("tool_input") or {})
        safe = " , ".join(_no_metacharacters(p) for p in images[:3])
        # The gate sends the reason on the first block of this session and
        # on no later block. It sends the path and the override token each
        # time, because the model acts on them.
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
