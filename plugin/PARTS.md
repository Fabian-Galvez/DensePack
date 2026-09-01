# Parts

One line per shipped file.

## Top level

| File | Contents |
| --- | --- |
| .claude-plugin/plugin.json | The plugin's name and version for Claude Code |
| hooks/hooks.json | The 8 hook events and the script each one runs |
| BRIEFING.md | The rules a spawned agent receives with its brief |
| README.md | The two install commands |
| PARTS.md | This file |
| skills/densepack-method/SKILL.md | The packing method as a Claude Code skill |
| commands/ | The 14 slash commands, one file each |
| fonts/ | DejaVu Sans Mono, regular and bold, with its license |
| instructions/ | The instruction images the plugin draws for each model |

## Scripts

| File | Contents |
| --- | --- |
| densepack.py | The packing engine: text in, PNG out, prices both and refuses a losing pack |
| common.py | Shared helpers every other script imports |
| bootstrap.py | First run: installs Pillow, draws the instruction images |
| ensure_python.ps1, ensure_python.sh | Install Python when the machine has none |
| dpctl.py | Reads and writes every setting from the terminal |
| pointer.py | The markers, pointers and the pack manifest |
| bash_pack.py | Packs long Bash output |
| brief_pack.py | Packs an agent's brief at the size that agent's model reads |
| prompt_card.py | The opening card a session starts with |
| agent_floor.py | The size floor under which an agent report stays text |
| gate_cost.py | Prices a gate's advice and stands it down when direct work is cheaper |
| delegate_gate.py | Points hands-on work at a subagent |
| tier_gate.py | Points each job at the cheapest model that can do it |
| verify_gate.py | Points verification reads at a subagent |
| bash_gate.py, grep_gate.py, read_gate.py, subread_gate.py, source_gate.py, drop_read_gate.py | The per-tool gates that decide pack, pass or point |
| write_gate.py | Holds a doc write to the writing rules when /stylepack is on |
| literal_check.py | The writing-rule checks write_gate.py runs |
| jargon.txt | The word list literal_check.py reads |
| cache_watch.py | Watches the prompt cache and reports what a pack re-bills |
| run_once.py | Runs a step once per session |
| subagent_start.py | Packs the spawn context when an agent starts |
| subagent_stop.py | Packs the report when an agent finishes |
| session_end.py | Closes the session's records |
| stop_gate.py | The end-of-turn check that unfinished work gets named |
| watchdog.py | Flags an agent whose transcript stops growing |
