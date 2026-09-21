"""Prices both routes before a delegation rule fires, and caps how often one
rule may fire in a session.

HOW THIS FILE FITS, in plain words: delegate_gate.py and agent_floor.py both
push the lead to spawn a subagent. Spawning is not free. This file holds the
two checks that stop either gate firing when firing costs more than it saves.

MECHANISM 1, THE PRICED STAND-DOWN. Every number below is already measured
somewhere in this plugin and is copied here with the line it came from. None
of them is new.

  agent_floor.py:14   two lead turns                    823,098 tokens
  agent_floor.py:15   a packed brief, report and call     1,870 tokens
  agent_floor.py:16   what one moved command removes    340,000 tokens, mean
  agent_floor.py:17   break-even                           2.42 commands

That 2.42 is the break-even for a command whose output rides the lead's
conversation as plain text. With this plugin on, it does not. common.py:88-93
measures a packed image at 0.11 to 0.14 of its text at 8 px, 0.21 to 0.24 at
10 px and 0.30 to 0.33 at 12 px, and common.py:104-105 measures the pointer
that rides beside it at 52 tokens for the report route and 60 for the bash
route. So the same command, delivered packed, costs the lead

    340,000 * packed share + pointer fee

and the break-even in commands is (823,098 + 1,870) divided by that. At the
Opus reader's 10 px and the worst measured share, 0.24, that is 81,660 tokens
a command and 10.1 commands to break even, not 2.42. Packing already took the
cheap work off the lead, so a spawn has four times as much to pay back.

WHICH SHARE IS USED. The high end of each measured range, and the larger of
the two pointer fees. Those are the values that price the direct route
highest, which is the side that keeps a gate firing. A stand-down has to be
earned by the measurement, never granted by rounding.

WHAT COUNTS AS PACKED. Only a call this plugin can show it would pack: a Read
of a file that exists and is at least common.stub_chars() long, or an
inspection command naming such a file at least common.bash_chars() long. A
call whose output size cannot be known before it runs is priced unpacked, at
the full 340,000, because an unproven saving is not a saving.

MECHANISM 2, THE INTERVENTION CAP. A gate that has already fired twice in one
session on the same rule stops firing for that session. Each repeat costs the
lead a whole turn re-reading the conversation, 411,549 tokens on the mean at
agent_floor.py:12, and a rule the lead has read twice and not followed will
not be followed on the third telling either.

WHERE THE STATE LIVES. Two JSON files beside the streak counter in tmp_dir(),
one session id to one number, the same per-session shape delegate_gate.py
already uses for STREAK_FILE.

WHAT IT NEVER TOUCHES. A session with no transcript on disk is never capped.
Without a transcript the counter cannot tell one session from a fresh one, and
a wrong cap silences a gate that never fired.
"""

import json
import os

from common import bash_chars, font_size, stub_chars, tmp_dir, transcript_path

# agent_floor.py:14. Two lead turns, what a spawn costs whatever it does.
TWO_LEAD_TURNS = 823098

# agent_floor.py:15. The packed brief out, the packed report back, the call.
BRIEF_CALL_REPORT = 1870

# agent_floor.py:16. What moving one command off the lead removes, mean.
MOVED_COMMAND = 340000

# common.py:88-93. What a packed image measures against its own text, per
# drawing size. The high end of each measured range, so the direct route is
# never priced cheaper than it was measured.
PACKED_SHARE_BY_PX = {8: 0.14, 10: 0.24, 12: 0.33}

# common.py:104-105. The pointer that rides beside the image every turn:
# report 52 tokens, bash 60. The larger one, for the same reason.
POINTER_TOKENS = 60

# The brief's own words: a gate that has fired twice on one rule in one
# session stops repeating for that session.
FIRE_CAP = 2

COST_FILE = "densepack-gate-cost.json"
FIRES_FILE = "densepack-gate-fires.json"


def delegate_price():
    """What one spawn costs the lead, whatever the agent then does."""
    return TWO_LEAD_TURNS + BRIEF_CALL_REPORT


def packed_share():
    """What a packed image measures against its text, for the reader in use."""
    return PACKED_SHARE_BY_PX.get(font_size(), PACKED_SHARE_BY_PX[10])


def command_price(packed):
    """What one hands-on call costs the lead, packed or plain."""
    if packed:
        return MOVED_COMMAND * packed_share() + POINTER_TOKENS
    return float(MOVED_COMMAND)


def break_even_commands():
    """How many packed calls a spawn has to carry back before it pays."""
    return delegate_price() / command_price(True)


def _sized(path, floor):
    try:
        return os.path.isfile(path) and os.path.getsize(path) >= floor
    except OSError:
        return False


def would_pack(tool, tool_input):
    """True only when this plugin can show it would pack this call's content."""
    try:
        if tool == "Read":
            return _sized(str(tool_input.get("file_path") or ""), stub_chars())
        if tool in ("Bash", "PowerShell"):
            command = str(tool_input.get("command") or "")
            floor = bash_chars()
            for word in command.replace("\n", " ").split():
                word = word.strip("'\"")
                if word and _sized(word, floor):
                    return True
            return False
    except Exception:  # noqa: BLE001
        return False
    return False


def _read(name):
    try:
        data = json.loads((tmp_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(name, data):
    try:
        (tmp_dir() / name).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def add_direct(session_id, tokens, keep):
    """Add this call's direct price to the session's running total."""
    data = _read(COST_FILE)
    total = data.get(session_id)
    if not isinstance(total, (int, float)) or total < 0:
        total = 0.0
    total += tokens
    data[session_id] = total
    _write(COST_FILE, {k: v for k, v in data.items() if k in keep})
    return total


def clear_direct(session_id, keep):
    """Forget the running total, for when the streak it priced is reset."""
    data = _read(COST_FILE)
    data.pop(session_id, None)
    _write(COST_FILE, {k: v for k, v in data.items() if k in keep})


def forget(session_id):
    """Drop every priced total and fire count, for a reset of all gate state."""
    for name in (COST_FILE, FIRES_FILE):
        data = _read(name)
        if data.pop(session_id, None) is not None:
            _write(name, data)


def cheaper_direct(direct_total):
    """True when doing this work in the lead costs less than one spawn."""
    return direct_total < delegate_price()


def _cappable(session_id):
    if not session_id:
        return False
    try:
        path = transcript_path(session_id)
    except Exception:  # noqa: BLE001
        return False
    return bool(path and path.is_file())


def capped(session_id, rule):
    """True when this rule has already fired its cap in this session."""
    if not _cappable(session_id):
        return False
    return _read(FIRES_FILE).get("%s|%s" % (session_id, rule), 0) >= FIRE_CAP


def record_fire(session_id, rule):
    """Count one firing of this rule in this session."""
    if not _cappable(session_id):
        return
    key = "%s|%s" % (session_id, rule)
    data = _read(FIRES_FILE)
    count = data.get(key, 0)
    data[key] = (count if isinstance(count, int) and count >= 0 else 0) + 1
    _write(FIRES_FILE, data)
