"""Writes images/savings-benchmarks.svg and prints the savings of BENCHMARKS.md.

For each bench, the chart compares the Opus 5.5 price without DensePack, with Ponytail 5.1.0, with DensePack 2.0, and
with DensePack 2.0 and a Sonnet 5.5 subagent. It also prints these prices as a Markdown table.
Run it from the repository folder: python -I bench/savings_chart.py"""
import html
import re
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

# Bench: model: (runs without DensePack, runs with DensePack), in USD at the prices of claude plugin eval.
# The runs without DensePack are every eval run of the same prompt that has a recorded price. Sources in BENCHMARKS.md.
RUNS = {
    "Five files read": {
        "Opus 5.5": ([0.9979, 1.0043, 1.0214, 1.0217, 1.0058,          # 29 September, 2.1.284
                      1.009, 1.025, 1.019, 1.023, 1.006],              # 9 October, 2.1.293
                     [0.482669, 0.485020, 0.479940, 0.484003, 0.480643]),
        "Sonnet 5.5": ([0.5169, 0.5124, 0.5112, 0.5248, 0.5087,        # 4 October
                        0.5173, 0.5182, 0.5140, 0.5114, 0.5134,        # 5 October
                        0.510, 0.510, 0.512, 0.514, 0.511, 0.511],     # 9 October, 2.1.293
                       [0.238243, 0.236787, 0.237474, 0.236445, 0.234873]),
    },
    "Architecture doc": {
        "Opus 5.5": ([0.754, 0.504, 0.539, 0.748, 1.085,               # 9 October, 2.1.293
                      0.549, 0.684, 0.808, 0.725, 1.090,
                      0.778, 0.815, 1.244, 1.121, 0.656,
                      0.508, 0.929, 0.725,
                      0.5709, 0.6740, 0.7092, 0.7542, 0.7825, 0.9164],
                     [0.390856, 0.407268, 0.884911, 0.457238, 0.717689]),
        "Sonnet 5.5": ([0.2820, 0.4115, 0.3328, 0.3745, 0.3315,        # 4 October
                        0.3011, 0.2895, 0.3180, 0.3297, 0.3326,        # 5 and 7 October
                        0.325, 0.381, 0.361, 0.322, 0.327,             # 9 October, 2.1.293
                        0.358, 0.362, 0.509, 0.376, 0.315,
                        0.390, 0.327, 0.333, 0.290, 0.318],
                       [0.181442, 0.212597, 0.239466, 0.222370, 0.318981]),
    },
    "Read-in-full architecture": {
        "Opus 5.5": ([1.685, 2.501, 1.747, 1.658, 1.635],             # 9 October, 2.1.293
                     [0.937057, 0.887478, 0.893804, 0.899595, 0.913855]),
        "Sonnet 5.5": ([0.848, 0.832, 0.884, 0.876, 0.793],           # 9 October, 2.1.293
                       [0.439943, 0.445467, 0.471341, 0.441772, 0.467811]),
    },
    "Code trace": {
        "Opus 5.5": ([5.2025, 4.3687, 4.5574, 4.7469, 4.4276,          # 29 September, 2.1.284
                      4.667, 5.587],                                   # 9 October, 2.1.293
                     [2.606652, 3.133268, 2.945981, 2.559782, 3.150222]),
        "Sonnet 5.5": ([2.7767, 2.7263, 2.7360, 2.8812, 2.7849,       # 5 and 7 October, 2.1.289 and 2.1.293
                        2.620],                                        # 9 October, 2.1.293
                       [1.437517, 2.360198, 2.614949, 1.980767, 2.032690]),
    },
}

