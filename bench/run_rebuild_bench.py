"""Score a byte identical rebuild of one file read only as a picture.

The accuracy bench. A reader is given a file path, the plugin hands it a
picture instead of the text, and the reader writes the file back out. The
rebuild is compared to the source with no stripping of any kind.

Earlier accuracy tables in this repository report a "stripped ratio", which
ignores each line's leading and trailing white space. Stripping the line
edges strips the indent, so an indent the page never carried scores as
correct. This bench never strips. It reports the raw ratio, the byte
comparison, and the indent and blank line accuracy on their own.

Run it in two steps.

  1. Build the arena and print the brief:

     python bench/run_rebuild_bench.py build --file bench/byte-identical-rebuild/samples/ab_run.py --arena ../DensePack-arenas/rebuild/rebuild-1

  2. Run the reader, then score:

     cd ../DensePack-arenas/rebuild/rebuild-1
     claude -p --model claude-opus-5 --tools Read,Write --allowedTools Read,Write < task.txt

  --tools AND --allowedTools, BOTH, from 11 September 2026. They do different
  jobs: --tools decides which tools EXIST, and --allowedTools decides which
  ones run without asking. The command carried only the second until this
  date, so the reader still had Bash, Write and PowerShell.

  MEASURED on an Opus leg that day: it tried a Bash heredoc, a second Bash
  call, and PowerShell twice, and the permission layer refused all four. It
  spent 5 of its 8 turns on that and wrote a Python script into its own
  scratchpad to emit the file rather than writing the file. bench/run_bench_arm.py
  has always passed both flags, which is why no other bench hit this.

     python bench/run_rebuild_bench.py score --file bench/byte-identical-rebuild/samples/ab_run.py --arena ../DensePack-arenas/rebuild/rebuild-1

The arena is kept outside the repository so the reader cannot reach the
source by searching the working tree. It holds task.txt and nothing else
until the reader writes rebuild.txt.

Prove the plugin's image before every run:

    python bench/check_bench_setup.py

History. The first Opus run of this bench scored 0.9605. That brief told the
reader to write one long line and mark each line break with a vertical bar,
and tools/ab_run.py prints markdown tables, so its own text holds 60 vertical
bars. The decoder turned all 60 into line breaks. The brief destroyed those
characters, the reader did not misread them. The brief below keeps real line
breaks and the same reader then scored 1.0000.
"""
import argparse
import difflib
import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bench"))
# arena_root is the one place that names DensePack-arenas beside the
# repository. Commit 3a444ef named it here and never imported it, so every
# run and build stopped with a NameError. Found 13 September 2026.
from run_bench_arm import arena_root, maxpack_on

# REWRITTEN 12 September 2026. Only the two paths are filled in per arena.
#
# What changed from the brief before it, and why each change is here:
#
#   It names the page's own marks. The old brief said "read the picture" and
#   left the reader to work the legend out. This one says the bands are the
#   nesting level, the green number is the literal line number, and the red
#   number beside it is the literal count of indent spaces.
#
#   It says the run is a benchmark of how well the reader reproduces the file.
#
#   It drops the line count and the character count. The old brief told the
#   reader the file has N lines and M characters, which hands it a check the
#   page does not carry.
#
#   It drops "Write the file once". MEASURED 11 September 2026: Opus read the
#   picture TWICE and scored 1.0000, Sonnet read once and scored 0.7881, and
#   the turn Opus spent on its second read carried 6,333 thinking tokens. So
#   telling a reader to look again is the difference the bench found.
BRIEF = """This is a benchmark to see how well you can rebuild the text file from an image of the literal text in the text file.
Color coding is added to the images to help you recreate the file from the image.
Green numbers inside a black square outline are the text files literal line number. If that line has indent spaces a red number appears next to it showing the number of literal spaces.

Read this file with the Read tool, giving it only the path:
%(source)s

Rebuild the text file and format identically from the image.

When you are done write write the file into this path:
%(out)s and reply with one line saying done
"""


def read(path):
    return io.open(path, encoding="utf-8", newline="").read()


def resolve(rel):
    return rel if os.path.isabs(rel) else os.path.join(REPO, rel)


# An arena is a bare folder outside the repository, so it inherits no project
# settings, and densepack is not enabled at user scope. A leg run in an arena
# without this file loads no plugin, no hook fires, Read returns the raw text
# and the reader rebuilds the file from the text it was handed.
#
# MEASURED 10 September 2026: five rebuild legs scored 1.0000 that way, on
# ab_run.py, cache_watch.py, MATH.md, baby.gd and new_account.html. Every one
# was a copy, not a read. Of the 60 arenas under ab-benches only ab-fresh
# carried this file. build() writes it now so no arena can score a page it
# was never shown.
ARENA_SETTINGS = '{\n  "enabledPlugins": {\n    "densepack@densepack-marketplace": true\n  }\n}\n'


