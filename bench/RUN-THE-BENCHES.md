# Run the DensePack benches

This file is for you and for your AI.
It explains the benches in plain words, so you can check what your AI does.

## Before you start

1. Install DensePack with the steps for your system in [INSTALL.md](../INSTALL.md).
2. When Claude Code asks for the install scope, choose any scope.
   Local scope does not bench better, and it does not make removal easier.
   Either scope downloads the same copy into `~/.claude/plugins`.
   `/plugin uninstall densepack` plus `/plugin marketplace remove densepack-marketplace` remove it either way.
3. Go into the folder the install made.
   On Windows:
   `cd $HOME\.claude\plugins\marketplaces\densepack-marketplace`
   On macOS and Linux:
   `cd ~/.claude/plugins/marketplaces/densepack-marketplace`
4. Start Claude Code:
   `claude`
5. When Claude Code asks about the folder, choose "Yes, I trust this folder".
6. Say which benches to run, for example:
   `Read bench/RUN-THE-BENCHES.md and run the benches for Sonnet.`
   Say Opus or Fable instead of Sonnet for another model.
   Say "run all the benches" for all three.
7. Say yes when Claude asks to start.
   Claude runs the single file bench first, then the 16-file bench, then the 32-file bench.
   A request for the 32-file bench runs all three, and a request for the 16-file bench runs the first two.
   It goes on to the next bench only when the image arm of the last pair scored 5 of 5.
   Claude reports the result of each pair when it finishes.

A copy of this repository you cloned yourself works the same way.

| What to expect when you run the benches                 | Value                                                        |
| ------------------------------------------------------- | ------------------------------------------------------------ |
| Time for all four benches, one model                    | About 10 minutes                                             |
| Memory on the first run                                 | Up to 5.1 GB                                                 |
| What each bench converts                                | Every file, cold, because each arm starts in an empty folder |
| First run on a machine                                  | Installs Pillow, freetype-py and NumPy when they are missing |
| Later runs                                              | Skip that install                                            |
| A second Read of an unchanged file, in your own project | Warm. DensePack reuses the images it saved                   |
| 32 files, warm against cold                             | 1.8 seconds against 71 to 80 seconds                         |

<sub>Measured with Opus 5 on a 12 core Windows machine. The <a href="../README.md#limits">Limits</a> section of the README holds the rest.</sub>

## 1. What a bench is

A bench gives one AI the same task twice.
The first time, DensePack is off, and the AI reads the files as text.
That run is the off arm.
The second time, DensePack is on, and the AI reads the same files as images.
That run is the on arm.
The two arms together make one pair.
The pair shows what each arm cost and how many questions each arm answered correctly.

| Word | What it names |
| --- | --- |
| Arm | One run of the task, with DensePack off or on |
| Pair | One off arm and one on arm of the same bench |
| Turn | One request Claude Code sends to the model |
| Cache read | Tokens Claude Code reuses from earlier requests, at a lower price |
| First cache read | The cached tokens an arm reused on its first request |
| As billed | The dollars Claude Code reported for an arm |
| Cold | The price with the first cache read charged as new tokens |

## 2. The four benches

| Bench | What the AI does | Folder |
| --- | --- | --- |
| Single file | Reads one Python file of about 1,000 tokens and answers the questions in its task | bench/single-1000-token-file/ |
| 16-file | Reads 16 scripts in one turn and answers the questions in TASK.txt | bench/sixteen-file/ |
| 32-file | Reads 32 scripts in one turn and answers the questions in TASK.txt | bench/thirty-two-file/ |
| Rebuild | Reads a file as an image and writes the file back out, character for character | bench/byte-identical-rebuild/samples/ |

The 16-file and 32-file benches copy their files from bench/sample-files/.
Those 32 scripts are copies of DensePack plugin scripts.
The rebuild bench has no off arm, because text rebuilds itself perfectly.

## 3. What your AI does, step by step

1. It tells you which benches will run and in what order.
2. It tells you that every pair uses your Claude plan or your API credits.
3. It waits for you to say yes.
4. It runs `python bench/check_bench_setup.py`, which must print PASS. On anything else it stops and shows you the output.
5. For each model it runs the single file bench first, then the 16-file bench, then the 32-file bench.
   A request for the 32-file bench runs all three, and a request for the 16-file bench runs the first two.
   A single file pair costs a few cents, so a fault on your machine costs little.
   It goes on to the next bench only when the image arm of the last pair scored 5 of 5.
6. It runs one pair of one bench for one model.
7. It checks that pair with bench/check_bench_pairs.py.
8. It tells you the result in plain words before it starts the next pair.
9. On DISCARD it stops and asks you whether to run the pair again or stop.
10. On PARTIAL it tells you why and goes on to the next pair.
11. On FAILS it tells you which questions the image arm missed, or how much more it cost.
    DensePack normally answers every question and costs less, so it stops and asks whether to investigate.
