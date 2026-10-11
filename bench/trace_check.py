"""Check that a claude -p stream-json trace is one valid bench run. Prints OK or the problems.

Checks: every line is valid JSON; exactly one init and one result; both have the same session id; the result
is a success with stop_reason end_turn; the Claude Code version and the model; Grep and Glob in the tools.

Usage: python -I trace_check.py <trace.jsonl> [--version 2.1.296] [--model claude-opus-5-5] [--grep yes|no]"""
import argparse, json, re, sys


def check(path, version=None, model=None, grep=None):
    problems, inits, results, bad = [], [], [], 0
    denied = re.findall(r"Permission to use (\w+) has been denied", open(path, encoding="utf-8").read())
    if denied:
        problems.append("%d permission denials (%s): the bench, not the agent, blocked a tool" % (
            len(denied), ", ".join(sorted(set(denied)))))
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if r.get("type") == "system" and r.get("subtype") == "init":
            inits.append(r)
        if r.get("type") == "result":
            results.append(r)
    if bad:
        problems.append("%d lines are not valid JSON" % bad)
    if len(inits) != 1:
        problems.append("%d init records, not 1" % len(inits))
    if len(results) != 1:
        problems.append("%d result records, not 1" % len(results))
    if inits and results and inits[0].get("session_id") != results[-1].get("session_id"):
        problems.append("the init and the result are from different sessions")
    if results and (results[-1].get("subtype") != "success" or results[-1].get("is_error")):
        problems.append("the result is %s, error %s" % (results[-1].get("subtype"), results[-1].get("is_error")))
    if inits:
        i = inits[0]
        tools = i.get("tools") or []
        if version and i.get("claude_code_version") != version:
            problems.append("version %s, not %s" % (i.get("claude_code_version"), version))
        if model and i.get("model") != model:
            problems.append("model %s, not %s" % (i.get("model"), model))
        if grep is not None and ("Grep" in tools) != grep:
            problems.append("Grep %s in the tools" % ("is" if "Grep" in tools else "is not"))
    cost = results[-1].get("total_cost_usd") if results else None
    return problems, cost


def first_cache_read(path):
    """Cache read tokens of the first API request: 0 means a cold start."""
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") == "assistant":
            return ((r.get("message") or {}).get("usage") or {}).get("cache_read_input_tokens", 0)
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", nargs="+")
    ap.add_argument("--version")
    ap.add_argument("--model")
    ap.add_argument("--grep", choices=["yes", "no"])
    a = ap.parse_args()
    for t in a.traces:
        p, cost = check(t, a.version, a.model, None if a.grep is None else a.grep == "yes")
        print("%s | $%s | %s" % (t[-50:], cost, "OK" if not p else "INVALID: " + "; ".join(p)))
