<!-- DensePack 1.2 -->
# How DensePack works

The mechanics in full. [README.md](README.md) contains the summary of each part
below and links here.

- [What DensePack changes](#what-densepack-changes)
- [How the swap happens](#how-the-swap-happens)
- [What DensePack packs](#what-densepack-packs)
- [The Edit check](#the-edit-check)
- [The image](#the-image)
- [Word files](#word-files)
- [The slash commands](#the-slash-commands)
- [The hooks](#the-hooks)
- [The scripts](#the-scripts)

Three other files contain the rest. [INSTALL.md](INSTALL.md) contains all the install
steps. [BENCHMARKS.md](BENCHMARKS.md) contains the measurements and the prices.
[PLUGIN-FOLDERS-FILES.md](PLUGIN-FOLDERS-FILES.md) lists each folder and
working file the plugin writes.
<br>

---

<br>

## What DensePack changes

DensePack changes three things that are yours and adds folders and packages of its own.

The slash command `/dense-remove` undoes all of them.

| What it changes | What DensePack does | Why |
| --- | --- | --- |
| `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` in a project, your `~/.claude/CLAUDE.md` and the project's auto memory index `MEMORY.md` | At session start, it copies the file to `<name>.densepack.bak`, converts the text into images and replaces the file with a short pointer that names each image. It converts a file only when the images and pointer cost less than the text | Claude Code sends these files as text on each call. As images they cost about half |
| `~/.claude/settings.json` | Adds `"CLAUDE_CODE_THRIFTY_SONIC": "0"` to the `env` block, once, when the key is not there | Auto mode tells the agent to read files with Bash. A Bash read saves less than using the Read tool because Bash takes an extra turn |
| A `.gitignore` in `.claude/tmp/` and `.claude/densepack-vault/` | Writes one line, `*` | Those folders contain copies of your files and command output. Git never commits them |
| `~/.claude/densepack-state` | Creates the folder. Contains the location of the Python it found and one folder per project | DensePack reads its own notes to find the files that it converted. A repository you clone can contain a fake copy of those notes. DensePack keeps the real notes in your home folder, where a clone cannot write |
| `~/.claude/densepack-cards` | Creates the folder. Contains the rendered legend cards, one folder per card | Without it, each new project draws the entire card set from nothing. That takes minutes at session start |
| Pillow, freetype-py and NumPy | Installs them with pip into the plugin's own data folder, once | DensePack needs all three to render an image. DensePack does not change your own Python and asks for no password |
<br> 
<br>

---

<br>

### How the conversion works

- Claude Code loads `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` in a project, your `~/.claude/CLAUDE.md` and the project's auto memory index `MEMORY.md` before DensePack runs.
  If you start in a folder that contains one of these, the conversion happens after Claude Code reads that file as text and caches it.
  To prevent this, run `/mdpack <folder>` from an empty folder next to the folder with the files. That converts them without reading them as text first. You can then start Claude Code in that folder. Claude Code reads the short text pointer and the images instead of the raw text.
- Each converted file becomes three files: the pointer, the `.densepack.bak` and the images.
- The `.bak` contains your original text, byte for byte. Claude Code does not load the `.bak` because Claude Code loads only the file names `CLAUDE.md`, `CLAUDE.local.md` and `MEMORY.md`.
- A file converts only when its images and pointer cost less than its text. A short file stays text.
- Reading the images can take one extra call at the start of a session. A large `CLAUDE.md` repays it within a few calls. A small file that converts alone, such as a short `MEMORY.md`, does not always repay it in a short session.
- To change your instructions, edit the `.bak`. DensePack converts it again at the next session start.
- Text added below the pointer moves into the `.bak` at the next session start. New lines from auto memory move the same way.
- If you replace a pointer with a new file, DensePack converts the new file and the old `.bak` stays as `.densepack.bak.old-1`.
- A Haiku session reads the `.bak` as text because Haiku does not read text on images accurately.
- Auto memory keeps working. DensePack sets no flag that turns memory off.
- In a shared repository, commit the `.bak` with the pointer. A teammate without DensePack reads the `.bak`.

<br> 
<br>

---

<br>

## How the swap happens

The swap happens automatically, before the tool runs.

1. The agent calls the Read tool on a file.
2. A hook runs **before** the read happens.
3. The hook converts that file into a dense image and swaps the file path for
   the image path.
4. The agent receives the image instead of the text. It reads it normally.

The same swap runs on shell output. When a Bash command prints a long wall
of text:
1. A hook rewrites the command before it runs.
2. The command writes its output to a file.
3. The hook renders that file as an image.
4. The agent receives the image instead of the text.

A subagent gets its brief as an image and sends its report back as an image.

### Folder files

A prompt can say "this folder" or name a folder by its full path.
Then `prompt_card.py` sends the names of the files in that folder with your prompt.
The agent reads the files in its first turn and does not spend a turn on Glob.
`prompt_card.py` also starts to draw those files in the background, many at a time.
A Read of one of those files waits for that draw and does not draw the file again.
A folder with more than 200 files gets no names.
<br>

---

<br>

## What DensePack packs

DensePack packs files and command outputs. DensePack also packs the briefs and reports that go to and from subagents.
Before each Read the plugin compares what the image costs with what the text costs.
It sends the text when the image costs more.
A Read costs nothing extra because the hook changes the file path before the Read runs.
A command costs one turn more than a Read: one turn to give the agent the image and one turn for the agent to read the image.
A command's output also arrives wrapped in extra text from Claude Code.
The plugin counts that turn and that extra text in the comparison. Thus Read packs at 1,000 bytes and a command needs thousands.

### What each DensePack part costs

Claude Code writes each new token to the 1-hour cache. Anthropic charges that token at 2x the input price.
Each later request sends the entire conversation again. Anthropic charges those same tokens at 0.1x the input price, 0.05x on Opus 5.5 or 0.025x on Fable 5.1.
An output token costs 5x the input price.

The table shows what Anthropic charges for each part. Each number is a count of input tokens.
The image is not in the table. The size of the image changes with the file.

| Part | How often | The first time | Each later request |
| --- | --- | --- | --- |
| The session start note and the list of 7 commands and 1 skill | One time per session | 772 | 39, or 10 on Fable 5.1 |
| A Read of a file that fits one image | Each Read | Nothing. The hook changes the path and adds no text | Nothing |
| The pointer in a Bash result, for one image | Each packed command output | 320 | 16, or 4 on Fable 5.1 |
| The agent's Read call that opens the Bash image | Each packed command output | 510 | 10, or 3 on Fable 5.1 |
| The extra request that the Read call makes | Each packed command output | The length of the conversation at 0.1x, 0.05x on Opus 5.5 or 0.025x on Fable 5.1 | Nothing. Anthropic charges it one time |

When a part goes to the model a second time, Anthropic charges it as new again.
A second Read of the same file uses the saved image. Anthropic charges that image at 2x again. The image is new at the end of the conversation.
When the agent runs the same command a second time, the result has the same image and the same pointer. Anthropic charges the image and the pointer at 2x again.
The lower price applies only to the tokens that a previous request sent.

The pointer contains the path of the project folder. A longer path adds a small number of tokens.

<sub>These numbers are from 20 September 2026, with Sonnet 5. Each test was a new `claude -p` session, with DensePack off and then on. The `usage` rows of each transcript give the token counts. The session start is 386 tokens. The pointer is 160 tokens. The Read call is 102 output tokens. One session sent each part two times.</sub>

| What DensePack packs | When |
| --- | --- |
| A brief that goes to a subagent | Before the subagent starts |
| A subagent's report | When the subagent finishes |
| Read tool | Before the Read runs |
| Long shell output | Before the Bash command runs |

| File type | Reads as an image |
| --- | --- |
| Text with accents, dashes, Greek and maths signs | Yes |
| Prose: reports, briefs, shell output | Yes. Agents communicate with each other with images of their reports and briefs |
| Python `.py` | Yes. <br><br>Opus rebuilt 99.8% of the characters or more. Fable scored 99.83% |
| HTML `.html` | Yes. Byte identical rebuild on Opus. Fable 99.99% |
| Markdown `.md` | Yes. Opus and Fable rebuilt all the words |
| Go `.go`, indented with tabs | Yes. <br><br>Fable scored 99.97%. Opus scored 99.93%. Sonnet scored 99.72%. All three rebuilt all tabs as tabs |
| Markdown with a wide table row | Not yet. The image costs more. The plugin sends text. |
| Word `.docx` and `.doc` | Yes. Claude Code cannot open a Word file on its own. DensePack reads the words out and draws them, in the same turn as all other files. Up to 0.5 MB, [raise that here](INSTALL.md#the-size-ceiling) |
| JSON, CSV, YAML | Not measured |
| Haiku, all files | No. Haiku gets text |
| Sonnet, all files | Yes. Type `/max-off` to send Sonnet text |
| Chinese, Japanese, Korean font | No. Only Inter font glyphs at the moment |

<sub>Byte identical rebuild is not a real use case. This bench is only to show that the agents can rebuild different file types from DensePack images near perfectly. </sub>
<br>

---

<br>

## The Edit check

DensePack checks an Edit before it runs. An Edit whose text is in the file
exactly once passes and costs nothing.

An Edit whose text is not in the file, or is there more than once, stops
before it runs. The message quotes the file's own lines, with each space and
tab visible:

```
DensePack: that text is not in m.md. The file contains this, character for character:
     1  'The first hook runs one time and never again. It cannot  '
     2  'see a file the agent finds ten tool calls later.'
Send the Edit again with the text above. The quotes show every space and tab.
```

An agent reads a file as an image. An image draws each character. An image
cannot draw a trailing space. An agent that copies a block out of an image can
lose that space. Then the Edit fails. This hook returns the real line in the
same turn. The agent sends the Edit again with it.
<br>

---

<br>

## The image

> One function, `pack_code()` in `plugin/scripts/codepack.py`, produces each image. 
> The image is the same PNG, 756 or 784 pixels wide, for each model. The renderer keeps the width that saves more.
> Several processes draw a file of 60,000 bytes or more at the same time. Each process draws its own pages. The pages are the same as from one process.
<br>

<p align="center">
<img src="images/single-file-bench-image.png" alt="The single file bench subject as a DensePack image" width="784" />
</p>
<br>

| Character ink color | Source file |
| --- | --- |
| Black | Letters |
| Blue | Digits |
| Red | Most other marks |
<br>

| Color Code | Description |
| --- | --- |
| A coloured band behind a row | The nesting depth of each line |
| A green number at the row start | The source file's line number |
| A gap in the green numbers | Blank lines |
| A red number after the green | The line's indent, in spaces |
| A purple mark at the right edge | The line continues on the next row |
| The top two rows of the image | Color code legend |




This is the image the single file bench reads.

| The image above | Value |
| --- | --- |
| What it contains | Each character of `bench/single-1000-token-file/subject-ab_run.py` |
| Size of that file | 4,461 characters of Python |
| Pixels | 784 by 896 |
| Cost as an image | 896 visual tokens |
| Cost as text | 1,859 tokens |
| Score | Fable, Opus and Sonnet each answered 5 of 5 |

The font is Inter SemiBold. 
FreeType renders each character as a grey mask and Pillow writes the PNG. 
The renderer condenses letters to 10 of 17 of their width. 
It condenses digits, brackets, the lowercase l and the comma to 12 of 17.

The API charges an image by patches of 28 by 28 pixels. 
A 784 by 896 image is 896 visual tokens. 
Text costs about one token per 2.4 characters. 
The plugin compares the two numbers for the file and sends the text when the text is cheaper.
<br>

---

<br>

## Word files

DensePack converts each `.doc` and `.docx` to images automatically.
A Word file costs one turn, the same as all other files.
Three hooks find Word files. The three hooks include all cases.

A Word file uses a different route because the Read tool of Claude Code does not open a Word file.
The table shows each difference.

|  | `.docx` | `.doc` | All other files |
| --- | --- | --- | --- |
| **Container** | a zip of XML | an OLE2 container, a small filesystem of streams | plain text on disk |
| **Extractor** | `pointer.docx_text()` unzips it, reads `word/document.xml`, reads each `<w:p>` paragraph node | `pointer.doc_text()` opens the OLE2 streams, reads the `WordDocument` stream, then reads the piece table in the `Table` stream to put the bytes back in reading order | none needed, the bytes are the words |
| **Library** | `zipfile` and `xml.etree` from the standard library | `struct` parsing by hand, standard library | none |
| **Which hook draws it** | `prompt_card.py`, on UserPromptSubmit, before the agent moves | same | `drop_read_gate.py` and `read_gate.py`, on PreToolUse for Read |
| **How the agent reads it** | the agent Reads the PNG that the hook drew | same | the agent Reads the file and the hook swaps the result for the image |
| **Turns to read** | one, always | one, always | one, always |
| **Edit** | does not work | does not work | works |
| **Write** | does not work | does not work | works |
| **How to change one** | a shell command, for example a Python script using `python-docx` | a shell command | Edit or Write |
<br>

---

<br>

### Why Edit and Write do not work on a Word file

Not because the file arrived as an image. Edit and Write ask only one question: did the agent
Read this exact path in this session? Claude Code answers yes as soon as the
agent makes the Read call, whatever the result looked like. An image counts.

A Word file never reaches that question. Claude Code's Read rejects a binary file
during its own input check. That check runs **before** all PreToolUse hooks.
`drop_read_gate.py` never runs for a `.doc` or `.docx`. Measured 17
September 2026: a `.md` Read logs an event in that gate, a `.doc` Read logs
nothing.

Claude Code never marks the path as read. Thus Edit and Write do not work on the file.
Claude Code makes this limit, not the plugin.

That check does not apply to the shell. A Python script can rewrite the
file. No other route changes a Word file.
<br>

---

<br>

### The three ways DensePack draws a Word file

DensePack draws a Word file before the agent asks for the file because the agent
cannot open a Word file. DensePack draws it at one of three moments. The three moments
include all cases. **All three cost one turn**, the same as all other files.

| When | What you did | Which hook finds it |
| --- | --- | --- |
| You name the file | `read C:\work\report.docx` | `prompt_card.py`, on UserPromptSubmit |
| You name the folder | `read the word files in C:\work` | `prompt_card.py`, same hook, lists the folder |
| The agent finds it later | you said "audit this repo" and the agent ran Glob | `pointer.py`, on PostToolUse |

The moment "The agent finds it later" needs an explanation.

`prompt_card.py` runs one time, when you press Enter. `prompt_card.py` cannot
see a file that the agent finds ten tool calls later. `pointer.py` finds those
files.

`pointer.py` runs after **each** tool call. Claude Code gives `pointer.py` the output
of that tool. When a Glob, Grep or shell listing prints a path ending in `.doc` or
`.docx`, the plugin draws it right then. The image is ready before the agent
reads the file.

That costs no extra tool call. The agent runs that Glob to find the file.
The drawing happens inside that same call.
<br>

---

<br>

### Why the scan does not slow everything down

That scan runs after each tool call. It has to be almost free on the calls that
do not name a Word file. Three things keep it that way:

- **It checks the tool name first.** Only `Glob`, `Grep`, `Bash` and `LS` can name
  a new file on disk. Anything else stops immediately.
- **Then it checks for the plain text `.doc`.** This is a substring search, not a
  regular expression. The search runs before the hook opens a file on your disk. No
  `.doc` in the output means the scan is over.
- **Then it stops at 6 files and 100,000 characters.** A folder that contains 400 Word
  documents cannot turn one Glob into a long render. The hook does not search a
  build log of many megabytes to the end.

The same rule applies to the prompt hook. A hook that lists folders for each
"hello" makes each message slower and finds no Word file. The hook follows only a path
that is absolute. The hook lists only the folder itself, never the folders below it.

These hooks run on **your computer**, not on Anthropic's. Claude Code waits for
them to finish before it sends your message. A slow hook is a pause that you
feel.
<br>

---

<br>

## The slash commands

The plugin has seven commands. Each one is a markdown file in
`plugin/commands/`. Claude Code reads that folder to build the list.

| Command | What it sets | Reach |
| --- | --- | --- |
| `/densepack` | Packing on and all settings back to default | All conversations |
| `/dense-off` | All hooks stop | This conversation only |
| `/maxpack` | Sonnet gets images. This is the default | All conversations |
| `/max-off` | Sonnet gets plain text. Fable and Opus still get images | All conversations |
| `/helppack` | Nothing. It prints all commands and all settings | Prints only |
| `/mdpack <folder>` | Nothing. It converts that folder's instruction files | That folder |
| `/dense-remove` | Nothing. It undoes all changes and deletes all DensePack files | Your machine |

Two commands read a setting rather than write one. `/helppack` prints the
table above with the current value of each row. `/mdpack` takes a folder path
and converts the `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` inside
it without reading them.

`dpctl.py` runs all the commands. It writes one file per setting in
`~/.claude/densepack-state`. The hooks read that folder fresh on each event,
and a change applies on the next tool call.

`/dense-off` is the one command that belongs to a single conversation. It
writes the session id of the window that typed it. All other windows keep
packing.

Run `/dense-remove` before `/plugin uninstall densepack`. No hook runs during
an uninstall. A plugin cannot run code after Claude Code deletes the plugin.
<br>

---

<br>

## The hooks

Claude Code runs a hook at a named moment. `plugin/hooks/hooks.json` names
the moment and the script. All rows below run on your computer.

| Moment | Tool it watches | Script | What it does |
| --- | --- | --- | --- |
| SessionStart | None | `ensure_python.sh`, `ensure_python.ps1` | Finds a Python and installs one when the machine has none |
| SessionStart | None | `bootstrap.py` | Converts the instruction files, draws the legend card and sends the standing note |
| UserPromptSubmit | None | `prompt_card.py` | Sends the legend card once a session, draws a Word file your prompt names and sends the file names of a folder your prompt names |
| PreToolUse | Read | `drop_read_gate.py` | Draws a file you dropped in by hand and swaps the path |
| PreToolUse | Read | `read_gate.py` | Swaps the file path for the image path before the Read runs |
| PreToolUse | Edit | `edit_gate.py` | Stops an Edit whose text is not in the file and quotes the real lines |
| PreToolUse | Grep, Glob | `grep_gate.py` | Stops a call that gives the agent a source file that the plugin drew |
| PreToolUse | Bash | `source_gate.py` | Stops a shell read of a file that has an image |
| PreToolUse | Bash | `bash_gate.py` | Wraps the command. Long output then arrives as an image |
| PreToolUse | Agent, Task | `brief_pack.py` | Converts a long brief to an image before the subagent starts |
| SubagentStop | None | `subagent_stop.py` | Converts the finished report to an image and saves it |
| PostToolUse | All tools | `pointer.py` | Writes the receipt table and scans for Word files the last call named |
| SessionEnd | None | `session_end.py` | Cleans the working folders and writes the conversation totals |

Two rules apply to all of them.

1. A hook never crashes its caller. Each script does its work in one `try` block.
   A fault in a script does not stop the call.
2. `run_once.py` runs first in each hook that runs a Python script. The first
   `SessionStart` hook runs `ensure_python.sh` or `ensure_python.ps1`. That hook
   runs no Python script. It does not use `run_once.py`. `run_once.py` creates a marker file with
   `O_CREAT | O_EXCL`. Only one process can create the marker file. A plugin loaded
   twice draws each file once.

`run_hook.sh` and `run_hook.ps1` pick the shell. Windows without Git for
Windows runs the PowerShell copy. All other machines run the shell copy.
<br>

---

<br>

## The scripts

All scripts are in `plugin/scripts/`. The table above names the ones a hook
runs. These are the rest.

| Script | What it does |
| --- | --- |
| `common.py` | The shared code. Reads the hook event, writes the reply, finds the project folder and contains the settings |
| `codepack.py` | The renderer. One function, `pack_code()`, draws each image this plugin makes |
| `style.py` | All colours, sizes and words the renderer uses, including the legend rows |
| `freetype_glyph.py` | Draws one character as a grey mask. FreeType renders it and Pillow writes the PNG |
| `densepack.py` | The command line entry point. It packs the files you name and prints the token comparison |
| `dpctl.py` | Runs all slash commands and prints the `/helppack` tables |
| `bash_pack.py` | Packs the output of a wrapped shell command. A wrapped command runs it, not a hook |
| `pack_instructions.py` | Turns one instruction file into a pointer, its images and a `.bak` of the original |
| `run_once.py` | The lock that stops a twice-loaded plugin drawing everything twice |
| `run_hook.sh`, `run_hook.ps1` | Pick the shell, then run the script the hook names |
| `ensure_python.sh`, `ensure_python.ps1` | Find a Python and install Pillow, freetype-py and NumPy into the plugin's own folder |

Read `codepack.py` and `style.py` first. They make all the images the plugin sends
to a model. The right-click tool uses the same two files. The HTML app has its
own renderer in `index.html`.
