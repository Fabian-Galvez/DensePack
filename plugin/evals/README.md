# DensePack eval suite

These are the tasks of the DensePack benches. In each case, Claude Code gets a real
task on a frozen copy of the DensePack scripts, 28 files of Python and shell.
`bench/direct_pair.py` runs each task with `claude -p`, once with DensePack and once
without it, and scores the answer with the regex graders of the case.

| Case | The task |
| --- | --- |
| `architecture-doc` | Write ARCHITECTURE.md for 14 hook scripts: the hook event of each, what it does and what it imports |
| `code-trace` | Trace in ANSWER.md how a Read becomes the image that the agent gets, through about 24,000 lines of code. Then list the other hooks that call the same drawing code, which a change there can break |
| `five-files-read` | Read five whole scripts of 5,586 lines in all and write a 5-line summary of them in ANSWER.md |

Run one case from the repository folder:

```
python bench/direct_pair.py five-files-read --model claude-opus-5-5 --warm --out bench-five-1
```

- The script copies the frozen scripts into a new folder for each side, so your own files are not touched.
- The command prints the price, the API requests and the score of each side. The traces stay in the `--out` folder.
- [Run these benches yourself](../../BENCHMARKS.md#run-these-benches-yourself) contains the other cases and the Windows settings.
