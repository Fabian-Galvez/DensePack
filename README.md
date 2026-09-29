<!-- DensePack 1.3 -->
<p align="left">
  <img src="images/densepack-readme-banner.svg" alt="DensePack" />
</p>

<p align="center">
DensePack packs text into the smallest image that Fable, Opus and Sonnet models can read. The image uses about half the input tokens of the text.<br>
<br>
<strong>On three coding tasks, run with Anthropic's <code>claude plugin eval</code> on Opus 5.5, DensePack saved 31.8% to 38.3% of the price on average, and every run passed its checks.</strong><br>
<br>
Turns are calls to the model that send the entire conversation that has been written to cache at cache read price.
</p>

<p align="center">
<sub>The DensePack plugin and the right-click tool render their images with FreeType and run on Windows, Linux and macOS. The tests ran on Windows and Linux.</sub>
</p>

---

<details>
<summary><strong>Contents</strong></summary>

- [Savings on the whole conversation](#savings-on-the-whole-conversation)
- [The three parts of DensePack](#the-three-parts-of-densepack)
- [Install the plugin](#install-the-plugin)
- [How to save the most](#how-to-save-the-most)
- [What DensePack changes on your computer](#what-densepack-changes-on-your-computer)
- [How it works](#how-it-works)
- [Word files](#word-files)
- [Speed and memory](#speed-and-memory)
- [Limits](#limits)
- [Thank you](#thank-you)
- [Files](#files)
</details>
<br>

---

<br>

## Savings on the whole conversation

<strong>Anthropic's <code>claude plugin eval</code> ran three tasks on Opus 5.5, 5 times with DensePack and 5 times without it. Each run with DensePack saved against its pair and passed every check.</strong><br>

![The mean price of the DensePack runs as a share of the runs without it, for the three benches](images/savings-benchmarks.svg)

| Task | What the agent does | Mean saving |
| --- | --- | --- |
| Code trace | Traces how a Read becomes an image, through about 20,000 lines of code | 32.6% |
| Architecture doc | Writes an architecture doc of 14 hook scripts, about 8,700 lines | 31.8% |
| Five files read whole | Reads five scripts whole, 5,586 lines, and writes a 5-line summary | 38.3% |

Each bench is one short task in a new session. In a longer session, every later turn reads the whole conversation again from the cache, and the images of the files the agent read cost about half the tokens of their text.

<sub>The tasks run on a frozen copy of the DensePack scripts, and the suite ships in <code>plugin/evals/</code>. [BENCHMARKS.md](BENCHMARKS.md#run-the-benches-yourself) has the command that runs it, the price and turns of each run, and the tasks where DensePack does not save.</sub>

### Byte identical rebuild

Opus 5.5 read each file as a DensePack image and wrote the file again from the image. A run passes when the new file is byte for byte identical to the source file. Each file had 100 runs.

| File | Text tokens | Image tokens | Saving | Passes |
| --- | --- | --- | --- | --- |
| Markdown prose, 115 lines | 1,855 | 886 | 52% | 100 of 100 |
| Python script, 116 lines | 1,859 | 834 | 55% | 73 of 100 |
| HTML email template, 25 lines | 2,360 | 1,150 | 51% | 63 of 100 |
| GDScript game code, 222 lines, tabs | 2,790 | 1,430 | 49% | 65 of 100 |

<sub>Most failed runs have a wrong count of spaces or tabs. [BENCHMARKS.md](BENCHMARKS.md#byte-identical-rebuild-25-september-2026) lists the errors.</sub>
<br>

---

<br>

## The three parts of DensePack

The DensePack plugin, the right-click tool and the HTML app each pack text into images. The plugin and the right-click tool use the same renderer. The HTML app has its own renderer with its own color coding and code mode, but it does not have the line numbers, space counts and tab boxes of the plugin, and no bench measured it.

| Part | What it does | Who it is for | Where to start |
| --- | --- | --- | --- |
| **Plugin** | Packs the files that the agent Reads, Bash output, Word files, `CLAUDE.md` and `MEMORY.md`, and the briefs and reports of subagents inside Claude Code with no extra step.<br><br>Two commands install it. | People who use Claude Code | [Install the plugin](#install-the-plugin) |
| **Right-click tool** | Packs a file from your file manager or your shell on Windows, Linux and macOS.<br><br>On Windows only, it also packs selected text with a hotkey or with the Ctrl+Right-click menu in each application.<br><br>The Windows and Linux installers add Pillow, freetype-py and NumPy to your own Python | People who use an AI chat | [INSTALL.md](INSTALL.md#install-the-right-click-tool) and [tools/Tool-README.md](tools/Tool-README.md) |
| **HTML app** | Runs in your browser.<br><br>You paste text, and the image updates while you type.<br>Download or copy the image. | People who want one image without an install | [Use the HTML app](INSTALL.md#use-the-html-app) and [index.html](index.html) |

[tools/Tool-README.md](tools/Tool-README.md) lists the changes that the right-click tool makes, how to install it without the hotkeys and how to remove it.
<br>

---

<br>

## Install the plugin

[INSTALL.md](INSTALL.md) has the steps for Windows, macOS and Linux.

```
/plugin marketplace add Fabian-Galvez/DensePack
/plugin install densepack@densepack-marketplace
```
<br>

DensePack needs Python 3.10 or newer, and an older Python counts as missing. On Windows, the first run installs <strong>Python</strong> with winget when it is missing. On macOS and Linux, the plugin prints the command that installs Python. The plugin then installs <strong>Pillow, freetype-py and NumPy</strong> into its own data folder. On Windows, the hooks run through Git Bash, or through PowerShell when the computer has no Git for Windows. The tests ran on Claude Code 2.1.283 and 2.1.284.

| System | Python | Pillow, freetype-py and NumPy |
| --- | --- | --- |
| Windows | winget installs Python 3.13 for your account. It needs no admin rights | pip puts them in the data folder of the plugin |
| macOS | Nothing. The plugin prints the brew command and the uv command for you to run | pip puts them in the data folder of the plugin |
| Linux | Nothing. The plugin prints the apt, dnf or pacman command for you to run | pip puts them in the data folder of the plugin |

On Windows, the plugin tries the Python install one time. <strong>Restart Claude Code after the Python install.</strong>

To update DensePack:

1. Run `claude plugin marketplace update densepack-marketplace` in a terminal.
2. Run `claude plugin update densepack@densepack-marketplace`.
3. Restart Claude Code.

To remove DensePack, follow [Remove DensePack](INSTALL.md#remove-densepack) in INSTALL.md.
<br>
<br>

| Command | What it does |
| --- | --- |
| `/densepack` | Starts DensePack and sets each setting to its default |
| `/dense-off` | Stops all DensePack hooks in this session only. A new session starts with DensePack on |
| `/maxpack` | Sends images to Sonnet. This is the default |
| `/max-off` | Sends text to Sonnet |
| `/helppack` | Prints all commands |
| `/dense-remove` | Restores the original text of each converted `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md` and `MEMORY.md`. Removes `CLAUDE_CODE_THRIFTY_SONIC` when its value is still `0`. Deletes the trust entry of the marketplace folder in `~/.claude.json` and the DensePack files that `/plugin uninstall` does not delete, except the files that [Remove DensePack](INSTALL.md#remove-densepack) lists as kept. Run it before the uninstall |
| `/mdpack <folder>` | Packs the `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` of that folder into images and puts a pointer in their place, without reading them. Run it from a folder next to that folder. Then open a new session in that folder. The new session reads the images and never the text |
| <strong>Coming soon</strong> | |
| `/dashpack` | Shows the saving of each conversation while it runs. It calculates the text price of each image that the agents read and of each later turn that reads the image again |

<br>
<br>

---

<br>

## How to save the most

DensePack saves the most in a long conversation that reads many files, for example an audit of a repository.

- Read files with the Read tool. DensePack also packs Bash output of 400 characters or more, but a Bash read saves less.
- Keep working in the same session. Each later turn reads the smaller images again.
- Open Claude Code in an empty folder next to the repository. Then give the agent the full path of the repository.
  - DensePack sends the names of the files directly in that folder with your prompt. It also packs those files in the background when they hold 700,000 bytes or fewer in total.
  - DensePack does neither for a folder with more than 200 files.
  - DensePack sends each file that the agent reads with the Read tool as images when the images cost less than the text, except in the cases that [Limits](#limits) lists.

[INSTALL.md](INSTALL.md#how-to-save-the-most) has the numbered steps for a repository with a `CLAUDE.md`, for an audit and for each session.
<br>
<br>

---

<br>

## What DensePack changes on your computer

DensePack changes some of your files and adds its own folders and packages. `/dense-remove` undoes the changes to your files and deletes the DensePack folders of each project that a transcript in `~/.claude/projects` names, except `.claude/tmp/` and the files that [Remove DensePack](INSTALL.md#remove-densepack) lists as kept. `/plugin uninstall` deletes the packages.

| What it changes | What DensePack does |
| --- | --- |
| `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` in a project, your `~/.claude/CLAUDE.md` and the `MEMORY.md` of the project | Copies each one to `<name>.densepack.bak`, packs the text into images and puts a short pointer in the file. A file stays text unless its images and pointer cost less than its text |
| `~/.claude/settings.json` | Adds `"CLAUDE_CODE_THRIFTY_SONIC": "0"` one time, when the key is not there. From the next session, Claude Code auto mode stops telling the agent to read files with Bash. A note on screen says so |
| A `.gitignore` in `.claude/tmp/` and `.claude/densepack-vault/` | Writes one line, `*`. Git does not commit those folders |
| `.claude/tmp/` and `.claude/densepack-vault/` in each project | Creates them. `.claude/tmp/` holds the settings and the working files. The vault holds the images, their text copies and one folder for each conversation. Session start deletes working files and images older than 24 hours. DensePack deletes the oldest conversation folders when those folders pass 200 MB, the default |
| `~/.claude/densepack-state` | Creates it. It holds the path of the Python that DensePack found, the key that seals the image records, the list of converted instruction files and the images of your `~/.claude/CLAUDE.md` and `MEMORY.md` |
| Pillow, freetype-py and NumPy | Installs them into the data folder of the plugin. DensePack does not change your own Python |

[HOW-IT-WORKS.md](HOW-IT-WORKS.md#what-densepack-changes) has the full table and the rules to read, edit and share a converted file. [PLUGIN-FOLDERS-FILES.md](PLUGIN-FOLDERS-FILES.md) lists each folder and working file.
<br>
<br>

---

<br>

## How it works

DensePack has four parts.

| Part | What happens |
| --- | --- |
| The swap | The agent calls Read, and the Read runs on the real file. Then a hook packs the file into an image and puts the image in the result in place of the text. The model receives the image.<br><br>Bash output of 400 characters or more takes the same route. A Bash result holds one image. When the output needs more than one image, the result holds the first image and a note names the others. Lines that a model can misread, such as a random ID that mixes capital and small letters and holds a capital I or a small l, go beside the image as exact text. Each packed output keeps its exact text in `.claude/densepack-vault/images/` |
| The packing | DensePack packs files, Bash output, briefs for subagents and reports from subagents, but only when the plugin calculates that the images will save compared to the text.<br><br>Briefs are only packed when they have 1,000 characters or more.<br><br>Agents still write their briefs and reports as text, and DensePack swaps that text for images that the receiving agent opens with one Read. [HOW-IT-WORKS.md](HOW-IT-WORKS.md#how-subagents-send-and-receive-images) explains each step |
| The image | One function, `pack_code()`, packs the text into each image. In the image, a green number starts each line, a red number gives a count of spaces and a `\t` box gives a count of tabs. In a file with tab indents, the band color shows the tab count |
| Exact lines | When an Edit that the agent copied from an image fails, a Read of 20 lines or fewer gives the exact lines as text, and the agent sends the Edit again |

- DensePack sends images to Fable, Opus and Sonnet models, such as Fable 5.1, Opus 5.5 and Sonnet 5.5. Each model gets the same image, with 17 px characters. Sonnet gets images while `/maxpack` is on, the default. Haiku and each other model get text.
- The lead gets a note at session start that says how to read the images, and a SubagentStart hook sends the same note to each subagent. Haiku leads get no note, and Sonnet leads and subagents get none after `/max-off`. Haiku subagents get the note, but their files stay text. The lead alone also gets one line that tells it to write the task of a subagent the same way as without DensePack.
- DensePack stops a Grep that prints each line of a file as text when a Read of that file gives images. Each other Grep passes. DensePack also stops a Bash read, such as `cat`, of the text file of a packed report or brief.

[HOW-IT-WORKS.md](HOW-IT-WORKS.md) explains the four parts, the seven slash commands, the hooks and each script.
<br>
<br>

---

<br>

## Word files

DensePack packs a `.doc` or `.docx` into images before the agent reads it, because the Read tool of Claude Code cannot open a Word file. A Word file gets no images when its text is under 1,000 bytes or over 500,000 bytes, or when the images cost more than the text. The agent can then read its text with a shell command.

DensePack also writes the text of each Word file beside its images. The text copy holds the exact text that the images show, one line for each paragraph, list item and table row. The key row of each image shows the name of the text copy after `file=`.

- A Word file that your prompt names, or that a Glob, a Grep or a Bash listing shows, gets a text copy in `.claude/densepack-vault/images/`, named after its working copy in `.claude/tmp`, for example `.claude-tmp-densepack_word_8d36c710126a.docx.txt` beside `.claude-tmp-densepack_word_8d36c710126a.docx.txt-image-1-of-3-DensePack.png`.
- A Word file that you copy into `.claude/densepack-vault/to-pack/` keeps its own name, for example `report.docx.txt` beside `report.docx.txt-image-1-of-3-DensePack.png` in `to-pack/packed/`.

A `.docx` is a zip of XML, and a `.doc` is an OLE2 container. DensePack reads the two formats with the Python standard library and does not need Word.

The Edit and Write tools of Claude Code do not work on a Word file. Change a Word file with a shell command. To change a `.docx`, unzip it, edit `word/document.xml` and zip it again.

[HOW-IT-WORKS.md](HOW-IT-WORKS.md#word-files) has the format table, the three ways that DensePack packs a Word file automatically and the three steps that keep the scan fast.
<br>
<br>

---

<br>

## Speed and memory

| Text size | Old renderer | New renderer |
| --- | --- | --- |
| 11 KB | 3.2 s, 528 MB, 16 processes | 0.9 s, 55 MB, 1 process |
| 21 KB | 5.4 s, 630 MB, 15 processes | 1.8 s, 76 MB, 1 process |
| 228 KB | 29.6 s, 3.3 GB, 16 processes | 8.2 s, 243 MB, 1 process |

The background pack of a named folder starts one process for each file, up to the number of CPU cores, and each file of 60,000 bytes or more also starts its own render processes. In one test, the first Bash call took 9.4 s while the background pack ran, against 2.7 s without DensePack.
<br>

---

<br>

## Limits

- DensePack sends Haiku text only, because in a test Haiku 4.5 scored 1 of 10 on a packed report and gave wrong numbers with no warning.
- DensePack packs a `.doc` or `.docx` in four cases. See [Word files](#word-files).
  - Your prompt names the file.
  - Your prompt names the folder of the file by its full path. DensePack then packs up to 8 Word files of that folder before your message goes to the model.
  - The agent finds the file with Glob, Grep or a Bash listing.
  - You copy the file into `.claude/densepack-vault/to-pack/`.
- When a Word file gets no images, the agent can still read its text with a shell command.
- Short tasks can cost more with DensePack, because the session note and the extra steps of some runs cost more than the images save. In the task that copies 6 lines of a Python file on Opus 5.5, each run with DensePack cost $0.0915 to $0.1082, and each run without it cost $0.0827 to $0.0839. [BENCHMARKS.md](BENCHMARKS.md#why-some-short-tasks-cost-more-with-densepack) gives the price of each run and each cause.
- Edit and Write work on a file that arrived as an image. They do not work on a Word file because Claude Code does not Read a Word file. See [Word files](#word-files).<br>
  <sub>DensePack tells this to each agent that gets images, to the lead at session start and to each subagent when it starts.</sub>
- On Opus 5.5, DensePack adds about 569 tokens to the first turn of a session. They are the session start note and the command list. Each later turn reads them again at the cache read price. The other hooks add nothing to a message that has no pasted image and names no folder and no Word file.<br>
  <sub>The count comes from two `claude -p` sessions with no tool call, one with DensePack off and one with it on.</sub>
- No bench measured the cost of the session start note in a subagent.
- After a conversation that packed a report or a brief, the next session gets a summary at session start. With the default receipts setting, the summary is one line that names the file of the totals.
- Files under 1,000 bytes, files over 500,000 bytes and files with a null byte stay text.
- Reads with a limit of 20 lines or fewer stay text. Longer Reads of part of a file get images of those lines only, or text when the text costs less. When those lines need more than one image, the Read returns the first image and a note that names the others.
- When one Sonnet turn reads more than 32 files, or more than 700,000 bytes of files, most Reads of that turn get text. Opus and Fable have no such limit.
- Files stay text when the font has no glyph for more than 2% of their characters that are not spaces, such as files in Chinese, Japanese or Korean and files of box-drawing characters.
- On Windows without Git for Windows, the hooks run through a PowerShell script. Claude Code then runs commands in PowerShell, and DensePack packs no command output, because it packs only Bash output.<br>
  <sub>A company policy that blocks PowerShell scripts stops DensePack on that computer.</sub>
- The benches measure the renderer of the plugin, which the right-click tool also uses. The HTML app uses its own renderer.
- When one Sonnet turn gets many images, the reply can hold thousands of output tokens. More output lowers the saving because Anthropic bills output at 5x the input price.
- Sonnet 5.5 and Opus 5.5 each copied one Python file of 116 lines from its image 10 times at medium effort. Sonnet 5.5 wrote each word right, with code that runs the same, in 8 copies, and Opus 5.5 did this in all 10. Run `/max-off` for work that must copy text exactly. [BENCHMARKS.md](BENCHMARKS.md#byte-identical-rebuild-on-sonnet-55-and-opus-55-28-september-2026) has the results.
<br>

---

<br>

## Thank you

The DensePack plugin renders each character with [FreeType](https://freetype.org) and the [Inter](https://rsms.me/inter/) font family. They gave DensePack a good font from the first day. Thank you both.

A font made for AI models to read is a later project.
<br>

---

<br>

## Files

| File | What it covers |
| --- | --- |
| [README.md](README.md) | What DensePack is, what it saves and how to install the plugin |
| [HOW-IT-WORKS.md](HOW-IT-WORKS.md) | The swap, the packing, the image, the Edit check, Word files, the commands, the hooks and the scripts |
| [INSTALL.md](INSTALL.md) | Each install step for Windows, macOS and Linux, the right-click tool, the HTML app and the removal |
| [BENCHMARKS.md](BENCHMARKS.md) | Each bench, the prices and how Anthropic bills |
| [PLUGIN-FOLDERS-FILES.md](PLUGIN-FOLDERS-FILES.md) | Each folder and working file that the plugin writes and what each one is for |
| [tools/Tool-README.md](tools/Tool-README.md) | The right-click tool, its install, its use and the files it puts on your computer |
| [PRIVACY-POLICY.md](PRIVACY-POLICY.md) | DensePack sends no data to an external service and uses the network only to install what it needs |
| [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) | The font and the libraries that this project uses, with their licenses |
| [LICENSE](LICENSE) | MIT |