def arena_settings(arena):
    """Enable the plugin inside the arena and say where it landed."""
    folder = os.path.join(arena, ".claude")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "settings.json")
    io.open(path, "w", encoding="utf-8", newline="").write(ARENA_SETTINGS)
    return path


def build(args, show_command=True):
    source = resolve(args.file)
    src = read(source)
    os.makedirs(args.arena, exist_ok=True)
    settings_path = arena_settings(args.arena)
    maxpack_on(args.arena)
    for stale in ("rebuild.txt",):
        p = os.path.join(args.arena, stale)
        if os.path.isfile(p):
            os.remove(p)
    out = os.path.join(args.arena, "rebuild.txt")
    task = BRIEF % {"source": source, "out": out,
                    "lines": len(src.split("\n")) - 1, "chars": len(src)}
    io.open(os.path.join(args.arena, "task.txt"), "w", encoding="utf-8",
            newline="").write(task)
    print("arena  : %s" % args.arena)
    print("source : %s" % source)
    print("chars  : %d" % len(src))
    print("lines  : %d" % (len(src.split("\n")) - 1))
    print()
    if show_command:
        print("now run, from the arena:")
        print("  claude -p --model <model id> --tools Read,Write "
              "--allowedTools Read,Write < task.txt")


# The score of the last rebuild score() checked, so run() can save it in the rows.
LAST_SCORE = {}

SAMPLES = ("bench/byte-identical-rebuild/samples/ab_run.py",
           "bench/byte-identical-rebuild/samples/MATH.md",
           "bench/byte-identical-rebuild/samples/new_account.html")


