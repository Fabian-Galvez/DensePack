"""Replaces a Read's result with its image, after the Read runs on the real
file.

When drop_read_gate.py sends a Read to the file's image before the Read
runs, Claude Code records a Read of the PNG, not of the file. It then
rejects a later Edit of the file with the error "not been read yet". Here
the Read runs on the real file. Claude Code records the Read and accepts an
Edit. This hook then replaces the Read's result with the image. Only the
tokens that reach the model cost money, and the text that the Read makes
locally costs nothing. A model that gets such a result reads the number in
the image, and Claude Code applies its Edit of the same file.

The hook runs on PostToolUse and PostToolUseFailure of Read. It calls
drop_read_gate.route() to get the image for the Read. route() holds all the
rules, which are the whole-file pages, the image of the lines that an
offset and limit name, the check that the text costs less, the burst cap
and the note sent once for each file. A Read that the gate leaves as text
stays text. A Read that failed, such as a Read of a file larger than the
Read limit, gets its image the same way.

THE HOOK NEVER CRASHES A CALLER. On a fault, it leaves the result as it was.
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import emit, read_event  # noqa: E402


def image_result(event):
    """Returns the PostToolUse answer that replaces this Read's result with
    its image. Returns None to leave the result as it is."""
    if event.get("tool_name") != "Read":
        return None
    resp = event.get("tool_response")
    if isinstance(resp, dict) and resp.get("type") == "image":
        return None
    # A Read that the user or a rule refused gets no image. Claude Code
    # 2.1.288 fires no PostToolUseFailure for such a Read, and this check
    # keeps the rule if a later version does.
    error = str(event.get("error") or "").lower()
    if "permission" in error or "denied" in error:
        return None
    import drop_read_gate as gate
    pre = {k: v for k, v in event.items() if k not in ("tool_response", "error")}
    pre["hook_event_name"] = "PreToolUse"
    pre["tool_input"] = dict(event.get("tool_input") or {})
    answer = gate.route(pre, post=True)
    hs = (answer or {}).get("hookSpecificOutput") or {}
    image = (hs.get("updatedInput") or {}).get("file_path")
    if not image or hs.get("permissionDecision") or not Path(image).is_file():
        return None
    if Path(image).suffix.lower() != ".png":
        return None
    from PIL import Image
    raw = Path(image).read_bytes()
    with Image.open(image) as im:
        w, h = im.size
    out = {"type": "image", "file": {
        "base64": base64.b64encode(raw).decode("ascii"), "type": "image/png",
        "originalSize": len(raw),
        "dimensions": {"originalWidth": w, "originalHeight": h,
                       "displayWidth": w, "displayHeight": h}}}
    reply = {"hookEventName": event.get("hook_event_name") or "PostToolUse",
             "updatedToolOutput": out}
    if hs.get("additionalContext"):
        reply["additionalContext"] = hs["additionalContext"]
    return {"hookSpecificOutput": reply}


def main():
    try:
        answer = image_result(read_event())
        if answer:
            emit(answer)
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
