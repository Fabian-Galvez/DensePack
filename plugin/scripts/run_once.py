"""Runs a DensePack hook script, but only when python3 cannot do it.

WHY THIS FILE EXISTS, in plain words.

DensePack's hooks used to be POSIX shell one-liners that chose between the two
names Python ships under. That needs a shell, and Claude Code could not always
find one. Measured 20 August 2026 on a machine that HAS Git for Windows
installed, under AppData\\Local\\Git:

    requires bash but Git Bash was not found

and where it fell back to PowerShell 5.1 by itself:

    The token '||' is not a valid statement separator in this version

Either way every hook died. The fix is exec form, which takes an argument list
and spawns the executable directly with no shell at all. Exec form cannot
choose a name at run time, and no single name works everywhere:

    Windows   python 3.13.12    python3 is a Microsoft Store stub
    Ubuntu    python absent     python3 3.14.4

So each event registers both names and Claude Code runs both. On a machine with
only one real Python name the other is skipped and the work still happens. On a
machine with both, which is normal on macOS and on Linux with python-is-python3
installed, both would run and every hook would fire twice: two standing reminders,
two receipts, a brief packed twice. This file stops that. The `python` entry
calls it first, and it does nothing when python3 can do the job, because in
that case the python3 entry has it.

The trap, and the reason this is not a one line check. On Windows,
`shutil.which("python3")` finds
`AppData\\Local\\Microsoft\\WindowsApps\\python3.EXE`. That file is an app
execution alias: 0 bytes, and running it returns 9009, which is Windows for
command not found. A guard that only asked whether the file exists would decide
python3 had the job, exit, and leave the plugin completely dead on Windows.
That happened in testing before this check was written. So the probe runs
python3 and reads the exit code, and the answer is cached in .claude/tmp
because hooks fire often and a spawn per hook is a cost worth paying once.
"""
import json
import os
import runpy
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_TTL = 24 * 60 * 60


def cache_path():
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    folder = os.path.join(root, ".claude", "tmp")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return None
    return os.path.join(folder, "densepack-python3.json")


def probe_python3():
    """True when a python3 on PATH actually starts and exits cleanly."""
    found = shutil.which("python3")
    if not found:
        return False
    try:
        if os.path.getsize(found) == 0:      # the Store stub is 0 bytes
            return False
    except OSError:
        return False
    try:
        done = subprocess.run([found, "-c", "pass"],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,
                              timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def probe_key():
    """Everything the cached answer depends on, as one string.

    A clock alone is not enough. Installing a python3, or removing one,
    changes the answer the moment it happens, and the cache cannot notice
    that by waiting. Measured on this machine 22 August 2026: the cache held
    "python3 does not work" from before a python3 shim was put on PATH, so
    for the rest of the day BOTH hook entries did the work. Every report was
    written to the manifest twice and every receipt printed twice.

    Keying on the resolved path with its size and its modified time means a
    shim appearing, changing or going away throws the answer out at once.
    """
    found = shutil.which("python3")
    if not found:
        return "none"
    try:
        st = os.stat(found)
        return "%s|%d|%d" % (found, st.st_size, int(st.st_mtime))
    except OSError:
        return found


def python3_works():
    path = cache_path()
    key = probe_key()
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                row = json.load(fh)
            if (row.get("key") == key
                    and time.time() - row.get("at", 0) < CACHE_TTL):
                return bool(row.get("works"))
        except (OSError, ValueError):
            pass
    answer = probe_python3()
    if path:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"works": answer, "at": time.time(), "key": key}, fh)
        except OSError:
            pass
    return answer


def main():
    if len(sys.argv) < 2:
        return 0
    if python3_works():
        return 0                       # the python3 entry has this event

    target = os.path.join(HERE, os.path.basename(sys.argv[1]))
    if not os.path.isfile(target):
        return 0

    # The hook script reads its event from stdin and writes its answer to
    # stdout, so it runs in this process rather than in a child one.
    sys.argv = [target] + sys.argv[2:]
    try:
        runpy.run_path(target, run_name="__main__")
    except SystemExit as exc:
        return exc.code or 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
