---
description: Check that DensePack works, and show why recent Reads or outputs stayed text.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" densedoctor

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" densedoctor

Then show the output as it is, and name each FAIL line in one sentence.

The command checks Python, Git Bash on Windows, Pillow, FreeType, NumPy and the font, and draws one test image. It then prints the last 10 lines of .claude/densepack-vault/why-text.log. DensePack logs a line each time a Read or command output stays text because of an error, a missing library or the price check.
