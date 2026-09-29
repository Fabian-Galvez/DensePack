# DensePack benchmarks

Each bench gives the same task to the same model twice, once with DensePack and once without it. The price of a run is what Anthropic bills for the whole conversation.

<br>

---

<br>

## Benches, 29 September 2026

The three tasks below run on a frozen copy of the DensePack scripts, with 28 files and 23,993 lines. Anthropic's eval command, `claude plugin eval`, ran each task with the plugin and without it. It graded each run and reported the price of each run. The suite ships with the plugin in [plugin/evals/](plugin/evals/), so you can run it again.

Each pair is one run with DensePack and one run without it. The runs used Opus 5.5 and Claude Code 2.1.284 in WSL2, one session at a time. Each DensePack run passed with a score of 1.00.

![The mean price of the DensePack runs as a share of the runs without it, for the three benches](images/savings-benchmarks.svg)

### The code trace

The agent traces how a Read becomes an image, through about 20,000 lines of the scripts, and writes the trace in ANSWER.md. 26 regex checks grade the answer.

| Run | With DensePack | Without DensePack | Result |
| --- | --- | --- | --- |
| 1 | $2.8890, 59 turns, 473 s | $5.2025, 64 turns, 518 s | saved 44.5% |
| 2 | $2.8715, 60 turns, 521 s | $4.3687, 45 turns, 385 s, score 0.96 | saved 34.3% |
| 3 | $3.5991, 78 turns, 638 s | $4.5574, 47 turns, 454 s | saved 21.0% |
| 4 | $2.7325, 58 turns, 476 s | $4.7469, 53 turns, 442 s | saved 42.4% |
| 5 | $3.5110, 71 turns, 623 s | $4.4276, 53 turns, 465 s | saved 20.7% |

The runs with DensePack wrote 129,513 to 155,980 new tokens to the cache, and the runs without it wrote 249,319 to 282,374. The runs with DensePack read the cache again for 4.6 to 6.7 million tokens, and the runs without it read 7.0 to 10.6 million. The runs with DensePack wrote 38,400 to 50,082 output tokens, and the runs without it wrote 35,192 to 46,637. Images do not make the output smaller.

### The architecture doc

The agent reads 14 hook scripts, about 8,700 lines, and outputs ARCHITECTURE.md. For each script, the doc gives the hook event, what the script does and which scripts it imports. 18 regex checks grade the doc.

| Run | With DensePack | Without DensePack | Result |
| --- | --- | --- | --- |
| 1 | $0.5120, 8 turns, 101 s | $0.5768, 8 turns, 93 s | saved 11.2% |
| 2 | $0.5807, 10 turns, 107 s | $1.2555, 35 turns, 166 s | saved 53.7% |
| 3 | $0.5150, 8 turns, 87 s | $0.9433, 21 turns, 126 s | saved 45.4% |
| 4 | $0.5002, 9 turns, 91 s | $0.5417, 10 turns, 91 s | saved 7.7% |
| 5 | $0.6240, 9 turns, 120 s | $1.0545, 14 turns, 121 s | saved 40.8% |

The runs without DensePack vary more. In runs 2, 3 and 5, they read more of the code as text, took 14 to 35 turns and cost $0.94 to $1.26. In runs 1 and 4 they took 8 and 10 turns and cost $0.54 to $0.58. Each run with DensePack took 8 to 10 turns.

### Five files read whole

The agent reads five scripts whole, 5,586 lines, and writes a 5-line summary of them in ANSWER.md. Six regex checks grade the summary against facts from the code. Five checks each test one fact about one script. The sixth check fails a summary that gives the old design of `drop_read_gate.py`.

| Run | With DensePack | Without DensePack | Result |
| --- | --- | --- | --- |
| 1 | $0.6214, 4 turns, 71 s | $1.0043, 4 turns, 30 s | saved 38.1% |
| 2 | $0.6246, 4 turns, 73 s | $1.0214, 4 turns, 31 s | saved 38.8% |
| 3 | $0.6260, 4 turns, 75 s | $1.0217, 4 turns, 34 s | saved 38.7% |
| 4 | $0.6215, 4 turns, 69 s | $0.9979, 4 turns, 32 s | saved 37.7% |
| 5 | $0.6243, 4 turns, 72 s | $1.0058, 4 turns, 34 s | saved 37.9% |