# The runs without DensePack ran with claude plugin eval, which turns on Claude Code's Bash sandbox. The sandbox adds its
# instructions to the start of each request: about 3,750 tokens on Claude Code 2.1.293 and 2.1.296, and about 3,000 on
# 2.1.284 to 2.1.289. Their first requests have 16,209 and 15,364 tokens, against 12,457 for the same tools with claude -p.
# The runs with DensePack and with Ponytail ran with claude -p and no sandbox, the same as a normal Claude Code session.
# The prices below take the sandbox tokens off each eval run: one 1-hour cache write, then one cache read per later request.
SANDBOX = {  # sandbox tokens of each run without DensePack, in the order of RUNS
    "Five files read": {"Opus 5.5": [3000] * 5 + [3750] * 5, "Sonnet 5.5": [3000] * 10 + [3750] * 6},
    "Architecture doc": {"Opus 5.5": [3750] * 24, "Sonnet 5.5": [3000] * 8 + [3750] * 17},
    "Read-in-full architecture": {"Opus 5.5": [3750] * 5, "Sonnet 5.5": [3750] * 5},
    "Code trace": {"Opus 5.5": [3000] * 5 + [3750] * 2, "Sonnet 5.5": [3000] * 2 + [3750] * 4},
}
OFF_REQUESTS = {"Five files read": 4, "Architecture doc": 12, "Read-in-full architecture": 8, "Code trace": 50}
WRITE = {"Opus 5.5": 8.0, "Sonnet 5.5": 4.0}  # 1-hour cache write, $ per million tokens
READ = 0.20  # cache read at the prices of claude plugin eval, $ per million tokens


def sandbox_cost(bench, model, tokens):
    return tokens * (WRITE[model] + (OFF_REQUESTS[bench] - 1) * READ) / 1e6


EVAL_RUNS = RUNS
RUNS = {b: {m: ([p - sandbox_cost(b, m, t) for p, t in zip(off, SANDBOX[b][m])], on) for m, (off, on) in per.items()}
        for b, per in EVAL_RUNS.items()}
for _b, _per in EVAL_RUNS.items():
    for _m, (_off, _on) in _per.items():
        assert len(_off) == len(SANDBOX[_b][_m]), (_b, _m)
# The chart shows Opus 5.5 on each bench: the average price without DensePack, Ponytail 5.1.0, DensePack 2.0, and
# DensePack 2.0 with an Opus lead that gives the reading to one Sonnet 5.5 subagent. Each list holds the price of each run.
OPUS = "Opus 5.5"
PONYTAIL = {"Five files read": [0.974702, 0.982883, 0.9860006, 0.973228, 0.9731778],
            "Architecture doc": [0.5598904, 0.49464, 0.480471, 0.479327, 0.7636842],
            "Read-in-full architecture": [1.5223788, 1.572377, 1.5587548, 1.680015, 1.5534774],
            "Code trace": [4.044022, 4.208957, 4.2307352, 4.3806602, 4.449936]}
DP2 = {"Five files read": [0.4965024, 0.5002164, 0.4981316, 0.5019438, 0.4960346],
       "Architecture doc": [0.2998858, 0.3635504, 0.342061, 0.3551044, 0.3332334],
       "Read-in-full architecture": [0.8741206, 0.8665606, 0.8538576, 0.8793146, 0.895286],
       "Code trace": [2.920332, 2.3290042, 2.0881588, 2.3610718, 2.5758684]}
SUBAGENT = {"Five files read": [0.2756044, 0.2858126, 0.3005497, 0.2869693, 0.2884585],
            "Read-in-full architecture": [0.6512977, 0.5245804, 0.5352062, 0.4818667, 0.5208927],
            "Code trace": [1.6370161, 1.5924593, 1.2793598, 1.9089162, 1.8057974],
            "Architecture doc": [0.3299158, 0.3024566, 0.3392125, 0.3766157, 0.3166825]}
SERIES = [("Baseline", "#a8a69e"), ("Ponytail 5", "#2f8f6b"), ("DensePack 2.0", "#eb6834"),
          ("DensePack 2.0", "#f5a623")]
# The models of each series, the second line of its legend entry. #f5a623 is DensePack's orange from its icon.
MODELS = ["Opus 5.5", "Opus 5.5", "Opus 5.5", "Opus 5.5 main + Sonnet 5.5 Subagent"]
# The percentage inside a bar is white, or dark on a light bar.
INSIDE_INK = {"#f5a623": "#0b0b0b"}
FONT = 'font-family="system-ui, -apple-system, &quot;Segoe UI&quot;, Arial, sans-serif" font-weight="600"'
HEAVY = 'font-family="&quot;Arial Black&quot;, &quot;Segoe UI Black&quot;, &quot;Arial Bold&quot;, sans-serif" font-weight="600"'
X0, UNIT = 40, 9.4           # bars start at x 40, and a 100% saving is 940 px
MAX_5X, PRO = 1.0, 0.25      # API price that used 1% of the 5-hour limit, measured on 10 October 2026
BAR, GAP, TITLE, BENCH_GAP = 28, 6, 34, 20
LEGEND = [(150, 1), (370, 2), (590, 3)]  # x of each legend square, and its entry in SERIES
TOP = 142


