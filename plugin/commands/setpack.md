---
description: Set one DensePack option and its value. The options are on, off, receipts, totals, keep, reader, maxtier, stylecard, agentpack, agents, vault, status and help. No argument prints the settings.
argument-hint: "[option] [value]"
---

Run this exact command with the Bash tool, with the words the user typed after
the command name in place of $ARGUMENTS:

p=python; command -v python >/dev/null 2>&1 || p=python3; "$p" "${CLAUDE_PLUGIN_ROOT}/scripts/dpctl.py" $ARGUMENTS

Then relay the line the command printed to the user in one sentence.

Every DensePack setting has an option name here. The option is the first word
and the value is the second, exactly as `dpctl.py` takes them:

| Option and value | What it sets |
| --- | --- |
| `on`, `off` | Packing on, with the defaults back, or every hook stood down |
| `receipts` `default`, `verbose`, `light`, `quiet` | The receipt table shape |
| `totals` `on`, `off`, `auto` | The CONVERSATION TOTALS row |
| `keep` `images`, `reports`, `both`, `off`, and a folder | What copies survive the session |
| `reader` `auto`, `fable`, `opus`, `sonnet` | The pixel size the images are drawn at |
| `maxtier` `on`, `off` | Whether an Opus 5 lead may spawn Fable 5 |
| `stylecard` `on`, `off` | The writing rules on the standing reminder |
| `agentpack` `force`, `on`, `off`, `support` | How DensePack's delegation rules rank |
| `agents` | Prints who this session spawned, and on what model |
| `vault` and a megabyte number | Lists the vault, or sets its cap |
| `status` | Prints the current settings |
| `help` | Prints the whole option table, and which value is the default |

No other command sets `agentpack support` or `vault`.

Twelve commands folded into this one on 31 August 2026: `/agentpack-table`,
`/keeppack`, `/keeppack-off`, `/lightpack`, `/lightpack-off`,
`/maxpack-off`, `/receiptpack`, `/statuspack`, `/statuspack-off`,
`/totalpack`, `/totalpack-off` and `/verbosepack`. Each set a single
value, and no session record on this machine showed ten of them ever
being run. `/statuspack` and `/statuspack-off` went for a different
reason: the delegation table they governed lives in the receipt records
now, per conversation, beside the receipt rows, where reading it costs
the conversation nothing.