Every run read all five files and took 4 turns. Every summary passed all six checks. The runs with DensePack wrote 62,720 to 62,856 new tokens to the cache, and the runs without it wrote 117,005 to 119,103. The runs with DensePack wrote 4,814 to 5,044 output tokens, and the runs without it wrote 1,477 to 1,796. The runs with DensePack wrote more output because they read each later image of a file with a separate Read call.

### Run the benches yourself

The cases use Bash, so they need a sandbox. Linux, macOS and WSL2 have one. Run this command in a folder that holds the plugin.

```
claude plugin eval ./plugin --tag bench --runs 5 --scaffold --allow-tools Bash Write Edit --model claude-opus-5-5 -j 1
```

- `--scaffold` runs the `setup.sh` of each case. The script copies the frozen scripts into the empty workspace.
- `--allow-tools Bash Write Edit` grants the tools that the tasks need.
- `-j 1` runs one session at a time. Each DensePack session packs the 28 scripts with several processes. On a computer with 8 GB for WSL, two of these sessions at once made the eval lose runs.
- The first run asks you to trust the `plugin` folder. The eval runs the hooks of the plugin and the `setup.sh` of each case on your computer. Claude Code asks for this trust for each folder, so an installed copy of DensePack does not count. In a script or in CI, add `--trust-plugin` to the command to trust the folder.

The report gives the score and the price of each run in each arm. Prices change from run to run, so compare each pair and run 5 or more of each.

<br>

---

<br>

## Where DensePack does not save

The same `claude plugin eval` command ran 15 short tasks on Opus 5.5, each 5 times with DensePack and 5 times without it. Each run could use Bash, and each run did its task correctly. The table gives the price of each run in run order.

### Short tasks, 28 September 2026

| Task | 5 runs with DensePack | 5 runs without DensePack |
| --- | --- | --- |
| Find 2 values in a Python file of 94 KB | $0.1073, $0.1080, $0.1067, $0.1076, $0.1064 | $0.2844, $0.0822, $0.0805, $0.0804, $0.2838 |
| Find which of 5 Python files defines a function | $0.0887, $0.0905, $0.0892, $0.0888, $0.0898 | $0.0989, $0.0977, $0.1408, $0.0985, $0.0991 |
| Fix a bug in a folder of 10 hook scripts | $0.1331, $0.1358, $0.1454, $0.1345, $0.1388 | $0.1588, $0.1581, $0.1738, $0.1570, $0.1707 |
| Answer 5 questions about 32 Python files | $0.0990, $0.0992, $0.1317, $0.1340, $0.1300 | $0.1746, $0.1246, $0.1159, $0.1700, $0.1092 |
| Fix a second bug in the 10 hook scripts | $0.1113, $0.1104, $0.1081, $0.1094, $0.1087 | $0.1052, $0.1205, $0.1183, $0.1282, $0.1247 |
| List each constant set to a number in the 10 hook scripts | $0.1132, $0.1234, $0.1107, $0.1181, $0.1250 | $0.1212, $0.1232, $0.1363, $0.1354, $0.1164 |
| Find 2 facts in a Word file | $0.0898, $0.0901, $0.0896, $0.0884, $0.0879 | $0.0902, $0.0911, $0.0896, $0.1013, $0.0904 |
| Answer 5 questions about 16 Python files | $0.1282, $0.1294, $0.1174, $0.2937, $0.1226 | $0.1421, $0.1622, $0.1748, $0.1257, $0.1896 |
| Rename a function in the 10 hook scripts | $0.1175, $0.1218, $0.1232, $0.1475, $0.1104 | $0.1207, $0.1270, $0.1312, $0.1163, $0.1206 |
| Find 3 values in a Markdown file | $0.1131, $0.0983, $0.0978, $0.1179, $0.1146 | $0.1091, $0.1082, $0.1015, $0.1073, $0.1072 |
| Copy one function of a GDScript file with its tabs | $0.1154, $0.1463, $0.1135, $0.1214, $0.1240 | $0.1063, $0.1136, $0.1373, $0.1094, $0.1422 |
| List each call of a function in the 10 hook scripts | $0.1267, $0.1170, $0.1186, $0.1110, $0.1140 | $0.1131, $0.1161, $0.1125, $0.1144, $0.1164 |
| Find 2 values in a Python file of 116 lines | $0.0997, $0.1000, $0.0997, $0.0988, $0.0999 | $0.0921, $0.0927, $0.0932, $0.0959, $0.0920 |
| Copy 6 lines of a Python file exactly | $0.1082, $0.1064, $0.0976, $0.0915, $0.0992 | $0.0833, $0.0827, $0.0831, $0.0839, $0.0828 |
| Copy an HTML file with one change | $0.1108, $0.1093, $0.1087, $0.3128, $0.1217 | $0.1077, $0.1114, $0.1096, $0.1177, $0.1104 |

