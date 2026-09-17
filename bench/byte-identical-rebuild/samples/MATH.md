> Superseded on 12 September 2026. Four claims in this file are wrong and
> `CLAUDE.md`, section "What the old documents get wrong", lists them.
> The current page arithmetic is in `PAGE-GEOMETRY.md` and
> `docs/HOW-DENSEPACK-WORKS.md`. This file stays because the README links it.

# Math

Every number DensePack shows comes from four rules.

## The four rules

| Rule | Value |
| --- | --- |
| One token of text | 2.40 characters, measured against Anthropic's count_tokens endpoint, 31 August 2026 |
| One image | Width / 28 rounded up, times height / 28 rounded up, plus 2 tokens |
| Type size | One size. Every code page draws a 9 px glyph for every reader. Haiku always gets text |
| The check | The plugin counts both prices first. When the image would cost more than the text, the text passes through unchanged |

The 28 is the patch grid. The plus 2 is the content block. Both come from
`PATCH` and `IMAGE_BLOCK` in plugin/scripts/densepack.py.

One size, stated plainly. `common.code_size()` returns `font.px.fable` for
every reader, and that value is 12. The layout is 1000 columns wide and the
page is 756, so the 12 px pick lands as a 9 px glyph. Fable, Opus and Sonnet
all read the same 9 px page.

`READER_SIZES` holds 10, 10 and 12. `READER_SIZES` sets the prose image size
and never sets the code page size.

## One example

tools/ab_run.py holds 4,461 characters.

As text it costs 1,859 tokens. 4,461 divided by 2.40.

As a page it draws 756 by 896 pixels for every reader.

27 patches across, 32 patches down, plus 2, is 866 tokens.

The page saves 993 tokens, 53.4 per cent.

Verified 9 September 2026 against the shipping code. `PATCH` is 28,
`IMAGE_BLOCK` is 2 and `CHARS_PER_TOKEN` is 2.4, all in
plugin/scripts/densepack.py. `MEASURED_MODELS` in plugin/scripts/common.py
is fable 10, opus 10, sonnet 12. Any model outside that set gets plain text,
which is why Haiku is never sent a page.

## The two API limits that shape every page

Both limits sit outside DensePack. The API applies them. Crossing either one
damages the picture the reader receives.

| Limit | Value | What happens past it |
| --- | --- | --- |
| Longest side | 1568 pixels | The API shrinks the picture. The shrink blurs the edges the ink curve just sharpened |
| File size | 512,000 bytes | The picture arrives as a JPEG, not the PNG that was drawn |

`page.edge`, `page.cap_w` and `page.cap_h` all hold 1568 in style.py.

Measured for the JPEG limit: a 202,948 byte page arrived as image/png. A
574,654 byte page arrived as image/jpeg. The JPEG copy carried 87,307 colours
where the drawn file holds 4,700.

Sonnet's page ships at 0.84 of its layout. A height cap of 2000 let a full
page of main.gd reach 1624 pixels, past the 1568 edge. A cap of 1840 lands at
1546. `page.code_height_by_reader` holds 1840 for Sonnet for that reason.
Measured 8 September 2026, recorded at style.py line 648.

Do not raise that cap and do not remove it.

## Page size and the limit

Width is fixed at 756 pixels. `page.code_width` sets it.

Height grows with the file until it hits a cap. `page.code_height` sets the
cap at 2000 pixels. `page.code_height_by_reader` lowers it to 1840 for
Sonnet. Past the cap the file takes a second page.

The 896 in the example above is the height ab_run.py needs. 896 is not the
limit.

## Page count

Every reader draws the same 9 px glyph, so a split comes from the height cap
alone. Sonnet's cap is 1840 where Fable and Opus get 2000, so Sonnet splits
sooner on the same file.

| File size | Fable | Opus | Sonnet |
| --- | --- | --- | --- |
| 4,461 bytes | 1 page | 1 page | 1 page |
| 7,524 bytes | 1 page | 1 page | 2 pages |
| 10,223 bytes | 2 pages | 2 pages | 2 pages |

Every page after the first costs the reader a whole Read turn.

## What the saving depends on

The token count above is the floor, not the result. Three things decide
whether a conversation really costs less.

- The reader must read the page with no struggle.
- A reader that struggles opens a thinking block. The thinking can cost more
  than the page saves.
- The page must cause about the same number of turns as raw text.

Measure a change as cash saved across a whole conversation, on an
on-against-off pair. Do not measure it as page size.

## Accuracy

The current page scores 10 of 10 on the five step task for Sonnet, measured
9 September 2026.

Older accuracy and savings figures were taken on earlier pages. They do not
describe what ships now.
