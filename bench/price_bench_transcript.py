"""Pools the on-against-off pairs, one configuration at a time, and prints
each configuration's figures separately.

Reads the pairs file named as its first argument, one row per side per pair, "side index transcript". For each
transcript it sums the four billed token fields, one usage record per message
id keeping the last record written, prices them at the rate the runs were
billed at, and adds every subagent transcript's usage to the lead's, because a
subagent's tokens are spent by the same run and are not in the lead file.

A pair counts only when both sides finished and made the same number of lead
tool calls. The pooled figure is the sum of the on side over the sum of the off
side across the usable pairs, never a mean of per pair percentages, so a large
pair carries the weight its size earns. Rows of different configurations never
pool together: GROUPS names each configuration's rows and each prints alone.
"""
import glob
import json
import re
import sys
from pathlib import Path

FIELDS = ("input_tokens", "cache_creation_input_tokens",
          "cache_read_input_tokens", "output_tokens")

# The three input fields, summed: fresh input, cache writes and cache reads.
INPUT_FIELDS = ("input_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens")

# Dollars per token, at the rates the run's own model bills. The table is
# bench/session_cost.py's RATES, the same one tools/live_dashboard.py
# imports, so the card and the dashboard cannot drift apart. Until
# 4 September 2026 this file held Claude Sonnet 5's 2.00 and 10.00 against
# every model, which read an Opus pair 2.5 times low and a Fable pair about
# 4.6 times low; bench/abgd-opus-2026-09-04.md holds that measurement.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_cost import RATES, family  # noqa: E402


def rates(model):
    """The five per-token rates one model bills at.

    Input, output, the five minute cache write, the one hour cache write
    and the cache read. A cache write costs 1.25 times input at the five
    minute time to live and 2 times input at one hour; a cache read costs
    a tenth of input, the ratio session_cost.py charges every model.
    Claude Fable 5.1 bills 0.25 dollars per million on cache reads, 0.025
    of its input, and this function prices it so.
    """
    inp, out = RATES[family(model)]
    # Fable 5.1 and Mythos 5.1 bill cache reads at 0.025 of input, 0.25
    # dollars a million, per the pricing page read 13 September 2026. Fable 5
    # bills 0.1 like every other model. Until this date every Fable 5.1 leg
    # was priced at the Fable 5 read rate.
    name = str(model or "").lower()
    read_share = 0.025 if re.search(r"(fable|mythos)[-_ ]?5[-_.]1", name) else 0.1
    return (inp / 1e6, out / 1e6, inp * 1.25 / 1e6,
            inp * 2.0 / 1e6, inp * read_share / 1e6)

# The words bash_pack.py's pointer starts with. A packed result begins a line
# with them. The repo's own sources hold the same words and task command 6
# prints them, but grep puts file:line: in front, so a line-start test never
# matches an off side run.
PACK_MARK = "DensePack: command output packed as"


def read_run(path):
    """One transcript's usage, tool calls, turns and packed results."""
    out = dict.fromkeys(FIELDS, 0)
    out.update(money=0.0, tokens=0, turns=0, calls=0, packed=0, done=False,
               spawns=0, bash=0)
    usage_by_id = {}
    model = ""
    no_id = 0
    try:
        text = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        message = row.get("message") or {}
        content = message.get("content")

        usage = message.get("usage")
        model = message.get("model") or model
        if isinstance(usage, dict):
            # One assistant message can be written to the transcript more than
            # once under one message id, and a split message carries a PARTIAL
            # output count on its first record and the final count on a later
            # one, so the LAST record per id is the one that counts. Verified
            # 29 August 2026 on off pair 1's subagent transcript
            # agent-<agent id>.jsonl: one message
            # id has output_tokens=5 on its first
            # record and 155 on its last. Keeping the first record, as this
            # function did before that date, undercounted output tokens.
            key = message.get("id")
            if key is None:
                no_id += 1
                key = ("no-id", no_id)
            usage_by_id[key] = usage

        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    out["calls"] += 1
                    name = block.get("name")
                    if name in ("Agent", "Task"):
                        out["spawns"] += 1
                    elif name == "Bash":
                        out["bash"] += 1
                if block.get("type") == "text" and "DONE" in str(block.get("text") or ""):
                    out["done"] = True
                if block.get("type") == "tool_result":
                    body = block.get("content")
                    if isinstance(body, list):
                        body = "\n".join(
                            b.get("text", "") for b in body
                            if isinstance(b, dict) and b.get("type") == "text")
                    for one in str(body or "").splitlines():
                        if one.startswith(PACK_MARK):
                            out["packed"] += 1
    IN, OUT, WRITE_5M, WRITE_1H, READ = rates(model)
    for usage in usage_by_id.values():
        out["turns"] += 1
        for name in FIELDS:
            out[name] += int(usage.get(name) or 0)
        creation = usage.get("cache_creation")
        write_5m = write_1h = 0
        if isinstance(creation, dict):
            write_5m = int(creation.get("ephemeral_5m_input_tokens") or 0)
            write_1h = int(creation.get("ephemeral_1h_input_tokens") or 0)
        if not (write_5m or write_1h):
            write_5m = int(usage.get("cache_creation_input_tokens") or 0)
        out["money"] += (
            int(usage.get("input_tokens") or 0) * IN
            + write_5m * WRITE_5M + write_1h * WRITE_1H
            + int(usage.get("cache_read_input_tokens") or 0) * READ
            + int(usage.get("output_tokens") or 0) * OUT)
    out["tokens"] = sum(out[name] for name in FIELDS)
    out["input"] = sum(out[name] for name in INPUT_FIELDS)
    return out


