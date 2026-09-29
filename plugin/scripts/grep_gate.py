"""Stops a Glob on a source-text sidecar, and a Grep that dumps a whole file
as text when a Read gives its image. Each other Grep passes.

For a Read of a source-text file with an image next to it, read_image.py
returns the image after the Read runs. source_gate.py stops a Bash command
that prints such a file, and bash_image.py returns Bash output as an image.
This file checks the Grep and Glob tools.

EACH REAL GREP PASSES. Each image that DensePack makes has its literal text
on disk, and the model gets the path in three places, which are the intro
at session start, the file= name in the key row of the image, and the
pointer next to a brief or a report. When the task needs an exact string
that the image cannot give, one Grep call on that text copy or source text
must work. This gate never denies a Grep with a real pattern, even one
whose `path` names a sidecar with a sibling image. The intro and the
pointers call Grep a last resort. The wording, not this gate, keeps the
model on the image.

WHAT IT DENIES ON GREP. A match-all dump. That is a Grep in content mode
whose pattern matches an empty line ("^", ".*", "$", "" and the like), with
no head_limit of LINE_PULL_MAX or fewer, on a file that a whole-file Read
packs, or on a folder that holds one. That call prints the whole file as
text and skips the image, which costs the most tokens of any way to see it.
drop_read_gate.draws_on_read() makes the decision, with the same checks as
a Read. A file that a Read keeps as text still greps. Such a file is small,
binary, a script that the font cannot render, a scratch or .claude file, or
a file for a model that gets text. A text copy is under .claude, and the one
last-resort way to its text stays open. A real pattern, the
files_with_matches and count modes, and a head_limit of LINE_PULL_MAX or
fewer, the same size as a Read line pull, all pass.

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
change to an image. The gate denies the call and names the image to Read,
the same shape as the deny-and-instruct fallback in drop_read_gate.py.

WHAT IT ALLOWS. The gate allows each Grep except a match-all dump, and each
call after /dense-off stops packing, the same as each other gate here. It
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
import os
import sys
from pathlib import Path

from common import LINE_PULL_MAX, disabled, emit, project_dir, quoted_path, \
    read_event, sibling_image, tmp_dir, vault_dir

# The deny for a match-all Grep dump. It is plain and short. It names the
# tool to call, what the call returns, and the one Grep that still works.
DUMP_MESSAGE = (
    "DensePack: Read %s with the Read tool. It returns an image of the "
    "whole file. Grep a real pattern when you need exact lines."
)
DUMP_MESSAGE_FOLDER = (
    "DensePack: Read the files in %s with the Read tool, such as %s. Each "
    "returns an image of the whole file. Grep a real pattern when you "
    "need exact lines."
)
# The gate denies a folder dump when the walk finds one file that a Read
# packs. The walk skips what ripgrep skips by default, hidden folders, plus
# the usual build and package folders. It stops after WALK_MAX files. A huge
# tree with nothing to pack near the top then passes and does not stall.
WALK_MAX = 500
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build", "target"}
# The Grep `type` argument names a ripgrep file type. This table holds the
# common types with more than one suffix. The gate uses each other type as
# its own suffix.
TYPE_SUFFIXES = {
    "py": (".py", ".pyi"),
    "js": (".js", ".mjs", ".cjs", ".jsx"),
    "ts": (".ts", ".tsx", ".mts", ".cts"),
    "rust": (".rs",),
    "md": (".md", ".markdown"),
    "markdown": (".md", ".markdown"),
    "cpp": (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h"),
    "c": (".c", ".h"),
    "sh": (".sh", ".bash"),
    "yaml": (".yaml", ".yml"),
}

MESSAGE = (
    "DensePack: this path holds a source-text file already packed into an "
    "image. Read the image instead: %s . The words are the same. The "
    "image is what the plugin already paid to pack. File: %s"
)

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


def _matches_empty(pattern):
    """Return True when `pattern` matches each line. A content Grep with it
    prints the whole file.

    "^", ".*", "$", "" and the like match an empty line. "." matches no
    empty line but each other line. A pattern that matches each
    one-character probe below counts too. A pattern that Python cannot
    compile passes. The function does not guess."""
    if not isinstance(pattern, str):
        return False
    import re
    try:
        if re.search(pattern, "") is not None:
            return True
        return all(re.search(pattern, probe) is not None
                   for probe in (" ", "a", "Z", "0", "_", "(", "}", "#"))
    except (re.error, RecursionError, OverflowError):
        return False


def _head_limited(tool_input):
    """Return True when the call prints LINE_PULL_MAX lines or fewer, the
    same size that a Read keeps as text. A head_limit of 0 is no limit."""
    value = tool_input.get("head_limit")
    if isinstance(value, bool):
        return False
    try:
        count = int(value)
    except (TypeError, ValueError):
        return False
    return 0 < count <= LINE_PULL_MAX


def _braces(pattern):
    """Return `pattern` with one {a,b} group expanded. fnmatch lacks this
    ripgrep glob form."""
    start = pattern.find("{")
    end = pattern.find("}", start + 1)
    if start < 0 or end < 0:
        return [pattern]
    head, tail = pattern[:start], pattern[end + 1:]
    return [head + part + tail for part in pattern[start + 1:end].split(",")]


def _grep_filters(tool_input, base):
    """Return the file test of the Grep `glob` and `type` arguments. The
    gate then checks a folder dump against the files that it prints."""
    glob = tool_input.get("glob")
    kind = tool_input.get("type")
    globs = []
    negate = False
    if isinstance(glob, str) and glob.strip():
        glob = glob.strip()
        negate = glob.startswith("!")
        globs = _braces(glob.lstrip("!"))
    suffixes = None
    if isinstance(kind, str) and kind.strip():
        kind = kind.strip().lower()
        suffixes = TYPE_SUFFIXES.get(kind, ("." + kind,))

    def keep(child):
        if suffixes is not None and child.suffix.lower() not in suffixes:
            return False
        if globs:
            hit = any(_name_matches(child, base, g) for g in globs)
            return hit != negate
        return True
    return keep


def _first_drawn(folder, event, keep):
    """Return the first file under `folder` that a whole-file Read packs, or
    None. The walk covers what ripgrep walks by default, up to WALK_MAX
    files."""
    import drop_read_gate as gate
    seen = 0
    for root, dirs, files in os.walk(str(folder)):
        dirs[:] = sorted(d for d in dirs
                         if not d.startswith(".") and d not in SKIP_DIRS)
        for name in sorted(files):
            if name.startswith("."):
                continue
            seen += 1
            if seen > WALK_MAX:
                return None
            child = Path(root) / name
            if keep(child) and gate.draws_on_read(str(child), event):
                return child
    return None


def grep_dump_reason(event):
    """Return the deny reason for a Grep that dumps a whole file as text
    when a Read gives its image, or None to let the Grep run.

    The function returns a reason only when the call is in content mode,
    its pattern matches an empty line, it has no head_limit of LINE_PULL_MAX
    or fewer, and its target is a file that a Read packs or a folder that
    holds one. drop_read_gate.draws_on_read() makes the decision for the
    file, the same as for a Read. A missing `path` is the project folder,
    where Grep searches by default."""
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if tool_input.get("output_mode") != "content":
        return None
    if not _matches_empty(tool_input.get("pattern")):
        return None
    if _head_limited(tool_input):
        return None
    path = tool_input.get("path")
    if path is not None and not isinstance(path, str):
        return None
    if not path:
        path = event.get("cwd") or str(project_dir())
    resolved = _resolved(path)
    if resolved is None:
        return None
    from common import gets_images
    if not gets_images(event):
        return None
    import drop_read_gate as gate
    if resolved.is_file():
        if gate.draws_on_read(str(resolved), event):
            return DUMP_MESSAGE % quoted_path(resolved)
        return None
    if resolved.is_dir():
        found = _first_drawn(resolved, event, _grep_filters(tool_input, resolved))
        if found is not None:
            return DUMP_MESSAGE_FOLDER % (quoted_path(resolved), quoted_path(found))
    return None


def main():
    # A fault never blocks the call. This gate runs before each Grep and
    # each Glob.
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        tool = event.get("tool_name") or ""
        # EACH REAL GREP PASSES. One Grep on a text copy or a source text
        # must work in one call. The gate denies only a match-all dump of a
        # file that a Read packs. See the module docstring.
        if tool == "Grep":
            reason = grep_dump_reason(event)
            if reason:
                emit({"hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }})
            return 0
        if tool != "Glob":
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
