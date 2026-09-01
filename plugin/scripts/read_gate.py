"""One Read call fetches every image waiting, instead of one Read each.

HOW THIS FILE FITS, in plain words: when several pictures are waiting to be
read, this swaps the first one the lead asks for and hands back a single
picture holding all of them. The lead pays for one look instead of several.

WHY IT EXISTS, measured 25 August 2026. Claude Code sends the whole
conversation at the start of every turn, and every tool call is its own turn.
A Read call to fetch a packed image is therefore one extra send of everything
said so far, 220,917 tokens as the mean over 470 turns of one session. Five
such Read calls spent 1,104,584 tokens against the 3,602,187 that drawing the
reports as images had saved.

| Reads per batch of images | Read turns in one session | Net saved | Cut |
| One per image | 62 | 3,361,782 | 3.8 per cent |
| One per batch | 17 | 13,303,047 | 13.6 per cent |

THE CONDITIONS. Ten of them, in plugin/READ-BATCH-SPEC.md, written before this
file. Each is checked in its own `if` and never joined into one expression:
CLAUDE.md records a gate whose three terms were joined with `and`, where the
middle term went missing and the whole test read as false. A gate here means a
hook that changes or refuses a tool call before it runs, and this one fails
closed, meaning any condition it cannot check leaves the Read exactly as the
lead typed it.
"""

import json
import sys
import time

from common import (disabled, emit, pending_entries, pending_path, read_event,
                    tmp_dir)
import densepack as dp

# The three names the plugin gives a packed image. A Read of anything else is
# left alone, because a Read before an Edit needs the real file: the Edit tool
# matches its old_string exactly, and a swapped Read would make the model edit
# against text it never saw.
PACKED_NAMES = ("densepack-img-", "densepack-bash-", "densepack-brief-")

COMPOSITE = "densepack-composite-1.png"

# What one extra turn costs, in tokens. Claude Code sends the whole
# conversation at the start of every turn, so a Read call is one more send of
# everything said so far. Measured 25 August 2026 over 470 turns of one
# session: the mean was 220,917 tokens and the median 220,261. The mean is
# taken, because the figure is used to compare sums rather than single cases.
TURN_TOKENS = 220917

# The file recording which pending rows have already been handed over. Kept
# beside the pending list rather than inside it, so a crash between writing
# the swap and writing this file loses nothing: an image not recorded here is
# simply offered again.
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
    (tmp_dir() / DELIVERED).write_text(json.dumps(sorted(keep)),
                                       encoding="utf-8")


def _pending_ids(paths):
    """The id recorded for each path in `paths`, read fresh from the pending
    list, so a manifest row can name which reports a batch contains instead
    of only counting them. A row written before the id field existed, or a
    path this function is asked about that the pending list no longer
    carries, falls back to the file's own stem, so the audit row always
    names something rather than raising."""
    from pathlib import Path

    by_path = {}
    for row in pending_entries():
        path = str(row.get("image") or "")
        if path:
            by_path[path] = str(row.get("id") or "") or Path(path).stem
    return [by_path.get(p) or Path(p).stem for p in paths]


def waiting():
    """Every pending image that exists on disk and has not been handed over."""
    done = delivered_set()
    out = []
    for row in pending_entries():
        path = str(row.get("image") or "")
        if not path or path in done:
            continue
        out.append(path)
    return out


def main():
    # NEVER CRASH A CALLER. This runs before every Read in the session.
    try:
        event = read_event()

        # 1. The plugin is on, asked of the session the event names, because
        #    disabled() with no id in hand answers for another window.
        if disabled(event.get("session_id")):
            return 0

        # 2. The call is a Read.
        if (event.get("tool_name") or "") != "Read":
            return 0

        tool_input = dict(event.get("tool_input") or {})

        # 3. The event carries a file path.
        asked = tool_input.get("file_path")
        if not isinstance(asked, str) or not asked:
            return 0

        # 4. That path names a packed image.
        name = asked.replace("\\", "/").rsplit("/", 1)[-1]
        if not any(name.startswith(mark) for mark in PACKED_NAMES):
            return 0

        # 5. That exact path is on the pending list, matched in full rather
        #    than by file name, so two folders holding the same name cannot be
        #    confused for each other.
        pending = waiting()
        if asked not in pending:
            return 0

        # From here on, `asked` reaches the lead one way or another: either
        # the untouched Read below fetches it directly, or a swap further
        # down hands over a composite that already contains it. Marking it
        # delivered now, not only when a swap succeeds, keeps a singly read
        # image out of a LATER composite that would otherwise show it to the
        # lead a second time. Found running the read batch gate against a
        # report finishing every few seconds rather than all at once: the
        # first report was read alone, correctly, but stayed marked pending
        # forever and was drawn a second time inside the composite the
        # SECOND report earned on its own.
        mark_delivered([asked])

        # 6. At least two images are waiting. One image needs no composite.
        if len(pending) < 2:
            return 0

        # 7. Every waiting image exists on disk. A missing part would drop
        #    content with nothing saying so.
        from pathlib import Path
        if not all(Path(p).is_file() for p in pending):
            return 0

        # 8. The composite is written and its size is read back from the file
        #    rather than assumed.
        made = dp.composite(pending, str(tmp_dir() / COMPOSITE))
        if made is None:
            return 0
        out_path, width, height = made

        # 9. The composite costs less than the images it replaces PLUS the
        #    turns it removes.
        #
        #    Comparing patches alone was wrong and the test caught it on
        #    25 August 2026: three real images stacked to 494 patches against
        #    474 for the three apart, so a patch comparison refused every
        #    composite. Stacking pages of the same width sums their rows and
        #    adds a header line each, so a composite nearly always costs a few
        #    patches more. The patches are not what a composite buys. It buys
        #    the turns: two Read calls removed, 441,834 tokens on the measured
        #    mean, against 20 more patches.
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

        # 10. The composite is inside the size the API leaves alone. A
        #     downscaled composite loses the text it exists to carry.
        if not dp.no_downscale(width, height):
            return 0

        # The swap is emitted BEFORE the rows are marked handed over, so a
        # fault between the two offers the images again rather than losing
        # them. updatedInput replaces the input object outright, so every
        # field the event carried is sent back.
        tool_input["file_path"] = str(out_path)
        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": tool_input,
            }
        })
        mark_delivered(pending)

        # A manifest row for the batch itself, so the saving this gate buys
        # is auditable the same way a report or a bash pack already is.
        # Never lets a manifest fault undo or hide the swap above: the swap
        # was already emitted, and this row is only the record of it.
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