12. When a Sonnet pair fails, or saves less than the lowest Sonnet pair for that bench in BENCHMARKS.md, it gives you choices.
    You can type `/max-off`, so Sonnet reads text and DensePack stays on for every other model.
    You can run the pair again, because Sonnet sometimes reads every image and saves less.
    When the image arm scored 5 of 5, a third choice is "Savings are savings: MaxPack it!" Sonnet keeps images, which is the default, and the benches continue.
    You decide whether to continue.

"All the benches" means Sonnet first, then Opus, then Fable.
For each model the order is the single file bench, the 16-file bench, the 32-file bench, then the rebuild bench.

## 4. The commands

On Linux and macOS, type `python3` where this file says `python`.

Every command runs from the folder that holds README.md.
Put `DENSEPACK_BENCH_EFFORT=high` in front of every bench command in the Bash tool, so both arms think at the same effort.
In PowerShell, run `$env:DENSEPACK_BENCH_EFFORT = "high"` once before the commands.
Give every run a new name, such as `sonnet-single-1`.

| Model | Model id |
| --- | --- |
| Sonnet 5 | `claude-sonnet-5` |
| Opus 5 | `claude-opus-5` |
| Fable 5.1 | `claude-fable-5-1` |

| Bench | Command for one pair |
| --- | --- |
| Single file | `python bench/run_1file_bench.py <run name> <model id> bench/single-1000-token-file/task.txt --copy-from bench/single-1000-token-file --off --on 1 --key 18054707 densepack-ab.jsonl "25 August 2026" plan_watch "name the side, on or off, and when, before or after"` |
| 16-file | `python bench/run_16file_32file_bench.py <model id> <run name>` |
| 32-file | `python bench/run_16file_32file_bench.py <model id> <run name> --bench thirty-two-file` |
| Rebuild | `python bench/run_rebuild_bench.py run --bench <run name> --model <model id>` |

The words after `--key` are the correct answers to the single file questions.
`/maxpack` sends Sonnet images and it is the default. `/max-off` sends Sonnet text.
The on arm turns `/maxpack` on inside its own bench folder, so Sonnet gets images on that arm.
Your own projects keep their own setting.

One Sonnet 5 run took these times on a 12 core Windows machine.

| Bench | Time for one pair |
| --- | --- |
| Single file | 23 seconds |
| 16-file | 1 minute 40 seconds |
| 32-file | 2 minutes 43 seconds |

Check each pair with this command:

`python bench/check_bench_pairs.py bench/rows/<run name>-rows.jsonl`

The rebuild bench prints its own score: the share of characters that match the original file.

## 5. Where the token counts are

The plugin writes one row for each file it changes into an image.
The rows are in the bench folder of the run, at
`.claude/tmp/densepack-manifest.jsonl`.

Each row holds the file's characters, its tokens as text and its tokens as an image.
A row does not name the file.

The prices come from a different place.
Every price comes from the token counts the Anthropic API returned for each message of the arm.
Claude Code writes those counts into the arm's transcript, `~/.claude/projects/<folder>/<session id>.jsonl`, under `usage`.
`bench/price_bench_transcript.py` reads that file.
Read that file to report the tokens the images cut.
The bench folder for a run is `DensePack-arenas/<bench>/<run name>/` in your home folder.
A copy you cloned yourself, outside `.claude`, puts `DensePack-arenas` beside the copy instead.
The command shows that folder when it starts.

    python -c "import json;rows=[json.loads(l) for l in open('.claude/tmp/densepack-manifest.jsonl',encoding='utf-8') if l.strip()];print('text',sum(r.get('text_tokens') or 0 for r in rows),'image',sum(r.get('image_tokens') or 0 for r in rows))"

Keep that folder until you report the run.
The row files in `bench/rows/` and that file are the only record of a run.

## 6. When a pair counts

The checker ends with one word: COUNTS, PARTIAL, FAILS or DISCARD.

| Rule | Why the rule exists |
| --- | --- |
| Both arms finished with no error and no refused tool call | A broken run measures nothing |
| The off arm got no image, and the on arm got at least one | Otherwise the pair does not compare text with images |
| The on arm answered as many questions as the off arm | A cheaper wrong answer is not a saving |
| The on arm cost less than the off arm at the cold price | A pair that costs more saves nothing |
| Both arms started with the same first cache read | A warmer start makes the billed price of one arm lower by chance |

| Verdict | What it says about the pair |
| --- | --- |
| COUNTS | The pair counts at both prices |
| PARTIAL | The first cache reads differ, so the pair counts at the cold price only |
| FAILS | The on arm answered fewer questions, or it cost as much or more |
| DISCARD | An arm had an error, or the images went to the wrong arm, so the pair measured nothing |

