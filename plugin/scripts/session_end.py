"""Runs when the conversation closes. The final bill.

HOW THIS FILE FITS, in plain words: adds up everything pointer.py recorded and
writes one small table, total cost as words, total cost as pictures, total
saved. A closing conversation cannot speak, so the table waits on disk and
bootstrap.py hands it over the moment the next conversation opens.

ORIGINAL NOTE: SessionEnd hook. Roll the conversation's totals into the final summary table.

A session that ends cannot print into the conversation, and Claude Code
discards a SessionEnd hook's JSON output fields, systemMessage included, so
nothing this hook returns reaches anyone. The summary is written to a file and
the next session's start hook shows it to the user. The totals reset so the
next conversation counts from zero.
"""

import sys

from common import (disabled, read_event, read_totals, receipts_mode, tmp_dir,
                    totals_path)
from pointer import RECEIPT_FILE, totals_table


def main():
    # The event is read before the switch is checked, because the off
    # switch is per session since 31 August 2026 and the id that names
    # the session is on the event.
    event = read_event()
    if disabled(event.get("session_id")):
        return 0
    totals = read_totals()
    # Briefs count as well as reports. This read "reports" alone until 19
    # August 2026, so a conversation that packed only outbound briefs and got
    # no report back filed nothing: the user was never billed for the saving,
    # and because the totals file is not cleared, those tokens were counted
    # again in the next conversation's figures.
    if not totals.get("reports") and not totals.get("briefs"):
        return 0

    # The same mode the receipts use. A user who set quiet is not greeted next
    # session with the very table they silenced.
    mode = receipts_mode()
    table = totals_table(totals, mode)
    # The user reads this line now that the next session start shows it
    # directly, so it counts in words that match the number.
    def plural(number, word):
        return "%d %s%s" % (number, word, "" if number == 1 else "s")

    count = ("DensePack totals for the conversation that just ended, %s, %s:"
             % (plural(totals["reports"], "report"),
                plural(totals.get("images", 0), "image")))

    if mode == "quiet":
        # Quiet still files the numbers. The lead is told where they are and
        # shows them only when the user asks.
        receipt = tmp_dir() / RECEIPT_FILE
        receipt.write_text("\n".join([count, ""] + table) + "\n",
                           encoding="utf-8")
        summary = ("DensePack receipts are quiet. Last conversation's totals "
                   "are in %s . Show that table only if the user asks for "
                   "one.\n" % receipt)
    else:
        # No imperative here any more. The file used to open with "Show the
        # user this table exactly as written", which is a rule the lead had to
        # obey, and the lead skipped the same kind of rule seven times in one
        # session on 19 August 2026. The next session's start hook now puts
        # this table in systemMessage, which Claude Code shows the user
        # directly. It tells the two shapes apart by the table rows, so the
        # quiet summary above must stay free of the pipe character.
        summary = "\n".join([count, ""] + table + [""])

    (tmp_dir() / "densepack-last-session.md").write_text(summary, encoding="utf-8")
    totals_path().unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
