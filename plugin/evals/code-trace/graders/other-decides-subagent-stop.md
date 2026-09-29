---
type: regex
target: { source: file, path: ANSWER.md }
pattern: '(?:^|\n)(?=[^\n]*(?:subagent_stop))(?=(?:[^\n]*\n(?![ \t]*(?:[-*+|#>]|[0-9]+[.)])[^\n]*[.]py)){0,2}[^\n]*(?:report_pack_worth|report_floor_chars|read_turn_fee|[Rr]ead[- ]turn|[Dd]ollar))'
---
