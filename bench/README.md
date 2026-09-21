<!-- DensePack 1.1 -->
# Benches

Four benches. Three of them run two arms, one with DensePack off and one with DensePack on. The rebuild bench runs the on arm only. 

The off arm reads the files as text and the on arm reads them as images. 

To run them, open Claude Code in the top folder of this repository and say "Read bench/RUN-THE-BENCHES.md and run the benches for Sonnet".
That file explains all the steps, the rules for a valid pair and the math, for you and for your AI.

<sub>All benches run at high effort. Set `DENSEPACK_BENCH_EFFORT=high` before each command below.</sub>

| Bench | Task | Proves | Command |
| --- | --- | --- | --- |
| Single ~1000 token file | Read image and answer five questions from it. | Agents can read and understand images as accurately as text.<br><br>DensePack saves even with a single file. | `python bench/run_1file_bench.py <run name> <model id> bench/single-1000-token-file/task.txt --copy-from bench/single-1000-token-file --off --on 1 --key 18054707 densepack-ab.jsonl "25 August 2026" plan_watch "name the side, on or off, and when, before or after"` |
| 16-file | Read 16 plugin scripts as images and answer five questions | Compounding savings and accuracy. | `python bench/run_16file_32file_bench.py <model id> <run name>` |
| 32-file | Save across a longer conversation with 32 of the plugin's scripts | Compounding savings and accuracy. | `python bench/run_16file_32file_bench.py <model id> <run name> --bench thirty-two-file` |
| Byte identical rebuild | The reader rebuilds a file from the image alone | Ability to rebuild text files from an image. | `python bench/run_rebuild_bench.py run --bench <run name> --model <model id>` |

The benches load the plugin from this download's plugin folder. They measure the plugin that ships.

Run `python bench/check_bench_setup.py` first. 
It prints PASS when the plugin produces the pixels it ships, pixel md5 `fe3e6449f9e1`.
The file md5 is `ca66e198d2df` on Windows. Other Pillow builds compress the same pixels to other bytes.
The results below scored md5 `df949a325598`. That image differs only in the top line of the key row's two mark boxes. 
Then check a pair: `python bench/check_bench_pairs.py bench/rows/<run name>-rows.jsonl`.
A run writes its rows to `bench/rows/`. 
A scored run copies each answers file to `bench/session-2026-09-07/`.

## Results

A run counts when: 
- the two arms are valid, 
- the on arm got images and the off arm got text, 
- the on arm answers as many questions as the off arm, 
- the on arm costs less at the cold price. 

The billed price counts only when the two arms report the same first cache read. 
Turns and Reads do not decide whether a run counts because the price includes all turns.

Each row is one bench for one reader. 
Legs is the count of pairs for the 16-file and 32-file benches and the count of on arms for the single file bench. 
For the 16-file and 32-file benches, Saved, cold is the middle of the three pairs. [BENCHMARKS.md](../BENCHMARKS.md) lists each pair. 
For the single file bench, Saved, as billed is the middle of 100 runs. 
Score counts the correct answers of the on arm.

![Cost as billed for three readers on three benches, against the text arm](../images/savings-by-reader.svg)

### Fable 5.1

| Fable 5.1 bench | Legs | Saved, as billed | Saved, cold | Score |
| --- | --- | --- | --- | --- |
| 32-file | 3 | 71.5% | 71.1% | 15 of 15 |
| 16-file | 3 | 66.1% | 65.2% | 15 of 15 |
| Single file | 100 | 22.0% | 17.5% | 500 of 500 |
| Rebuild | 3 |  |  | py 0.9983, md 0.9991, html 0.9999 |

<sub>The rebuild bench has no off arm. Its score is the share of characters that match the source. Fable's three rebuilds differ from the source by one moved line break, one moved line break and one blank line.</sub>

### Opus 5

| Opus 5 bench | Legs | Saved, as billed | Saved, cold | Score |
| --- | --- | --- | --- | --- |
| 32-file | 3 | 73.7% | 73.3% | 15 of 15 |
| 16-file | 3 | 66.1% | 65.2% | 15 of 15 |
| Single file | 100 | 27.5% | 22.8% | 500 of 500 |
| Rebuild | 3 |  |  | html byte identical, py and md 99.8% or more |

<sub>The 32-file as billed figure is the one pair whose two arms started with the same cache. The cold figure is the middle of the three pairs. The md rebuild matches all characters and differs in line endings only.</sub>

### Sonnet 5

Sonnet answers as well as the other two readers and saves a different amount each run.

| Sonnet 5 bench | Legs | Saved, as billed | Saved, cold | Score |
| --- | --- | --- | --- | --- |
| 32-file | 3 | 70.8% | 70.4% | 15 of 15 |
| 16-file | 3 | 33.0% | 31.5% | 15 of 15 |
| Single file | 100 | 27.4% | 22.0% | 499 of 500 |
| Rebuild | 3 |  |  | py 0.9353, md 0.9886, html 0.9760 |

<sub>Sonnet answered 5 of 5 on the two arms in each of its six pairs. The Sonnet saving is between 25.8% and 72.7% because Sonnet reads all images on some runs and reads only the necessary images on other runs. Sonnet's rebuilds drop or swap a few words in each file.</sub>

Haiku missed all questions and hallucinated 100% of the time when asked to recreate a text file from an image or answer questions about it. It consistently made up text and lines, even with larger font images, claiming an image made from a file with 12 lines contained 67. 

