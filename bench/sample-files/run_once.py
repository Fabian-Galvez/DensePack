"""Runs a DensePack hook script once per event, under whichever Python works.

WHY THIS FILE EXISTS, in plain words.

Every DensePack hook is registered twice in hooks.json, once under the name
python3 and once under the name python, because no one name for the
interpreter exists on every machine. Both entries run this file.

The first entry is told --first. It writes a small marker file for the event
it was given, then runs the hook script. The second entry is told --second.
It looks for that marker, and runs the hook script itself only when the
marker never appears, which is the sign that the first entry never started.
So the work happens once when either name works, and once when only one does.

WHAT WENT WRONG BEFORE, twice.

22 August 2026: both entries did the work all day. Every agent report went
into the manifest twice and every receipt printed twice. The cause was a
cached probe answer from before a python3 shim was put on PATH.

3 September 2026: the opposite failure. A whole session packed nothing,
printed nothing and reported no error. The probe said python3 works, because
it ran the file shutil.which() had returned, a .CMD shim in the user's own
bin folder, and that file does run. The hook runner never runs that file. It
spawns the bare name python3, and a bare name is resolved by appending .exe
only, which finds the Microsoft Store stub in WindowsApps. That stub prints
"Python was not found" and exits 9009. Measured on a Windows machine that
day: the shim printed the version, the bare name exited 9009. So the probe
below runs the bare name, which is the same question the hook runner asks.

WHY A MARKER AND NOT A PROBE ALONE.

A probe is a guess about the next event. The marker is a fact about this one.
A python3 that stops working between two events now costs nothing: the second
entry waits a moment, sees no marker, and does the work itself. The probe is
kept only to answer, cheaply, whether the wait is worth making at all.

WHY THE MARKER IS WRITTEN HERE AND NOT INSIDE THE HOOK SCRIPT.

Because some hook scripts are built to exit before they read the event.
Measured 3 September 2026: pointer.py answers a Read event in 0.12 seconds
without ever loading common.py, which is the whole point of its early exit. A
marker written inside the scripts would never appear for those events, and
the second entry would wait the full bound on nearly every event. Written
here, before the script is loaded, the marker appears for every event and the
usual wait is a few milliseconds.
"""
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import time

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
        # The script name is part of the marker. FIXED 3 September 2026:
        # every PreToolUse Read gate receives the same event bytes, so a
        # marker named by the event alone let the first gate to claim it
        # run and skipped the other four, drop_read_gate.py among them, and
        # a Fable on arm read fourteen of sixteen files as raw text.
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
    runs for a day piles them up: 38,285 on 6 September 2026, and a listing
    of .claude/tmp took 7.6 seconds inside every Bash call. The sweep is a
    scandir of the folder, about a twentieth of a second at a few thousand
    files, taken once in two hundred claims.
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
    # --first and --second were passed here until 10 September 2026 and read
    # into a variable nothing else read. They are stripped rather than
    # rejected, so an old hooks.json still runs.
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
    # One claim, no clock. FIXED 3 September 2026, twice in one night on the
    # a Windows machine. First the probe said python3 does not run, because
    # CreateProcess finds the Store stub where the hook runner's shell finds
    # the shim, so the second entry never waited and every hook ran twice.
    # Then a bounded wait failed under load: sixteen parallel Reads start
    # about 160 hook processes at once, a first entry took longer than the
    # half second to write its marker, the second gave up and ran, and the
    # first ran after it; 40 markers stood for about 90 events and one file
    # was drawn five times. Both entries now try to CREATE the event's
    # marker with O_EXCL: the one that creates it runs the script, the
    # other exits. Order, speed and the probe's answer decide nothing.
    # With no marker name at all, no session id or an unreadable event,
    # both entries run, because a hook done twice is a smaller fault than
    # a hook not done.
    if marker is not None and not claim_marker(marker):
        return 0
    return run(target, raw, args[1:])


def guarded_main():
    """Never let an exception out of this hook.

    Security audit 3 September 2026: main() ran outside any try, so a fault
    in it could change the outcome of the tool call that fired the hook.
    Same shape as tier_gate.py, with the error written to stderr so the
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
