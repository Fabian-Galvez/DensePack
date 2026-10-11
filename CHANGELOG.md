# DensePack changes

<br>

---

<br>

## 2.0

### Rules and the project map

DensePack 2.0 also cuts what the agent writes.

- The start note now contains the rules in [plugin/rules/STYLE-RULES.md](plugin/rules/STYLE-RULES.md): the smallest complete code change, few turns, and short, plain replies. Subagents get the same rules.
- The rules keep private data private. No change may show private data to more people than before, such as one user's email address to other users.
- The start note also names an image of the project map: each folder, its files and the names that each file defines. The agent reads that image in its first turn.
- The start note is about 2,300 tokens, up from 72. [BENCHMARKS.md](BENCHMARKS.md#densepack-20-10-october-2026) has the savings.

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
