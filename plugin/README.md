# DensePack Plugin

The plugin packs what a Claude Code conversation carries anyway,
agent reports, agent briefs, Bash output, file reads and rules pages,
into pictures that cost fewer tokens than the text, with nothing
typed. The plugin prices every pack first, and text that would cost
less as text passes through unchanged.

## Install

The same two commands in Claude Code install the plugin on Windows,
Linux and macOS.

```
/plugin marketplace add Fabian-Galvez/DensePack
/plugin install densepack@densepack-marketplace
```

The first run installs Python and Pillow if they are missing, on
Windows through winget and on macOS through Homebrew. On Linux the
install needs sudo, so the first run prints the one command to run.
`/plugin uninstall densepack` removes it.

## The hook events

| Hook | Job |
| --- | --- |
| SessionStart | Installs Pillow, briefs the lead model, shows last conversation's totals, and warns when the drawing size does not match the model |
| SessionEnd | Files the conversation totals for the next session start to show |
| SubagentStart | Tells every subagent the report shape: final message is the report, summary on top, findings after |
| SubagentStop | Packs each finished agent's report into a PNG when the PNG costs less, and records it |
| PreToolUse | Packs an outgoing agent brief at the size the receiving model reads |
| PostToolUse | Packs long Bash output and file reads, and prints the savings receipt |
| UserPromptSubmit | Carries the rules pages as one picture instead of text on every message |
| Stop | Holds an unfinished turn to its open work |

## The commands

`/setpack` reaches every setting and `/helppack` prints every command
with what it sets.

| Group | Commands | Job |
| --- | --- | --- |
| Packing | `/densepack`, `/densepack-off`, `/dpack` | Turns every hook on or off and resets every setting to default |
| Type size | `/opuspack`, `/fablepack` | 10 px for an Opus 5 lead, 8 px for a Fable 5 lead. The plugin reads the lead's model on its own |
| Receipts | `/quietpack` | Whether the savings table prints in the reply. The numbers stay on the dashboard either way |
| Delegation | `/agentpack`, `/agentpack-off`, `/maxpack` | Whether DensePack's delegation rules win, and whether an Opus 5 lead may spawn Fable 5 workers |
| Writing rules | `/stylepack`, `/stylepack-off` | Whether the writing rules ride with each message |
| Any setting | `/setpack`, `/helppack` | Sets one option to one value, and prints the table of options |
| Self-check | `/tune` | Counts what this session's records show and names the command that fixes each count |

## What it packs

| Surface | How |
| --- | --- |
| Agent reports | Each finished agent's report arrives as one picture at the size the lead's model reads |
| Agent briefs | Each outgoing brief goes out as one picture at the size the receiving agent's model reads |
| Bash output | Long command output lands as a picture, and the exact bytes stay in a .txt beside it |
| Grep results and file reads | Long results land the same way, picture plus exact .txt |
| Rules pages | A rules page rides on the message once as a picture instead of as text every message |
| Code, diffs, ids, hashes, exact values | Never packed. Exact text stays text |

## How a pack works

Text costs about 1 token per 2.40 characters. An image costs 1 token
per 28 by 28 pixel patch. The plugin draws the text at the smallest
size the reading model reads exactly: 8 px for Fable 5, 10 px for
Opus 5, 12 px for Sonnet 5. A model without a measured size gets
text, Haiku always gets text, and the plugin refuses and logs any
pack that would cost more than its text. An id, a hash, a file name
or a comma grouped number never enters a picture; the exact value
travels as text beside it, and every picture's exact source text
stays in a .txt file the reader can quote byte for byte.

## The files

[PARTS.md](PARTS.md) lists every file in this folder with its job.
[BRIEFING.md](BRIEFING.md) is the working brief the plugin draws for
the lead model each session.
