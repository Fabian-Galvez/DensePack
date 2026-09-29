---
max_turns: 150
allowed_tools: [Read, Glob, Grep, Write, Edit, Bash]
tags: [realistic]
timeout_seconds: 3600
---

The files in the current directory are the scripts of DensePack, a Claude Code plugin. I'm new to this codebase and there's no architecture doc yet, so please write ARCHITECTURE.md in this directory for onboarding. It should cover these hook scripts: bash_image.py, bootstrap.py, brief_pack.py, drop_read_gate.py, edit_gate.py, grep_gate.py, pointer.py, prompt_card.py, read_gate.py, read_image.py, session_end.py, source_gate.py, subagent_start.py and subagent_stop.py. The hooks.json that registers them is not in this folder, so the facts have to come from the scripts themselves. For each script, give the Claude Code hook event it runs on (and for a tool event, which tool or tools it handles), what it does in two or three sentences, and which other scripts of this folder it imports. Don't change any of the scripts. Please do this yourself, without subagents.
