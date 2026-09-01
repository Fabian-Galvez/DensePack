"""What one conversation cost, split by token kind, and what DensePack saved.

    python bench/session_cost.py                 the current lead session
    python bench/session_cost.py <transcript>    any .jsonl transcript

THE FOUR KINDS OF TOKEN A CONVERSATION BILLS. Every request the harness sends
carries the whole conversation so far, so three of the four are re-billed on
every single turn.

    input_tokens                 fresh text this request added and that was
                                 not served from the cache
    cache_creation_input_tokens  text written into the cache this request, so
                                 later requests can read it cheaply
    cache_read_input_tokens      text served from the cache, which is the
                                 whole conversation so far on almost every
                                 turn. The biggest count in any long session
    output_tokens                what the assistant wrote, thinking included.
                                 The smallest count and the dearest rate

There is no separate reasoning token field in the transcript. Thinking is
billed inside output_tokens. There are no "action" or "wall" tokens; wall
clock is seconds, not tokens, and it is not billed.

RATES, dollars per million, read from the Claude API model table on
26 August 2026. A five minute cache write costs 1.25 times input, a one hour
cache write costs 2 times input, and a cache read costs a tenth of input.
"""
import datetime
import json
import os
import pathlib
import re
import sys

RATES = {
    "opus": (5.00, 25.00),
    "fable": (10.00, 50.00),
    # Sonnet 5 bills 2.00 and 10.00; Sonnet 4.6 bills 3.00 and 15.00.
    # Both carry "sonnet" in the id, so family() matches the versioned
    # key first. The flat 3.00/15.00 here priced every Sonnet 5 token
    # 50 per cent high, found 31 August 2026 against the API model table.
    "sonnet-5": (2.00, 10.00),
    "sonnet": (3.00, 15.00),
    "haiku": (1.00, 5.00),
}

# Claude Code names a project folder after the working directory the CLI
# was started in, every character that is not a letter or a digit replaced
# by a dash: bench/run_leg.py's projects_dir_for() derives a leg's folder
# the same way. This used to name one machine's owner and one fixed
# working directory outright, so a checkout under a different account or a
# different drive read someone else's empty folder and nothing here ever
# resolved. Deriving it from the home folder and the current working
# directory at import time is what makes a fresh machine watch its own
# conversations instead.
PROJECTS = pathlib.Path(os.path.expanduser("~"), ".claude", "projects",
                        re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(os.getcwd())))
def _lead_file():
    here = pathlib.Path.cwd()
    for folder in (here, *here.parents):
        cand = folder / ".claude" / "tmp" / "densepack-lead-session"
        if cand.is_file():
            return cand
    return here / ".claude" / "tmp" / "densepack-lead-session"


LEAD = _lead_file()

# The four fields, in the order they are explained above.
FIELDS = ("input_tokens", "cache_creation_input_tokens",
          "cache_read_input_tokens", "output_tokens")

PLAIN = {
    "input_tokens": "Fresh input, not cached",
    "cache_creation_input_tokens": "Cache write",
    "cache_read_input_tokens": "Cache read, the conversation so far",
    "output_tokens": "Output, thinking included",
}


def family(model):
    low = str(model or "").lower()
    for name in RATES:
        if name in low:
            return name
    return "opus"


def price(field, model):
    """Dollars per token for one field on one model."""
    inp, out = RATES[family(model)]
    if field == "output_tokens":
        return out / 1e6
    if field == "cache_creation_input_tokens":
        # The transcript does not record which time to live was bought. The
        # five minute rate is used, which is the cheaper of the two, so this
        # figure is a floor and never an overstatement.
        return inp * 1.25 / 1e6
    if field == "cache_read_input_tokens":
        return inp * 0.1 / 1e6
    return inp / 1e6


def read(path):
    """Totals for one transcript, counted one record per message id.

    A split assistant message writes its usage more than once, partial records
    first and the final one last, all under the same message id. Summing every
    record roughly triples a live session (measured 29 August 2026: 154 usage
    records, 47 message ids, 9,674,267 tokens summed raw against 3,280,496
    counted once). The last record per id is the one that counts, the rule
    recorded in bench/TOTALS.md.
    """
    seen = {}
    order = []
    model = ""
    stamps = []
    lines = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            lines += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            # The conversation's own clock, for claiming manifest rows that
            # carry no session. Stored as ISO text with a trailing Z.
            when = row.get("timestamp")
            if isinstance(when, str):
                try:
                    stamps.append(datetime.datetime.fromisoformat(
                        when.replace("Z", "+00:00")).timestamp())
                except ValueError:
                    pass
            message = row.get("message") or {}
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            model = message.get("model") or model
            key = message.get("id") or ("line-%d" % lines)
            if key not in seen:
                order.append(key)
            seen[key] = (usage, model, stamps[-1] if stamps else 0.0)
    counts = dict.fromkeys(FIELDS, 0)
    money = dict.fromkeys(FIELDS, 0.0)
    turn_times = []
    for key in order:
        usage, row_model, stamp = seen[key]
        if stamp:
            turn_times.append(stamp)
        for field in FIELDS:
            n = int(usage.get(field) or 0)
            counts[field] += n
            money[field] += n * price(field, row_model)
    return (counts, money, len(order), model,
            min(stamps) if stamps else 0.0,
            max(stamps) if stamps else 0.0,
            sorted(turn_times))