# GitHub shows the SVG as an image, which can use only the fonts of the viewer's computer. So each text becomes an outline
# of Inter SemiBold, the font in plugin/fonts, as in images/densepack-readme-banner.svg.
FONT_FILE = Path(__file__).resolve().parents[1] / "plugin" / "fonts" / "Inter-SemiBold.ttf"


def outline(svg):
    font = TTFont(FONT_FILE)
    glyphs, cmap, hmtx, upm = font.getGlyphSet(), font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm

    def path(m):
        attrs, text = m.group(1), html.unescape(m.group(2))
        get = lambda k, d=None: dict(re.findall(r'([\w-]+)="([^"]*)"', attrs)).get(k, d)
        x, y, size, spacing = float(get("x")), float(get("y")), float(get("font-size")), float(get("letter-spacing", "0"))
        scale = size / upm
        names = [cmap.get(ord(c), ".notdef") for c in text]
        width = sum(hmtx[n][0] for n in names) * scale + spacing * (len(names) - 1)
        x -= {"middle": width / 2, "end": width}.get(get("text-anchor"), 0)
        pen = SVGPathPen(glyphs, ntos=lambda v: "%.1f" % v)
        for n in names:
            glyphs[n].draw(TransformPen(pen, (scale, 0, 0, -scale, x, y)))
            x += hmtx[n][0] * scale + spacing
        keep = " ".join('%s="%s"' % (k, get(k)) for k in ("class", "style", "fill", "stroke", "stroke-width") if get(k))
        return '<path %s d="%s"/>' % (keep, pen.getCommands())

    return re.sub(r"<text ([^>]*)>([^<]*)</text>", path, svg)


def money(v):
    return "$%.2f" % v


def cost(v):
    return "%s per run | 5-hour bar: Max 5x ~%.1f%%, Pro ~%.1f%%" % (money(v), v / MAX_5X, v / PRO)


def average(runs):
    return sum(runs) / len(runs)


def prices(bench):
    return [average(RUNS[bench][OPUS][0]), average(PONYTAIL[bench]), average(DP2[bench]), average(SUBAGENT[bench])]


def table():
    print("| Bench | Without DensePack | Ponytail 5.1.0 | DensePack 2.0 | DensePack 2.0 with a Sonnet subagent |")
    print("| --- | --- | --- | --- | --- |")
    for bench in RUNS:
        p = prices(bench)
        cells = ["$%.3f" % p[0]] + ["$%.3f, %.1f%%" % (v, 100 * (1 - v / p[0])) for v in p[1:]]
        print("| %s | %s |" % (bench, " | ".join(cells)))


