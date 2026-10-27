# DensePack

DensePack is a plugin for Claude Code and Cowork. It packs file Reads and long Bash output into images, so the model reads fewer tokens.

Install steps, commands and benchmarks are in the full README at https://github.com/Fabian-Galvez/DensePack.

Claude Code needs `densepack:` before every command, such as `/densepack:helppack`. Cowork uses the short names, such as `/helppack`.

## What DensePack changes in Claude Code

DensePack changes how the agent works in each session where the plugin is on.

- Its session start hook puts the writing rules in `rules/STYLE-RULES.md` and a map of your project in the agent's start note. Its hooks repeat a one-line reminder of the rules after each prompt and each batch of tool calls. The rules make the agent write shorter replies, docs and code. Subagents get the same rules. Edit `rules/STYLE-RULES.md` to change them, or delete it to stop the rules and the map.
- It adds `"CLAUDE_CODE_THRIFTY_SONIC": "0"` to the `env` block of `~/.claude/settings.json`. This turns off an instruction from Claude Code to read files with `cat`, so the agent uses Read, which DensePack packs.
- On Windows with Git for Windows, it also adds `"EMBEDDED_SEARCH_TOOLS": "1"` and `"CLAUDE_CODE_USE_POWERSHELL_TOOL": "0"`. They remove the Grep and Glob tools and run commands in Git Bash. The agent then searches with `grep` in Bash, so DensePack packs that output.

The settings apply to all your projects from the next session. DensePack never changes a value that you set yourself. `/densepack:dense-remove` deletes the settings that DensePack added.

## What DensePack runs and downloads

DensePack sends no file, text or image to an outside service. It uses the network only to download and install what it needs, once on each computer:

- At session start, if Pillow, freetype-py or NumPy is missing, it downloads and installs them from PyPI with pip. They go into the plugin's own data folder.
- On macOS with no Python 3.10 or newer, it downloads uv 0.13.5 from the uv releases on GitHub and checks its SHA-256. uv downloads and installs Python 3.13 from the python-build-standalone releases on GitHub into the plugin's data folder. Then pip downloads and installs the three packages, and DensePack deletes uv.
- On Windows with no Python 3.10 or newer, it downloads and installs Python 3.13 with winget.
- On Windows with no Git Bash, it downloads and installs Git for Windows with winget.
- On Linux, it installs no Python and shows the command for you to run.

The macOS install needs no password and changes no PATH. The plugin uninstall deletes the data folder and what is in it. PRIVACY-POLICY.md in the repository has the details.

The license is MIT. See LICENSE in this folder.
