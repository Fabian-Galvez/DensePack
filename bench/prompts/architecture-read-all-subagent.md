---
max_turns: 150
allowed_tools: [Read, Glob, Grep, Write, Edit, Bash, Agent]
tags: [bench]
timeout_seconds: 3600
---

The files in this folder are the scripts of DensePack, a Claude Code plugin. Before I change its hook scripts, I need to learn their code. Read these hook scripts in full:

- bash_image.py
- bootstrap.py
- brief_pack.py
- drop_read_gate.py
- edit_gate.py
- grep_gate.py
- pointer.py
- prompt_card.py
- read_gate.py
- read_image.py
- session_end.py
- source_gate.py
- subagent_start.py
- subagent_stop.py

Then write ARCHITECTURE.md in this folder as one Markdown table and nothing else. The table has one row for each script. The columns are Script, Hook event, Tool, Imports and Change.

- Tool is the tool of a tool event.
- Imports are the other scripts of this folder that the script imports.
- Change is one short sentence on what the script changes, and on which condition.

The hooks.json file is not in this folder. Take the facts from the scripts. Do not change the scripts. Use one Sonnet subagent to read the scripts in full and report these facts back to you, then write ARCHITECTURE.md yourself from its report.
