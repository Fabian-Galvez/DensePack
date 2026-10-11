---
max_turns: 150
allowed_tools: [Read, Glob, Grep, Write, Edit, Bash, Agent]
tags: [bench]
timeout_seconds: 3600
---

The files in the current directory are the scripts of DensePack, a Claude Code plugin I maintain. Read the entire files style.py, drop_read_gate.py, densepack.py, bootstrap.py and freetype_glyph.py, and write a 5-line summary of what they are about to ANSWER.md. Don't change any of the scripts. Use one Sonnet subagent to read the entire files and report what each one is about back to you, then write ANSWER.md yourself from its report.
