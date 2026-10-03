"""The control script for the slash commands. One verb per command.

The slash commands change settings, and nobody edits JSON by hand. Each
command runs this script with one verb. The script writes the flag or the
settings file that the hooks read, and prints one plain line with the new
state. This script does not pack. The hooks read the state again on each
event, and a change applies from the next agent.

  python dpctl.py status
  python dpctl.py on                        /densepack: packing on, defaults back
  python dpctl.py off                       /dense-off: each hook stops
  python dpctl.py remove                    /dense-remove: restore the converted
                                            instruction files and delete the
                                            DensePack files
  python dpctl.py bakpack <folder>          /bakpack: pack the instruction files of
                                            that folder
  python dpctl.py maxpack|maxoff            /maxpack and /max-off: Sonnet gets
                                            images or plain text
  python dpctl.py receipts quiet            the default, no receipt table (the
                                            table of what each image saved)
                                            in the reply
  python dpctl.py receipts default|verbose|light
                                            the receipt shapes, for the rare
                                            case when you want one in the reply
  python dpctl.py receipts full|line|off    the old words, still accepted
  python dpctl.py totals on|off|auto        the CONVERSATION TOTALS row
  python dpctl.py keep images|reports|both|off [folder]
                                            which copies stay after the session
  python dpctl.py vault [megabytes]         list the vault, or set its cap
  python dpctl.py keep <conversation>       copy one conversation out of it
  python dpctl.py reader auto|fable|opus|sonnet
                                            names the model when the plugin
                                            cannot read it from the transcript.
                                            One text size serves each model
  python dpctl.py stylecard on|off          the writing rule check on or off
  python dpctl.py agents                    the agents that started, and their
                                            models
  python dpctl.py help                      /helppack: the command table

Each verb above is one setting, and a setting needs no command of its own.
"""

import os
import re
import sys
from pathlib import Path

# The slash commands start this file without run_once.py. This file has its
# own version check. Pillow 12 has no wheel for Python below 3.10.
if sys.version_info < (3, 10):
    print("DensePack needs Python 3.10 or newer. This Python is %d.%d." % sys.version_info[:2])
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (disabled,
                    lead_model_name, font_size, keep_promote,
                    off_flag_path, resolved_reader, tmp_dir, vault_cap_bytes,
                    vault_folders, vault_trim,
                    OFF_FLAG, QUIET_FLAG, CODE_PX,  # noqa: E402
                    READER_SIZES, RECEIPTS_ALIASES, SETTINGS_ALLOWED,
                    SETTINGS_DEFAULTS, read_leads, settings,
                    write_settings)


def _settings_local():
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(root) / ".claude" / "settings.local.json"


def caller_session():
    """Return the session of this dpctl call, or "" when there is none.

    Claude Code exports CLAUDE_CODE_SESSION_ID into the environment of each
    Bash tool call. The slash commands reach dpctl.py through the Bash tool.
    The window that typed /dense-off then names itself. No value goes
    through a hook, and the code guesses nothing.

    The last id in read_leads() can name a different window. This function
    reads the variable and does not guess from that list. Claude Code also
    sets the variable inside the Bash call of a subagent, where it holds the
    session id of the parent. An agent that stops the plugin stops its own
    session.

    The value is empty when dpctl.py runs from a terminal, where there is no
    session. off_flag_path() then writes the bare file that each session
    checks, which is the correct result for a run from a terminal.
    """
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()


def prune_off_flags(keep=""):
    """Delete the off switches of sessions that ended.

    Without this, a per-session file stays on disk forever, one per window
    that ever stopped the plugin. read_leads() holds the last ten sessions,
    the same as in the rest of the plugin. A file whose id is not on that
    list belongs to a window that did not start in the last ten sessions.

    keep is the session of the caller. The function never prunes it,
    whatever the leads list holds. A window can reach dpctl.py before its
    SessionStart hook records it. A sweep that deletes the file that this
    window wrote makes /dense-off do nothing.

    An empty leads list prunes nothing. It means that the plugin recorded no
    session yet, not that each session ended. A sweep on it deletes the
    switch of a live neighbor in a new project.
    """
    live = set(read_leads())
    if not live:
        return
    for path in tmp_dir().glob(OFF_FLAG + "-*"):
        session = path.name[len(OFF_FLAG) + 1:]
        if session in live or session == str(keep):
            continue
        try:
            path.unlink()
        except OSError:
            pass