DensePack sends text as an image only when its estimate says that the image costs fewer tokens than the text. It packs the files that the agent Reads, Bash output of 400 characters or more, Word files, the CLAUDE.md, CLAUDE.local.md and MEMORY.md files, and the briefs and reports of subagents. The saving grows with the length of that text. In the task on the Python file of 94 KB, 2 runs without DensePack read the whole file as text and cost $0.2844 and $0.2838. The other 3 runs without DensePack searched the file with `grep` and cost $0.0804 to $0.0822. Each run with DensePack read the first image of the file, then searched it with `grep`, and cost $0.1064 to $0.1080.

### Why some short tasks cost more with DensePack

In the task that copies 6 lines of a Python file and in the task that finds 2 values in the Python file of 116 lines, each run with DensePack cost more than each run without it. In the tasks that find 3 values in a Markdown file, copy a GDScript function, copy an HTML file, rename a function and list each call of a function, the prices of the runs with DensePack and without it overlap. These seven tasks need 6 lines, 2 or 3 values, 17 lines, one button, one rename or one list of calls. They end after 2 to 7 turns, and five of them work on one file of 25 to 222 lines. The extra cost has three causes.

- **The session note.** The note adds 569 tokens to the first turn of each session. On Opus 5.5 it costs $0.0046 in the first turn and $0.0001 in each later turn. In six runs with DensePack, the agent made the same steps as in the runs without it, and DensePack added only its note. These are run 3 of the task that lists calls, run 3 of the rename, runs 2 and 5 of the GDScript copy, run 5 of the HTML copy and run 4 of the 6-line copy.
- **Extra steps with DensePack.** In the task that copies 6 lines of a Python file, 4 of the 5 runs with DensePack read 10 or 20 lines with the Read tool, and each run without DensePack used one `sed` command. Those Reads saved nothing, because DensePack keeps a Read of 20 lines or fewer as text. In the task that lists each call of a function, runs 1 and 2 with DensePack printed code ranges with `sed`. In the task that finds 2 values in the Python file of 116 lines, each run with DensePack read the image and then ran `grep` for the 2 values. That check added one turn, about $0.0065 in each run.
- **Causes outside DensePack.** In the HTML task, Claude Code denied the `sed` and `cp` commands of run 4 with DensePack, and the agent wrote the whole file with Write. That run cost $0.3128. In the rename task, run 4 with DensePack deleted the `__pycache__` folder that its own `py_compile` check made. In the Markdown task, runs 1, 4 and 5 with DensePack searched the DensePack code, because the Markdown file says that it is out of date, and the runs without DensePack searched only the task folder.

### Bug hunts and edits, 29 September 2026

When the agent hunts a subtle bug or makes many Edits, DensePack can cost more. The model writes more output when it reasons over code in images, and Anthropic bills output at 5x the input price.

- In a bug hunt of one Python file of 587 lines, each of 10 runs found the bug. The 5 runs with DensePack wrote 6,844 to 10,762 output tokens and cost $0.3072 to $0.3972. The 5 runs without it wrote 3,669 to 5,833 output tokens and cost $0.2561 to $0.3454. At a text size of 24 px in place of 17 px, the runs with DensePack still wrote 4,388 to 8,615 output tokens.
- In a pre-release review of 10 hook scripts with 3 planted bugs, the runs with DensePack wrote 19,743 to 35,550 output tokens against 11,848 to 17,046 without it, and cost more in 5 of the 10 pairs of two batches of 5.
- When an agent copies a block of several lines from an image into an Edit, it can put a line break in the wrong place, and the Edit fails. In five bug-fix and feature tasks, 12 of 103 lines that Opus 5.5 copied from images into Edits were wrong, and 0 of 44 when it copied from text. The session note now tells the agent to Read the lines it will change as text before an Edit.

<br>

---

<br>

## Accuracy

Sonnet 5.5 answered 15 of 15 questions from images at high effort and 15 of 15 at medium effort, the same as Opus 5.5.

### Python rebuild, 28 September 2026

