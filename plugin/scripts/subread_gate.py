"""Sends a subagent's big Read through the Bash path, where it arrives packed.

HOW THIS FILE FITS, in plain words: bash_gate.py already packs what a
subagent reads through cat, sed, grep and the other reader programs, and
subagent_start.py teaches every agent how to use the packed result. The Read
tool was the hole: a subagent's Read of a long file landed in that agent's
context as raw text, at full price, with nothing offering the packed copy.
This is a PreToolUse hook on Read, the same shape as verify_gate.py but for
the OTHER side: it fires only for sessions that are confirmed not the lead.

THE MEASUREMENT BEHIND IT, taken 29 August 2026 over 599 subagent
transcripts of this project (agent-*.jsonl under the Claude Code projects
folder): 3,765 Read calls, 965 of images or PDFs, 2,800 of text. At the
1,306 character opus floor, 1,742 were full reads, no offset and no limit,
at or over the floor. 1,367 of those, 78.5 per cent, never fed a later Edit
or Write of the same file: 15,541,542 characters that needed no exact bytes
and could have arrived packed. The other 375, 21.5 per cent, fed an edit
and DO need the raw file, which is why this gate denies a given file once
and lets the repeat through.

WHAT A DENY SAYS. Run the same file through cat: bash_gate.py rewrites that
command, bash_pack.py packs the output, and the agent gets the pointer, the
image, and the exact text on disk beside it. An agent that is about to Edit
the file repeats the Read instead, and the repeat passes, because the
once-per-file marker is already down. Either way one file costs at most one
extra agent-side turn, and the 78.5 per cent case stops paying full price.

THE FLOOR IS THE MEASURED ONE. common.bash_chars(), the character count at
which the bash-route packer this gate redirects into flips from refusing to
packing for the reader in force. The file's byte size stands in for its character count
here; a multi-byte file over-counts slightly, and bash_pack.py re-prices
the real text before packing, so a file the image cannot actually help is
still returned as text by the packer itself.

WHO THIS NEVER TOUCHES. The lead (verify_gate.py owns the lead's reads), a
session that cannot be proven a subagent (no session id, or no lead list to
compare against), a densepack-* file with NO image beside it (the plugin's
own bookkeeping: settings, manifest, legend sidecar and the like), an image,
PDF or notebook, and a Read carrying offset or limit, which is already a
targeted, economical read.

FIXED 29 August 2026, FIXES-PENDING.md section 3. A densepack-* file used to
pass here on its name alone, which let a subagent Read
densepack-briefsrc-<stamp>.txt or densepack-src-<agent id>.txt as raw text
even when the packed image beside it, densepack-brief-<stamp>-1.png or
densepack-img-<agent id>-1.png, already held the same words. The name never
told the difference between that source-text sidecar and a file like
densepack-manifest.jsonl that has no image at all. common.sibling_image()
now answers the real question, by matching the file's own name against the
patterns the packers write and checking the image exists on disk. When one
does, the Read is redirected to the image instead of allowed through: the
exact-text file still exists for the one case that needs it, an Edit about
to match against it, which reaches it through the untouched retry path
below, never through this exemption.

NOTES, what this deliberately leaves open, recorded rather than silent:
  - The repeat Read passes unpacked by design, for the 21.5 per cent that
    feed an Edit, so a non-complying agent can still read raw at the cost
    of one denial per file.
  - Grep with context flags and Glob results are not covered; nothing
    measures how much a subagent's Grep output weighs yet.
  - This gate makes no sizing decision of its own. It denies the Read and
    points the agent at cat, and bash_gate.py decides from there. CHANGED
    31 August 2026: this note used to say the image is drawn at the LEAD's
    measured size and that an agent on an unmeasured model works from the
    exact-text sidecar. It does not any more. bash_gate.py now leaves the
    cat alone for an actor whose model has no measured floor, so that
    agent reads plain text and no image is drawn for it at all. Haiku
    readers were misreading facts off images drawn at another model's
    floor, and a sidecar it had to be told to open did not prevent it.
NEVER CRASH A CALLER. One try around everything; any fault allows the Read.
"""

import hashlib
import sys

from common import (bash_chars, disabled, emit, read_event, read_leads,
                    sibling_image, tmp_dir)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf",
                  ".ipynb")

# One marker per session and file: its presence means this file was already
# deflected once and every later Read of it passes. Pruned with the other
# working files by bootstrap.py.
MARKER = "densepack-readonce-%s-%s"

# 313 fixed characters before the size and path fill in, about 130 tokens
# at the measured 2.40 characters a token, charged at
# most once per file per agent, on the agent's side of the ledger, against
# the measured 15,541,542 characters of raw reads it exists to deflect.
MESSAGE = (
    "DensePack: this file is %s bytes, over the pack floor. Do not Read it "
    "raw. Run it through Bash instead: cat \"%s\" . The output comes back "
    "packed, with its exact text saved beside it, and costs less than the "
    "raw read. Use the Read tool only when you are about to Edit this "
    "file: repeat this exact Read and it will pass."
)


def marker_path(session_id, file_path):
    digest = hashlib.sha256(
        str(file_path).replace("\\", "/").lower().encode("utf-8")
    ).hexdigest()[:12]
    return tmp_dir() / (MARKER % (str(session_id)[:8], digest))


def main():
    # NEVER CRASH A CALLER. This runs before every Read in every session.
    try:
        # Each condition on its own line, never joined into one expression,
        # the same discipline READ-BATCH-SPEC.md sets for read_gate.py.
        event = read_event()
        if disabled(event.get("session_id")):
            return 0

        if (event.get("tool_name") or "") != "Read":
            return 0

        # Confirmed NOT the lead, or no verdict at all. A missing session
        # id, or an empty lead list, is no proof this is a subagent, and
        # acting on a guess could slow a lead bootstrap never recorded.
        sid = str(event.get("session_id") or "")
        if not sid:
            return 0
        leads = read_leads()
        if not leads:
            return 0
        if sid in leads:
            return 0

        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        path = tool_input.get("file_path")
        if not isinstance(path, str) or not path:
            return 0

        name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name.endswith(IMAGE_SUFFIXES):
            return 0
        if name.startswith("densepack-"):
            # Not exempt on the name alone. A source-text sidecar with a
            # drawn image beside it is redirected to that image instead of
            # allowed through; a plugin bookkeeping file with no image
            # (settings, manifest, legend sidecar, marker) has nothing to
            # redirect to and passes as before.
            image = sibling_image(path)
            if image is None:
                return 0
            tool_input["file_path"] = image
            emit({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": tool_input,
                }
            })
            return 0

        # offset or limit means a targeted partial read, already the cheap
        # form. 780 of the 2,800 measured text reads were this shape.
        if tool_input.get("offset") or tool_input.get("limit"):
            return 0

        from pathlib import Path
        try:
            size = Path(path).stat().st_size
        except OSError:
            return 0
        if size < bash_chars():
            return 0

        marker = marker_path(sid, path)
        if marker.exists():
            return 0
        # Written before the deny goes out: a fault after this line lets
        # the Read through with the marker already down, which only means
        # one file was never deflected. The reverse order could deny the
        # same file forever.
        try:
            marker.write_text("1", encoding="utf-8")
        except OSError:
            return 0

        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": MESSAGE % (format(size, ","), path),
            }
        })
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
