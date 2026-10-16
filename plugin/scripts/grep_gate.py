"""Stops a Glob on a source-text sidecar, and puts the real spelling of
look-alike letters into a Grep.

For a Read of a source-text file with an image next to it, read_image.py
returns the image after the Read runs. source_gate.py stops a Bash command
that prints such a file, and bash_image.py returns Bash output as an image.
This file checks the Glob tool. hooks.json sends it Glob and Grep calls.

LOOK-ALIKE LETTERS IN A GREP. Some Cyrillic and Greek letters, such as the
Е and Р of ЕР-0042, look like Latin letters in an image, so a model searches
for EP-0042 and finds nothing. When DensePack draws Read or Bash text, it
saves such words in .claude/tmp/look-alikes.json under their Latin twin.
Greps whose pattern holds a saved twin then match both spellings, such as
[EЕ][PР]-0042, so the Latin twin in other files still matches. Claude Code
2.1.300 has no Grep tool, so source_gate.py sends grep, rg and Select-String
commands here as well. Fixed-string searches, such as grep -F, stay as they
are, because they read brackets as text. In auto and bypass modes the call changes before
it runs. Other modes get one denial that gives the pattern, and the same
search sent again runs unchanged.

EACH REAL GREP PASSES. Each image that DensePack makes has its literal text
on disk, and the model gets the path in two places, which are the file= name in the key
row of the image and the pointer next to a brief or a report. When the task needs an exact string
that the image cannot give, one Grep call on that text copy or source text
must work. This gate never denies a Grep with a real pattern, even one
whose `path` names a sidecar with a sibling image. The pointer next to a brief
tells the model to Grep the text only for an exact string that the image cannot give. The wording, not this gate, keeps the
model on the image.

NO MATCH-ALL GREP IS DENIED. A match-all Grep such as "^" with a head_limit is how
an agent reads the first lines of a file with text. The gate denied it
before, when the limit was over 20 lines. In an Opus 5.5 eval run of the
architecture-doc bench, that made 7 denied Greps and 7 Reads in their
place, so each file head took 2 calls in place of 1. Grep output is capped
by Claude Code, and the agent makes the same calls as with text.

WHAT IT BLOCKS. A Glob call whose `path` argument names a densepack-
source-text file that has a sibling image on disk, or a folder that holds
one. Each such file that this plugin writes is in .claude/tmp or
.claude/densepack-vault of the project, and the gate blocks only when
`path` resolves inside one of the two. An ordinary Glob of the repo never
goes there. The denial names the image and the source file, and the model
still gets the location of the text.

WHY A DENY, NOT A REWRITE. A Bash command names one file. source_gate.py
can replace that one line with the image path, and the call still runs.
Glob takes a pattern, not a single destination. The call has nothing to
change to an image. The gate denies the call and names the image to Read.

WHAT IT ALLOWS. The gate allows each Grep, and each call after /dense-off stops packing, the same as each other gate here. It
allows a path outside .claude/tmp and .claude/densepack-vault, which covers
each ordinary Glob of a project. It also allows a path inside either folder
that names no source-text file with an image next to it. That covers the
plugin bookkeeping (settings, manifest, legend sidecar, markers) and each
file whose image the plugin rejected or never packed, which has no image to
name.

A FAULT NEVER BLOCKS THE CALL. One try covers all of main(), and a fault
allows the call. Each other gate in this folder does the same.

A GLOB FOR IMAGES PASSES. A lead can glob .claude/tmp for its own packed
image, with the pattern densepack-img-<id>*.png, a call that reads no text.
The gate applies the name pattern of the call. A call whose pattern cannot
match a source-text file passes. A denial names at most LISTED images,
newest first, with the count and a pointer to densepack-manifest.jsonl for
the rest. That file is the running record of the packs of this plugin, one
JSON row for each. The message size does not grow with the folder.
"""

import fnmatch
import json
import os
import re
import sys
from pathlib import Path

from common import disabled, emit, project_dir, read_event, sibling_image, \
    may_rewrite, tmp_dir, vault_dir

MESSAGE = (
    "DensePack: this path holds a source-text file already packed into an "
    "image. Read the image instead: %s . The words are the same. The "
    "image is what the plugin already paid to pack. File: %s"
)

LOOK_ALIKE_MESSAGE = (
    "DensePack: an image you read showed this text with Cyrillic or Greek "
    "letters that look like Latin ones, so a search in Latin letters misses it. "
    "Search with this %s to match the text as it is: %s\n"
    "To search the Latin letters only, send the same %s again: %s")

# The most images that one denial names. Five covers the recent packs of a
# conversation. With no bound, a denial names each image in the folder, and
# the message grows with the folder.
LISTED = 5

MESSAGE_MANY = (
    "DensePack: this folder holds %d source-text files already packed into "
    "images, too many to name here. The newest %d images: %s . Every source "
    "and image pair is a row in densepack-manifest.jsonl in this folder. "
    "File: %s"
)


def scratch_roots():
    """Return the only two folders that can hold a source-text file with a
    sibling image, the .claude/tmp and .claude/densepack-vault of this
    project."""
    return (tmp_dir(), vault_dir())


