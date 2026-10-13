---
description: Experimental: the benches did not run it, so it has not been thoroughly tested. Packs the instruction files of this project, or of a folder you name, into images behind a pointer. DensePack packs a file only when its images and pointer cost less than its text.
argument-hint: "[folder]"
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead. Use the folder name after the command name in place of $ARGUMENTS, or nothing when there is none.

Bash: sh "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" bakpack "$ARGUMENTS"

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" bakpack "$ARGUMENTS"

Then print the command's output exactly as it returns it. Do not read the files in that folder.

DensePack converts no file on its own. With no folder, this command packs CLAUDE.md, .claude/CLAUDE.md, CLAUDE.local.md, AGENTS.md and .claude/rules/*.md of this project and its memory index MEMORY.md. With a folder, it packs those files of that folder. /bakpack ~/.claude packs your personal CLAUDE.md, which applies to every project.

The next session gets the images. /bak-off turns the files back into text.
