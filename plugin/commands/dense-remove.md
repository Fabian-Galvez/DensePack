---
description: Restore the original text of each converted CLAUDE.md, CLAUDE.local.md and MEMORY.md. Remove CLAUDE_CODE_THRIFTY_SONIC from ~/.claude/settings.json. Delete the DensePack files that /plugin uninstall does not delete. Run it before the uninstall.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" remove

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" remove

Then print the command's output exactly as it returns it.

It also removes the trust entry of the densepack-marketplace folder from ~/.claude.json. It cleans each project folder that a transcript in ~/.claude/projects names. It keeps each densepack-archive folder and each .bakpack.old-N file.
