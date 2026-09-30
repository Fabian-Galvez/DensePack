<!-- DensePack 1.3.2 -->
# Privacy policy

DensePack does all its work on your computer.

DensePack sends no file, no text and no image to an external service and collects no data. Claude Code sends the images that DensePack makes to Anthropic in each turn, in place of the text that it sends when DensePack is off.

DensePack uses the network only to install what it needs.

- At session start, when the plugin cannot load Pillow, freetype-py or NumPy, it installs the three packages with pip into its own data folder, `~/.claude/plugins/data/densepack-densepack-marketplace/pylibs/`. The plugin does not change your Python.
- On Windows, when the plugin finds no Python 3.10 or newer, it tries one time to install Python 3.13 with winget. On macOS and Linux, the plugin installs no Python and shows the command for you to run.
- The installers of the right-click tool for Windows and Linux install Pillow, freetype-py and NumPy into your own Python with `pip install --user` when they are missing. The Windows installer also installs Python and AutoHotkey with winget when they are missing. The macOS Quick Action installs nothing.

The plugin contains the Inter font and downloads no font.

The HTML app, `index.html`, loads nothing from the network. It uses the fonts that are already on your computer, and it keeps its archive and its layout in the local storage of your browser.

DensePack saves files on your own disk only.

- The plugin saves the images it makes and copies of the text it packs in the `.claude` folder of each project and in `~/.claude`.
- During a pack, the plugin puts a temporary copy of the text in the system temp folder and deletes that copy after the pack.
- When the images and the pointer of a `CLAUDE.md`, `CLAUDE.local.md` or `MEMORY.md` cost less than its text, the plugin replaces that text with the pointer and keeps the original beside the file as `<name>.densepack.bak`.
- When `~/.claude/settings.json` has no `CLAUDE_CODE_THRIFTY_SONIC` entry, the plugin sets it to 0 there.
- `/dense-remove` restores the originals and removes that setting.
- `dpctl.py keep <conversation>` copies one conversation from the vault into `densepack-archive` in the project folder, or into the keep folder that you set. No DensePack code deletes that folder.
- The right-click tool saves each image beside the source file, as `<file>.densepack-1.png`, `<file>.densepack-2.png` and so on.
- On Windows, the hotkeys save the text and the images of each pack in the two vault folders in `tools`. When the `tools` folder is read-only, they save them in `%LOCALAPPDATA%\DensePack`. The hotkeys also keep two small files in `%LOCALAPPDATA%\DensePack`, `tool.ini` for the warning setting and `last-pack.txt` for the list of images of the last pack.
- On Windows, the installer of the right-click tool adds a right-click entry under `HKCU\Software\Classes` and a hotkey shortcut in the Startup folder. It also copies a reading card hook into `~/.claude/hooks` and adds its entry to `~/.claude/settings.json`.
- On Linux, the installer of the right-click tool writes `~/.local/share/densepack/densepack-file.sh` and `~/.local/share/applications/densepack.desktop`. It also copies a `DensePack it` script into the scripts folder of Nautilus, Nemo and Caja when they are installed.
