<!-- DensePack 1.3.4 -->
# DensePack folders and files

This doc lists the folders and working files that the DensePack plugin writes, what they hold and when the plugin writes them.

DensePack writes files in these places.

| Place | What it holds |
| --- | --- |
| `<project>/.claude/densepack-vault/` | It holds the images of the files and the Bash output that the agent reads, and the copies that DensePack keeps. |
| `<project>/.claude/tmp/` | It holds the working files of the current sessions. |
| `~/.claude/densepack-state/` and the data folder of the plugin | They hold files outside the project, such as the seal key and the savings table of the last session. |
| Your system temp folder | It holds the copy of a file while DensePack packs it, and the job files of each pack. |
| Each `CLAUDE.md`, `CLAUDE.local.md` and `MEMORY.md` that DensePack converts | DensePack replaces the file with a pointer to the images and keeps the original text beside it in `<name>.densepack.bak`. |
| `~/.claude/settings.json` | DensePack sets `CLAUDE_CODE_THRIFTY_SONIC` to `0` in this file. |

DensePack saves all of these files on your computer and sends none of them to a service.

<br>

---

<br>

## Folders in `.claude/densepack-vault/`

### `images/`

This folder holds the images that DensePack makes.

- Files that the agent reads have their images here.
- Files in a folder that your message names also have their images here. DensePack packs them in the background before the agent reads them. It does this only when the folder holds 200 files or fewer, and only when the files of 1,000 to 1,000,000 bytes in that folder together hold 700,000 bytes or less.
- Word files have their images here when your message names them, when they are in a folder that your message names by its full path, or when the result of a Glob, Grep, Bash or LS call names them.
- Bash output that DensePack packs has its images here.

DensePack packs files into images one character at a time. The pack of a file of 127,466 bytes took 8.1 seconds, and for that reason DensePack saves the images of whole files here.

Image names follow these rules.

- Image names start with the folder of the file in the project and the file name. For example, `src/README.md` gets `src-README.md-image-1-of-2-DensePack.png`.
- The file `<name>-claim-DensePack.txt` beside the images holds the full path of the source file.
- When a second file gets the same image name, its images get `~2`, `~3` and so on, up to `~50`. After `~50`, the name gets `~` and 8 hex characters of a hash of the path.

The images of a whole file also get a `.json` file, `<name>-images-DensePack.json`, that holds a digest and a seal.

- The digest is a short hash of the file and the plugin version. The same text and the same plugin version always give the same digest.
- Cloned projects cannot make a valid seal because the seal uses a key in `~/.claude/densepack-state/`.
- At the next Read of the same file, DensePack compares the digest and checks the seal. When the two match, DensePack gives the agent the saved images.
- When you change the file or install a DensePack release with a new version number, the digest changes, and DensePack packs the file again.

Reads of part of a file, with an `offset` or a `limit`, get images of only those lines.

- The names of these images hold the line range, for example `src-app.py-lines-40-120-image-1-of-1-DensePack.png`.
- These images have no `.json` file.
- Reads with a `limit` of 20 lines or fewer stay text.

Word files (`.doc` or `.docx`) also get a text copy here.

- The text copy holds the exact text that the images show, with one line for each paragraph, list item and table row.
- DensePack packs a copy of the Word file in `.claude/tmp/`, and for that reason the name of the text copy starts with `.claude-tmp-`, for example `.claude-tmp-densepack_word_<12 hex>.docx.txt`.
- Each image name is the name of the text copy with `-image-N-of-M-DensePack.png` added.
- The key row of each image shows the name of the text copy after `file=`.
- Only Word files that you copy into `to-pack/` get a text copy with their own name, such as `report.docx.txt`. See the `to-pack/packed/` section below.

Bash output that DensePack packs also gets a text copy here, `bash-output-<id>.txt`, beside its image.

### `to-pack/`

Copy a file into this folder to pack it without a Read.

DensePack packs the file at the next tool call of the agent.

- DensePack does not pack the file when you copy it or when you send a message. `pointer.py` looks in `to-pack/` as one of its steps, and it runs on the `PostToolUse` event after each tool call.
- Each tool call packs one file, and several files in `to-pack/` need several tool calls.
- To pack a file, `pointer.py` first renames it in the same folder to `.densepack-claim-<epoch>-<8 hex>-<name>`. Two sessions can look in the folder at the same time, but only one rename succeeds, and only that session packs the file.
- Claims older than 30 minutes get their old names back at the next tool call.
- `pointer.py` also packs files in `drop/`, a folder of an older version.
- `pointer.py` does not pack files in `to-draw/`, the name of this folder in DensePack 1.1, and those files stay there.

