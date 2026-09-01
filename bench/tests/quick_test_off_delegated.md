# Test 2, plugin off, delegated

## The setup

Type `/densepack-off` first in this chat, before anything else, and run this test after test 1. Type nothing else before the prompt.
Paste the block between the rules, or point the lead at this file, the same way in all three tests.

## The prompt

---
I am new to this repo and I need to understand DensePack well enough to explain it to someone else. The repo sits at
`<repo folder>`.

Read only these five files: `README.md`, `plugin/PARTS.md`, `plugin/README.md`, `tests/BENCHMARK.md` and `MATH.md`. Open no other
file of any kind, no source, no HTML, no scripts and no other markdown. If those five do not answer one of the questions below, say
so for that question instead of looking anywhere else.

Do not read the five yourself. Send one subagent per file, all at the same time, and run each one on Haiku 4.5, the cheap model,
because reading one named file is a small bounded job. Each one reads its file and sends back the facts
themselves, the names, the numbers and the conditions it finds, in the file's own words where the wording matters. Send back nothing
that merely describes what a file covers: a report saying a file explains something, without saying what it says, is no use to me.
Answer me from what they send back.

Write me a short summary that answers four things:

1. What does the plugin pack?
2. When does it refuse to pack, and what does it do instead?
3. How does it price what the text would cost against what the image costs?
4. How does it pick the size of the drawn text for the model that reads it?

Keep the whole answer under 300 words, four short paragraphs, one per question. If the documentation does not answer one of them,
say that for that one instead of filling the gap. I need this inside five minutes.
---

## The count

Run `cd <repo folder> && python bench/session_cost.py "$(python bench/own_transcript.py quick_test_off_delegated.md)"`.
`own_transcript.py` returns the chat whose first prompt names this file, which
is this chat, whatever else is open.
Put its TOTAL row's Tokens and Dollars into the test 2 row of the results table in
`bench/quick_test.md`. Do not open that page in this chat.