The checker exits with code 0 on COUNTS and PARTIAL, and with code 1 on FAILS and DISCARD.
PARTIAL is normal for the 16-file and 32-file benches, because the image arm loads the plugin and starts with more cached tokens.
The single file scorer ignores letter case, so `densePack` scores the same as `densepack`.
The checker prints the turns and the Reads of each arm, and they never decide the verdict.
The price already counts every turn an arm takes.
The on arm can take more turns, or open only the images it needs, and still cost less.
In pair `sonnet-thirtytwo-1` the on arm took 6 turns and the off arm took 4.
Both arms answered 5 of 5, and the on arm cost 60.5% less at the cold price.

In pair `sonnet-sixteen-1` the off arm started with 0 cached tokens and the on arm with 1,964.
The cold price charges those 1,964 tokens as new tokens, so the cold price removes the difference.

## 7. The math

Saving in % = (off arm price - on arm price) / off arm price x 100.

Each arm has two prices.

| Price | Row field | What it means |
| --- | --- | --- |
| As billed | `cli_cost` | The dollars Claude Code reported for that arm |
| Cold | `money` | The price from the transcript tokens, with the first cache read charged again at the cache write rate minus the read rate |

The cold price removes the discount a warm cache gives.
`cold()` in bench/run_bench_arm.py computes it.
The token prices sit in `RATES` in bench/session_cost.py and in `rates()` in bench/price_bench_transcript.py.
Anthropic publishes the prices at https://platform.claude.com/docs/en/about-claude/pricing

| Token | Price |
| --- | --- |
| Input | The model's input price |
| 5 minute cache write | 1.25 times input |
| 1 hour cache write | 2 times input |
| Cache read | 0.1 times input, or 0.025 times input on Fable 5.1 |
| Output | The model's output price |

Claude Code writes a 1 hour cache for the main conversation on a Pro or Max plan.
It writes a 5 minute cache for subagents, and for everything on an API key.
Each transcript line records both kinds under `cache_creation`: `ephemeral_1h_input_tokens` and `ephemeral_5m_input_tokens`.

One real single file pair, run on Opus 5:

| | Off arm | On arm |
| --- | --- | --- |
| As billed | $0.036973 | $0.026264 |
| Cold | $0.0450 | $0.0343 |

As billed saving: (0.036973 - 0.026264) / 0.036973 x 100 = 29.0%.
Cold saving: (0.0450 - 0.0343) / 0.0450 x 100 = 23.8%.

Your AI should recompute at least one pair itself, from the transcript tokens and the published prices.
`cli_cost` is Claude Code's own figure, and it can differ from that sum by about a tenth of a cent.
If the numbers differ from the checker's, your AI shows you both.
Neither you nor your AI has to agree with the results table in README.md.
Report what the rows show, including a pair that saves nothing or costs more.
If a rule looks unfair to one arm, say which rule and why.

## 8. What you need

- Claude Code, with the `claude` command working in a terminal and logged in.
- Python 3, with Pillow, freetype-py and NumPy. The plugin's first session installs them.
- The repository folder from the start of this file. The benches load that folder's own plugin, so an installed copy changes no result.
- Plan usage or API credits. Every arm is a real Claude Code conversation.
- Memory. A 32-file on arm used about 5 GB while it converted 32 files.

Both arms switch any installed DensePack off with bench/settings/off-plugin.json.
The on arm loads this download's plugin folder with `--plugin-dir`.
Each arm runs in its own empty folder under `DensePack-arenas` in your home folder.

## 9. Where results land, and what each file does

| Result | Place |
| --- | --- |
| Rows of one run, for the checker | bench/rows/<run name>-rows.jsonl |
| Rows of one rebuild run | bench/rows/rebuild-<run name>-rows.jsonl |
| Every arm, one row a line | bench/rows/all-arms-rows.jsonl |
| The answers file of a scored arm | bench/session-2026-09-07/<run name>-<model id>-<arm>-answers.txt |
| The folders each arm ran in | `DensePack-arenas/` in your home folder |

| File | What it does |
| --- | --- |
| bench/check_bench_setup.py | Proves the plugin makes the same image the published results used |
| bench/run_1file_bench.py | Runs the single file bench |
| bench/run_16file_32file_bench.py | Runs the 16-file and 32-file benches |
| bench/run_rebuild_bench.py | Runs and scores the rebuild bench |
| bench/run_bench_arm.py | Runs one arm, prices it and scores it |
| bench/check_bench_pairs.py | Checks a pair and prints COUNTS, PARTIAL, FAILS or DISCARD |
| bench/score_16file_32file_answers.py | Holds the correct answers for the 16-file and 32-file benches and scores them |
| bench/price_bench_transcript.py | Reads the tokens of an arm's transcript and prices them |
| bench/session_cost.py | Holds the token prices |
| bench/settings/ | Turn DensePack off for the off arm and on for the on arm |
| bench/README.md | The published results |
