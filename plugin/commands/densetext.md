---
description: Keep more output and short files as text. It costs more tokens than the default.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" densetext

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" densetext

Then relay the status line in one sentence.

With this setting, Bash output under 15 lines and 2,000 characters, JSON output and Reads of files under 100 lines stay text. Repeated blocks of output fold to one copy, and the whole output goes to a file.

More IDs and hashes go beside each image as exact text. More text costs more tokens, so the savings drop. /densepack turns it off and sets the other settings back to their defaults.

The setting applies to each session in this project folder. Another project folder keeps its own setting.
