"""Keeps the list of waiting report images, and opens an expired image from
the vault.

Each packed subagent report puts its images on the pending list. The lead
reads the waiting images with Read calls in one message, and one message is
one turn. DensePack 1.3.3 also joined the waiting images into one image. Two
packed reports did not fit in one image without a downscale, and DensePack
1.3.4 removes the join. The lead gets each report as its own image.

This gate does two things on a Read of a packed report image.

  It marks the image delivered. A note about waiting images then does not
  name it again.
  When the image is gone from .claude/tmp, it opens the copy in the vault
  folder of this conversation. It changes the Read only in a mode that asks
  before no Read. See THE PERMISSION RULE in common.py.
"""

import json
import sys
from pathlib import Path

from common import (disabled, emit, may_rewrite, pending_entries, project_dir,
                    read_event, tmp_dir, vault_dir)

# The three name prefixes that the plugin gives a packed image. The gate does
# not change a Read of another file, because a Read before an Edit needs the
# real file. The Edit tool matches its old_string exactly, and a changed Read
# makes the model edit against text that it did not read.
PACKED_NAMES = ("densepack-img-", "densepack-bash-", "densepack-brief-")

# The file that records which pending rows the gate already returned. It is
# next to the pending list and not inside it. A crash between the swap and
# the write of this file loses nothing. An image that is not in this file
# stays pending for the next Read.
DELIVERED = "densepack-delivered.json"


def delivered_set():
    try:
        body = (tmp_dir() / DELIVERED).read_text(encoding="utf-8")
        found = json.loads(body)
    except (OSError, ValueError):
        return set()
    return set(found) if isinstance(found, list) else set()


def mark_delivered(paths):
    keep = delivered_set() | set(paths)
    # write_text_atomic moves a new file onto the name. The move replaces a
    # link at that name and does not write through it.
    from common import write_text_atomic
    write_text_atomic(tmp_dir() / DELIVERED, json.dumps(sorted(keep)))


def waiting():
    """Return each pending image that is on disk and not yet returned."""
    done = delivered_set()
    # Each image that the plugin packs is under the .claude folder of the
    # project. A row that names another path came from a file that the
    # plugin did not write. The gate skips that row. Without this check, the
    # composite can show that image to the model.
    root = (project_dir() / ".claude").resolve()
    out = []
    for row in pending_entries():
        path = str(row.get("image") or "")
        if not path or path in done:
            continue
        try:
            inside = root in Path(path).resolve().parents
        except (OSError, ValueError):
            inside = False
        if not inside:
            continue
        out.append(path)
    return out


def main():
    # A fault never blocks the call. This gate runs before each Read in the
    # session.
    try:
        event = read_event()

        # 1. The plugin is on for the session that the event names.
        #    disabled() with no id returns the state of another window.
        if disabled(event.get("session_id")):
            return 0

        # 2. The call is a Read.
        if (event.get("tool_name") or "") != "Read":
            return 0

        tool_input = dict(event.get("tool_input") or {})

        # 3. The event has a file path.
        asked = tool_input.get("file_path")
        if not isinstance(asked, str) or not asked:
            return 0

        # 4. That path names a packed image.
        name = asked.replace("\\", "/").rsplit("/", 1)[-1]
        if not any(name.startswith(mark) for mark in PACKED_NAMES):
            return 0

        # The swaps below change the Read before it runs. They are for the
        # modes that ask before no Read. See THE PERMISSION RULE in
        # common.py. In the other modes the Read opens the image it names.
        if not may_rewrite(event, "Read"):
            return 0

        # 5. That exact path is on the pending list. The gate matches the
        #    full path and not the file name. A file with the same name in
        #    another folder does not match.
        # A pointer can be older than the sweep. The tmp copy is then gone,
        # but the copy that keep_copy() put in the vault folder of this
        # conversation is still there. The gate changes the Read to that
        # copy. A session open past 24 hours can still open each image that
        # it got.
        pending = waiting()
        if asked not in pending:
            if not Path(asked).is_file():
                alt = vault_dir(event.get("session_id")) / name
                if alt.is_file():
                    tool_input["file_path"] = str(alt)
                    emit({"hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "updatedInput": tool_input,
                    }})
            return 0

        # The Read opens `asked` as written. The gate marks it delivered, and
        # the pending list then names only the images that still wait.
        mark_delivered([asked])
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
