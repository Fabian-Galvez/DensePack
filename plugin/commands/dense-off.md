---
description: Stop all DensePack hooks for this session. New sessions start with DensePack on.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: r="${CLAUDE_PLUGIN_ROOT}"; [ -f "$r/scripts/dpctl.py" ] || { c="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins"; r=$(sh -c 'ls -t "$1"/synced/*/densepack/scripts/dpctl.py "$1"/cache/*/densepack/*/scripts/dpctl.py 2>/dev/null | head -1' sh "$c"); r="${r%/scripts/dpctl.py}"; echo "DensePack: CLAUDE_PLUGIN_ROOT was empty, so this command uses $r" >&2; }; sh "$r/scripts/run_hook.sh" "$r/scripts/dpctl.py" off

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" off

Then relay the status line in one sentence.

This command turns DensePack off for this session and its subagents only. DensePack stays installed, and your settings stay. /densepack turns DensePack on again and sets all settings to their defaults.
