<!-- DensePack 2.0 -->
# Privacy policy

DensePack does all its work on your computer.

DensePack sends no file, no text and no image to an external service and collects no data. Claude Code sends your conversation to Anthropic in each turn. With DensePack on, it sends the images that DensePack makes in place of the text.

DensePack uses the network only to install what it needs.

- At session start, if the plugin cannot load Pillow, freetype-py or NumPy, it installs them with pip. The packages go into its own data folder, `~/.claude/plugins/data/densepack-densepack-marketplace/pylibs/`, so your Python stays as it is.
- On Windows, when the plugin finds no Python 3.10 or newer, it installs Python 3.13 with winget. The install runs in the background, once on each computer. On macOS and Linux, the plugin installs no Python and shows the command for you to run.
- On Windows, when the plugin finds no Git Bash, it installs Git for Windows with winget, once on each computer. DensePack runs the agent's commands in Bash.
- The right-click tool runs in your own Python. If Pillow, freetype-py or NumPy are missing, its Windows and Linux installers add them with `pip install --user`. The Windows installer also installs Python and AutoHotkey with winget when they are missing. The macOS Quick Action installs nothing.

The plugin contains the Inter font and downloads no font.

The HTML app, `index.html`, loads nothing from the network. It uses the fonts that are already on your computer, which needs no font download. It keeps its archive and its layout in the local storage of your browser, which stays on your computer.

DensePack saves files on your own disk only.

- The plugin saves its images and a copy of each packed text in each project's `.claude` folder and in `~/.claude`. They stay on disk after the session ends.
- The log `.claude/densepack-vault/why-text.log` in each project names the files and outputs that stayed text, with the reason. It stays on your computer, and `/dense-remove` deletes it with the vault.
- During a pack, the plugin works on a temporary copy of the text in the system temp folder. It deletes that copy after the pack. If a pack stops early, the next session deletes the leftover copy once it is an hour old.
- The plugin changes `~/.claude/settings.json` on your computer, and the instruction files that you convert with `/bakpack`. The originals stay beside their files as `<name>.bakpack`, and `/dense-remove` undoes the changes. See [HOW-IT-WORKS.md](HOW-IT-WORKS.md#what-densepack-changes) for each change.
- DensePack deletes the oldest vault folders when the vault is over its cap. To keep a conversation, run `python3 $HOME/.claude/plugins/cache/densepack-marketplace/densepack/2.0.2/scripts/dpctl.py keep <conversation>`. On Windows, write `py -3` in place of `python3`. It copies the conversation to `densepack-archive` in the project folder or to the keep folder that you set. No DensePack code deletes that folder.
- The right-click tool saves each image beside the source file, as `<file>.densepack-1.png`, `<file>.densepack-2.png` and so on.
- On Windows, the hotkeys save the text and the images of each pack in the two vault folders in `tools`. When the `tools` folder is read-only, they save them in `%LOCALAPPDATA%\DensePack`. The hotkeys also keep two small files in `%LOCALAPPDATA%\DensePack`. `tool.ini` saves your choice to hide the warning before a replace. `last-pack.txt` contains the list of images of the last pack, which the hotkey reads to find what to paste.
- The Windows installer of the right-click tool adds its right-click entry under `HKCU\Software\Classes`, which changes only your user account. It also puts a shortcut in the Startup folder, so the hotkeys start when you sign in. The installer also copies a reading card hook into `~/.claude/hooks` and adds its entry to `~/.claude/settings.json`.
- On Linux, the installer of the right-click tool writes `~/.local/share/densepack/densepack-file.sh` and `~/.local/share/applications/densepack.desktop`. Nautilus, Nemo and Caja show one right-click menu item for each script in their scripts folder. If one of them is on the computer, the installer copies a `DensePack it` script into that folder.
