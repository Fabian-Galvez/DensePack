"""Check one bench pair and print whether it counts.

    python bench/check_bench_pairs.py bench/rows/<run name>-rows.jsonl

The rows file holds one off arm and one or more on arms. The checker prints
one line per arm, the saving at both prices, and one verdict word.

    COUNTS    the pair counts at both prices
    PARTIAL   the pair counts at the cold price only
    FAILS     the on arm answered fewer questions, or it cost as much or more
    DISCARD   the pair measured nothing, so it does not count

The rules, and why each one exists:

  valid            an arm with an API error or a refused tool call measured nothing
  images           the on arm must get at least one image and the off arm none,
                   or the pair does not compare images with text
  score            the on arm must answer as many questions as the off arm
  cold price       the on arm must cost less than the off arm at the cold price
  first cache read both arms must start with the same cached tokens for the
                   billed price to count; the cold price removes that difference

Turns and Reads are printed and never decide the verdict. The price already
counts every turn an arm takes. An image arm can take more turns, or read only
the images it needs, and still cost less.
"""
import json
import sys


def load(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line.startswith("{"):
            rows.append(json.loads(line))
    return rows


def saving(off, on):
    return 100.0 * (off - on) / off if off else 0.0


def mean(values):
    return sum(values) / float(len(values)) if values else 0.0


def right(row):
    score = row.get("score") or []
    return score[0] if score else 0


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        print("usage: python bench/check_bench_pairs.py bench/rows/<run name>-rows.jsonl")
        return 2
    rows = load(sys.argv[1])
    # Rows from bench/run_bench_arm.py carry result_kinds and turns_usage but
    # no images or first_cache_read field, so both come from those two.
    for r in rows:
        if r.get("images") is None and r.get("result_kinds") is not None:
            r["images"] = sum(1 for k in r["result_kinds"] if "image" in k)
        if r.get("first_cache_read") is None and r.get("turns_usage"):
            r["first_cache_read"] = r["turns_usage"][0][1]
    offs = [r for r in rows if r.get("arm") == "off"]
    ons = [r for r in rows if r.get("arm") == "on"]
    if not offs or not ons:
        print("DISCARD  the file needs one off arm and at least one on arm")
        return 1
    # The newest off arm is the one compared. An older off arm in the same
    # file belongs to an earlier try of the same run name.
    off = offs[-1]
    arms = [off] + ons

    print("bench   %s" % off.get("bench"))
    print("model   %s" % off.get("model"))
    print()
    print("arm   valid  score    turns  reads  images  first cache read  billed $   cold $")
    discard = []
    for r in arms:
        reads = sum(1 for c in (r.get("calls") or []) if c == "Read")
        images = r.get("images") or 0
        if not r.get("valid"):
            discard.append("%s arm: not valid, %s" % (r["arm"], "; ".join(r.get("problems") or [])))
        if r["arm"] == "on" and images == 0:
            discard.append("on arm: it got no image")
        if r["arm"] == "off" and images != 0:
            discard.append("off arm: it got %d images" % images)
        score = r.get("score") or []
        print("%-5s %-6s %-8s %-6s %-6s %-7s %-17s %-10.6f %.4f"
              % (r["arm"], r.get("valid"), "%s of %s" % tuple(score) if len(score) == 2 else score,
                 r.get("turns"), reads, images, r.get("first_cache_read"),
                 r.get("cli_cost") or 0.0, r.get("money") or 0.0))

    good = [r for r in ons if r.get("valid")]
    billed_on = mean([r.get("cli_cost") or 0.0 for r in good])
    cold_on = mean([r.get("money") or 0.0 for r in good])
    billed_saved = saving(off.get("cli_cost") or 0.0, billed_on)
    cold_saved = saving(off.get("money") or 0.0, cold_on)
    # An arm with an API error has no first cache read, and None does not sort
    # against a number.
    starts = sorted({r.get("first_cache_read") for r in arms},
                    key=lambda v: (v is None, v or 0))
    print()
    print("saved   %.1f%% as billed, %.1f%% cold" % (billed_saved, cold_saved))
    print("first cache read  %s, %s" % (starts, "the same" if len(starts) == 1 else "different"))
    print()

    if discard:
        print("DISCARD")
        for why in discard:
            print("   %s" % why)
        return 1
    fails = []
    fewer = [r for r in good if right(r) < right(off)]
    if fewer:
        fails.append("the image arm missed %d of the questions the text arm answered: "
                     "%d right against %d"
                     % (right(off) - right(fewer[0]), right(fewer[0]), right(off)))
    if cold_on >= (off.get("money") or 0.0):
        fails.append("the on arm cost $%.4f cold and the off arm $%.4f" % (cold_on, off.get("money") or 0.0))
    if fails:
        print("FAILS")
        for why in fails:
            print("   %s" % why)
        print("   DensePack normally answers every question and costs less.")
        print("   Ask the user whether to investigate this pair before the next one.")
        return 1
    if len(starts) != 1:
        print("PARTIAL   the pair saved %.1f%% at the cold price. Use the cold price for this pair." % cold_saved)
        print("          The image arm loads the plugin, so it started with more cached tokens than the text arm.")
        print("          The billed saving compares unequal starts, and the cold price charges both arms as fresh starts.")
        print("          PARTIAL is normal for the 16-file and 32-file benches, and nothing went wrong.")
        return 0
    print("COUNTS    the pair counts at both prices: %.1f%% as billed, %.1f%% cold." % (billed_saved, cold_saved))
    return 0


if __name__ == "__main__":
    sys.exit(main())
