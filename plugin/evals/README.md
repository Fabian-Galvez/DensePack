# DensePack eval suite

These cases run with Anthropic's `claude plugin eval`. Each case gives Claude Code
a real task on a frozen copy of the DensePack scripts, 28 files of Python and
shell, and runs it with DensePack and without it. The report gives the score and
the price of each run in each arm.

| Case | The task |
| --- | --- |
| `realistic-architecture` | Write ARCHITECTURE.md for 14 hook scripts: the hook event of each, what it does and what it imports |
| `realistic-trace-large` | Trace how a Read becomes the image that the agent gets, through about 20,000 lines of code, and list the other hooks that call the same drawing code, in ANSWER.md |
| `realistic-read-files` | Read five scripts whole, 5,586 lines, and write a 5-line summary of them in ANSWER.md |

Run the suite from a folder that holds the plugin. The cases use Bash, so they
need a sandbox: Linux, macOS or WSL2.

```
claude plugin eval ./plugin --tag realistic --runs 5 --scaffold --allow-tools Bash Write Edit --model claude-opus-5-5 -j 1
```

- `--scaffold` runs each case's `setup.sh`, which copies the frozen scripts into the empty workspace.
- `--allow-tools Bash Write Edit` grants the tools that the tasks need.
- `-j 1` runs one session at a time. Each DensePack session packs the 28 scripts with several processes, and on a computer with 8 GB for WSL, two such sessions at once made the eval lose runs.
