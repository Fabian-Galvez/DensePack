"""One bench pair with claude -p on this machine, without `claude plugin eval`.

The eval always gives its agent Grep and Glob, so it cannot test EMBEDDED_SEARCH_TOOLS. This launcher runs
each side as a plain `claude -p` session in a fresh folder, with a fresh config folder that holds only the
login, then scores the output with the case's own regex graders.

  with:    --plugin-dir <copy of plugin/>, and the environment variables of --with-env (KEY=VALUE)
  without: no plugin

Usage: python -I direct_pair.py <case> [--model claude-opus-5-5] [--with-env EMBEDDED_SEARCH_TOOLS=1]
                                [--tools "Bash Read Write Edit"] [--out <folder>]
Prints cost, API requests, tools offered, score and failed graders for each side. Traces stay in --out."""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVALS = REPO / "plugin" / "evals"


def frontmatter(path):
    text = path.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    head, body = (m.group(1), m.group(2)) if m else ("", text)
    meta = {}
    for line in head.splitlines():
        k, _, v = line.partition(":")
        if k.strip():
            meta[k.strip()] = v.strip()
    return meta, body.strip()


def scaffold(case_dir, cwd):
    """The steps of setup.sh: copy the fixture scripts, resources, and move _fonts next to cwd."""
    shutil.copytree(EVALS / "_fixtures" / "densepack-scripts", cwd, dirs_exist_ok=True)
    if (case_dir / "resources").is_dir():
        shutil.copytree(case_dir / "resources", cwd, dirs_exist_ok=True)
    fonts = cwd / "_fonts"
    if fonts.is_dir():
        shutil.move(str(fonts), str(cwd.parent / "fonts"))


def grade(case_dir, cwd, side):
    passed, failed = 0, []
    for g in sorted((case_dir / "graders").glob("*.md")):
        text = g.read_text(encoding="utf-8")
        if re.search(r"^type:\s*regex", text, re.M) is None:
            continue
        # "arm: with-only" graders, such as densepack_fired, are a plugin-fired indicator in the eval and
        # not part of the score. The eval scores the rest the same on both sides.
        if re.search(r"^arm:\s*with-only", text, re.M):
            continue
        target = re.search(r"path:\s*([^\s}]+)", text).group(1)
        pat = re.search(r"^pattern:\s*'(.*)'\s*$", text, re.M | re.S).group(1).replace("''", "'")
        # The check's own flags line sets its regex flags, such as "flags: i" for a check that ignores case.
        flags = re.M
        fl = re.search(r"^flags:\s*(\w+)", text, re.M)
        for ch in (fl.group(1) if fl else ""):
            flags |= {"i": re.I, "s": re.S, "m": re.M, "x": re.X}.get(ch, 0)
        f = cwd / target
        found = f.is_file() and re.search(pat, f.read_text(encoding="utf-8", errors="replace"), flags) is not None
        # "match: not_contains" passes when the pattern is absent.
        ok = (f.is_file() and not found) if re.search(r"^match:\s*not_contains", text, re.M) else found
        if ok:
            passed += 1
        else:
            failed.append(g.stem)
    return passed, failed


def with_image(cmd, side, args):
    """With --prompt-image, the with side sends its first message as stream-json: the image, then the prompt text, so
    the image sits in the first turn the way a start note does. Returns the command and its stdin text."""
    if not args.prompt_image or side != "with":
        return cmd, None
    import base64
    data = base64.b64encode(Path(args.prompt_image).read_bytes()).decode("ascii")
    msg = {"type": "user", "message": {"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
        {"type": "text", "text": cmd[2]}]}}
    return cmd[:2] + cmd[3:] + ["--input-format", "stream-json"], json.dumps(msg) + "\n"


