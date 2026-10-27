# DensePack changes

<br>

---

<br>

## 2.0.5

| Change | Before | Now |
| --- | --- | --- |
| Python on macOS | With no Python 3.10 or newer, DensePack showed the Homebrew and uv commands, and you ran them yourself. New Macs have no such Python, because `/usr/bin/python3` is 3.9 or a stub. | DensePack downloads uv in the background. uv downloads and installs Python 3.13 into the plugin's data folder, the same as winget on Windows. It needs no password and changes no PATH. It also downloads and installs Pillow, freetype-py and NumPy, and hooks wait for the install, so the first session packs. On an Intel Mac mini, the install took 8 to 39 seconds in tests, and the five-files-read bench saved 48.4% in its first session. |
| `~/.local/bin` | The Claude desktop app and an unchanged `~/.zshrc` start hooks with a PATH that lacks `~/.local/bin`. DensePack then did not find the Python of `uv python install --default`. | DensePack looks in `~/.local/bin` after PATH and the Homebrew folders. |
| macOS install steps | INSTALL.md named the Git step for Windows only. On a new Mac, `/plugin marketplace add` failed with "git is not installed on this Mac". | INSTALL.md and README.md name `xcode-select --install` before the plugin install. |
| Cowork | INSTALL.md had no Cowork steps. | INSTALL.md and README.md show how to add the plugin in Cowork. Cowork uses the short command names, such as `/helppack`. Claude Code needs `densepack:` before every command, such as `/densepack:helppack`, and the docs now say so on each page that shows a command. |
| Right-click tool on macOS | The Quick Action ran only `~/DensePack/tools/densepack.py` and the first `python3` on PATH. On a new Mac that was macOS's Python 3.9 or its install stub. | The Quick Action also finds the plugin's download, and it uses the plugin's Python and packages when they are there. It skips a Python older than 3.10. Tool-README.md and INSTALL.md name the Quick Actions menu and the steps to remove the tool. |
| Word files in tool results | Word paths in a Bash, Glob or Grep result packed only when a subagent report was also waiting. The scan also missed relative paths such as `docs/memo.docx`. | The scan runs when a tool result names a .doc or .docx file, and relative paths without spaces pack too. |
| Subagents with `CLAUDE_CONFIG_DIR` | DensePack looked for subagent transcripts only in `~/.claude/projects`. With `CLAUDE_CONFIG_DIR` set, it could not name the subagent's model, so subagents got text. In a test, the session cost $0.291 instead of $0.196. | DensePack looks in the folder that `CLAUDE_CONFIG_DIR` names, and subagents get images. The same test cost $0.201. |
| Upgrade from 2.0.4 on macOS | On a Mac with no Python, 2.0.4 left a `python-install-tried` file after it showed the install commands. | That file no longer stops the uv install, so the Mac gets Python after the upgrade. |
| Commands in Cowork | Cowork runs the commands with `CLAUDE_PLUGIN_ROOT` empty, so the commands could not find their scripts. | The commands find the plugin folder when `CLAUDE_PLUGIN_ROOT` is empty. |
| Plugin folder | The `plugin` folder had no README or LICENSE. The Claude Directory needs both there. | The `plugin` folder has a README and a LICENSE. The README names what DensePack downloads and installs. The docs now say "downloads and installs" for Python, uv, Git for Windows and the packages. |
| Benches on macOS | `bench/direct_pair.py` copied `~/.claude/.credentials.json`, which macOS does not have, because Claude Code keeps the login in the Keychain. | The bench uses `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` when that file is missing. BENCHMARKS.md has the steps. |

Tests of 2.0.5 on 26 October 2026:

- The Mac was an Intel Mac mini with macOS 14.8.9 and no Python 3.10 or newer. Its first Claude Code session downloaded and installed Python 3.13 with uv in 39 seconds and returned images. `/densepack:densedoctor` and the 23 unit tests passed there. Word files found with Glob and subagent Reads returned images.
- In Cowork on Anthropic's cloud Linux, Reads, Bash output and subagents with and without a named model returned images. Word files found with Glob, `find` and `ls` packed. The Edit check and `/densedoctor` worked, and Grep results stayed text.
- In Claude Code on Linux, a new install from a local marketplace returned images for Reads, Word files and subagents, also with `CLAUDE_CONFIG_DIR` set.

## 2.0.4

