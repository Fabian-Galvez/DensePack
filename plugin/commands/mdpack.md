---
description: Convert another folder's CLAUDE.md, .claude/CLAUDE.md and CLAUDE.local.md into images behind a pointer, without reading them.
argument-hint: "<folder>"
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead. Run it, with the folder the user typed after the command name in place of $ARGUMENTS:

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" mdpack "$ARGUMENTS"

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" mdpack "$ARGUMENTS"

Then print the command's output to the user exactly as it returns it. Do not read any file in that folder.
