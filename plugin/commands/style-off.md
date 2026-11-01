---
description: Turn off the DensePack writing rules. Packing, the project map and the rules for finding and reading files stay on.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: r="${CLAUDE_PLUGIN_ROOT}"; [ -f "$r/scripts/dpctl.py" ] || { c="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins"; r=$(sh -c 'ls -t "$1"/synced/*/densepack/scripts/dpctl.py "$1"/cache/*/densepack/*/scripts/dpctl.py 2>/dev/null | head -1' sh "$c"); r="${r%/scripts/dpctl.py}"; echo "DensePack: CLAUDE_PLUGIN_ROOT was empty, so this command uses $r" >&2; }; sh "$r/scripts/run_hook.sh" "$r/scripts/dpctl.py" styleoff

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" styleoff

Then relay the status line in one sentence. For the rest of this session, follow only the "Work in few turns" section of the DensePack rules, and stop following the other sections.

The reminder line after each message stops now, and subagents that start from now on get no writing rules. From the next session, the start note keeps the project map and the rules for finding and reading files, without the writing rules. Packing works the same as before.

The setting applies to each session in this project folder. /stylepack turns the writing rules on again.
