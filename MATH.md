# Math

Every number DensePack shows comes from four rules.

## The four rules

| Rule              | Value                                                                                                                |
| ----------------- | -------------------------------------------------------------------------------------------------------------------- |
| One token of text | 2.40 characters, measured against Anthropic's count_tokens endpoint, 31 August 2026                                  |
| One image         | Width / 28 rounded up, times height / 28 rounded up, plus 2 tokens                                                   |
| Type size         | Fable 5 reads 8 px, Opus 5 reads 10 px, Sonnet 5 reads 12 px, and Haiku always gets text. Smaller type makes a smaller image                     |
| The check         | The plugin counts both prices first. When the image would cost more than the text, the text passes through unchanged |

## One example

A 4,800 character report costs 2,000 tokens as text.
Drawn at 8 px it fits a 560 x 700 image: 20 x 25 patches, plus 2, is 502 tokens.
The pack saves 1,498 tokens, 75 per cent.

## Accuracy

Two cold readers answered 60 of 60 questions character for character,
with the plugin off and with it on.

## The savings

The three-test benchmark and its results are in
[bench/results/BENCHMARK.md](bench/results/BENCHMARK.md). The rerun steps are in
[bench/tests/quick_test.md](bench/tests/quick_test.md).
