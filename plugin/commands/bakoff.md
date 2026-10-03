---
description: Restore the original instruction files of a folder that /bakpack packed, and delete their images.
argument-hint: "<folder>"
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead. Use the folder name after the command name in place of $ARGUMENTS.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" bakoff "$ARGUMENTS"

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" bakoff "$ARGUMENTS"

Then print the command's output exactly as it returns it.
