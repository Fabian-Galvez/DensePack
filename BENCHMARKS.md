<!-- DensePack 1.2 -->
# DensePack benchmarks

Each bench gives one reader the same task two times.
The off arm reads the files as text. The on arm reads the files as images.
The two arms together make one pair.


`bench/RUN-THE-BENCHES.md` tells you how to run these.

## Current benches, 23 September 2026

### Where the numbers come from

All prices come from the token counts the Anthropic API returned for each message of the arm.
Claude Code writes those counts into the arm's transcript, `~/.claude/projects/<folder>/<session id>.jsonl`, in `usage`.
The bench adds up `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` and `output_tokens`. Then the bench multiplies them by Anthropic's published prices.
The billed price is `total_cost_usd`, the dollar figure Claude Code reports for the arm.
The token columns come from DensePack's own record, `.claude/tmp/densepack-manifest.jsonl`, in the bench folder.

Each reader gets the same images and prompt.
Each bench ran one text arm and three image arms on each reader.
The 16-file and 32-file prices are cold prices. The 1-file prices are as billed.
The saving and the image arm price are the middle of the three image arms.
Opus 5.5 bills a cache read at 0.05x of input and Fable 5.1 at 0.025x. The prices use those rates.

### Fable 5.1

| Bench   | Tokens as text | Tokens as images | Text arm | Image arm | Saving | Score  |
| ------- | -------------- | ---------------- | -------- | --------- | ------ | ------ |
| 1-file | 1,859 | 898 | $0.0877 | $0.0522 | 40.5% | 15 of 15 |
| 16-file | 93,101 | 44,257 | $2.00 | $0.70 | 65.3% | 15 of 15 |
| 32-file | 273,149 | 129,170 | $5.44 | $1.57 | 71.2% | 15 of 15 |

### Opus 5.5

| Bench   | Tokens as text | Tokens as images | Text arm | Image arm | Saving | Score  |
| ------- | -------------- | ---------------- | -------- | --------- | ------ | ------ |
| 1-file | 1,859 | 898 | $0.0358 | $0.0252 | 29.7% | 15 of 15 |
| 16-file | 93,101 | 44,257 | $0.81 | $0.28 | 65.5% | 15 of 15 |
| 32-file | 273,149 | 129,170 | $2.20 | $0.59 | 73.1% | 15 of 15 |

### Sonnet 5

| Bench   | Tokens as text | Tokens as images | Text arm | Image arm | Saving | Score  |
| ------- | -------------- | ---------------- | -------- | --------- | ------ | ------ |
| 1-file | 1,859 | 898 | $0.0201 | $0.0123 | 39.1% | 15 of 15 |
| 16-file | 93,101 | 44,257 | $0.42 | $0.29 | 30.1% | 15 of 15 |
| 32-file | 273,149 | 129,170 | $1.13 | $0.30 | 73.4% | 15 of 15 |

Each image arm answered all 5 questions correctly.

### Each image arm

| Reader | Bench | Arm 1 | Arm 2 | Arm 3 |
| --- | --- | --- | --- | --- |
| Fable 5.1 | 1-file | 40.6% | 40.5% | 31.3% |
| Fable 5.1 | 16-file | 65.3% | 65.4% | 65.2% |
| Fable 5.1 | 32-file | 71.2% | 71.4% | 71.2% |
| Opus 5.5 | 1-file | 33.1% | 29.7% | 29.5% |
| Opus 5.5 | 16-file | 65.8% | 65.5% | 65.5% |
| Opus 5.5 | 32-file | 73.1% | 75.3% | 73.0% |
| Sonnet 5 | 1-file | 39.2% | 39.0% | 39.1% |
| Sonnet 5 | 16-file | 30.1% | 30.2% | 20.7% |
| Sonnet 5 | 32-file | 73.6% | 73.4% | 69.2% |

Sonnet reads each image on some runs and only the images it must have on others.

### Turns and time

A prompt about the files of a folder gets the names of those files before the first turn.
The image arm then reads the files in its first turn and does not spend a turn on Glob.

