<!-- DensePack 1.3 -->
# DensePack folders and files

This file lists each folder and working file that the DensePack plugin writes, what each one holds and when the plugin writes it.

DensePack writes in these places.

| Place | What it holds |
| --- | --- |
| `<project>/.claude/densepack-vault/` | The images of the files and the Bash output that the agent reads, and the copies that DensePack keeps |
| `<project>/.claude/tmp/` | Working files for the current sessions |
| `~/.claude/densepack-state/` and the data folder of the plugin | Files outside the project, such as the seal key and the savings table of the last session |
| Your system temp folder | The copy of a file while DensePack packs it, and the job files of each pack |
| Each `CLAUDE.md`, `CLAUDE.local.md` and `MEMORY.md` that DensePack converts | A pointer to the images, with the original text beside it as `<name>.densepack.bak` |
| `~/.claude/settings.json` | `CLAUDE_CODE_THRIFTY_SONIC` set to `0` |

DensePack saves all of these files on your computer and sends none of them to a service.

---

## Folders in `.claude/densepack-vault/`

### `images/`

This folder holds these images.

- The images of the files that the agent reads.
- The images of the files in a folder that your message names. DensePack packs them in the background before the agent reads them. It does this only for a folder of 200 files or fewer, and only when the files of 1,000 to 500,000 bytes in that folder together hold 700,000 bytes or less.
- The images of a Word file that your message names, of a Word file in a folder that your message names by its full path, and of a Word file that the result of a Glob, Grep, Bash or LS call names.
- The images of Bash output that DensePack packs.

DensePack packs a file into images one character at a time, and a file of 127,466 bytes took 8.1 seconds to pack. For that reason, DensePack saves the images of a whole file here.

The name of the image of a file starts with the folder of the file in the project and the file name. For example, `src/README.md` gets `src-README.md-image-1-of-2-DensePack.png`. The file `<name>-claim-DensePack.txt` beside the images holds the full path of the source file. When a second file gets the same image name, its images get `~2`, `~3` and so on, up to `~50`. After `~50`, the name gets `~` and 8 hex characters of a hash of the path.

The images of a whole file have a `.json` file, `<name>-images-DensePack.json`, that holds a digest and a seal. The digest is a short hash of the file and the plugin version, and the same text and the same plugin version always give the same digest. The seal uses a key in `~/.claude/densepack-state/`, and for that reason a cloned project cannot make a valid seal.

At the next Read of the same file, DensePack compares the digest and checks the seal. When the two match, DensePack gives the agent the saved images. When you change the file or install a DensePack release with a new version number, the digest changes, and DensePack packs the file again.

A Read of part of a file, with an `offset` or a `limit`, gets images of only those lines. Their names hold the line range, for example `src-app.py-lines-40-120-image-1-of-1-DensePack.png`, and these images have no `.json` file. A Read with a `limit` of 20 lines or fewer stays text.

A Word file (`.doc` or `.docx`) also gets a text copy here. The text copy holds the exact text that the images show, one line for each paragraph, list item and table row. DensePack packs a copy of the Word file in `.claude/tmp/`, and for that reason the name of the text copy starts with `.claude-tmp-`, for example `.claude-tmp-densepack_word_<12 hex>.docx.txt`. The name of each image is the name of the text copy with `-image-N-of-M-DensePack.png` added, and the key row of each image shows the name of the text copy after `file=`. Only a Word file that you copy into `to-pack/` gets a text copy with its own name, such as `report.docx.txt`, as the section `to-pack/packed/` below explains.

Bash output that DensePack packs also gets a text copy here, `bash-output-<id>.txt`, beside its image.

### `to-pack/`

Copy a file into this folder to pack it without a Read.

DensePack packs the file at the next tool call of the agent. It does not pack the file when you copy it or when you send a message, because `pointer.py` runs on the `PostToolUse` event after each tool call, and one of its steps is to look in `to-pack/`.

Each tool call packs one file. Several files in `to-pack/` need several tool calls.

