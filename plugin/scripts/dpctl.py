"""The control desk behind the slash commands. One verb per command.

HOW THIS FILE FITS, in plain words: the slash commands need to flip settings
without anyone hand-editing JSON. Each command runs this script with one verb,
the script writes the flag or the settings file the hooks already read, and
prints one plain line saying what the state now is. Nothing here touches
packing itself; the hooks read the state fresh on every event, so a change
takes effect at the very next agent.

  python dpctl.py status
  python dpctl.py on                        /densepack: packing on, defaults back
  python dpctl.py off                       /densepack-off: every hook stands down
  python dpctl.py agentpack force           /agentpack: delegation rules supersede,
                                             also the default, also set by "on"
  python dpctl.py agentpack off             /agentpack-off: no delegation rules
  python dpctl.py agentpack support         rules on, but secondary to other
                                             plugins'
  python dpctl.py receipts quiet            /quietpack
  python dpctl.py receipts default|verbose|light
                                            the receipt shapes, for the rare
                                             time one is wanted in the reply
  python dpctl.py receipts full|line|off    the old words, still accepted
  python dpctl.py totals on|off|auto        the CONVERSATION TOTALS row
  python dpctl.py status on|off             the delegation table in the reply
  python dpctl.py keep images|reports|both|off [folder]
                                            what copies survive the session
  python dpctl.py vault [megabytes]         list the vault, or set its cap
  python dpctl.py keep <conversation>       save one conversation out of it
  python dpctl.py reader auto|fable|opus|sonnet
                                            auto reads the lead's own model.
                                            /fablepack and /opuspack override it
  python dpctl.py maxtier on|off            /maxpack, and off again
  python dpctl.py stylecard on|off          /stylepack, /stylepack-off
  python dpctl.py agents                    who was spawned, and on what model
  python dpctl.py help                      /helppack: the command table

Every verb above is one /setpack argument, so a setting needs no command of
its own. Twelve commands that each set a single value were folded into
/setpack on 31 August 2026: agentpack-table, keeppack, keeppack-off,
lightpack, lightpack-off, maxpack-off, receiptpack, statuspack,
statuspack-off, totalpack, totalpack-off and verbosepack. No session record
on this machine showed ten of them ever being run. statuspack and
statuspack-off went for a different reason: the delegation table they
governed is on the dashboard page now, per conversation, beside the receipt
rows, where reading it costs the conversation nothing.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (disabled,
                    lead_model_name, font_size, keep_promote,
                    off_flag_path, resolved_reader, tmp_dir, vault_cap_bytes,
                    vault_folders, vault_trim,
                    OFF_FLAG,  # noqa: E402
                    READER_SIZES, RECEIPTS_ALIASES, SETTINGS_ALLOWED,
                    SETTINGS_DEFAULTS, read_leads, settings, tmp_dir,
                    write_settings)
from pointer import delegation_table  # noqa: E402

PROXY_PORT = 41100
PROXY_URL = "http://127.0.0.1:%d" % PROXY_PORT


def _settings_local():
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(root) / ".claude" / "settings.local.json"


def proxy_switch(mode):
    """Write or remove ANTHROPIC_BASE_URL in .claude/settings.local.json.

    No hook can set an environment variable for the Claude Code process that
    is already running; the hooks reference lists additionalContext,
    systemMessage and terminalSequence and nothing else. The settings file is
    read into the process environment at startup, so this takes effect at the
    NEXT session and the message says so.

    Switching it on and then not running proxy.py sends every request to a
    closed port and the session stops. That is why this is a command and not
    a default.
    """
    import json as _json

    path = _settings_local()
    try:
        conf = _json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        conf = {}
    env = conf.get("env") or {}

    if mode == "status":
        here = env.get("ANTHROPIC_BASE_URL")
        print("proxy: %s" % ("on, " + here if here else "off"))
        print("settings file: %s" % path)
        return 0

    if mode == "on":
        env["ANTHROPIC_BASE_URL"] = PROXY_URL
        # A base URL that is not Anthropic's own turns MCP tool search off,
        # which would put every deferred tool schema back into the context and
        # cost more than the proxy saves. Read from the environment variable
        # reference on 26 August 2026.
        env["ENABLE_TOOL_SEARCH"] = "true"
    else:
        env.pop("ANTHROPIC_BASE_URL", None)
        env.pop("ENABLE_TOOL_SEARCH", None)

    if env:
        conf["env"] = env
    else:
        conf.pop("env", None)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps(conf, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print("could not write %s: %s" % (path, exc))
        return 1

    if mode == "on":
        print("proxy on at %s, from the NEXT session." % PROXY_URL)
        print("Start it with: python plugin/scripts/proxy.py")
        print("With the proxy not running, every request fails. "
              "python dpctl.py proxy off removes it.")
    else:
        print("proxy off, from the next session. Requests go straight to the API.")
    return 0

QUIET_FLAG = "densepack-quiet"


def caller_session():
    """The session this dpctl call speaks for, or "" when it speaks for none.

    Claude Code exports CLAUDE_CODE_SESSION_ID into the environment of every
    Bash tool call, and the slash commands reach dpctl.py through the Bash
    tool, so the window that typed /densepack-off names itself. Nothing has to
    be threaded through a hook and nothing has to be guessed.

    Read live 31 August 2026 inside a Bash call: the variable held
    2ba3f5a4-e585-4eba-8f29-29a834e074c6, which is the id that project's
    densepack-lead-sessions.json carries for that window. It was the eighth of
    the ten ids on that list, not the last, so the read_leads()[-1] guess this
    replaced would have flipped the switch on a different window. It is also
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
    make /densepack-off do nothing at all.

    An empty leads list prunes nothing. It means no session has been recorded
    yet, not that every session is dead, and sweeping on it deleted a live
    neighbour's switch when this was first run in a fresh project, 31 August
    2026, tests/test_off_scope.py.
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