def read_all(path):
    """read_run for the lead transcript, with every subagent's usage added.

    calls and turns stay the lead's own, so the same-work test compares the
    lead's work on both sides. tokens and money are what the whole run spent,
    which is what a bill and a plan window actually count.
    """
    out = read_run(path)
    for sub in glob.glob(path[:-6] + "/subagents/agent-*.jsonl"):
        s = read_run(sub)
        for name in FIELDS:
            out[name] += s[name]
        out["tokens"] += s["tokens"]
        out["input"] += s["input"]
        out["money"] += s["money"]
        out["packed"] += s["packed"]
    return out


# THE GROUPS, added 29 August 2026. The pairs file holds rows of more than one
# configuration, and pooling across configurations makes a figure no single
# setup ever produced: before this date rows 23 and 24 pooled silently into
# the seven-pair headline. Each group below pools alone. The bar checks and
# the bias check print for the headline group only, because the outside
# figures they compare against were measured on that configuration.
GROUPS = (
    # The INDEX benchmark, DensePack's own, from 30 August 2026. A lead
    # delegates a survey of the plugin's scripts to two cheap agents, then
    # verifies all 28 files itself, about 84 lead commands after the packs
    # land. Correctness is scored by bench/index_score.py against truth
    # rebuilt from the tree, so a run that saves tokens by doing less work
    # fails the score rather than flattering the plugin.
    #
    # Every earlier group left this file on that date. Rows 36
    # to 38 ran a different task file on each side, so they were never A/B
    # results; row 39 carried a subagent that looped 416 seconds to return
    # 293 characters; and several rows disagreed between tools. Numbering
    # restarts at 1 here so no archived row can be mistaken for a current one.
    # The index task retired the same day it ran: its one pair passed
    # correctness on both sides while the off lead ran 86 Bash calls and 2
    # spawns against the on lead's 7 and 4, so the totals compared two
    # different workflows. bench/shape_check.py now fails a pair shaped like
    # that before it can pool. Verified 30 August 2026 by counting both
    # transcripts' tool_use blocks and billed message ids directly.
    ("The INDEX benchmark, retired 30 August 2026, sides diverged in shape",
     tuple(range(1, 50)), False, 96),
    # The HOOKS benchmark, bench/hooks_task.md, from 30 August 2026: four
    # research agents each report a quarter of plugin/scripts in detail,
    # then the lead verifies every claim itself, 62 commands after the
    # reports land, and writes the map bench/hooks_score.py checks against
    # the tree. Its pairs number from 50 so no index row can pool in.
    ("The HOOKS benchmark, delegated research then a lead-only verify pass",
     tuple(range(50, 100)), True, 63),
)