To pack a file, `pointer.py` first renames it in the same folder to `.densepack-claim-<epoch>-<8 hex>-<name>`. Two sessions can look in the folder at the same time, but only one rename succeeds, and only that session packs the file. Claims older than 30 minutes get their old names back at the next tool call.

`pointer.py` also packs a file that is in `drop/`, a folder of an older version. It does not pack a file in `to-draw/`, the name of this folder in DensePack 1.1, and that file stays there.

### `to-pack/packed/`

Session start makes this folder. `pointer.py` moves each packed file from `to-pack/` into this folder and puts its images beside it. DensePack does not delete the file, and it does not pack a file in `packed/` again. A file in a subfolder of `to-pack/` keeps that subfolder here.

The images take the name of the file. For example, `notes.md` gets the images `notes.md-image-1-of-1-DensePack.png`. When `packed/` already has a file with that name, the new file gets `~2` or `~3` before its extension, for example `notes~2.md`. A Word file also gets a text copy with `.txt` added to its name, for example `report.docx.txt`, and its images take the name of the text copy. The key row of each image shows the name of the text file after `file=`.

The message after the tool call names the image and the new path of the file.

### `not-converted/`

`pointer.py` moves a file from `to-pack/` into this folder when it cannot pack the file. When `pointer.py` cannot move the file here, the file stays in `to-pack/packed/` if the pack failed, or in `to-pack/` as `.densepack-failed-<name>` if the move into `packed/` failed. The scan skips that file.

### `drop-gate/`

Older versions kept the copy of a file for a Read in this folder. This version writes nothing here. At session start, `bootstrap.py` deletes its files that are older than 24 hours and its empty subfolders that are older than one hour.

### The copy of a file for a Read

When a Read ends and the file has no image in `images/`, the hook `read_image.py` asks `drop_read_gate.py` for the image. `drop_read_gate.py` copies the file into a new folder in your system temp folder, packs the copy and writes the images into `images/`. `read_image.py` then puts the image in the Read result. These steps run inside the same tool call, and the agent uses no extra turn.

The name of the new folder is `densepack-stage-` and random characters. Each pack gets a new folder, and for that reason two files with the same name in different folders never share a copy. Two agents that read the same file at the same time also get different folders.

The copy is outside the project, because a copy inside the project shows in the Grep and Glob results of the agent while the pack runs. DensePack deletes the copy and its folder when the pack ends. At session start, `bootstrap.py` deletes a `densepack-stage-` folder that is older than one hour.

### `instruction-images/`

