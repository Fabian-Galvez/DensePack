"""Sends the output of a long Bash command to a file, to be packed as an image.

hooks.json does not register this file. bash_image.py, a PostToolUse hook on
Bash, returns Bash output as an image in the same tool result. This file and
bash_pack.py hold the older pointer route.

The report side of this plugin packs the finished output of an agent as a
small image. This file does the same for a command that the model runs. A
test run or a build can print thousands of characters into the conversation,
and each character costs full price. This hook reads a Bash command before
it runs. When the command matches the lists below, the hook changes it to
write the output to a file first. plugin/scripts/bash_pack.py then packs that
file as the same kind of image as the report side. It gets the file path and
the exit code of the command as its two arguments.

As a PreToolUse hook on the Bash tool, it has the same shape as
source_gate.py. Claude Code sends the tool call to stdin before it runs, and
the updatedInput that this script returns becomes the call that runs.
updatedInput REPLACES the whole input object and does not merge into it. The
hook sends back each field of the event input, the same as source_gate.py. A
partial object fails schema validation with "the required parameter is
missing".

What the hook never changes, and the reason for each:

  A one line read, sed -n 'Np' on a file. The hook changes it like each
  other reader, and it returns as text because one line is below
  common.BASH_CHARS. The Read tool with offset N and limit 1 is the route
  that the cards teach for an exact value.
  git, with each subcommand. A hash, a diff and a commit message are
  exact-copy data, for the same reason as above.
  sha256sum, md5sum, certutil, base64, openssl. The output of each is an
  identifier, not prose.
  A call whose tool_input has run_in_background set to true. The result
  comes later on a different path, and the print statement of the wrapper
  does not reach that later turn.
  A command whose output already goes elsewhere, where the text contains >,
  >>, tee or Out-File. That output does not enter the conversation, and this
  hook has nothing to save.
  A command with a heredoc, where << appears. A change to it can collapse
  the backslashes of the heredoc.
  An event with no command field. The hook passes it unchanged.

The hook skips each command that is not in ALLOW_PROGRAMS or READERS. It
never changes an unknown command. It changes only the command shapes that
the tests of this file covered.

What the hook changes. A command that starts a program in READERS, or one of
the programs in ALLOW_PROGRAMS. ALLOW_PROGRAMS holds the programs that a
measured session transcript ran with a long printed result. In that
transcript, 51 of 205 Bash calls printed a long result, and each one that
was not a reader ran one program, python. No build, installer, linter or
recursive-listing command appeared at that length, and none of those
categories has an entry. ALLOW_PROGRAMS holds the one program that this
measurement found, plus the name of that program on Linux and macOS. A Linux
or macOS machine has no program called python on PATH. The interpreter there
is python3. With the measured entry alone, each packable python run on those
systems passes unchanged. The two names start the same interpreter, and the
second entry adds no new command shape.

A fault in the hook never blocks the call. A try covers the whole decision,
and each path returns 0, the same as source_gate.py. A damaged event, such
as input that is not JSON, changes nothing and still exits 0.
"""

import os
import re
import shlex
import sys
import time
from pathlib import Path

from common import (actor_key, disabled, emit, gets_images,
                    read_event, tmp_dir)

# The reader programs. Their output can go into the exact-match argument of
# the Edit tool, and a small image can lose exact text. Over the 8 largest
# measured transcripts, reader output is 81 per cent of the Bash characters
# over the floor. Of 348 such results, 277 never went into a later Edit.
# Without the readers, the Bash path saves little. The exact text of each
# packed output is on disk next to the image, under the same id. bash_pack.py
# names that file on the pointer. An Edit that needs the text reads that file
# and not the image.
READERS = ("cat", "sed", "head", "tail", "type", "Get-Content", "grep",
           "awk", "nl", "od")

# git prints hashes, diffs and commit messages, which are exact-copy data.
# The hook never changes a git command.
GIT = ("git",)

# Each of these prints an identifier, not prose. An image of the result can
# lose the one value that the command exists to print.
IDENTIFIER_TOOLS = ("sha256sum", "md5sum", "certutil", "base64", "openssl")

# The list comes from real commands, as the module docstring says. python
# was the only program with a long result that was not one of the readers.
ALLOW_PROGRAMS = ("python", "python3")

# Words that show that a command already sends its output elsewhere. That
# output does not enter the conversation, and a change saves nothing.
REDIRECT_WORDS = ("tee", "Out-File")

# The heredoc marker. A change to a command with a heredoc can collapse its
# backslashes. The hook leaves that command as written.
HEREDOC = "<<"


