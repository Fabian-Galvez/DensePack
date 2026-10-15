# DensePack benchmarks

In each A/B bench, the same task runs twice on the same model, once with DensePack and once without it. The price of a run is its tokens at the [Anthropic API prices](#how-anthropic-bills).

<br>

---

<br>

## DensePack 2.0.2, 13 October 2026

DensePack 2.0.2 has a start note of rules for less code and short replies. The note also names an image that maps the project's folders, files and the names in each file.

The savings below are against the price of the same task without DensePack. When a saving is negative, the run cost more.

### DensePack's benches

DensePack 2.0.2 ran each bench 5 times in a row on both Opus 5.5 setups on 13 October 2026. The Sonnet 5.5 table is from DensePack 2.0 on 10 and 11 October. The runs used Claude Code 2.1.296 on Windows, `claude -p`, Bash and no Grep or Glob.

The first table of each setup contains the averages from the README. The runs table below it contains the price and the score of each run.

### Opus 5.5

| Bench | Without DensePack | DensePack 2.0.2 |
| --- | --- | --- |
| Five files read | $0.984 | $0.509, 48.3% |
| Architecture doc | $0.740 | $0.349, 52.8% |
| Read-in-full architecture | $1.810 | $0.866, 52.1% |
| Code trace | $4.737 | $2.359, 50.2% |

The price of each run:

| Run | Five files read | Architecture doc | Read-in-full architecture | Code trace |
| --- | --- | --- | --- | --- |
| 1 | $0.512, 7/7 | $0.331, 18/18 | $0.883, 18/18 | $2.016, 26/26 |
| 2 | $0.510, 7/7 | $0.342, 18/18 | $0.873, 18/18 | $2.390, 26/26 |
| 3 | $0.505, 7/7 | $0.412, 18/18 | $0.854, 18/18 | $2.865, 26/26 |
| 4 | $0.512, 7/7 | $0.323, 18/18 | $0.868, 18/18 | $2.511, 26/26 |
| 5 | $0.505, 7/7 | $0.338, 18/18 | $0.853, 18/18 | $2.013, 26/26 |

- All 20 runs count. No run was left out or run again.
- Architecture doc saves the most, because the agent writes a long document there, and the rules make it shorter.
- In five files read, the agent reads 5 named files and writes a 5-line summary, so the rules have little to cut.
- Code trace is mostly reading, with 31 to 48 Reads in each run.

<details>
<summary>DensePack 2.0 on 10 and 11 October 2026</summary>

| Bench | Without DensePack | DensePack 2.0 |
| --- | --- | --- |
| Five files read | $0.984 | $0.499, 49.3% |
| Architecture doc | $0.740 | $0.339, 54.2% |
| Read-in-full architecture | $1.810 | $0.874, 51.7% |
| Code trace | $4.737 | $2.455, 48.2% |

The price of each run:

| Run | Five files read | Architecture doc | Read-in-full architecture | Code trace |
| --- | --- | --- | --- | --- |
| 1 | $0.497, 7/7 | $0.300, 18/18 | $0.874, 18/18 | $2.920, 26/26 |
| 2 | $0.500, 7/7 | $0.364, 18/18 | $0.867, 18/18 | $2.329, 26/26 |
| 3 | $0.498, 7/7 | $0.342, 18/18 | $0.854, 18/18 | $2.088, 26/26 |
| 4 | $0.502, 7/7 | $0.355, 18/18 | $0.879, 18/18 | $2.361, 26/26 |
| 5 | $0.496, 7/7 | $0.333, 18/18 | $0.895, 18/18 | $2.576, 26/26 |

- Architecture doc saves the most, because the agent writes a long document there, and the rules make it shorter.
- In five files read, the agent reads 5 named files and writes a 5-line summary, so the rules have little to cut.
- Code trace is mostly reading, with 29 to 47 Reads in each run.

</details>

### Opus 5.5 main agent with a Sonnet 5.5 subagent

The Opus main agent gives the reading to one Sonnet 5.5 subagent, and DensePack 2.0.2 gives the rules to the subagent too. The savings are against Opus 5.5 without DensePack.

| Bench | Without DensePack | DensePack 2.0.2 with a Sonnet subagent |
| --- | --- | --- |
| Five files read | $0.984 | $0.283, 71.2% |
| Architecture doc | $0.740 | $0.415, 43.9% |
| Read-in-full architecture | $1.810 | $0.556, 69.3% |
| Code trace | $4.737 | $1.477, 68.8% |

The price of each run:

| Run | Five files read | Architecture doc | Read-in-full architecture | Code trace |
| --- | --- | --- | --- | --- |
| 1 | $0.286, 7/7 | $0.578, 18/18 | $0.536, 18/18 | $1.447, 26/26 |
| 2 | $0.293, 7/7 | $0.358, 18/18 | $0.514, 18/18 | $1.309, 26/26 |
| 3 | $0.268, 7/7 | $0.347, 18/18 | $0.532, 18/18 | $1.602, 26/26 |
| 4 | $0.284, 7/7 | $0.445, 18/18 | $0.586, 18/18 | $1.455, 26/26 |
| 5 | $0.286, 7/7 | $0.345, 18/18 | $0.612, 18/18 | $1.572, 26/26 |

- All 20 runs count. No run was left out or run again.
- With no DensePack, the Opus main agent with a Sonnet subagent cost $0.892 on the architecture doc. Against that price, DensePack 2.0.2 saved 53.5% on average. That price leaves out an estimate of the cost of the eval's Bash sandbox.

<details>
<summary>DensePack 2.0 on 10 and 11 October 2026</summary>

| Bench | Without DensePack | DensePack 2.0 with a Sonnet subagent |
| --- | --- | --- |
| Five files read | $0.984 | $0.287, 70.8% |
| Architecture doc | $0.740 | $0.333, 55.0% |
| Read-in-full architecture | $1.810 | $0.543, 70.0% |
| Code trace | $4.737 | $1.645, 65.3% |

The price of each run:

| Run | Five files read | Architecture doc | Read-in-full architecture | Code trace |
| --- | --- | --- | --- | --- |
| 1 | $0.276, 7/7 | $0.330, 18/18 | $0.651, 18/18 | $1.637, 26/26 |
| 2 | $0.286, 7/7 | $0.302, 18/18 | $0.525, 18/18 | $1.592, 26/26 |
| 3 | $0.301, 7/7 | $0.339, 18/18 | $0.535, 18/18 | $1.279, 26/26 |
| 4 | $0.287, 7/7 | $0.377, 18/18 | $0.482, 18/18 | $1.909, 26/26 |
| 5 | $0.288, 7/7 | $0.317, 18/18 | $0.521, 18/18 | $1.806, 26/26 |

- In the architecture doc, the subagent searched the scripts with Bash and read only the parts it needed, with 5 to 11 images.
- With no DensePack, the Opus main agent with a Sonnet subagent cost $0.892 on the architecture doc. Against that price, DensePack 2.0 saved 57.7% to 66.1%, 62.7% on average. That price leaves out an estimate of the cost of the eval's Bash sandbox.

</details>

### Sonnet 5.5

These runs show what a Sonnet 5.5 main agent costs with DensePack, and that Sonnet reads the images correctly.

| Bench | Without DensePack | DensePack 2.0 |
| --- | --- | --- |
| Five files read | $0.498 | $0.256, 48.6% |
| Architecture doc | $0.322 | $0.208, 35.3% |
| Read-in-full architecture | $0.826 | $0.502, 39.2% |
| Code trace | $2.706 | $2.370, 12.4% |

The price of each run:

| Run | Five files read | Architecture doc | Read-in-full architecture | Code trace |
| --- | --- | --- | --- | --- |
| 1 | $0.256, 7/7 | $0.224, 18/18 | $0.458, 18/18 | $2.287, 26/26 |
| 2 | $0.256, 7/7 | $0.201, 18/18 | $0.539, 18/18 | $2.262, 26/26 |
| 3 | $0.254, 7/7 | $0.184, 18/18 | $0.540, 18/18 | $2.512, 26/26 |
| 4 | $0.257, 7/7 | $0.213, 18/18 | $0.498, 18/18 | $2.582, 26/26 |
| 5 | $0.257, 7/7 | $0.219, 18/18 | $0.474, 18/18 | $2.208, 26/26 |

- In the architecture doc, the agent searched the 14 scripts with Bash or read only their first lines.
- Code trace took 40 to 49 API requests.

These notes apply to all runs above.

- The runs with DensePack started with `claude -p` through `bench/direct_pair.py`, with the same tools that `claude plugin eval` offers, apart from Grep and Glob. DensePack ran with the two settings from [Install the plugin](README.md#install-the-plugin), so the agent had no Grep, Glob or PowerShell tool.
- The runs without DensePack ran earlier with `claude plugin eval` on Claude Code 2.1.284 to 2.1.293, with Grep and Glob. That tool turns on the Bash sandbox, which adds sandbox instructions to each request. Their prices here leave out the cost of those instructions.
- The Sonnet prices, with and without DensePack, count cache reads at $0.20 per million tokens, the price of `claude plugin eval`, so both sides use the same price. The Anthropic price list has $0.10, so at the list price Sonnet costs less than these tables show.
- The DensePack prices are averages of 5 runs. Without DensePack, the Opus prices average 10, 24, 5 and 7 runs, in the order of the tables. The Sonnet prices average 16, 25, 5 and 6 runs.
- The runs tables contain 5 runs of each bench on each setup, and all of them scored full marks.


### Opus 5.5 with each setup

![The price of one Opus 5.5 session without DensePack, with DensePack 2.0.2, and with DensePack 2.0.2 and a Sonnet subagent](images/savings-benchmarks.svg)

The savings are against the price without DensePack. The DensePack prices are averages of 5 runs. In the last column, the Opus lead gives the reading to one Sonnet 5.5 subagent.

| Bench | Without DensePack | DensePack 2.0.2 | DensePack 2.0.2 with a Sonnet subagent |
| --- | --- | --- | --- |
| Five files read | $0.984 | $0.509, 48.3% | $0.283, 71.2% |
| Architecture doc | $0.740 | $0.349, 52.8% | $0.415, 43.9% |
| Read-in-full architecture | $1.810 | $0.866, 52.1% | $0.556, 69.3% |
| Code trace | $4.737 | $2.359, 50.2% | $1.477, 68.8% |

- DensePack adds a start note of about 2,300 tokens with its rules. The note names a project map image, 466 tokens for these 24 scripts, which the agent reads in its first turn.
- The DensePack prices already contain the cost of this extra text.

### Opus 5.5 with DensePack costs about as much as Sonnet 5.5

Without DensePack, Sonnet 5.5 costs about half as much as Opus 5.5 in these benches. With DensePack 2.0.2, Opus 5.5 costs about the same as Sonnet 5.5 without it, so you get Opus for about the price of Sonnet.

The savings are against Opus 5.5 without DensePack.

| Bench | Opus 5.5 without DensePack | Opus 5.5 with DensePack 2.0.2 | Sonnet 5.5 without DensePack |
| --- | --- | --- | --- |
| Five files read | $0.984 | $0.509, 48.3% | $0.498, 49.4% |
| Architecture doc | $0.740 | $0.349, 52.8% | $0.322, 56.5% |
| Read-in-full architecture | $1.810 | $0.866, 52.1% | $0.826, 54.4% |
| Code trace | $4.737 | $2.359, 50.2% | $2.706, 42.9% |

<br>

---

<br>

## Run these benches yourself

Run this command in the repository folder for one run with DensePack:

```
python bench/direct_pair.py five-files-read --model claude-opus-5-5 --warm --sides with --out bench-five-1
```

- The script copies your Claude Code login from `~/.claude/.credentials.json`. On macOS, Claude Code keeps the login in the Keychain, so run the benches on Windows or Linux.

- On Windows, add `--with-env EMBEDDED_SEARCH_TOOLS=1 --with-env CLAUDE_CODE_USE_POWERSHELL_TOOL=0`. The runs start in a new home folder, so the settings that DensePack writes to `~/.claude/settings.json` for later sessions never reach them. These two flags give the runs those settings.
- The cases are `five-files-read`, `architecture-doc` and `code-trace` in `plugin/evals`. For read-in-full, add `--prompt-file bench/prompts/architecture-read-all.md` to `architecture-doc`. For the benches with a subagent, add `--prompt-file bench/prompts/<name>`: `five-files-read-subagent.md` with `five-files-read`, `architecture-doc-subagent.md` and `architecture-read-all-subagent.md` with `architecture-doc`, and `code-trace-subagent.md` with `code-trace`.
- The command prints the price, the API requests and the score of the run. `bench/trace_check.py` checks that the trace is one valid run.
- `bench/savings_chart.py` contains the price of each run without DensePack in these tables and draws the chart. It needs fontTools (`pip install fonttools`), because it draws each letter as an outline of the Inter font in `plugin/fonts`.

<br>

---

<br>

## How DensePack saves

DensePack packs the files that the agent reads into images when an image costs fewer tokens than the text. Claude Code sends the smaller image again with each later request, at the cache read price. [What DensePack packs](HOW-IT-WORKS.md#what-densepack-packs) and [What are the limits?](HOW-IT-WORKS.md#the-limits) give the rules and the files that stay text.

In the byte identical rebuild, each image uses 49% to 55% fewer tokens than the text of its file. The cache read price is 0.05x of the input price on Sonnet 5.5 and Opus 5.5. It is 0.025x on Fable 5.1.
- The saving of each image grows with the number of turns after it.

<br>

---

<br>

### Models that get images

- Fable and Opus models always get images. Sonnet models get images while the maxpack setting is on. These models get the same image, with a font size of 17 px.
- The maxpack setting is on by default, which lets Sonnet get images. `/max-off` sends Sonnet text instead of images.
- Haiku gets text.
- Some Word files and the files in `.claude/densepack-vault/to-pack/` are the exception. DensePack packs them for all models, Haiku included.

<br>

---

<br>

### Bash output

DensePack also packs long Bash output into images. Some kinds of lines are easy to misread in an image, so DensePack sends them as exact text. [How the swap happens](HOW-IT-WORKS.md#how-the-swap-happens) lists them.

To find these lines, Opus 5.5 copied real Bash output from images with the exact lines turned off.

- It typed 76 of 108 random IDs with I or l wrong, each time with I and l swapped.
- It miscounted 54 of 72 `git --stat` bars.
- It typed 106 of 108 IDs without I or l correctly.
- It also typed 167 of 168 hex hashes and 160 of 160 numbers of 8 to 17 digits correctly.

Those strings stay in the image only. On that day, 597 of 8,274 real Bash outputs of 400 characters or more had such a line, about 7%.

In earlier tests, the model lost all 14 lines of only spaces and all 18 tabs inside a line. In another test, Opus 5.5 typed 33 of 34 packed Bash outputs exactly, apart from a final newline. The one miss was a lost space at the end of a row. Opus 5.5 also answered questions about exact strings in packed output.

| Input | Questions answered correctly |
| --- | --- |
| With DensePack | 59 of 60 |
| With DensePack, image only | 50 of 51 |
| Text | 60 of 60 |

<br>

---

<br>

### Subagents

- At the start of each session, DensePack sends its session note to the lead.
- DensePack also sends the note to each subagent when the subagent starts, except to a Sonnet subagent after /max-off.
- Haiku subagents get no note, because their Reads, their Bash output and their briefs stay text.
- DensePack packs subagent reports when the image costs less than the text.
- DensePack packs briefs of 1,000 characters or more the same way, in auto and bypassPermissions mode only.
- In the other modes, a change to the Agent call can skip the permission prompt, so briefs stay text.

The lead opens a packed report with one Read, because the result of the Agent tool cannot carry an image. Read results and Bash results can carry an image.

One test used a hook on the Agent tool.

- The hook replaced the result with other text. The Opus 5.5 lead read that text instead of the report, which is how `report_swap.py` swaps in the image name.
- The same hook then put an image into the result in four shapes:
  - Image block
  - Image shape of a Read result
  - Image shape of a Bash result
  - Text block with an image block
- In all four cases, the lead got the original text of the subagent.

<br>

---

<br>

### Later requests cost less

Claude Code sends the whole conversation with each request. Images cost fewer tokens than their text, so each later request sends fewer cached tokens.

In the [code trace](#opus-55) on Opus 5.5, the 5 runs with DensePack 2.0 took 33 to 56 API requests. They read 2.3 to 4.5 million tokens from the cache. The 7 runs without DensePack took 45 to 64 requests and read 7.0 to 11.6 million.

Image runs can also read less than text runs.

- If a file fills several images, the Read can return them stacked into one image. This works when the stack fits in 1,568 by 1,568 pixels, the size that DensePack sets for one joined image.
- Otherwise, a whole-file Read returns its images in one result. Like a text Read, it stops at line 2,000.
- Text runs read each file in full.

<br>

---

<br>

### Cost per message

This example uses these values.

- One file of 1,000 tokens goes with each message.
- Cache writes with a 1-hour lifetime cost 2x the input price. Cache reads cost 0.05x, the rate of Sonnet 5.5.
- DensePack packs each file into an image of 500 tokens.

| Message | Without DensePack | With DensePack |
| --- | --- | --- |
| 1 | write 1,000 at 2x = 2,000 | write 500 at 2x = 1,000 |
| 2 | read 1,000 + write 1,000 = 2,050 | read 500 + write 500 = 1,025 |
| 3 | read 2,000 + write 1,000 = 2,100 | read 1,000 + write 500 = 1,050 |
| Total after 3 | 6,150 | 3,075 |
| Total after 10 | 22,250 | 11,125 |
| Total after 50 | 161,250 | 80,625 |
| Total after 100 | 447,500 | 223,750 |

The cache read grows with each message because Claude Code sends all the earlier messages again with each message. In this example, DensePack halves each cache write and each cache read after it.

Agents often take more than one turn for one prompt. The model reads the whole conversation from the cache again on every turn, which repeats the saving of each smaller image. In the [code trace](#opus-55), the runs with DensePack 2.0 read 2.3 to 4.5 million tokens from the cache. The runs without it read 7.0 to 11.6 million.

<br>

---

<br>

## How Anthropic bills

Anthropic bills per million tokens (MTok). The price depends on the model.

| Model | Input (1x) | Cache write, 1 hour (2x) | Cache write, 5 minutes (1.25x) | Cache read | Output (5x) |
| --- | --- | --- | --- | --- | --- |
| <strong>Fable 5.1</strong> | $10 | $20 | $12.50 | $0.25 (0.025x) | $50 |
| <strong>Opus 5.5</strong> | $4 | $8 | $5 | $0.20 (0.05x) | $20 |
| <strong>Sonnet 5.5</strong> | $2 | $4 | $2.50 | $0.10 (0.05x) | $10 |

<sub>The prices come from the <strong>Model pricing</strong> table on <a href="https://platform.claude.com/docs/en/about-claude/pricing">Anthropic's pricing page</a>.</sub>

- The multipliers apply to the base input price. The cache read price is not a part of the 2x cache write price.
- `cache_creation_input_tokens` are the input tokens that Claude Code writes to the cache. They cost 2x the base input price in the 1-hour cache and 1.25x in the 5-minute cache.
- In the Opus 5.5 runs, Claude Code wrote the main conversation to the 1-hour cache. In the Sonnet 5.5 subagent runs, it wrote the conversation of each subagent to the 5-minute cache.
- Claude Code sends the whole conversation on each turn. The cache contains the part that repeats. Anthropic bills that part at the `cache_read_input_tokens` price.
- Without a cache, Anthropic bills the whole conversation at the base input price on each turn.

<br>

---

<br>

## Exact values

Opus 5.5 copied these values correctly from images of Bash output:

- 167 of 168 hex hashes
- 160 of 160 numbers of 8 to 17 digits
- 96 of 96 temp folder names

Numbers of 18 digits or more are the exception. Opus 5.5 got 2 of 64 of them wrong, so DensePack sends those lines as exact text.

The text of each image stays on disk.

- For a Read, that text is the file itself.
- Command output, Word files and the files of `.claude/densepack-vault/to-pack/` also get a text copy on disk. The key row of each image has the copy's name after `file=`, so the agent can Grep it for an exact string.
- The briefs and reports of subagents keep their text in a `.txt` file beside the image.
- The CLAUDE.md, CLAUDE.local.md, AGENTS.md, rules and MEMORY.md files keep their text in a `.bakpack` file beside them.

The text is saved as a fallback in case the agent ever needs to read text.

- Reads with offset N and limit 1 also return line N as text. N is the green line number in the image.

Reads of 20 lines or fewer stay text, so the agent can pull a few exact lines cheaply. `LINE_PULL_MAX` in `plugin/scripts/common.py` sets that limit of 20 lines.
