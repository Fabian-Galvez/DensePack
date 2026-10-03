---
description: Pack the instruction files of a folder, such as CLAUDE.md, CLAUDE.local.md, AGENTS.md and .claude/rules/*.md, into images and put a pointer in their place. The agent does not read them. DensePack packs a file only when its images and pointer cost less than its text.
argument-hint: "<folder>"
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead. Use the folder name after the command name in place of $ARGUMENTS.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" bakpack "$ARGUMENTS"

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" bakpack "$ARGUMENTS"

Then print the command's output exactly as it returns it. Do not read the files in that folder.

The images go to <folder>/.claude/densepack-vault/instruction-images. DensePack writes a .gitignore into that vault, and git ignores the images. /bakoff <folder> restores the originals of that folder.
