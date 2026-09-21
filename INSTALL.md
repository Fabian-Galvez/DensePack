<!-- DensePack 1.1 -->
# Install DensePack, step by step

Follow the steps for your system, in order.
Type each command exactly and press Enter after it.
You need a Claude Pro, Max, Team, Enterprise or Console account.
The free claude.ai plan does not include Claude Code.

- [Windows](#windows)
- [macOS](#macos)
- [Linux](#linux)
- [Run the benches](#run-the-benches)
- [Remove DensePack](#remove-densepack)

## Windows

1. Open the Start menu, type `PowerShell` and open Windows PowerShell.
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
8. Sign in to your Claude account in the browser window that opens.
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
14. If the plugin installed Python, type `/exit`, close PowerShell, open it again and repeat steps 6 and 7.
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
7. Sign in to your Claude account in the browser window that opens.
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
7. Sign in to your Claude account in the browser window that opens.
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
    On Ubuntu and Debian that command is `sudo apt install python3 python3-pip`.
14. After Python installs, type `/exit`, then start `claude` again in your project folder.
    The plugin then installs Pillow, freetype-py and NumPy into its own folder.
15. Check that DensePack is on:
    `/helppack`
    Claude prints the DensePack commands.

## The size ceiling

DensePack turns a file into pictures the first time you read it. A big file
takes a while. You wait once per file. DensePack saves the pictures.
Each later read of that file is fast.

DensePack skips each file over 500,000 bytes. You wait a long time only when you
raise the limit yourself.

| File size | Wait, the first time only |
| --- | --- |
| 1,000 characters | 0.15 seconds |
| 250,000 bytes, 0.25 MB | about 38 seconds |
| 500,000 bytes, 0.5 MB | about 75 seconds. The limit |
| 1,000,000 bytes, 1 MB | about 2.5 minutes |
| 2,000,000 bytes, 2 MB | about 5 minutes |

A file over the limit is still read. You read it as text and save nothing on
it. Word files are the one exception. Claude Code cannot open a Word file on
its own. Nothing can read a Word file over the limit.

Big files are the ones that save the most. If you want to wait and keep
the saving, raise the limit. Paste this into Claude Code:

```
Raise DensePack's READ_MAX_BYTES to 1000000
```

`READ_MAX_BYTES` is a number in the plugin's file `plugin/scripts/drop_read_gate.py`. It is not a setting. Claude Code edits that file in the installed copy of the plugin. A plugin update replaces the file. Make the change again after an update.

Word files count the same way. DensePack reads and draws `.docx` and the older `.doc`
like all other files, with no extra step and no extra install. Claude
Code cannot open either one on its own.

## Run the benches

Follow [bench/RUN-THE-BENCHES.md](bench/RUN-THE-BENCHES.md).

## Remove DensePack

1. Start Claude Code in your project folder, not in the marketplace folder:
   `claude`
2. Delete all DensePack files the uninstall leaves behind:
   `/dense-remove`
   It deletes the image copies in each project, the bench folders, the files in your home folder and the trust of the marketplace folder.
3. Remove the plugin:
   `/plugin uninstall densepack`
   The uninstall deletes the plugin's data folder.
4. Remove the downloaded copy of this repository:
   `/plugin marketplace remove densepack-marketplace`
5. Close Claude Code:
   `/exit`

### Why the uninstall needs `/dense-remove`

No hook runs on uninstall. No plugin can run code during an uninstall.
Claude Code itself deletes only the plugin's data folder, `~/.claude/plugins/data/densepack-densepack-marketplace`.

`/dense-remove` first undoes what DensePack changed:

- each converted `CLAUDE.md`, `CLAUDE.local.md` and `MEMORY.md` gets its original text back from its `.densepack.bak`. Then `/dense-remove` deletes the `.bak`
- `CLAUDE_CODE_THRIFTY_SONIC` leaves the `env` block of `~/.claude/settings.json`, when DensePack's value `0` is still there

Then it deletes the rest:

- `~/.claude/densepack-state` and `~/.claude/densepack-cards`
- the Python install markers
- `~/DensePack-arenas`
- leftover `densepack-trial-*.pkl` files in the temp folder
- each project's `.claude/densepack-vault` and its `densepack-*` files in `.claude/tmp`
- the trust entry of the marketplace folder. A reinstall at the same path asks for trust again

It keeps all files that are not DensePack's, such as your settings, your transcripts and your own files in `.claude/tmp`.
Claude Code can write the trust entry back when you close the session that ran `/dense-remove`.

<br>

---

<br>

## Work for the most savings

DensePack saves the most in long conversations that read many files, such as auditing a repository.
A short session that mostly runs commands saves little because only file reads become images.

**A repository that has a `CLAUDE.md`:**

1. Start Claude Code in a folder next to the repository, not inside it. Claude Code does not load the repository's `CLAUDE.md` there.
2. Run `/mdpack <path to the repository>`. DensePack converts the repository's `CLAUDE.md` into images behind a pointer. The agent reads none of the text.
3. Exit and start a new session inside the repository. Its first session loads the pointer and reads the images. The text is never sent.

**Auditing or reading a repository:**

1. Start Claude Code in an empty folder outside the repository.
2. Point the agent at the repository. Each file it reads arrives as images.
3. This is how the benches ran.

**In each session:**

- Read files with the Read tool. DensePack packs a Bash read (`cat`, `head`, `sed`, `type`) too. A Bash read takes an extra turn. The file has to be bigger before a Bash read saves.
- Keep working in the same session. Each later turn reads the images again at the cheaper size. The saving grows with the conversation.
- Your `~/.claude/CLAUDE.md` and each project's `MEMORY.md` convert on their own at session start. The session that converts them still sends their text once.

<br> 
<br>

---

<br>

## Install the right-click tool

The right-click tool uses files from this repository. You need a copy of them on your computer.

<strong>If you installed the plugin</strong>, you have them, in this folder:

- Windows: `%USERPROFILE%\.claude\plugins\marketplaces\densepack-marketplace`
- macOS and Linux: `~/.claude/plugins/marketplaces/densepack-marketplace`

<strong>If you did not install the plugin</strong>, click the green **Code** button at the top of this page, choose **Download ZIP** and unzip it.

<strong>Open the `tools` folder inside it and start the installer.</strong>

| Your computer | What to do |
| --- | --- |
| Windows | Double-click `install-densepack.bat` |
| macOS | Double-click `DensePack it.workflow` |
| Linux | Open a terminal in that folder and run `sh install-densepack.sh` |

The installer does the rest. [tools/Tool-README.md](tools/Tool-README.md) says what it changes, how to skip the hotkeys, how to skip the reading card and how to uninstall.

On Windows, `Ctrl + Shift + D` and the menu item DensePack it remove the selected text and paste the image in its place. The tool saves the text and all images of each pack in `tools\ctrl-shift-vault` or `tools\ctrl-right_click-vault`. A window tells you this the first time. One check box stops the window.
<br>
<sub>The right-click tool needs this repository on your machine. You do not need Claude Code or the plugin.</sub>
<br>

---

<br>

## Use the HTML app

Download [index.html](index.html) from this repository and open it in a browser.
It needs no install and it makes the images in your browser.
Paste a file, watch the token count fall and download the image or copy it
to paste into an AI chat.

| Control | What it changes |
| --- | --- |
| Reader | Picks the type size for the model that will read the image |
| Width | Auto picks a near-square image shape. 1024, 1536 and 1932 px set it by hand |
| Type | The glyph size, the line height and the letter spacing |
| Code mode | Produces the banded code image instead of plain prose |
| Colours | The number ink, the symbol ink and the mark ink |
| Download PNG, Copy image, Copy | Saves the image, puts it on the clipboard, or copies the Complementary Prompt |

The HTML app uses its own renderer and prints a pilcrow at each line end
where the plugin prints a line number. 