### `to-pack/packed/`

DensePack makes this folder at session start.

- `pointer.py` moves each packed file from `to-pack/` into this folder and puts its images beside it.
- DensePack does not delete the files in `packed/` and does not pack them again.
- Files in a subfolder of `to-pack/` keep that subfolder here.
- The image names start with the file name. For example, `notes.md` gets the images `notes.md-image-1-of-1-DensePack.png`.
- When `packed/` already has a file with that name, the new file gets `~2` or `~3` before its extension, for example `notes~2.md`.
- Word files also get a text copy with `.txt` added to their name, for example `report.docx.txt`, and the image names start with the name of the text copy. The key row of each image shows the name of the text file after `file=`.
- The message after the tool call gives the image name and the new path of the file.

### `not-converted/`

`pointer.py` moves a file from `to-pack/` into this folder when it cannot pack the file. When `pointer.py` cannot move the file here, the file stays in one of these places, and the `to-pack/` scan skips it.

- The file stays in `to-pack/packed/` if the pack failed.
- The file stays in `to-pack/` as `.densepack-failed-<name>` if the move into `packed/` failed.

### `drop-gate/`

Older versions kept the copy of a file for a Read in this folder, and this version writes nothing here. At session start, `bootstrap.py` deletes the files in this folder that are older than 24 hours and the empty subfolders that are older than one hour.

### Read copies

When a Read ends and the file has no image in `images/`, DensePack makes the image in these steps.

1. The hook `read_image.py` calls `drop_read_gate.py` to get the image.
2. `drop_read_gate.py` copies the file into a new folder in your system temp folder, packs the copy and writes the images into `images/`.
3. `read_image.py` puts the image in the Read result.

These steps run inside the same tool call, and the agent uses no extra turn.

- The name of the new folder is `densepack-stage-` followed by random characters.
- Each pack gets a new folder, and for that reason two files with the same name in different folders never share a copy. When two agents read the same file at the same time, they also get different folders.
- DensePack puts the copy outside the project because a copy inside the project shows in the Grep and Glob results of the agent while the pack runs.
- DensePack deletes the copy and its folder when the pack ends.
- At session start, `bootstrap.py` deletes the `densepack-stage-` folders that are older than one hour.

### `instruction-images/`

