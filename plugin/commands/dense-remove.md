---
description: Restore the original text of each converted instruction file. Remove the settings that DensePack added to ~/.claude/settings.json: CLAUDE_CODE_THRIFTY_SONIC, and on Windows EMBEDDED_SEARCH_TOOLS and CLAUDE_CODE_USE_POWERSHELL_TOOL. Delete the DensePack files that remain after /plugin uninstall. Run it before the uninstall.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: r="${CLAUDE_PLUGIN_ROOT}"; [ -f "$r/scripts/dpctl.py" ] || { c="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins"; r=$(sh -c 'ls -t "$1"/synced/*/densepack/scripts/dpctl.py "$1"/cache/*/densepack/*/scripts/dpctl.py 2>/dev/null | head -1' sh "$c"); r="${r%/scripts/dpctl.py}"; echo "DensePack: CLAUDE_PLUGIN_ROOT was empty, so this command uses $r" >&2; }; sh "$r/scripts/run_hook.sh" "$r/scripts/dpctl.py" remove

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" remove

Then print the command's output exactly as it returns it.

It also removes the trust entry of the densepack-marketplace folder from ~/.claude.json. It cleans each project folder that a transcript in ~/.claude/projects names. It keeps each densepack-archive folder and each .bakpack.old-N file.
