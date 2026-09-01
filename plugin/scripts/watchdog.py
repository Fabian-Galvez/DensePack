"""Catches a stalled subagent while the prompt cache is still warm.

HOW THIS FILE FITS, in plain words: stop_gate.py refuses to let the lead's
reply land while an agent has gone silent, through common.stale_agents(),
but that check runs only inside the Stop hook, the moment the lead is about
to hand its turn back. A background agent between its spawn and its own
stop fires no hooks at all, so a real stall in that gap went unseen for
twenty five minutes once tonight and an hour another time, both past the
five minute life of the prompt cache, so the eventual nudge re-read the
whole conversation at full price instead of resuming a warm one.

FIXED 30 August 2026, alongside common.stale_agents(): quiet used to mean
time since the agent started, not time since it last did anything, and two
agents that were working the whole time, files on disk, transcript still
growing, were reported dead for running long. Both this file and
stale_agents() now call the one shared function, common.last_activity(),
so a slow but working agent reads as alive in both places.

WHAT IT DOES. subagent_start.py launches this file as a detached process
the moment the first background agent of a session spawns; maybe_launch()
below is the one entry point, and it is a no-op when a watchdog for that
session already has a fresh heartbeat. The detached process wakes every
WAKE_SECONDS, reads common.unfinished_agents() for the agents this session
is still waiting on, and for each one reads common.last_activity(), the
newest of its transcript file's mtime and its start time: one stat() call
per agent, not a read of the file's contents, since a poll every two to
three minutes cannot afford to parse a transcript the way cache_watch.py
parses the lead's own, much smaller one. An agent with no activity for
QUIET_AFTER seconds is stalled.

A stall is recorded once, to watchdog_path(), the same append-only jsonl
shape bash_pack.py uses for densepack-pending.jsonl: one row in, never
rewritten. The record names the signal, the transcript's own last-activity
age, and the last file the agent wrote or edited with its own age, from
common.last_touched_file(), read only for this one flagged agent, never on
the hot path that checks every live agent every wake. stop_gate.py reads
watchdog_path() at the lead's next Stop event and folds any new row into
the block reason it already sends, so the lead learns about a stall
through the channel it already listens to, with the record sitting there
from minutes earlier instead of computed cold at that moment.

WHAT IT NEVER DOES. It never resumes a stalled agent and never kills one.
Catching a stall early only saves the cache-warm resume the header above
describes if a person watching tools/live_dashboard.py acts on the record
before the cache lapses; nudging a stalled agent is a decision this file
leaves to that person or to the lead, never to itself.

WHEN IT STOPS. Every wake it also asks whether unfinished_agents() is now
empty for its session. The moment it is, this process deletes its own
heartbeat file and exits. Nothing else stops it: no fixed lifetime and no
cron; a poller with no exit condition runs for money once nothing is left
to watch, the one shape this file must never take.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (disabled, last_activity, last_touched_file, tmp_dir,
                    unfinished_agents)

# Two to three minutes, the stated interval. The short end is used so
# QUIET_MISSES wakes below land inside the five minute prompt cache life
# (SHORT_TTL in cache_watch.py) with margin left over; the middle or long
# end would not leave that margin at two missed wakes.
WAKE_SECONDS = 120

# An agent must show no activity across two full wakes, not one, before it
# is called stalled: a single quiet wake between tool calls is normal for a
# working agent. Two wakes at 120 seconds is 240 seconds, inside the five
# minute cache window with 60 seconds left for this poll's own work and for
# a person to read the record and act before the cache lapses.
QUIET_MISSES = 2
QUIET_AFTER = WAKE_SECONDS * QUIET_MISSES

# Heartbeat freshness that counts as "a watchdog is already alive for this
# session". Three wake periods, not one, so a watchdog caught mid-sleep by
# maybe_launch() still reads as alive and a slow wake under load does not
# cause a second watchdog to start on top of the first.
HEARTBEAT_STALE_AFTER = WAKE_SECONDS * 3

# The tail of an agent transcript delivered_report() reads. Same size
# common.last_touched_file() reads, and for the same reason: it holds
# thousands of lines, far more than one agent writes in one turn.
TAIL_BYTES = 200000


def _short(session):
    return (str(session or "x"))[:8]


def heartbeat_path(session):
    return tmp_dir() / ("densepack-watchdog-%s.heartbeat" % _short(session))


def watchdog_path():
    return tmp_dir() / "densepack-watchdog.jsonl"


def watchdog_off():
    """A second, narrower off switch than common.disabled(), for a single
    problem that switch cannot solve: a test that invokes subagent_start.py
    directly, to check the pointer text or the start marker it writes,
    never runs subagent_stop.py or writes the manifest row that would let a
    real launched watchdog exit. Full plugin-off is the wrong tool there,
    since those tests are checking plugin behavior WITH the plugin on.
    tmp_dir() / densepack-watchdog-off, set once by such a test alongside
    its sandbox, stops only the launch in maybe_launch() and nothing else
    DensePack does. Not a slash command: no session that spawns a real
    background agent should ever want this file to exist.
    """
    return (tmp_dir() / "densepack-watchdog-off").exists()


def watchdog_alive(session):
    """True when a watchdog for this session touched its heartbeat inside
    HEARTBEAT_STALE_AFTER. A missing file, or one older than that, means no
    watchdog is running for this session right now."""
    path = heartbeat_path(session)
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age <= HEARTBEAT_STALE_AFTER


def touch_heartbeat(session):
    heartbeat_path(session).write_text(str(time.time()), encoding="utf-8")


def already_recorded(agent_id):
    """True when watchdog_path() already carries a row for this agent id.
    Read once per newly-stalled agent, never on the hot path."""
    path = watchdog_path()
    if not path.is_file():
        return False
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if str(row.get("agent_id")) == str(agent_id):
                    return True
    except OSError:
        return False
    return False


def record_stall(session, agent_id, quiet_seconds, started, now):
    """Append one row for this agent's stall, unless one is already on
    file. Matches bash_pack.py's append_pending(): open, append, close,
    never rewritten, so a crash mid-write loses at most this one row.

    file_path and file_age_seconds name the last file this agent wrote or
    edited, read here from common.last_touched_file() because this is the
    one place that call is worth its cost: a single flagged agent, not
    every live agent on every wake.
    """
    if already_recorded(agent_id):
        return
    file_path, file_when = last_touched_file(agent_id)
    row = {
        "session": str(session or ""),
        "agent_id": str(agent_id),
        "signal": "transcript_mtime",
        "quiet_seconds": round(quiet_seconds, 1),
        "started": started,
        "detected_at": now,
        "last_file": file_path,
        "last_file_ago_seconds":
            round(now - file_when, 1) if file_when else None,
    }
    with watchdog_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def stall_row(session, agent_id):
    """The watchdog's own record for this session and agent id, or None.
    Read by stop_gate.py at the lead's next Stop event, so the block
    reason it already sends can name the last file this agent touched
    instead of only a duration, without stop_gate.py running its own copy
    of last_touched_file()."""
    path = watchdog_path()
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (str(row.get("session")) == str(session or "") and
                        str(row.get("agent_id")) == str(agent_id)):
                    return row
    except OSError:
        return None
    return None


def agent_transcript(agent_id):
    """This agent's own transcript file, agent-<id>.jsonl, or None when no
    such file exists yet. Same glob and same home as
    common.agent_transcript_mtime(), which returns that file's mtime and not
    its path, so the path is looked up again here.
    """
    if not agent_id or agent_id == "unknown":
        return None
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return None
    for path in root.glob("*/*/subagents/agent-%s.jsonl" % agent_id):
        return path
    return None


def delivered_report(agent_id):
    """True when this agent's transcript ends on a plain assistant message:
    text blocks and no tool call. A subagent finishes by writing exactly that
    row, so the row is the report it handed back, and a start marker still on
    disk beside it is a leftover rather than a live agent.

    False when no transcript exists, when the last message still holds a tool
    call, and when DensePack has blocked this agent: a blocked agent's last
    message is text too, and it is the message that got refused, not a
    delivery. The marker alone never decides either way, which is the point:
    a SubagentStop hook that never ran leaves the same marker a crash does.

    Reads the last TAIL_BYTES only, the size common.last_touched_file() reads,
    because a transcript can pass a hundred megabytes and this runs on a poll.
    """
    if (tmp_dir() / ("densepack-blocked-%s" % agent_id)).exists():
        return False
    path = agent_transcript(agent_id)
    if path is None:
        return False
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - TAIL_BYTES))
            tail = fh.read()
    except OSError:
        return False
    for line in reversed(tail.decode("utf-8", "replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            # The first line of the tail is cut mid-record. Skip it.
            continue
        if not isinstance(row, dict) or row.get("type") != "assistant":
            continue
        blocks = (row.get("message") or {}).get("content")
        if not isinstance(blocks, list) or not blocks:
            continue
        kinds = set(b.get("type") for b in blocks if isinstance(b, dict))
        return "tool_use" not in kinds and "text" in kinds
    return False


def clear_marker(agent_id):
    """Delete the start marker a finished agent left behind. subagent_stop.py
    deletes it on every normal stop, so this only ever fires for the stop hook
    that did not run: one crash used to leave a marker that raised a false
    stall on every later wake for the rest of the session.
    """
    try:
        (tmp_dir() / ("densepack-start-%s" % agent_id)).unlink()
    except OSError:
        pass


def check_once(session, now=None):
    """One wake: read who this session is still waiting on, record a stall
    for anyone quiet past QUIET_AFTER that has not already been recorded.

    Stateless between wakes on purpose: common.last_activity() reads the
    transcript file's own mtime, an absolute timestamp the filesystem
    already keeps, so no memory of the previous wake's reading has to be
    carried here to know how long an agent has been quiet.

    Returns (still_live_ids, newly_stalled_ids).
    """
    when = time.time() if now is None else now
    live = unfinished_agents(session, now=when)
    still_live = []
    newly_stalled = []
    for agent_id, started in live:
        quiet = when - last_activity(agent_id, started)
        # An agent that has been quiet this long has either delivered and lost
        # its stop hook, or hung. Its transcript says which; the marker cannot.
        if quiet >= QUIET_AFTER and delivered_report(agent_id):
            clear_marker(agent_id)
            continue
        still_live.append(agent_id)
        if quiet < QUIET_AFTER:
            continue
        if already_recorded(agent_id):
            continue
        record_stall(session, agent_id, quiet, started, when)
        newly_stalled.append(agent_id)
    return still_live, newly_stalled


def run_loop(session):
    """The detached process's own body. Wakes, checks, sleeps, exits the
    moment nothing is left to watch. No other exit condition exists."""
    while True:
        if disabled(session):
            return
        touch_heartbeat(session)
        still_live, _newly = check_once(session)
        if not still_live:
            try:
                heartbeat_path(session).unlink(missing_ok=True)
            except OSError:
                pass
            return
        time.sleep(WAKE_SECONDS)


def maybe_launch(session):
    """Start a detached watchdog for this session, unless one is already
    alive or the plugin is off. Called from subagent_start.py on every
    spawn; watchdog_alive() is what keeps a second copy from starting on
    top of the first on a later spawn in the same session. This is the
    only place that starts a watchdog: subagent_start.py already fires on
    every spawn and records per-session state, and this reuses that
    instead of adding a second trigger.
    """
    if disabled(session):
        return False
    if watchdog_off():
        return False
    if not session:
        return False
    if watchdog_alive(session):
        return False
    script = str(Path(__file__).resolve())
    log_path = tmp_dir() / ("densepack-watchdog-%s.log" % _short(session))
    kwargs = dict(stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    # Written before the process starts: a launch slow to schedule must
    # still read as handled to the very next spawn's own maybe_launch()
    # call a moment later, or two watchdogs start for the same session.
    touch_heartbeat(session)
    try:
        # The log file handle is opened and closed in this same "with", so
        # this short-lived hook process never holds it open; the detached
        # child gets its own duplicate of the handle from Popen and keeps
        # that one for as long as it runs.
        with open(log_path, "a", encoding="utf-8") as log_fh:
            subprocess.Popen(
                [sys.executable, script, "--run", "--session", str(session)],
                stdout=log_fh, **kwargs)
    except OSError:
        try:
            heartbeat_path(session).unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true",
                         help="Run the wake loop in this process. What "
                              "maybe_launch() passes to the detached copy.")
    parser.add_argument("--session", default="")
    args = parser.parse_args(argv)
    if args.run:
        run_loop(args.session)
        return 0
    # No flags: one wake, printed as JSON, for a human or a test checking
    # the signal without waiting out a real loop.
    still_live, newly = check_once(args.session)
    print(json.dumps({"live": still_live, "newly_stalled": newly}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
