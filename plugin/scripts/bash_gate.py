"""Sends a long, plain-prose Bash command's output to be drawn as an image.

HOW THIS FILE FITS, in plain words: the report side of this plugin draws an
agent's finished output as a small picture. Nothing on the lead's own side did
the same for a command the lead runs itself. A test run or a build can print
thousands of characters straight into the conversation, and every one of
those characters is paid for at full price. This hook looks at a Bash command
before it runs and, when its output is expected to be prose, rewrites the
command so the output lands in a file first. plugin/scripts/bash_pack.py then
turns that file into the same kind of picture the report side already draws,
given the file's path and the command's exit code as its two arguments.

It is a PreToolUse hook on the Bash tool, the same shape as source_gate.py:
Claude Code pipes in the tool call about to run, and whatever this script
returns under updatedInput becomes the call that actually runs. updatedInput
REPLACES the whole input object rather than merging into it, so every field
the event carried is sent back, exactly as source_gate.py does it. A partial
object fails schema validation with "the required parameter is missing".

WHAT NEVER GETS REWRITTEN, and why each one is on that list:

  cat, sed, head, tail, type, Get-Content, grep, awk, nl, od reading a
  project file. Their output often feeds the Edit tool's exact-match
  argument, and exact text does not survive being drawn small.
  git, any subcommand. A hash, a diff and a commit message are exact-copy
  data, the same reason as above.
  sha256sum, md5sum, certutil, base64, openssl. The output of each of these
  is itself an identifier, not prose.
  A call whose tool_input carries run_in_background set true. The result
  arrives on a different path later, and the wrapper's print statement here
  would never reach that later turn.
  A command whose output is already redirected, meaning the text contains
  >, >>, tee or Out-File. That output was never going to enter the
  conversation, so there is nothing this hook could save.
  A command holding a heredoc, meaning << appears. Rewriting one risks
  collapsing the heredoc's own backslashes.
  An event with no command field at all. It is passed through untouched.

Anything not on the allow list below is skipped the same way: an unknown
command is never rewritten, because the whole point is to touch only the
shapes this file was actually checked against.

WHAT GETS REWRITTEN. Only a command that starts one of the programs in
ALLOW_PROGRAMS, which are the programs this project actually ran, in this
conversation's own transcript, whose printed result was long. Read from one
session transcript under the Claude Code projects folder on 25 August 2026:
205 Bash calls
in that transcript, 51 of them with a result of 1,306 characters or longer,
the Opus stub floor common.STUB_CHARS_BY_READER held on 25 August (the
constant has been re-bisected downward twice since). Among those
51, every command that was not already one of the never-rewrite readers
above ran the same one program: python, invoking this project's own test
files under tests/test_*.py, or a one-off verification script. No build,
installer, linter or recursive-listing command appeared at that length
anywhere in the transcript, so none of those categories has an entry yet.
ALLOW_PROGRAMS holds exactly the one program this measurement found, plus
the name that same program carries on Linux and macOS. A Linux or macOS
machine has no program called python on PATH: the interpreter there is
python3, so the measured entry alone would let every packable python run on
those systems through unrewritten. The two names start the same interpreter,
so the second entry adds no new command shape.

The hook never crashes a caller. The whole decision is wrapped in a try and
every path returns 0, the way source_gate.py does: a damaged event, meaning
input that is not JSON, rewrites nothing and still exits 0.
"""

import re
import shlex
import sys
import time
from pathlib import Path

from common import (actor_size, disabled, emit, is_subagent, read_event,
                    tmp_dir)

# The reader programs. Their output was refused until 25 August 2026, on the
# grounds that it feeds the Edit tool's exact-match argument and exact text
# does not survive being drawn small. Measured that day over the 8 largest
# transcripts: reader output is 1,009,041 of the 1,246,234 Bash characters
# over the floor, 81 per cent, and refusing it left the whole Bash path worth
# minus 0.09 per cent of a plan. Of 348 such results, 71 fed a later Edit and
# 277 never did. The exact words of every packed output sit on disk beside the
# image under the same id, and bash_pack.py names that file on the pointer, so
# an Edit that needs them reads them instead of the picture.
READERS = ("cat", "sed", "head", "tail", "type", "Get-Content", "grep",
           "awk", "nl", "od")

# git prints hashes, diffs and commit messages, which are exact-copy data
# for the same reason the readers above are never rewritten.
GIT = ("git",)

# Each of these prints an identifier, not prose, so drawing the result as a
# picture would lose the one thing the command was run for.
IDENTIFIER_TOOLS = ("sha256sum", "md5sum", "certutil", "base64", "openssl")

# Seeded from the real commands in this conversation's own transcript, per
# the module docstring above. Measured, not guessed: 205 Bash calls read, 51
# with a result at or above the 1,306 character floor, and python was the
# only program among those 51 that was not already one of the readers above.
ALLOW_PROGRAMS = ("python", "python3")

# A command already sending its output somewhere else. That output was
# never going to enter the conversation, so rewriting it saves nothing.
REDIRECT_WORDS = ("tee", "Out-File")

# A command carrying a heredoc. Rewriting one risks collapsing its own
# backslashes, so it is left exactly as written.
HEREDOC = "<<"


def _has_word(command, names):
    """True when one of `names` appears in `command` as its own word.

    Matched on a boundary so that a path or variable holding the same
    letters, such as a folder named catalog, does not count as the word
    itself. The same approach source_gate.py uses for its own reader list.
    """
    for name in names:
        if re.search(r"(^|[\s;|&(])%s([\s]|$)" % re.escape(name), command):
            return True
    return False


