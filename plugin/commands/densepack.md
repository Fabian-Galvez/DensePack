---
description: Turn DensePack on and put every setting back to default.
---

Run this exact command with the Bash tool:

p=python; command -v python >/dev/null 2>&1 || p=python3; "$p" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" on

Then relay the status line to the user in one sentence.

This is also the only way back to the one state no other command reaches: totals auto. Agentpack support has no slash command at all; reach it only from a terminal, `dpctl.py agentpack support`.