# The /helppack output. Each "default" below matches SETTINGS_DEFAULTS in
# common.py. Each "permanent" line names a behavior with no key in
# SETTINGS_ALLOWED.
HELP_TABLE = """DensePack commands.

Permanent while DensePack is on. No command stops one of these alone.
Only /dense-off stops them all.

| Permanent behavior | What it does |
| --- | --- |
| The standing reminder | On a message with a pasted image, DensePack tells the lead how to read a condensed image |
| Report packing | DensePack packs the report of each finished subagent into an image when the image costs less than the text |
| Brief packing | In auto and bypassPermissions mode, DensePack packs each brief over the threshold into an image before the subagent starts. In other modes, the subagent gets the brief as text |
| One text size | DensePack packs each report and brief at one text size for all models. Each image is between 700 and 952 px wide, at the width that costs the fewest tokens. A longer text makes a taller image or more images. It is not a setting |
| Reject when worse | DensePack deletes an image that costs more than the text and sends the text |
| Never to an unmeasured model | Haiku 4.5 gets plain text because Haiku does not read text on images accurately |
| Sonnet gets images | Sonnet gets images. Type /max-off to send it plain text |
| The delivery rule | DensePack sends each subagent the note that tells how files and command output arrive as images |
| The manifest | Each agent that finishes gets a row, packed or not |
| The vault | DensePack copies each packed image and its text to .claude/densepack-vault, one folder per conversation. The copies stay when DensePack prunes .claude/tmp. When the vault is over 200 MB, DensePack deletes the oldest folders |
| The spawn log | Each SPAWNED agent also gets a row before it finishes, with the model that it runs on. The log changes nothing |
| Instruction files as images | At session start, the folder's CLAUDE.md, .claude/CLAUDE.md, CLAUDE.local.md, AGENTS.md and .claude/rules/*.md, your ~/.claude/CLAUDE.md and the project's MEMORY.md each become a short pointer, the images and <name>.bakpack with the original text. DensePack packs a file only when its images and pointer cost less than its text. A short file stays text. The change applies from the next session, because Claude Code loads these files before DensePack runs. /dense-remove restores the originals |

| Command | What it sets | Is this the default |
| --- | --- | --- |
| /densepack | Packing on and all settings below back to default | It IS the reset |
| /dense-off | All hooks stop | No |
| /dense-remove | Restores each converted instruction file to its original text from its .bakpack, removes CLAUDE_CODE_THRIFTY_SONIC and deletes all DensePack files that /plugin uninstall does not delete. Run it before the uninstall | Sets nothing |
| /bakpack <folder> | Packs the CLAUDE.md, .claude/CLAUDE.md, CLAUDE.local.md, AGENTS.md and .claude/rules/*.md of that folder into images behind a pointer. The agent does not read them. Run it from a session in another folder. The first session in that folder reads the images | Sets nothing |
| /bakoff <folder> | Restores the originals of that folder from their .bakpack copies and deletes their images | Sets nothing |
| /maxpack | Sonnet gets images too | YES |
| /max-off | Sonnet gets plain text | No |
| /helppack | Nothing. Prints this table | Sets nothing |

Every other setting is one /setpack argument, and needs no command of its
own. DensePack saves the last receipt table in
.claude/tmp/densepack-receipt-last.md. A look at it costs the conversation
nothing.

The reader setting is the one setting that belongs to a single
conversation. Run dpctl.py reader inside the conversation that it is for.
/setpack keep both sets images and reports. dpctl keep images or keep
reports sets one, and takes a folder after it."""


def help_text():
    """Return HELP_TABLE without the rows for commands that this copy does
    not ship.

    A help row that names a command that you cannot type is out of date. A
    command row stays only when its <name>.md file is in the commands folder
    next to this script. The argument section stays only when its own
    command file is there."""
    commands = Path(__file__).resolve().parents[1] / "commands"
    text = HELP_TABLE
    head, marker, tail = text.partition("\nEvery other setting is one /setpack argument")
    if marker and not (commands / "setpack.md").is_file():
        text = head.rstrip() + "\n"
    # A behavior row belongs to one script. A copy of the plugin without
    # that script drops the row.
    scripts = Path(__file__).resolve().parent
    row_script = {"The delivery rule": "subagent_start.py",
                  "The spawn log": "subagent_start.py"}
    kept = []
    for line in text.splitlines():
        m = re.match(r"\| /([a-z-]+) \|", line)
        if m and not (commands / (m.group(1) + ".md")).is_file():
            continue
        row = re.match(r"\| ([A-Z][^|]*?) \|", line)
        if (row and row.group(1) in row_script
                and not (scripts / row_script[row.group(1)]).is_file()):
            continue
        kept.append(line)
    return "\n".join(kept)


