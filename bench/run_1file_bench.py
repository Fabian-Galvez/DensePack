"""Run one bench with every leg isolated, and report what each leg received.

Each leg gets its own empty folder, so no leg inherits another's vault, record
or drop. Legs run in waves so they meet the same cache conditions, and each
one records the cache read on its own first request. run_bench_arm.py already charges
a first turn's cache reads at the write rate, so a warm prefix is priced cold:
see cold() in bench/run_bench_arm.py.

    python bench/run_1file_bench.py <bench name> <model> <task file> [--on N] [--off]
        [--tools Read] [--wave 5] [--key ...]

Example, the one file bench for Opus, one off leg and one on leg:

    python bench/run_1file_bench.py opus-one claude-opus-5 ^
        bench/single-1000-token-file/task.txt --copy-from bench/single-1000-token-file --off --on 1 ^
        --key 18054707 densepack-ab.jsonl "25 August 2026" plan_watch ^
        "name the side, on or off, and when, before or after"
"""
import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import threading
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from run_bench_arm import projects_dir_for  # noqa: E402

# DensePack-arenas/iso beside the repository, one root for every bench,
# run_bench_arm.arena_root(). DENSEPACK_ARENA_ROOT names
# another root.
from run_bench_arm import arena_root  # noqa: E402
ARENA_ROOT = arena_root("iso")
lock = threading.Lock()


def look(arena, session):
    """The images a leg received and the cache read on its first request."""
    widths, images, first = Counter(), 0, None
    path = os.path.join(projects_dir_for(arena), (session or "") + ".jsonl")
    if not os.path.exists(path):
        return widths, images, first
    from PIL import Image
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        u = (d.get("message") or {}).get("usage")
        if u and first is None:
            first = u.get("cache_read_input_tokens")
        c = (d.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if b.get("type") != "tool_result":
                continue
            inner = b.get("content")
            if not isinstance(inner, list):
                continue
            for x in inner:
                if x.get("type") == "image":
                    with Image.open(io.BytesIO(base64.b64decode(x["source"]["data"]))) as im:
                        widths[im.size[0]] += 1
                    images += 1
    return widths, images, first


def leg(args, arm, i, out_path):
    arena = os.path.join(ARENA_ROOT, args.bench, "%s-%02d" % (arm, i))
    if os.path.isdir(arena):
        shutil.rmtree(arena)
    os.makedirs(arena)
    task = args.task
    if args.copy_from:
        # the bench reads the files beside its task, so each leg takes its own
        # copy and the task file inside that copy
        for name in sorted(os.listdir(args.copy_from)):
            src = os.path.join(args.copy_from, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(arena, name))
        task = os.path.join(arena, os.path.basename(args.task))
    cmd = [sys.executable, "bench/run_bench_arm.py", task, args.model, args.bench,
           "--tools", args.tools, "--cwd", arena, "--only", arm]
    if args.key:
        cmd += ["--key"] + args.key
    if args.answers:
        cmd += ["--answers", args.answers]
    if args.scorer:
        cmd += ["--scorer", args.scorer]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    row = None
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                row = json.loads(line)
            except ValueError:
                pass
    with lock:
        if row is None:
            print("%s leg %2d FAILED %s" % (arm, i, (r.stdout[-200:] + r.stderr[-200:])), flush=True)
            return
        widths, images, first = look(arena, row.get("session"))
        row.update(arena=arena, widths=dict(widths), images=images,
                   first_cache_read=first)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print("%-3s leg %2d  valid=%s score=%s money=%s turns=%s images=%d fcr=%s"
              % (arm, i, row.get("valid"), row.get("score"), row.get("money"),
                 row.get("turns"), images, first), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bench")
    ap.add_argument("model")
    ap.add_argument("task")
    ap.add_argument("--on", type=int, default=10)
    ap.add_argument("--off", action="store_true", help="one off leg beside the first wave")
    ap.add_argument("--tools", default="Read")
    ap.add_argument("--wave", type=int, default=5)
    ap.add_argument("--key", nargs="*")
    ap.add_argument("--copy-from", default="",
                    help="a folder whose files every leg gets a fresh copy of, "
                         "for a bench that reads the files beside its task")
    ap.add_argument("--answers", default="",
                    help="the file the task writes, relative to the leg folder")
    ap.add_argument("--scorer", default="",
                    help="a command with {answers}, printing SCORE n of m")
    args = ap.parse_args()

    out_path = os.path.join(HERE, "rows", args.bench + "-rows.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    jobs = [("on", i) for i in range(1, args.on + 1)]
    waves = [jobs[i:i + args.wave] for i in range(0, len(jobs), args.wave)] or [[]]
    if args.off:
        waves[0] = [("off", 0)] + waves[0]
    for wave in waves:
        threads = [threading.Thread(target=leg, args=(args, arm, i, out_path))
                   for arm, i in wave]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        print("-- wave done --", flush=True)

    rows = [json.loads(l) for l in open(out_path, encoding="utf-8")]
    rows = [r for r in rows if r.get("arena", "").startswith(
        os.path.join(ARENA_ROOT, args.bench))]
    off = [r for r in rows if r["arm"] == "off"]
    on = [r for r in rows if r["arm"] == "on"]
    if off and on:
        m = [r["money"] for r in on]
        o = off[-1]["money"]
        mean = sum(m) / len(m)
        print("\noff  %.4f  score %s" % (o, off[-1]["score"]))
        print("on   n=%d mean %.4f  saved %.4f  %.1f per cent"
              % (len(m), mean, o - mean, 100.0 * (o - mean) / o))
        print("     each %s" % ["%.4f" % x for x in sorted(m)])
        print("     scores %s" % dict(Counter(tuple(r["score"]) for r in on)))
        print("     arenas %d  sessions %d  first cache read %s"
              % (len({r["arena"] for r in rows}), len({r["session"] for r in rows}),
                 sorted({r["first_cache_read"] for r in rows})))


if __name__ == "__main__":
    main()
