# DensePack benchmarks

In each A/B bench, the same task runs twice on the same model, once with DensePack and once without it. The price of a run is its tokens at the [Anthropic API prices](#how-anthropic-bills).

<br>

---

<br>

## DensePack 2.0, 10 October 2026

DensePack 2.0 has a start note of rules for less code and short replies. The note also names an image that maps the project's folders, files and the names in each file.

The savings below are against the price of the same task without either plugin, or against Ponytail 5 in the Ponytail table. When a saving is negative, the run cost more.

### DensePack's benches

DensePack 2.0 ran each bench 5 times on each setup on 10 and 11 October. The runs used Claude Code 2.1.296 on Windows, `claude -p`, Bash and no Grep or Glob.

The first table of each setup contains the averages from the README. The runs table below it contains the price of each run, and all counted runs scored full marks.

### Opus 5.5

| Bench | Without DensePack | DensePack 2.0 |
| --- | --- | --- |
| Five files read | $0.984 | $0.499, 49.3% |
| Architecture doc | $0.740 | $0.339, 54.2% |
| Read-in-full architecture | $1.810 | $0.874, 51.7% |
| Code trace | $4.737 | $2.455, 48.2% |

The price of each run:

| Run | Five files read | Architecture doc | Read-in-full architecture | Code trace |
| --- | --- | --- | --- | --- |
| 1 | $0.497 | $0.300 | $0.874 | $2.920 |
| 2 | $0.500 | $0.364 | $0.867 | $2.329 |
| 3 | $0.498 | $0.342 | $0.854 | $2.088 |
| 4 | $0.502 | $0.355 | $0.879 | $2.361 |
| 5 | $0.496 | $0.333 | $0.895 | $2.576 |

- Architecture doc saves the most, because the agent writes a long document there, and the rules make it shorter.
- In five files read, the agent reads 5 named files and writes a 5-line summary, so the rules have little to cut.
- Code trace is mostly reading, with 29 to 47 Reads in each run.

### Opus 5.5 main agent with a Sonnet 5.5 subagent

The Opus main agent gives the reading to one Sonnet 5.5 subagent, and DensePack 2.0 gives the rules to the subagent too. The savings are against Opus 5.5 without DensePack.

| Bench | Without DensePack | DensePack 2.0 with a Sonnet subagent |
| --- | --- | --- |
| Five files read | $0.984 | $0.287, 70.8% |
| Architecture doc | $0.740 | $0.333, 55.0% |
| Read-in-full architecture | $1.810 | $0.543, 70.0% |
| Code trace | $4.737 | $1.645, 65.3% |

The price of each run:

| Run | Five files read | Architecture doc | Read-in-full architecture | Code trace |
| --- | --- | --- | --- | --- |
| 1 | $0.276 | $0.330 | $0.651 | $1.637 |
| 2 | $0.286 | $0.302 | $0.525 | $1.592 |
| 3 | $0.301 | $0.339 | $0.535 | $1.279 |
| 4 | $0.287 | $0.377 | $0.482 | $1.909 |
| 5 | $0.288 | $0.317 | $0.521 | $1.806 |

- In the architecture doc, the subagent searched the scripts with Bash and read only the parts it needed, with 5 to 11 images.
- With no DensePack, the Opus main agent with a Sonnet subagent cost $0.892 on the architecture doc. Against that price, DensePack 2.0 saved 57.7% to 66.1%, 62.7% on average. That price leaves out an estimate of the cost of the eval's Bash sandbox.

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
| 1 | $0.256 | $0.224 | $0.458 | $2.287 |
| 2 | $0.256 | $0.201 | $0.539 | $2.262 |
| 3 | $0.254 | $0.184 | $0.540 | $2.512 |
| 4 | $0.257 | $0.213 | $0.498 | $2.582 |
| 5 | $0.257 | $0.219 | $0.474 | $2.208 |

- In the architecture doc, the agent searched the 14 scripts with Bash or read only their first lines.
- Code trace took 40 to 49 API requests.

These notes apply to all runs above.

- The runs with DensePack started with `claude -p` through `bench/direct_pair.py`, with the same tools that `claude plugin eval` offers, apart from Grep and Glob. DensePack ran with the two settings from [Install the plugin](README.md#install-the-plugin), so the agent had no Grep, Glob or PowerShell tool.
- The runs without DensePack ran earlier with `claude plugin eval` on Claude Code 2.1.284 to 2.1.293, with Grep and Glob. That tool turns on the Bash sandbox, which adds sandbox instructions to each request. Their prices here leave out the cost of those instructions.
- The Sonnet prices, with and without DensePack, count cache reads at $0.20 per million tokens, the price of `claude plugin eval`, so both sides use the same price. The Anthropic price list has $0.10, so at the list price Sonnet costs less than these tables show.
- The DensePack prices are averages of 5 runs. Without DensePack, the Opus prices average 10, 24, 5 and 7 runs, in the order of the tables. The Sonnet prices average 16, 25, 5 and 6 runs.

- Runs that missed a check are not counted, and they ran again.

### Opus 5.5 with each setup

![The price of one Opus 5.5 session without DensePack, with Ponytail, with DensePack 2.0, and with DensePack 2.0 and a Sonnet subagent](images/savings-benchmarks.svg)

The savings are against the price without DensePack. The DensePack and Ponytail prices are averages of 5 runs, and Ponytail 5.1.0 ran with Grep and Glob. In the last column, the Opus lead gives the reading to one Sonnet 5.5 subagent.

| Bench | Without DensePack | Ponytail 5.1.0 | DensePack 2.0 | DensePack 2.0 with a Sonnet subagent |
| --- | --- | --- | --- | --- |
| Five files read | $0.984 | $0.978, 0.6% | $0.499, 49.3% | $0.287, 70.8% |
| Architecture doc | $0.740 | $0.556, 24.9% | $0.339, 54.2% | $0.333, 55.0% |
| Read-in-full architecture | $1.810 | $1.577, 12.8% | $0.874, 51.7% | $0.543, 70.0% |
| Code trace | $4.737 | $4.263, 10.0% | $2.455, 48.2% | $1.645, 65.3% |

- Ponytail adds a start note of about 2,000 tokens: its rules and a list of the function names in the folder. It costs about $0.02 per run, and $0.03 on code trace.
- DensePack 2.0 adds a start note of about 2,300 tokens with its rules. The note names a project map image, 466 tokens for these 24 scripts, which the agent reads in its first turn.
- The prices of both tools already contain the cost of this extra text.

### Opus 5.5 with DensePack costs about as much as Sonnet 5.5

Without DensePack, Sonnet 5.5 costs about half as much as Opus 5.5 in these benches. With DensePack 2.0, Opus 5.5 costs about the same as Sonnet 5.5 without it, so you get Opus for about the price of Sonnet.

The savings are against Opus 5.5 without DensePack.

| Bench | Opus 5.5 without DensePack | Opus 5.5 with DensePack 2.0 | Sonnet 5.5 without DensePack |
| --- | --- | --- | --- |
| Five files read | $0.984 | $0.499, 49.3% | $0.498, 49.4% |
| Architecture doc | $0.740 | $0.339, 54.2% | $0.322, 56.5% |
| Read-in-full architecture | $1.810 | $0.874, 51.7% | $0.826, 54.4% |
| Code trace | $4.737 | $2.455, 48.2% | $2.706, 42.9% |

### Ponytail's benchmark

- [Ponytail's agentic benchmark](https://github.com/DietrichGebert/ponytail/blob/main/benchmarks/results/2026-10-07-agentic.md) has 39 tasks. They are 18 small tasks with a hidden check, 12 features in a FastAPI and React repo, 6 small apps and 3 learning examples.
- DensePack 2.0 ran each task 5 times on 10 and 11 October, with Opus 5.5 and Claude Code 2.1.296 on Windows. The agent had Bash and no Grep or Glob.
- Ponytail's own checks scored the runs. The DensePack 2.0 prices and lines are medians of the 5 runs of each task that passed every check. The Ponytail medians include all 5 of its runs, also the runs that failed a check.
- The Ponytail off and Ponytail 5 prices and lines are medians of 5 runs from Ponytail's results of 7 October 2026, on Claude Code 2.1.288. Ponytail off is the run with no plugin. Those runs had Grep and Glob and no Bash.
- Lines are the source lines of the delivered code. Tests do not count.
- The savings come from the prices in the table, so you can check them with the numbers shown.

With the median of 5 runs on both sides, DensePack 2.0 cost $4.767 against Ponytail 5's $5.443, 12.4% less. It was cheaper on 31 of the 39 tasks. It wrote 1,115 lines, and Ponytail 5 wrote 1,334.

On the 38 tasks where the run with no plugin finished, DensePack 2.0 cost 41.3% less than no plugin. On `vibe-md2html`, all 5 runs with no plugin timed out, so that task has no Ponytail off price.

The rows go from the biggest saving against Ponytail 5 to the smallest. The 8 tasks where DensePack 2.0 cost more are at the bottom.

| Task | Type | Ponytail off | Ponytail off lines | Ponytail 5 | Ponytail 5 lines | DensePack 2.0 | DensePack 2.0 lines | Saving against Ponytail 5 | Saving against Ponytail off |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `tmpl-fe-wizard` | repo feature | $0.678 | 311 | $0.214 | 90 | $0.124 | 53 | 42.1% | 81.7% |
| `tmpl-be-search` | repo feature | $0.244 | 31 | $0.221 | 29 | $0.162 | 23 | 26.7% | 33.6% |
| `tmpl-be-csv` | repo feature | $0.270 | 48 | $0.218 | 38 | $0.161 | 27 | 26.1% | 40.4% |
| `tmpl-be-archive` | repo feature | $0.353 | 99 | $0.269 | 59 | $0.199 | 59 | 26.0% | 43.6% |
| `vibe-md2html` | small app | timed out | 0 | $0.316 | 139 | $0.242 | 104 | 23.4% | no price |
| `vibe-shortener` | small app | $0.240 | 285 | $0.136 | 79 | $0.105 | 52 | 22.8% | 56.2% |
| `tmpl-be-bulkdelete` | repo feature | $0.338 | 35 | $0.230 | 21 | $0.182 | 21 | 20.9% | 46.2% |
| `tmpl-be-duplicate` | repo feature | $0.208 | 20 | $0.181 | 21 | $0.147 | 21 | 18.8% | 29.3% |
| `rate-limit` | hidden check | $0.147 | 44 | $0.144 | 26 | $0.119 | 26 | 17.4% | 19.0% |
| `open-mandelbrot` | learning example | $0.237 | 129 | $0.113 | 32 | $0.095 | 31 | 15.9% | 59.9% |
| `vibe-langgraph` | small app | $0.557 | 148 | $0.095 | 29 | $0.080 | 24 | 15.8% | 85.6% |
| `open-decorators` | learning example | $0.107 | 79 | $0.087 | 20 | $0.074 | 17 | 14.9% | 30.8% |
| `tmpl-fe-command` | repo feature | $0.431 | 319 | $0.269 | 131 | $0.231 | 101 | 14.1% | 46.4% |
| `vibe-password` | small app | $0.175 | 224 | $0.097 | 38 | $0.084 | 32 | 13.4% | 52.0% |
| `open-dataclass` | learning example | $0.110 | 84 | $0.106 | 51 | $0.092 | 41 | 13.2% | 16.4% |
| `vibe-todo` | small app | $0.157 | 197 | $0.106 | 45 | $0.092 | 36 | 13.2% | 41.4% |
| `vibe-csvstats` | small app | $0.150 | 124 | $0.102 | 47 | $0.090 | 36 | 11.8% | 40.0% |
| `trace-amount` | hidden check | $0.096 | 9 | $0.106 | 9 | $0.094 | 10 | 11.3% | 2.1% |
| `tmpl-fe-rating` | repo feature | $0.183 | 136 | $0.124 | 60 | $0.110 | 46 | 11.3% | 39.9% |
| `csv-sum` | hidden check | $0.133 | 58 | $0.111 | 17 | $0.099 | 15 | 10.8% | 25.6% |
| `sql-user` | hidden check | $0.093 | 9 | $0.089 | 7 | $0.081 | 6 | 9.0% | 12.9% |
| `conv-seam` | hidden check | $0.122 | 12 | $0.139 | 14 | $0.127 | 12 | 8.6% | -4.1% |
| `auth-token` | hidden check | $0.081 | 18 | $0.105 | 16 | $0.096 | 18 | 8.6% | -18.5% |
| `tmpl-fe-dropzone` | repo feature | $0.265 | 247 | $0.134 | 62 | $0.125 | 51 | 6.7% | 52.8% |
| `tmpl-be-count` | repo feature | $0.280 | 25 | $0.145 | 12 | $0.136 | 12 | 6.2% | 51.4% |
| `critic-email` | hidden check | $0.127 | 33 | $0.115 | 12 | $0.109 | 12 | 5.2% | 14.2% |
| `safe-path` | hidden check | $0.117 | 16 | $0.106 | 13 | $0.101 | 11 | 4.7% | 13.7% |
| `scope-format` | hidden check | $0.137 | 21 | $0.147 | 15 | $0.142 | 16 | 3.4% | -3.6% |
| `trace-transfer` | hidden check | $0.135 | 27 | $0.126 | 20 | $0.122 | 21 | 3.2% | 9.6% |
| `tmpl-fe-colorpicker` | repo feature | $0.199 | 135 | $0.111 | 26 | $0.110 | 24 | 0.9% | 44.7% |
| `scope-recipients` | hidden check | $0.154 | 13 | $0.159 | 4 | $0.158 | 6 | 0.6% | -2.6% |
| `reuse-slug` | hidden check | $0.091 | 20 | $0.103 | 21 | $0.104 | 19 | -1.0% | -14.3% |
| `conv-ui` | hidden check | $0.095 | 17 | $0.099 | 17 | $0.101 | 17 | -2.0% | -6.3% |
| `reuse-money` | hidden check | $0.083 | 9 | $0.096 | 9 | $0.098 | 9 | -2.1% | -18.1% |
| `conv-service` | hidden check | $0.099 | 7 | $0.089 | 4 | $0.093 | 4 | -4.5% | 6.1% |
| `scope-rename` | hidden check | $0.133 | 3 | $0.128 | 3 | $0.134 | 3 | -4.7% | -0.8% |
| `cache` | hidden check | $0.096 | 11 | $0.083 | 11 | $0.089 | 11 | -7.2% | 7.3% |
| `todo-null` | hidden check | $0.166 | 203 | $0.125 | 77 | $0.137 | 78 | -9.6% | 17.5% |
| `tmpl-fe-datepicker` | repo feature | $0.427 | 335 | $0.099 | 10 | $0.122 | 10 | -23.2% | 71.4% |
| **All 39** | | **$7.714, 38 tasks** | **3,541** | **$5.443** | **1,334** | **$4.767** | **1,115** | **12.4%** | **41.3%** |

DensePack 2.0 cost more on `cache`, `conv-service`, `conv-ui`, `reuse-money`, `reuse-slug`, `scope-rename`, `todo-null` and `tmpl-fe-datepicker`. These tasks are too small and have too few reads for DensePack's images to save more than its start note costs.

- Ponytail 5's median price on those 8 tasks is $0.099, and $0.126 on the other 31.
- The runs start with about 6,300 tokens that Claude Code, the rules and the map put in the first request. They cost about $0.051, which is 37% to 57% of the DensePack 2.0 price on those 8 tasks.
- The tasks on this benchmark have little to read, 0 to 5 images in each run. So the saving here comes mostly from the rules, which make the agent write less code and shorter replies.
- The 6 small apps start in an empty folder, so the agent read nothing. They still saved 11.8% to 23.4% against Ponytail 5.
- 7 of the 8 cost between 1.0% and 9.6% more. `tmpl-fe-datepicker` cost 23.2% more, $0.122 against $0.099.

On `scope-recipients`, every counted DensePack 2.0 run sent the digest as one message with the subscribers in Bcc, so it passed the privacy check. Both Ponytail arms passed that check in 2 of 5 runs. All counted runs passed every check, and a run that failed a check ran again.

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
- Haiku gets text. Haiku 5.5 got about 95% of the [bench checks](HOW-IT-WORKS.md#haiku-55-with-images-7-october-2026) right from images. Its misses were code facts such as which script imports which, so Haiku still gets text.
- Some Word files and the files in `.claude/densepack-vault/to-pack/` are the exception. DensePack packs them for all models, Haiku included.
- The Sonnet results in [Accuracy](HOW-IT-WORKS.md#accuracy) and [Subagent copy](HOW-IT-WORKS.md#subagent-copy-28-september-2026) ran on Sonnet 5.5.

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