AGENTPACK_SAID = {
    "support": ("delegation rules on but SECONDARY, they yield to other "
                "plugins' and the user's own delegation rules"),
    "force": ("delegation rules FORCED, they supersede other delegation "
              "rules. The default"),
    "off": "delegation rules OFF, image packing and receipts unchanged",
}


# The /helppack output. Every "default" below was read off SETTINGS_DEFAULTS in
# common.py rather than remembered, and every "permanent" line names a
# behavior with no setting of its own, which was checked by grepping
# SETTINGS_ALLOWED for a key that controls it and finding none.
HELP_TABLE = """DensePack commands.

Permanent while DensePack is on. No command switches these off on their own,
only /densepack-off, which stops everything.

| Permanent behavior | What it does |
| --- | --- |
| The standing reminder | Before each of your messages the lead is told what a condensed image is and which size is in force |
| Report packing | Every finished subagent's report is drawn as an image when the image measures cheaper than the text |
| Brief packing | Every brief over the threshold is drawn as an image before the subagent starts, at the size the RECEIVING model reads |
| Cross model reporting | A Fable agent reporting to an Opus lead is drawn at 10 px, an Opus agent reporting to a Fable lead at 8 px. Not a setting |
| Refuse when worse | An image that would cost more than the words is thrown away and the words are sent |
| Never to an unmeasured model | Sonnet 5 and Haiku 4.5 get plain text. They have never been scored on a condensed image |
| The delivery rule | Every subagent is told how to return its report |
| The catch net | A subagent that ignores the rule is stopped and asked again |
| The manifest | Every agent that finishes gets a row, packed or not |
| The delegation log | Every agent SPAWNED gets a row too, before it finishes, holding the model it ran on. Recording only; /setpack status off stops the automatic PRINT of this log as a table, never the recording |

| Command | What it sets | Is this the default |
| --- | --- | --- |
| /densepack | Packing on, and every setting below back to its default | It IS the reset |
| /dpack | The same command, short. The d is for default | It IS the reset |
| /densepack-off | Every hook stands down | No |
| /fablepack | Images drawn at 8 px, for a Fable 5 lead. An override; auto is the default | No |
| /opuspack | Images drawn at 10 px, for an Opus 5 lead | No |
| /maxpack | An Opus lead may spawn Fable 5 subagents | No |
| /agentpack | DensePack's delegation rules beat other plugins' | YES |
| /agentpack-off | No delegation rules at all | No |
| /stylepack | The card carries the writing rules | No |
| /stylepack-off | They do not | YES |
| /quietpack | No receipt table in the reply | YES |
| /dashboard | Opens the live page: the bill, every pack and every agent, per conversation | Sets nothing |
| /helppack | Nothing. Prints this table | Sets nothing |
| /setpack | Takes a verb and a value and sets that one thing | Sets nothing on its own |

Every other setting is one /setpack argument, and needs no command of its
own. The receipt table and the delegation table are the two the conversation
used to print; both are on the dashboard page now, per conversation, and cost
the conversation nothing to look at.

| /setpack argument | What it sets | Is this the default |
| --- | --- | --- |
| receipts default | One 6 column receipt table per batch, always ending in a BATCH TOTALS row | No |
| receipts verbose | The arithmetic split into columns, plus image sizes | No |
| receipts light | The compact 6 column table, no totals row of any kind, ever | No |
| receipts quiet | No receipt table in the reply. The same as /quietpack | YES |
| totals on | A CONVERSATION TOTALS row under every table too, below BATCH TOTALS | No |
| totals off | CONVERSATION TOTALS held back for the wrap up only | No |
| totals auto | The row follows the receipt mode: wrap up only in default, every table in verbose | YES |
| keep both | Copies of images and report text are kept | No |
| keep off | No copies kept | YES |
| maxtier off | An Opus lead spawns Opus 5 and below only | YES |
| status on | The delegation table appends after every batch. Asked for again while already on, it prints once instead | No |
| status off | The delegation table stops appending. Every spawn is still recorded, and the dashboard still shows it | YES |
| agents | Nothing. Prints who was spawned this session and on what model | Sets nothing |
| agentpack support | Rules on, but secondary to other plugins' | No |
| vault | Nothing. Lists the vault, or sets its cap in megabytes | Sets nothing |

The reader is the one setting that belongs to a single conversation, since
31 August 2026, so dpctl.py reader has to be run inside the conversation it
is for. /setpack keep both sets both images and reports; dpctl keep images or
keep reports sets one, and takes a folder after it.

Twelve commands were folded into /setpack on 31 August 2026:
agentpack-table, keeppack, keeppack-off, lightpack, lightpack-off,
maxpack-off, receiptpack, statuspack, statuspack-off, totalpack,
totalpack-off and verbosepack. Ten of them no session record on this machine
showed ever being run. The other two, statuspack and statuspack-off, went
because the table they governed is on the dashboard now."""