def _has_word(command, names):
    """Return True when one of `names` is in `command` as its own word.

    The match uses a word boundary. A path or variable with the same
    letters, such as a folder named catalog, does not count as the word.
    source_gate.py uses the same method for its reader list.
    """
    for name in names:
        if re.search(r"(^|[\s;|&(])%s([\s]|$)" % re.escape(name), command):
            return True
    return False


# A redirect that joins one stream to another and does not send it to a
# file, such as 2>&1, >&2 and 1>&2. The text still reaches the conversation.
# A command with one of these is not redirected in the sense that matters
# here. A test for a bare ">" skips such a command by mistake.
STREAM_JOIN = re.compile(r"\d?>&\d")


def _already_redirected(command):
    """Return True when the output of this command already goes to a file.

    The function removes a stream join such as 2>&1 before the test. A
    stream join sends stderr into stdout, and stdout still reaches the
    conversation.
    """
    if ">" in STREAM_JOIN.sub("", command):
        return True
    return _has_word(command, REDIRECT_WORDS)


# The session id shape that Claude Code documents.
SESSION_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def _next_stamp(session_id):
    """Return a file stamp that no other call of this hook uses now.

    brief_pack.py builds its stamp the same way. The session id is the same
    for each call in one session. The function adds the process id and the
    clock in milliseconds. It adds a bump number when two calls still land
    in the same millisecond, which is rare.
    """
    import os
    # Only the documented uuid shape goes into the file name. Without this
    # check, a separator in the id can put the output file outside
    # .claude/tmp.
    tag = str(session_id or "")
    base = "%s-%d-%d" % (tag[:8] if SESSION_ID.fullmatch(tag) else "x",
                         os.getpid(),
                         int(time.time() * 1000) % 100000000)
    stamp = base
    bump = 0
    while (tmp_dir() / ("densepack-bashout-%s.txt" % stamp)).exists():
        bump += 1
        stamp = "%s-%d" % (base, bump)
    return stamp


def build_rewrite(command, session_id, actor=None):
    """Return the replacement command text.

    The original command runs as written, through eval as one quoted word in
    a subshell. Its pipes, quoting and cd stay unchanged, and its combined
    output goes to a file. The rewrite saves the exit code before anything
    else runs. bash_pack.py gets the file path and that exit code. The
    rewrite then sets the SAME code that the original command returns. A
    rewrite that changes the exit code is worse than no rewrite.

    THE LAST LINE IS (exit N), NOT exit N. Claude Code keeps one shell
    running across Bash calls, and a cd in one call still applies in the
    next. A bare exit ends that shell. The next call then starts in a new
    shell with the working directory reset. In an on-against-off run of the
    same six commands, a bare exit took 15 turns against 9, because a
    command failed on a reset working directory. It cost 81.62 per cent more.

    A test in bash:

        printf 'echo A\\n(exit 7)\\necho "code=$?"\\necho B\\n' | bash
            A / code=7 / B          the shell keeps running
        printf 'echo A\\nexit 7\\necho B\\n' | bash
            A                       B never prints, the shell is gone

    A subshell that exits N sets $? to N in the parent, and the parent keeps
    running. The exit code that the caller reads does not change, and the
    shell stays open.
    """
    packer = Path(__file__).resolve().parent / "bash_pack.py"
    stamp = _next_stamp(session_id)
    outfile = tmp_dir() / ("densepack-bashout-%s.txt" % stamp)
    cwdfile = tmp_dir() / ("densepack-bashcwd-%s.txt" % stamp)
    # The command runs through eval as one quoted word, inside a subshell.
    # Nothing in it can end the calling shell before bash_pack.py runs. An
    # exit, an exec, or set -e or set -u with a failing step, in any
    # spelling, ends only the subshell. The output that it printed is still
    # in the file. The subshell writes its working folder last, and the
    # calling shell moves there. A cd in the command then still applies in
    # the next Bash call. The rewrite uses no brace group, because Claude
    # Code rejects a rewritten command with a brace next to a quote. As one
    # quoted word, a stray ")" in the command cannot end anything early.
    return (
        "( eval %s; densepack_bash_gate_ec=$?; pwd > %s; exit $densepack_bash_gate_ec ) > %s 2>&1\n"
        "densepack_bash_gate_ec=$?\n"
        "[ -s %s ] && cd \"$(cat %s)\" 2>/dev/null; rm -f %s\n"
        "if %s %s %s $densepack_bash_gate_ec %s %s; then rm -f %s; "
        "else cat %s; fi\n"
        "(exit $densepack_bash_gate_ec)"
        % (shlex.quote(command), shlex.quote(cwdfile.as_posix()),
           shlex.quote(outfile.as_posix()),
           shlex.quote(cwdfile.as_posix()), shlex.quote(cwdfile.as_posix()),
           shlex.quote(cwdfile.as_posix()),
           # The Python that runs this hook. A machine with only python3
           # still packs the output. The shell of the Bash tool has no
           # CLAUDE_PLUGIN_DATA. Without it, bash_pack.py cannot find the
           # packages that the plugin installed there. The rewrite puts it
           # in front of the command.
           ("CLAUDE_PLUGIN_DATA=%s " % shlex.quote(os.environ["CLAUDE_PLUGIN_DATA"])
            if os.environ.get("CLAUDE_PLUGIN_DATA") else "")
           + shlex.quote(Path(sys.executable).as_posix()),
           shlex.quote(packer.as_posix()), shlex.quote(outfile.as_posix()),
           # The session id. bash_pack.py puts its 181 character usage rule
           # on the first pointer of this session and on no later pointer.
           # The rule then costs characters once a session and not 39 times
           # a run.
           shlex.quote(str(session_id or "")),
           # The agent that reads the image, "agent-<agent id>", or "" for
           # the lead. bash_pack.py packs at the floor of THIS agent, not the
           # floor of the lead. A wrapped shell command starts bash_pack.py,
           # not a hook. No event reaches it, and the command line is the
           # only way to name the receiver. The rewrite quotes this id like
           # each other argument. An id with a shell character cannot break
           # the rewrite.
           shlex.quote(str(actor or "")),
           # The rewrite removes the file only when the packer exits 0. A
           # packer that fails prints nothing. The rewrite then prints the
           # captured output, and the model gets the text and not an empty
           # result.
           shlex.quote(outfile.as_posix()),
           shlex.quote(outfile.as_posix()))
    )


