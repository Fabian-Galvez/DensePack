---
type: regex
target: { source: file, path: ANSWER.md }
pattern: '(?:^|\n)(?=[^\n]*(?:brief_pack))(?=(?:[^\n]*\n(?![ \t]*(?:[-*+|#>]|[0-9]+[.)])[^\n]*[.]py)){0,2}[^\n]*(?:brief_chars|BRIEF_FLOOR|WRITE_CHEAPEST|read_call_fee|[Rr]ead[- ]call|(?<![A-Za-z])[Ff]ees?(?![A-Za-z])|(?<![0-9.])1\.25(?![0-9])|(?<![0-9])(?<![0-9][.])1,?000(?![0-9])(?!,[0-9]{3})))'
---
