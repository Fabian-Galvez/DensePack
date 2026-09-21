"""Run one on-against-off pair of isolated headless legs and price both.

What this file does, in plain words:

  1. Launches the OFF leg: claude -p with the plugin disabled by a settings
     file, no MCP servers, only the project's settings, a one line system
     prompt and only the tools the task needs. Nothing else reaches the model.
  2. Waits past the API's five minute cache window, so the ON leg cannot read
     the OFF leg's prefix from cache. A first turn with any cache read makes
     the leg invalid.
  3. Launches the ON leg the same way with the plugin enabled.
  4. Checks each transcript: no denied tool call, the OFF leg's tool results
     all text, the ON leg's code Reads all pictures, first turn cold.
  5. Scores the reply or the answers file against the key, prices each
     transcript with read_run, and appends one JSON row to the record.

Run it as:
  python bench/run_bench_arm.py TASK MODEL BENCH [--tools Read,Bash] [--cwd DIR]
      [--key "a|b" "c" ...] [--scorer "python bench/score_16file_32file_answers.py {answers} py"]
      [--answers answers.txt] [--sleep 310] [--only on|off]
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
def projects_dir_for(path):
    """The folder where Claude Code keeps the transcripts of a session started in `path`."""
    return os.path.join(os.path.expanduser("~"), ".claude", "projects",
                        re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path)))
from price_bench_transcript import read_run, rates  # noqa: E402

OFFJSON = os.path.join(HERE, "settings", "off-plugin.json")
ONJSON = os.path.join(HERE, "settings", "on-plugin.json")
# Legs run from a folder outside any repository, so no CLAUDE.md up the tree reaches
# them; a Fable leg inside the repo read HANDOFF.md first because CLAUDE.md said to.
# ONE ARENA ROOT FOR EVERY BENCH, from 13 September 2026: the folder
# DensePack-arenas beside the repository, so a fresh install finds every
# leg's folder in one place and nothing lands in the home folder.
# DENSEPACK_ARENA_ROOT names another root. It is a sibling of the
# repository and never inside it, because Claude Code loads CLAUDE.md from
# every ancestor folder of a leg's cwd, and the repository's CLAUDE.md
# would enter every leg's prefix and move every price.
REPO = os.path.dirname(HERE)


def arena_root(*parts):
    root = os.environ.get("DENSEPACK_ARENA_ROOT") or os.path.join(
        os.path.dirname(REPO), "DensePack-arenas")
    # /plugin install puts this repository inside ~/.claude/plugins. An arm
    # folder inside a .claude folder breaks both arms: Claude Code refuses the
    # Write of the answers file there, and DensePack converts no file under a
    # .claude folder. The arm folders then go to DensePack-arenas in the home
    # folder instead.
    if ".claude" in os.path.normpath(root).replace("\\", "/").split("/"):
        root = os.path.join(os.path.expanduser("~"), "DensePack-arenas")
    return os.path.join(root, *parts)


ARENA = os.environ.get("DENSEPACK_ARENA") or arena_root("lead")
# Every arm this script runs, one row a line. bench/rows/<run name>-rows.jsonl holds one run's rows for the checker.
RECORD = os.path.join(HERE, "rows", "all-arms-rows.jsonl")
SYSTEM = "You are a careful coding agent. Use the tools you are given and follow the task exactly."
DENIED = ("requested permissions to", "haven't granted it yet", "tool use was rejected",
          "user doesn't want to proceed")
CODE_SUFFIX = (".py", ".gd", ".js", ".ts", ".md", ".html", ".css", ".json", ".txt", ".toml", ".yaml", ".yml", ".sh", ".mjs")


def maxpack_on(cwd):
    """Switch /maxpack on inside the arm's own folder, so the on arm sends
    images to every reader, Sonnet included. The user's own projects keep
    their own setting."""
    path = os.path.join(cwd, ".claude", "tmp", "densepack-settings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["maxpack"] = "on"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def launch(prompt, model, plugin_on, tools, cwd, one_line_prompt=False):
    # The prompt goes in over stdin: as an argument the shell cuts it at the
    # first newline, measured 7 September 2026, three legs answered "names no files".
    cmd = ["claude", "-p", "--output-format", "json", "--model", model,
           "--strict-mcp-config", "--setting-sources", "project",
           "--tools", tools, "--allowedTools", tools,
           # Both arms switch the installed plugin off. The on arm loads this
           # download's own plugin folder, so the bench measures the plugin that ships.
           "--settings", OFFJSON]
    if plugin_on:
        cmd += ["--plugin-dir", os.path.join(REPO, "plugin")]
    # Fable's safeguard refuses a read-and-answer brief under a one line
    # custom system prompt, reason reasoning_extraction, and takes the same
    # brief under the default prompt; measured 7 September 2026, four legs.
    # EVERY READER GETS THE ONE LINE SYSTEM PROMPT, from 13 September 2026.
    # Fable carried Claude Code's default prompt from 7 September, when its
    # safeguard refused the read-and-answer brief under the one line prompt
    # on four legs. That prompt wrote about 3,700 more prefix tokens a leg
    # on both arms, so every Fable saving read as a small share of a large
    # bill: 5.2 per cent cold on fable-one-v22-sq4-10. Re-measured on
    # 13 September, fable-one-v24-oneline-5: five legs under the one line
    # prompt, no refusal, 5 of 5 on every leg, 22.2 per cent cold.
    # DENSEPACK_BENCH_DEFAULT_PROMPT=1 puts the default prompt back for a
    # Fable leg, for a comparison.
    if not ("fable" in model and os.environ.get("DENSEPACK_BENCH_DEFAULT_PROMPT")):
        cmd += ["--system-prompt", SYSTEM]
    # DENSEPACK_BENCH_EFFORT, from 13 September 2026: a level for --effort,
    # low, medium, high, xhigh or max. Fable spent about 220 thinking tokens
    # on every picture turn with MAX_THINKING_TOKENS at 0 and none on a text
    # turn, and the effort level is the other knob the API reads. Unset, the
    # leg runs as before and inherits whatever effort the machine's settings
    # give it.
    effort = os.environ.get("DENSEPACK_BENCH_EFFORT")
    if effort:
        cmd += ["--effort", effort]
    # A prompt given as content blocks, a picture and a line, goes in as one
    # stream-json user message, so the picture is in the first message and
    # costs no Read; the result event is the same JSON the plain form prints.
    if isinstance(prompt, list):
        cmd[cmd.index("--output-format") + 1] = "stream-json"
        cmd += ["--input-format", "stream-json", "--verbose"]
        prompt = json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n"
    # No thinking budget, on either arm. MEASURED 10 September 2026 on
    # opus-one-snapped-fixedq: with a budget, eight of ten on-arm legs opened
    # a thinking block on the turn that reads the image and output ran 145 to
    # 1872, mean 747, for the same 5 of 5 answer every time. One noisy leg
    # billed 1778 output tokens on that turn with 1721 of them thinking,
    # against a 120 character reply. Without a budget, ten legs ran 145 to
    # 353, mean 170, and the bench went from losing 9.6 per cent to saving
    # 22.8. The block changes no answer, so it is measurement noise priced at
    # 10.02 dollars a million.
    #
    # The budget arrives from the user's own ~/.claude/settings.json, which
    # sets effortLevel, and the leg inherits it although --setting-sources
    # names only the project. Both arms get this, so neither is flattered.
    env = dict(os.environ)
    env["MAX_THINKING_TOKENS"] = "0"
    if plugin_on:
        maxpack_on(cwd)
    t0 = time.time()
    # No shell: a list with shell=True runs only "claude" on Linux and macOS.
    cmd[0] = shutil.which(cmd[0]) or cmd[0]
    r = subprocess.run(cmd, cwd=cwd, input=prompt, capture_output=True, text=True, timeout=3600, env=env)
    secs = time.time() - t0
    try:
        if "--input-format" in cmd:
            j = {"error": "no result event: " + r.stdout[-500:] + r.stderr[-500:]}
            for line in r.stdout.splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "result":
                    j = ev
        else:
            j = json.loads(r.stdout)
    except ValueError:
        j = {"error": r.stdout[-500:] + r.stderr[-500:]}
    j["wall_seconds"] = round(secs, 1)
    return j


def inspect(path):
    """Per-turn usage, tool calls, tool result kinds and denial hits from one transcript."""
    seen, calls, results, denied = {}, [], [], []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        m = row.get("message") or {}
        if isinstance(m.get("usage"), dict):
            seen[m.get("id")] = m["usage"]
        c = m.get("content")
        blocks = c if isinstance(c, list) else []
        for b in blocks:
            t = b.get("type")
            if t == "tool_use":
                calls.append((b.get("name"), json.dumps(b.get("input"))[:200]))
            elif t == "tool_result":
                cc = b.get("content")
                kinds = [x.get("type") for x in cc] if isinstance(cc, list) else ["text"]
                text = " ".join(x.get("text", "") for x in cc if isinstance(x, dict)) if isinstance(cc, list) else str(cc)
                results.append((kinds, text[:200]))
                # A denial is the tool result itself: Claude Code opens the
                # result text with the phrase, or marks the block is_error.
                # A file that quotes the phrase is not one. FOUND
                # 13 September 2026: plugin/bench/thirty-two-file/corpus/
                # test_run_leg.py holds "requested permissions to" at its
                # line 64 as a test fixture, and every text arm that read it
                # was marked invalid, along with every picture arm that got
                # that file as text.
                head = text[:120]
                for d in DENIED:
                    if d in head or (b.get("is_error") and d in text):
                        denied.append(d)
    turns = [(u.get("cache_creation_input_tokens", 0), u.get("cache_read_input_tokens", 0), u.get("output_tokens", 0))
             for u in seen.values()]
    return turns, calls, results, denied


def validate(path, plugin_on):
    turns, calls, results, denied = inspect(path)
    problems = []
    if not turns:
        problems.append("no usage rows")
    # A first turn that reads from cache is not a fault: Claude Code writes one
    # hour cache entries, so the two arms share their tool block within the
    # hour whatever the wait. price() charges those reads at the write rate.
    if denied:
        problems.append("denied tool call: " + denied[0])
    reads = [inp for name, inp in calls if name == "Read"]
    code_reads = [inp for inp in reads if any(inp.lower().rstrip('"}').endswith(s) or s + '"' in inp.lower() for s in CODE_SUFFIX)]
    # a PDF of pages arrives as a document block and is a picture too
    image_results = sum(1 for kinds, _ in results if "image" in kinds or "document" in kinds)
    # A code Read the plugin left as text is the plugin's own call, not a
    # run fault: Sonnet's burst cap reads a wide turn as text whole, and a
    # file priced cheaper as text stays text. It is counted, not failed.
    notes = []
    if plugin_on and code_reads and image_results < len(code_reads):
        notes.append("plugin on and %d of %d code Reads came back as text" % (len(code_reads) - image_results, len(code_reads)))
    if not plugin_on and image_results:
        problems.append("plugin off but %d tool results were pictures" % image_results)
    return problems, turns, calls, results, notes


def cold(path, r):
    """The run's money with its first turn's cache reads charged at the one
    hour write rate, so an arm that found the other arm's prefix in cache
    pays what a cold arm pays."""
    turns = inspect(path)[0]
    if not turns:
        return r["money"]
    model = next((json.loads(l).get("message", {}).get("model") for l in open(path, encoding="utf-8", errors="replace")
                  if '"model"' in l and '"usage"' in l), None)
    if not model:
        return r["money"]
    IN, OUT, W5, W1, RD = rates(model)
    return r["money"] + turns[0][1] * (W1 - RD)


def price(path):
    r = read_run(path)
    r["money"] = cold(path, r)
    sid = os.path.basename(path)[:-6]
    subs = glob.glob(os.path.join(os.path.dirname(path), sid, "subagents", "agent-*.jsonl"))
    for s in subs:
        rs = read_run(s)
        for k in ("money", "tokens", "turns", "input_tokens", "cache_creation_input_tokens",
                  "cache_read_input_tokens", "output_tokens"):
            r[k] += rs[k]
    r["subagents"] = len(subs)
    return r


def score_reply(text, key):
    lines = {}
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)[.)]?\s*(.*)", line)
        if m:
            lines[int(m.group(1))] = m.group(2).strip()
    right, detail = 0, []
    for i, alts in enumerate(key, 1):
        ans = lines.get(i, "")
        ok = any(a.lower() in ans.lower() for a in alts.split("|"))
        right += ok
        detail.append("%d %s %s" % (i, "ok" if ok else "BAD", ans[:80]))
    return right, len(key), detail


BRIEFS = os.path.join(HERE, "session-2026-09-07", "briefs")


def brief_as_file(prompt, args, plugin_on):
    """The ON arm's first message IS the brief picture: the brief drawn by the
    plugin's own brief renderer for the model that reads it, sent inside the
    message as an image block, with the tag values as text beside it, so the
    agent reads nothing to learn its task and spends no turn on it. The OFF
    arm's first message is the same brief as text. A design decision, 7
    September 2026 at night: a Read of the brief is a whole extra turn."""
    if not plugin_on:
        return prompt
    os.makedirs(BRIEFS, exist_ok=True)
    stem = os.path.join(BRIEFS, "%s-%s-brief" % (args.bench, args.model))
    sys.path.insert(0, os.path.join(REPO, "plugin", "scripts"))
    import base64
    import densepack as dp, codepack, common
    reader = "sonnet" if "sonnet" in args.model else ("opus" if "opus" in args.model else "fable")
    px = common.READER_SIZES[reader]
    packed_text, legend = dp.lift_identifiers(dp.flatten(prompt, "\n"))
    written, _t, _lh = codepack.pack_code(packed_text, common.code_size(px, reader), stem,
                                          python=False, legend=None, reader=reader, title="brief")
    blocks = []
    for path, _w, _h in written:
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}})
    text = "The picture is your brief."
    if legend:
        text += " Its tags: " + "; ".join("%s = %s" % (tag, value) for tag, value in legend) + "."
    blocks.append({"type": "text", "text": text})
    return blocks


def run_arm(args, prompt, plugin_on, proj):
    arm = "on" if plugin_on else "off"
    answers_path = os.path.join(args.cwd, args.answers) if args.answers else None
    if answers_path and os.path.exists(answers_path):
        os.remove(answers_path)
    if args.brief_file:
        prompt = brief_as_file(prompt, args, plugin_on)
    j = launch(prompt, args.model, plugin_on, args.tools, args.cwd, args.one_line_prompt)
    sid = j.get("session_id")
    row = {"bench": args.bench, "model": args.model, "arm": arm, "session": sid,
           "wall_seconds": j.get("wall_seconds"), "cli_cost": j.get("total_cost_usd"),
           # The WHOLE reply. A reader can open with a preamble that answers
           # an instruction Claude Code appends to tool results, so the
           # numbered answers can fall far into the reply, and score_reply()
           # must see all of it.
           "cli_turns": j.get("num_turns"), "reply": (j.get("result") or "")}
    if "error" in j or not sid:
        row["valid"] = False
        row["problems"] = ["no json from the CLI: " + str(j.get("error"))[:300]]
        return row
    path = os.path.join(proj, sid + ".jsonl")
    problems, turns, calls, results, notes = validate(path, plugin_on)
    row["notes"] = notes
    row["turns_usage"] = turns
    row["calls"] = [c[0] for c in calls]
    row["result_kinds"] = [k for k, _ in results]
    pr = price(path)
    row.update(money=round(pr["money"], 4), tokens=pr["tokens"], turns=pr["turns"],
               input=pr["input_tokens"], cache_write=pr["cache_creation_input_tokens"],
               cache_read=pr["cache_read_input_tokens"], output=pr["output_tokens"],
               subagents=pr["subagents"])
    if args.scorer and answers_path:
        os.makedirs(os.path.join(HERE, "session-2026-09-07"), exist_ok=True)
        keep = os.path.join(HERE, "session-2026-09-07", "%s-%s-%s-answers.txt" % (args.bench, args.model, arm))
        if os.path.exists(answers_path):
            shutil.copy(answers_path, keep)
            # {answers} is the copied answers file; {transcript} the lead's
            # transcript, for a scorer that reads the Write call itself
            out = subprocess.run(args.scorer.format(answers='"%s"' % keep, transcript='"%s"' % path), shell=True, capture_output=True, text=True)
            m = re.search(r"SCORE (\d+) of (\d+)", out.stdout)
            # hooks_score.py prints PASS or FAIL and a percent instead
            p = re.search(r"\b(PASS|FAIL) ([\d.]+)", out.stdout)
            row["score"] = [int(m.group(1)), int(m.group(2))] if m else ([int(float(p.group(2))), 100] if p else [0, 0])
            row["score_detail"] = out.stdout.strip().splitlines()[-8:]
        else:
            row["score"] = [0, 0]
            problems.append("no answers file written")
    elif args.key:
        right, total, detail = score_reply(row["reply"], args.key)
        row["score"] = [right, total]
        row["score_detail"] = detail
    row["problems"] = problems
    if row.get("reply", "").startswith("API Error"):
        # the model never ran the task; two Fable legs of 7 September 2026
        # were recorded valid at 0 of 5 with this reply
        problems.append("API error, no leg ran: " + row["reply"][:80])
    row["valid"] = not problems
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("model")
    ap.add_argument("bench")
    ap.add_argument("--tools", default="Read,Bash")
    ap.add_argument("--cwd", default=ARENA)
    ap.add_argument("--key", nargs="*", help="one entry per numbered answer, alternatives split by |")
    ap.add_argument("--scorer", default="", help="command with {answers}, printing SCORE n of m")
    ap.add_argument("--answers", default="", help="file the task writes, relative to cwd")
    # 0, AND THE ENTRY REALLY DOES LIVE AN HOUR. PROVED 11 September 2026,
    # from the legs' own usage rows rather than from any documentation.
    #
    # Anthropic's prompt caching page says the default lifetime is five
    # minutes, with an hour available on request, and several posts report a
    # silent return to five minutes in March 2026. NONE OF THAT DESCRIBES THIS
    # HARNESS. Claude Code asks for the hour explicitly. Every cache write in
    # every leg of opus-one-v14cold reads:
    #
    #     "cache_creation": {"ephemeral_1h_input_tokens": 971,
    #                        "ephemeral_5m_input_tokens": 0}
    #
    # A run with --sleep 310 was measured that day to be sure. Both arms still
    # reported a first cache read of 974, and the off arm found the entry warm
    # from a run more than half an hour earlier.
    #
    # The lifetime is measured from the START of a request, and a read
    # REFRESHES the entry free of charge, so the wait must clear an hour from
    # the last request that touched the prefix. Nothing shortens it: the entry
    # lives on Anthropic's side, so no local file can be cleared, and neither a
    # new folder nor an isolated agent misses it. Two arms sharing a tool list
    # cannot both be cold unless they run more than an hour apart.
    #
    # price() charges the first turn's reads at the write rate instead, so a
    # warm arm pays what a cold arm pays. Run both arms in one wave through
    # run_1file_bench.py, which puts them under the same conditions and prints each
    # leg's first cache read so the conditions are checked rather than assumed.
    ap.add_argument("--sleep", type=int, default=0,
                    help="seconds between arms; the entry lives an hour and a "
                         "read refreshes it, so a wait under that buys nothing "
                         "and price() charges a warm arm cold instead")
    ap.add_argument("--only", choices=("on", "off", ""), default="")
    ap.add_argument("--rows", default="",
                    help="also append this run's rows to this file, one bench a file, for bench/check_bench_pairs.py")
    ap.add_argument("--brief-file", action="store_true",
                    help="the ON arm gets the brief drawn as a picture inside its first message, the OFF arm the same brief as text; no Read of the brief on either arm")
    ap.add_argument("--one-line-prompt", action="store_true",
                    help="the one line system prompt for Fable too, in place of the default prompt")
    args = ap.parse_args()
    # {REPO} in a brief is this repository, so a brief never names a file by
    # an absolute path that exists on one machine only.
    prompt = open(args.task, encoding="utf-8").read().replace("{REPO}", REPO)
    # The run name opens the prompt. Both arms of one run share it, and a rerun
    # within the hour gets a new name, so it cannot read the earlier run's whole
    # conversation from the cache: a single file pair did that on Ubuntu and
    # measured 2.0% where a cold pair measures about 23%.
    prompt = "Bench run %s.\n\n%s" % (args.bench, prompt)
    proj = projects_dir_for(args.cwd)
    rows = []
    if args.only != "on":
        rows.append(run_arm(args, prompt, False, proj))
        print(json.dumps(rows[-1]), flush=True)
    if not args.only:
        time.sleep(args.sleep)
    if args.only != "off":
        rows.append(run_arm(args, prompt, True, proj))
        print(json.dumps(rows[-1]), flush=True)
    os.makedirs(os.path.dirname(RECORD), exist_ok=True)
    with open(RECORD, "a", encoding="utf-8") as fh:
        for r in rows:
            r["stamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
            fh.write(json.dumps(r) + "\n")
    if args.rows:
        os.makedirs(os.path.dirname(os.path.abspath(args.rows)), exist_ok=True)
        with open(args.rows, "a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    if len(rows) == 1 and args.only == "on" and os.path.exists(RECORD):
        # An on arm run alone pairs with the newest valid off arm already
        # recorded for this bench and model: the off arm carries no plugin,
        # so a change to the plugin never needs it run again.
        off_row = None
        for line in open(RECORD, encoding="utf-8"):
            r = json.loads(line)
            if r.get("bench") == args.bench and r.get("model") == args.model and r.get("arm") == "off" and r.get("valid"):
                off_row = r
        if off_row:
            rows = [off_row, rows[0]]
    if len(rows) == 2:
        off, on = rows
        if off.get("money") and on.get("money"):
            saved = off["money"] - on["money"]
            print("PAIR %s %s | on %.4f | off %.4f | turns %s/%s | score %s/%s | saved %.4f, %.1f per cent | valid %s %s"
                  % (args.bench, args.model, on["money"], off["money"], on.get("turns"), off.get("turns"),
                     on.get("score"), off.get("score"), saved, 100.0 * saved / off["money"], on["valid"], off["valid"]))


if __name__ == "__main__":
    main()
