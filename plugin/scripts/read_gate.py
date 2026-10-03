"""One Read call gets all waiting images, in place of one Read per image.

When several images wait for a Read, this gate replaces the path of the first
image that the model asks for. The Read then returns one image that holds all
of them. The model pays for one Read in place of several.

The reason. Claude Code sends the whole conversation at the start of each
turn, and each tool call is its own turn. A Read call for a packed image is
one more send of the whole conversation so far. Over 470 turns of one
session, the mean send was 220,917 tokens. Five such Read calls used
1,104,584 tokens, against the 3,602,187 tokens that packing the reports as
images saved.

| Reads per batch of images | Read turns in one session | Net saved | Cut |
| One per image | 62 | 3,361,782 | 3.8 per cent |
| One per batch | 17 | 13,303,047 | 13.6 per cent |

The conditions. The gate checks ten conditions, each with its own `if`, and
never joins them into one expression. A gate that joins its terms with `and`
can lose a middle term and read as false. A gate in this plugin is a hook
that changes or rejects a tool call before it runs. When this gate cannot
check a condition, it leaves the Read as the model typed it.
"""

import json
import sys
from pathlib import Path
import time

from common import (disabled, emit, may_rewrite, pending_entries, pending_path,
                    project_dir, read_event, tmp_dir, vault_dir)
import densepack as dp

# The three name prefixes that the plugin gives a packed image. The gate does
# not change a Read of another file, because a Read before an Edit needs the
# real file. The Edit tool matches its old_string exactly, and a changed Read
# makes the model edit against text that it did not read.
PACKED_NAMES = ("densepack-img-", "densepack-bash-", "densepack-brief-")

COMPOSITE = "densepack-composite-1.png"

# The cost of one extra turn, in tokens. Claude Code sends the whole
# conversation at the start of each turn. A Read call is one more send of the
# whole conversation so far. Over 470 turns of one session, the mean was
# 220,917 tokens and the median was 220,261. The code uses the mean, because
# it compares sums and not single cases.
TURN_TOKENS = 220917

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


def _pending_ids(paths):
    """Return the id recorded for each path in `paths`.

    The function reads the ids from the pending list at each call. A manifest
    row then names the reports in a batch, and does not only count them. For
    a row with no id field, or a path that is no longer in the pending list,
    the function uses the stem of the file name. The function never raises,
    and the audit row always names something."""
    from pathlib import Path

    by_path = {}
    for row in pending_entries():
        path = str(row.get("image") or "")
        if path:
            by_path[path] = str(row.get("id") or "") or Path(path).stem
    return [by_path.get(p) or Path(p).stem for p in paths]


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

        # After this point, the model gets `asked` in one of two ways. The
        # unchanged Read gets it, or a swap below returns a composite that
        # contains it. The gate marks it delivered now, not only after a
        # swap. A LATER composite then does not show the model the same
        # image a second time. This case happens when reports finish a few
        # seconds apart and not all at once.
        mark_delivered([asked])

        # 6. At least two images are waiting. One image needs no composite.
        if len(pending) < 2:
            return 0

        # 7. Each waiting image exists on disk. A missing part drops content
        #    without a warning. Path is the module import. A local import
        #    here makes Path a local name for the whole function and breaks
        #    the vault copy step above.
        if not all(Path(p).is_file() for p in pending):
            return 0

        # 8. The gate writes the composite and reads its size from the file.
        #    It does not guess the size.
        made = dp.composite(pending, str(tmp_dir() / COMPOSITE))
        if made is None:
            return 0
        out_path, width, height = made

        # 9. The composite costs less than the images it replaces PLUS the
        #    turns it removes.
        #
        #    A test of patches alone rejects each composite. Three real
        #    images stack to 494 patches, against 474 for the three apart. A
        #    stack of pages with the same width adds their rows together and
        #    adds a header line for each page, and a composite usually costs a
        #    few patches more. The saving of a composite is in the turns. Two
        #    fewer Read calls save 441,834 tokens at the measured mean,
        #    against 20 more patches.
        separate = 0
        for path in pending:
            try:
                from PIL import Image
                with Image.open(path) as img:
                    separate += dp.image_cost(img.width, img.height)
            except Exception:  # noqa: BLE001
                return 0
        turns_saved = (len(pending) - 1) * TURN_TOKENS
        if dp.image_cost(width, height) >= separate + turns_saved:
            return 0

        # 10. The composite is inside the size that the API does not
        #     downscale. A downscaled composite loses its text.
        if not dp.no_downscale(width, height):
            return 0

        # The gate emits the swap BEFORE it marks the rows delivered. After a
        # fault between the two steps, the images stay pending and nothing is
        # lost. updatedInput replaces the whole input object, and the gate
        # returns each field of the event input.
        tool_input["file_path"] = str(out_path)
        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": tool_input,
            }
        })
        mark_delivered(pending)

        # A manifest row for the batch. The saving of this gate is then
        # auditable, the same as a report or a bash pack. A manifest fault
        # never undoes or hides the swap above. The gate already emitted the
        # swap, and this row is only its record.
        try:
            from subagent_stop import manifest_write
            ended = time.time()
            manifest_write({
                "kind": "read_batch",
                "agent_id": "batch-%d" % int(ended * 1000),
                "spawned_by": str(event.get("session_id") or ""),
                "reports": _pending_ids(pending),
                "count": len(pending),
                "composite": str(out_path),
                "ended": ended,
            })
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
