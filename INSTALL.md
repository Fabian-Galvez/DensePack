<!-- DensePack 1.3.4 -->
# Install DensePack

Follow the steps for your system in order. Type each command exactly and press Enter after it.

You need a Claude Pro, Max, Team, Enterprise or Console account. The free claude.ai plan does not include Claude Code.

The DensePack repository is https://github.com/Fabian-Galvez/DensePack. The two plugin commands in the steps below install DensePack from it.

| Model | What DensePack sends |
| --- | --- |
| Fable and Opus | DensePack sends images |
| Sonnet | DensePack sends images. After `/max-off`, it sends text, and after `/maxpack`, it sends images again |
| Haiku and other models | DensePack sends text |

DensePack packs the files that you copy into `.claude/densepack-vault/to-pack/` and some Word files into images for all models. [The size limit](#the-size-limit) lists the Word files that DensePack packs.

- [Windows](#windows)
- [macOS](#macos)
- [Linux](#linux)
- [The size limit](#the-size-limit)
- [Remove DensePack](#remove-densepack)
- [Save the most](#save-the-most)
- [Install the right-click tool](#install-the-right-click-tool)
- [Use the HTML app](#use-the-html-app)

<br>

---

<br>

## Windows

1. Open the Start menu, type `PowerShell` and open Windows PowerShell.
2. Install Git for Windows from https://git-scm.com/downloads/win. This step is optional. Without Git, Claude Code runs commands in PowerShell, and DensePack packs no command output because it packs only Bash output.
3. Install Claude Code.
   `irm https://claude.ai/install.ps1 | iex`
4. Close PowerShell and open it again.
5. Check the install.
   `claude --version`
6. Make a folder for your project and change to that folder.
   `mkdir $HOME\myproject; cd $HOME\myproject`
7. Start Claude Code.
   `claude`
8. Sign in to your Claude account in the browser window that opens.
9. When Claude Code asks about the folder, choose "Yes, I trust this folder".
10. Add the DensePack marketplace.
    `/plugin marketplace add Fabian-Galvez/DensePack`
11. Install the plugin.
    `/plugin install densepack@densepack-marketplace`
12. Close Claude Code.
    `/exit`
13. Start Claude Code again.
    `claude`
    - In this first session, the plugin installs Python 3.13 with winget when it finds no Python 3.10 or newer. The plugin tries this install one time.
    - If winget is missing, install Python 3.10 or newer from https://www.python.org.
    - To make the plugin try the winget install again, type `/exit`, run this command in PowerShell and start Claude Code again.
      `Remove-Item $HOME\.claude\plugins\data\densepack-densepack-marketplace\python-install-tried`
    - If Python 3.10 or newer is installed and Pillow, freetype-py or NumPy is missing, the plugin installs them into its own folder in this session. If that install fails, DensePack shows a `pip` command at each session start that installs them into your own Python.
14. If the plugin installed Python, type `/exit` and close PowerShell. Open PowerShell again and type these two commands. The plugin then installs Pillow, freetype-py and NumPy into its own folder.
    `cd $HOME\myproject`
    `claude`
15. Check that DensePack is on.
    `/helppack`
    Claude prints the DensePack commands.

<br>

---

<br>

## macOS

1. Open the Terminal app from the Utilities folder in Applications.
2. Install Claude Code.
   `curl -fsSL https://claude.ai/install.sh | bash`
3. If the installer says that `~/.local/bin` is not in your PATH, type this command.
   `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc`
4. Check the install.
   `claude --version`
5. Make a folder for your project and change to that folder.
   `mkdir ~/myproject && cd ~/myproject`
6. Start Claude Code.
   `claude`
7. Sign in to your Claude account in the browser window that opens.
8. When Claude Code asks about the folder, choose "Yes, I trust this folder".
9. Add the DensePack marketplace.
   `/plugin marketplace add Fabian-Galvez/DensePack`
10. Install the plugin.
    `/plugin install densepack@densepack-marketplace`
11. Close Claude Code.
    `/exit`
12. Start Claude Code again.
    `claude`
    If Python 3.10 or newer is installed and Pillow, freetype-py or NumPy is missing, the plugin installs them into its own folder in this session. If that install fails, DensePack shows a `pip` command at each session start that installs them into your own Python.
13. If Python 3.10 or newer is missing, DensePack shows a message with two ways to install it. Use one of them.
    - To use Homebrew, install Homebrew from https://brew.sh and then run `brew install python`.
    - To use uv, install uv from https://docs.astral.sh/uv and then run `uv python install --default`. DensePack finds Python only by the names `python3`, `python` and `py`, and the `--default` option adds the name `python3`. Without `--default`, uv adds only a name that contains the version, such as `python3.13`, and DensePack does not find that Python.

    DensePack shows the commands only in the first session and shows a short message without them in later sessions. To see the commands again, delete `~/.claude/plugins/data/densepack-densepack-marketplace/python-install-tried`.
14. After the Python install, type `/exit` and start `claude` again in your project folder. The plugin then installs Pillow, freetype-py and NumPy into its own folder.
15. Check that DensePack is on.
    `/helppack`
    Claude prints the DensePack commands.

<br>

---

<br>

## Linux

These steps are the same on each Linux system. Only step 13 names a package manager.

1. Open a terminal.
2. Install Claude Code.
   `curl -fsSL https://claude.ai/install.sh | bash`
3. If the installer says that `~/.local/bin` is not in your PATH, type this command.
   `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc`
4. Check the install.
   `claude --version`
5. Make a folder for your project and change to that folder.
   `mkdir ~/myproject && cd ~/myproject`
6. Start Claude Code.
   `claude`
7. Sign in to your Claude account in the browser window that opens.
8. When Claude Code asks about the folder, choose "Yes, I trust this folder".
9. Add the DensePack marketplace.
   `/plugin marketplace add Fabian-Galvez/DensePack`
10. Install the plugin.
    `/plugin install densepack@densepack-marketplace`
11. Close Claude Code.
    `/exit`
12. Start Claude Code again.
    `claude`
    If Python 3.10 or newer is installed and Pillow, freetype-py or NumPy is missing, the plugin installs them into its own folder in this session. If that install fails, DensePack shows a `pip` command at each session start that installs them into your own Python.
13. If Python 3.10 or newer is missing, DensePack shows a message with the command that installs it.
    - On Ubuntu and Debian, run `sudo apt install python3 python3-pip`.
    - On Fedora, run `sudo dnf install python3 python3-pip`.
    - On Arch Linux, run `sudo pacman -S python python-pip`.
    - On systems without these package managers, the message says to install Python 3.10 or newer with your package manager.

    DensePack shows the message with the command only in the first session and shows a short message without it in later sessions. To see the command again, delete `~/.claude/plugins/data/densepack-densepack-marketplace/python-install-tried`.
14. After the Python install, type `/exit` and start `claude` again in your project folder. The plugin then installs Pillow, freetype-py and NumPy into its own folder.
15. Check that DensePack is on.
    `/helppack`
    Claude prints the DensePack commands.

<br>

---

<br>

## The size limit

DensePack does not pack files over 1,000,000 bytes.

### Pack times

DensePack packs a file into images the first time the agent reads it.

- DensePack saves the images of the whole file, and later Reads of the whole file are fast.
- DensePack packs the lines again at each Read that has an offset and no limit or a limit of more than 20 lines.
- After a change to the file or a new plugin version, DensePack packs the file again.
- At session start, DensePack deletes images older than 24 hours and packs those files again at their next Read.
- The Read tool of Claude Code rejects files over 256 KB. DensePack still packs those files, and the agent gets a note that names the images and opens the first image with one more Read.

The table below lists the first wait for five file sizes. The pack times come from tests on one computer, and the wait is longer when DensePack packs files in other sessions at the same time.

| File size | First wait |
| --- | --- |
| 4,453 bytes | 1.0 seconds |
| 22,024 bytes | 1.4 seconds |
| 94,618 bytes | 4.9 seconds |
| 127,466 bytes | 8.1 seconds |
| about 300,000 bytes | 14 to 17 seconds |

The wait increases with the size of the file.

### Folders

When your message names a folder by its full path or says "this folder", DensePack gives the agent the file names of that folder and packs those files in the background before the agent reads them.

- "This folder", "the current folder", "the project folder" and the same words with "directory" mean the folder where you started Claude Code.
- The folder must be at least two levels below the root of the disk, such as `C:\Users\you` or `/home/you`.
- DensePack does not find folder paths that contain a space.
- DensePack gives the agent the file names of up to 4 folders for each message.
- DensePack skips folders with more than 200 files.
- DensePack packs nothing when the files that it can pack contain more than 700,000 bytes in total.

### Word files

DensePack packs `.docx` files and older `.doc` files the same way as other files, and they need no extra step and no extra install.

- DensePack packs the Word files that your message names.
- After each Glob, Grep, Bash or LS call, DensePack packs up to 6 of the Word files that the result names by full path.
- If your message names no Word file, DensePack packs up to 8 Word files from the folders that your message names by full path before it sends your message to the model.
- This Word pack has no 200-file limit and no 700,000-byte limit, and "this folder" does not start it.

### Files over the limit

- The agent reads files over the limit as text, and DensePack saves nothing on them.
- Word files over the limit get no images, and the Read tool cannot open them. DensePack tells the agent why and tells it to read the text with a shell command.
- The same limit applies to Word files and to Bash output.
- For Word files, DensePack measures the text in the file, not the size of the file.
- For Bash output, DensePack counts the characters.

### Raise the limit

To pack a file over 1,000,000 bytes, raise the limit and accept the wait. Paste this line into Claude Code.

```
Raise DensePack's READ_MAX_BYTES to 2000000
```

- `READ_MAX_BYTES` is a number in the file `scripts/drop_read_gate.py` of the installed plugin in `~/.claude/plugins/cache/densepack-marketplace/densepack/<version>`.
- It is not a setting, and Claude Code edits the number in that file when you paste the line.
- DensePack does not run the copy in the marketplace folder.
- Plugin updates replace the file. Make the change again after each update.

### Files that stay text

- Files smaller than 1,000 bytes stay text.
- Files with a null byte stay text.
- Files stay text when the font has no glyph for more than 2% of the characters that are not spaces, such as files in Chinese, Japanese or Korean.
- Files in a `.claude` folder and files in the scratchpad folder of Claude Code stay text. DensePack still packs Word files in these locations.
- Files stay text when their images and note cost as much as their text or more.
- All files stay text when Pillow, freetype-py or NumPy is missing.

<br>

---

<br>

## Remove DensePack

1. Start Claude Code in your project folder, not in the marketplace folder.
   `claude`
2. Delete the DensePack files that the uninstall does not delete.
   `/dense-remove`
   - `/dense-remove` restores each converted instruction file to its original text.
   - It deletes the images in each project folder that a transcript in `~/.claude/projects` names.
   - It deletes the DensePack files in your home folder.
   - It deletes the trust entry of the marketplace folder.
3. Remove the plugin.
   `/plugin uninstall densepack`
   The uninstall deletes the data folder of the plugin.
4. Remove the downloaded copy of this repository.
   `/plugin marketplace remove densepack-marketplace`
5. Close Claude Code.
   `/exit`

### What `/dense-remove` does

Plugins cannot run code during an uninstall, and Claude Code deletes only the data folder of the plugin, `~/.claude/plugins/data/densepack-densepack-marketplace`.

`/dense-remove` first undoes the changes that DensePack made.

- It restores the original text of each converted `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `.claude/rules/*.md` and `MEMORY.md` from its `.bakpack`. Text that you added below the pointer stays at the end of the file. Then it deletes the `.bakpack` and the images of that file.
- It removes `CLAUDE_CODE_THRIFTY_SONIC` from the `env` block of `~/.claude/settings.json` when the value is still the `0` that DensePack wrote.

Then it deletes the files and folders below.

- It deletes `~/.claude/densepack-state` and `~/.claude/densepack-cards`.
- It deletes `~/.claude/densepack-tracker.json`, which only versions before DensePack 1.0 wrote.
- It deletes the Python install markers in `~/.densepack` and `%LOCALAPPDATA%\densepack`. In `%LOCALAPPDATA%\densepack`, it deletes only the file `python-install-tried`, because the right-click tool keeps its own files in `%LOCALAPPDATA%\DensePack` and Windows treats the two names as one folder.
- It deletes the `densepack-trial-*.pkl` files in the temp folder.
- It deletes the `.claude/densepack-vault` folder and the `densepack-*` and `.densepack-*` files in `.claude/tmp` of each folder that a transcript in `~/.claude/projects` names.
- It deletes the trust entry of the marketplace folder. Claude Code asks for trust again when you reinstall at the same path.

It keeps all other files. The list below gives examples.

- It keeps your settings and your transcripts.
- It keeps your own files in `.claude/tmp` and the `.gitignore` that DensePack wrote in `.claude/tmp`.
- It keeps each older `<name>.bakpack.old-N` copy and the `densepack-archive` folder that `dpctl.py keep <conversation>` makes.

Claude Code can write the trust entry again when you close the session that ran `/dense-remove`.

Some DensePack files can stay after `/dense-remove`.

- Projects whose transcripts are no longer in `~/.claude/projects` keep their `.claude/densepack-vault` folder and their `densepack-*` files in `.claude/tmp`. Delete them by hand.
- The hooks of the session that ran `/dense-remove` still run until you close it. They can write a few `densepack-ran-*` files in `.claude/tmp`, and an image of the printed list with its text copy `bash-output-<id>.txt` in `.claude/densepack-vault/images`. Delete them by hand after you close Claude Code.
- `/dense-remove` keeps the Python that winget installed. If no other program needs it, remove it with `winget uninstall --id Python.Python.3.13`.
- `/dense-remove` keeps the right-click tool. [tools/Tool-README.md](tools/Tool-README.md) gives the steps to uninstall it.

<br>

---

<br>

## Save the most

DensePack saves the most in long sessions in which the agent reads many files or long command output, for example an audit of a repository. Short tasks can cost more, because the DensePack session note adds about 569 tokens to the first turn of an Opus 5.5 session and short tasks give DensePack little text to pack.

**Repositories with `CLAUDE.md`**

1. Start Claude Code in a folder next to the repository, not in the repository. In that folder, Claude Code does not load the `CLAUDE.md` of the repository.
2. Run `/bakpack <path to the repository>`.
   - DensePack packs the `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md` and `.claude/rules/*.md` of the repository into images and puts a pointer in the place of each file.
   - Files stay text when their images and pointer cost as much as their text or more, or when they are over 1,000,000 bytes.
   - DensePack keeps the original text next to each file as `<name>.bakpack`.
   - The agent reads none of the text.
3. Close Claude Code and start a new session in the repository. In the new session, Claude Code loads the pointer and the agent reads the images. Claude Code never sends the text.

**Repository audits**

1. Start Claude Code in an empty folder outside the repository.
2. Give the agent the full path of the repository. The agent gets the files that it reads as images when the images cost less than the text. [The size limit](#the-size-limit) lists the files that stay text.

The benches in [BENCHMARKS.md](BENCHMARKS.md) ran the same way. `claude plugin eval` starts each run in an empty folder, and the setup script of each case copies only the code of the task into that folder.

**In each session**

- Read a whole file with the Read tool. Reads with a limit of 20 lines or fewer stay text.
- Search the way you do without DensePack. DensePack packs Bash output of 400 characters or more into images when the images cost less than the text. Output of the Grep tool stays text.
- Before an Edit, Read the lines you will change with a limit of 20 or fewer. The Read returns the lines as exact text, and the Edit copies them from that text.
- When Bash output fills more than one image, the result contains image 1 and a note that names the other images.
- DensePack puts some lines of Bash output beside the image as exact text. These are lines with a `git --stat` bar, a `pip list` rule, a number of 18 or more digits, or a random ID that mixes capital and small letters and contains a capital I or a small l. Lines with only spaces or tabs, and lines with a tab inside the line other than the tab after a line number, also go beside the image as exact text.
- In two tests on Opus 5.5, a Bash `cat` of a file added more tokens than a Read of the same file. The `cat` of a 157-line file added 1,444 tokens against 1,348 for the Read, and the `cat` of a 507-line file added 1,819 tokens against 1,378 for the Read.
- Keep working in the same session. Each later turn sends the smaller images again at the cache read price. The saving increases with the length of the conversation.
- At session start, DensePack converts the `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md` and `.claude/rules/*.md` of the project, your `~/.claude/CLAUDE.md` and the `MEMORY.md` of the project the same way as `/bakpack`. Claude Code still sends their text one time in the session that converts them.
- At session start, DensePack sets `CLAUDE_CODE_THRIFTY_SONIC` to `0` in the `env` block of `~/.claude/settings.json` when the key is not there. With this value, Claude Code stops sending the message that tells Claude to read files with Bash in auto mode and bypassPermissions mode. The change applies from the next session.
- Subagents also get the DensePack session note, except Sonnet subagents after `/max-off`. Haiku subagents get the note, but their Reads, their Bash output and their briefs stay text.
- DensePack packs a subagent report into images only when it calculates that the saving is more than the cost of the extra Read that the lead makes. For a background subagent, that cost also includes the extra turn of the subagent. The lead opens a packed report with the Read tool.

<br>

---

<br>

## Install the right-click tool

The right-click tool uses files from this repository, and you need a copy of them on your computer.

<strong>If you installed the plugin</strong>, the files are in the folder below.

- On Windows, the folder is `%USERPROFILE%\.claude\plugins\marketplaces\densepack-marketplace`.
- On macOS and Linux, the folder is `~/.claude/plugins/marketplaces/densepack-marketplace`.

<strong>If you did not install the plugin</strong>, click the green **Code** button at the top of this page, choose **Download ZIP** and unzip it.

<strong>Open the `tools` folder in it and start the installer.</strong>

| Your computer | What to do | What the tool packs |
| --- | --- | --- |
| Windows | Double-click `install-densepack.bat` | The tool packs files from the right-click menu of File Explorer. It packs selected text with `Ctrl + Shift + D`, `Ctrl + Shift + C` or the `Ctrl + Right-click` menu |
| macOS | Double-click `DensePack it.workflow`. The workflow runs `~/DensePack/tools/densepack.py`. If your copy is in another folder, edit the PACKER line of the workflow | The tool packs files from the Quick Action in Finder |
| Linux | Open a terminal in that folder and run `sh install-densepack.sh` | The tool packs files from the Scripts menu of Nautilus, Nemo or Caja. It packs text, Markdown, CSV, log, JSON and XML files from Open With in Thunar, Dolphin or PCManFM |

The tool packs selected text and uses the hotkeys only on Windows. On all systems, the tool writes the images of a file beside the file as `<file>.densepack-N.png`.

- The Windows and Linux installers install Pillow, freetype-py and NumPy into your own Python with `pip install --user` when they are missing. The Windows installer also installs Python 3.13 and AutoHotkey with winget when they are missing.
- The macOS Quick Action installs nothing and runs `python3` from Homebrew or from your PATH, or `python` if there is no `python3`. That Python must have Pillow, and it needs freetype-py and NumPy to make the same image as the plugin.
- On Linux, the installer writes `~/.local/share/densepack/densepack-file.sh` and `~/.local/share/applications/densepack.desktop`. It also writes a `DensePack it` script in the scripts folder of Nautilus, Nemo and Caja when they are installed. `sh uninstall-densepack.sh` deletes them and keeps Pillow, freetype-py and NumPy.

[tools/Tool-README.md](tools/Tool-README.md) lists the changes that the installers make. It also gives the steps to install without the hotkeys or the reading card and the steps to uninstall.

On Windows, `Ctrl + Shift + D` and the menu item **DensePack it** replace the selected text with its image.

- The tool saves the text and all images of each pack in `tools\ctrl-shift-vault` or `tools\ctrl-right_click-vault`.
- When the `tools` folder is read-only, the tool saves them in the folder of the same name in `%LOCALAPPDATA%\DensePack`.
- The tool shows this information in a window the first time, and a check box in the window stops it from showing again.

<sub>The right-click tool needs this repository on your computer, but it does not need Claude Code or the plugin.</sub>

<br>

---

<br>

## Use the HTML app

Download [index.html](index.html) from this repository and open it in a browser. The app needs no install and makes the images in your browser.

When you paste a file, the app shows the token cost of the text, the token cost of the image and the saving or extra cost of the image in percent.

Then download the image, or copy it and paste it into an AI chat.

| Control | What it changes |
| --- | --- |
| Model | It sets the smallest font size for the model that reads the image. The list names Fable 5 at 8 px, Opus 5 at 10 px and Sonnet 5 at 12 px. The plugin uses 17 px for all models |
| Font size, Font | They set the glyph size and the font. The fonts are Verdana, Tahoma, Trebuchet MS, Arial or Helvetica, and Courier New, and Verdana is the default. The app uses the fonts on your computer |
| Line spacing, Letter spacing | They set the space between the lines and between the letters |
| Image width | Auto picks an image shape close to a square, and 1024, 1536 and 1932 px set the width manually |
| Color coding | It sets the colors of the digits, the symbols and the marks |
| Mark line breaks | Off is the default and changes each line break to a space. On adds a mark at the end of each line |
| Code mode | It adds colored bands and marks for code. Until you set it manually, it is on when the text that you paste or type looks like code and off when it does not |
| Download PNG, Copy image | Download PNG saves the image, and Copy image puts it on the clipboard |
| Complementary Prompt, Copy | Copy copies a short prompt that explains the image to the model |
| Archive current pages | Archive current pages saves the pages in the storage of your browser. Download selected downloads the selected pages, and Delete selected and Delete all remove saved pages |

The HTML app uses its own renderer, which marks the end of each line when Mark line breaks is on. The plugin prints a line number at the start of each line.