TOTALS_SAID = {
    "on": "conversation totals row under every table, beside the batch totals row that always prints",
    "off": "conversation totals row at wrap-up only, batch totals row still prints every table",
    "auto": "conversation totals row follows the mode, batch totals row still prints every table",
}


def status_line():
    current = settings(caller_session())
    # This window's own switch, not any other window's. The status line used to
    # read the one bare file, so a second session's /densepack-off made this
    # one report OFF while its hooks were still running.
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
        # The session running now, never whatever name is on disk: the file
        # used to hold one bare model with no session on it, so a name from a
        # finished session was still being reported days later.
        found = lead_model_name(session)
        how = ("read from the lead model %s" % found if found
               else "lead model not read yet, using the size both models read")

    # Fable subagents are only ever restricted while the lead reads Opus, so
    # the line says so only then. On a Fable lead the words would be noise.
    tier = ""
    if reader == "opus":
        tier = (", fable agents allowed" if current.get("maxtier") == "on"
                else ", fable agents blocked (/maxpack allows)")
    return ("DensePack: packing %s, reader %s (%d px, %s)%s, agentpack %s, "
            "receipts %s, totals %s (%s)%s, keep %s, style card %s, "
            "delegation table %s"
            % (packing, reader, READER_SIZES.get(reader, 8), how, tier,
               current["agentpack"], current["receipts"], current["totals"],
               TOTALS_SAID[current["totals"]], quiet, keep,
               current.get("stylecard", "off"), current.get("status", "on")))


# The model each reader profile names, and the day its size was measured.
# These were two if-else expressions inside the message until 25 August 2026,
# which is why adding a third reader left the message naming the wrong model.
READER_NAMES = {"fable": "Fable 5", "opus": "Opus 5", "sonnet": "Sonnet 5"}
READER_DATES = {"fable": "14 August 2026", "opus": "18 August 2026",
                "sonnet": "25 August 2026"}


