"""The control desk behind the slash commands. One verb per command.

HOW THIS FILE FITS, in plain words: the slash commands need to flip settings
without anyone hand-editing JSON. Each command runs this script with one verb,
the script writes the flag or the settings file the hooks already read, and
prints one plain line saying what the state now is. Nothing here touches
packing itself; the hooks read the state fresh on every event, so a change
takes effect at the very next agent.

  python dpctl.py status
  python dpctl.py on                        /densepack: packing on, defaults back
  python dpctl.py off                       /dense-off: every hook stands down
  python dpctl.py receipts quiet            the default: no receipt table in the reply
  python dpctl.py receipts default|verbose|light
                                            the receipt shapes, for the rare
                                             time one is wanted in the reply
  python dpctl.py receipts full|line|off    the old words, still accepted
  python dpctl.py totals on|off|auto        the CONVERSATION TOTALS row
  python dpctl.py keep images|reports|both|off [folder]
                                            what copies survive the session
  python dpctl.py vault [megabytes]         list the vault, or set its cap
  python dpctl.py keep <conversation>       save one conversation out of it
  python dpctl.py reader auto|fable|opus|sonnet
                                            names the reader when the plugin
                                            cannot read it from the transcript.
                                            One text size serves every reader
  python dpctl.py stylecard on|off          the writing rule check on or off
  python dpctl.py agents                    who was spawned, and on what model
  python dpctl.py help                      /helppack: the command table

Every verb above is one setting, so a setting needs no command of its own.
"""

import os
import re
import sys
from pathlib import Path

# The slash commands start this file without run_once.py, so the version
# check is here too. Pillow 12 has no wheel under Python 3.10.
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
from pointer import delegation_table  # noqa: E402



def _settings_local():
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(root) / ".claude" / "settings.local.json"


def caller_session():
    """The session this dpctl call speaks for, or "" when it speaks for none.

    Claude Code exports CLAUDE_CODE_SESSION_ID into the environment of every
    Bash tool call, and the slash commands reach dpctl.py through the Bash
    tool, so the window that typed /dense-off names itself. Nothing has to
    be threaded through a hook and nothing has to be guessed.

    The last id in read_leads() can name a different window, so this reads
    the variable rather than guessing from that list. The variable is also
    set inside a subagent's Bash call, and holds the parent session's id
    there, so an agent standing the plugin down stands its own session down.

    Empty when dpctl.py is run from a terminal, where there is no session at
    all. off_flag_path() then writes the bare file every session honours,
    which is what an A B test from a shell wants.
    """
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()


def prune_off_flags(keep=""):
    """Delete off switches belonging to sessions that are gone.

    A per-session file would otherwise stay on disk forever, one per window
    that ever stood the plugin down. read_leads() is the same ten session
    horizon the rest of the plugin keeps, so a file whose id is not on that
    list belongs to a window that has not started in the last ten.

    keep is the caller's own session, never pruned whatever the leads list
    says. A window can reach dpctl.py before its SessionStart hook has
    recorded it, and a sweep that deleted the file it had just written would
    make /dense-off do nothing at all.

    An empty leads list prunes nothing. It means no session has been recorded
    yet, not that every session is dead, and a sweep on it would delete a
    live neighbour's switch in a fresh project.
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

# The /helppack output. Every "default" below matches SETTINGS_DEFAULTS in
# common.py, and every "permanent" line names a behavior with no key in
# SETTINGS_ALLOWED.
HELP_TABLE = """DensePack commands.

Permanent while DensePack is on. No command switches these off on their own,
only /dense-off, which stops everything.

| Permanent behavior | What it does |
| --- | --- |
| The standing reminder | A message that carries a pasted image tells the lead how to read a condensed image |
| Report packing | Every finished subagent's report is converted to an image when the image measures cheaper than the text |
| Brief packing | Every brief over the threshold is converted to an image before the subagent starts, at the one text size |
| One text size | Every report and brief converts at one text size, whatever model wrote it or reads it. Each image is 756 or 784 px wide, and a longer text makes a taller image or more images. Not a setting |
| Refuse when worse | An image that would cost more than the words is thrown away and the words are sent |
| Never to an unmeasured model | Haiku 4.5 gets plain text. It has never been scored on a condensed image |
| Sonnet gets images | Sonnet gets images. Type /max-off to send it plain text |
| The delivery rule | Every subagent is told how to return its report |
| The manifest | Every agent that finishes gets a row, packed or not |
| The vault | Every converted image and its text are copied to .claude/densepack-vault, one folder a conversation, so they survive when .claude/tmp is cleaned. Past 200 MB the oldest folders are deleted |
| The spawn log | Every agent SPAWNED gets a row too, before it finishes, holding the model it ran on. Recording only |
| Instruction files as images | At session start, the folder's CLAUDE.md, .claude/CLAUDE.md and CLAUDE.local.md, your ~/.claude/CLAUDE.md and the project's MEMORY.md each become a short pointer, the images and <name>.densepack.bak with the original text. A file converts only when its images and pointer cost less than its text, so a short file stays text. It applies from the next session, since Claude Code loads these files before DensePack runs. /dense-remove puts the originals back |

