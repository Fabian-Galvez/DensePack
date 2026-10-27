<!-- DensePack 2.0 -->
# Install DensePack

<br>

---

<br>

## Quick install

DensePack works in Claude Code and in Cowork. This section is for Claude Code, and [Install in Cowork](#install-in-cowork) is for Cowork.

If Claude Code already runs on your computer, type these two commands in Claude Code:

```
/plugin marketplace add Fabian-Galvez/DensePack
/plugin install densepack@densepack-marketplace
```

Then type `/exit` and start Claude Code again.

On macOS without the Xcode Command Line Tools, the first command fails with "git is not installed on this Mac". Claude Code downloads the plugin with Git. New Macs do not have them. Run this command in Terminal and choose Install in the window that opens. The download takes several minutes. Then type the two commands again.

```
xcode-select --install
```

On Windows without Git, the first command fails, because Claude Code downloads the plugin with Git. Run these 2 commands in PowerShell instead. The first one installs Git.

```
winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
```

Then open a new PowerShell window, so that it finds Git, and install the plugin. This command needs Claude Code 2.1.292 or later.

```
claude plugin install densepack --marketplace Fabian-Galvez/DensePack
```

<br>
<sub>Type `/densepack:helppack`. When it prints the table of DensePack commands, the plugin is installed. Claude Code needs `densepack:` before every DensePack command.</sub>

<br>

---

<br>

## Install in Cowork

Cowork gets plugins from your claude.ai account, not from the `/plugin` command of Claude Code. You add DensePack to your account online, and then check it in Cowork.

1. In your browser, open claude.ai, then Customize, then Plugins. In the Code tab of the Claude desktop app, the same page adds the plugin to Claude Code on that computer only, not to Cowork.
2. Select Add, then Add marketplace, and enter `Fabian-Galvez/DensePack`.
3. Add the densepack plugin from that marketplace, and turn it on.
4. In the Claude desktop app, open Cowork, then Customize, then Plugins, and check that DensePack is on.
5. Start a new Cowork task and type `/helppack`. When it prints the table of DensePack commands, the plugin is installed. If the commands do not show, start a new task, because Cowork loads plugins when a task starts.

Cowork uses the short command names, such as `/densepack` and `/dense-off`. The hooks run in Cowork too, so reads and command output arrive as images, the same as in Claude Code.

To get a new version, open the plugin in Customize, then Plugins, and select Check for updates. The plugin on your account also syncs to Claude Code when you sign in with the same account. When Claude Code also has DensePack from `/plugin install`, Claude Code uses that copy.

<br>

---

<br>

## What you need

- For Claude Code, Claude Pro, Max, Team, Enterprise or a Console account. The free claude.ai plan does not include Claude Code.
- For Cowork, the Claude desktop app, signed in to the claude.ai account that has DensePack.
- On Linux, you need Python 3.10 or newer.
- On macOS and Windows, DensePack downloads and installs Python 3.13 when it is missing.
- On macOS, you need the Xcode Command Line Tools, which bring Git. Claude Code downloads the plugin with Git. Run `xcode-select --install` in Terminal to install them. The Python of these tools is 3.9, which is too old for DensePack.
- Windows: Git for Windows, which brings Bash. Claude Code downloads the plugin with Git, and DensePack runs Claude Code with Bash because that is how it saves. It sets the two settings that [Install the plugin](README.md#install-the-plugin) shows.

- [Install walkthrough](#install-walkthrough)
- [Remove DensePack](#remove-densepack)
- [Install the right-click tool](#install-the-right-click-tool)

<br>

---

<br>

## Install walkthrough

This walkthrough is for Claude Code. For Cowork, see [Install in Cowork](#install-in-cowork).

<sub><strong>Windows: Git for Windows</strong>
<br>
Claude Code downloads the plugin with Git, so install Git before the plugin. In PowerShell, run `winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements`, or download Git from https://git-scm.com/downloads/win and install it with the default options.

If your Git Bash setup needs a password when it first opens, such as an SSH key password, enter it before you start Claude Code. Otherwise each Bash command in Claude Code fails.</sub>

<sub><strong>macOS: Xcode Command Line Tools</strong>
<br>
Claude Code downloads the plugin with Git, and a new Mac has no Git. In Terminal, run `xcode-select --install`, choose Install in the window that opens and wait for it to finish. `git --version` then prints a version. Homebrew installs these tools too.</sub>



### 1. Install Claude Code

| Your computer | Open                                                | Type                                              |
| ------------- | --------------------------------------------------- | ------------------------------------------------- |
| Windows       | Windows PowerShell, from the Start menu             | `irm https://claude.ai/install.ps1 \| iex`        |
| macOS         | Terminal, from the Utilities folder in Applications | `curl -fsSL https://claude.ai/install.sh \| bash` |
| Linux         | Your terminal                                       | `curl -fsSL https://claude.ai/install.sh \| bash` |

- On Windows, close PowerShell and open it again.
- On macOS and Linux, the installer can print that `~/.local/bin` is not in your PATH. Then type this command. On Linux, write `~/.bashrc` in place of `~/.zshrc`.

```
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

Check the install:
```
claude --version
```

### 2. Install DensePack

1. Make a folder for your project and change to that folder.

<strong>Windows:</strong> 
```PowerShell
mkdir $HOME\myproject; cd $HOME\myproject
```

<strong>macOS and Linux:</strong>
```Bash
mkdir ~/myproject && cd ~/myproject
```

2. Start Claude Code with `claude`. Sign in to your Claude account in the browser window that opens.
3. When Claude Code asks about the folder, choose "Yes, I trust this folder".
4. Type the two [Quick install](#quick-install) commands:
```
/plugin marketplace add Fabian-Galvez/DensePack
/plugin install densepack@densepack-marketplace
```
5. Type `/exit` and start `claude` again.

### 3. The first session

DensePack needs Python 3.10 or newer. It finds Python only by the names `python3`, `python` and `py`.

<strong>Windows:</strong> When DensePack does not find Python 3.10 or newer, it downloads and installs Python 3.13 with winget in `%LOCALAPPDATA%\Programs\Python\Python313`. The install runs in the background, so a slow connection does not cut it off.

The install leaves out Tcl/Tk (`tkinter`) and the Python test suite, which DensePack does not use. To add them later, open Settings, Apps, Python 3.13 and choose Modify.

Wait a few minutes, then type `/exit` and close PowerShell. Open PowerShell again and type these commands.

```
cd $HOME\myproject
claude
```

- If winget is missing, install Python 3.10 or newer from https://www.python.org.
- To try the winget install again, type `/exit` and run this command in PowerShell. Then start Claude Code again.

```PowerShell
Remove-Item $HOME\.claude\plugins\data\densepack-densepack-marketplace\python-install-tried
```

<strong>macOS:</strong> When DensePack does not find Python 3.10 or newer, it downloads [uv](https://docs.astral.sh/uv) and uses it to download and install Python 3.13 in the background. It needs no password. It also downloads and installs Pillow, freetype-py and NumPy. On a Mac mini with an Intel processor and a home connection, the whole install took 8 to 39 seconds in tests.

- uv and Python go into the data folder of the plugin, `~/.claude/plugins/data/densepack-densepack-marketplace`. DensePack does not change your PATH, your shell files, `~/.local/bin` or a Python that you installed.
- The uv download is checked against its SHA-256 before it runs. DensePack deletes uv after the install.
- DensePack starts packing in the same session when the install is done, with no restart. Hooks that start during the install wait for it, up to 45 seconds.
- `/plugin uninstall densepack` deletes the data folder, and this Python with it.

If the install fails, the start message names its log, `python-install.log` in the data folder. Then use one of these routes, or delete `python-install-tried` in the data folder to let DensePack try again.

- To use Homebrew, install it from https://brew.sh and then run `brew install python`. The Homebrew installer asks for your password.
- To use uv, install it from https://docs.astral.sh/uv and then run `uv python install --default`. The `--default` option adds the name `python3` in `~/.local/bin`. DensePack looks in that folder too, also when the Claude desktop app starts it with a PATH that lacks it.

<strong>Linux:</strong> When Python is missing, DensePack shows the command that installs it.

<strong>Ubuntu and Debian:</strong>
```Bash
sudo apt install python3 python3-pip
```
<strong>Fedora:</strong>
```Bash
sudo dnf install python3 python3-pip
```
<strong>Arch Linux:</strong>
```Bash
sudo pacman -S python python-pip
```
<strong>Other systems:</strong> Install Python 3.10 or newer with your package manager.

On Linux, type `/exit` after the Python install and start `claude` again in your project folder. DensePack shows the install commands only in the first session. To see them again, delete `~/.claude/plugins/data/densepack-densepack-marketplace/python-install-tried`.

<strong>Then, on each system:</strong>

- DensePack downloads and installs Pillow, freetype-py and NumPy into its own folder.
- If that install fails, DensePack shows a `pip` command at each session start. That command installs them into the Python that DensePack runs.
- Type `/densepack:helppack`. When it prints the table of DensePack commands, the plugin is installed.

<br>

---

<br>

## Remove DensePack

To remove DensePack from Cowork, open it on claude.ai in Customize, then Plugins, open its menu and select Remove. The steps below remove it from Claude Code.

1. Start Claude Code in your project folder, not in the marketplace folder.
```
claude
```
2. Delete the DensePack files that the uninstall does not delete.
```
/densepack:dense-remove
```
3. Remove the plugin. The uninstall deletes the data folder of the plugin.
```
/plugin uninstall densepack
```
4. If you installed the right-click tool from this folder, uninstall it first, and copy out the `ctrl-shift-vault` and `ctrl-right_click-vault` folders that you want to keep. The next command deletes this folder. On Windows, double-click `tools\uninstall-densepack.bat`. On Linux, run `sh tools/uninstall-densepack.sh`. On macOS, delete `~/Library/Services/DensePack it.workflow`.
5. Remove the downloaded copy of this repository.
```
/plugin marketplace remove densepack-marketplace
```
6. Close Claude Code.
```
/exit
```

### What `/dense-remove` does

Plugins cannot run code during an uninstall. Claude Code deletes only the data folder of the plugin, `~/.claude/plugins/data/densepack-densepack-marketplace`. `/dense-remove` first undoes the changes that DensePack made.

- It restores the original text of each converted `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `.claude/rules/*.md` and `MEMORY.md` from its `.bakpack`. Text that you added below the pointer stays at the end of the file. Then it deletes the `.bakpack` and the images of that file.
- It removes `CLAUDE_CODE_THRIFTY_SONIC`, `EMBEDDED_SEARCH_TOOLS` and `CLAUDE_CODE_USE_POWERSHELL_TOOL` from the `env` block of `~/.claude/settings.json` when each still has the value that DensePack wrote.
- It deletes `~/.claude/densepack-state`, `~/.claude/densepack-cards` and `~/.claude/densepack-tracker.json`.
- It deletes the Python install markers in `~/.densepack`. In `%LOCALAPPDATA%\densepack`, it deletes only the files `python-install-tried`, `python-install-running` and `git-install-tried`, because the right-click tool keeps its own files in that folder.
- It deletes the `densepack-trial-*.pkl` files in the temp folder.
- In each project that a transcript in `~/.claude/projects` names, it deletes the `.claude/densepack-vault` folder and the `densepack-*` and `.densepack-*` files in `.claude/tmp`.
- It deletes the trust entry of the marketplace folder. Claude Code asks for trust again when you reinstall at the same path.

It keeps your settings, your transcripts, your own files in `.claude/tmp`, each older `<name>.bakpack.old-N` copy and the `densepack-archive` folder that `dpctl.py keep` makes.

Some DensePack files can stay after `/dense-remove`.

- Projects whose transcripts are no longer in `~/.claude/projects` keep their `.claude/densepack-vault` folder and their `densepack-*` files in `.claude/tmp`. Delete them by hand.
- The hooks of the `/dense-remove` session run until you close it. They can write a few `densepack-*` files in `.claude/tmp` and the trust entry again. Delete those files by hand after you close Claude Code.
- `/dense-remove` keeps the Python from winget. If no other program needs it, remove it with `winget uninstall --id Python.Python.3.13`.
- `/dense-remove` keeps the right-click tool. [tools/Tool-README.md](tools/Tool-README.md) has the steps to uninstall it.

<br>

---

<br>

## Install the right-click tool

The right-click tool packs files from the right-click menu of your file manager. It needs the files of this repository. It does not need Claude Code or the plugin.

- If you installed the plugin, the files are in `%USERPROFILE%\.claude\plugins\marketplaces\densepack-marketplace` on Windows and in `~/.claude/plugins/marketplaces/densepack-marketplace` on macOS and Linux.
- If you did not install the plugin, download this repository. Click the green **Code** button at the top of this page, then choose **Download ZIP** and unzip it.

Open the `tools` folder and start the installer.

| Your computer | Start the installer                                                                                                                                               |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Windows       | Double-click `install-densepack.bat`                                                                                                                              |
| macOS         | Double-click `DensePack it.workflow` and choose Install. In Finder, right-click a file, then choose Quick Actions, then DensePack it. The workflow runs `tools/densepack.py` from `~/DensePack`, or else from the plugin's download in `~/.claude/plugins/marketplaces/densepack-marketplace`. When the plugin is installed and has run once, the workflow uses its Python and packages and needs no other install. Without the plugin, run `brew install python`, then `python3 -m pip install --user --break-system-packages pillow freetype-py numpy` |
| Linux         | Open a terminal in that folder and run `sh install-densepack.sh`                                                                                                  |

[tools/Tool-README.md](tools/Tool-README.md) has what each installer changes, the hotkeys and the steps to uninstall.