This folder holds the images of the `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` of the project. The images of your `~/.claude/CLAUDE.md` and of the memory index `MEMORY.md` are in `~/.claude/densepack-state/instruction-images/`. See [HOW-IT-WORKS.md](HOW-IT-WORKS.md#what-densepack-changes) for that conversion.

`/mdpack <folder>` converts the `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` of another folder.

- It writes their images to the `instruction-images/` folder in the vault of that folder and writes a `.gitignore` in that vault.
- `/dense-remove` restores these files and deletes their images.
- `/dense-remove` deletes the vault of that folder only when a conversation file in `~/.claude/projects/` names the folder. Otherwise the vault and its `.gitignore` stay, and you can delete them by hand.

### Conversation folders

DensePack keeps a copy of each packed report and brief in a folder that has the session id as its name.

- When DensePack has no session id, it uses the folder `no-session-id/`.
- These copies stay when you or DensePack clean `.claude/tmp/`.
- Each copy holds the images, the source text and its `.seal` file. It also holds the code file and the legend when the pack made them.
- When a pack of a subagent report saves too little, DensePack keeps the report as text in `densepack-reply-<agent id>.txt` in `.claude/tmp/` and in the vault.

When the conversation folders together hold more than 200 MB, DensePack deletes files in this order.

1. DensePack deletes the oldest conversation folders first. It deletes only folders with a session id or `no-session-id` as the name.
2. When the conversation folders still hold more than 200 MB, DensePack deletes the oldest files of the newest folder.

DensePack never deletes the newest conversation folder, `images/`, `to-pack/`, `not-converted/`, `instruction-images/`, a folder from an older version or a folder that you make. Set the `vault_mb` value in `densepack-settings.json` to change the 200 MB limit.

### `.gitignore`

DensePack writes a `.gitignore` file in the vault and in `.claude/tmp/`. The file holds one line, `*`, and for that reason Git commits nothing from these folders. The files in them are useful only on this computer.

### Vault cleanup

At session start, `bootstrap.py` deletes all files older than 24 hours in `images/`, `drops/` and `drop-gate/`.

- The `drops/` and `drop-gate/` folders come from older versions.
- DensePack packs a file again at the next Read.
- DensePack cannot make the deleted images and text copy of a Bash output again, because it keeps no other copy of that output.
- You can also delete these folders by hand.

<br>

---

<br>

## Files in `.claude/tmp/`

### Lock files

The `densepack-ran-...` files are lock files. They hold the word `ran` and a line end, and they are 5 bytes on Windows and 4 bytes on Linux and macOS.

`hooks.json` names each hook script two times, one time for each shell.

```
exec sh run_hook.sh ... ; powershell -File run_hook.ps1 ... ;
```

Only one of the two runs, and the hooks work with and without Git for Windows.

- In a POSIX shell, `exec` replaces the shell, and the PowerShell part never starts.
- In PowerShell, `exec` is not a command, and the PowerShell part runs.

Claude Code can load the plugin two times, from an install and from `--plugin-dir`, and then each hook runs two times for one event. `run_once.py` prevents the second run, because it creates the lock file with the flags `O_CREAT | O_EXCL`.

- With those flags, the operating system creates the file only when the file does not exist, and only one process can create it.
- The process that creates the file runs the hook script.
- Other processes for the same event find the file and exit.

The file name is `densepack-ran-`, then the session id, then a hash of 12 characters of the event and the script name.

- Each hook makes one file for each tool call.
- One Read runs four hooks, and a session with 40 Reads makes 160 files.
- All sessions of the project write into the same folder.

DensePack deletes these files in two ways.

- `run_once.py` deletes the lock files that are older than one hour in about 1 run in 200.
- `bootstrap.py` deletes the lock files that are older than one hour at session start.

You can delete these files by hand.

### Other files

| File | What it holds |
| --- | --- |
| `densepack-lead-session` | It holds the id of the session that started last. `bootstrap.py` writes it at session start, and `common.py` uses it to find the project folder. |
| `densepack-lead-sessions.json` | It holds the ids of the last main sessions. The hooks use the list to separate main sessions from subagents. |
| `densepack-leadmodel` | It holds the model of each main session as a `{session id: model}` map. DensePack uses a map because one project can be open in two windows at the same time. |
| `densepack-manifest.jsonl` | It holds one row for each pack of a file, of a Bash output of 1,000 characters or more, of a brief and of a subagent report. It also holds one row for each Read that returns the waiting report images, each report swap that missed and each command that reads packed text with `DENSEPACK_SOURCE_OK`. Bash output of 400 to 999 characters packs as one small image and gets no row. Subagent reports that stay text also get a row with the reason. Each row has a seal hash. The row of a pack also holds the character count, the text tokens and the image tokens, and the rows of files, Bash output and reports also hold the model. |
| `densepack-settings.json` | It holds the settings that the slash commands and `dpctl.py` write. These settings apply to each session in this project folder, and each hook reads the file again when it runs. |
| `densepack-packing-<hash>` | DensePack writes this file while it packs a file. Other Reads of the same file wait and do not pack the file again. DensePack deletes this file when the pack ends, or when it is older than 300 seconds. |
| `densepack-off-<session id>` | It is the off switch of one window. `/dense-off` writes it, and `/densepack` deletes it. |
| `densepack-queue.jsonl` | It holds the rows of the savings table that `pointer.py` did not show yet. |
| `densepack-pending.jsonl` and `densepack-delivered.json` | The first file holds the images of packed reports, and the second holds the images that a Read already returned. |
| `densepack-instructions-note.txt`, `densepack-instructions-lock` and `densepack-instructions-job-<pid>.json` | The background pack of the instruction files writes these files at session start. The note holds the names of the converted files, and the next session start shows it and deletes it. |
| `densepack-delegation.jsonl` and `densepack-card-<session>.jsonl` | They hold one row for each Agent call. |
| `densepack-agentmodel-agent-<id>` | It holds the model of one subagent. |
| `densepack-lifecycle.jsonl` | It gets one row when a subagent ends or when the lead stops it. |
| `densepack-totals.json` | It holds the totals of the reports and briefs of this conversation. |
| `densepack-receipt-last.md` and `densepack-receipt-owed.json` | The first file holds the last savings table in quiet mode, and the second holds the turn that owes a table. |
| `densepack-rule-<name>` | DensePack writes this file when the lead gets one rule, such as the rule for the savings table. DensePack does not send that rule again while this file exists. |
| `densepack-cap-<key>` | DensePack writes this file after a one-time step, such as the note that names the images of a file. DensePack does not run that step again while this file exists. |
| `densepack-dropread-<session>-<hash>` | DensePack writes this file when the pack of a file fails in this session. The agent then gets the text, and DensePack tries the pack again at the next Read of the file. |
| `densepack-word-<12 hex>.docx` or `.doc` | DensePack copies a Word file here and packs this copy. It does this when your message or a tool result names the Word file, or when the Word file is in a folder that your message names. The 12 hex characters come from a hash of the path of the Word file. |
| `densepack-reply-<agent id>.txt` | DensePack writes the subagent report to this file when a pack saves too little and the report stays text. |
| `densepack-report-swap-<agent id>.json` and `densepack-report-background-<agent id>` | The first file holds the line that replaces the report of a subagent in the Agent result, and the second file marks a background subagent. |
| `densepack-sourcewhy-<session>` | DensePack writes this file after `source_gate.py` sends the reason for a blocked command in this session. Only `/dense-remove` deletes it. |
| `densepack-rangeonce-<session>-<hash>` | DensePack writes this file after `source_gate.py` checks one `sed -n` range of this report or brief text in this session. Later ranges of the same text run as written. Only `/dense-remove` deletes it. |

At session start, `bootstrap.py` deletes the files in this folder that are older than 24 hours and whose names start with these parts.

- The image, source, report, code and legend files start with `densepack-img-`, `densepack-src-`, `densepack-report-`, `densepack-code-` and `densepack-legend-`.
- The brief files start with `densepack-brief-`, `densepack-briefsrc-` and `densepack-briefcode-`.
- The Bash files start with `densepack-bash-`, `densepack-bashsrc-` and `densepack-bashout-`, and the marker files start with `densepack-card-sent`, `densepack-start-` and `densepack-readonce-`.

`bootstrap.py` also deletes these files at session start, and it deletes no other file here.

- It deletes the `densepack-ran-` files that are older than one hour.
- It deletes the `densepack-blocked-`, `densepack-asked-` and `densepack-floorpass-` flags of all ages.
- It deletes the symbolic links and junctions in this folder, even when DensePack is off.

`session_end.py` deletes `densepack-totals.json` at the end of a conversation that packed a report or a brief.

### Model names

Models that get images all get the same image, with characters 17 px in size. `CODE_PX` in `plugin/scripts/common.py` sets that size, and the environment variable `DENSEPACK_CODE_PX` can change it.

DensePack uses the model name for these things.

- Fable, Opus and Sonnet get images.
- Haiku and all other models get the files that they Read, their command output, their briefs and the reports that they receive as plain text. Haiku 4.5 with no earlier context read 1 of 10 packed reports correctly.
- Some Word files get images for all models when the images cost less than the text. These are the Word files that your message names, the Word files in a folder that your message names by its full path, and the Word files that a Glob, Grep, Bash or LS result names.
- Main sessions whose model DensePack does not know get text. DensePack reads the newest model from the transcript. Claude Code writes the model there before the first tool call and after a `/model` change. Subagents whose model DensePack cannot find get the files that they read and their Bash output as text.
- `/maxpack` and `/max-off` apply to Sonnet only. DensePack checks the model name to find Sonnet.
- Only Sonnet has a limit on the files of one turn. See the note at the end of this file.
- `report_pack_worth()` in `common.py` uses the dollar rates of the lead model, and for a background subagent also the rates of the subagent model, to decide whether a report packs.
- The manifest row of each file and each report records the model.

<br>

---

<br>

## Files outside the project

| File or folder | What it holds |
| --- | --- |
| `~/.claude/densepack-cards/` | This version writes nothing here because the plugin has no `instructions` folder. Session start deletes the folders here that no session used for 7 days. |
| `~/.claude/densepack-state/` | It holds the key that seals the image records and the queue records. It also holds the list of converted instruction files and the images of your own `CLAUDE.md` and memory index. The files `python-path` and `python-path-win` hold the path of the Python that the hooks start. Session start writes each path first to a part file, such as `python-path.<number>`, and then renames the part file. When the rename fails, the part file stays here, and you can delete it. The plugin writes no style file. When you write a style file here, `projects/<hash>/style.json`, DensePack reads it and uses it in place of the default settings. The images then differ from the images in [BENCHMARKS.md](BENCHMARKS.md). |
| `~/.claude/plugins/data/densepack-densepack-marketplace/`, the data folder of the plugin | It holds the savings table of the last session in `projects/<hash>/`. It holds Pillow, freetype-py and NumPy in `pylibs/` when your Python does not have them, and the hooks and the slash commands load them from there. It holds the file `python-install-tried` when session start found no Python 3.10 or newer. On Windows, this file stops a second winget install, and when you delete it, the next session start tries winget again. On macOS and Linux, when you delete it, the next session start shows the install command again. Without this folder, the savings table goes to `~/.claude/densepack-state/projects/<hash>/`, and `python-install-tried` goes to `~/.densepack/` or `%LOCALAPPDATA%\densepack\`. |
| `~/.claude/settings.json` | It holds `CLAUDE_CODE_THRIFTY_SONIC` set to `0` in the `env` block. Session start adds this value when the `env` block does not have it, and it does not change values that you set. The value stops the message that tells Claude to read files with Bash in auto mode and `bypassPermissions` mode. |
| `~/.claude/CLAUDE.md` and the `MEMORY.md` of each project in `~/.claude/projects/` | When DensePack converts the file, it replaces the file with a pointer to the images and keeps the original text beside it in `<name>.densepack.bak`. DensePack renames an older `.bak` to `<name>.densepack.bak.old-N`. |
| `~/.claude/plugins/cache/densepack-marketplace/densepack/<version>/` | It holds the plugin. |
| Your system temp folder | It holds the copy of a file for a Read in a `densepack-stage-*` folder. It also holds the work folders `densepack-bashimg-*`, `densepack-bashsmall-*`, `densepack-plan-*`, `densepack-widths-*` and `densepack-warm-*`, and the job files `densepack-pack-*`, `densepack-plan-*`, `densepack-trial-*` and `densepack-prepack-*`. Each pack deletes its folders when it ends and its job file when it reads it. Session start deletes the `densepack-stage-*` folders that are older than one hour. |

<sub>Run `/dense-remove` before you uninstall. The command makes these changes.</sub>

- <sub>It restores the original text of each converted `CLAUDE.md`, `CLAUDE.local.md` and `MEMORY.md`.</sub>
- <sub>It deletes `~/.claude/densepack-cards/`, `~/.claude/densepack-state/`, and the vault and the `densepack-` and `.densepack-` files in `.claude/tmp/` of each project folder that a conversation file in `~/.claude/projects/` names.</sub>
- <sub>It also deletes `~/.densepack`, the `python-install-tried` file in `%LOCALAPPDATA%\densepack` and the `densepack-trial-*.pkl` files in your temp folder.</sub>
- <sub>It deletes `~/.claude/densepack-tracker.json`, which only versions before DensePack 1.0 wrote.</sub>
- <sub>It removes `CLAUDE_CODE_THRIFTY_SONIC` from `~/.claude/settings.json` when its value is `0`.</sub>
- <sub>It removes the trust entry of the marketplace folder from `~/.claude.json`. Claude Code writes that trust entry, not DensePack.</sub>

<sub>The hooks of the same session can write a few more files after the command runs, such as `densepack-ran-` files in `.claude/tmp/` and an image of the printed list in `.claude/densepack-vault/images/`, and you can delete them by hand. Then run `/plugin uninstall densepack` and `/plugin marketplace remove densepack-marketplace`. The uninstall deletes the plugin and its data folder.</sub>

<br>

---

<br>

## Actions and results

| What you do | What DensePack does |
| --- | --- |
| You Read a file of 1,000 bytes or more | The file arrives as images when the images and the note cost less than the text. When the file needs more than one image, the result holds image 1, and a note names the others. Reads with a `limit` of 20 lines or fewer stay text. |
| You run a command that prints 400 characters or more | The output arrives as images when the images and the exact lines cost less than the text. The result holds the first image, and a note names the others. DensePack puts some lines beside the image as exact text. These are lines with a `git --stat` bar, a `pip list` rule, a number of 18 or more digits or a random ID with a capital I or a small l. Lines of only spaces or tabs, and lines with a tab inside the line, also go beside the image. The tab after a line number does not count. Only the output of the Bash tool packs, and the output of the PowerShell tool stays text. |
| You run a command that prints the text of a packed report or brief in `.claude/tmp/` | The command prints a line that names the image in place of the text. The command runs as written when it prints one line with `sed -n 'Np'`, when it is the second or a later `sed -n 'N,Mp'` range of the same file in this session, or when it holds the word `DENSEPACK_SOURCE_OK`. DensePack does not change commands that print the text copy of a Bash output in the vault. |
| You start a subagent with a brief of 1,000 characters or more | The subagent gets a line that names an image of the brief, and it Reads that image. This happens only when the subagent gets images, code blocks fill half of the brief or less, and the saving pays for the extra Read. |
| Subagents start | `subagent_start.py` sends each subagent the session start note. It sends no note when DensePack knows that the subagent gets text, such as Sonnet after `/max-off`. Haiku subagents get the note too, but their Reads, their Bash output and their brief stay text. |
| Subagents finish their report | The report arrives as an image only when the lead gets images, code blocks fill half of the report or less, and `report_pack_worth()` calculates that the image saves more than the extra Read of the lead costs. Claude Code cannot put an image in the result of the Agent tool, and for that reason the lead gets a line that names the image and then Reads the image. For a background subagent, DensePack also asks the subagent one time to reply with only the line that names the report file, and the saving must pay for that extra turn too. Otherwise the report arrives as text. |
| You Edit a file that arrived as an image | The Edit works. |
| You Write a file that arrived as an image | The Write works. |
| You Edit or Write a Word file | Edit and Write fail, and only a shell command can change a Word file. |
| You Edit with an `old_string` that the file does not hold | The Edit fails, and the message quotes the closest lines of the file with each space and tab shown. When no line is close, the message tells the agent to Read the file again. |
| You Edit with an `old_string` that the file holds more than one time, without `replace_all` | The Edit fails, and the message names up to 3 lines where a copy starts. |
| You Grep a file that a Read packs, or a folder that holds such a file, with a pattern that prints each line | The Grep fails, and the message names a file to Read. The Grep runs as written when it has a `head_limit` of 20 or fewer or when it uses the `files_with_matches` or `count` mode. It also runs as written when its pattern matches no empty line and does not match at least one of the characters space, `a`, `Z`, `0`, `_`, `(`, `}` and `#`. |
| You Glob a DensePack text file that has an image, in `.claude/tmp/` or the vault | The Glob fails, and the message names the image. |

> [!IMPORTANT]
> In Claude Code 2.1.284, an Edit works with no Read of the file. In a test without DensePack,
> Edit worked after `cat` 3 times and after `grep | head` one time. With DensePack, a Read runs
> on the real file, and the hook replaces the result with the image after the Read runs. Edit and
> Write work on that file.
>
> Edit and Write do not work on Word files. The Read tool of Claude Code does not open `.doc`
> and `.docx` files, because they are binary containers and not text. See [Word files](HOW-IT-WORKS.md#word-files).

DensePack never packs these Reads.

- Images, PDFs and notebooks do not pack because Claude Code reads them as images or as structured cells.
- Files in a `.claude` folder and files in the scratchpad folder of Claude Code do not pack. Those folders hold working files.
- Files below 1,000 bytes do not pack because the pack takes time and memory and saves only a few tokens. The pack of a 483-byte file took 2.5 seconds and 469 MB of memory to save 10 tokens.
- Files over 1,000,000 bytes do not pack because the wait at the first Read grows with the size of the file. The pack of a file of about 300,000 bytes took 14 to 17 seconds.
- Files with a null byte do not pack because those files are not text.
- Files do not pack when the Inter font has no character shape for more than 2% of the characters that are not spaces, such as Chinese, Japanese or Korean text.
- Reads with a `limit` of 20 lines or fewer do not pack, and the agent gets those lines as text.
- Reads do not pack for agents that get text, such as Haiku, Sonnet after `/max-off` or subagents whose model DensePack cannot find.
- Reads do not pack when Pillow, freetype-py or NumPy is missing.
- Files do not pack when their images and note do not cost less than their text.

<sub>One rule applies to Sonnet only. When one Sonnet turn asks for more than 32 files, or for more than 700,000 bytes of files, DensePack sends text. Opus and Fable have no such limit.</sub>
