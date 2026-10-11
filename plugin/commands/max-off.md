---
description: Send Sonnet plain text. Sonnet gets images by default.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" maxoff

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" maxoff

Then relay the status line in one sentence.

Fable and Opus still get images. Reports to Fable or Opus main agents become images when the images and their Read cost less than the text. Reports to Sonnet main agents stay text.

Sonnet main agents still get the session start note. Claude Code does not name the model at session start, so DensePack cannot leave the note out. The note also covers Sonnet after /max-off, which gets text. Sonnet subagents get no note when DensePack finds their model at the start, because they never get an image.

The setting applies to each session in this project folder. Another project folder keeps its own setting.
