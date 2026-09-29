---
type: regex
target: { source: file, path: ANSWER.md }
pattern: '_ONE_BAND|ONE_BAND_TINT|[Tt][Ii][Nn][Tt][Ss]\[0\]|(?:[Ss]ingle|[Ss]ame|[Uu]niform)[ -](?:band[ -](?:colou?r|tint)|tint)|[Oo]ne[ -](?:band[ -](?:colou?r|tint)|tint)(?![ -](?:per|for each|by))|(?:(?<![A-Za-z])(?:[Nn]ot|[Nn]o|[Nn]ever)(?![A-Za-z])|[Ii]nstead of|[Rr]ather than)[^\n]{0,40}(?:depth|nesting)|(?:[Ee]very|[Ee]ach|[Aa]ll)[^\n]{0,30}lines?[^\n]{0,40}(?:first|same|single|depth[- ]0)[^\n]{0,15}(?:tint|band|colou?r)'
---
