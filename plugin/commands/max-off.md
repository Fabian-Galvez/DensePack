---
description: Send Sonnet plain text. Sonnet gets images by default.
disable-model-invocation: true
---

Run the Bash line with the Bash tool. When Claude Code has no Bash tool, run the PowerShell line with the PowerShell tool instead.

Bash: r="${CLAUDE_PLUGIN_ROOT}"; [ -f "$r/scripts/dpctl.py" ] || { c="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins"; r=$(sh -c 'ls -t "$1"/synced/*/densepack/scripts/dpctl.py "$1"/cache/*/densepack/*/scripts/dpctl.py 2>/dev/null | head -1' sh "$c"); r="${r%/scripts/dpctl.py}"; echo "DensePack: CLAUDE_PLUGIN_ROOT was empty, so this command uses $r" >&2; }; sh "$r/scripts/run_hook.sh" "$r/scripts/dpctl.py" maxoff

PowerShell: powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run_hook.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" maxoff

Then relay the status line in one sentence.

Fable and Opus still get images. Reports to Fable or Opus main agents become images when the images and their Read cost less than the text. Reports to Sonnet main agents stay text.

Sonnet main agents still get the session start note. Claude Code does not name the model at session start, so DensePack cannot leave the note out. The note also covers Sonnet after /max-off, which gets text. Sonnet subagents get no note when DensePack finds their model at the start, because they never get an image.

The setting applies to each session in this project folder. Another project folder keeps its own setting.
