# Quick test kit

Three fresh chats answer the same four questions about DensePack from the same
five documents. One chat runs the plugin as installed and two run it off. Each
chat's conversation total is its result.

## The results

Test 3 is the baseline. It runs the plugin off and asks for the four answers
and nothing more, so it is what a user pays with no plugin in the chat. Every
saved figure below compares a row against test 3.

| Test | Input tokens | Dollars | Answer correct | Tokens saved against test 3 | Tokens saved per cent | Dollars saved against test 3 | Dollars saved per cent |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3, plugin off, plain, the baseline | 239,407 | 1.1839 | 4 of 4 | 0 | 0.0 | 0.0000 | 0.0 |
| 2, plugin off, delegated | 192,692 | 0.9535 | 4 of 4 | 46,715 | 19.5 | 0.2304 | 19.5 |
| 1, plugin on, minimal | 95,729 | 0.5152 | 4 of 4 | 143,678 | 60.0 | 0.6687 | 56.5 |

The off-delegated test ran with the plugin off and a prompt that carried the
delegation rules.

[Bar view of these rows](../quick_test_bars.html). The page reads the table above
at load, so it cannot disagree with it.

## How to run it

| Test | File | Setup |
| --- | --- | --- |
| 1 | `bench/tests/quick_test_on.md` | On, as installed |
| 2 | `bench/tests/quick_test_off_delegated.md` | `/densepack-off` first in that chat |
| 3 | `bench/tests/quick_test_off_plain.md` | `/densepack-off` first in that chat |

Open a fresh chat for each test and ask nothing else in it. Point the lead at
that test's file, or paste the prompt block out of it, and do the same one in
all three.

Each test file ends with its counting step. It runs
`python bench/own_transcript.py <test file>` to find the chat's own transcript,
then `python bench/session_cost.py <that transcript>`, and it puts the TOTAL
row's tokens and dollars into that test's row above.