TOTALS_SAID = {
    "on": "conversation totals row under each table, next to the batch totals row that always prints",
    "off": "conversation totals row at wrap-up only, batch totals row still prints with each table",
    "auto": "conversation totals row follows the mode, batch totals row still prints with each table",
}


def status_line():
    current = settings(caller_session())
    # The switch of this window, not of another window. The /dense-off of a
    # second session does not make this one report OFF while its hooks run.
    packing = "OFF" if disabled(caller_session()) else "on"
    quiet = ", quiet flag set" if (tmp_dir() / QUIET_FLAG).exists() else ""
    keep = current["keep"]
    if keep != "off":
        keep += " -> " + (current["keep_folder"] or "densepack-archive")
    session = caller_session()
    setting = current.get("reader", "auto")
    reader = resolved_reader(session)
    if setting in READER_SIZES:
        how = "set by hand"
    else:
        # The session that runs now, never a model name that a finished
        # session left on disk.
        found = lead_model_name(session)
        how = ("read from the lead model %s" % found if found
               else "lead model not read yet, using the one size for all models")

    # One image size serves each model, and the status line names no tier.
    tier = ""
    return ("DensePack: packing %s, reader %s (%d px, %s)%s, "
            "receipts %s, totals %s (%s)%s, keep %s, style card %s, "
            "Sonnet images %s"
            % (packing, reader, CODE_PX, how, tier,
               current["receipts"], current["totals"],
               TOTALS_SAID[current["totals"]], quiet, keep,
               current.get("stylecard", "off"), current.get("maxpack", "on")))


# The model that each reader profile names. A model id that contains the
# profile name maps to that profile.
READER_NAMES = {"fable": "Fable 5.1", "opus": "Opus 5.5", "sonnet": "Sonnet 5.5"}


