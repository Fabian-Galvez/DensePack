"""Print the transcript file of the chat that is running this command.

    python bench/own_transcript.py quick_test_on.md

A chat cannot see its own session id, and the counting step used
`ls -t ... | head -1` instead. That returns the newest transcript in the
project folder, which is another chat whenever more than one is open. On
31 August 2026 it put the test 2 chat's bill into test 1's row.

This script matches on the first user message instead. Every quick test chat
opens with a prompt that names its own test file, and no other chat's first
message does, so the match is the chat itself. The newest match wins when the
same test ran more than once.

The exit code is 1 and nothing prints when no transcript matches, so a caller
that pipes the name into another command fails loudly rather than counting the
wrong chat.
"""
import glob
import json
import os
import sys

# Every project folder, not one written down. Claude Code names a folder
# after the directory the CLI was started in, so a chat opened in this repo
# and a leg bench/run_leg.py launches with cwd=REPO land in different
# folders.
#
# MEASURED 31 August 2026: this was the single folder
# one launch folder's name while the leg wrote to
# another launch folder's name. Asked for the leg naming
# quick_test_on.md it answered with the lead session that only mentions the
# file, and the number taken from it would have been the wrong chat's.
PROJECTS = os.path.expanduser("~/.claude/projects")
HERE = os.path.dirname(os.path.abspath(__file__))


def first_user_text(path):
    """The text of the first real user message, or an empty string."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("isSidechain"):
                continue
            message = row.get("message") or {}
            if not isinstance(message, dict):
                continue
            if message.get("role") != "user":
                continue
            content = message.get("content")
            parts = []
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
            text = "\n".join(parts).strip()
            if text:
                return text
    return ""


def needles_for(argument):
    """The texts to look for at the head of a transcript, strictest first.

    A leg file's name never appears in the chat that ran it: run_leg.py sends
    the prompt block, not the file name, so the only chat holding the words
    "quick_test_on.md" is the one that talked ABOUT the leg. When the argument
    names a leg file, its own prompt block is the needle. Anything else is used
    as typed, which is how a person naming a phrase still works.

    The needle is the whole block, never a line of it. Sibling legs share their
    opening sentence: quick_test_on.md, quick_test_on_sonnet.md and
    quick_test_on_haiku.md differ only in the reader model, so a first-line
    needle answered with whichever of the three chats was newest. A leg that
    has not run yet returns nothing and the caller fails, which is the point:
    counting the wrong chat is the fault this script exists to stop.
    """
    for candidate in (argument, os.path.join(HERE, argument)):
        if not os.path.isfile(candidate):
            continue
        text = open(candidate, encoding="utf-8", errors="replace").read()
        mark = "\n---\n"
        start = text.find(mark)
        if start < 0:
            break
        start += len(mark)
        end = text.find(mark, start)
        if end < 0:
            break
        prompt = text[start:end].strip()
        if prompt:
            return [prompt]
        break
    return [argument]


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    heads = {}
    for path in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        heads[path] = first_user_text(path)
    found = []
    for needle in needles_for(argv[1]):
        found = [p for p, head in heads.items() if needle in head]
        if found:
            break
    if not found:
        sys.stderr.write("No transcript opens with a prompt naming %s\n"
                         % needle)
        return 1
    found.sort(key=os.path.getmtime)
    print(found[-1].replace(os.sep, "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
