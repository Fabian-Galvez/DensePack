"""Stops Grep or Glob handing back a source-text sidecar's words directly.

HOW THIS FILE FITS, in plain words: drop_read_gate.py and subread_gate.py
stop a Read of a source-text file with an image beside it, source_gate.py
stops a Bash command that prints one, and bash_pack.py packs whatever a Bash
reader prints. Nothing stood at the Grep or Glob tool at all: the hook list
for both, in plugin/hooks/hooks.json, ran delegate_gate.py only, which counts
a LEAD's hands-on calls and never even fires for a subagent. A subagent that
ran Grep straight against a densepack-briefsrc-<stamp>.txt file, the words
behind its own packed brief, got the whole file back as matched lines, at
full price, with no hook in the way. FIXED 29 August 2026, found by testing
this exact call: source_gate.py and bash_gate.py both answered null to it,
because neither one is on Grep's or Glob's own hook list.

WHAT IT BLOCKS. A Grep or Glob call whose own `path` argument names, or is a
folder holding, a densepack- source-text file that has a sibling image on
disk. Every such file this plugin writes lives in one folder, the project's
own .claude/tmp, and nowhere else, so this only fires when `path` resolves
inside .claude/tmp or .claude/densepack-vault. An ordinary Grep of the repo
never reaches there: .claude/tmp is a line in .gitignore, and the Grep tool
here is ripgrep underneath, which does not walk a gitignored folder unless a
caller names it directly. Naming it directly is the one shape this file
exists to catch.

WHY A DENY, NOT A REWRITE. A Read or a Bash command names one file, so the
gate can swap that one path or that one line for the image's own path and
the call still runs. Grep and Glob take a pattern, not a single destination,
so there is nothing in the call to rewrite to a picture. The call is denied
instead, naming the image to Read, the same shape drop_read_gate.py's own
fallback and subread_gate.py already use when an automatic redirect is not
possible.

WHAT IT LETS THROUGH. Packing turned off with /densepack-off, the same
escape every gate here shares. A path outside .claude/tmp and
.claude/densepack-vault, which is every ordinary Grep or Glob in this
project. A path inside either folder that names no source-text file with an
image beside it: the plugin's own bookkeeping (settings, manifest, legend
sidecar, markers) and any file whose image was refused or never drawn, which
has nothing to redirect to.

NEVER CRASH A CALLER. One try around everything; any fault allows the call,
the same failure mode every gate in this folder chooses.

FIXED 30 August 2026, measured in the INDEX benchmark's pair 1 ON run. A
lead globbed .claude/tmp for its own packed image, pattern
densepack-img-<id>*.png, a call that reads no words at all. This gate
denied it anyway, and the denial named every image in the folder: 574
paths, 43,707 characters into the lead's context, about 18,200 tokens at the
measured 2.40 characters each, more than any leak this gate has ever
stopped. Two
changes close it. The gate now applies the call's own name pattern, Glob's
pattern or Grep's glob filter, so a call whose pattern cannot match a
source-text file passes. And a denial now names at most LISTED images,
newest first, with the count and a pointer to
densepack-manifest.jsonl, the running record of every pack this plugin
writes, one JSON row per image, for the rest. The message can never again
scale with the folder.
"""

import fnmatch
import os
import sys
from pathlib import Path

from common import disabled, emit, project_dir, read_event, sibling_image, \
    tmp_dir, vault_dir

MESSAGE = (
    "DensePack: this path holds a source-text file already drawn as an "
    "image. Read the image instead: %s . The words are the same; the "
    "image is what the plugin already paid to draw. File: %s"
)

# The most images one denial ever names. The manifest rows of 30 August 2026
# show no batch writing more than two images, so five names every image a
# caller could be mid-conversation about; the 574-path denial above is what
# no bound at all produces.
LISTED = 5

MESSAGE_MANY = (
    "DensePack: this folder holds %d source-text files already drawn as "
    "images, too many to name here. The newest %d images: %s . Every source "
    "and image pair is a row in densepack-manifest.jsonl in this folder. "
    "File: %s"
)


def scratch_roots():
    """The only two folders a source-text file with a sibling image ever
    sits in: this project's own .claude/tmp and .claude/densepack-vault."""
    return (tmp_dir(), vault_dir())


def _resolved(path):
    """`path` as an absolute Path, resolved against the project root when it
    is not already absolute. A path that cannot be resolved returns None
    rather than raising, so a caller here always gets a clean answer."""
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = project_dir() / candidate
        return candidate.resolve()
    except OSError:
        return None


def under_scratch(resolved):
    """True when `resolved` is one of scratch_roots() or sits inside one."""
    for root in scratch_roots():
        try:
            root = root.resolve()
        except OSError:
            continue
        if resolved == root or root in resolved.parents:
            return True
    return False


def _name_matches(child, base, pattern):
    """True when `pattern`, a Glob pattern or a Grep glob filter, could hand
    back `child`. No pattern means every name matches. The name is tried
    bare, as the path relative to `base`, and against the pattern's last
    path piece, because Glob accepts all three shapes and a miss here must
    fail toward denying, never toward leaking."""
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
    """Every (source path, image path) pair `resolved` names or holds.

    `resolved` a file: itself, when it is a source-text file with a sibling
    image. `resolved` a folder: every file inside it, at any depth, that is
    one. .claude/tmp holds every source file flat, one folder, no nesting,
    but .claude/densepack-vault keeps one subfolder per conversation, so a
    Grep or a Glob aimed at the vault's own top folder still has to walk
    down into each one to find them. Only a file the call's own `pattern`
    could hand back counts: a Glob for the packed images alone reads no
    words, and stopping it stopped the exact thing the plugin asks a lead
    to do.
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


def main():
    # NEVER CRASH A CALLER. This runs before every Grep and every Glob.
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        tool = event.get("tool_name") or ""
        if tool not in ("Grep", "Glob"):
            return 0
        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        path = tool_input.get("path")
        if not isinstance(path, str) or not path:
            return 0

        resolved = _resolved(path)
        if resolved is None:
            return 0
        if not under_scratch(resolved):
            return 0

        # Glob names files by its pattern; Grep can carry a glob filter. A
        # file the call could never hand back is not this gate's business.
        pattern = tool_input.get("pattern") if tool == "Glob" \
            else tool_input.get("glob")
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
