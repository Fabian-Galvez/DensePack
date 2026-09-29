---
type: regex
target: { source: file, path: ANSWER.md }
pattern: '(?:^|\n)(?=[^\n]*(?:bash_image))(?=(?:[^\n]*\n(?![ \t]*(?:[-*+|#>]|[0-9]+[.)])[^\n]*[.]py)){0,2}[^\n]*(?:MIN_CHARS|pick_note|(?<![0-9])(?<![0-9][.])400(?![0-9])(?!,[0-9]{3})))'
---