| Command | What it sets | Is this the default |
| --- | --- | --- |
| /densepack | Packing on, and every setting below back to its default | It IS the reset |
| /dense-off | Every hook stands down | No |
| /dense-remove | Puts every converted CLAUDE.md, CLAUDE.local.md and MEMORY.md back to its original text from its .densepack.bak, removes CLAUDE_CODE_THRIFTY_SONIC, and deletes every DensePack file that /plugin uninstall leaves behind. Run it before the uninstall | Sets nothing |
| /mdpack <folder> | Converts that folder's CLAUDE.md, .claude/CLAUDE.md and CLAUDE.local.md into images behind a pointer, without reading them. Run it from a folder next to that folder, then open a new session inside it: that session reads the images and never the text | Sets nothing |
| /maxpack | Sonnet gets images too | YES |
| /max-off | Sonnet gets plain text | No |
| /stylepack | Every Write and Edit is checked against the writing rules | No |
| /stylepack-off | No writing rule check | YES |
| /dashboard | Opens the live page: the bill, every pack and every agent, per conversation | Sets nothing |
| /helppack | Nothing. Prints this table | Sets nothing |
| /setpack | Takes a verb and a value and sets that one thing | Sets nothing on its own |

Every other setting is one /setpack argument, and needs no command of its
own. The last receipt table is saved in .claude/tmp/densepack-receipt-last.md,
and costs the conversation nothing to look at.

| /setpack argument | What it sets | Is this the default |
| --- | --- | --- |
| receipts default | One 6 column receipt table per batch, always ending in a BATCH TOTALS row | No |
| receipts verbose | The arithmetic split into columns, plus image sizes | No |
| receipts light | The compact 6 column table, no totals row of any kind, ever | No |
| receipts quiet | No receipt table in the reply. The last table is saved in .claude/tmp/densepack-receipt-last.md | YES |
| totals on | A CONVERSATION TOTALS row under every table too, below BATCH TOTALS | No |
| totals off | CONVERSATION TOTALS held back for the wrap up only | No |
| totals auto | The row follows the receipt mode: wrap up only in default, every table in verbose | YES |
| keep both | Copies of images and report text are kept | YES |
| keep off | No copies kept | No |
| agents | Nothing. Prints who was spawned this session and on what model | Sets nothing |
| vault | Nothing. Lists the vault, or sets its cap in megabytes | Sets nothing |

