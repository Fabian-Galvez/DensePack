---
name: densepack-bench
description: Run the DensePack benches and check their math. Use when the user asks to run the benches, such as "Run the benches for Opus" or "Run all the benches". Also use when the user asks whether the DensePack savings are real.
---

# DensePack benches

Find the DensePack download folder: the folder that holds bench/RUN-THE-BENCHES.md.
Look in the current folder first, then in ~/.claude/plugins/marketplaces/densepack-marketplace, where the plugin install puts this repository.
If the file is in neither folder, ask the user for the path of their DensePack copy.
Read bench/RUN-THE-BENCHES.md in that folder and follow it.
That file holds the steps, the commands, the rules for a valid pair and the math.
Tell the user what will run and what it costs. Wait for a yes before the first bench command.

## The order

For each model, run the benches in this order: the single file bench, the 16-file bench, then the 32-file bench.
A request for the 32-file bench runs all three. A request for the 16-file bench runs the first two.
Say that in the plan you show the user.
Continue to the next bench only when the image arm of the last pair scored 5 of 5.
When a pair FAILS, say plainly that it failed and which questions the image arm missed.
Opus and Fable answer all questions and cost less. Ask the user whether to investigate.
When a Sonnet pair fails, or saves less than the lowest Sonnet pair for that bench in BENCHMARKS.md, give the user these choices.
One: type `/max-off`. Make Sonnet read text instead of images like Haiku. Fable and Opus still receive images.
Two: run the pair again because Sonnet sometimes reads all images and then saves less.
Three, only when the image arm scored 5 of 5: "Savings are savings: MaxPack it!" Sonnet keeps images. That is the default. The benches continue.
The user decides whether to continue.

## The token counts of a run

The plugin writes one row for each file it changes into an image.
The rows are in the bench folder of the run, at
`.claude/tmp/densepack-manifest.jsonl`.
Each row holds the characters of the file, its tokens as text and its tokens
as an image.
Read that file when the user asks what the images saved in tokens.
Do not delete the bench folder before you report the run.
