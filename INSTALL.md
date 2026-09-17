# Install DensePack, step by step

Follow the steps for your system, in order.
Type each command exactly, and press Enter after it.
You need a Claude Pro, Max, Team, Enterprise or Console account.
The free claude.ai plan does not include Claude Code.

- [Windows](#windows)
- [macOS](#macos)
- [Linux](#linux)
- [Run the benches](#run-the-benches)
- [Remove DensePack](#remove-densepack)

## Windows

1. Open the Start menu, type `PowerShell`, and open Windows PowerShell.
2. Optional: install Git for Windows from https://git-scm.com/downloads/win.
   Claude Code works without it and uses PowerShell instead.
3. Install Claude Code:
   `irm https://claude.ai/install.ps1 | iex`
4. Close PowerShell and open it again.
5. Check the install:
   `claude --version`
6. Make a folder for your project and go into it:
   `mkdir $HOME\myproject; cd $HOME\myproject`
7. Start Claude Code:
   `claude`
8. Log in with your Claude account in the browser window that opens.
9. When Claude Code asks about the folder, choose "Yes, I trust this folder".
10. Add the DensePack marketplace:
    `/plugin marketplace add Fabian-Galvez/DensePack`
11. Install the plugin:
    `/plugin install densepack@densepack-marketplace`
12. Close Claude Code:
    `/exit`
13. Start Claude Code again:
    `claude`
    On this first session the plugin installs Python 3.13 with winget, if Python is missing.
    It also installs Pillow, freetype-py and NumPy into the plugin's own folder.
14. If the plugin installed Python, type `/exit`, close PowerShell, open it again, and repeat steps 6 and 7.
15. Check that DensePack is on:
    `/helppack`
    Claude prints the DensePack commands.

## macOS

1. Open the Terminal app from Applications, Utilities.
2. Install Claude Code:
   `curl -fsSL https://claude.ai/install.sh | bash`
3. If the installer says that `~/.local/bin` is not in your PATH, type:
   `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc`
4. Check the install:
   `claude --version`
5. Make a folder for your project and go into it:
   `mkdir ~/myproject && cd ~/myproject`
6. Start Claude Code:
   `claude`
7. Log in with your Claude account in the browser window that opens.
8. When Claude Code asks about the folder, choose "Yes, I trust this folder".
9. Add the DensePack marketplace:
   `/plugin marketplace add Fabian-Galvez/DensePack`
10. Install the plugin:
    `/plugin install densepack@densepack-marketplace`
11. Close Claude Code:
    `/exit`
12. Start Claude Code again:
    `claude`
13. If Python 3.10 or newer is missing, DensePack shows a message with the command to install it.
    On macOS that command is `brew install python`, after you install Homebrew from https://brew.sh.
14. After Python installs, type `/exit`, then start `claude` again in your project folder.
    The plugin then installs Pillow, freetype-py and NumPy into its own folder.
15. Check that DensePack is on:
    `/helppack`
    Claude prints the DensePack commands.

## Linux

These steps use Ubuntu or Debian.
On Fedora, use `dnf` where a step says `apt`.

1. Open a terminal.
2. Install Claude Code:
   `curl -fsSL https://claude.ai/install.sh | bash`
3. If the installer says that `~/.local/bin` is not in your PATH, type:
   `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc`
4. Check the install:
   `claude --version`
5. Make a folder for your project and go into it:
   `mkdir ~/myproject && cd ~/myproject`
6. Start Claude Code:
   `claude`
7. Log in with your Claude account in the browser window that opens.
8. When Claude Code asks about the folder, choose "Yes, I trust this folder".
9. Add the DensePack marketplace:
   `/plugin marketplace add Fabian-Galvez/DensePack`
10. Install the plugin:
    `/plugin install densepack@densepack-marketplace`
11. Close Claude Code:
    `/exit`
12. Start Claude Code again:
    `claude`
13. If Python 3.10 or newer is missing, DensePack shows a message with the command to install it.
    On Ubuntu and Debian that command is `sudo apt install python3`.
14. After Python installs, type `/exit`, then start `claude` again in your project folder.
    The plugin then installs Pillow, freetype-py and NumPy into its own folder.
15. Check that DensePack is on:
    `/helppack`
    Claude prints the DensePack commands.

## Run the benches

Follow [bench/RUN-THE-BENCHES.md](bench/RUN-THE-BENCHES.md).

## Remove DensePack

1. Start Claude Code in your project folder, not in the marketplace folder:
   `claude`
2. Delete every DensePack file the uninstall leaves behind:
   `/dense-remove`
   It deletes the image copies in each project, the bench folders, the files under your home folder, and the trust of the marketplace folder.
3. Remove the plugin:
   `/plugin uninstall densepack`
   The uninstall deletes the plugin's data folder.
4. Remove the downloaded copy of this repository:
   `/plugin marketplace remove densepack-marketplace`
5. Close Claude Code:
   `/exit`

### Why the uninstall needs `/dense-remove`

No hook runs on uninstall, so no plugin can run code when it is uninstalled.
Claude Code itself deletes only the plugin's data folder, `~/.claude/plugins/data/densepack-densepack-marketplace`.

`/dense-remove` first undoes what DensePack changed:

- every converted `CLAUDE.md`, `CLAUDE.local.md` and `MEMORY.md` gets its original text back from its `.densepack.bak`, and the `.bak` is deleted
- `CLAUDE_CODE_THRIFTY_SONIC` leaves the `env` block of `~/.claude/settings.json`, when DensePack's value `0` is still there

Then it deletes the rest:

- `~/.claude/densepack-state` and `~/.claude/densepack-cards`
- the Python install markers
- `~/DensePack-arenas`
- leftover `densepack-trial-*.pkl` files in the temp folder
- each project's `.claude/densepack-vault` and its `densepack-*` files in `.claude/tmp`
- the trust entry of the marketplace folder, so a reinstall at the same path asks for trust again

It keeps every file that is not DensePack's, such as your settings, your transcripts and your own files in `.claude/tmp`.
Claude Code can write the trust entry back when the session you ran `/dense-remove` in closes.
