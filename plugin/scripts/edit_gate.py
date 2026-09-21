"""Hands an Edit the exact line when its own text would not match.

HOW THIS FILE FITS, in plain words: a reader finds a file by reading
DensePack's images. An image draws every character, and it cannot draw a
trailing space. A reader that copies a line out of an image and sends it as
Edit's old_string can lose that space, and Edit refuses the call. The reader
then spends a turn asking what the line really says.

This gate spends that turn for it, before the Edit runs. It counts the
reader's own old_string in the file. One match and the call goes straight
through, which is every call that was already correct. No match, and the
denial carries the file's own line, character for character, in quotes that
show a space, a tab and a no-break space. The reader sends the Edit again
with that text and it matches.

WHAT IT BLOCKS. An Edit whose old_string is in the named file no times, and
an Edit whose old_string is there more than once without replace_all. Both
are calls Edit itself refuses. The gate refuses them one step earlier and
says what the file holds.

WHAT IT LETS THROUGH. Every Edit that would have worked. A missing file, an
unreadable file and an empty old_string all pass, because the answer belongs
to Edit and not to this gate. Packing stays off with /dense-off, the same
escape every gate here shares.

WHY A DENY, NOT A REWRITE. A rewrite would put words in the reader's mouth.
The reader asked to change one exact piece of text, and a gate that quietly
edited that text could change a line the reader never looked at. The denial
names the line and lets the reader decide.

NEVER CRASH A CALLER. One try around everything. Any fault allows the call,
the same failure mode every gate in this folder chooses.
"""

import difflib
import io
import os
import sys

from common import disabled, emit, read_event

# How many near lines a denial names. Three is enough to recognise the right
# one and short enough that the message never grows into a file listing.
CANDIDATES = 3

# How many lines of the file a denial quotes when the first line matched and
# a later one did not. The reader needs the whole block to see which line
# drifted, and a block longer than this is a sign the reader wants a Read.
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
    """The line as Python text, which draws a space and a tab you can see."""
    shown = repr(text)
    if shown.startswith("u"):
        shown = shown[1:]
    return shown


def lines_of(path):
    """The file's lines without their endings, or None when it cannot open."""
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
    """Every line number, counting from one, whose line equals `first`."""
    return [number for number, line in enumerate(lines, 1) if line == first]


def copy_lines(whole, old):
    """The line number each copy of `old` starts on, counting from one.

    Counted from the character offset rather than from whole lines, because
    a reader's text often starts in the middle of a line.
    """
    numbers, at = [], whole.find(old)
    while at != -1 and len(numbers) <= CANDIDATES:
        numbers.append(whole.count("\n", 0, at) + 1)
        at = whole.find(old, at + 1)
    return numbers


def row(lines, number):
    return "%6d  %s" % (number, quote(lines[number - 1]))


def block_from(lines, start, count):
    """`count` lines from `start`, each with its number and its exact text."""
    last = min(start + min(count, BLOCK), len(lines) + 1)
    return "\n".join(row(lines, number) for number in range(start, last))


def near_numbers(lines, first):
    """The line numbers of the closest lines to `first`, best first."""
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
    """The words a denial carries when old_string is not in the file."""
    shown = os.path.basename(path)
    wanted = old.splitlines() or [old]

    # Where the reader's first line sits, or where it nearly sits.
    starts = match_lines(lines, wanted[0]) or near_numbers(lines, wanted[0])
    if not starts:
        return NO_MATCH % shown

    # One place to look. Quote the whole block the reader asked for, because
    # the drift is inside it and the reader needs every line to send again.
    if len(starts) == 1:
        return NOT_FOUND % (shown, block_from(lines, starts[0], max(len(wanted), 1)))

    # Several places. Name each one by its first line and let the reader pick.
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