def main(argv):
    verb = argv[0] if argv else "status"

    if verb == "status":
        # No argument: just print the status line below, unchanged behavior.
        # An argument sets the "status" setting, the automatic delegation
        # table toggle behind /setpack status on and /setpack status off.
        if len(argv) > 1:
            mode = argv[1]
            if mode not in SETTINGS_ALLOWED["status"]:
                print("status needs on or off")
                return 1
            was_on = settings()["status"] == "on"
            write_settings({"status": mode})
            if mode == "on":
                # /setpack status on prints the table every time it turns the setting
                # on. Until 24 August 2026 it printed only when the setting was
                # already on, so a user turning it on saw a status line and had
                # to type the command a second time to see anything. The table
                # is what the command is for, so the command shows the table.
                #
                # The state line goes ABOVE the table, so the reader knows
                # whether this call changed anything before reading the rows.
                session = read_leads()[-1] if read_leads() else ""
                print("DensePack delegation table was already on."
                      if was_on else
                      "DensePack delegation table is now on, and appends "
                      "after every batch from here.")
                print("Every agent this session has spawned:")
                print("\n".join(delegation_table(session)))

    elif verb == "on":
        # Both shapes. This window's own file, and any bare one left by a
        # version before 31 August 2026 or by a terminal run, because a bare
        # file stops every session and /densepack must not report the plugin
        # on while one sits there. Another window's file is left alone.
        off_flag_path(caller_session()).unlink(missing_ok=True)
        (tmp_dir() / OFF_FLAG).unlink(missing_ok=True)
        (tmp_dir() / QUIET_FLAG).unlink(missing_ok=True)
        prune_off_flags()
        write_settings(dict(SETTINGS_DEFAULTS))

    elif verb == "off":
        session = caller_session()
        off_flag_path(session).write_text(
            "set by /densepack-off%s\n"
            % (" in session " + session if session else ", no session"),
            encoding="utf-8")
        prune_off_flags(keep=session)

    elif verb == "agentpack":
        mode = argv[1] if len(argv) > 1 else ""
        if mode not in SETTINGS_ALLOWED["agentpack"]:
            print("agentpack needs one of: support, force, off")
            return 1
        write_settings({"agentpack": mode})
        print("DensePack agentpack set to %s: %s. The briefing follows at the "
              "next session start." % (mode, AGENTPACK_SAID[mode]))
        return 0

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
        # "two readers" is the MEASUREMENT that picked the size, not run-time
        # behavior. One agent reads one image. The old wording read as though
        # two agents ran per request and doubled the cost.
        if mode == "auto":
            print("DensePack reads the lead's own model off the first "
                  "assistant line of this session's transcript and draws at "
                  "the size that model was measured to read: 8 px for Fable 5, "
                  "10 px for Opus 5, 12 px for Sonnet 5. A model that was "
                  "never measured gets 10 px, a size two of the three read "
                  "with every answer exact. Right now: %s, %d px."
                  % (resolved_reader(session),
                     READER_SIZES[resolved_reader(session)]))
        else:
            print("DensePack reader set to %s: every image from the next agent "
                  "on is drawn at %d px. That is the smallest size %s read "
                  "without a single mistake when it was measured on %s. One "
                  "agent reads one image. Set it back to auto and the plugin "
                  "reads the lead's model itself."
                  % (mode, READER_SIZES[mode], READER_NAMES[mode],
                     READER_DATES[mode]))

    elif verb == "stylecard":
        mode = argv[1] if len(argv) > 1 else ""
        if mode not in SETTINGS_ALLOWED["stylecard"]:
            print("stylecard needs on or off")
            return 1
        write_settings({"stylecard": mode})

    elif verb == "proxy":
        mode = argv[1] if len(argv) > 1 else ""
        if mode not in ("on", "off", "status"):
            print("proxy needs on, off or status")
            return 1
        return proxy_switch(mode)

    elif verb == "maxtier":
        mode = argv[1] if len(argv) > 1 else ""
        if mode not in SETTINGS_ALLOWED["maxtier"]:
            print("maxtier needs on or off")
            return 1
        write_settings({"maxtier": mode})
        if mode == "on":
            print("DensePack maxtier ON: while the reader is opus the lead may "
                  "now spawn Fable 5 subagents. Cross model image reporting is "
                  "unchanged, because it is on always and is not a setting.")
        else:
            print("DensePack maxtier OFF: while the reader is opus the lead "
                  "spawns Opus 5 and below only, so a plan without Fable is "
                  "never billed for one. Cross model image reporting is "
                  "unchanged, because it is on always and is not a setting.")

    elif verb == "agents":
        session = read_leads()[-1] if read_leads() else ""
        print("\n".join(delegation_table(session)))
        return 0

    elif verb == "help":
        print(HELP_TABLE)
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
        print("unknown verb %r. Verbs: status, on, off, agentpack, receipts, "
              "totals, keep, reader, maxtier, stylecard, agents, vault, help"
              % verb)
        return 1

    print(status_line())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