| Change | Before | Now |
| --- | --- | --- |
| Look-alike characters | Sonnet sometimes read Cyrillic letters as their Latin twins in an image, so Cyrillic A became Latin A. | Whole-file Reads with Cyrillic letters still become images, and the lines with Cyrillic letters go next to the images as exact text. DensePack also checks for Greek letters, Unicode spaces, the minus sign and rare dashes. They have the same shapes as ASCII characters. Files that are mostly Cyrillic stay text. Bash output, Reads of some lines, subagent tasks and reports with these characters stay text. The reason goes in `why-text.log`. The `exacttext` setting is `lines` by default. `on` keeps all such Reads as text, `off` turns the check off, and `strict` also keeps en and em dashes as text. This comes from pull request [#5](https://github.com/Fabian-Galvez/DensePack/pull/5) by [@deny-atk](https://github.com/deny-atk). |
| Long Markdown tables | Sonnet skipped some rows of 120-row Markdown tables in images. | Reads of files with a Markdown table of 10 or more rows stay text. |

## 2.0.3

| Change | Before | Now |
| --- | --- | --- |
| Long file names in the key row | File names too long for the first row of the key were drawn over its last entries, such as "=same line". | Such names get a row of their own, because the name ties each page to its file and Bash pages to their text copy. The name and the line count keep a gap before them, the same as between entries. This comes from issue [#3](https://github.com/Fabian-Galvez/DensePack/issues/3) by [@wdadadsdsa](https://github.com/wdadadsdsa). |
| Cyrillic and Greek look-alikes in searches | Sonnet read Cyrillic letters as their Latin twins in an image. Its search for ЕР-0042 looked for EP-0042 and found nothing. | DensePack saves these words when it draws Read and Bash text. Searches for the Latin spelling, with Grep or with grep, rg or Select-String in Bash, then match both spellings, such as `[EЕ][PР]-0042`. In tests, Sonnet 5.5 and Opus 5.5 found the entry with their first search in 4 of 4 runs. In auto and bypass modes the search changes before it runs, and other modes get one denial that gives the right pattern. This comes from issue [#4](https://github.com/Fabian-Galvez/DensePack/issues/4) by [@deny-atk](https://github.com/deny-atk). |
| Files you keep as text | Only files with characters the font cannot draw, such as Chinese text, stayed text. | List files in `~/.claude/densepack-text-files.txt`, one pattern per line, such as `*.kt`. Reads of matching files stay text in every project. This comes from issue [#3](https://github.com/Fabian-Galvez/DensePack/issues/3) by [@wdadadsdsa](https://github.com/wdadadsdsa). |
| Rejected Edits on Claude Code 2.1.300 | Claude Code 2.1.300 rejects an Edit whose old text is not in the file before any hook runs, so DensePack could not send the exact lines. | DensePack sends the exact lines right after the failed Edit. In a test with a Cyrillic line, Sonnet 5.5 needed 4 requests instead of 5. |

## 2.0.2

| Change | Before | Now |
| --- | --- | --- |
| Rules in long sessions | Claude followed the rules of the session start note less as the session grew, because they sit far back. | One line of about 15 tokens before each model call points Claude back to those rules. It adds no API request. |
| Writing rules | Replies often used "Label: text" lines, lists for most answers and a closing note. | Under the new rules, replies give the answer first and then stop. They use a colon only before a list, and lists only for steps or 3 to 5 items. The rule to fix a sentence by rewriting it has no step to read the paragraph again. With that step, Opus 5.5 used a median of 1,239 thinking tokens on Ponytail's `open-mandelbrot` task, against 269 with the rules before it. |
| Instruction files | At each session start, DensePack converted `CLAUDE.md`, `AGENTS.md`, `.claude/rules/*.md`, your personal `~/.claude/CLAUDE.md` and the memory index into images on its own. | DensePack converts these files only when you run `/bakpack`. `/bakpack` with no folder converts this project and its memory index, and `/bakpack ~/.claude` converts your personal `CLAUDE.md`. Files that an older version converted stay images, and `/bak-off` turns them back into text. |
| Why output stayed text | Reads and Bash outputs that stayed text because of an error or a missing library showed no reason. 2.0.1 sent Read errors to stderr only. | DensePack writes the reason to `.claude/densepack-vault/why-text.log` in the project. The log names the cause at the first Read, such as the Python 3.12 error of issue [#1](https://github.com/Fabian-Galvez/DensePack/issues/1) by [@wdadadsdsa](https://github.com/wdadadsdsa). |
| `/densedoctor` | Checking an install took several manual steps. | `/densedoctor` checks Python, Git Bash on Windows, Pillow, FreeType, NumPy and the font, draws one test image and prints the last lines of the log. |
| `/densetext` | Bash output from 400 characters, JSON output and short files became images. | `/densetext` keeps more as text, folds repeated output, and puts more IDs beside images as exact text. It is off by default, because it saves less, and `/densepack` turns it off. These ideas come from issue [#2](https://github.com/Fabian-Galvez/DensePack/issues/2) by [@wdadadsdsa](https://github.com/wdadadsdsa). |
| Python install on Windows | The winget install ran inside the session start hook. On a slow connection, the 10-minute hook limit could cut it, and DensePack never tried again. | The install runs in a background process, and DensePack marks it as tried only when it ends. It leaves out Tcl/Tk and the Python test suite, which DensePack does not use. In Windows Sandbox, the Tcl/Tk step alone took over 10 minutes. |
| Tests | None | `tests/test_densepack.py` checks it and the parts of `/densetext`. Run it with `python -m unittest discover tests`. |
| Small project maps | The start note named an image of the project map, so the agent spent a Read on it, also for a map of 1 line. | When the map has under 400 characters, the same floor as Bash output, the start note contains it as text. On Ponytail's `scope-rename` task, the map has 226 characters. |
| Ponytail's benchmark | The table had 5 runs of each task with DensePack 2.0, with a 12.4% saving against Ponytail 5. | DensePack 2.0.2 ran all 39 tasks 10 times in a row on 13 October, and all 390 runs count. All 390 passed Ponytail's own checks, and DensePack cost 11.0% less than Ponytail 5. [BENCHMARKS.md](https://github.com/Fabian-Galvez/DensePack/blob/f2529e5/BENCHMARKS.md#ponytails-benchmark) has the price and check result of each run. |
| Install on Windows without Git | On Windows PCs without Git, installing the plugin failed with "Command 'git' not found", because Claude Code needs Git to download plugins. | INSTALL.md has 2 PowerShell commands for Windows without Git. The first installs Git with winget, and the second installs the plugin. |

<br>

---

<br>

## 2.0.1

| Change | Before | Now |
| --- | --- | --- |
| Windows with Python 3.12 | Reads stayed text, with no error. DensePack set `platform._wmi` to None, and on Python 3.12 that made `platform.system()` raise AttributeError, so the freetype import failed. This was in each release since 1.1. | Reads get images. DensePack replaces `platform._wmi_query` with a stub that raises OSError, which skips the slow WMI query on Python 3.12, 3.13 and 3.14. |
| Claude Code worktrees | Reads in `.claude/worktrees/<name>/` stayed text, because DensePack skipped each path with a `.claude` part. | Reads in worktrees get images. Other `.claude` folders still stay text. |
| Failed Read packs | The Read stayed text and no error showed. | The Read still stays text, and the error goes to stderr. |
| Saved Python path on Windows | When 2 sessions started at once, a temp file such as `python-path.1234` could stay in `~/.claude/densepack-state`. | DensePack deletes its temp file when the move fails. |

The first 2 changes fix issue [#1](https://github.com/Fabian-Galvez/DensePack/issues/1) by [@wdadadsdsa](https://github.com/wdadadsdsa).

<br>

---

<br>

## 2.0

### Rules and the project map

DensePack 2.0 also cuts what the agent writes.

- The start note now contains the rules in [plugin/rules/STYLE-RULES.md](plugin/rules/STYLE-RULES.md): the smallest complete code change, few turns, and short, plain replies. Subagents get the same rules.
- The rules keep private data private. No change may show private data to more people than before, such as one user's email address to other users.
- The start note also names an image of the project map: each folder, its files and the names that each file defines. The agent reads that image in its first turn.
- The start note is about 2,300 tokens, up from 72. [BENCHMARKS.md](BENCHMARKS.md#densepack-202-13-october-2026) has the savings.

### If you used /mdpack

`/mdpack` was renamed `/bakpack` in 1.3.4, and 2.0 removes the old name. `/bak-off` puts the original files back. It was named `/bakoff` in 1.3.4.

In 1.3.3, `/mdpack` only packed `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md`. `/bakpack` also packs `AGENTS.md` and `.claude/rules/*.md`, which `/mdpack` left as text.

Your packed folders and files still work.

Follow these 2 steps to update the folders that `/mdpack` was used on:

1. Run `/bak-off <folder>`. This puts your original files back.
2. Run `/bakpack <folder>`. This packs the folder again, with `AGENTS.md` and `.claude/rules/*.md`.

### Changes

| Change                          | Before                                                                                                | Now                                                                                                                                                                                                                          |
| ------------------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Whole-file Reads of long files  | The Read returned the first image and a note. The agent then Read each other image.                   | The Read returns the images of the file in one result, up to line 2,000 like a text Read. In 5 Opus 5.5 runs of the read-in-full architecture bench, the saving was 51.7%.                                                    |
| PowerShell output               | PowerShell output stayed text.                                                                        | DensePack packs PowerShell output too. PowerShell results contain only one image, so longer output returns image 1 and a note that names the others. Error text goes in the note.                                            |
| Sonnet with many files          | DensePack sent text to Sonnet for a turn of more than 32 files or more than 700,000 bytes.            | DensePack sends images to Sonnet for each Read, whatever the number of files in the turn.                                                                                                                                    |
| Large pages                     | DensePack saved each page in full color first. It then cut a page over 250,000 bytes to fewer colors. | DensePack saves a page over 1,041,666 pixels in 256 colors at once. In a test of 195 pages, each page that large was over the 250,000-byte cap in full color. This skips a full-color save of about 0.4 seconds.             |
| Small files                     | Files under 1,000 bytes stayed text.                                                                  | Only empty files stay text. DensePack sends other files as images when the images cost fewer tokens than the text.                                                                                                           |
| Session start note              | The note listed the image marks and rules for Reads and Edits.                                        | The note is "DensePack is on.", one line about subagents, the rules and the name of the project map image, about 2,300 tokens. With the old list of marks and rules, Sonnet 5.5 planned to Read each file whole in 5 of 14 architecture-doc runs. |
| Guidance beside the first image | About 80 tokens, with a rule that a Read of 20 lines or fewer returns text.                           | About 25 tokens. Files and command output arrive as images. The images have a legend. With the rule, Opus 5.5 made 9 small Reads to get text. The run without DensePack read the same parts with a few Bash loops.           |
| Folders that your prompt names  | The agent got a list of the files in the folder.                                                      | DensePack packs the files in the background and sends no list. With the list, Sonnet 5.5 skipped its usual size check and Read all 14 scripts whole. Its runs cost $0.516 on average, and runs without the list cost $0.279. |
| Grep                            | DensePack denied a Grep with the pattern `^` and more than 20 lines.                                  | DensePack denies no Grep. Agents read the first lines of a file with that Grep. Denying a Grep cost one more API request for a Read.                                                                                         |
| Long Bash output                | The result contained image 1. Its note named the other images. The agent then Read them.              | All images of the output go in the same result. The agent gets the whole output in one API request, the same as with text. PowerShell results contain only image 1 and a note that names the others.                         |
| Reads of a line range           | The Read returned the first image of the range and a note.                                            | The Read returns all images of the range in one result, the same as the text of the range.                                                                                                                                   |
| Search and shell on Windows     | Grep, Glob and PowerShell gave the agent results that DensePack cannot pack in full.                  | On Windows with Git for Windows, DensePack sets `EMBEDDED_SEARCH_TOOLS` to `1` and `CLAUDE_CODE_USE_POWERSHELL_TOOL` to `0` in `~/.claude/settings.json`. Search and commands then run in Bash, where DensePack packs all of it. |
| Failed packs                    | DensePack denied the Read and asked the agent to copy the file into `to-pack/`.                       | The Read returns the text, the same as without DensePack.                                                                                                                                                                    |
| `/mdpack`                       | It was the old name of `/bakpack`.                                                                    | It is gone. See [If you used /mdpack](#if-you-used-mdpack).                                                                                                                                                                  |

<br>

---

<br>

## 1.3.4

| Change                     | Before                                                                                                  | Now                                                                                                                                                                 |
| -------------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Permission prompts         | In manual mode, a Word file outside the project reached the agent as images with no prompt.             | In manual mode, DensePack packs a file only when the agent can read it with no prompt.                                                                              |
| Tool calls before they run | Hooks changed some tool calls before they ran.                                                          | Hooks change a call only in auto and bypassPermissions mode, and never when an `ask` rule names the tool. See [Permission modes](HOW-IT-WORKS.md#permission-modes). |
| Packed report text         | In auto mode, a `cat` of packed report text became an `echo`. The agent did not act on it.              | DensePack blocks the command in all modes. The agent then reads the image.                                                                                          |
| Report images              | DensePack joined the report images that wait for a Read into one image. Two packed reports did not fit. | The main agent gets each report as its own image.                                                                                                                   |
| Unknown model              | Sessions with an unknown model got images.                                                              | It gets text. DensePack reads the model at the first tool call and after a `/model` change.                                                                         |
| `/bakpack` limit           | 250,000 characters or 6,000 lines.                                                                      | 1,000,000 bytes, the same as a file Read.                                                                                                                           |
| Command names              | `/mdpack` with backups named `.densepack.bak`.                                                          | `/bakpack` and `/bakoff` (now `/bak-off`) with backups named `.bakpack`. `/mdpack` and old backups still work.                                                                       |
| Instruction files          | `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md`.                                                 | Also `AGENTS.md` and `.claude/rules/*.md`, with a list that you can change.                                                                                         |
| Session start              | The session waited for the pack of `CLAUDE.md`.                                                         | The pack runs in the background. The next session uses the images.                                                                                                  |
| Folders named "scratch"    | Files in a folder with "scratch" or "sandbox" in its name stayed text.                                  | Only `.claude` and the scratchpad folder of Claude Code stay text.                                                                                                  |

- DensePack 1.3.3 and 1.3.4 send no data off your computer. Claude Code checks `deny` rules before the hooks run.
