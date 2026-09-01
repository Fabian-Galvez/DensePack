---
description: Print no receipt table. The numbers are still measured. Default.
---

Run this exact command with the Bash tool:

p=python; command -v python >/dev/null 2>&1 || p=python3; "$p" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" receipts quiet

Then relay the status line to the user in one sentence.

Image pointers still deliver. They are function rather than reporting. The hook names the file it wrote, and you show that table only if the user's prompt asked for it.
