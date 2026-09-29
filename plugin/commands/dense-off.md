---
description: Stop all DensePack hooks for this session. A new session starts with DensePack on.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" off

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" off

Then relay the status line in one sentence.

This command uninstalls nothing and keeps all settings. The hooks of each subagent of this session stop too. /densepack starts DensePack again. It also sets all settings to their defaults.