def run_side(side, args, case_dir, prompt, out):
    root = Path(tempfile.mkdtemp(prefix="dp-direct-%s-" % side))
    # The config folder is ~/.claude, as in a normal install. DensePack finds a subagent's model in
    # ~/.claude/projects, so a config folder outside the home gave each subagent text, not images.
    cwd, config = root / "home" / "cwd", root / "home" / ".claude"
    cwd.mkdir(parents=True)
    config.mkdir()
    # On macOS the login is in the Keychain, not in this file. A token from
    # claude setup-token in CLAUDE_CODE_OAUTH_TOKEN reaches the run instead.
    creds = Path.home() / ".claude" / ".credentials.json"
    if creds.is_file():
        shutil.copy(creds, config / ".credentials.json")
    elif not (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        sys.exit("No Claude Code login to copy. On macOS, run claude setup-token "
                 "and set CLAUDE_CODE_OAUTH_TOKEN to the token that it prints.")
    scaffold(case_dir, cwd)
    # The environment `claude plugin eval` gives its agent (Claude Code 2.1.296, function mp): its own home, temp
    # and config folders, no CLAUDE.md files, no nonessential traffic, no claude.ai MCP servers, no auto-update.
    home, tmp = root / "home", root / "tmp"
    tmp.mkdir()
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(config), HOME=str(home), USERPROFILE=str(home),
               TMPDIR=str(tmp), TMP=str(tmp), TEMP=str(tmp), CLAUDE_CODE_TMPDIR=str(tmp),
               CLAUDE_CODE_DISABLE_CLAUDE_MDS="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
               ENABLE_CLAUDEAI_MCP_SERVERS="false", DISABLE_AUTOUPDATER="1",
               APPDATA=str(home / "AppData" / "Roaming"), LOCALAPPDATA=str(home / "AppData" / "Local"))
    if os.name == "nt":
        env["HOMEDRIVE"], env["HOMEPATH"] = str(home)[:2], str(home)[2:]
    for k in ("EMBEDDED_SEARCH_TOOLS",):
        env.pop(k, None)
    # Naming Grep or Glob in --allowed-tools opts in to them and turns EMBEDDED_SEARCH_TOOLS off, so only
    # the side without DensePack names them. A plain Windows 2.1.296 session has them anyway.
    tools = args.tools.split() + ([] if side == "with" and not args.with_search else ["Grep", "Glob"])
    cmd = [shutil.which("claude") or "claude", "-p", prompt, "--model", args.model, "--output-format", "stream-json",
           "--verbose", "--max-turns", str(args.max_turns), "--permission-mode", "dontAsk",
           "--setting-sources", "user", "--allowed-tools", *tools]
    if args.builtin:
        # The tool set that `claude plugin eval` gave its agent (11 tools). A plain session offers about 25,
        # which adds about 3,600 tokens to each request. The side without DensePack also gets Grep and Glob.
        offered = args.builtin.split() + ([] if side == "with" and not args.with_search else ["Grep", "Glob"])
        cmd += ["--tools", ",".join(offered)]
    if side == "with":
        plugin = root / "plugin"
        # --plugin loads another plugin on this side, such as Ponytail, in place of DensePack.
        shutil.copytree(Path(args.plugin) if args.plugin else REPO / "plugin", plugin,
                        ignore=shutil.ignore_patterns("__pycache__", "evals", ".git", "benchmarks", "tests", "node_modules"))
        cmd += ["--plugin-dir", str(plugin)]
        for kv in args.with_env:
            k, _, v = kv.partition("=")
            env[k] = v
    if args.warm:
        # One short call with the same flags, folder and config first. The prompt cache then holds this side's
        # system prompt and tools, as it does in a session that follows another one.
        warm = cmd[:2] + ["Reply with the word OK. Use no tools."] + cmd[3:]
        warm[warm.index("--max-turns") + 1] = "1"
        warm, warm_in = with_image(warm, side, args)
        with open(out / ("warm-%s.txt" % side), "w", encoding="utf-8") as wf:
            subprocess.run(warm, cwd=cwd, env=env, stdout=wf, stderr=subprocess.STDOUT, input=warm_in, text=True,
                           encoding="utf-8")
    trace = out / ("%s.jsonl" % side)
    t0 = time.time()
    cmd, cmd_in = with_image(cmd, side, args)
    with open(trace, "w", encoding="utf-8") as f:
        subprocess.run(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.DEVNULL, input=cmd_in, text=True,
                       encoding="utf-8")
    secs = time.time() - t0
    tools, cost, reqs, version = [], None, set(), None
    for line in open(trace, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") == "system" and r.get("subtype") == "init":
            tools, version = r.get("tools") or [], r.get("claude_code_version")
        if r.get("type") == "assistant":
            reqs.add((r.get("message") or {}).get("id"))
        if r.get("type") == "result":
            cost = r.get("total_cost_usd")
    passed, failed = grade(case_dir, cwd, side)
    sys.path.insert(0, str(Path(__file__).parent))
    import trace_check
    want_grep = None if side == "with" and not any(kv.startswith("EMBEDDED_SEARCH_TOOLS=") for kv in args.with_env) \
        else side != "with"
    problems, _cost = trace_check.check(trace, version, args.model, want_grep)
    print("%-7s trace check: %s | first request cache read %s" % (
        side, "OK" if not problems else "INVALID: " + "; ".join(problems), trace_check.first_cache_read(trace)))
    for name in ("ARCHITECTURE.md", "ANSWER.md"):
        if (cwd / name).is_file():
            shutil.copy(cwd / name, out / ("%s-%s" % (side, name)))
    print("%-7s $%.3f | API requests %d | %ds | version %s | Grep %s Glob %s | score %d/%d | failed %s" % (
        side, cost or 0, len(reqs), secs, version, "Grep" in tools, "Glob" in tools,
        passed, passed + len(failed), failed or "none"))
    # The temp folder holds the session transcript and DensePack's own state and logs. --keep leaves it, so a run
    # that went wrong can be read afterwards.
    if args.keep:
        print("%-7s temp folder kept: %s" % (side, root))
    else:
        shutil.rmtree(root, ignore_errors=True)
    return cost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--with-env", action="append", default=[])
    # The agent on Windows uses PowerShell, so it is in the list too.
    ap.add_argument("--tools", default="Bash PowerShell Read Write Edit")
    ap.add_argument("--out", default=None)
    ap.add_argument("--plugin", default=None, help="plugin folder for the with side; DensePack's plugin/ by default")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder with the session transcript and logs")
    ap.add_argument("--prompt-image", default=None,
                    help="a PNG that the with side gets in its first message, before the prompt")
    ap.add_argument("--with-search", action="store_true",
                    help="the with side also gets Grep and Glob, the same as the side without DensePack")
    ap.add_argument("--prompt-file", default=None, help="another prompt for the case, such as bench/prompts/*.md")
    ap.add_argument("--warm", action="store_true", help="one short call per side first, so both sides start warm")
    ap.add_argument("--sides", default="with,without", help="with, without, or both (default)")
    ap.add_argument("--builtin", default="Task Bash Edit NotebookEdit Read Skill TaskStop ToolSearch Write",
                    help="tools offered (--tools), the eval's set by default; empty for Claude Code's full set")
    args = ap.parse_args()
    case_dir = EVALS / args.case
    meta, prompt = frontmatter(Path(args.prompt_file) if args.prompt_file else case_dir / "prompt.md")
    # The case's own turn limit, as the eval uses it: 150, or 200 for code-trace.
    args.max_turns = int(meta.get("max_turns", 150))
    out = Path(args.out or tempfile.mkdtemp(prefix="dp-direct-out-"))
    # Two runs that write into one folder mix their traces, so refuse a used folder.
    if out.exists() and any(out.glob("*.jsonl")):
        sys.exit("refused: %s already holds a trace. Use a new --out folder." % out)
    out.mkdir(parents=True, exist_ok=True)
    ver = subprocess.run([shutil.which("claude") or "claude", "--version"], capture_output=True, text=True).stdout.strip()
    head = subprocess.run(["git", "-C", str(REPO), "log", "-1", "--format=%h"], capture_output=True, text=True).stdout.strip()
    print("case %s | prompt %s | model %s | claude %s | DensePack %s | with-env %s | tools %s | warm %s | traces %s" % (
        args.case, args.prompt_file or "case", args.model, ver, head, args.with_env, args.tools, args.warm, out))
    costs = {s: run_side(s, args, case_dir, prompt, out) for s in args.sides.split(",")}
    sys.path.insert(0, str(Path(__file__).parent))
    import trace_check
    starts = {s: trace_check.first_cache_read(out / ("%s.jsonl" % s)) or 0 for s in costs}
    # Claude Code shares about 14,000 to 16,000 tokens of system prompt and tools between sessions with the same
    # setup. A side that reads them from the cache starts warm. A pair is fair only when both sides start alike.
    if len(starts) == 2 and (starts["with"] >= 5000) != (starts["without"] >= 5000):
        print("INVALID PAIR: unequal start, first request cache read with %d, without %d" % (starts["with"], starts["without"]))
    if costs.get("with") and costs.get("without"):
        print("saving %.1f%%" % ((1 - costs["with"] / costs["without"]) * 100))


if __name__ == "__main__":
    main()
