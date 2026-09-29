---
type: regex
target: { source: file, path: ANSWER.md }
pattern: '(?:_start_helpers|_draw_split|_draw_child|_shared_widths|[Hh]elper|[Pp]open|[Ss]ubprocess|[Cc]hild process)[^\n]{0,400}(?:\n[^\n]{0,400}){0,2}(?<![0-9])(?<![0-9][.])(?:5,?(?:456|5(?:00|22|3[6-9]|[4-9][0-9])|6(?:0[0-4]|2[1-9]|[346-9][0-9]|5[0-589])|7(?:[0-46-9][0-9]|5[014-9])|800))(?![0-9])(?!,[0-9]{3}(?![0-9]))|(?<![0-9])(?<![0-9][.])(?:5,?(?:456|5(?:00|22|3[6-9]|[4-9][0-9])|6(?:0[0-4]|2[1-9]|[346-9][0-9]|5[0-589])|7(?:[0-46-9][0-9]|5[014-9])|800))(?![0-9])(?!,[0-9]{3}(?![0-9]))[^\n]{0,400}(?:_start_helpers|_draw_split|_draw_child|_shared_widths|[Hh]elper|[Pp]open|[Ss]ubprocess|[Cc]hild process)'
---