def remove_everything():
    """Delete each DensePack file that /plugin uninstall does not delete.

    No hook runs on uninstall. Claude Code deletes only the data folder of
    the plugin, ~/.claude/plugins/data/<plugin>. This function removes the
    rest. That is the machine folders under the home folder, the Python
    install markers, the bench folders, old render jobs in the temp folder,
    the vault and densepack files of each project, and the trust entry of
    the marketplace folder. On a reinstall at the same path, Claude Code then
    asks for trust again. The function prints each path that it removes."""
    import glob
    import json
    import shutil
    import tempfile
    home = Path.home()
    removed = []

    def drop(path):
        path = Path(path)
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
            else:
                return
            removed.append(str(path))
        except OSError as exc:
            print("Could not remove %s: %s" % (path, exc))

    # The code restores the originals before it deletes the state folder and
    # the vaults, because the state file lists each converted CLAUDE.md and
    # MEMORY.md.
    try:
        import pack_instructions
        for name in pack_instructions.restore_all():
            removed.append("the pointer in %s, original restored from its .bakpack" % name)
    except Exception as exc:  # noqa: BLE001
        print("Could not restore the converted instruction files: %s" % exc)

    for path in (home / ".claude" / "densepack-state", home / ".claude" / "densepack-cards",
                 home / ".claude" / "densepack-tracker.json", home / ".densepack"):
        drop(path)
    # ensure_python.ps1 writes only python-install-tried in this folder. The
    # right-click tool keeps its saved packs in the same folder (Windows
    # names are not case sensitive), so the removal deletes only that file.
    if os.environ.get("LOCALAPPDATA"):
        drop(Path(os.environ["LOCALAPPDATA"]) / "densepack" / "python-install-tried")
    for path in glob.glob(os.path.join(tempfile.gettempdir(), "densepack-trial-*.pkl")):
        drop(path)

    # Each folder that has a conversation in Claude Code. Each transcript line
    # names its working folder in "cwd".
    projects = set()
    for transcript in glob.glob(str(home / ".claude" / "projects" / "*" / "*.jsonl")):
        try:
            with open(transcript, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"cwd"' in line:
                        cwd = json.loads(line).get("cwd")
                        if cwd:
                            projects.add(cwd)
                            break
        except (OSError, ValueError):
            continue
    for project in sorted(projects):
        folder = Path(project) / ".claude"
        drop(folder / "densepack-vault")
        for pattern in ("densepack-*", ".densepack-*"):
            for path in glob.glob(str(folder / "tmp" / pattern)):
                drop(path)

    config = home / ".claude.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
        trusted = [key for key in (data.get("projects") or {})
                   if key.replace("\\", "/").rstrip("/").endswith(
                       "plugins/marketplaces/densepack-marketplace")]
        if trusted:
            for key in trusted:
                del data["projects"][key]
            part = config.with_name(config.name + ".densepack-part")
            part.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(str(part), str(config))
            removed += ["the trust entry for " + key for key in trusted]
    except (OSError, ValueError):
        pass

    from common import bash_first_off
    if bash_first_off(enable=False):
        removed.append("CLAUDE_CODE_THRIFTY_SONIC from ~/.claude/settings.json")

    print("DensePack removed %d items:" % len(removed))
    for item in removed:
        print("  " + item)
    print("To finish, run /plugin uninstall densepack, then "
          "/plugin marketplace remove densepack-marketplace. The uninstall "
          "deletes the plugin's data folder.")
    return 0


def main(argv):
    # The words of this verb arrive as ONE quoted argument. A stray ; or &
    # that you typed after the command never reaches the shell. The code
    # splits the words here and keeps only these characters. The colon and
    # the backslash are in the set because "keep" takes a folder, and a
    # Windows folder path holds the two.
    if argv and argv[0] == "setpack":
        words = " ".join(argv[1:]).split()
        argv = [w for w in words
                if all(c.isalnum() or c in "-_./:\\" for c in w)]
    verb = argv[0] if argv else "status"

    if verb == "status":
        # No argument. The status line below prints.
        pass

    elif verb == "remove":
        return remove_everything()

    elif verb in ("bakpack", "mdpack"):
        # mdpack is the name of this command in DensePack 1.3.3 and earlier.
        # The folder arrives as one quoted argument and can hold spaces.
        folder = " ".join(argv[1:]).strip().strip('"').strip("'")
        if not folder:
            print("Name a folder: /bakpack <folder>")
            return 1
        import pack_instructions
        for name, result in pack_instructions.convert_folder(folder):
            if result != "absent":
                print("%s: %s" % (name, result))
        print("A session that starts in that folder loads the pointer and reads the images. "
              "The original text stays next to each file as <name>.bakpack. "
              "/bakoff <folder> restores the originals.")
        return 0

    elif verb == "bakoff":
        folder = " ".join(argv[1:]).strip().strip('"').strip("'")
        if not folder:
            print("Name a folder: /bakoff <folder>")
            return 1
        import pack_instructions
        done = pack_instructions.restore_folder(folder)
        for name in done:
            print("restored " + name)
        if not done:
            print("No packed instruction file in " + folder)
        return 0

    elif verb == "on":
        # The two shapes. The file of this window, and a bare file from an
        # older version or a terminal run. A bare file stops each session,
        # and /densepack must not report the plugin on while that file
        # exists. The code does not touch the file of another window.
        off_flag_path(caller_session()).unlink(missing_ok=True)
        (tmp_dir() / OFF_FLAG).unlink(missing_ok=True)
        (tmp_dir() / QUIET_FLAG).unlink(missing_ok=True)
        prune_off_flags()
        write_settings(dict(SETTINGS_DEFAULTS))

    elif verb in ("maxpack", "maxoff"):
        write_settings({"maxpack": "on" if verb == "maxpack" else "off"})

    elif verb == "off":
        session = caller_session()
        off_flag_path(session).write_text(
            "set by /dense-off%s\n"
            % (" in session " + session if session else ", no session"),
            encoding="utf-8")
        prune_off_flags(keep=session)

    elif verb == "receipts":
        mode = argv[1] if len(argv) > 1 else ""
        mode = RECEIPTS_ALIASES.get(mode, mode)
        if mode not in SETTINGS_ALLOWED["receipts"]:
            print("receipts needs one of: default, verbose, light, quiet. "
                  "The old words still work, with full as verbose, line as "
                  "default and off as quiet")
            return 1
        (tmp_dir() / QUIET_FLAG).unlink(missing_ok=True)
        write_settings({"receipts": mode})

    elif verb == "totals":
        mode = argv[1] if len(argv) > 1 else ""
        if mode not in SETTINGS_ALLOWED["totals"]:
            print("totals needs one of: on, off, auto")
            return 1
        write_settings({"totals": mode})

    elif verb == "reader":
        mode = argv[1] if len(argv) > 1 else ""
        if mode not in SETTINGS_ALLOWED["reader"]:
            print("reader needs one of: auto, fable, opus, sonnet")
            return 1
        session = caller_session()
        write_settings({"reader": mode})
        if mode == "auto":
            print("DensePack reads the model of the lead from the first "
                  "assistant line of the transcript of this session. DensePack "
                  "packs each image at one size, %d px, for all models. The "
                  "current reader is %s." % (CODE_PX, resolved_reader(session)))
        else:
            print("DensePack reader set to %s, %s. DensePack packs each image "
                  "at one size, %d px, for all models. This changes the "
                  "name that the plugin reports and no image. Set it to auto "
                  "again, and the plugin reads the model of the lead."
                  % (mode, READER_NAMES[mode], CODE_PX))

    elif verb == "stylecard":
        mode = argv[1] if len(argv) > 1 else ""
        if mode not in SETTINGS_ALLOWED["stylecard"]:
            print("stylecard needs on or off")
            return 1
        write_settings({"stylecard": mode})

    elif verb == "agents":
        # pointer.py needs Pillow and exits when Pillow is missing. The import
        # stays here, so that every other command works without Pillow.
        from pointer import delegation_table
        session = read_leads()[-1] if read_leads() else ""
        print("\n".join(delegation_table(session)))
        return 0

    elif verb == "help":
        print(help_text())
        return 0

    elif verb == "vault":
        if len(argv) < 2:
            rows = vault_folders()
            if not rows:
                print("The vault is empty. It fills as agents finish.")
                return 0
            print("The vault, oldest first. Each packed image and its source "
                  "text, one folder per conversation. The cap is %d MB. When the vault "
                  "reaches the cap, DensePack deletes the oldest folder first."
                  % (vault_cap_bytes() // 1024 // 1024))
            print("%-40s %10s" % ("conversation", "size"))
            for _t, folder, size in rows:
                print("%-40s %9.1f MB" % (folder.name, size / 1024 / 1024))
            print("%-40s %9.1f MB" % ("TOTAL",
                                      sum(r[2] for r in rows) / 1024 / 1024))
            return 0
        try:
            megabytes = int(argv[1])
        except ValueError:
            print("vault needs a number of megabytes, or no argument to list")
            return 1
        write_settings({"vault_mb": megabytes})
        removed = vault_trim()
        print("Vault cap set to %d MB.%s" % (
            megabytes,
            (" Deleted %d conversation folder(s): %s"
             % (len(removed), ", ".join(removed))) if removed else " Nothing deleted."))

    elif verb == "keep":
        mode = argv[1] if len(argv) > 1 else ""
        # A conversation id in place of a mode word means "save that one".
        if mode and mode not in SETTINGS_ALLOWED["keep"]:
            dest = keep_promote(mode)
            if dest is None:
                print("No conversation named %s in the vault. Run "
                      "dpctl.py vault to list what is there." % mode)
                return 1
            print("Copied conversation %s out of the vault into %s. Nothing "
                  "deletes that folder." % (mode, dest))
            return 0
        if mode not in SETTINGS_ALLOWED["keep"]:
            print("keep needs one of: images, reports, both, off, a folder, "
                  "or a conversation id from dpctl.py vault")
            return 1
        changes = {"keep": mode}
        if len(argv) > 2:
            # A folder with spaces arrives as several arguments when the
            # caller forgot quotes. The code joins them again. That is always
            # correct, because nothing else follows the folder.
            changes["keep_folder"] = " ".join(argv[2:])
        write_settings(changes)

    else:
        print("unknown verb %r. Verbs: status, on, off, remove, bakpack, bakoff, maxpack, "
              "maxoff, receipts, totals, keep, reader, stylecard, agents, vault, help"
              % verb)
        return 1

    print(status_line())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
