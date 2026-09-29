---
description: Start DensePack and set all settings to their defaults.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" on

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" on

Then relay the status line in one sentence.

It removes the off setting of this session and an off setting that names no session. It sets all settings to their default values.

| Setting | Default |
| --- | --- |
| receipts | quiet |
| totals | auto |
| keep | both |
| reader | auto |
| stylecard | off |
| maxpack, images for Sonnet | on |
| vault cap | 200 MB |

The settings apply to each session in this project folder. Another project folder keeps its own settings.
