"""Runs when the conversation ends and writes the totals of the conversation.

This hook adds up the totals that pointer.py records and writes one small
table with the total cost as text, the total cost as images and the total
saved.

A session that ends cannot print into the conversation, because Claude Code
discards the JSON output fields of a SessionEnd hook, systemMessage
included. For that reason this hook writes the summary to
densepack-last-session.md. At the next session start, deliver_context() in
bootstrap.py reads that file, shows the table on screen unless receipts are
quiet, and deletes the file. This hook also deletes densepack-totals.json,
and the next conversation counts from zero. An empty .claude/tmp after
several sessions is the normal result.

Claude Code runs SessionEnd after SessionStart and Stop, also for a
claude -p run. Claude Code closes the transcript before this hook runs, and
a transcript has no SessionEnd row. A conversation that packed no report and
no brief writes no totals, and this hook then writes nothing.
"""

import sys

from common import (disabled, read_event, read_totals, receipts_mode, tmp_dir,
                    totals_path)
from pointer import RECEIPT_FILE, totals_table


def main():
    # The hook reads the event before it checks the off switch. The off
    # switch is per session, and the session id is on the event.
    event = read_event()
    if disabled(event.get("session_id")):
        return 0
    totals = read_totals()
    # Briefs count as well as reports. A conversation that packed only
    # outbound briefs still writes its saving and deletes the totals file.
    if not totals.get("reports") and not totals.get("briefs"):
        return 0

    # This is the same mode that the receipts use. When you set quiet, the
    # next session does not show the table on screen.
    mode = receipts_mode()
    table = totals_table(totals, mode)
    # The next session start shows this line to you on screen. plural()
    # makes each word match its number.
    def plural(number, word):
        return "%d %s%s" % (number, word, "" if number == 1 else "s")

    count = ("DensePack totals for the conversation that ended, %s, %s:"
             % (plural(totals["reports"], "report"),
                plural(totals.get("images", 0), "image")))

    if mode == "quiet":
        # Quiet mode still writes the numbers to a file. The note tells the
        # model where the file is. The model shows the table only when you
        # ask.
        receipt = tmp_dir() / RECEIPT_FILE
        receipt.write_text("\n".join([count, ""] + table) + "\n",
                           encoding="utf-8")
        summary = ("DensePack receipts are quiet. Last conversation's totals "
                   "are in %s . Show that table only if the prompt asks for "
                   "one.\n" % receipt)
    else:
        # The start hook of the next session puts this table in
        # systemMessage, and Claude Code shows it on screen. The file holds
        # no instruction for the model. The start hook finds the table by
        # its rows, which start with the pipe character. The quiet summary
        # above must not contain a line that starts with the pipe character.
        summary = "\n".join([count, ""] + table + [""])

    # The next session start reads this file as text from the plugin. The
    # file is outside the project. A cloned project cannot put a false copy
    # there.
    from common import machine_state_dir
    (machine_state_dir() / "densepack-last-session.md").write_text(summary, encoding="utf-8")
    totals_path().unlink(missing_ok=True)
    return 0


def guarded_main():
    """Catch each exception that main() raises.

    main() runs inside a try. A fault in main() cannot change the result of
    the event that started the hook. The hook writes the error to stderr,
    where it stays visible. The exit code stays 0.
    """
    try:
        return main()
    except Exception as err:  # noqa: BLE001
        sys.stderr.write("DensePack %s: %s\n" % ("session_end.py", err))
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