| Reader | Bench | Turns, text arm | Turns, image arm | Time, text arm | Time, image arm |
| --- | --- | --- | --- | --- | --- |
| Fable 5.1 | 1-file | 2 | 2 | 4.6 s | 14 to 15 s |
| Fable 5.1 | 16-file | 4 | 4 | 19.6 s | 29 to 44 s |
| Fable 5.1 | 32-file | 4 | 4 | 36.0 s | 63 to 83 s |
| Opus 5.5 | 1-file | 2 | 2 | 5.8 s | 9 to 11 s |
| Opus 5.5 | 16-file | 4 | 4 | 20.5 s | 24 to 27 s |
| Opus 5.5 | 32-file | 4 | 4 to 5 | 29.8 s | 57 to 69 s |
| Sonnet 5 | 1-file | 2 | 2 | 4.6 s | 6 to 8 s |
| Sonnet 5 | 16-file | 4 | 4 to 6 | 19.6 s | 47 to 60 s |
| Sonnet 5 | 32-file | 4 | 5 to 7 | 26.1 s | 46 to 66 s |

The image arm takes more time because DensePack draws each file before the agent reads it.
An image arm with more turns fetched later images of a file.

## Ubuntu benches, 16 September 2026

These pairs ran on Ubuntu 26.04 in WSL2, on 12 cores and 7 GB of memory, from the GitHub copy.
Claude Code 2.1.273 ran each arm in bash.
Each row is one pair at the cold price.
The two arms of each pair answered all 5 questions correctly.

![Cost of the image arm against the text arm on Ubuntu, two readers, three benches](images/savings-ubuntu.svg)

### Opus 5 on Ubuntu

| Bench   | Tokens as text | Tokens as images | Text arm | Image arm | Saving | Score  | Verdict |
| ------- | -------------- | ---------------- | -------- | --------- | ------ | ------ | ------- |
| 1-file  | 1,859          | 898              | $0.0418  | $0.0311   | 25.6%  | 5 of 5 | COUNTS  |
| 16-file | 93,101         | 44,257           | $1.09    | $0.40     | 63.3%  | 5 of 5 | PARTIAL |
| 32-file | 273,149        | 129,170          | $3.11    | $0.71     | 77.2%  | 5 of 5 | PARTIAL |

### Sonnet 5 on Ubuntu

| Bench   | Tokens as text | Tokens as images | Text arm | Image arm | Saving | Score  | Verdict |
| ------- | -------------- | ---------------- | -------- | --------- | ------ | ------ | ------- |
| 1-file  | 1,859          | 898              | $0.0181  | $0.0139   | 23.2%  | 5 of 5 | COUNTS  |
| 16-file | 93,101         | 44,257           | $0.42    | $0.22     | 47.1%  | 5 of 5 | PARTIAL |
| 32-file | 273,149        | 125,843          | $1.13    | $0.34     | 70.3%  | 5 of 5 | PARTIAL |

### Each pair on Ubuntu

| Reader   | Bench   | Pair 1 |
| -------- | ------- | ------ |
| Opus 5   | 32-file | 77.2%  |
| Opus 5   | 16-file | 63.3%  |
| Sonnet 5 | 32-file | 70.3%  |
| Sonnet 5 | 16-file | 47.1%  |

The Sonnet 32-file image arm read 31 of the 32 files. Its image tokens are lower.
PARTIAL means the two arms started with different cached tokens. The pair counts at the cold price only.

## Real session, 16 September 2026

This is a real Claude Code working session, not a bench pair.
Opus 5 ran it with DensePack 0.4.62 on, over 84 model calls.
The session ran the Go tab rebuild, edited the READMEs, exported and published.

The measure reads the session's own transcript.
Anthropic's count_tokens endpoint counted each image the model received.
It also counted the exact lines each image replaced, as Bash text and as Read text.
Each later model call sends all results again. The bench multiplies each count by the calls after it.
The comparison assumes the same calls on the image route and on the text route.

| Measure                        | Images  | Bash text | Read text |
| ------------------------------ | ------- | --------- | --------- |
| 6 images, read once            | 6,195   | 11,035    | 12,903    |
| Saved, read once               |         | 43.9%     | 52.0%     |
| Sent again on each later call | 409,421 | 732,708   | 858,493   |
| Saved, sent again              |         | 44.1%     | 52.3%     |
| Saved, less the extra call     |         | 33.2%     | 43.0%     |

