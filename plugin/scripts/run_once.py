"""Runs a DensePack hook script once per event, under whichever Python works.

WHY THIS FILE EXISTS, in plain words.

Every DensePack hook entry in hooks.json starts run_hook.sh, which picks a
working Python and runs this file. This file runs the hook script once per
event.

It creates one marker file for the event, with O_CREAT and O_EXCL. The first
process whose create succeeds runs the hook script, and any other process for
the same event exits. The plugin loaded twice, from an install and from
--plugin-dir, still does the work once.

WHY THE MARKER IS WRITTEN HERE AND NOT INSIDE THE HOOK SCRIPT.

Some hook scripts exit before they read the event. pointer.py answers a Read
event without loading common.py. A marker written inside the scripts would
never appear for those events. Written here, before the script is loaded,
the marker appears for every event.
"""
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import time

# Pillow 12, which the plugin installs, has no wheel under Python 3.10, so an
# older Python runs no hook and stays silent. ensure_python.sh and
# ensure_python.ps1 tell the user at session start.
if sys.version_info < (3, 10):
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))

MARKER_PREFIX = "densepack-ran-"



def read_stdin():
    """The event as text, read once here and handed to the script later."""
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        return sys.stdin.read()
    except (OSError, ValueError, UnicodeDecodeError):
        return ""


def marker_path(raw, target=None):
    """Where this one event's marker goes, the same answer in both entries.

    The name carries the session and a short hash of the whole event, so two
    different events never share a marker and the two entries handling one
    event always agree on the name. The folder is the one the plugin prunes.
    """
    if not raw:
        return None
    try:
        import hashlib
        import re
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import common
        event = json.loads(raw)
        if not isinstance(event, dict):
            return None
        common.note_event_cwd(event)
        session = re.sub(r"[^A-Za-z0-9_-]", "",
                         str(event.get("session_id") or ""))[:36]
        # The script name is part of the marker. Every PreToolUse Read gate
        # receives the same event bytes, so a marker named by the event alone
        # would let the first gate run and skip the others.
        digest = hashlib.sha1((raw + "|" + os.path.basename(str(target or "")))
                              .encode("utf-8", "replace")).hexdigest()[:12]
        return os.path.join(str(common.tmp_dir()),
                            MARKER_PREFIX + (session or "none") + "-" + digest)
    except Exception:
        # Any failure here means the two entries cannot agree on a name, so
        # the caller falls back to running the script. A hook done twice is
        # a smaller fault than a hook not done at all.
        return None


def claim_marker(path):
    """True for exactly one caller per marker path: the one whose create
    succeeds. os.open with O_CREAT and O_EXCL is atomic on Windows, Linux
    and macOS, so two entries racing for one event cannot both win. A
    folder that cannot be written returns True, so the script still runs."""
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except OSError:
        return True
    try:
        os.write(handle, b"ran\n")
    finally:
        os.close(handle)
    sweep_stale_markers(os.path.dirname(path))
    return True


STALE_MARKER_SECONDS = 3600


def sweep_stale_markers(folder, every=200):
    """One claim in `every` deletes run markers older than an hour.

    A marker is claimed within milliseconds of its event and never read
    again, but bootstrap.py prunes only at session start, so a session that
    runs for a day piles up tens of thousands of them, and a listing of
    .claude/tmp slows every Bash call. The sweep is a scandir of the folder,
    about a twentieth of a second at a few thousand files, taken once in two
    hundred claims.
    """
    import random
    import time
    if random.randrange(every):
        return
    cutoff = time.time() - STALE_MARKER_SECONDS
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if not entry.name.startswith(MARKER_PREFIX):
                    continue
                try:
                    if entry.stat().st_mtime < cutoff:
                        os.unlink(entry.path)
                except OSError:
                    continue
    except OSError:
        return


def run(target, raw, rest):
    """Run the hook script in this process, with the event put back on stdin."""
    sys.argv = [target] + rest
    sys.stdin = io.StringIO(raw)
    try:
        runpy.run_path(target, run_name="__main__")
    except SystemExit as exc:
        return exc.code or 0
    return 0


def main():
    args = sys.argv[1:]
    # --first and --second are stripped rather than rejected, so an old
    # hooks.json still runs.
    if args and args[0] in ("--first", "--second"):
        args = args[1:]
    if not args:
        return 0
    target = args[0]
    if not os.path.isfile(target):
        target = os.path.join(HERE, os.path.basename(target))
    if not os.path.isfile(target):
        return 0
    raw = read_stdin()
    marker = marker_path(raw, target)
    # One claim, no clock. Both entries try to CREATE the event's marker
    # with O_EXCL: the one that creates it runs the script, the other exits.
    # A bounded wait fails under load, when parallel Reads start hundreds of
    # hook processes at once. With no marker name at all, no session id or
    # an unreadable event, both entries run, because a hook done twice is a
    # smaller fault than a hook not done.
    if marker is not None and not claim_marker(marker):
        return 0
    return run(target, raw, args[1:])


def guarded_main():
    """Never let an exception out of this hook.

    main() runs inside a try, so a fault in it cannot change the outcome of
    the tool call that fired the hook. The error is written to stderr so the
    fault is still visible. The exit code stays 0, which lets the call
    through.
    """
    try:
        return main()
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack %s: %s\n" % ("run_once.py", err))
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
