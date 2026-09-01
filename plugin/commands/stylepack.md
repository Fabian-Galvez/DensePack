---
description: Add the writing rules to the standing reminder, the short text sent before each message.
---

Run this exact command with the Bash tool:

p=python; command -v python >/dev/null 2>&1 || p=python3; "$p" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" stylecard on

Then relay the status line to the user in one sentence.

Off by default on purpose. The same card is usually installed personally at a hook of your own in ~/.claude/hooks, which runs in every project, and two copies would arrive twice and cost twice. Turn this on only where the personal one is missing, such as Claude Code on the web, which does not read ~/.claude/settings.json.