The model reads the Python script of the [byte identical rebuild](#file-rebuilds-25-september-2026) as an image and writes the file again from the image. Sonnet 5.5 and Opus 5.5 each ran 10 times at medium effort.

| Result | Sonnet 5.5 | Opus 5.5 |
| --- | --- | --- |
| Byte identical | 1 of 10 | 5 of 10 |
| Each word right and the same Python program | 8 of 10 | 10 of 10 |
| Character match | 98.8% to 100% | 98.5% to 100% |

- The character match is the similarity of the new file to the source file, as the `difflib` module of Python measures it.
- In the runs that have each word right but are not byte identical, the only differences are line breaks that moved inside the docstring at the top of the file.
- In one Sonnet 5.5 run the model changed the words of one `print` line. In another run it put the end of a comment on a new line without its `#`, and that line is a syntax error.
- In one more Sonnet 5.5 run at high effort, the one error is a line that ends 2 words early, and the character match is 99.96%.

For work that copies whole files exactly, type /max-off to send Sonnet text.

### File rebuilds, 25 September 2026

The model reads one file as an image and writes the file again from that image. Runs pass when the new file is byte for byte identical to the source file. Opus 5.5 at medium effort ran 100 times on each file.

| File | Lines | Indent | Text tokens | Image tokens | Saving | Passes | Price of each run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Markdown prose | 115 | spaces | 1,855 | 886 | 52% | 100 of 100 | $0.1551 to $0.1991 |
| Python script | 116 | spaces | 1,859 | 834 | 55% | 73 of 100 | $0.1608 to $0.2599 |
| HTML email template | 25 | spaces | 2,360 | 1,150 | 51% | 63 of 100 | $0.1911 to $0.2483, and $0.0697 to $0.0859 for the 10 runs that the safety classifier stopped |
| GDScript game code | 222 | tabs | 2,790 | 1,430 | 49% | 65 of 100 | $0.2339 to $0.3420 |

The failed runs had these errors.

- In the Python script, all 27 failed runs have a wrong count of spaces. In 19 of them, the model writes 12 spaces on a line that has 14.
- In the HTML email template, 27 failed runs have a wrong count of spaces. In 10 more runs, a safety classifier stopped the model before it wrote the file.
- In the GDScript game code, 18 failed runs have only a wrong count of tabs or spaces. 17 failed runs change the text. The model adds a lone "#" line after line 3 in 8 runs and a period on line 42 in 10 runs, and 2 runs have the two changes. One more run changes only line 46.

No run changed a word in the Markdown, Python or HTML file.

The image uses these marks.

- Green numbers inside a black outline box are the line number of the literal text file.
- Red numbers in a box count spaces. Red 0s mean no spaces.
- Boxes with one blue `\t` mean 1 tab. Boxes with a blue `\t` and a red `\t` mean 2 tabs. Blue `N\t` boxes mean N tabs, for 3 tabs or more.
- Green `N\n` boxes before a line number count blank lines.
- The key at the top of the first image names the marks. The file name is at the right end of the first key row.
- The key also names the digit `1`, the letter `l` and the pipe character `|`.
- Purple waves at the end of a row show that the line continues on the next row.
- In a file with tab indents, the band color behind a line shows its tab count.

### Subagent copy, 28 September 2026

The Opus 5.5 lead started one Sonnet 5.5 subagent that read 8 whole Python files and copied the first line of the docstring of each file. In 10 runs with DensePack, the subagent copied 78 of 80 lines exactly, and in 10 runs without DensePack it copied 80 of 80. In the two misses, the subagent typed "stalled agent" for "stalled subagent", and the image shows "subagent" clearly. The Sonnet 5.5 part of each run cost $0.050 to $0.055 with DensePack and $0.198 to $0.201 without it.

### Cost of each action, 28 September 2026

Opus 5.5 ran each action in two `claude -p` sessions, one with DensePack and one without it. Each number is the cache write of the turn after the action, which is the count of tokens that the action added to the conversation.

| Action | With DensePack | Without DensePack |
| --- | --- | --- |
| The session note, with no tool call | 569 more tokens in the first turn | 0 |
| Read, 72 lines, 2,794 characters | 686 | 1,352 |
| Read, 157 lines, 6,616 characters | 1,348 | 2,818 |
| Read, 507 lines, 22,024 characters | 1,378 (image 1 of 4, and a note that names images 2 to 4) | 9,037 |
| Read, 15 lines | 482 (text) | 484 |
| Bash `cat`, 6,616 characters | 1,444 | 2,474 |
| Bash `cat`, 22,024 characters | 1,819 (image 1 of 4, and a note that names images 2 to 4 and gives the exact text of the lines that a model can misread) | 7,946 |
| Bash `sed`, 60 lines | 887 | 1,379 |
| Bash `grep -n`, small output | 334 | 381 |
| Grep tool | 463 (text) | 389 |

The Grep result stays text in the two runs, and the cause of its 74 more tokens with DensePack is not known. One Read of 72 lines and 2,794 characters saved 666 tokens, more than the 569 tokens of the session note.

<br>

---

<br>

## How DensePack saves

Claude Code sends your messages, the CLAUDE.md, CLAUDE.local.md and MEMORY.md files, the files that the agent reads, Bash output, and the briefs and reports of subagents to the model as input tokens. Anthropic bills those tokens and writes them to the cache, and each later turn reads them again from the cache.

When the agent reads a text file, DensePack packs the file into an image, and the agent gets the image only when DensePack's estimate says that the image costs fewer tokens than the text. Files under 1,000 bytes, files over 1,000,000 bytes and files with a null byte stay text. Files also stay text when the font has no glyph for more than 2% of their characters that are not spaces, such as files in Chinese, Japanese or Korean. Files in a `.claude` folder or in a folder with sandbox or scratch in its name stay text too. The agent reads and caches the image in place of the text. DensePack does not trim or compress the text, and the image still uses about half the tokens of the text. In the byte identical rebuild, each image uses 49% to 55% fewer tokens than the text of its file.

- You pay the cache write one time, on the smaller image.
- Each later turn reads the smaller cache at the cache read price. That price is 0.1x of the input price on Sonnet 5.5, 0.05x on Opus 5.5 and 0.025x on Fable 5.1.
- The saving of each image grows with the number of turns after it.

<br>

---

<br>

### Models that get images

- Each Fable, Opus and Sonnet model gets images, for example Fable 5.1, Opus 5.5 and Sonnet 5.5. Each model gets the same image, with a font size of 17 px.
- Sonnet gets images while the maxpack setting is on. That setting is on by default. /max-off sends Sonnet text. In a turn that Reads more than 32 files or more than 700,000 bytes, Sonnet gets most of those files as text.
- Haiku gets text, except for some Word files and the files in `.claude/densepack-vault/to-pack/`, which DensePack packs into images for each model.
- The Sonnet results in [Accuracy](#accuracy) and [Subagent copy](#subagent-copy-28-september-2026) ran on Sonnet 5.5.

<br>

---

<br>

### Bash output

DensePack also packs Bash output of 400 characters or more into images.

- When Bash output needs more than one image, the tool result holds image 1 and a note that names the other images.
- Lines that a model can misread go beside the image as exact text. These are random IDs that mix capital and small letters and hold a capital I or a small l, `git --stat` bars, the dash rules that `pip list` prints, numbers of 18 digits or more, lines of only spaces or tabs, and a tab inside a line. The tab after a line number, as `cat -n` prints it, does not count.
- The output stays text when DensePack's estimate says that the images and those lines cost as many tokens as the text or more.

Opus 5.5 misreads some kinds of lines in images of Bash output. In a copy of the plugin without the rule, Opus 5.5 at medium effort read images of real Bash output and typed their text. It typed 76 of 108 random IDs with I or l wrong, each time with I and l swapped, and it miscounted 54 of 72 `git --stat` bars. It typed 106 of 108 IDs without I or l, 167 of 168 hex hashes and 160 of 160 numbers of 8 to 17 digits right. On that day, the rule matched a line in 597 of 8,274 Bash outputs of 400 characters or more from real sessions, 7%.

In another test, Opus 5.5 typed 33 of 34 packed Bash outputs from the image with each character right, apart from a final newline. The one miss is a space lost at the end of a row. With DensePack it answered 59 of 60 questions that ask for an exact string of packed output, and 50 of 51 when it used only the image. From text it answered 60 of 60.

<br>

---

<br>

### Subagents

At the start of each session, DensePack sends its session note to the lead when the lead gets images. It also sends the note to each subagent when the subagent starts, except to a Sonnet subagent after /max-off. Haiku subagents get the note too, but their Reads, their Bash output and their briefs stay text. DensePack packs a brief of 1,000 characters or more, or a subagent report, only when the plugin calculates that the image costs less than the text.

The lead opens a packed report with one Read, because the result of the Agent tool cannot carry an image. In one test, a hook on the Agent tool changed the result to other text, and the Opus 5.5 lead read that text. The same hook then put an image into the result in four shapes: an image block, the image shape of a Read result, the image shape of a Bash result, and a text block with an image block. Each time the lead got the original text of the subagent. Read results and Bash results can carry an image.

<br>

---

<br>

### More turns can still cost less

Each turn reads the whole conversation again from the cache. Because an image costs fewer tokens than its text, each later turn reads a smaller cache, and the image run can take more turns and still cost less.

In the [code trace](#the-code-trace), 4 of the 5 runs with DensePack took more turns than their pair, 58 to 78 turns against 45 to 53, and each still cost less.

The image run can also read less than the text run. When a file needs more than one image and the stack of those images fits in the largest image that the API does not shrink, a Read of the whole file returns the stack as one image. Otherwise the Read returns the first image and a note that names the other images, and the model can then open only the images it needs. The text run reads each file in full.

<br>

---

<br>

### What a file costs, message by message

In this example, each message sends one file of 1,000 tokens. A 1-hour cache write costs 2x the input price, and a cache read costs 0.1x. DensePack packs each file into an image of 500 tokens.

| Message | Without DensePack | With DensePack |
| --- | --- | --- |
| 1 | write 1,000 at 2x = 2,000 | write 500 at 2x = 1,000 |
| 2 | read 1,000 + write 1,000 = 2,100 | read 500 + write 500 = 1,050 |
| 3 | read 2,000 + write 1,000 = 2,200 | read 1,000 + write 500 = 1,100 |
| Total after 3 | 6,300 | 3,150 |
| Total after 10 | 24,500 | 12,250 |
| Total after 50 | 222,500 | 111,250 |
| Total after 100 | 695,000 | 347,500 |

The cache read grows with each message because each message reads all the earlier messages. In this example, DensePack halves each cache write and each cache read after it.

Agents often take more than one turn for one prompt, and each turn adds one more cache read. In the [code trace](#the-code-trace), the runs with DensePack read the cache again for 4.6 to 6.7 million tokens, against 7.0 to 10.6 million without it.

<br>

---

<br>

## How Anthropic bills

Anthropic bills per million tokens (MTok). Each model has its own price.

| Model | `input_tokens` (1x) | `cache_creation`, 1 hour (2x) | `cache_creation`, 5 minutes (1.25x) | `cache_read` | `output_tokens` (5x) |
| --- | --- | --- | --- | --- | --- |
| <strong>Fable 5.1</strong> | $10 | $20 | $12.50 | $0.25 (0.025x) | $50 |
| <strong>Opus 5.5</strong> | $4 | $8 | $5 | $0.20 (0.05x) | $20 |
| <strong>Sonnet 5.5</strong> | $2 | $4 | $2.50 | $0.20 (0.1x) | $10 |

<sub>The prices come from the <strong>Model pricing</strong> table on <a href="https://platform.claude.com/docs/en/about-claude/pricing">Anthropic's pricing page</a>. The Sonnet 5 benches used the same prices as Sonnet 5.5.</sub>

- The multipliers apply to the base input price. The cache read price is not a part of the 2x cache write price.
- `cache_creation_input_tokens` are the input tokens that Claude Code writes to the cache. A 1-hour cache write costs 2x the base input price, and a 5-minute cache write costs 1.25x.
- In the Opus 5.5 runs, Claude Code wrote the main conversation to the 1-hour cache, and in the Sonnet 5.5 subagent runs it wrote the conversation of each subagent to the 5-minute cache.
- Claude Code sends the whole conversation on each turn. The cache holds the part that repeats. Anthropic bills that part at the `cache_read_input_tokens` price.
- Without a cache, Anthropic bills the whole conversation at the base input price on each turn.

<br>

---

<br>

## Exact values

In a test, Opus 5.5 typed 167 of 168 hex hashes, 160 of 160 numbers of 8 to 17 digits and 96 of 96 temp folder names right from images of Bash output. DensePack puts each line of Bash output that holds a number of 18 digits or more beside the image as exact text.

The text of each image stays on disk. For a Read, that text is the file itself. Command output, Word files and the files of `.claude/densepack-vault/to-pack/` have a text copy that the key row of the image names after `file=`. The briefs and reports of subagents keep their text in a `.txt` file beside the image, and the CLAUDE.md, CLAUDE.local.md and MEMORY.md files keep their text in a `.densepack.bak` file beside them.

The note that DensePack sends at the start of each session tells the model to use that text only for an exact string that the image cannot give. The note names Bash commands such as grep -n, sed -n and head. Reads with offset N and limit 1 also give one line as text, where N is the green line number in the image.

DensePack does not pack a Read with a limit of 20 lines or fewer, and that Read stays text. `LINE_PULL_MAX` in `plugin/scripts/common.py` sets that limit of 20 lines.
