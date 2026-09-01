---
description: Stop every DensePack hook. The one switch for all of it.
---

Run this exact command with the Bash tool:

p=python; command -v python >/dev/null 2>&1 || p=python3; "$p" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" off

Then relay the status line to the user in one sentence.

Nothing is uninstalled and no setting is lost. /densepack brings it all back.
