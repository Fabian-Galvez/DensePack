---
description: Send Sonnet images. This is the default. Haiku still gets text.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" maxpack

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" maxpack

Then relay the status line in one sentence.

/max-off sends Sonnet text again.

At its next session start, a Sonnet main agent gets the DensePack session start note. Each Sonnet subagent gets the same note when it starts.

The setting applies to each session in this project folder. Another project folder keeps its own setting.
