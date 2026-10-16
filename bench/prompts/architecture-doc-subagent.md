---
max_turns: 150
allowed_tools: [Read, Glob, Grep, Write, Edit, Bash, Agent]
tags: [bench]
timeout_seconds: 3600
---

The files in the current directory are the .py files of DensePack, a Claude Code plugin. I'm new to this codebase and there's no architecture doc yet.

Use one Sonnet subagent for this task. The subagent reads the hook scripts, the .py files that a Claude Code hook runs, writes ARCHITECTURE.md in this directory for onboarding, and then reports back to you that it is done.

The doc covers every hook script in this directory. The hooks.json that registers them is not in this directory, so the facts have to come from the .py files themselves. For each hook script, the doc gives the Claude Code hook event it runs on (and for a tool event, which tool or tools it handles), what it does in two or three sentences, and which other .py files of this directory it imports. Don't change any of the files.
