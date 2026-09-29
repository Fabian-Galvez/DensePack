---
type: regex
target: { source: file, path: ANSWER.md }
pattern: '(?:[Tt]oken|[Cc]ost|[Pp]ric|[Cc]heap|CHARS_PER_TOKEN|image_cost|[Pp]atch)[^\n]{0,400}(?:\n[^\n]{0,400}){0,2}(?<![0-9])(?<![0-9][.])(?:1,?1(?:3[1-9]|4[0-9])|(?:190|50[6-8]|7(?:1[6-9]|2[0-3])))(?![0-9])(?!,[0-9]{3}(?![0-9]))|(?<![0-9])(?<![0-9][.])(?:1,?1(?:3[1-9]|4[0-9])|(?:190|50[6-8]|7(?:1[6-9]|2[0-3])))(?![0-9])(?!,[0-9]{3}(?![0-9]))[^\n]{0,400}(?:[Tt]oken|[Cc]ost|[Pp]ric|[Cc]heap|CHARS_PER_TOKEN|image_cost|[Pp]atch)'
---
