"""Record one side of an on-against-off comparison.

HOW THIS FILE FITS, in plain words: every saving figure this plugin publishes
is measured on one side and worked out for the other. This records a real
before and after around a piece of real work, so the two sides can be compared
without reconstructing either. Run it before the work and again after, once
with the plugin on and once with it off.

WHAT IT RECORDS. The transcript's four billed token totals, which are exact,
and the plan meter, which is coarse but is what a subscription enforces. The
transcript is the instrument; the meter is there so the answer can be stated
in plan per cent as well as tokens.

Run:  python tools/ab_run.py <transcript.jsonl> on before
      python tools/ab_run.py <transcript.jsonl> on after
      python tools/ab_run.py <transcript.jsonl> off before
      python tools/ab_run.py <transcript.jsonl> off after
      python tools/ab_run.py <transcript.jsonl> --report
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import plan_watch as pw  # noqa: E402

RECORD = "densepack-ab.jsonl"

# Measured 25 August 2026 by watching the five hour meter cross twice, with
# each crossing bracketed by the readings either side of it.
TOKENS_PER_PLAN_POINT = 18054707


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("side", nargs="?", choices=("on", "off"))
    ap.add_argument("when", nargs="?", choices=("before", "after"))
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    out = Path(args.transcript).parent / RECORD

    if not args.report:
        if not args.side or not args.when:
            sys.exit("name the side, on or off, and when, before or after")
        row = pw.snapshot(args.transcript)
        row["side"] = args.side
        row["when"] = args.when
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print("| Recorded | Value |")
        print("| --- | --- |")
        print("| Side | %s, %s |" % (args.side, args.when))
        print("| Turns so far | %s |" % format(row["totals"]["turns"], ","))
        print("| Tokens so far | %s |"
              % format(sum(row["totals"][f] for f in pw.FIELDS), ","))
        print("| Five hour window | %s |" % row["meter"]["5h"])
        return

    if not out.is_file():
        sys.exit("nothing recorded yet")
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()
            if l.strip()]

    sides = {}
    for side in ("on", "off"):
        before = next((r for r in rows
                       if r["side"] == side and r["when"] == "before"), None)
        after = next((r for r in reversed(rows)
                      if r["side"] == side and r["when"] == "after"), None)
        if not before or not after:
            continue
        sides[side] = {
            name: after["totals"][name] - before["totals"][name]
            for name in pw.FIELDS
        }
        sides[side]["turns"] = after["totals"]["turns"] - before["totals"]["turns"]

    if len(sides) < 2:
        print("| Side | Recorded |")
        print("| --- | --- |")
        for side in ("on", "off"):
            print("| %s | %s |" % (side, "both ends" if side in sides
                                   else "not both ends yet"))
        return

    print("| Quantity | Plugin on | Plugin off | Difference |")
    print("| --- | --- | --- | --- |")
    for name in ("turns",) + pw.FIELDS:
        a, b = sides["on"][name], sides["off"][name]
        print("| %s | %s | %s | %s |"
              % (name, format(a, ","), format(b, ","), format(b - a, ",")))

    total_on = sum(sides["on"][f] for f in pw.FIELDS)
    total_off = sum(sides["off"][f] for f in pw.FIELDS)
    saved = total_off - total_on
    print()
    print("| Result | Value |")
    print("| --- | --- |")
    print("| Tokens the same work spent with the plugin on | %s |"
          % format(total_on, ","))
    print("| Tokens the same work spent with it off | %s |"
          % format(total_off, ","))
    print("| Saved | %s, %.2f per cent |"
          % (format(saved, ","),
             100.0 * saved / total_off if total_off else 0.0))
    print("| Five hour plan window that saves | %.3f per cent |"
          % (100.0 * saved / (TOKENS_PER_PLAN_POINT * 100)))


if __name__ == "__main__":
    main()