def report_group(title, both_by_index, headline, min_bash=96):
    print("## %s" % title)
    print()
    # THE USABILITY TEST, ruled 26 August 2026 and one sided on purpose. An
    # extra lead tool call can only add tokens to the side that made it: it
    # adds a turn, that turn re-reads the prefix, and its result grows the
    # prefix for every later turn. Admitting only pairs where the ON side made
    # at least as many calls admits only pairs whose bias runs against the
    # plugin, so no admitted pair can overstate the saving through a count
    # mismatch. A symmetric tolerance was rejected because its width is
    # invented and can be widened later; this rule has no width.
    print("| Pair | Side | Lead calls | Spawns | Bash | Turns | Packed | Tokens | Dollars | Usable, or why not |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    usable = []
    for index in sorted(both_by_index):
        both = both_by_index[index]
        on, off = both.get("on"), both.get("off")
        why = ""
        if not (on and off):
            why = "a side did not finish"
        elif not (on["done"] and off["done"]):
            why = "a side never printed DONE"
        elif on["spawns"] < 4 or off["spawns"] < 4:
            why = "fewer than 4 agent spawns"
        elif on["bash"] < min_bash or off["bash"] < min_bash:
            why = "fewer than %d Bash commands" % min_bash
        elif on["packed"] == 0 or off["packed"] != 0:
            # The side test, from the transcripts themselves. A pair where the
            # switch was in the wrong state is not a comparison.
            why = "the switch was not in the state the run intended"
        if not why:
            usable.append((on, off))
        for name, run in (("off", off), ("on", on)):
            if run is None:
                print("| %s | %s | - | - | - | - | - | - | - | %s |"
                      % (index, name, why))
                continue
            print("| %s | %s | %d | %d | %d | %d | %d | %s | %.4f | %s |"
                  % (index, name, run["calls"], run["spawns"], run["bash"],
                     run["turns"], run["packed"], format(run["tokens"], ","),
                     run["money"], "yes" if not why else why))

    print()
    if not usable:
        print("No usable pair yet.")
        return
    on_t = sum(a["tokens"] for a, _b in usable)
    off_t = sum(b["tokens"] for _a, b in usable)
    on_i = sum(a["input"] for a, _b in usable)
    off_i = sum(b["input"] for _a, b in usable)
    on_m = sum(a["money"] for a, _b in usable)
    off_m = sum(b["money"] for _a, b in usable)
    print("| Pooled over %d usable pairs | Plugin off | Plugin on | Saved | Saved per cent |"
          % len(usable))
    print("| --- | --- | --- | --- | --- |")
    print("| Input tokens | %s | %s | %s | %.2f |"
          % (format(off_i, ","), format(on_i, ","), format(off_i - on_i, ","),
             100.0 * (off_i - on_i) / off_i if off_i else 0.0))
    print("| Tokens, input and output together | %s | %s | %s | %.2f |"
          % (format(off_t, ","), format(on_t, ","), format(off_t - on_t, ","),
             100.0 * (off_t - on_t) / off_t if off_t else 0.0))
    print("| Dollars | %.4f | %.4f | %.4f | %.2f |"
          % (off_m, on_m, off_m - on_m,
             100.0 * (off_m - on_m) / off_m if off_m else 0.0))
    if not headline:
        return
    losers = sum(1 for a, b in usable if a["tokens"] > b["tokens"])
    print()
    print("| Check | Value | Verdict |")
    print("| --- | --- | --- |")
    print("| Usable pairs | %d | %s |"
          % (len(usable), "enough" if len(usable) >= 7 else "under 7, do not publish"))
    print("| Pairs where the on side spent more tokens | %d | %s |"
          % (losers, "stop, the plugin loses" if losers >= 4 else "under 4"))

    # THE CALL COUNT MISMATCH, AND WHAT IT IS WORTH. Every pair in the group
    # pools. A pair whose off side made more lead tool calls than its on side
    # can flatter the plugin. The subset below pools only the pairs where the
    # on side made at least as many calls, which is the set that can
    # only understate the saving. Both figures print, so the size of the
    # mismatch is a number a reader can see rather than a claim.
    strict = [(a, b) for a, b in usable if a["calls"] >= b["calls"]]
    if strict and len(strict) != len(usable):
        s_on_i = sum(a["input"] for a, _b in strict)
        s_off_i = sum(b["input"] for _a, b in strict)
        s_on_m = sum(a["money"] for a, _b in strict)
        s_off_m = sum(b["money"] for _a, b in strict)
        print()
        print("| Bias check | All %d pairs | The %d pairs where the on side made at least as many calls | Difference |"
              % (len(usable), len(strict)))
        print("| --- | --- | --- | --- |")
        input_pct = 100.0 * (off_i - on_i) / off_i if off_i else 0.0
        money_pct = 100.0 * (off_m - on_m) / off_m if off_m else 0.0
        s_i = 100.0 * (s_off_i - s_on_i) / s_off_i if s_off_i else 0.0
        s_m = 100.0 * (s_off_m - s_on_m) / s_off_m if s_off_m else 0.0
        print("| Input tokens saved per cent | %.2f | %.2f | %.2f |"
              % (input_pct, s_i, input_pct - s_i))
        print("| Dollars saved per cent | %.2f | %.2f | %.2f |"
              % (money_pct, s_m, money_pct - s_m))


def main():
    pairs_file = sys.argv[1]
    if not Path(pairs_file).is_file():
        print("No pairs yet. %s does not exist." % pairs_file)
        print("Run the INDEX benchmark first:")
        print("  DENSEPACK_TASK=<repo>/bench/index_task.md DENSEPACK_LIMIT=2400"
              " bash <repo>/bench/ab_pairs.sh 1 1")
        return 0
    rows = [l.split() for l in Path(pairs_file).read_text(encoding="utf-8").splitlines()
            if l.strip()]
    pairs = {}
    for row in rows:
        if len(row) < 3:
            pairs.setdefault(int(row[1]), {})[row[0]] = None
            continue
        pairs.setdefault(int(row[1]), {})[row[0]] = read_all(row[2])

    grouped = set()
    first = True
    for title, indices, headline, min_bash in GROUPS:
        both_by_index = {i: pairs[i] for i in indices if i in pairs}
        grouped.update(both_by_index)
        if not both_by_index:
            continue
        if not first:
            print()
        first = False
        report_group(title, both_by_index, headline, min_bash)

    left_over = sorted(set(pairs) - grouped)
    if left_over:
        print()
        print("Rows %s are in %s but in no configuration group above. They are"
              " not pooled anywhere: add them to a group in GROUPS before"
              " quoting a figure that includes them."
              % (", ".join(str(i) for i in left_over), pairs_file))


if __name__ == "__main__":
    main()
