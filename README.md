<!-- DensePack 1.1 -->
<p align="left">
  <img src="images/densepack-readme-banner.svg" alt="DensePack" />
</p>

<p align="center">
DensePack packs raw text into the smallest possible image that an AI model can read accurately. Packed images average 50% fewer input tokens than their raw text counterpart.<br>
<br>
<br>
Each later turn re-reads the files as cheaper images. A longer session saves more.<br>
DensePack works best for conversations that read many files, such as auditing a repository by reading its files as images.<br>
<strong>DensePack's floor is 22.0% to 27.5% total conversation savings on a single file. That counts the entire conversation, not only input tokens.</strong>
</p>


<p align="center">
  <sub>DensePack draws with FreeType. It runs on Windows, Linux and macOS. Tested on Windows and Linux.</sub>
</p>

---
> <details>
> <summary><strong>Table of Contents</strong></summary>
>
> - [Benchmarks - Total conversation savings](#benchmarks---total-conversation-savings)
> - [DensePack's three parts](#densepacks-three-parts)
> - [Install the plugin](#install-the-plugin)
> - [Work for the most savings](#work-for-the-most-savings)
> - [What DensePack changes on your machine](#what-densepack-changes-on-your-machine)
> - [How it works](#how-it-works)
> - [Word files](#word-files)
> - [The right-click tool and the HTML app](#the-right-click-tool-and-the-html-app)
> - [Limits](#limits)
> - [Thank you](#thank-you)
> - [Files](#files)
> </details>
<br>

---

<br>

## Benchmarks - Total conversation savings

> These are the total conversation savings for the single-file, 16-file and 32-file bench On/Off pairs.
> <strong>On the 32-file bench, DensePack cuts the cost of the entire conversation by 70.4% to 73.3%.</strong>
> <sub>That bench is a small task. 32 files read in 4 turns is about $2.82 on Opus 5 with DensePack off.</sub><br><br>
> Fable 5.1, Opus 5 and Sonnet 5 were each benched with the DensePack plugin On against a baseline text arm with the DensePack plugin Off. 
> 
> All arms run isolated. Each arm gets the same task, to read files and answer questions about them. The only difference is that the On arm reads DensePack images instead of the raw text.

![Savings for three readers on three benches, against the text arm](images/savings-by-reader.svg)
<br>


| Model | 32-file bench | 16-file bench | Score | Runs |  | Single-file bench | Score | Runs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| <strong>Fable 5.1</strong> | 71.1% | 65.2% | 5 of 5 | 3 pairs |  | 22.0% | 5 of 5 | 100 |
| <strong>Opus 5</strong> | 73.3% | 65.2% | 5 of 5 | 3 pairs |  | 27.5% | 5 of 5 | 100 |
| <strong>Sonnet 5</strong> | 70.4% | 31.5% | 5 of 5 | 3 pairs |  | 27.4% | 5 of 5 | 100 |

<sub>[BENCHMARKS.md](BENCHMARKS.md) contains each pair, the price of each one, how
Anthropic bills and six numbered steps to recreate these benches on your own
machine.</sub>
<br>

---

<br>

## DensePack's three parts

The DensePack plugin, the right-click tool and the HTML app all pack images.
<br>
The HTML app still uses its original renderer. The original renderer packs plain text into legible images but does not have the color coding that makes a code file readable.
<br>

| Part | What it does | Who it is for | Where to start |
| --- | --- | --- | --- |
| **Plugin** | Automatic packing inside Claude Code. <br><br>Two commands to install.<br>Simple commands to run the benches. | Anyone using Claude Code | [Install the plugin](#install-the-plugin) |
| **Right-click tool** | Pack highlighted text or a file from your shell or file manager | Anyone using an AI chat | [tools/Tool-README.md](tools/Tool-README.md) |
| **HTML app** | Runs in your browser. <br><br>Paste text in and the image renders live.<br>Download or Copy to take with you.<br><br><br><br> | Anyone who wants one image prompt without an install. | [Use the HTML app](INSTALL.md#use-the-html-app) |

<br> 
<br>

---

<br>

## Install the plugin

<a href="INSTALL.md">INSTALL.md</a> has all the steps for Windows, macOS and Linux.<br>


```
/plugin marketplace add Fabian-Galvez/DensePack
/plugin install densepack@densepack-marketplace
```

<br>
<br>

On Windows the first run installs <strong>Python</strong> with winget if it is missing. On macOS and Linux the plugin prints the command that installs Python. The plugin then installs <strong>Pillow, freetype-py and NumPy</strong> into its own data folder.
<br>
On Windows the hooks run through Git Bash, or through PowerShell when the computer has no Git for Windows.
<br>

| System | Python | Pillow, freetype-py and NumPy |
| --- | --- | --- |
| Windows | winget installs Python 3.13 for your user, with no admin rights | pip puts them in the plugin's data folder |
| macOS | Nothing. The plugin prints the brew command for you to run | pip puts them in the plugin's data folder |
| Linux | Nothing. The plugin prints the sudo command for you to run | pip puts them in the plugin's data folder |
<br>

- The plugin runs the Python install once per machine. <strong>Restart Claude Code after Python installs.</strong> 
- Update from a terminal with `claude plugin marketplace update densepack-marketplace`, then `claude plugin update densepack@densepack-marketplace`. 
- Restart Claude Code after.
<br>
Uninstall with `/plugin uninstall densepack`.
The install also keeps a copy of this repository. `/plugin marketplace remove densepack-marketplace` deletes that copy.
<br>
<br>

| Command | Function |
| --- | --- |
| `/densepack` | Turns DensePack on and puts all settings back to DensePack's default |
| `/dense-off` | Stops all DensePack hooks for this session only. A new session starts with DensePack on |
| `/maxpack` | Sends Sonnet images. This is the default |
| `/max-off` | Sends Sonnet text |
| `/helppack` | Prints all commands |
| `/dense-remove` | Puts each converted `CLAUDE.md`, `CLAUDE.local.md` and `MEMORY.md` back to its original text, removes `CLAUDE_CODE_THRIFTY_SONIC` and deletes all DensePack files that `/plugin uninstall` leaves behind. Run it before the uninstall |
| `/mdpack <folder>` | Converts that folder's `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` into images behind a pointer, without reading them. Run it from a folder next to that folder, then open a new session inside it. That session reads the images and never the text |
| <strong>Coming soon</strong> |  |
| /agentpack | Spawns subagents and gives them work. The main agent sends online research to a subagent. The subagent sends back a summary report with cited sources as a packed image. The main agent's context window stays small. The first benches measure another 15% saving on delegated tasks, above DensePack's default floor. |
| /dashpack | Shows the live saving for each conversation. It calculates the text cost of the images that the agents read and adds the cost of each later turn that reads them again. |

<br> 
<br>

---

<br>

## Work for the most savings

DensePack saves the most in a long conversation that reads many files, such as
an audit of a repository.

- Read files with the Read tool. DensePack packs a Bash read too. A Bash
  read takes an extra turn.
- Keep working in the same session. Each later turn reads the images again at
  the cheaper size.
- Point the agent at a repository from an empty folder next to it. Each file
  it reads arrives as an image.

[INSTALL.md](INSTALL.md#work-for-the-most-savings) contains the numbered steps for
a repository that has a `CLAUDE.md`, for an audit and for each
session.
<br>

---

<br>

## What DensePack changes on your machine

DensePack changes three things that are yours and adds folders and packages of
its own. `/dense-remove` undoes all of them.

| What it changes | What DensePack does |
| --- | --- |
| `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `MEMORY.md` | Copies each one to `<name>.densepack.bak`, converts the text to images and leaves a short pointer |
| `~/.claude/settings.json` | Adds `"CLAUDE_CODE_THRIFTY_SONIC": "0"` once, when the key is not there |
| A `.gitignore` in `.claude/tmp/` and `.claude/densepack-vault/` | Writes one line, `*`. Git never commits those folders |
| `~/.claude/densepack-state` and `~/.claude/densepack-cards` | Creates them. They contain the settings and the rendered legend cards |
| Pillow, freetype-py and NumPy | Installs them into the plugin's own data folder. DensePack does not change your own Python |

[HOW-IT-WORKS.md](HOW-IT-WORKS.md#what-densepack-changes) contains the full table
and the rules for reading, editing and sharing a converted file.
[PLUGIN-FOLDERS-FILES.md](PLUGIN-FOLDERS-FILES.md) lists each folder and
working file.
<br>

---

<br>

## How it works

DensePack has four pieces. Each one costs you nothing to run.

| Piece | What happens |
| --- | --- |
| The swap | You call Read. A hook runs first. The hook draws the file as an image and gives the agent the image path. The agent reads the image normally |
| The packing | Files, shell output, subagent briefs and subagent reports all pack. The plugin compares the image price against the text price first and sends the text when the image costs more |
| The image | One function, `pack_code()`, draws each image. Color shows the nesting depth. A green number starts each line. A red number gives the indent |
| The Edit check | An Edit whose text is not in the file stops before it runs. The message quotes the file's own lines with each space and tab visible |

[HOW-IT-WORKS.md](HOW-IT-WORKS.md) explains all four in full, plus the seven slash
commands, the thirteen hooks and what all the scripts do.
<br>

---

<br>

## Word files

Claude Code cannot open a Word file on its own. DensePack converts each `.doc`
and `.docx` to images for you automatically, in the same turn as all other
file.

A `.docx` is a zip of XML. A `.doc` is an OLE2 container. DensePack reads `.docx` and `.doc` with
the standard library and needs no Word install.

Change a Word file with a shell command. A `.docx` is a zip. Unzip it, edit
`word/document.xml` and zip it back. The Edit and Write tools do not work on a Word
file. That limit is Claude Code, not the plugin.

[HOW-IT-WORKS.md](HOW-IT-WORKS.md#word-files) has the container table, the
three moments DensePack draws a Word file and why the scan costs almost nothing.
<br>

---

<br>

## The right-click tool and the HTML app

Two ways to pack text without Claude Code.

| Part | What it does | Who it is for |
| --- | --- | --- |
| Right-click tool | Packs a highlighted block or a file from your file manager. Ctrl+Right-click works in each application | Anyone using an AI chat |
| HTML app | Runs in your browser. Paste text in and the image renders live | Anyone who wants one image prompt without an install |

[INSTALL.md](INSTALL.md#install-the-right-click-tool) has the install steps for
the right-click tool and the HTML app. [tools/Tool-README.md](tools/Tool-README.md) says what the right-click
tool changes, how to skip the hotkeys and how to uninstall.
[index.html](index.html) is the app itself.
<br>

---

<br>

## Limits

- Haiku hallucinates image text. It is never sent images, only text.
  <br>

- DensePack converts a .doc or .docx in three ways. All three ways cost one turn: your prompt
  names the file, your prompt names the folder that contains it, or the agent finds it
  mid-task through Glob, Grep or a shell listing. See [Word files](#word-files).
  <br>
  
- Short conversations save less than long ones.
  <br>

- Edit and Write work on a file that arrived as an image. A Word file is the
  exception. Edit and Write do not work on a Word file because Claude Code does not Read a Word file.
  See [Word files](#word-files).
  <br>
  <sub>Your agent is told this at the start of each session.</sub>
  <br>
  
- DensePack adds about 370 prompt tokens once a session.
  That is the list of its 7 commands and 1 skill, plus one short note at session start. The other hooks add nothing to a plain message.
  <sub>Measured with Opus 5, as the same two messages with DensePack off and on.</sub>
  <br>

- A file over 500,000 bytes or 6,000 lines stays text. A file that contains a null byte stays text.
  <br>
- A file in Chinese, Japanese or Korean stays text. A file full of box-drawing characters stays text. The font has no glyphs for those characters.
  <br>
- On Windows without Git for Windows, the hooks run through a PowerShell script.
  Each hook then takes about 0.8 seconds, against about 0.2 seconds with Git.
  <sub>A company policy that blocks PowerShell scripts switches DensePack off on that computer.</sub>
<br>
- The HTML app uses its own renderer. The benches score the plugin's renderer.
  <sub>The right-click tool uses the plugin's renderer.</sub> 
<br>
- A model that has difficulty with an image uses more turns and more thinking blocks. 
  More output decreases the saving because Anthropic bills output at 5x the input price. 
<br>
- Sonnet 5 sometimes answers a question wrong on the text run and on the image run alike.
<br>

---

<br>

## Thank you

A font made for AI legibility and accuracy is a later project.

The DensePack plugin renders each character with [FreeType](https://freetype.org) and the [Inter](https://rsms.me/inter/) font family.<br>
Without them this project would have needed its own font from day one and the project may have stalled.
<br>

Thank you both.
<br>

---

<br>

## Files

| File | What it covers |
| --- | --- |
| [README.md](README.md) | What DensePack is, what it saves and how to install the plugin |
| [HOW-IT-WORKS.md](HOW-IT-WORKS.md) | The machinery: the swap, packing, the image, the Edit check, Word files, the commands, the hooks and the scripts |
| [INSTALL.md](INSTALL.md) | Each install step for Windows, macOS and Linux, the right-click tool, the HTML app and removal |
| [BENCHMARKS.md](BENCHMARKS.md) | Each bench pair, the prices, how Anthropic bills and how to recreate them |
| [PLUGIN-FOLDERS-FILES.md](PLUGIN-FOLDERS-FILES.md) | Each folder and working file the plugin writes and what each one is for |
| [tools/Tool-README.md](tools/Tool-README.md) | The right-click tool: install, use and the files it puts on your machine |
| [bench/README.md](bench/README.md) | The benches, the results, the faults and the fixes |
| [PRIVACY-POLICY.md](PRIVACY-POLICY.md) | What leaves your machine: nothing |
| [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) | The font and the libraries this project uses, with their licences |
| [LICENSE](LICENSE) | MIT |
