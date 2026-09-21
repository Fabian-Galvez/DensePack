"""Run one on-and-off pair of a sample file bench for one reader.

    python bench/run_16file_32file_bench.py <model id> <bench name>
    python bench/run_16file_32file_bench.py <model id> <bench name> --bench thirty-two-file

A sample file bench reads every .py file in its own folder, so each leg gets a
fresh arena under DensePack-arenas/<bench folder>/<bench name>/ beside the
repository. The arena holds the files bench/<bench folder>/FILES.txt
names, copied from bench/sample-files/, and that folder's TASK.txt. The
pair then runs through bench/run_bench_arm.py with the three tools Read, Glob and
Write, the answers file and the scorer. The PAIR line ladder prints is the
result, and the rows land where every ladder run's rows land.

Written 12 September 2026, the night the bench took three reads of two
files to find the arena rule. The shared sample files and FILES.txt came on
13 September 2026, when both sets of sample files became copies of the plugin's own
scripts so that a downloaded plugin can run the bench.
"""
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_FILES = os.path.join(REPO, "bench", "sample-files")
KEYS = {"sixteen-file": "py", "thirty-two-file": "py32"}


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    model, bench = argv[1], argv[2]
    extra = argv[3:]
    folder = "sixteen-file"
    if "--bench" in extra:
        i = extra.index("--bench")
        folder = extra[i + 1]
        del extra[i:i + 2]
    key = KEYS[folder]
    here = os.path.join(REPO, "bench", folder)
    with open(os.path.join(here, "FILES.txt"), encoding="utf-8") as fh:
        names = [n.strip() for n in fh if n.strip()]
    sys.path.insert(0, os.path.join(REPO, "bench"))
    from run_bench_arm import arena_root
    # A bench name with a path in it would make the delete below reach that
    # path instead of a folder under the arena root.
    if bench != os.path.basename(bench) or "/" in bench or "\\" in bench or bench in ("", ".", ".."):
        sys.exit("The bench name must be a plain name with no folder in it: %r" % bench)
    arena = arena_root(folder, bench)
    if os.path.isdir(arena):
        shutil.rmtree(arena)
    os.makedirs(arena)
    for n in names:
        shutil.copy(os.path.join(SAMPLE_FILES, n), os.path.join(arena, n))
    shutil.copy(os.path.join(here, "TASK.txt"), os.path.join(arena, "TASK.txt"))
    print("arena  : %s, %d files" % (arena, len(names) + 1))
    cmd = [sys.executable, os.path.join(REPO, "bench", "run_bench_arm.py"),
           os.path.join(here, "TASK.txt"), model, bench,
           "--tools", "Read,Glob,Write", "--cwd", arena,
           "--answers", "answers.txt",
           "--rows", os.path.join(REPO, "bench", "rows", bench + "-rows.jsonl"),
           # Quoted, because the scorer runs as one shell command and a path can hold a space.
           "--scorer", '"%s" bench/score_16file_32file_answers.py "{answers}" %s' % (sys.executable, key)] + extra
    print("running:", " ".join(cmd[1:]))
    return subprocess.call(cmd, cwd=REPO)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
