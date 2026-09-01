---
description: Make DensePack's delegation rules beat other plugins'.
---

Run this exact command with the Bash tool:

p=python; command -v python >/dev/null 2>&1 || p=python3; "$p" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" agentpack force

Then relay the status line to the user in one sentence.

Follow the new order yourself for the rest of this session: DensePack's delegation rules, as your briefing states them, now take precedence over delegation guidance from other plugins or defaults. The user's direct instructions still outrank everything.

This is also the default. /densepack reaches the same state. A terminal
call, `dpctl.py agentpack support`, puts them back to secondary, where they
yield to other plugins.
