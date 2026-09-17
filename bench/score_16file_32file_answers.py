"""Score one answers.txt from the ab-big or ab-gd task against the answer key.

Usage: python bench/score_16file_32file_answers.py <answers.txt> [py|gd]

The second argument names the sample files. It defaults to py, the Python task.
"""
import re
import sys

KEYS = {
    # The sixteen sample files in bench/sixteen-file/FILES.txt, five plain
    # questions, one per line of TASK.txt in that folder. Three name a script
    # by what it does, so a reader has to open every file to find them. One
    # reads a constant. One reads a function name at line 495 of
    # drop_read_gate.py, past the first image of that file, so a leg that
    # never fetched a second image cannot score 5 of 5.
    "py": [
        ["write_gate.py", "write_gate"],
        ["tier_gate.py", "tier_gate"],
        ["gate_cost.py", "gate_cost"],
        ["6"],
        ["capped"],
    ],
    # The thirty-two .py files of bench/thirty-two-file/sample files, ten
    # questions, one per line of TASK.txt there. Written 13 September 2026.
    # Five ask the function defined at a line in the second half of its
    # file, so a page past the first image has to arrive. Five ask a value
    # or a name the reader works out from the code: a range's first index,
    # a count a docstring states, the length of a list literal, a file name
    # string and a constant's name.
    # REPLACED the same day, when the sample files became thirty-two of the
    # plugin's own scripts, bench/thirty-two-file/FILES.txt, and the
    # task five plain questions of the same shape. Question 5 reads
    # CARD_CACHE at line 381 of bootstrap.py, an image past the first of that file. The old
    # eleven answers sit in git history.
    "py32": [
        ["stop_gate.py", "stop_gate"],
        ["watchdog.py", "watchdog"],
        ["session_end.py", "session_end"],
        ["2000"],
        ["densepack-cards"],
    ],
    # The twenty-six .gd files in bench/gdsample files, five questions.
    "gd": [
        ["742"],
        ["5", "8", "13"],
        ["THAT WOKE THE HOUSE"],
        ["user://catnap.cfg"],
        ["_add"],
    ],
}
# Zero-based rows where every key part must appear, per sample files.
ALL_REQUIRED_BY = {"py": set(), "py32": set(), "gd": {1}}

WHICH = sys.argv[2] if len(sys.argv) > 2 else "py"
KEY = KEYS[WHICH]
ALL_REQUIRED = ALL_REQUIRED_BY[WHICH]

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
lines = {}
for line in text.splitlines():
    m = re.match(r"\s*(\d+)[.)]?\s*(.*)", line)
    if m:
        lines[int(m.group(1))] = m.group(2).strip()
right = 0
for i, parts in enumerate(KEY, 1):
    ans = lines.get(i, "")
    low = ans.lower()
    if (i - 1) in ALL_REQUIRED:
        ok = all(p.lower() in low for p in parts)
    else:
        ok = any(p.lower() in low for p in parts)
    if WHICH in ("py", "py32"):
        # every py answer is one identifier or one number, so it must stand
        # as a whole word. A word boundary alone lets 4 score inside 4.5, so
        # a digit or a dot on either side also fails.
        # Any listed form counts, so write_gate scores beside write_gate.py.
        ok = any(re.search(r"(?<![\w.])%s(?![\w.])" % re.escape(p), ans)
                 for p in parts)
    right += ok
    print("%2d %s | %s" % (i, "ok " if ok else "BAD", ans[:90]))
print("SCORE %d of %d" % (right, len(KEY)))
