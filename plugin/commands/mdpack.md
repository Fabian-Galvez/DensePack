---
description: Pack the CLAUDE.md, .claude/CLAUDE.md and CLAUDE.local.md of another folder into images and put a pointer in their place, without reading them. DensePack packs a file only when its images and pointer cost less than its text.
argument-hint: "<folder>"
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead. Use the folder name after the command name in place of $ARGUMENTS.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" mdpack "$ARGUMENTS"

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" mdpack "$ARGUMENTS"

Then print the command's output exactly as it returns it. Do not read the files in that folder.

The images go to <folder>/.claude/densepack-vault/instruction-images. DensePack writes a .gitignore into that vault, and git ignores the images. /dense-remove restores the originals.
