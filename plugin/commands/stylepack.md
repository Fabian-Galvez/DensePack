---
description: Turn on the DensePack writing rules and print them, so the agent reads them again. This is the default.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: r="${CLAUDE_PLUGIN_ROOT}"; [ -f "$r/scripts/dpctl.py" ] || { c="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins"; r=$(sh -c 'ls -t "$1"/synced/*/densepack/scripts/dpctl.py "$1"/cache/*/densepack/*/scripts/dpctl.py 2>/dev/null | head -1' sh "$c"); r="${r%/scripts/dpctl.py}"; }; sh "$r/scripts/run_hook.sh" "$r/scripts/dpctl.py" stylepack

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" stylepack

The output contains the DensePack rules. Follow them from now on, then relay the status line in one sentence.

Run it again whenever the replies stop following the rules. The setting applies to each session in this project folder. /style-off turns the writing rules off.