def main():
    out, grid, desc, delay = [], [], [], 1.80  # the first bar starts 1.8 s after the page loads
    y = TOP
    for bench in RUNS:
        p = prices(bench)
        out.append('<text x="537" y="%d" font-size="21" text-anchor="middle" stroke="#0b0b0b" stroke-width="0.6" %s '
                   'fill="#0b0b0b">%s</text>' % (y + 22, HEAVY, bench))
        y += TITLE
        rows_top = y
        for (series, color), model, v in zip(SERIES, MODELS, p):
            name = "%s, %s" % (series, model)
            s = 100 * (1 - v / p[0])
            base = v == p[0]
            desc.append("%s, %s: %s%s." % (bench, name, money(v), "" if base else ", %.1f%% less" % s))
            if base:
                out.append('<text class="lab" style="animation-delay:%.2fs" x="537" y="%d" font-size="18" '
                           'text-anchor="middle" %s fill="#0b0b0b">Baseline | %s</text>' % (delay, y + 21, FONT, cost(v)))
            else:
                width = max(s, 0) * UNIT
                out.append('<rect class="bar" style="animation-delay:%.2fs" x="%d" y="%d" width="%.1f" height="%d" rx="5" '
                           'fill="%s"><title>%s, %s: %s, %.1f%% less</title></rect>' % (
                               delay, X0, y, width, BAR, color, bench, name, money(v), s))
                inside = width >= 50
                if inside:
                    out.append('<text class="lab" style="animation-delay:%.2fs" x="%.1f" y="%d" font-size="16" text-anchor="end" %s '
                               'fill="%s">%.1f%%</text>' % (delay + 1.2, X0 + width - 7, y + 20, FONT,
                                                             INSIDE_INK.get(color, "#ffffff"), s))
                after = "%s per run" % money(v) if inside else "%.1f%% | %s per run" % (s, money(v))
                out.append('<text class="lab" style="animation-delay:%.2fs" x="%.1f" y="%d" font-size="18" %s '
                           'fill="#0b0b0b">%s</text>' % (delay + 1.2, X0 + width + 12, y + 21, FONT, after))
            delay += 0.12
            y += BAR + GAP
        for k in range(0, 101, 25):
            x = X0 + k * UNIT
            grid.append('<line x1="%.0f" y1="%d" x2="%.0f" y2="%d" stroke="#e1e0d9" stroke-width="1"/>' % (
                x, rows_top + BAR + GAP - 4, x, y - GAP + 4))
        y += BENCH_GAP
    for k in range(0, 101, 25):
        grid.append('<text x="%.0f" y="%d" font-size="13" text-anchor="middle" %s fill="#6b6a64">%d%%</text>' % (
            X0 + k * UNIT, y, FONT, k))
    notes = ["Each bar is the saving against the baseline, one Opus 5.5 run without DensePack or Ponytail, for the whole session.",
             "The 5-hour bar is the share of the 5-hour limit that one baseline run used on Max 5x and on Pro.",
             "With Opus 5.5 main + Sonnet 5.5 Subagent, the Opus agent gives the reading to one Sonnet 5.5 subagent."]
    legend = ['<text x="537" y="%d" font-size="15" text-anchor="middle" %s fill="#52514e">%s</text>' % (y + 28 + 22 * i, FONT, n)
              for i, n in enumerate(notes)]
    for x, i in LEGEND:
        name, color = SERIES[i]
        legend.append('<rect x="%d" y="76" width="20" height="20" rx="4" fill="%s"/><text x="%d" y="92" font-size="17" %s '
                      'fill="#0b0b0b">%s</text><text x="%d" y="113" font-size="14" %s fill="#52514e">%s</text>' % (
                          x, color, x + 28, FONT, name, x + 28, FONT, MODELS[i]))
    height = y + 28 + 22 * len(notes) + 10
    css = ('.bar{transform-box:fill-box;transform-origin:left center;transform:scaleX(0);'
           'animation:grow 1.44s cubic-bezier(.2,.7,.2,1) forwards}.lab{opacity:0;animation:fade 0.64s ease-out forwards}'
           '@keyframes grow{to{transform:scaleX(1)}}@keyframes fade{to{opacity:1}}'
           '@media(prefers-reduced-motion:reduce){.bar{transform:none;animation:none}.lab{opacity:1;animation:none}}')
    svg = ['<svg viewBox="-1 0 1074 %d" width="1074" height="%d" xmlns="http://www.w3.org/2000/svg" role="img" '
           'aria-labelledby="t d">' % (height, height),
           '<title id="t">Total conversation savings</title><desc id="d">The saving of one Claude Code session on Opus 5.5 '
           'against the price without DensePack, with Ponytail 5, with DensePack 2.0, and with DensePack 2.0 on an '
           'Opus 5.5 main agent and a Sonnet 5.5 subagent. %s</desc>' % " ".join(desc),
           '<style>%s</style>' % css,
           '<rect x="-1" y="0" width="1074" height="%d" fill="#fcfcfb"/>' % height,
           '<text x="537" y="50" text-anchor="middle" font-size="36" %s letter-spacing="1" fill="#0b0b0b" '
           'stroke="#0b0b0b" stroke-width="2">TOTAL CONVERSATION SAVINGS</text>' % HEAVY]
    svg += grid + out + legend + ["</svg>"]
    Path("images/savings-benchmarks.svg").write_text(outline("\n".join(svg)), encoding="utf-8", newline="")
    table()
    print("wrote images/savings-benchmarks.svg, height %d" % height)


if __name__ == "__main__":
    main()
