"""Runs a DensePack hook script once per event, with a working Python.

Each DensePack hook entry in hooks.json starts run_hook.sh. run_hook.sh finds
a working Python and runs this file. This file runs the hook script once per
event.

This file creates one marker file for the event, with O_CREAT and O_EXCL. The
first process that creates the marker runs the hook script. Each other process
for the same event exits. When Claude Code loads the plugin twice, from an
install and from --plugin-dir, the hook script still runs once.

This file writes the marker, not the hook script. Some hook scripts exit
before they read the event. pointer.py returns its output for a Read event
without loading common.py. A marker written by the hook scripts does not
appear for those events. This file writes the marker before it loads the
script, and the marker appears for each event.
"""
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import time

# The plugin installs Pillow 12, which has no wheel for Python below 3.10. An
# older Python runs no hook and prints nothing. ensure_python.sh and
# ensure_python.ps1 show the problem at session start.
if sys.version_info < (3, 10):
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))

MARKER_PREFIX = "densepack-ran-"



def read_stdin():
    """Read the event once and return it as text for the script."""
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        return sys.stdin.read()
    except (OSError, ValueError, UnicodeDecodeError):
        return ""


def marker_path(raw, target=None):
    """Return the marker path for this event. The two entries get one path.

    The name holds the session id and a short hash of the whole event. Two
    different events never share a marker. The two entries for one event
    always build the same name. The folder is the one that the plugin prunes.
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
        # The script name is part of the marker. Each PreToolUse Read gate
        # gets the same event bytes. With a marker named by the event alone,
        # the first gate runs and the others skip.
        digest = hashlib.sha1((raw + "|" + os.path.basename(str(target or "")))
                              .encode("utf-8", "replace")).hexdigest()[:12]
        return os.path.join(str(common.tmp_dir()),
                            MARKER_PREFIX + (session or "none") + "-" + digest)
    except Exception:
        # After a failure here, the two entries cannot build the same name.
        # The caller then runs the script. A hook that runs twice is a
        # smaller fault than a hook that does not run.
        return None


def claim_marker(path):
    """Return True for one caller per marker path, the caller that creates it.

    os.open with O_CREAT and O_EXCL is atomic on Windows, Linux and macOS.
    When two entries try to create the marker of one event at the same time,
    only one succeeds. When the folder is not writable, the function returns
    True and the script still runs."""
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
    """Delete run markers older than an hour, once in `every` claims.

    The hook claims a marker within milliseconds of its event and never reads
    it again. bootstrap.py prunes markers only at session start. A session
    that runs for a day can make tens of thousands of markers, and a listing
    of .claude/tmp then slows each Bash call. The sweep is one scandir of the
    folder. It takes about a twentieth of a second at a few thousand files,
    and it runs once in two hundred claims.
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
    """Run the hook script in this process, with the event on stdin again."""
    sys.argv = [target] + rest
    sys.stdin = io.StringIO(raw)
    try:
        runpy.run_path(target, run_name="__main__")
    except SystemExit as exc:
        return exc.code or 0
    return 0


def main():
    args = sys.argv[1:]
    # The code removes --first and --second and does not reject them. An old
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
    # One claim and no timer. The two entries try to create the marker of
    # the event with O_EXCL. The entry that creates it runs the script, and
    # the other exits. A timed wait fails under load, when parallel Reads
    # start hundreds of hook processes at once. With no marker name, from an
    # empty or unreadable event, the two entries run. A hook that runs twice
    # is a smaller fault than a hook that does not run.
    if marker is not None and not claim_marker(marker):
        return 0
    return run(target, raw, args[1:])


def guarded_main():
    """Catch each exception that main() raises.

    main() runs inside a try. A fault in main() cannot change the result of
    the tool call that started the hook. The hook writes the error to stderr,
    where it stays visible. The exit code stays 0, and the tool call goes on.
    """
    try:
        return main()
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack %s: %s\n" % ("run_once.py", err))
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