The agent read no image twice.
One call fetched images 2 and 3 of a 323-line file. A text Read does not need that call.
That call sent 80,099 context tokens and wrote 237 output tokens. The row "Saved, less the extra call" subtracts that call.
After each image, the API's own usage shows the context grew by more than the counted image.

The same session read 5 files through Bash as text: 6,720 tokens, sent again as 317,097.
Those reads saved nothing.

These are token counts, not prices.
A cache read bills at a tenth of input. The saving in dollars is lower.

## Previous benches, 16 September 2026

These ran with Fable 5.1, Opus 5 and Sonnet 5. Opus 5 is retired.

![Cost of the image arm against the text arm, three readers, three benches](images/savings-by-reader.svg)


### Fable 5.1

| Bench   | Tokens as text | Tokens as images | Text arm | Image arm | Saving | Score  |
| ------- | -------------- | ---------------- | -------- | --------- | ------ | ------ |
| 1-file  | 1,859          | 898              | $0.0875  | $0.0682   | 22.0%  | 5 of 5 |
| 16-file | 93,101         | 44,257           | $2.01    | $0.70     | 65.2%  | 5 of 5 |
| 32-file | 273,149        | 129,170          | $5.45    | $1.57     | 71.1%  | 5 of 5 |

### Opus 5

| Bench   | Tokens as text | Tokens as images | Text arm | Image arm | Saving | Score  |
| ------- | -------------- | ---------------- | -------- | --------- | ------ | ------ |
| 1-file  | 1,859          | 898              | $0.0446  | $0.0323   | 27.5%  | 5 of 5 |
| 16-file | 93,101         | 44,257           | $1.05    | $0.37     | 65.2%  | 5 of 5 |
| 32-file | 273,149        | 129,170          | $2.82    | $0.75     | 73.3%  | 5 of 5 |

### Sonnet 5

| Bench   | Tokens as text | Tokens as images | Text arm | Image arm | Saving | Score  |
| ------- | -------------- | ---------------- | -------- | --------- | ------ | ------ |
| 1-file  | 1,859          | 898              | $0.0193  | $0.0140   | 27.4%  | 5 of 5 |
| 16-file | 93,101         | 44,257           | $0.42    | $0.29     | 31.5%  | 5 of 5 |
| 32-file | 273,149        | 129,170          | $1.13    | $0.33     | 70.4%  | 5 of 5 |

The 1-file saving is the middle of 100 runs.
Its image arm price is its text arm price less that saving.
The 1-file bench is one image at each setting. This change cannot move it.

An image of a file costs about 50% of the text of that file.
The full conversation cuts more than 50% because each turn after the first
reads the image again and does not read the text.

Each on arm answered all 5 questions correctly.

### Each pair

| Reader    | Bench   | Pair 1 | Pair 2 | Pair 3 |
| --------- | ------- | ------ | ------ | ------ |
| Fable 5.1 | 32-file | 71.1%  | 71.1%  | 71.1%  |
| Fable 5.1 | 16-file | 64.6%  | 65.2%  | 68.9%  |
| Opus 5    | 32-file | 75.3%  | 73.3%  | 70.2%  |
| Opus 5    | 16-file | 64.7%  | 65.4%  | 65.2%  |
| Sonnet 5  | 32-file | 72.7%  | 70.4%  | 29.9%  |
| Sonnet 5  | 16-file | 59.3%  | 31.5%  | 25.8%  |

Fable and Opus give the same result each time.
Sonnet reads each image on some runs and only the images it must have on
others.
A run that opens only the images it must have cuts about 70%.
A run that opens each image cuts about 30%.

### Turns

The image arm uses one or two turns more than the text arm and costs less.
The price counts each turn. A pair with more turns can count.

### Speed and memory, 22 September 2026

| Data | Before | Now |
|---|---|---|
| 11 KB | 3.2 s, 528 MB, 16 processes | 0.9 s, 55 MB, 1 process |
| 21 KB | 5.4 s, 630 MB, 15 processes | 1.8 s, 76 MB, 1 process |
| 228 KB | 29.6 s, 3.3 GB, 16 processes | 8.2 s, 243 MB, 1 process |