def saved_by_densepack(session, first, last, turn_times):
    """Tokens DensePack kept out of this conversation, from its own manifest.

    Every packed row records what the words would have cost as text and what
    the picture cost instead. The difference is the saving on the turn it
    happened. A saving also repeats, because text kept out of turn N is kept
    out of every turn after N, but the manifest does not record turn numbers,
    so only the one-time figure is counted here. It is a floor.

    SCOPING. A row written by bash_pack.py before 26 August 2026 carries a
    blank spawned_by, because the packer was never told which session it was
    serving. Measured that day: 789 of 939 packed rows had none, so counting
    by session alone returned two rows and counting blanks as this session's
    returned every session's history. A row with no session is claimed by its
    own timestamp instead, and only when that timestamp falls between this
    conversation's first and last packed row. bash_pack.py now records the
    session, so this fallback ages out.
    """
    path = LEAD.parent / "densepack-manifest.jsonl"
    if not path.is_file():
        return 0, 0, 0, 0, 0
    text = image = rows = dated = 0
    weighted = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not row.get("packed"):
            continue
        owner = str(row.get("spawned_by") or "")
        if owner and owner != str(session):
            continue
        if not owner:
            when = row.get("ended") or row.get("captured") or 0
            if not (first <= float(when) <= last):
                continue
            dated += 1
        saving = int(row.get("text_tokens") or 0) - int(row.get("image_tokens") or 0)
        text += int(row.get("text_tokens") or 0)
        image += int(row.get("image_tokens") or 0)
        rows += 1
        # Every turn after this pack would have re-read the text.
        when = float(row.get("ended") or row.get("captured") or 0)
        after = sum(1 for stamp in turn_times if stamp > when)
        weighted += saving * after
    return text, image, rows, dated, weighted


def group(n):
    return format(int(n), ",")


def main():
    if len(sys.argv) > 1:
        path = pathlib.Path(sys.argv[1])
        session = path.stem
    else:
        session = LEAD.read_text(encoding="utf-8").strip()
        path = PROJECTS / ("%s.jsonl" % session)
    if not path.is_file():
        sys.exit("no transcript at %s" % path)

    counts, money, turns, model, first, last, turn_times = read(path)
    total_tokens = sum(counts.values())
    total_money = sum(money.values())

    print("Transcript: %s" % path.name)
    print("Model: %s, requests with a usage record: %d" % (model, turns))
    print("")
    print("| Token kind | What it is | Tokens | Share of tokens | Dollars | Share of cost |")
    print("| --- | --- | --- | --- | --- | --- |")
    for field in FIELDS:
        print("| %s | %s | %s | %.1f per cent | %.4f | %.1f per cent |" % (
            field, PLAIN[field], group(counts[field]),
            counts[field] / total_tokens * 100 if total_tokens else 0,
            money[field],
            money[field] / total_money * 100 if total_money else 0))
    print("| TOTAL | Everything this conversation billed | %s | 100.0 per cent | %.4f | 100.0 per cent |"
          % (group(total_tokens), total_money))

    text, image, rows, dated, weighted = saved_by_densepack(
        session, first, last, turn_times)
    if not rows:
        return 0
    saved = text - image
    rate = price("cache_read_input_tokens", model)
    fresh = price("input_tokens", model)
    print("")
    print("| DensePack in this conversation | Value |")
    print("| --- | --- |")
    print("| Things it packed | %s |" % group(rows))
    print("| Of those, claimed by their timestamp because the row carries no session | %s |"
          % group(dated))
    print("| Tokens the words would have cost | %s |" % group(text))
    print("| Tokens the pictures cost instead | %s |" % group(image))
    print("| Tokens saved, counted once | %s |" % group(saved))
    print("| Saved as a share of this conversation's tokens | %.1f per cent |"
          % (saved / (total_tokens + saved) * 100 if total_tokens else 0))
    print("| Dollars saved if that text were fresh input | %.4f |" % (saved * fresh))
    print("| Dollars saved if that text were a cache read | %.4f |" % (saved * rate))
    print("| Tokens saved counting every later turn that would have re-read it | %s |"
          % group(weighted))
    print("| Dollars saved counting every later turn, at the cache read rate | %.4f |"
          % (weighted * rate))
    print("| That saving as a share of what this conversation actually billed | %.1f per cent |"
          % (weighted * rate / (total_money + weighted * rate) * 100
             if total_money else 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
