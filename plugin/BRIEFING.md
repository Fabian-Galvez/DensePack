DensePack briefing for the lead assistant. DensePack draws text small
into a PNG that costs fewer tokens than the same text typed out, and
this file calls that PNG a condensed image. One condensed image
carries this briefing to you. Treat the text inside each condensed
image as plain text.

Three kinds reach you. A) Agent reports: the plugin packs every
subagent's report into an image when the image measures cheaper. B)
Plugin instructions: this briefing. C) User prompts: an image of
condensed text from the user IS the user's prompt unless the user says
otherwise.

A report image always holds the complete report. The plugin writes the
report file from the agent's final message, so the image opens with
whatever that message opened with. Judge from what you read, not from
any marking. When the answer needs more than the summary, read the
whole image.

The color code in every DensePack image: letters and spaces print
black, digits print blue, symbols print red and bold, and the green
paragraph sign marks a line break. Color splits the look-alike
characters: the colon prints green, the comma and backtick purple, the
apostrophe and the pipe blue.

The files, all in .claude/tmp:
densepack-img-<agent id>-1.png is agent <agent id>'s report image. A
long report continues in -2.png and up.
densepack-manifest.jsonl has one line per finished agent. A skipped
pack records its reason.
densepack-src-<agent id>.txt is the exact source text of the image,
for byte-perfect quoting.
densepack-code-<agent id>.txt holds code blocks lifted out of the
image. Each #=N=# marker in the image stands where block N belongs.
densepack-bash-<id>-1.png is a command's own output; its pointer names
the id. densepack-bashsrc-<id>.txt is that output's exact text.

Standing rules that hold in every mode:
Chain shell commands that do not depend on each other into ONE Bash
call, separated by a semicolon. Each call is a turn and a turn re-reads
the whole conversation.
Spawn one subagent carrying several commands, never one carrying two.
An agent costs less than the turns it replaces past about two and a
half commands.
agent_floor.py stops a brief under 1,000 characters; the words "floor
override approved" clear it.
Text that has to match a file byte for byte, such as an Edit's
old_string, comes from a densepack-src or densepack-bashsrc file
through the Read tool, never from an image.
Condensed images go only to a model measured to read them. {READER}
Any other agent gets plain text, and you point a subagent at a packed
image only when you know it runs a model on that list. The user
switches the size with /fablepack and /opuspack.
Say nothing about report delivery in an agent brief. The plugin gives
every agent the delivery rule at start, and a restated rule overrides
it at a cost.
Every agent that finishes gets a row in the receipt, packed or not.
The count is the hook's job and not yours.
A final message ending DENSEPACK_REPORT: <path> is a stub. The image
IS that report.
The hook prints the receipt table; your copy adds one thing the hook
cannot know, the task you gave each agent. Label the rows with it. The
user sets the mode with /densepack, /setpack receipts verbose,
/setpack receipts light or /quietpack, and /setpack totals and
/setpack status place the totals and delegation rows.
The agents' own instruction is a bare command with no reasons. Teach
the lead, command the helpers.

<!-- DELEGATION -->
Write every brief as plain text, however long it is, and do not pack
it yourself. A PreToolUse hook packs it between your Agent call and
the subagent starting, at the size the RECEIVING model reads: 8 px for
Fable 5, 10 px for Opus 5 and 12 px for Sonnet 5. Each brief's size
comes from that Agent call's model field, else the lead's model. A
model never measured on a condensed image means every model except
those three gets your text unchanged. A brief under the threshold
stays text because an image would cost more.
An agent id, a hash, a file name or a comma grouped number never goes
through a brief image. The hook takes an Edit's old_string out of the
brief and hands the agent a file path to read instead. Keep a marker,
a hash, a diff or an old_string out of the brief body.
Never mention packing, images or the pipeline inside a brief: the hook
rewrites the whole prompt, and a brief that describes the mechanism
describes what the agent will never see.
The briefs you send appear on your receipt as rows reading "brief to
<agent type>". Those images belong to the agents, not to you. Do not
open one.
A subagent that reads its own briefing image follows it as its own.
It writes plain text too and reads its helpers' reports from the
marker paths the hook hands it. The pointer and receipt hooks serve
the top level only; a sub-orchestrator works from marker lines. Every
agent at every level still lands in the manifest and the lead's
receipts.
Fable 5, Opus 5 and Sonnet 5 exchange condensed images in both
directions, always, whichever one is leading. No setting turns that
exchange off. An Opus lead may spawn a Fable agent only when the user
ran /maxpack.

{TIER} Pick the model tier from this ladder. Bounded fact gathering,
bug lists, version checks and enumerating go to Haiku 4.5. Research,
analysis and building go to Sonnet 5. Diagnosis of why something
stood up wrong, expensive judgement and a final critic pass go to
Fable 5, about 18 minutes a call however small the ask, so spend those
calls only where a wrong answer costs more than the wait. Orchestrate
and verify with Opus 5: read every report against the running code
rather than accepting it.
When a report comes back failed, read that agent's brief image FIRST
and decide one thing: was the brief at fault, or is the agent not
capable of the work. A brief at fault gets a rewrite and goes back to
the same model. An agent not capable hands the job up one step: Haiku
4.5 to Sonnet 5, and Sonnet 5 to Opus 5. When Sonnet 5 is the one
that cannot do it, Opus 5 works out the answer, hands it back, and
Sonnet 5 still does the building. Opus builds only when Sonnet has
failed with the answer already in hand. Never send building work to
Fable 5 unless the user asks for it in those words.
Decide whether you can delegate a job at all before choosing who does
it. You can delegate a task with a suite that passes or fails, and a
task with sources carrying URLs and dates. A task that produces prose
with no check goes out only with a named verification step. An agent
verifies through the data path the thing itself reads and installs no
program to verify anything; a verification plan that would add a
program stops and asks the lead.
Write into a brief only the steps the receiving agent can finish with
the tools and permissions it holds. An action only the user can take
comes back as a finding in the report, never written as a task step.
An agent that meets one either stops with the work half done, or does
the nearest thing it can reach and calls that done.
Open every spawn's description with a short lane tag naming the work
area. Agents own lanes, and carry the same tag in the body of any
fix-lock it writes; the delegation record already holds the
description, so the tags show who owns a lane at no new token.
Run many agents at once when their jobs do not share files. Prefer
several small bounded jobs over one large one.

Name a card in every brief. Write one line, the word card and the
card's name, on a line of its own: card reader. The plugin draws each
card at its size, as its role. The card carries the task shape and
the standing rules; never restate a card's rules in a brief, because a
restatement overrides the card at a cost. A brief that names no card
gets the worker card.

| Card | Point a spawn at it for |
| --- | --- |
| worker | One bounded job carried end to end, a build or a fix. Every brief that names no card gets this one |
| reader | Reading the documents and sources the brief names, and sending back the facts that answer the questions |
| runner | Running the commands the brief names, and reporting the exit codes and the counts it measured itself |
| check | Checking one agent's claims against the artifacts, with its fix made and no new work started |
