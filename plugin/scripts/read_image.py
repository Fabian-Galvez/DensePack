"""Replaces a Read's result with its images, after the Read runs on the real
file. A whole-file Read gets all the images up to line 2,000, and a range
Read gets all the images of the range, in one result.

When drop_read_gate.py sends a Read to the file's image before the Read
runs, Claude Code records a Read of the PNG, not of the file. It then
rejects a later Edit of the file with the error "not been read yet". Here
the Read runs on the real file. Claude Code records the Read and accepts an
Edit. This hook then replaces the Read's result with the images. Only the
tokens that reach the model cost money, and the text that the Read makes
locally costs nothing. A model that gets such a result reads the number in
the image, and Claude Code applies its Edit of the same file.

The hook runs on PostToolUse and PostToolUseFailure of Read. It calls
drop_read_gate.route() to get the image for the Read. route() holds all the
rules, which are the whole-file pages, the image of the lines that an
offset and limit name, the check that the text costs less and the note sent
once for each file. A Read that the gate leaves as text
stays text. A Read that failed, such as a Read of a file larger than the
Read limit, gets its image the same way.

THE HOOK NEVER CRASHES A CALLER. On a fault, it leaves the result as it was.
"""
import base64
import re
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
    # A Read that you or a rule refused gets no image. Claude Code
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
    note = hs.get("additionalContext") or ""
    pages = all_pages(Path(image), event, note)
    if pages:
        out = {"type": "parts", "file": {
            "filePath": str(image), "originalSize": sum(len(p) for p in pages),
            "count": len(pages), "outputDir": str(Path(image).parent)},
            "firstPage": 1,
            "pages": [{"base64": base64.b64encode(p).decode("ascii"), "mediaType": "image/png"}
                      for p in pages]}
        note = all_pages_note(note, len(pages), int(PAGE_ONE.search(Path(image).name).group(1)))
    from common import first_image_note
    note = "\n".join(x for x in (first_image_note(event), note) if x)
    reply = {"hookEventName": event.get("hook_event_name") or "PostToolUse",
             "updatedToolOutput": out}
    if note:
        reply["additionalContext"] = note
    return {"hookSpecificOutput": reply}


# A whole-file Read of a file of more than one page returns all its pages in
# one result, the Read result type "parts" of Claude Code. Before, the result
# held page 1 and a note named the other pages, and the model Read them in
# later requests. Each of those requests sends the whole conversation again.
# In an architecture-doc run on 9 October 2026, 70 page Reads took 10 extra
# requests. On Claude Code 2.1.295, one Read result carried 18 pages, and
# Sonnet 5.5 read each one.
PAGE_ONE = re.compile(r"-image-1-of-(\d+)-DensePack\.png$")
# A text Read without a limit returns the first 2,000 lines of a file. The
# pages go up to the page that holds line 2,000, so a long file returns about
# what its text would.
TEXT_READ_LINES = 2000
PAGE_LINES = re.compile(r"#(\d+)=(\d+)-")


def all_pages(first, event, note=""):
    """Return the bytes of each page of the file, in page order, when this
    Read is a whole-file Read and the file has more than one page. The pages
    stop at the page that holds line TEXT_READ_LINES, when the note gives the
    first line of each page. Return None otherwise, and the Read keeps its
    single image."""
    tool_input = event.get("tool_input") or {}
    ranged = bool(tool_input.get("offset") or tool_input.get("limit"))
    # A Read of a line range gets images of only those lines, named with
    # "-lines-". A text Read returns the whole range in one result, so the
    # images of the range all go in one result too. A ranged Read that got a
    # page of the whole-file pack keeps its single image.
    if ranged and "-lines-" not in first.name:
        return None
    m = PAGE_ONE.search(first.name)
    if not m or int(m.group(1)) < 2:
        return None
    total = int(m.group(1))
    starts = {int(n): int(a) for n, a in PAGE_LINES.findall(note)}
    if starts and not ranged:
        total = max([n for n, a in starts.items() if a <= TEXT_READ_LINES] or [1])
    stem = first.name[:m.start()]
    count = int(m.group(1))
    if total < 2:
        return None
    paths = [first.parent / ("%s-image-%d-of-%d-DensePack.png" % (stem, n, count))
             for n in range(1, total + 1)]
    if not all(p.is_file() for p in paths):
        return None
    return [p.read_bytes() for p in paths]


def all_pages_note(note, sent, count):
    """Rewrite the note for a result that holds pages 1 to `sent` of `count`.
    With every page sent, the note no longer names pages to Read. It keeps the
    line range of each page and the rows of exact text."""
    m = re.search(r"This is image 1 of \d+, (.*?-DensePack\.png)(?:, lines [^.]*?)?\.", note)
    if sent == count:
        head = "This result holds all %d images, in page order." % count
        note = re.sub(r"Image \d+ of \d+ is .*?-DensePack\.png(?:, lines [^.]*?)?\. ?", "", note)
        note = note.replace("Read all the other images that you need in one turn.", "")
    else:
        head = ("This result holds images 1 to %d of %d, like a text Read of 2,000 lines. "
                "Image 1 is %s. The other images have the same name with their own number."
                % (sent, count, m.group(1) if m else "the first image"))
    if m:
        note = note[:m.start()] + head + note[m.end():]
    return note.strip()


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