def _resolved(path):
    """Return `path` as an absolute Path, resolved against the project root
    when it is not absolute. For a path that does not resolve, return None
    and do not raise. A caller here always gets a clean answer."""
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = project_dir() / candidate
        return candidate.resolve()
    except OSError:
        return None


def under_scratch(resolved):
    """Return True when `resolved` is one of scratch_roots() or inside one."""
    for root in scratch_roots():
        try:
            root = root.resolve()
        except OSError:
            continue
        if resolved == root or root in resolved.parents:
            return True
    return False


def _name_matches(child, base, pattern):
    """Return True when `pattern`, a Glob pattern, can return `child`.

    No pattern means that each name matches. The function tests the bare
    name, the path relative to `base`, and the last path piece of the
    pattern. Glob accepts all three shapes. A miss here must fail toward a
    denial, never toward a leak."""
    if not pattern:
        return True
    name = child.name
    try:
        rel = child.relative_to(base).as_posix()
    except ValueError:
        rel = name
    last = pattern.split("/")[-1] or "*"
    return (fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern)
            or fnmatch.fnmatch(name, last))


def leaking_files(resolved, pattern=None):
    """Return each (source path, image path) pair that `resolved` names or
    holds.

    For a file, the pair is the file itself, when it is a source-text file
    with a sibling image. For a folder, the pairs are each such file inside
    it, at any depth. .claude/tmp holds each source file flat, in one folder
    with no nesting. .claude/densepack-vault keeps one subfolder per
    conversation, and a Glob of the top vault folder must search each
    subfolder to find them. Only a file that the `pattern` of the call can
    return counts. A Glob for the packed images alone reads no text. A block
    of that Glob stops the exact step that the plugin asks a lead to do.
    """
    out = []
    try:
        if resolved.is_file():
            if not _name_matches(resolved, resolved.parent, pattern):
                return out
            image = sibling_image(str(resolved))
            if image:
                out.append((str(resolved), image))
            return out
        if resolved.is_dir():
            for child in resolved.rglob("*"):
                if not child.is_file():
                    continue
                if not _name_matches(child, resolved, pattern):
                    continue
                image = sibling_image(str(child))
                if image:
                    out.append((str(child), image))
    except OSError:
        return out
    return out


def both_spellings(twin, spellings):
    """Returns a pattern that matches the Latin twin and each saved spelling,
    such as [EЕ][PР]-0042, so a Latin EP-0042 in another file still matches.
    Grep, grep, rg and Select-String all read the brackets as one letter."""
    out = ""
    for i, ch in enumerate(twin):
        chars = sorted({ch} | {s[i] for s in spellings if len(s) == len(twin)})
        out += ch if len(chars) == 1 else "[%s]" % "".join(chars)
    return out


def look_alike_search(event, tool_input, field="pattern"):
    """Returns the hook output that puts the real spelling into a Grep pattern,
    or a Bash search command with field="command", that holds the Latin twin
    of a word that an image showed, or None."""
    pattern = tool_input.get(field)
    saved_path = tmp_dir() / "look-alikes.json"
    if not isinstance(pattern, str) or not saved_path.is_file():
        return None
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    new = pattern
    for twin, spellings in saved.items():
        if twin in new:
            real = both_spellings(twin, spellings)
            new = re.sub(r"(?<![\w-])%s(?![\w-])" % re.escape(twin), lambda m: real, new)
    if new == pattern:
        return None
    if may_rewrite(event):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "updatedInput": dict(tool_input, **{field: new})}}
    # Modes that ask get no changed call, see THE PERMISSION RULE in
    # common.py. The gate denies once, and the same search sent again runs.
    denied_path = tmp_dir() / "look-alikes-denied.json"
    denied = json.loads(denied_path.read_text(encoding="utf-8")) if denied_path.is_file() else []
    if pattern in denied:
        return None
    denied_path.write_text(json.dumps((denied + [pattern])[-50:], ensure_ascii=False), encoding="utf-8")
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": LOOK_ALIKE_MESSAGE % (field, new, field, pattern),
    }}


def main():
    # A fault never blocks the call. This gate runs before each Glob.
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        tool = event.get("tool_name") or ""
        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        if tool == "Grep":
            out = look_alike_search(event, tool_input)
            if out:
                emit(out)
            return 0
        if tool != "Glob":
            return 0
        path = tool_input.get("path")
        if not isinstance(path, str) or not path:
            return 0

        resolved = _resolved(path)
        if resolved is None:
            return 0
        if not under_scratch(resolved):
            return 0

        # Glob names files by its pattern. The gate ignores a file that the
        # call cannot return.
        pattern = tool_input.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            pattern = None
        found = leaking_files(resolved, pattern)
        if not found:
            return 0

        images = []
        for _source, image in found:
            if image not in images:
                images.append(image)
        try:
            images.sort(key=os.path.getmtime, reverse=True)
        except OSError:
            pass
        # The message names files for the model to open, and the code does
        # not clean the two paths, because a cleaned path names a file that
        # does not exist. A file name from the project then reaches the
        # model as it is.
        if len(images) <= LISTED:
            reason = MESSAGE % (" , ".join(images), found[0][0])
        else:
            reason = MESSAGE_MANY % (
                len(images), LISTED, " , ".join(images[:LISTED]),
                found[0][0])
        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        })
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
