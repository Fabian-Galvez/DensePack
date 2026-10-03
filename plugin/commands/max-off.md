---
description: Send Sonnet plain text. Sonnet gets images by default.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" maxoff

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" maxoff

Then relay the status line in one sentence.

Fable and Opus still get images. A report to a Fable or Opus main agent still becomes an image when the image saves more than it costs. A report to a Sonnet main agent stays text.

A Sonnet main agent still gets the session start note, because Claude Code does not name the model at session start. The note says that Sonnet after /max-off gets text. A Sonnet subagent gets no note when DensePack knows its model at the start.

The setting applies to each session in this project folder. Another project folder keeps its own setting.
