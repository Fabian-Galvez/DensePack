<!-- DensePack 2.0 -->
# DensePack folders and files

DensePack writes files in these places.

| Place                                                                                                          | What it contains                                                                                                                    |
| -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `<project>/.claude/densepack-vault/`                                                                           | It contains the images of the files and Bash output that the agent reads. It also contains copies of the packed reports and briefs. |
| `<project>/.claude/tmp/`                                                                                       | It contains the working files of the current sessions.                                                                              |
| `~/.claude/densepack-state/` and the data folder of the plugin                                                 | They contain files outside the project, such as the seal key and the savings table of the last session.                             |
| Your system temp folder                                                                                        | It contains a copy of each file while DensePack packs it. The packs also write their job files here.                                |
| The `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`, `.claude/rules/*.md` and `MEMORY.md` files that DensePack converts | DensePack replaces the file with a pointer to the images and keeps the original text beside it in `<name>.bakpack`.                 |
| `~/.claude/settings.json`                                                                                      | DensePack sets `CLAUDE_CODE_THRIFTY_SONIC` to `0` in this file. On Windows with Git for Windows, it also sets `EMBEDDED_SEARCH_TOOLS` to `1` and `CLAUDE_CODE_USE_POWERSHELL_TOOL` to `0`. |
| `~/.claude/densepack-text-files.txt`                                                                           | You write this file. Reads of files that match one of its patterns, one per line such as `*.kt`, stay text in every project |

DensePack saves all of these files on your computer and sends none of them to a service.

<br>

---

<br>

## Folders in `.claude/densepack-vault/`

### `images/`

This folder contains the images that DensePack makes.