## Previous benches, 14 September 2026

These are from the wide images.

| Reader    | 32-file bench | 16-file bench | Score  | Pairs   | 1-file bench | Score                     | Runs |
| --------- | ------------- | ------------- | ------ | ------- | ------------ | ------------------------- | ---- |
| Fable 5.1 | 64.1%         | 45.5%         | 5 of 5 | 3       | 22.0%        | 5 of 5                    | 100  |
| Opus 5    | 60.3%         | 39.3%         | 5 of 5 | 3       | 27.5%        | 5 of 5                    | 100  |
| Sonnet 5  | 63.9%         | 47.1%         | 5 of 5 | 2 and 1 | 27.4%        | 5 of 5 on 99, 4 of 5 on 1 | 100  |

The 1-file numbers do not change because the 1-file bench uses one image at each
setting.
These benches are from the 14th and 16th of September, after sessions that fine-tuned the images for AI legibility.
Originally, DensePack lost over 20% on the single file bench. A month and more than a thousand benches later, DensePack saves over 20% on a single file.

<br>

---

<br>

## How the DensePack plugin saves

AI agents tokenize your input (messages, files and reports from subagents). Anthropic bills those tokens and writes them to cache. Each later turn reads them again. 
<br>
<strong>DensePack shrinks your input before it goes into context.</strong>
<br>

- DensePack images cost **31 to 55%** compared to raw text input.
- You pay cache write **once**, on the 31 to 55%.
- Each later turn pays cache read on that same 31 to 55%, at 0.1x, 0.05x
  on Opus 5.5 or 0.025x on Fable 5.1.
<br>
When your agent needs to read a text file, the DensePack plugin replaces it with an image. 
Your agent reads and caches the image instead. 
<br>
Smaller cache writes make smaller cache reads. The cost grows more slowly. You do not trim or compress the data that you send.
The longer you work, the more DensePack saves.
<br>

---

<br>

### Cost on small tasks

DensePack now saves on a single file. An image costs extra turns and longer
thinking. Output bills at 5x. An earlier version of DensePack lost money on
small tasks for that reason.

The tables above contain the most recent benches.
<br>

---

<br>

### DensePack saves even when it takes more turns

Each turn re-reads the entire conversation from the cache. 
An image costs fewer tokens than its text. Each later turn re-reads less. 
An extra turn re-reads that smaller cache at 0.1x the input price, 0.05x on Opus 5.5 or 0.025x on Fable 5.1. 
The image arm can take more turns and still cost less. 

In Sonnet 5 pair `sonnet-thirtytwo-1`, the image arm took 6 turns and the text arm took 4. 
The two arms answered 5 of 5. The image arm cost 60.5% less. 
In Sonnet 5 pair `sonnet-thirtytwo-v26-check-2`, the image arm took 8 turns and the text arm took 4. 
That pair ran an earlier 32-file task with 10 questions. 
The two arms answered 10 of 10. The image arm cost 78.2% less. 

<strong>The image arm sometimes reads less than the text arm.</strong>

The image arm opens only the images it needs. The text arm reads each file in full.
<br>

---

<br>

### What a file costs, message by message

Each message sends one 1,000 token file.
A 1-hour cache write costs 2x the input price. A cache read costs 0.1x.
DensePack packs each file into an image of 500 tokens, with nothing trimmed
and nothing compressed.

| Message         | Without DensePack                | With DensePack                 |
| --------------- | -------------------------------- | ------------------------------ |
| 1               | write 1,000 at 2x = 2,000        | write 500 at 2x = 1,000        |
| 2               | read 1,000 + write 1,000 = 2,100 | read 500 + write 500 = 1,050   |
| 3               | read 2,000 + write 1,000 = 2,200 | read 1,000 + write 500 = 1,100 |
| Total after 3   | 6,300                            | 3,150                          |
| Total after 10  | 24,500                           | 12,250                         |
| Total after 50  | 222,500                          | 111,250                        |
| Total after 100 | 695,000                          | 347,500                        |