def run(args):
    """Build, run and score one rebuild per sample file for one reader, and
    print the cost of each leg from the claude JSON result."""
    import json
    import subprocess
    short = args.model.replace("claude-", "").split("-")[0]
    files = [args.file] if args.file != SAMPLES[0] else list(SAMPLES)
    rows = []
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        arena = arena_root("rebuild", "%s-%s-%s" % (args.bench, short, stem))
        a = argparse.Namespace(file=f, arena=arena)
        build(a, show_command=False)
        with io.open(os.path.join(arena, "task.txt"), encoding="utf-8") as task, \
                io.open(os.path.join(arena, "result.json"), "w", encoding="utf-8") as out:
            # The installed plugin is switched off, and the rebuild loads this
            # download's own plugin folder, so the bench measures the plugin that ships.
            cmd = ["claude", "-p", "--output-format", "json", "--model", args.model,
                   "--tools", "Read,Write", "--allowedTools", "Read,Write",
                   "--settings", os.path.join(REPO, "bench", "settings", "off-plugin.json"),
                   "--plugin-dir", os.path.join(REPO, "plugin")]
            # DENSEPACK_BENCH_EFFORT, from 13 September 2026: the same
            # passthrough bench/run_bench_arm.py has, so a rebuild round runs at
            # the effort level the session names. Unset, the leg inherits
            # the machine's setting. The thinking budget stays unset here.
            # A run with MAX_THINKING_TOKENS=0 in the working repository
            # dropped a line of code on this bench.
            effort = os.environ.get("DENSEPACK_BENCH_EFFORT")
            if effort:
                cmd += ["--effort", effort]
            # No shell: a list with shell=True runs only "claude" on Linux and macOS.
            import shutil
            cmd[0] = shutil.which(cmd[0]) or cmd[0]
            subprocess.call(cmd, stdin=task, stdout=out, cwd=arena)
        print("=== %s %s" % (short, os.path.basename(f)))
        score(a)
        try:
            j = json.load(io.open(os.path.join(arena, "result.json"), encoding="utf-8-sig"))
        except (OSError, ValueError):
            j = {}
        u = j.get("usage") or {}
        row = {"bench": args.bench, "model": args.model, "file": f, "arena": arena,
               "cost": j.get("total_cost_usd"), "turns": j.get("num_turns"),
               "output": u.get("output_tokens"),
               "thinking": (u.get("output_tokens_details") or {}).get("thinking_tokens"),
               "cache_write": u.get("cache_creation_input_tokens"),
               "cache_read": u.get("cache_read_input_tokens"), **LAST_SCORE}
        print("cost %s  turns %s  output %s  thinking %s  cache write %s  cache read %s"
              % (row["cost"], row["turns"], row["output"], row["thinking"],
                 row["cache_write"], row["cache_read"]))
        rows.append(row)
    rows_path = os.path.join(REPO, "bench", "rows", "rebuild-%s-rows.jsonl" % args.bench)
    os.makedirs(os.path.dirname(rows_path), exist_ok=True)
    with io.open(rows_path, "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print("rows appended to %s" % rows_path)
    return 0


def score(args):
    source = resolve(args.file)
    got_path = os.path.join(args.arena, "rebuild.txt")
    if not os.path.isfile(got_path):
        print("no rebuild.txt in %s" % args.arena)
        return 1
    raw_key = read(source)
    raw_got = read(got_path)

    # A line ending cannot be drawn. CRLF and LF put the same marks on the
    # page, so a reader has no way to tell them apart and writes whatever its
    # own platform uses. Measured 9 September 2026 on plugin/scripts/
    # cache_watch.py: the source holds 148 CRLF, the rebuild 148 LF, and the
    # two are identical once normalised. That is the medium, not a misread,
    # so the comparison runs on normalised text and the endings are reported
    # on their own line.
    key = raw_key.replace("\r\n", "\n")
    got = raw_got.replace("\r\n", "\n")

    print("source  : %d characters, %d lines"
          % (len(key), len(key.split("\n")) - 1))
    print("rebuild : %d characters, %d lines"
          % (len(got), len(got.split("\n")) - 1))
    src_crlf, got_crlf = raw_key.count("\r\n"), raw_got.count("\r\n")
    print()

    # The headline is the strict comparison, against the bytes on disk. A
    # bench that quietly normalises is the same fault as the stripped ratio
    # of a whitespace-stripped ratio: it reports a pass the file does not have.
    strict = raw_key == raw_got
    print("BYTE IDENTICAL : %s" % ("yes" if strict else "no"))
    print("  bytes        : source %d, rebuild %d, difference %d"
          % (len(raw_key), len(raw_got), abs(len(raw_key) - len(raw_got))))

    identical = key == got
    if not strict and identical:
        print("  cause        : line endings only. The source holds %d CRLF "
              "and the rebuild %d." % (src_crlf, got_crlf))
        print("                 Every other character matches. A page draws no "
              "line ending, so a")
        print("                 reader cannot see which kind a file uses and "
              "writes its own.")
        print("  content      : identical, %d characters" % len(key))
    ratio = difflib.SequenceMatcher(None, key, got).ratio()
    print("ratio          : %.4f" % ratio)

    kl, gl = key.split("\n"), got.split("\n")
    both = min(len(kl), len(gl))

    blank_k = [n for n, l in enumerate(kl, 1) if l == ""]
    blank_g = [n for n, l in enumerate(gl, 1) if l == ""]
    print("blank lines    : %d in the source, %d in the rebuild, %s"
          % (len(blank_k), len(blank_g),
             "same places" if blank_k == blank_g else "DIFFERENT places"))

    checked = right = 0
    wrong = []
    for i in range(both):
        if not kl[i].strip():
            continue
        ki = len(kl[i]) - len(kl[i].lstrip(" "))
        gi = len(gl[i]) - len(gl[i].lstrip(" "))
        checked += 1
        if ki == gi:
            right += 1
        elif len(wrong) < 10:
            wrong.append((i + 1, ki, gi, kl[i].strip()[:40]))
    print("indent         : %d of %d lines correct" % (right, checked))
    for n, ki, gi, txt in wrong:
        print("    line %-4d source %-3d rebuild %-3d  %s" % (n, ki, gi, txt))

    exact = sum(1 for i in range(both) if kl[i] == gl[i])
    print("lines exact    : %d of %d, nothing stripped" % (exact, both))
    print()
    LAST_SCORE.update(ratio=round(ratio, 4), byte_identical=strict, same_text=identical,
                      lines_exact=exact, lines=both, indent_right=right, indent_checked=checked)
    if strict:
        print("BYTE IDENTICAL")
    elif identical:
        print("SAME TEXT, only the line endings differ")
    else:
        print("NOT IDENTICAL: ratio %.4f, %d of %d lines exact" % (ratio, exact, both))
    return 0 if strict else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("verb", choices=("build", "score", "run"))
    ap.add_argument("--file", default=SAMPLES[0],
                    help="the file to rebuild, relative to the repository")
    ap.add_argument("--arena", default=arena_root("rebuild", "rebuild-1"),
        help="a folder outside the repository holding task.txt and rebuild.txt")
    ap.add_argument("--model", default="claude-opus-5", help="run: the reader")
    ap.add_argument("--bench", default="v18", help="run: a name for the rows file and the arenas")
    args = ap.parse_args()
    return {"build": build, "score": score, "run": run}[args.verb](args) or 0


if __name__ == "__main__":
    sys.exit(main())