def should_rewrite(command, tool_input):
    """Return True when the hook captures the output of this command and
    packs it later.

    The function checks each reason to skip first. It then changes a command
    only when the command starts a program in READERS, or a program in
    ALLOW_PROGRAMS, measured with a long prose result in this project.
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
    # A fault never blocks the call. This hook runs before each Bash command
    # in the session. After a fault, the command runs unchanged.
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

        # IMAGES ONLY TO MEASURED MODELS. The rewrite below is the only step
        # that starts bash_pack.py. bash_pack.py packs at font_size(), which
        # is the size for the LEAD and does not depend on the model that
        # reads the image. The hook stops here and does not pass a size on
        # the command line. The hook then never captures the command of an
        # unmeasured actor, and the output reaches that actor as plain text.
        #
        # An unmeasured model that gets an image packed at the floor of
        # another model reads wrong facts from it. common.event_reader()
        # states the rule. The code must not guess an actor that is
        # unmeasured or has no name, and must not give it the largest scored
        # size.
        #
        # Sonnet gets images, and a Haiku lead gets text.
        if not gets_images(event):
            return 0
        # The rewrite runs the command in a subshell, and an exit, exec or
        # set -e ends only that subshell. $$ still names the calling shell
        # inside it. A command with $$, such as kill -9 $$, can end the
        # calling shell before bash_pack.py runs. Such a command runs
        # unchanged, and its output arrives as text.
        # The check removes quotes and backslashes first. A quoted or
        # escaped $$ still counts. ${$ covers ${$}, ${$:-0} and ${$%x}. A
        # command can also build $$ from pieces and run it with eval,
        # source, . <(...), /dev/stdin, or ANSI-C quoting such as
        # $'\x65val'. It can read the id of the calling shell from BASHPID,
        # PPID or /proc. A command with one of these, or with the word kill,
        # stays text. It loses only the saving, never output. Words count
        # only between shell word boundaries. scripts/eval.py and
        # eval-notes.md are still packed.
        plain = "".join(c for c in command if c not in (chr(34), chr(39), chr(92)))
        if ("$$" in plain or "${$" in plain or "$" + chr(39) in command
                or "<(" in plain or "/dev/stdin" in plain or "/proc/" in plain
                or re.search(r"(^|[\s;|&(`])(eval|source|kill)($|[\s;|&)`])", plain)
                or re.search(r"(?i)(bashpid|ppid)", plain)):
            return 0
        replacement = dict(tool_input)
        replacement["command"] = build_rewrite(
            command, event.get("session_id"), actor_key(event))
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