This folder holds the images of the `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` of the project. The images of your `~/.claude/CLAUDE.md` and of the memory index `MEMORY.md` are in `~/.claude/densepack-state/instruction-images/`. [HOW-IT-WORKS.md](HOW-IT-WORKS.md#what-densepack-changes) explains that conversion.

`/mdpack <folder>` converts the `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` of another folder. It writes their images in the `instruction-images/` folder of the vault of that folder, and a `.gitignore` in that vault. `/dense-remove` restores these files and deletes their images. It deletes the vault of that folder only when a conversation file in `~/.claude/projects/` names the folder. Otherwise the vault and its `.gitignore` stay, and you can delete them by hand.

### One folder for each conversation

DensePack keeps a copy of each packed report and brief in a folder with the session id as its name. When DensePack has no session id, it uses the folder `no-session-id/`. These copies stay when you or DensePack clean `.claude/tmp/`.

Each copy holds the images, the source text and its `.seal` file. It also holds the code file and the legend when the pack made them. When a pack of a subagent report saves too little, DensePack keeps the report as text in `densepack-reply-<agent id>.txt` in `.claude/tmp/` and in the vault.

When the conversation folders together hold more than 200 MB, DensePack deletes the oldest conversation folders first. It deletes only folders with a session id or `no-session-id` as the name. It never deletes the newest conversation folder, `images/`, `to-pack/`, `not-converted/`, `instruction-images/`, a folder from an older version or a folder that you make. When the conversation folders still hold more than 200 MB, DensePack deletes the oldest files of the newest folder. The `vault_mb` value in `densepack-settings.json` changes the 200 MB limit.

### `.gitignore`

DensePack writes a `.gitignore` file in the vault and in `.claude/tmp/`. The file holds one line, `*`, and Git commits nothing from these folders. The files in them are useful only on this computer.

### Cleanup of the vault

At session start, `bootstrap.py` deletes all files older than 24 hours in `images/`, `drops/` and `drop-gate/`. `drops/` and `drop-gate/` are folders of older versions. DensePack packs a file again at the next Read, but it cannot make the deleted images and text copy of a Bash output again, because it keeps no other copy of that output. You can also delete these folders by hand.

---

## Files in `.claude/tmp/`

### The `densepack-ran-...` files

Each of these files is a lock that holds the word `ran` and a line end, 5 bytes on Windows and 4 bytes on Linux and macOS.

`hooks.json` names each hook script two times, one time for each shell.

```
exec sh run_hook.sh ... ; powershell -File run_hook.ps1 ... ;
```

Only one of the two runs. In a POSIX shell, `exec` replaces the shell, and the PowerShell part never starts. In PowerShell, `exec` is not a command, and the PowerShell part runs. The hook works with Git for Windows and without it.

Claude Code can load the plugin two times, from an install and from `--plugin-dir`, and then each hook runs two times for one event.

`run_once.py` prevents the second run, because it creates the lock file with the flags `O_CREAT | O_EXCL`. With those flags, the operating system creates the file only when the file does not exist, and only one process can create it. The process that creates the file runs the hook script, and a second process for the same event finds the file and exits.

The file name is `densepack-ran-`, then the session id, then a hash of 12 characters of the event and the script name. Each hook makes one file for each tool call. One Read runs four hooks, and a session with 40 Reads makes 160 files. All sessions of the project write into the same folder.

DensePack deletes these files in two ways.

- About 1 run in 200 of `run_once.py` deletes the lock files that are older than one hour.
- `bootstrap.py` deletes the lock files that are older than one hour at session start.

You can delete these files by hand.

### The other files

| File | What it holds |
| --- | --- |
| `densepack-lead-session` | The id of the session that started last. `bootstrap.py` writes it at session start. `common.py` uses this file to find the project folder |
| `densepack-lead-sessions.json` | The ids of the last main sessions. A hook uses the list to tell a main session from a subagent |
| `densepack-leadmodel` | The model of each main session, as a `{session id: model}` map. It is a map because one project can be open in two windows at the same time |
| `densepack-manifest.jsonl` | One row for each pack of a file, of a Bash output of 1,000 characters or more, of a brief and of a subagent report, and one row for each Read that returns the waiting report images, each report swap that missed and each command that reads packed text with `DENSEPACK_SOURCE_OK`. Bash output of 400 to 999 characters packs as one small image and gets no row. When a subagent report stays text, it also gets a row with the reason. Each row has a seal hash. A row of a pack also holds the character count, the text tokens and the image tokens. The rows of files, Bash output and reports also hold the model |
| `densepack-settings.json` | The settings that the slash commands and `dpctl.py` write. They apply to each session in this project folder, and each hook reads the file again when it runs |
| `densepack-packing-<hash>` | A lock while DensePack packs one file. A Read of the same file waits for it. DensePack deletes the lock when the job ends, or when the lock is older than 300 seconds |
| `densepack-off-<session id>` | The off switch of one window. `/dense-off` writes it, and `/densepack` deletes it |
| `densepack-queue.jsonl` | The rows of the savings table that `pointer.py` did not show yet |
| `densepack-pending.jsonl` and `densepack-delivered.json` | The images of packed reports, and the images that a Read already returned |
| `densepack-composite-1.png` | One image that holds all waiting report images, for one Read |
| `densepack-delegation.jsonl` and `densepack-card-<session>.jsonl` | One row for each Agent call |
| `densepack-agentmodel-agent-<id>` | The model of one subagent |
| `densepack-lifecycle.jsonl` | One row when a subagent ends or when the lead stops it |
| `densepack-totals.json` | The totals of the reports and briefs of this conversation |
| `densepack-receipt-last.md` and `densepack-receipt-owed.json` | The last savings table in quiet mode, and the turn that owes a table |
| `densepack-rule-<name>` | A mark that the lead already got one rule, such as the rule for the savings table |
| `densepack-cap-<key>` | A mark for a step that runs one time only, such as the note that names the images of a file |
| `densepack-dropread-<session>-<hash>` | A mark that a pack of this file failed in this session. A Read whose pack fails returns the text, and the next Read of the file tries the pack again |
| `densepack-word-<12 hex>.docx` or `.doc` | A copy of a Word file that your message or a tool result names, or that is in a folder that your message names. DensePack packs the copy, and the 12 hex characters come from a hash of the path of the Word file |
| `densepack-reply-<agent id>.txt` | A subagent report that stays text because a pack saves too little |
| `densepack-report-swap-<agent id>.json` and `densepack-report-background-<agent id>` | The line that replaces the report of a subagent in the Agent result, and the mark of a background subagent |
| `densepack-sourcewhy-<session>` | A mark that `source_gate.py` already sent the reason for a changed command in this session. No DensePack step except `/dense-remove` deletes it |
| `densepack-rangeonce-<session>-<hash>` | A mark that `source_gate.py` already checked one `sed -n` range of this report or brief text in this session. A later range of the same text runs as written. No DensePack step except `/dense-remove` deletes it |

At session start, `bootstrap.py` deletes the files in this folder that are older than 24 hours and whose names start with one of these parts.

- `densepack-img-`, `densepack-src-`, `densepack-report-`, `densepack-code-` and `densepack-legend-`
- `densepack-brief-`, `densepack-briefsrc-` and `densepack-briefcode-`
- `densepack-bash-`, `densepack-bashsrc-`, `densepack-bashout-`, `densepack-card-sent`, `densepack-start-` and `densepack-readonce-`

It deletes the `densepack-ran-` files that are older than one hour. It also deletes each `densepack-blocked-`, `densepack-asked-` and `densepack-floorpass-` flag at any age. Even when DensePack is off, it deletes each symbolic link and junction in this folder. `bootstrap.py` deletes no other file here. `session_end.py` deletes `densepack-totals.json` at the end of a conversation that packed a report or a brief.

### Why DensePack records the model

Each model that gets images gets the same image, and the size of its characters is 17 px. `CODE_PX` in `plugin/scripts/common.py` sets that size, and the environment variable `DENSEPACK_CODE_PX` can change it.

DensePack uses the model name for these things.

- Fable, Opus and Sonnet get images. Haiku and each other model get the files that they Read, their command output, their briefs and the reports that they receive as plain text. A Word file that your message names, a Word file in a folder that your message names by its full path and a Word file that a Glob, Grep, Bash or LS result names still get images for each model when the images cost less than the text. Haiku 4.5 with no earlier context read 1 of 10 packed reports correctly.
- A main session whose model DensePack did not record yet gets images, the same as Opus, but a subagent whose model DensePack cannot find gets the files that it reads and its Bash output as text.
- `/maxpack` and `/max-off` apply to Sonnet only. DensePack checks the model name to find Sonnet.
- Only Sonnet has a limit on the files of one turn. See the note at the end of this file.
- `report_pack_worth()` in `common.py` uses the dollar rates of the lead model, and for a background subagent also the rates of the subagent model, to decide whether a report packs.
- The manifest row of each file and each report records the model.

---

## Files and folders outside the project

| File or folder | What it holds |
| --- | --- |
| `~/.claude/densepack-cards/` | Nothing from this version, because the plugin has no `instructions` folder. Session start deletes each folder here that no session used for 7 days |
| `~/.claude/densepack-state/` | The key that seals the image records and the queue records. The list of converted instruction files, and the images of your own `CLAUDE.md` and memory index. The path of the Python that the hooks start, in `python-path` and `python-path-win`. Session start writes each path first to a part file, such as `python-path.<number>`, and then renames the part file. When the rename fails, the part file stays here, and you can delete it. The plugin writes no style file. A style file here, `projects/<hash>/style.json`, is an override for developers. When you write that file, DensePack reads it, and the images then differ from the images that [BENCHMARKS.md](BENCHMARKS.md) measured |
| `~/.claude/plugins/data/densepack-densepack-marketplace/`, the data folder of the plugin | The savings table of the last session, in `projects/<hash>/`. Pillow, freetype-py and NumPy in `pylibs/` when your Python does not have them. The hooks and the slash commands load them from there. The file `python-install-tried` when session start found no Python 3.10 or newer. On Windows, this file stops a second winget install, and when you delete it, the next session start tries winget again. On macOS and Linux, when you delete it, the next session start shows the install command again. Without this folder, the savings table goes to `~/.claude/densepack-state/projects/<hash>/`, and `python-install-tried` goes to `~/.densepack/` or `%LOCALAPPDATA%\densepack\` |
| `~/.claude/settings.json` | `CLAUDE_CODE_THRIFTY_SONIC` set to `0` in the `env` block. Session start adds it when the `env` block does not have it. A value that you set stays. The value stops the message in auto mode and `bypassPermissions` mode that tells Claude to read files with Bash |
| `~/.claude/CLAUDE.md` and the `MEMORY.md` of each project in `~/.claude/projects/` | A pointer to the images when DensePack converts the file, with the original text beside it as `<name>.densepack.bak`. An older `.bak` becomes `<name>.densepack.bak.old-N` |
| `~/.claude/plugins/cache/densepack-marketplace/densepack/<version>/` | The plugin |
| Your system temp folder | The copy of a file for a Read, in a `densepack-stage-*` folder. The work folders `densepack-bashimg-*`, `densepack-bashsmall-*`, `densepack-plan-*`, `densepack-widths-*` and `densepack-warm-*`. The job files `densepack-pack-*`, `densepack-plan-*`, `densepack-trial-*` and `densepack-prepack-*`. A pack deletes its folders when it ends and its job file when it reads it. Session start deletes a `densepack-stage-*` folder that is older than one hour |

<sub>Run `/dense-remove` before you uninstall. It restores the original text of each converted `CLAUDE.md`, `CLAUDE.local.md` and `MEMORY.md`. It deletes `~/.claude/densepack-cards/`, `~/.claude/densepack-state/`, and the vault and the `densepack-` and `.densepack-` files in `.claude/tmp/` of each project folder that a conversation file in `~/.claude/projects/` names. It also deletes `~/.densepack`, the `python-install-tried` file in `%LOCALAPPDATA%\densepack` and the `densepack-trial-*.pkl` files in your temp folder. It deletes `~/.claude/densepack-tracker.json`, a file that only a version before DensePack 1.0 wrote. It removes `CLAUDE_CODE_THRIFTY_SONIC` from `~/.claude/settings.json` when its value is `0`, and it removes the trust entry of the marketplace folder from `~/.claude.json`. Claude Code writes that trust entry, not DensePack. The hooks of the same session can still write a few files after the command runs, such as `densepack-ran-` files in `.claude/tmp/` and an image of the printed list in `.claude/densepack-vault/images/`, and you can delete them by hand. Then run `/plugin uninstall densepack` and `/plugin marketplace remove densepack-marketplace`. The uninstall deletes the plugin and its data folder.</sub>

---

## What DensePack does for each action

| What you do | What DensePack does |
| --- | --- |
| You Read a file of 1,000 bytes or more | The file arrives as images when the images and the note cost less than the text. When the file needs more than one image, the result holds image 1, and a note names the others. A Read with a `limit` of 20 lines or fewer stays text |
| You run a command that prints 400 characters or more | The output arrives as images when the images and the exact lines cost less than the text. The result holds the first image, and a note names the others. Each line with a `git --stat` bar, a `pip list` rule, a number of 18 or more digits, a random ID with a capital I or a small l, only spaces or tabs, or a tab inside a line other than the tab after a line number goes beside the image as exact text. Only the output of the Bash tool packs, and the output of the PowerShell tool stays text |
| You run a command that prints the text of a packed report or brief in `.claude/tmp/` | The command prints a line that names the image in place of the text. The command runs as written when it prints one line with `sed -n 'Np'`, when it is the second or a later `sed -n 'N,Mp'` range of the same file in this session, or when it holds the word `DENSEPACK_SOURCE_OK`. DensePack does not change a command that prints the text copy of a Bash output in the vault |
| You start a subagent with a brief of 1,000 characters or more | The subagent gets a line that names an image of the brief, and it Reads that image. This happens only when the subagent gets images, code blocks fill half of the brief or less, and the saving pays for the extra Read |
| A subagent starts | `subagent_start.py` sends it the session start note. When DensePack knows that the subagent gets text, such as Sonnet after `/max-off`, it sends no note. A Haiku subagent gets the note too, but its Reads, its Bash output and its brief stay text |
| A subagent finishes its report | The report arrives as an image only when the lead gets images, code blocks fill half of the report or less, and `report_pack_worth()` calculates that the image saves more than the extra Read of the lead costs. Because Claude Code cannot put an image in the result of the Agent tool, the lead gets a line that names the image and Reads the image. For a background subagent, DensePack also asks the subagent one time to reply with only the line that names the report file, and the saving must pay for that extra turn too. Otherwise the report arrives as text |
| You Edit a file that arrived as an image | The Edit works |
| You Write a file that arrived as an image | The Write works |
| You Edit or Write a Word file | Edit and Write fail. Only a shell command can change a Word file |
| You Edit with an `old_string` that the file does not hold | The Edit fails, and the message quotes the closest lines of the file with each space and tab shown. When no line is close, the message tells the agent to Read the file again |
| You Edit with an `old_string` that the file holds more than one time, without `replace_all` | The Edit fails, and the message names up to 3 lines where a copy starts |
| You Grep a file that a Read packs, or a folder that holds such a file, with a pattern that prints each line | The Grep fails, and the message names a file to Read. A Grep works when its pattern matches no empty line and fails to match at least one of the characters space, `a`, `Z`, `0`, `_`, `(`, `}` and `#`, when it has a `head_limit` of 20 or fewer, or when it uses the `files_with_matches` or `count` mode |
| You Glob a DensePack text file that has an image, in `.claude/tmp/` or the vault | The Glob fails, and the message names the image |

> [!IMPORTANT]
> In Claude Code 2.1.284, an Edit works with no Read of the file. In a test without DensePack,
> Edit worked after `cat` 3 times and after `grep | head` one time. With DensePack, a Read runs
> on the real file, and the hook swaps the result for the image after the Read runs. Edit and
> Write work on that file.
>
> A Word file is the one exception, because a `.doc` or `.docx` file is a binary container and not
> text, and the Read tool of Claude Code does not open it. See [Word files](HOW-IT-WORKS.md#word-files).

DensePack never packs these Reads.

- Images, PDFs and notebooks. Claude Code reads them as images or as structured cells.
- A file in a `.claude` folder, or a file whose path has `sandbox` or `scratch` in the name of a folder or of the file. Those folders hold working files and the images of DensePack.
- A file below 1,000 bytes, because the pack takes time and memory and saves only a few tokens. The pack of a 483-byte file took 2.5 seconds and 469 MB of memory to save 10 tokens.
- A file over 500,000 bytes, because the wait at the first Read grows with the size of the file, and a file of about 300,000 bytes took 14 to 17 seconds to pack.
- A file with a null byte, because that file is not text.
- A file where the Inter font cannot show more than 2% of the characters that are not spaces, such as Chinese, Japanese or Korean text.
- A Read with a `limit` of 20 lines or fewer. The agent gets those lines as text.
- A Read by an agent that gets text, such as Haiku, Sonnet after `/max-off`, or a subagent whose model DensePack cannot find.
- A Read when Pillow, freetype-py or NumPy is missing.
- A file whose images and note do not cost less than its text.

<sub>One rule applies to Sonnet only. When one Sonnet turn asks for more than 32 files, or for more than 700,000 bytes of files, DensePack sends text. Opus and Fable have no such limit.</sub>