The cache read increases with each message because each message reads
all the earlier messages.
DensePack halves each cache write. It halves each cache read after it.

An agent often takes more than one turn for one prompt. Each turn is one
more cache read.
That is why the 32-file benches save more than half even if the image arm
takes twice the turns.
<br>

---

<br>

### A real session

A real Opus 5 working session with DensePack on made 84 model calls and read 6 images.
Anthropic's count_tokens endpoint counted each image and the exact text it replaced.

- Read once, the images cost 43.9% less than the same lines as Bash text and 52.0% less than Read text.
- On each later call, the images sent 409,421 tokens where Bash text sends 732,708 and Read text sends 858,493.
- The images needed one extra call to fetch a file's later images.
- With that call counted, the images saved **33.2%** against Bash text and **43.0%** against Read text.

<sub>These are token counts, not prices. [BENCHMARKS.md](BENCHMARKS.md#real-session-16-september-2026) contains the full measure.</sub>
<br>

---

<br>

## How Anthropic bills

Anthropic bills per million tokens (MTok), priced per model:

<strong>Cache read is 0.1x of the 1x base input price</strong>, not 0.1x the 2x cache creation price. 
Opus 5.5 reads at 0.05x and Fable 5.1 at 0.025x.

| Model                      | `input_tokens` (1x) | `cache_creation` (2x) | `cache_read` (0.1x) | `output_tokens` (5x) |
| -------------------------- | ------------------- | --------------------- | ------------------- | -------------------- |
| <strong>Fable 5.1</strong> | $10                 | $20                   | $0.25 (0.025x)      | $50                  |
| <strong>Opus 5.5</strong>  | $4                  | $8                    | $0.20 (0.05x)       | $20                  |
| <strong>Sonnet 5</strong>  | $2                  | $4                    | $0.20               | $10                  |

<sub>The rates come from the <strong>Model pricing</strong> table on <a href="https://platform.claude.com/docs/en/about-claude/pricing">Anthropic's pricing site</a>.</sub>


`input_tokens` is the baseline that the multipliers calculate against. 

`cache_creation_input_tokens` are `input_tokens` that Claude Code writes to the cache. 
 
Claude Code writes a 1-hour cache for the main conversation on a Pro or Max plan. 
It writes a 5-minute cache for subagents and for everything on an API key. 
A 1-hour cache write costs 2x the base input rate of the model. A 5-minute cache write costs 1.25x. 
Claude Code sends the entire conversation on each call. The cache stores the part that repeats.
The model reads that part at the `cache_read_input_tokens` 0.1x multiplier price.

<sub>With no cache, Anthropic bills the entire conversation at the base 1x price on each call.</sub>
<br>

---

<br>

## Exact values

The reader takes a long number, a hash or a path from the image when it reads clean. 
When in doubt the reader pulls only that line from the text by its green line number in the image. 
It uses Read at offset N and limit 1. 
It never reads the entire text file.

A Read of 20 lines or fewer passes all DensePack hooks untouched. 
`LINE_PULL_MAX` in `plugin/scripts/common.py` contains the 20 lines.

<br>

---

<br>

## Recreate these benches yourself

1. Install DensePack. [INSTALL.md](INSTALL.md) contains all the steps for Windows, macOS and Linux.
2. Download this repository. Click the green **Code** button at the top of the page, choose **Download ZIP** and unzip it.
3. Open Claude Code in the folder you unzipped.
4. Set the effort. Put `DENSEPACK_BENCH_EFFORT=high` in front of each bench command in the Bash tool. The two arms then think at the same effort.
5. Say this to Claude Code: `Read bench/RUN-THE-BENCHES.md and run the benches for Sonnet`.
6. Read each result. The checker prints COUNTS, PARTIAL, FAILS or DISCARD after each pair. The checker tells you what each one means.

One pair of the single file bench costs a few cents. A fault on your
machine costs little.

[bench/RUN-THE-BENCHES.md](bench/RUN-THE-BENCHES.md) contains the four benches,
the exact commands, the rules for a valid pair and the math, written for you
and for your AI. [bench/README.md](bench/README.md) contains the results, the
faults and the fixes.
