# Benchmark

Three fresh chats answered the same four questions about this repo from
the same five documents. One ran the plugin as installed and two ran it
off. Each chat's whole bill is its row.

| Test | Input tokens | Dollars | Answer correct | Tokens saved against test 3 | Tokens saved per cent | Dollars saved against test 3 | Dollars saved per cent |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1, plugin on, default | 95,729 | 0.5152 | 4 of 4 | 143,678 | 60.0 | 0.6687 | 56.5 |
| 2, plugin off, delegated | 192,692 | 0.9535 | 4 of 4 | 46,715 | 19.5 | 0.2304 | 19.5 |
| 3, plugin off, plain, the baseline | 239,407 | 1.1839 | 4 of 4 | 0 | 0.0 | 0.0000 | 0.0 |

The rerun steps, the three test prompts and the counter are in
[quick_test.md](../tests/quick_test.md). Anyone with this repo can
run all three chats and count the same way.

## Accuracy

Two cold readers answered 60 of 60 questions character for character,
with the plugin off and with it on.

## The arithmetic

Every figure follows the four rules in [MATH.md](../../MATH.md): 2.40
characters a token, the image patch formula, the per-model type sizes,
and the check that refuses a losing pack.