# A redirect that joins one stream to another rather than sending it to a
# file: 2>&1, >&2, 1>&2 and so on. The text still reaches the conversation, so
# a command carrying one of these is not redirected in the sense that matters
# here. Testing for a bare ">" counted them as redirected and skipped them.
# Measured 25 August 2026 over the 8 largest transcripts: 196,112 of the
# 217,838 characters the gate skipped as "already redirected" were skipped by
# this fault, and every one of them entered the conversation in full.
STREAM_JOIN = re.compile(r"\d?>&\d")


def _already_redirected(command):
    """True when this command's own output already goes to a file.

    A stream join such as 2>&1 is removed before the test, because it sends
    stderr into stdout and stdout still reaches the conversation.
    """
    if ">" in STREAM_JOIN.sub("", command):
        return True
    return _has_word(command, REDIRECT_WORDS)


def _next_stamp(session_id):
    """A file name no other call of this hook is using right now.

    Built the same way brief_pack.py builds its own stamp: the session id
    is the same for every call in one session, so the process id and the
    clock in milliseconds are added, and a bump number is appended on the
    rare chance two calls still land in the same millisecond.
    """
    import os
    base = "%s-%d-%d" % (str(session_id or "x")[:8], os.getpid(),
                         int(time.time() * 1000) % 100000000)
    stamp = base
    bump = 0
    while (tmp_dir() / ("densepack-bashout-%s.txt" % stamp)).exists():
        bump += 1
        stamp = "%s-%d" % (base, bump)
    return stamp


def build_rewrite(command, session_id):
    """The replacement command text, or None when nothing should change.

    The original command runs exactly as written, inside a group so its own
    pipes and quoting are untouched, and its combined output is captured to
    a file. The exit code is saved before anything else runs, bash_pack.py
    is handed the file path and that exit code, and the rewrite then sets the
    SAME code the original command would have produced on its own. A rewrite
    that changed the exit code would be worse than no rewrite.

    THE LAST LINE IS (exit N), NOT exit N. Claude Code keeps one shell alive
    across Bash calls, which is why a cd in one call is still in force in the
    next. A bare exit terminates that shell, so the next call starts in a
    fresh one with the working directory reset. Measured 25 August 2026 in an
    on-against-off run of the same six commands: the run with this hook active
    took 15 turns against 9, because its first command failed on a working
    directory that had been reset, and it cost 81.62 per cent more.

    Proved directly in bash:

        printf 'echo A\\n(exit 7)\\necho "code=$?"\\necho B\\n' | bash
            A / code=7 / B          the shell keeps running
        printf 'echo A\\nexit 7\\necho B\\n' | bash
            A                       B never prints, the shell is gone

    A subshell that exits N sets $? to N in the parent and leaves the parent
    running, so the exit code the caller reads is unchanged and the shell
    survives.
    """
    packer = Path(__file__).resolve().parent / "bash_pack.py"
    outfile = tmp_dir() / ("densepack-bashout-%s.txt" % _next_stamp(session_id))
    return (
        "{\n%s\n} > %s 2>&1\n"
        "densepack_bash_gate_ec=$?\n"
        "python %s %s $densepack_bash_gate_ec %s\n"
        "(exit $densepack_bash_gate_ec)"
        % (command, shlex.quote(outfile.as_posix()),
           shlex.quote(packer.as_posix()), shlex.quote(outfile.as_posix()),
           # The reader's own id. bash_pack.py puts its 181 character usage
           # rule on this reader's first pointer and on none after it, so the
           # rule is charged once a session instead of 39 times a run.
           shlex.quote(str(session_id or "")))
    )


def should_rewrite(command, tool_input):
    """True when this command's output should be captured and drawn later.

    Every reason not to rewrite is checked first. Anything left after that
    is rewritten only when it starts a program this project has actually
    been measured running with a long, prose result, per ALLOW_PROGRAMS.
    """
    if not command:
        return False
    if tool_input.get("run_in_background"):
        return False
    if HEREDOC in command:
        return False
    if _already_redirected(command):
        return False
    if _has_word(command, GIT):
        return False
    if _has_word(command, IDENTIFIER_TOOLS):
        return False
    return _has_word(command, ALLOW_PROGRAMS) or _has_word(command, READERS)


def main():
    # NEVER CRASH A CALLER. This runs before every Bash command in the
    # session, so a fault here must let the command through, not stop it.
    try:
        event = read_event()
        if disabled(event.get("session_id")):
            return 0
        if (event.get("tool_name") or "") != "Bash":
            return 0
        tool_input = event.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            return 0
        command = str(tool_input.get("command") or "")
        if not should_rewrite(command, tool_input):
            return 0

        # IMAGES ONLY TO MEASURED READERS. The rewrite below is the only
        # thing that ever starts bash_pack.py, and bash_pack.py draws at
        # font_size(), which is the LEAD's size and says nothing about who
        # will read the picture. Standing down here, rather than passing a
        # size down the command line, means an unmeasured actor's command
        # is never captured in the first place and its output reaches it as
        # plain text.
        #
        # MEASURED 31 August 2026: haiku readers in delegated legs were
        # served images drawn at another model's floor and misread facts
        # from them. common.event_reader()'s contract is that an actor that
        # is unmeasured or cannot be named must not be guessed at and must
        # not be given the largest scored size.
        #
        # This also closes subread_gate.py's route, which denies a
        # subagent's Read and points it at cat: that cat arrives here and
        # is left alone for the same actor, so the exact text reaches it
        # whole. The LEAD is untouched and keeps resolved_reader().
        if is_subagent(event) and actor_size(event) is None:
            return 0
        replacement = dict(tool_input)
        replacement["command"] = build_rewrite(command, event.get("session_id"))
        emit({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": replacement,
            }
        })
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
