<!-- DensePack 1.1 -->
# DensePack folders and files

This file lists all folders and working files that the DensePack plugin writes. It says what each one contains and when the plugin writes it.

DensePack writes in three places:

| Place | What it contains |
| --- | --- |
| `<project>/.claude/densepack-vault/` | The images of the files the agent reads and the copies DensePack keeps |
| `<project>/.claude/tmp/` | Working files for the current sessions |
| `~/.claude/densepack-state/` and `~/.claude/densepack-cards/` | Files that all projects use |

DensePack saves all of these files on your computer. It sends none of them to a service.

---

## Folders in `.claude/densepack-vault/`

### `images/`

This folder contains the images of the files the agent read.

DensePack converts a file into images one character at a time. That takes time. DensePack saves the images here. Then it converts each file one time only.

Each set of images has a `.json` file. The `.json` file contains a digest of the source text. A digest is a short hash. The same text always gives the same digest.

At the next Read of the same file, DensePack compares the digest. When the digest is the same, DensePack gives the agent the saved images. When you change the file, the digest changes. Then DensePack converts the file again.

### `to-draw/`

You copy a file into this folder to convert it without a Read.

DensePack converts a file when the agent reads it. This folder lets you convert a file yourself.

DensePack converts the file at the next tool call the agent makes. It does not convert the file when you copy it or when you send a message. The reason is that `pointer.py` runs on the `PostToolUse` event. That event is after each tool call. One of its steps is to look in `to-draw/`.

To convert a file, `pointer.py` first renames it in the same folder to `.densepack-claim-<epoch>-<8 hex>-<name>`. Two sessions can look in the folder at the same time. Only one rename succeeds. Thus only one session converts the file.

`pointer.py` also converts a file that is in `drop/`. An older version used that folder.

### `not-converted/`

`pointer.py` moves a file from `to-draw/` into this folder when it cannot convert the file.

### `drop-gate/`

This folder contains the copy of a file that DensePack converts during a Read.

When a Read arrives and the file has no image in `images/`, the hook `drop_read_gate.py` does three things. It copies the file into a new subfolder of `drop-gate/`. It converts the copy. It changes the Read to give the agent the image. All three steps run inside the same hook, before the Read returns. The agent uses no extra turn.

The name of the subfolder is the first 12 characters of a hash of the file path, then the process id. Two files with the same name in different folders get different subfolders. Two agents that read the same file at the same time also get different subfolders.

`pointer.py` does not look in `drop-gate/`. It never converts these copies a second time.

### `instruction-images/`

This folder contains the images of the project's `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md` and `MEMORY.md`. [HOW-IT-WORKS.md](HOW-IT-WORKS.md#what-densepack-changes) explains that conversion.

### One folder for each conversation

DensePack keeps a copy of each converted report, brief and command output in a folder that has the session id as its name. These copies stay when you or DensePack clean `.claude/tmp/`. When the vault is larger than 200 MB, DensePack deletes the oldest of these folders first.

### `unknown-conversation/`

DensePack uses this folder when it cannot find the session id.

A hook receives the session id from Claude Code. `bash_pack.py` is not a hook. A wrapped shell command runs it. It receives no session id. At session start the plugin writes the session id to the file `.claude/tmp/densepack-lead-session`. `bash_pack.py` reads the id from that file.

When that file is missing, `bash_pack.py` saves the copy in `unknown-conversation/`. The file is missing when you or DensePack cleaned `.claude/tmp/`, or when a bench folder never ran the session start hook. The image is correct. Only the folder name is different.

### `.gitignore`

DensePack writes a `.gitignore` file in the vault and in `.claude/tmp/`. The file contains one line, `*`. Git commits nothing from these folders. The files in them are useful only on this computer.

### Cleanup of the vault

At session start, `bootstrap.py` deletes all files older than 24 hours in `images/`, `drops/` and `drop-gate/`. `drops/` is a folder that an older version used. DensePack converts a file again at the next Read. You lose nothing. You can also delete these folders by hand.

---

## Files in `.claude/tmp/`

### The `densepack-ran-...` files

Each of these files is a lock. It contains the word `ran` and a line end. That is 5 bytes on Windows and 4 bytes on Linux and macOS.

`hooks.json` names each hook script two times, one time for each shell:

```
exec sh run_hook.sh ... ; powershell -File run_hook.ps1 ... ;
```

Only one of the two runs. In a POSIX shell, `exec` replaces the shell. The PowerShell part never starts. In PowerShell, `exec` is not a command. The PowerShell part runs. The hook works with Git for Windows and without it.

