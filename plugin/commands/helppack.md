---
description: Print every command, what it sets, and which are default.
disable-model-invocation: true
---

Run this exact command with the Bash tool:

p=python; command -v python >/dev/null 2>&1 || p=python3; "$p" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" help

Then relay the status line to the user in one sentence.

Print the table exactly as the command returns it. Do not summarize it and do not reorder it.
