---
name: densepack-method
description: Cut input tokens when orchestrating subagents. Activates the DensePack workflow, where long subagent reports arrive as dense packed images the lead reads at roughly half the tokens. It states no delegation rules and overrides none. Use when the user mentions DensePack, packed reports, or token savings on delegation.
---

# DensePack

Text costs about 1 token per 2.40 characters. An image costs about 1
token per 28 by 28 pixel patch. Text rendered small and dense into an
image costs roughly half of what the same text costs raw, and this
plugin automates that arithmetic for subagent reports. These
instructions are standing behavior for the rest of the session.

One topology rule: orchestrate from the main session. The hooks
deliver images and receipts to the session lead. An agent that spawns
its own sub-agents will not receive pointers for them, the session
lead does. The one deliberate exception is a subagent that reads the
packed size and holds an orchestration job: it works from the marker
lines its own agents return instead of pointers, and every agent it
spawns still lands in your manifest and receipts.

## Hook behavior

| Hook | Description |
| --- | --- |
| SessionStart | Installs Pillow, sends you the briefing image, shows the user last conversation's totals, and warns the user when the drawing size does not match the model |
| SessionEnd | Files the conversation totals. Claude Code discards this hook's output. The next session start shows them |
| SubagentStart | Tells every subagent: the final chat message is the report, a summary of five lines or fewer at the top, every later line a finding, and no report file written by the agent |
| SubagentStop | Files a long final message to the report file itself, blocks the stop once, takes the one marker line ending in `DENSEPACK_REPORT: <path>`, then packs the file into a PNG and writes the agent's manifest line. A marker naming a file that does not exist gets the same block, never a forward. Skips packing when the image would cost more, measured, never assumed |
| PostToolUse | Names the image folder and pattern, and sends you a savings receipt. Lead session only |

## The lead agent

- FIRST, the reader check. Three reader profiles set the size the
  plugin draws every image at: fable draws 8 px, opus draws 10 px,
  sonnet draws 12 px, each the smallest size that model reads with
  every answer exact. The session start hook catches a mismatched
  pairing and names it to the user itself. Read the profile off the
  status line the hooks print, or run
  `python plugin/scripts/dpctl.py status`, rather than assuming. If
  the profile does not match your model, say so once and offer the
  switch, /opuspack or /fablepack, or /quietpack. Do not silently work
  from images you cannot read confidently.
- Say nothing about report delivery in subagent prompts. The hook
  instructs every agent itself, and a prompt that restates the rule in
  other words overrides the hook's wording at a cost. The net enforces
  what politeness misses.
- Do not ask subagents to use the protocol for code, diffs, or data
  the lead must copy exactly. The hook already tells them to return
  those normally. Exact text belongs in text.
- Write every brief as plain text however long it is, and never pack
  one yourself. A PreToolUse hook packs it between your call and the
  subagent starting, at the size the RECEIVING model reads: 8 px for a
  fable agent, 10 px for an opus agent, 12 px for a sonnet agent. A
  model the floor tests never measured gets your text unchanged, and
  so does a brief under the threshold, because an image would cost
  more.
- Never mention packing, images or the pipeline inside a brief. The
  hook replaces the whole prompt. A brief that describes the mechanism
  describes what the agent will never read.
- A brief that asks an agent to check what a window or page shows also
  names the endpoint or file that feeds it.
- Do not open a brief image. Rows on the receipt reading `brief to
  <agent type>` are the agents' copies. You wrote those words already,
  and reading them back as a picture spends the saving a second time.
- Fable 5, Opus 5 and Sonnet 5 exchange condensed images in both
  directions, whichever one is leading, and no setting turns that
  exchange off.
- When the pointer names packed images, read the image and work from
  it. Do not re-read the text file it came from.
- The hook shows the user the savings table itself, one table per run
  of agents. Your copy adds the one thing the hook cannot know:
  replace each row's generic agent type with a two or three word name
  for what that agent was doing. Keep the columns exactly as the
  pointer formats them. Neither this table nor the delegation table
  ever carries an internal agent id; an id string means nothing to a
  reader. Do not add one yourself.
- When the user wraps up, hands off, or asks where the session stands,
  show the conversation total table the pointer prints: total
  characters, total pixels, and saved, each against its token count.
  The pointer's running line carries the numbers. The session end hook
  files the totals without your work, and the next session start shows
  them.

## The receipt

The receipt mode is the user's setting, and quiet is the default: no
table in the reply, because every pack made this conversation stays in
the receipt records instead, one row each. `/quietpack` is the command
for that mode. The other three shapes are `/setpack receipts`
arguments: `default` is the 6 column table, `verbose` splits the
arithmetic into columns and names the image dimensions, and `light` is
the same 6 column table with no totals row ever. A printed table
always ends in a BATCH TOTALS row, this batch's own sums, whatever the
totals setting says; in default and verbose alike, `light` is the one
mode with no totals row of any kind. `/setpack totals on` adds a
CONVERSATION TOTALS row back for the wrap-up only. When the user asks
for quiet receipts, create the flag file
`.claude/tmp/densepack-quiet` under the project root and delete it
when they ask for receipts again.

The delegation table (model, job, state, time left) does not append
after every batch by default, because the receipt records carry the
same rows per conversation at no cost to the conversation. The
plugin logs every spawn behind it either way. `/setpack status on`
turns the automatic print on and prints the table once immediately;
`/setpack status off` turns it back off. Job is the task the lead
gave that agent, with the agent type joined in brackets only when it
is not general-purpose. State says what each row is: finished or
still running. Time left says the number, a real duration from a
finished row, worded "took" so it reads as spent, or a median duration
for that model minus the time already spent for a still-running row,
with the sample size stated beside it whenever the median is too thin
to trust. No agent id ever appears in this table either. In quiet
mode the pointer names the file it wrote,
`.claude/tmp/densepack-receipt-last.md`. Show that table only when
the user's own prompt asked for a report.

A final message that ends with `DENSEPACK_REPORT: <path>` is the
stub; the full report is in the file it names. The protocol is
working.

## Delegation

DensePack states no delegation rules and overrides none. You pick
your own agents, your own models and your own methods, and the plugin
packs whatever comes back. The packing, the priced gates and the
agent-facing delivery rules all keep their earlier behavior.

## Skipped packing

| Case | Reason |
| --- | --- |
| The image measures more expensive than the text | The one guard, per report, live. The same comparison the DensePack app's meter shows. Tiny returns usually stay text for this reason, not because of any character floor; there is none |
| Code, diffs, machine-readable data | Exact text belongs in text. A packed image is for prose a lead reads, never for content a reader copies or parses |
| Pillow missing | Everything degrades to plain text. Nothing breaks |