Claude Code can load the plugin two times, from an install and from `--plugin-dir`. Then each hook runs two times for one event.

`run_once.py` prevents the second run. It creates the lock file with the flags `O_CREAT | O_EXCL`. With those flags the operating system creates the file only when the file does not exist. Only one process can create the file. The process that creates the file runs the hook script. A second process for the same event finds the file and exits.

The file name is `densepack-ran-`, then the session id, then a 12 character hash of the event and the script name. Each hook makes one file for each tool call. One Read runs three hooks. A session with 40 Reads makes 120 files. All sessions of the project write into the same folder.

DensePack deletes these files in two ways:

- About 1 run in 200 of `run_once.py` deletes the lock files that are older than one hour.
- `bootstrap.py` deletes the lock files that are older than one hour at session start.

You can delete these files by hand.

### The other files

| File | What it contains |
| --- | --- |
| `densepack-lead-session` | The id of the session that started last. `bootstrap.py` writes it at session start. `bash_pack.py` reads the id from this file because Claude Code gives the session id only to hooks. `common.py` also uses this file to find the project folder |
| `densepack-lead-sessions.json` | The ids of the last main sessions. A hook uses the list to tell a main session from a subagent |
| `densepack-leadmodel` | The model of each main session, as a `{session id: model}` map. It is a map because one project can be open in two windows at the same time |
| `densepack-manifest.jsonl` | One row for each conversion. A row has the character count, the text tokens, the image tokens and a seal hash |
| `densepack-settings.json` | The settings that the slash commands write |

`bootstrap.py` deletes the other working files in this folder when they are older than 24 hours.

### Why DensePack records the model

All models get the same image size. `CODE_PX` in `plugin/scripts/common.py` sets that size. It is 17 px unless the environment variable `DENSEPACK_CODE_PX` contains another number.

DensePack uses the model name for three things:

1. Haiku always gets plain text because Haiku does not read text on images accurately.
2. `/maxpack` and `/max-off` apply to Sonnet only. DensePack must know when the reader is Sonnet.
3. Each manifest row records the model, for example `"drawn_model": "opus"`.

---

## Files and folders outside the project

| File or folder | What it contains |
| --- | --- |
| `~/.claude/densepack-cards/` | Images that the plugin uses again in each session |
| `~/.claude/densepack-state/`, or the plugin's data folder | The savings table of the last session, the style file, the key that seals image records and queue records, the list of converted instruction files and the images of your user `CLAUDE.md` and memory index |
| `~/.claude/plugins/cache/densepack-marketplace/densepack/<version>/` | The plugin |

<sub>Run `/dense-remove` before you uninstall. It deletes `~/.claude/densepack-cards/`, `~/.claude/densepack-state/` and the vault of each project. `/plugin uninstall densepack` deletes the plugin.</sub>

---

## What DensePack does for each action

| What you do | What DensePack does |
| --- | --- |
| You Read a file over 1,000 bytes | The file arrives as one or more images |
| You run a command that prints over 5,000 characters | The output arrives as an image when the image saves more than the extra turn costs |
| You start a subagent with a brief over 1,000 characters | The brief arrives as an image, before the subagent starts |
| A subagent finishes its report | The report arrives as an image |
| You Edit a file that arrived as an image | The Edit works |
| You Write a file that arrived as an image | The Write works |
| You Edit or Write a Word file | Edit and Write fail. Only a shell command can change a Word file |

> [!IMPORTANT]
> Edit and Write check one thing: whether this session called Read on this exact path.
> Claude Code records that when the agent calls Read. The record is the same for text and for an
> image. Claude Code records a file that DensePack replaced with an image as read. Edit and Write work on that file.
>
> A Word file is the one exception. The image is not the reason. Claude Code's
> Read does not open a `.doc` or `.docx` file. Claude Code never records the path as
> read. Edit and Write do not work on it. See [Word files](HOW-IT-WORKS.md#word-files).

DensePack never converts these Reads:

- Images, PDFs and notebooks. Claude Code reads them as images or as structured cells.
- A file in a `.claude` folder, or in a folder named `sandbox` or `scratch`. Those folders contain working files and DensePack's own images.
- A file below 1,000 bytes because the image does not save tokens.
- A file over 500,000 bytes or over 6,000 lines because the conversion takes too long.
- A file that contains a null byte because that file is not text.

<sub>One rule applies to Sonnet only. When one Sonnet turn asks for more than 32 files, or for more than 700,000 bytes of files, DensePack sends text. Opus and Fable have no such limit.</sub>