This download does not hold the raw rows behind these tables. 

The two long tasks ask for all files in one turn. 
Without those words Sonnet read the 32 files in batches over nine turns and saved 13.9%. 
With them it read all files in one turn and saved 62.8%. 
All rows above ran on the task with those words. All readers read all files in one turn.

## Math

Four rules make all the numbers here. 
The plugin prices the text and the image with them before each Read and sends the text when the image costs more.

| Rule | Value |
| --- | --- |
| One token of text | 2.40 characters, measured against Anthropic's count_tokens endpoint |
| One image | width over 28 rounded up, times height over 28 rounded up, plus 2 tokens for the image block |
| Type size | One size. All images use a 17 px glyph for all readers |
| The check | The plugin prices the text and the image first. It sends the text when the image costs more |

| Example, bench/single-1000-token-file/subject-ab_run.py | Value |
| --- | --- |
| Characters | 4,461 |
| Text tokens | 1,859 |
| Image | 784 by 896 pixels, 28 by 32 patches |
| Image tokens | 898. That is 896 patches plus 2 |
| Saved | 961 tokens, 51.7% |

## Two prices

Each run has two prices for the same pair. 

The as billed price is what the API charged. 
A new conversation that starts within an hour of the last one starts warm. That price is the realistic one. 

The cold price charges the first turn's cache reads again, at the write rate minus the read rate. 
It removes the credit a warm start gives. Its saving is a few points below the billed saving. 

The billed price of a pair counts only when the two arms report the same first cache read. 
Different cache conditions credit one arm for luck. 
All tables above show the billed price and the cold price.

| Price | Field in the rows | What the number is |
| --- | --- | --- |
| As billed | `cli_cost` | What the API charged |
| Cold-priced | `money` | The price from the token counts, plus the first turn's cache reads at the write rate minus the read rate |

## One pair

One pair of the single file bench, `opus-one-v14-20`, shows the shape of each pair. 
Same question, same tools, one file as text on one arm and as an image on the other. 
The image arm wrote 145 output tokens where the text arm wrote 146. The image arm cached 1,997 tokens where the text arm cached 3,065.

| Tool result | Off arm | On arm |
| --- | --- | --- |
| Kinds | text | image |
| Images | 0 | 1 |
| Turns | 2 | 2 |
| Score | 5 of 5 | 5 of 5 |
| Output tokens | 146 | 145 |
| Cache write | 3,065 | 1,997 |
| First cache read | 974 | 974 |
| Billed | 0.036973 | 0.026264 |
| Cold-priced | 0.0450 | 0.0343 |

## Faults and fixes

| Fault | Fix | Date |
| --- | --- | --- |
| A reader read the lowercase p as a capital P at a thin stroke | The image uses Inter SemiBold, a heavier face | 11 September 2026 |
| A reader spent a thinking budget on the turn that reads the image and changed no answer | Each leg runs with the budget at zero | 10 September 2026 |
| The reading card described a mark the image no longer had | Each card names the marks the image has | 9 September 2026 |
| The layout search returned one image and left another on disk | The search converts on a work stem and encodes only the winner | 13 September 2026 |
| Three conversions of a 32-file read failed on a busy file name on Windows | The replace retries | 13 September 2026 |
| Fable dropped the l of `jsonl` before a closing quote on 5 of 100 legs | One more clear column before a closing quote | 13 September 2026 |
| Sonnet read the note that names a file's later images as a prompt injection and stopped at the first image | The note names the plugin, the file and each image in literal words | 13 September 2026 |
| A 20 KB file took 62 seconds to convert | The renderer caches each measurement, trials stay in memory and the widening trials compute without glyphs, 5.6 seconds now | 13 September 2026 |
| 32 conversion hooks of one Read waited the entire hook timeout on Windows' WMI service | No hook asks WMI. The freetype package asked it for the OS version when it loaded | 13 September 2026 |
| Each conversion hook committed 428 MB before it converted anything. 32 hooks filled the memory | OpenBLAS runs one thread, 59 MB a hook now | 13 September 2026 |
| A markdown file with a wide table row converts in 131 seconds into 30 images that cost more than the text | Open |  |
| A line number box can have no white between it and the character beside it | Open |  |
| One leg in ten truncates an answer where a row wraps | Open |  |

## Files

| File | What it runs |
| --- | --- |
| `run_1file_bench.py` | Runs the single file bench, one empty folder a leg |
| `run_16file_32file_bench.py` | Runs the 16-file and 32-file benches |
| `run_rebuild_bench.py` | Runs the byte identical rebuild |
| `run_bench_arm.py` | Runs one arm, prices it and scores its reply |
| `check_bench_pairs.py`, `check_bench_setup.py` | Check a run's rows and the plugin's image |
| `score_16file_32file_answers.py` | Scores the 16-file and 32-file answers |
| `price_bench_transcript.py`, `session_cost.py` | Price a leg |
| `sample-files/` | 32 scripts copied from an earlier version of the plugin. They are bench input only. The two long benches read them. The plugin does not run them. 16 of them are not in the plugin now. The other 16 differ from the plugin's scripts |
| `sixteen-file/`, `thirty-two-file/` | Each bench's task and file list |
| `single-1000-token-file/` | The single file task and its file |
| `byte-identical-rebuild/samples/` | The three input files the rebuild bench converts. Their own text can be out of date. The MATH.md sample opens with a superseded note |