- Files that the agent reads have their images here.
- Files in a folder that your message names also have their images here. DensePack packs them in the background before the agent reads them. [What are the limits?](HOW-IT-WORKS.md#the-limits) gives the size limits of this step.
- Word files have their images here too. See [Word file packing](HOW-IT-WORKS.md#word-file-packing) for when DensePack packs them.
- Bash output that DensePack packs has its images here.

DensePack saves the images of whole files here, which lets the next Read of the same file skip that pack. The times of a pack are in [Pack times](HOW-IT-WORKS.md#pack-times).

Image names follow these rules.

- Image names start with the folder of the file in the project and the file name. For example, `src/README.md` gets `src-README.md-image-1-of-2-DensePack.png`. Hyphens and other signs inside a folder or file name become `_`, so `HOW-IT-WORKS.md` gets `HOW_IT_WORKS.md-image-1-of-10-DensePack.png`.
- The file `<name>-claim-DensePack.txt` beside the images contains the full path of the source file.
- When a second file gets the same image name, its images get `~2`, `~3` and so on, up to `~50`. After `~50`, the name gets `~` and 8 hex characters of a hash of the path.

The images of a whole file also get a `.json` file, `<name>-images-DensePack.json`, that contains a digest and a seal.

- The digest is a short hash of the file and the plugin version. The same text and the same plugin version always give the same digest.
- Cloned projects cannot make a valid seal because the seal uses a key in `~/.claude/densepack-state/`.
- At the next Read of the same file, DensePack compares the digest and checks the seal. When the two match, DensePack gives the agent the saved images.
- Changes to the file and new DensePack versions change the digest. DensePack then packs the file again at the next Read.

Reads of part of a file, with an `offset` or a `limit`, get images of only those lines.

- The names of these images contain the line range, for example `src-app.py-lines-40-120-image-1-of-1-DensePack.png`.
- These images have no `.json` file.

Word files (`.doc` or `.docx`) also get a text copy here.

- The text copy has the same text as the images, one line for each paragraph, list item and table row. The agent can Grep it for an exact string.
- The name of the text copy starts with `.claude-tmp-`, because DensePack packs a copy of the Word file in `.claude/tmp/`. One such name is `.claude-tmp-densepack_word_<12 hex>.docx.txt`.
- The 12 hex characters are a hash of the file path. When a later message or tool result names the same Word file, DensePack reuses its images.
- The images take the name of the text copy, with `-image-N-of-M-DensePack.png` added.
- The key row of each image shows the name of the text copy after `file=`.
- Only Word files that you copy into `to-pack/` get a text copy with their own name, such as `report.docx.txt`. See the `to-pack/packed/` section below.

Bash output that DensePack packs also gets a text copy here, `bash-output-<id>.txt`, beside its image.

### `to-pack/`

Copy a file into this folder to pack it without a Read.

DensePack packs the file at the next tool call of the agent.

- `pointer.py` checks `to-pack/` after each tool call, so files you copy in pack at the next tool call.
- One tool call packs one file from `to-pack/`, so 5 files take 5 tool calls. Parallel tool calls pack different files at the same time.
- To pack a file, `pointer.py` first renames it in the same folder to `.densepack-claim-<epoch>-<8 hex>-<name>`. Only one rename can succeed, which lets only one session or parallel tool call pack the file.
- Claims older than 30 minutes get their old names back at the next tool call.
- `pointer.py` also packs files in `drop/`, a folder of an older version.
- `pointer.py` does not scan `to-draw/`, the name of this folder in DensePack 1.1. Move those files into `to-pack/` to pack them.

### `to-pack/packed/`

DensePack makes this folder at session start.

- `pointer.py` moves each packed file from `to-pack/` into this folder and puts its images beside it.
- DensePack does not delete the files in `packed/` and does not pack them again.
- Files in a subfolder of `to-pack/` keep that subfolder here.
- The image names start with the file name. For example, `notes.md` gets the images `notes.md-image-1-of-1-DensePack.png`.
- New files never replace older files of the same name in `packed/`. They get `~2` or `~3` before their extension, such as `notes~2.md`.
- Word files also get a text copy, such as `report.docx.txt`. The agent can Grep the text copy for an exact string that is hard to read from an image.
- The image names start with the name of the text copy, which also appears after `file=` in each key row.
- The message after the tool call gives the image name and the new path of the file.

### `not-converted/`

`pointer.py` moves a file from `to-pack/` into this folder when it cannot pack the file. When that move fails too, the file stays in one of these places, which the `to-pack/` scan skips.

- The file stays in `to-pack/packed/` if the pack failed.
- The file stays in `to-pack/` as `.densepack-failed-<name>` if the move into `packed/` failed.

### `drop-gate/`

Older versions kept the copy of a file for a Read in this folder. This version writes nothing here and only deletes what older versions left. At session start, `bootstrap.py` deletes the files here that are older than 7 days. It also deletes the empty subfolders that are older than one hour.

### Read copies

When a Read ends and the file has no image in `images/`, DensePack makes the image in these steps.

1. The hook `read_image.py` calls `drop_read_gate.py` to get the image.
2. `drop_read_gate.py` packs a copy of the file in your system temp folder and writes the images into `images/`.
3. `read_image.py` puts the images in the Read result.

The agent uses no extra turn, because these steps run inside the same tool call.

- The name of the new folder is `densepack-stage-` followed by random characters.
- Two files with the same name in different folders never share a copy, because each pack gets a new folder. When two agents read the same file at the same time, they also get different folders.
- DensePack puts the copy outside the project, which keeps it out of the agent's Grep and Glob results.
- DensePack deletes the copy and its folder when the pack ends.
- At session start, `bootstrap.py` deletes the `densepack-stage-` folders that are older than one hour.

### `instruction-images/`

This folder contains the images of the `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md` and `.claude/rules/*.md` of the project. The images of your `~/.claude/CLAUDE.md` and of the memory index `MEMORY.md` are in `~/.claude/densepack-state/instruction-images/`. See [HOW-IT-WORKS.md](HOW-IT-WORKS.md#what-densepack-changes) for that conversion.

`/bakpack` converts the `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md` and `.claude/rules/*.md` of this project, or of the folder you name. DensePack converts no file on its own. Claude Code needs `densepack:` before every command, such as `/densepack:bakpack`.

- It writes their images to `instruction-images/` in the vault of that folder. It also writes a `.gitignore` there, so Git does not commit the images.
- `/bak-off [folder]` restores these files and deletes their images for one folder. See [Remove DensePack](INSTALL.md#remove-densepack) for what `/dense-remove` does for all folders.

### `instructions/map/`

DensePack 2.0 draws the project map here at each session start, as `project-map-image-1-of-1-DensePack.png`. The image lists each folder of the project, its source and config files, and the names that each file defines.

The start note names the image, and the agent reads it in its first turn. At every session start, DensePack draws it again, over the old one.

### Conversation folders

DensePack keeps copies of the packed reports and briefs in a folder named after the session id.

- When DensePack has no session id, it uses the folder `no-session-id/`.
- These copies stay when you or DensePack clean `.claude/tmp/`.
- The copies contain the images, the source text and its `.seal` file. They also contain the code file and the legend when the pack made them.
- If the image of a subagent report does not save more than the extra Read costs, the report stays text. DensePack still keeps a copy in `densepack-reply-<agent id>.txt`, in `.claude/tmp/` and in the vault.

When the conversation folders total more than 200 MB, DensePack deletes files in this order.

1. DensePack deletes the oldest conversation folders first. It deletes only folders with a session id or `no-session-id` as the name.
2. When the conversation folders still total more than 200 MB, DensePack deletes the oldest files of the newest folder.

DensePack never deletes the newest conversation folder as a whole, because it contains the conversation in progress. The cleanup also skips `images/`, `to-pack/`, `not-converted/`, `instruction-images/`, `instructions/`, the folders of older versions and folders that you make. Set the `vault_mb` value in `densepack-settings.json` to change the 200 MB limit.

### `why-text.log` and `doctor-test-image.png`

`why-text.log` gets one line for each Read or Bash output that stays text, with the reason, such as an error or the price check. At 512 KB, the log moves to `why-text.old.log`. `/densedoctor` prints its last 10 lines and saves its test image as `doctor-test-image.png`.

### `.gitignore`

DensePack writes a `.gitignore` file in the vault and in `.claude/tmp/`. Git commits nothing from these folders, because the file contains one line, `*`. The files in them are useful only on this computer.

### Vault cleanup

At session start, `bootstrap.py` deletes all files older than 7 days in `images/`, `drops/` and `drop-gate/`.

- The `drops/` and `drop-gate/` folders come from older versions.
- DensePack packs a file again at the next Read.
- DensePack cannot rebuild deleted Bash output images, because it keeps no other copy of the output.
- You can also delete these folders by hand.

<br>

---

<br>

## Files in `.claude/tmp/`

### Lock files

The `densepack-ran-...` files are lock files, which stop a second run of a hook for one event. They contain only the word `ran` and a line end, which is 4 or 5 bytes.

`hooks.json` names each hook script two times, one time for each shell.

```
exec sh run_hook.sh ... ; powershell -File run_hook.ps1 ... ;
```

The hooks work with and without Git for Windows, because only one of the two parts runs.

- In a POSIX shell, the PowerShell part never starts, because `exec` replaces the shell.
- In PowerShell, the PowerShell part runs, because `exec` is not a command there.

Claude Code can load the plugin two times, from an install and from `--plugin-dir`. Then every hook runs two times for one event. `run_once.py` prevents the second run, because it creates the lock file with the flags `O_CREAT | O_EXCL`.

- With those flags, the operating system lets only one process create the file.
- The process that creates the file runs the hook script.
- Other processes for the same event find the file and exit.

The file name is `densepack-ran-`, the session id and a 12-character hash of the event and the script name. The script name keeps the hooks of one event apart, because several hooks get the same event.

- Hooks make one file per hook and tool call. One Read runs four hooks, so a session of 40 Reads makes 160 lock files.
- All sessions of the project write into the same folder.

DensePack deletes these files in two ways.

- `run_once.py` deletes the lock files that are older than one hour in about 1 run in 200.
- `bootstrap.py` deletes the lock files that are older than one hour at session start.

You can delete these files by hand.

### Other files

| File                                                                                                         | What it contains                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `densepack-lead-session`                                                                                     | It contains the id of the session that started last, which `common.py` uses to find the project folder. `bootstrap.py` writes it at session start.                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `densepack-lead-sessions.json`                                                                               | It contains the ids of the last main sessions. The hooks use the list to separate main sessions from subagents.                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `densepack-leadmodel`                                                                                        | It contains the model of each main session as a `{session id: model}` map. DensePack uses a map because one project can be open in two windows at the same time.                                                                                                                                                                                                                                                                                                                                                                                                     |
| `densepack-manifest.jsonl`                                                                                   | It contains one row for each packed file, brief, subagent report and Bash output of 1,000 characters or more. It also logs each Read of waiting report images, each missed report swap and each use of `DENSEPACK_SOURCE_OK`. Bash output of 400 to 999 characters packs as one small image and gets no row. Subagent reports that stay text also get a row with the reason. All rows contain a seal hash. Rows of packs also contain the character count, the text tokens and the image tokens. The rows of files, Bash output and reports also contain the model.    |
| `densepack-settings.json`                                                                                    | It contains the settings that the slash commands and `dpctl.py` write. These settings apply to each session in this project folder. The hooks read the file again when they run, which applies a change at the next tool call.                                                                                                                                                                                                                                                                                                                                       |
| `densepack-packing-<hash>`                                                                                   | DensePack writes this file while it packs a file. Other Reads of the same file wait and do not pack the file again. DensePack deletes this file when the pack ends. If this file is older than 300 seconds, the pack did not finish. The next Read then deletes it and packs the file.                                                                                                                                                                                                                                                                               |
| `densepack-off-<session id>`                                                                                 | `/dense-off` writes this file to stop the hooks in one window only. `/densepack` deletes it, which turns the hooks on again.                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `densepack-queue.jsonl`                                                                                      | It contains the rows of the savings table that `pointer.py` did not show yet.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `densepack-pending.jsonl` and `densepack-delivered.json`                                                     | The first file contains the images of packed reports that no Read has opened yet. The second file lists the images that a Read returned, so the next note names only the waiting images.                                                                                                                                                                                                                                                                                                                                                                             |
| `densepack-instructions-note.txt`, `densepack-instructions-lock` and `densepack-instructions-job-<pid>.json` | The background pack of the instruction files writes these files at session start. The note contains the names of the converted files. The next session start shows the note and deletes it.                                                                                                                                                                                                                                                                                                                                                                          |
| `densepack-delegation.jsonl` and `densepack-card-<session>.jsonl`                                            | They contain one row for each Agent call.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `densepack-agentmodel-agent-<id>`                                                                            | It contains the model of one subagent.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `densepack-lifecycle.jsonl`                                                                                  | It gets one row when a subagent ends or when the main agent (the lead) stops it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `densepack-totals.json`                                                                                      | It contains the totals of the reports and briefs of this conversation.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `densepack-receipt-last.md` and `densepack-receipt-owed.json`                                                | In quiet mode, the first file contains the last savings table in place of a table in the conversation. The second file contains the turn whose table DensePack has not shown yet.                                                                                                                                                                                                                                                                                                                                                                                    |
| `densepack-rule-<name>`                                                                                      | DensePack writes this file when the lead gets one rule, such as the rule for the savings table. DensePack does not send that rule again while this file exists.                                                                                                                                                                                                                                                                                                                                                                                                      |
| `densepack-cap-<key>`                                                                                        | DensePack writes this file after a one-time step, such as the note that names the images of a file. DensePack does not run that step again while this file exists.                                                                                                                                                                                                                                                                                                                                                                                                   |
| `densepack-word-<12 hex>.docx` or `.doc`                                                                     | DensePack copies a Word file here and packs this copy. See [Word file packing](HOW-IT-WORKS.md#word-file-packing) for when. The 12 hex characters come from a hash of the path of the Word file.                                                                                                                                                                                                                                                                                                                                                                     |
| `densepack-reply-<agent id>.txt`                                                                             | DensePack writes the subagent report to this file when the image would not save more than the extra Read costs.                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `densepack-report-swap-<agent id>.json` and `densepack-report-background-<agent id>`                         | The first file contains the line that replaces the report of a foreground subagent in the Agent result. The second file marks a background subagent, which gets one request to reply with that line instead.                                                                                                                                                                                                                                                                                                                                                         |
| `densepack-sourcewhy-<session>`                                                                              | DensePack writes this file after `source_gate.py` sends the reason for a blocked command in this session. Only `/dense-remove` deletes it.                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `densepack-rangeonce-<session>-<hash>`                                                                       | DensePack writes this file after `source_gate.py` checks one `sed -n` range of this report or brief text in this session. Later ranges of the same text run as written. Only `/dense-remove` deletes it.                                                                                                                                                                                                                                                                                                                                                             |

At session start, `bootstrap.py` deletes the files with these names once they are older than 7 days.

`look-alikes.json` and `look-alikes-denied.json` in the same folder stay until you delete them. The first holds up to 500 words with Cyrillic or Greek letters that look like Latin ones, so `grep_gate.py` can put both spellings into a search. The second holds up to 50 searches that `grep_gate.py` denied once in a mode that asks.

- The image, source, report, code and legend files start with `densepack-img-`, `densepack-src-`, `densepack-report-`, `densepack-code-` and `densepack-legend-`.
- The brief files start with `densepack-brief-`, `densepack-briefsrc-` and `densepack-briefcode-`.
- The Bash files start with `densepack-bash-`, `densepack-bashsrc-` and `densepack-bashout-`. The marker files start with `densepack-card-sent`, `densepack-start-` and `densepack-readonce-`.

At session start, `bootstrap.py` also deletes these files and no other file here.

- It deletes the `densepack-ran-` files that are older than one hour.
- It deletes the `densepack-blocked-`, `densepack-asked-` and `densepack-floorpass-` flags of all ages.
- It deletes the symbolic links and junctions in this folder, even when DensePack is off.

`session_end.py` deletes `densepack-totals.json` at the end of a conversation that packed a report or a brief.

<br>

---

<br>

## Files outside the project

| File or folder                                                                           | What it contains                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `~/.claude/densepack-cards/`                                                             | This version writes nothing here because the plugin has no `instructions` folder. Session start deletes the folders here that no session used for 7 days.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `~/.claude/densepack-state/`                                                             | It contains the key that seals the image records and the queue records. It also contains the list of converted instruction files and the images of your own `CLAUDE.md` and memory index. The files `python-path` and `python-path-win` contain the path of the Python that the hooks start. Session start writes each path to a part file, such as `python-path.<number>`. It then renames the part file, which keeps a hook from reading a half-written path. When the rename fails, the part file stays here. You can delete it. The plugin writes no style file. If you write a style file at `projects/<hash>/style.json`, DensePack uses it in place of the default settings. The images then differ from the images in [BENCHMARKS.md](BENCHMARKS.md). |
| `~/.claude/plugins/data/densepack-densepack-marketplace/`, the data folder of the plugin | It contains the savings table of the last session in `projects/<hash>/`. When your Python lacks Pillow, freetype-py or NumPy, session start downloads and installs them in `pylibs/` for the hooks and slash commands. On macOS, the uv install fills `pylibs/` first. It contains the file `python-install-tried` when session start found no Python 3.10 or newer. On Windows, this file stops a second winget install. When you delete it, the next session start runs winget again. On macOS, the file contains the result of the uv install. When you delete it, the next session start runs the uv install again. On macOS, the folder also contains `python/` and `python-install.log`. `python/` is the Python 3.13 that uv installed when session start found no Python 3.10 or newer. The log has the steps of that install. `python-install-running` is there while the install runs. On Linux, when you delete it, the next session start shows the install command again. Without this folder, the savings table goes to `~/.claude/densepack-state/projects/<hash>/`. The file `python-install-tried` goes to `~/.densepack/` or `%LOCALAPPDATA%\densepack\`. On Windows, it also contains `git-install-tried` when session start found no Git Bash and ran the winget install of Git for Windows. That file also goes to `%LOCALAPPDATA%\densepack\` without this folder.                                                |
| `~/.claude/settings.json`                                                                | It contains `CLAUDE_CODE_THRIFTY_SONIC` set to `0` in the `env` block. On Windows with Git for Windows, it also contains `EMBEDDED_SEARCH_TOOLS` set to `1` and `CLAUDE_CODE_USE_POWERSHELL_TOOL` set to `0`. [What DensePack changes](HOW-IT-WORKS.md#what-densepack-changes) gives the reason.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `~/.claude/CLAUDE.md` and the `MEMORY.md` of each project in `~/.claude/projects/`       | DensePack replaces the converted file with a pointer to its images and keeps the original text in `<name>.bakpack`. DensePack renames an older `.bakpack` to `<name>.bakpack.old-N`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `~/.claude/plugins/cache/densepack-marketplace/densepack/<version>/`                     | It contains the plugin.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| Your system temp folder                                                                  | It contains the copy of a file for a Read in a `densepack-stage-*` folder. It also contains the work folders `densepack-bashimg-*`, `densepack-bashsmall-*`, `densepack-plan-*`, `densepack-widths-*` and `densepack-warm-*`. The job files of the packs are `densepack-pack-*`, `densepack-plan-*`, `densepack-trial-*` and `densepack-prepack-*`. The packs delete their folders when they end and their job files when they read them. Session start deletes the `densepack-stage-*` folders that are older than one hour.                                                                                                                                                                                                                                 |

Run `/dense-remove` before you uninstall. [Remove DensePack](INSTALL.md#remove-densepack) lists what the command deletes and what it keeps.

<br>

---

<br>

## Blocked shell reads

DensePack blocks a shell command that prints the text of a packed report or brief in `.claude/tmp/`. The block names the image, because a shell read of that text undoes the saving. In one session, 14 such commands added 20,064 tokens against a saving of 20,014. Commands that print one line with `sed -n 'Np'` still run, because one line keeps the saving of the image. After the first block, later `sed -n 'N,Mp'` ranges of the same file run, because the agent then needs the exact text. Commands with the word `DENSEPACK_SOURCE_OK` also run, which lets you check the images against their source text. DensePack does not block commands that print the text copy of a Bash output in the vault.
