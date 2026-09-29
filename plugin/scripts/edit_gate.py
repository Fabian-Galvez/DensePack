"""Gives an Edit the exact file line when its old_string does not match.

The model reads a file from DensePack images. An image shows each character,
but it cannot show a trailing space. When the model copies a line from an
image and sends it as the old_string of an Edit, the model can lose that
space. Edit then rejects the call, and the model uses a turn to find the
exact text of the line.

This gate does that step before the Edit runs. It counts the old_string in
the file. With one match, the call runs unchanged, as each correct call
does. With no match, the denial holds the line from the file, character for
character, in quotes that show a space, a tab and a no-break space. The
model sends the Edit again with that text, and the text matches.

What the gate blocks. The gate blocks an Edit whose old_string is not in the
named file, and an Edit whose old_string is in the file more than once
without replace_all. Edit rejects the two kinds of call, and the gate
rejects them one step earlier and shows what the file contains.

What the gate allows. The gate allows each Edit that can work. A missing
file, an unreadable file and an empty old_string all pass, because Edit
gives the answer for them. /dense-off stops this gate and each other gate
here.

Why a denial and not a rewrite. The model asked to change one exact piece of
text. A gate that changes that text itself can change a line that the model
did not read. The denial names the line, and the model chooses the next step.

A fault never blocks the call. One try covers all of main(), and a fault
allows the call. Each other gate in this folder does the same.
"""

import difflib
import io
import os
import sys

from common import disabled, emit, read_event

# The number of near lines that a denial names. Three is enough to find the
# right line. The message stays short and does not become a file listing.
CANDIDATES = 3

# The number of file lines that a denial quotes when the first line matched
# and a later line did not. The model needs the whole block to find the line
# that differs. A block longer than this needs a Read.
BLOCK = 12

NOT_FOUND = ("DensePack: that text is not in %s. The file contains this, "
             "character for character:\n%s\nSend the Edit again with the "
             "text above. The quotes show every space and tab.")

NO_MATCH = ("DensePack: that text is not in %s, and no line there is close "
            "to it. Read the file to see what it contains now.")

MANY = ("DensePack: that text is in %s %d times. Each copy starts on one of "
        "these lines:\n%s\nSend more of one line to name it, or set "
        "replace_all.")


def quote(text):
    """Return the line as Python text that shows each space and tab."""
    shown = repr(text)
    if shown.startswith("u"):
        shown = shown[1:]
    return shown


def lines_of(path):
    """Return the lines without line endings, or None when the read fails."""
    try:
        with io.open(path, encoding="utf-8", newline="") as handle:
            return handle.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def text_of(path):
    try:
        with io.open(path, encoding="utf-8", newline="") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def match_lines(lines, first):
    """Return each line number, counting from one, whose line equals `first`."""
    return [number for number, line in enumerate(lines, 1) if line == first]


def copy_lines(whole, old):
    """Return the line number where each copy of `old` starts, from one.

    The count uses the character offset and not whole lines, because the
    text from the model often starts in the middle of a line.
    """
    numbers, at = [], whole.find(old)
    while at != -1 and len(numbers) <= CANDIDATES:
        numbers.append(whole.count("\n", 0, at) + 1)
        at = whole.find(old, at + 1)
    return numbers


def row(lines, number):
    return "%6d  %s" % (number, quote(lines[number - 1]))


def block_from(lines, start, count):
    """Return `count` lines from `start`, each with its number and exact text."""
    last = min(start + min(count, BLOCK), len(lines) + 1)
    return "\n".join(row(lines, number) for number in range(start, last))


def near_numbers(lines, first):
    """Return the numbers of the lines closest to `first`, closest first."""
    close = difflib.get_close_matches(first, lines, n=CANDIDATES, cutoff=0.6)
    numbers, used = [], set()
    for line in close:
        for number, candidate in enumerate(lines, 1):
            if candidate == line and number not in used:
                numbers.append(number)
                used.add(number)
                break
    return numbers


def report(path, lines, old):
    """Return the denial text for an old_string that is not in the file."""
    shown = os.path.basename(path)
    wanted = old.splitlines() or [old]

    # Find the first line of the model's text, or the lines closest to it.
    starts = match_lines(lines, wanted[0]) or near_numbers(lines, wanted[0])
    if not starts:
        return NO_MATCH % shown

    # One match. Quote the whole block that the model sent. The difference
    # is inside it, and the model needs each line to send the Edit again.
    if len(starts) == 1:
        return NOT_FOUND % (shown, block_from(lines, starts[0], max(len(wanted), 1)))

    # Several matches. Name each one by its first line. The model chooses one.
    rows = "\n".join(row(lines, number) for number in starts[:CANDIDATES])
    return NOT_FOUND % (shown, rows)


def main():
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        if (event.get("tool_name") or "") != "Edit":
            return 0

        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0

        path = tool_input.get("file_path")
        old = tool_input.get("old_string")
        if not isinstance(path, str) or not isinstance(old, str) or not old:
            return 0
        if not os.path.isfile(path):
            return 0

        whole = text_of(path)
        if whole is None:
            return 0
        # Claude Code's Edit matches a file with CRLF line ends as if they
        # were LF, and the model sends old_string with LF. Without the same
        # step, the gate denied every multi-line Edit on a CRLF file that Edit
        # then made.
        whole = whole.replace("\r\n", "\n")
        old = old.replace("\r\n", "\n")

        found = whole.count(old)
        if found == 1:
            return 0
        if found > 1 and tool_input.get("replace_all"):
            return 0

        lines = lines_of(path)
        if lines is None:
            return 0

        if found > 1:
            at = copy_lines(whole, old)
            shown = "\n".join(row(lines, number) for number in at[:CANDIDATES])
            reason = MANY % (os.path.basename(path), found, shown)
        else:
            reason = report(path, lines, old)

        emit({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                     "permissionDecision": "deny",
                                     "permissionDecisionReason": reason}})
        return 0
    except Exception:  # noqa: BLE001
        return 0


if __name__ == "__main__":
    sys.exit(main())