The reader is the one setting that belongs to a single conversation, so
dpctl.py reader has to be run inside the conversation it is for. /setpack
keep both sets both images and reports; dpctl keep images or keep reports
sets one, and takes a folder after it."""

def help_text():
    """HELP_TABLE without the rows for commands this copy does not ship.

    A help table that names a command the user cannot type is a stale row.
    A command row stays only when its <name>.md file sits in the commands
    folder beside this script, and the argument section stays only when its
    own command file is there."""
    commands = Path(__file__).resolve().parents[1] / "commands"
    text = HELP_TABLE
    head, marker, tail = text.partition("\nEvery other setting is one /setpack argument")
    if marker and not (commands / "setpack.md").is_file():
        text = head.rstrip() + "\n"
    # A behaviour row belongs to one script. A copy without that script,
    # such as the export, drops the row.
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
    "on": "conversation totals row under every table, beside the batch totals row that always prints",
    "off": "conversation totals row at wrap-up only, batch totals row still prints every table",
    "auto": "conversation totals row follows the mode, batch totals row still prints every table",
}


def status_line():
    current = settings(caller_session())
    # This window's own switch, not any other window's, so a second session's
    # /dense-off does not make this one report OFF while its hooks run.
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
        # The session running now, never a model name a finished session
        # left on disk.
        found = lead_model_name(session)
        how = ("read from the lead model %s" % found if found
               else "lead model not read yet, using the size both models read")

    # One image size serves every reader, so the status line names no tier.
    tier = ""
    return ("DensePack: packing %s, reader %s (%d px, %s)%s, "
            "receipts %s, totals %s (%s)%s, keep %s, style card %s, "
            "Sonnet images %s"
            % (packing, reader, CODE_PX, how, tier,
               current["receipts"], current["totals"],
               TOTALS_SAID[current["totals"]], quiet, keep,
               current.get("stylecard", "off"), current.get("maxpack", "on")))


# The model each reader profile names.
READER_NAMES = {"fable": "Fable 5", "opus": "Opus 5", "sonnet": "Sonnet 5"}


def remove_everything():
    """Delete every DensePack file that /plugin uninstall leaves behind.

    No hook runs on uninstall, so Claude Code deletes only the plugin's data
    folder, ~/.claude/plugins/data/<plugin>. This removes the rest: the
    machine folders under the home folder, the Python install markers, the
    bench folders, leftover render jobs in the temp folder, each project's
    vault and densepack files, and the trust entry of the marketplace folder,
    so a reinstall at the same path asks for trust again. It prints each
    path it removes."""
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

    # The originals come back before the state folder and the vaults go, because
    # the state file lists every converted CLAUDE.md and MEMORY.md.
    try:
        import pack_instructions
        for name in pack_instructions.restore_all():
            removed.append("the pointer in %s, original restored from its .densepack.bak" % name)
    except Exception as exc:  # noqa: BLE001
        print("Could not restore the converted instruction files: %s" % exc)

    for path in (home / ".claude" / "densepack-state", home / ".claude" / "densepack-cards",
                 home / ".claude" / "densepack-tracker.json", home / ".densepack",
                 home / "DensePack-arenas"):
        drop(path)
    if os.environ.get("LOCALAPPDATA"):
        drop(Path(os.environ["LOCALAPPDATA"]) / "densepack")
    for path in glob.glob(os.path.join(tempfile.gettempdir(), "densepack-trial-*.pkl")):
        drop(path)

    # Every folder Claude Code holds a conversation for. Each transcript line
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
    # This verb's words arrive as ONE quoted argument, so a stray ; or & the
    # user typed after the command never reaches the shell. They are split
    # here and only these letters survive. The colon and the backslash are in
    # the set because "keep" takes a folder and a Windows folder holds both.
    if argv and argv[0] == "setpack":
        words = " ".join(argv[1:]).split()
        argv = [w for w in words
                if all(c.isalnum() or c in "-_./:\\" for c in w)]
    verb = argv[0] if argv else "status"

    if verb == "status":
        # No argument: the status line below.
        pass

    elif verb == "remove":
        return remove_everything()

    elif verb == "mdpack":
        # The folder arrives as one quoted argument and may hold spaces.
        folder = " ".join(argv[1:]).strip().strip('"').strip("'")
        if not folder:
            print("Name a folder: /mdpack <folder>")
            return 1
        import pack_instructions
        for name, result in pack_instructions.convert_folder(folder):
            if result != "absent":
                print("%s: %s" % (name, result))
        print("A session started in that folder loads the pointer and reads the images. "
              "The original text stays beside each file as <name>.densepack.bak.")
        return 0

    elif verb == "on":
        # Both shapes. This window's own file, and any bare one left by an
        # older version or by a terminal run, because a bare
        # file stops every session and /densepack must not report the plugin
        # on while one sits there. Another window's file is left alone.
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
                  "The old words still work: full is verbose, line is "
                  "default, off is quiet")
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
            print("DensePack reads the lead's own model off the first "
                  "assistant line of this session's transcript. Every image "
                  "converts at one size, %d px, for every model. Right now: "
                  "%s." % (CODE_PX, resolved_reader(session)))
        else:
            print("DensePack reader set to %s, %s. Every image converts at "
                  "one size, %d px, for every model, so this changes the "
                  "name the plugin reports and no image. Set it back to auto "
                  "and the plugin reads the lead's model itself."
                  % (mode, READER_NAMES[mode], CODE_PX))

    elif verb == "stylecard":
        mode = argv[1] if len(argv) > 1 else ""
        if mode not in SETTINGS_ALLOWED["stylecard"]:
            print("stylecard needs on or off")
            return 1
        write_settings({"stylecard": mode})


    elif verb == "agents":
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
            print("The vault, oldest first. Every packed image and its source "
                  "text, one folder per conversation. Cap %d MB, and the "
                  "oldest folder goes first when it is reached."
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
        # A conversation id rather than a mode word means "save that one".
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
            # caller forgot quotes. Joining them back is always right, because
            # nothing else follows the folder.
            changes["keep_folder"] = " ".join(argv[2:])
        write_settings(changes)

    else:
        print("unknown verb %r. Verbs: status, on, off, remove, maxpack, maxoff, "
              "receipts, totals, keep, reader, stylecard, agents, vault, help"
              % verb)
        return 1

    print(status_line())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
