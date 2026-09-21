"""Reads grey glyphs from FreeType as Pillow masks, on every platform.

WHAT THIS FILE IS
    This file is the glyph backend, the only one. A glyph backend does one
    job. It gives the renderer the ink of one character and the pen step of
    one character. codepack.py does every other part of the drawing.

WHY THIS FILE EXISTS
    Pillow draws through FreeType, but Pillow does not let the caller pick
    the hinting target, pick the render mode, or make the outline bolder.
    Pillow's C source hardcodes FT_LOAD_DEFAULT. This file calls FreeType
    directly and takes all three settings.

WHAT IT DEPENDS ON
    freetype-py, which is a binding onto the same FreeType C library that
    Pillow already links. Nothing is compiled. Version 2.13.2 is installed on
    the machine this was written on.

THE CONTRACT THIS FILE ANSWERS
    Four calls, the one contract the draw loop in codepack.py calls.

        available(font_file)                    -> True or False
        advance(font_file, pixel_size, char)    -> the pen step in pixels
        ascent(font_file, pixel_size)           -> rows down to the baseline
        glyph(char, font_file, pixel_size)      -> (mask, left, top)

    mask is a Pillow image in mode L. The value 0 is paper. The value 255 is
    full ink. The values between are partial ink. A character that inks
    nothing, such as a space, gives None.

    left and top are offsets from the pen on the baseline. A caller whose
    baseline is on row b pastes the mask at (x + left, b + top). The value of
    top is negative when the ink is above the baseline.

WHERE THE SETTINGS COME FROM
    MacType is a Windows text renderer built on FreeType. MacType is a
    C++ program. It uses no Python. This file makes the same FreeType calls.
    Its ft.cpp builds its flags like this:

        font_type.flags = FT_LOAD_NO_BITMAP | FT_LOAD_IGNORE_GLOBAL_ADVANCE_WIDTH;
        switch (pfs->GetHintingMode()) {
        case 0: break;                                   // the font's bytecode
        case 1: font_type.flags |= FT_LOAD_NO_HINTING; break;
        case 2: font_type.flags |= FT_LOAD_FORCE_AUTOHINT; break;
        }
        switch (pfs->GetAntiAliasMode()) {
        case -1: flags |= FT_LOAD_TARGET_MONO;   render_mode = FT_RENDER_MODE_MONO;   break;
        case  0: flags |= FT_LOAD_TARGET_NORMAL; render_mode = FT_RENDER_MODE_NORMAL; break;
        case  1: flags |= FT_LOAD_TARGET_LIGHT;  render_mode = FT_RENDER_MODE_LIGHT;  break;
        }

    HINTING_MODE and ANTIALIAS_MODE below carry the same numbers. A setting
    written against MacType's documentation means the same thing here.

TWO PARTS OF THAT RECIPE DO NOT APPLY
    FT_LOAD_IGNORE_GLOBAL_ADVANCE_WIDTH has no effect. The FreeType reference
    gives it as "Ignored. Deprecated." This file does not pass it.

    FT_RENDER_MODE_LIGHT is the same as FT_RENDER_MODE_NORMAL. The FreeType
    reference says so. LIGHT is a hinting choice, not a render mode.

WHICH SETTING TO USE AT 9 PX
    The test draws "owed = json.loads(path.read_text())  told 1l0O" in Inter
    at 9 px. It counts the share of inked pixels in the middle greys. A sharp
    glyph puts its pixels at the two ends. A blurred glyph puts them in the
    middle.

        FreeType, LIGHT hinting      66.5 per cent of 821 ink pixels
        FreeType, NORMAL hinting     62.5 per cent of 815 ink pixels
        FreeType, auto-hinter        44.2 per cent of 708 ink pixels

    The auto-hinter wins twice. It puts the least ink in the middle greys, and
    it uses the fewest ink pixels, so its ink is concentrated and not spread.

    LIGHT is worse than NORMAL at this size. The FreeType documentation gives
    the reason: LIGHT snaps "glyphs to the pixel grid only vertically". At
    9 px the horizontal snap is what puts a stem on one whole pixel column.

DO NOT SUPERSAMPLE
    Drawing at four times the size and reducing the image is worse at 9 px,
    not better. The same string measures:

        FreeType NORMAL, drawn at 9 px                61.9 per cent of  722
        FreeType NORMAL, drawn at 36 px, then to 9 px 51.7 per cent of 1138

    The reduced image spreads the same glyphs over 58 per cent more ink. Its
    lower middle-grey share is arithmetic, not sharpness. Hinting at 36 px
    fits each stem to the 36 px grid, that grid has no relation to the 9 px
    output grid, and the reduction averages each stem across two output
    columns. MacType does not supersample either. It draws at the size it
    shows.

HOW TO CHECK THIS FILE
    Run it. It draws one line and asserts the contract.

        python plugin/scripts/freetype_glyph.py
"""
import ctypes
import math
import os
import platform
import sys

if sys.platform == "win32":
    # The freetype package calls platform.system() when it is imported, and
    # on Python 3.12 and later that call asks Windows' WMI service for the OS
    # version before it looks anywhere else. One hook process pays that
    # query once. When thirty-two hook processes ask at the same moment, WMI
    # can answer none of them for the length of the hook timeout: each sits
    # in platform._wmi_query, the Reads go through as text, and the service
    # reports "Shutting down" to every other caller on the machine. With the
    # _wmi module set aside, platform answers from sys.getwindowsversion(),
    # the path it takes on a Python built without that module, and no hook
    # touches WMI.
    platform._wmi = None

try:
    import freetype
except ImportError:  # pragma: no cover - the caller falls back to Pillow
    freetype = None

from PIL import Image


# ---------------------------------------------------------------- settings --

# The hinting modes, with MacType's own numbers from its HintingMode wiki page.
HINTING_FONT_BYTECODE = 0   # use the hinting the font designer wrote
HINTING_OFF = 1             # no hinting at all, unless HINT_SMALL_FONT is on
HINTING_AUTO = 2            # FreeType fits the outline itself, ignoring the font
# MacType documents this as "use freetype light autohinter to generate
# hinting. This options must be used together with 'AntiAliasMode' light
# mode", and it is the pairing its wiki presents for small text.
HINTING_AUTO_LIGHT = 3

# The antialias modes, with MacType's own numbers. The LCD modes are declared
# so a setting written against MacType's documentation means the same thing
# here, but they must never ship: they target the subpixel geometry of a
# physical display, and this page is a PNG read by a model.
ANTIALIAS_BILEVEL = -1      # one bit a pixel, ink or paper, no grey
ANTIALIAS_GREY = 0          # eight bits a pixel, grid fitted on both axes
ANTIALIAS_GREY_LIGHT = 1    # eight bits a pixel, grid fitted vertically only
ANTIALIAS_LCD_RGB = 2
ANTIALIAS_LCD_BGR = 3
ANTIALIAS_LCD_LIGHT_RGB = 4
ANTIALIAS_LCD_LIGHT_BGR = 5

# The two settings this file draws with. HINTING_MODE defaults to 2, the
# auto-hinter, against MacType's default of 0; DENSEPACK_HINTING overrides it.
# ANTIALIAS_MODE is greyscale, MacType's default.
#
# Measured on Inter SemiBold at 12 px, the share of glyph ink landing on a
# WHOLE pixel rather than partial coverage: mode 0 gives 17.7 per cent, mode 1
# gives 13.4, mode 2 gives 24.0 and mode 3 gives 16.7. A stem on a whole pixel
# is what reads as crisp.
#
# The auto-hinter snaps every stem to the same whole pixel, so it flattens
# the difference between weights: at 11 px the widest solid run inside an n
# is 2 px for a 400, a 500 and a 600 face alike, where the font's own
# bytecode gives 4 px for a 400 and a 500.
#
# The TrueType interpreter version does not change this: 35 and 40 draw the
# identical bitmap on Inter, because there is little bytecode to obey.
#
# The auto-hinter also brings two settings to life that the bytecode
# interpreter never reads, because FreeType defines both on the auto-hinter:
# stem darkening and increase-x-height.
HINTING_MODE = int(os.environ.get("DENSEPACK_HINTING") or HINTING_AUTO)
ANTIALIAS_MODE = ANTIALIAS_GREY

# MacType's HintSmallFont. Its wiki: applies the font's embedded hinting to
# fonts below 12 pt, and "only functions when HintingMode is set to 1".
# Default 0. In ft.cpp the test is
#     if (pSettings->HintSmallFont() && font_type.height < 12)
# which clears FT_LOAD_NO_HINTING for that glyph.
HINT_SMALL_FONT = int(os.environ.get("DENSEPACK_HINT_SMALL_FONT") or 0)
HINT_SMALL_FONT_PT = 12

# MacType's LcdFilter: 0 none, 1 default, 2 light, 3 and 16 legacy. Default 0.
# It only acts in an LCD render mode, so it does nothing while ANTIALIAS_MODE
# is greyscale, which is the only mode this renderer should ever ship.
LCD_FILTER_NONE, LCD_FILTER_DEFAULT, LCD_FILTER_LIGHT, LCD_FILTER_LEGACY = 0, 1, 2, 3
LCD_FILTER = int(os.environ.get("DENSEPACK_LCD_FILTER") or LCD_FILTER_NONE)

# MacType's GammaMode and GammaValue, from CAlphaBlend::init in ft.cpp:
#
#     if (mode < 0)        temp = (1.0f/255.0f) * i;                  linear
#     else if (mode == 1)  sRGB, with a knee at i <= 10
#     else if (mode == 2)  a hybrid of sRGB and linear
#     else                 temp = pow((1.0f/255.0f) * i, gamma);
#
# The table it fills, tbl1, is not an alpha table. It converts a COLOUR to
# linear light so the blend happens in linear space and is converted back
# afterwards. That is the stage this renderer never had: Pillow composites in
# sRGB space, where a half-covered pixel reads far lighter than half ink.
#
# Default.ini ships GammaMode = -1 and GammaValue = 1.0, so the default is a
# linear transfer, which is the same as not blending in linear space at all.
GAMMA_DISABLED, GAMMA_VALUE_MODE, GAMMA_SRGB, GAMMA_HYBRID = -1, 0, 1, 2
# At MacType's default of -1. Every MacType gamma setting here sits where
# Default.ini leaves it.
#
# -1 is a linear transfer, so paste_ink() blends the sRGB numbers directly and
# is arithmetically identical to Pillow's own composite. Mode 1, sRGB,
# converts both colours to linear light, blends there and converts back,
# which is the physically correct thing to do for an sRGB PNG. It measured
# 10.7 per cent solid ink against 53.5 per cent grey, softer than the 44.8 and
# 26.9 the sRGB-number blend gives, because blending in linear light thins a
# stroke.
GAMMA_MODE = int(os.environ.get("DENSEPACK_GAMMA_MODE") or GAMMA_DISABLED)
GAMMA_VALUE = float(os.environ.get("DENSEPACK_GAMMA_VALUE") or 1.0)

# MacType's TextTuning, range 0 to 12, default 0, with TextTuningR/G/B per
# channel. In ft.cpp it remaps the alpha before blending:
#     tunetbl[i] = Bound(0, alphatbl[Bound(table[i], 0, 255)], BASE)
# so it shifts coverage up by a fixed amount before the weight and contrast
# curve is looked up. 0 leaves coverage alone.
TEXT_TUNING = int(os.environ.get("DENSEPACK_TEXT_TUNING") or 0)

# THE TRUETYPE INTERPRETER VERSION
#
# This is a library property, not a per-load flag, so it is set once per
# process. FreeType's reference gives three values:
#
#   35  "MS rasterizer v.1.7 as used e.g. in Windows 98; only grayscale and
#        B/W rasterizing is supported"
#   38  "the same Version 40. The original Infinality code is no longer
#        available"
#   40  "MS rasterizer v.2.1; it is roughly equivalent to the hinting provided
#        by DirectWrite ClearType"
#
# and states the default is "subpixel support if TT_CONFIG_OPTION_SUBPIXEL_
# HINTING is defined", which every current build defines. So a FreeType left
# alone runs v40.
#
# v40 is the stripped-down subpixel path: it grid-fits vertically and leaves
# the horizontal alone, which is right for ClearType on a real display and
# wrong here. It allows a stem to sit at a fractional horizontal position, so
# a one-pixel stem spreads across two columns of grey. v35 runs the font's
# bytecode fully on both axes, so a stem snaps to whole pixels.
#
# Under HINTING_MODE 0 the interpreter runs the font's own bytecode, and this
# decides how much of it is obeyed. The auto-hinter modes do not read it.
TT_INTERPRETER_V35, TT_INTERPRETER_V40 = 35, 40
TT_INTERPRETER_VERSION = int(os.environ.get("DENSEPACK_TT_INTERPRETER")
                             or TT_INTERPRETER_V35)


# ------------------------------------------------------- the gamma transfer --
#
# MacType blends a glyph in LINEAR LIGHT. CAlphaBlend::init fills tbl1 with the
# transfer for the mode, the blend happens on those linear values, and the
# result is converted back. Pillow's Image.paste does none of that: it blends
# the sRGB numbers directly, so a pixel at half coverage lands halfway between
# the two sRGB values, which the eye and a camera both read as far lighter than
# half ink. That is why an anti-aliased edge looks soft next to a drawn
# rectangle, which has no partly covered pixels at all.
#
# transfer_to_linear() is tbl1. transfer_from_linear() is its inverse, which
# MacType needs too and which ft.cpp builds by searching the same table.

_transfer_cache = {}


def transfer_to_linear():
    """MacType's tbl1 as 256 floats in 0..1, for the mode and value set."""
    key = ("to", GAMMA_MODE, GAMMA_VALUE)
    kept = _transfer_cache.get(key)
    if kept is not None:
        return kept
    out = []
    for i in range(256):
        v = i / 255.0
        if GAMMA_MODE < 0:
            temp = v
        elif GAMMA_MODE == GAMMA_SRGB:
            # sRGB, with MacType's knee at i <= 10
            temp = (i / (12.92 * 255.0)) if i <= 10 else \
                pow((v + 0.055) / 1.055, 2.4)
        elif GAMMA_MODE == GAMMA_HYBRID:
            # ft.cpp calls this a hybrid of sRGB and linear; the mean of the
            # two transfers, which is what its curve sits between.
            srgb = (i / (12.92 * 255.0)) if i <= 10 else \
                pow((v + 0.055) / 1.055, 2.4)
            temp = (srgb + v) / 2.0
        else:
            temp = pow(v, GAMMA_VALUE)
        out.append(temp)
    _transfer_cache[key] = out
    return out


def transfer_from_linear(steps=4096):
    """The inverse of tbl1: linear 0..1 to an sRGB byte, as a list of steps."""
    key = ("from", GAMMA_MODE, GAMMA_VALUE, steps)
    kept = _transfer_cache.get(key)
    if kept is not None:
        return kept
    forward = transfer_to_linear()
    out = []
    j = 0
    for s in range(steps):
        want = s / float(steps - 1)
        while j < 255 and forward[j + 1] < want:
            j += 1
        # take whichever of the two neighbours is nearer in linear light
        if j < 255 and abs(forward[j + 1] - want) < abs(forward[j] - want):
            out.append(j + 1)
        else:
            out.append(j)
    _transfer_cache[key] = out
    return out


def tuning_table():
    """MacType's TextTuning: coverage shifted up before the curve is read."""
    if not TEXT_TUNING:
        return None
    return [min(255, i + TEXT_TUNING) for i in range(256)]

# FT_LOAD_NO_BITMAP stops an embedded bitmap strike replacing the outline. The
# FreeType reference gives it as "Ignore bitmap strikes when loading."
LOAD_FLAGS_ALWAYS = 0
if freetype is not None:
    LOAD_FLAGS_ALWAYS = freetype.FT_LOAD_NO_BITMAP

# FreeType takes sizes in 26.6 fixed point, which is 64 units to the pixel.
FIXED_POINT_26_6 = 64

# HOW MANY PLACES INSIDE ONE PIXEL A GLYPH MAY START.
#
# A pen step is a fraction: Inter at 12 px asks 7.488 px for a b and 4.664 for
# an f. Rounding each step to a whole pixel makes the spacing uneven, because
# the error is not the same for every letter: b, d, p and q each lose 0.49 px
# and f, g and s each gain about 0.4, a spread of 0.98 px on a letter only
# 7 px wide. At 4 places the pen keeps its fraction and the glyph is drawn at
# it, with at most an eighth of a pixel of placing error and at most four
# cached masks per character.
#
# The default is 1, WHOLE PIXELS. Subpixel placement draws a glyph at one of
# four offsets inside a pixel, chosen by where its pen lands, so two copies of
# the same letter in one line come out different weights. Snapping every
# glyph to a whole pixel makes each letter identical everywhere.
#
# IT COSTS WIDTH. A whole-pixel step rounds every advance up, so an image is
# about 10 per cent wider than it is at 4 steps.
SUBPIXEL_STEPS = int(os.environ.get("DENSEPACK_SUBPIXEL") or 1)


def snap_phase(phase):
    """One of SUBPIXEL_STEPS places inside a pixel, as a float in 0.0 to 1.0.

    Snapping keeps the mask cache small. A value of 1 for SUBPIXEL_STEPS turns
    subpixel placement off and every glyph draws on the whole pixel again.

    A phase that snaps up to a whole pixel comes back as 0.0, so callers must
    take the whole pixel from split_pen() rather than flooring the pen
    themselves; flooring first would draw such a glyph a whole pixel early.
    """
    if SUBPIXEL_STEPS <= 1 or not phase:
        return 0.0
    phase -= int(phase)
    if phase < 0:
        phase += 1.0
    return round(phase * SUBPIXEL_STEPS) % SUBPIXEL_STEPS / float(SUBPIXEL_STEPS)


def split_pen(x):
    """A fractional pen position as (whole pixel to paste on, phase).

    The two are chosen together. Rounding the pen to the nearest of the
    SUBPIXEL_STEPS places first, and only then splitting off the whole pixel,
    is what keeps a pen at x.9 on the pixel above x rather than on x itself.
    """
    if SUBPIXEL_STEPS <= 1:
        return int(round(x)), 0.0
    snapped = round(x * SUBPIXEL_STEPS) / float(SUBPIXEL_STEPS)
    whole = int(math.floor(snapped))
    return whole, snapped - whole

# The resolution FreeType scales against. 72 dots an inch makes one point one
# pixel, so a size given in pixels arrives as that many pixels.
RESOLUTION_DPI = 72

# MacType makes a small face bolder by 1/36 of its size, in ft.cpp, for any
# size under 15 px. This file uses the same fraction.
# MacType's BoldWeight, range -32 to +32, default 0. It emboldens a glyph
# marked bold, over and above NormalWeight.
#
# 0.18, so that the four dot marks can be drawn bold. font.bold names the same
# file as font.regular, so there is no bold face to switch to and bold is
# simulated by widening the outline. At MacType's default of 0 a character
# marked bold would draw identically to one that is not.
#
# MacType's own vertical cap still applies below 15 px: the horizontal widens
# by the full fraction and the vertical is held to half a pixel, which is what
# keeps a bold comma from closing up into a blob.
EMBOLDEN_FRACTION = float(os.environ.get("DENSEPACK_BOLD") or 0.18)
# MacType's FT_BOLD_LOW. Below this size it caps the vertical widening.
EMBOLDEN_SIZE_LIMIT_PX = 15
# MacType's Min(long(32), str_v): 32 units in 26.6 fixed point is half a pixel.
EMBOLDEN_VERTICAL_CAP = 32

# STEM_FRACTION widens EVERY glyph, not only the ones the source text marks
# bold. It defaults to 0.0, MacType's NormalWeight default: stock MacType
# emboldens nothing, and the weight of the face carries the stroke instead.
# DENSEPACK_STEM overrides it, so the fraction can be swept without an edit.
#
# FT_Outline_EmboldenXY is the call that adds a pixel to a stem. The ink curve
# cannot do it, because the curve only moves the grey of a pixel the outline
# already covers.
#
# Measured on one code file, sweeping the fraction:
#   0.000   stroke 1.92 px   49.5 per cent of dark runs only one pixel wide
#   0.100   stroke 2.05 px   41.9 per cent
#   0.220   stroke 2.32 px   27.2 per cent
#
# Below 15 px the widening grows in proportion to the size; at 15 px and above
# it is held at the 15 px amount, see load_character().
STEM_FRACTION = float(os.environ.get("DENSEPACK_STEM") or 0.0)

# STEM DARKENING
#
# A screen applies gamma correction. Gamma correction makes thin ink look
# thinner than it is. At a small size a stem is about one pixel wide, so the
# whole letter is thin ink, and the letter fades. The FreeType documentation
# states the problem and the answer: stem darkening "emboldens glyphs at
# smaller point sizes to counteract the visual thinning that occurs with
# gamma correction".
#
# The auto-hinter has stem darkening OFF by default. The property
# "no-stem-darkening" holds TRUE for the auto-hinter, and TRUE means off.
# Setting it to FALSE turns the darkening on.
#
# STEM_DARKENING True passes FALSE to that property, which turns the
# darkening on. FreeType defines stem darkening on the auto-hinter and the
# Adobe CFF/Type1/CID engines only, so it can act under HINTING_MODE 2 and 3
# and does nothing under the TrueType bytecode interpreter. On the FreeType
# build this file was measured with, both values drew identical bitmaps.
STEM_DARKENING = True

# The darkening curve, as pairs of (stem width, how much to darken), both in
# thousandths of a pixel. These are Adobe's defaults, quoted in the FreeType
# properties reference:
#
#     stem 0.5 px or less  darken by 0.400 px
#     stem 1.000 px        darken by 0.275 px
#     stem 1.667 px        darken by 0.275 px
#     stem 2.333 px+       darken by 0.000 px
#
# A 9 px page draws stems near 1 px, so it takes the 0.275 px step.
DARKENING_PARAMETERS = (500, 400, 1000, 275, 1667, 275, 2333, 0)

# INCREASE X HEIGHT
#
# The FreeType documentation says this property "improves small font
# legibility" by rounding the font's x height up "much more often than
# normally" for sizes from 6 pixels up to the limit set here. A taller x
# height gives a lowercase letter more rows to hold its shape in.
# 14 is the size limit. FreeType's own default is 0, which means disabled.
# FreeType defines increase-x-height on the auto-hinter alone, so it acts
# under HINTING_MODE 2 and 3 and not under the font's own bytecode.
INCREASE_X_HEIGHT_LIMIT = 14

# THE INK CURVE
#
# FreeType hands back coverage, which is how much of a pixel the outline
# covers. Coverage is not ink. A screen applies gamma, so a pixel at half
# coverage does not read as half ink, it reads much lighter. At 9 px most of a
# letter is partial coverage, so the whole letter reads light.
#
# MacType answers this with a table, in CAlphaBlend::init in ft.cpp:
#
#     temp = pow((1.0f / 255.0f) * i, 1.0f / weight);
#     if (temp < 0.5f)
#         alpha = pow(temp * 2, contrast) / 2.0f;
#     else
#         alpha = 1.0f - pow((1.0f - temp) * 2, contrast) / 2.0f;
#     alphatbl[i] = (int)(alpha * BASE);
#
# The first line is the gamma. The two after it are an S curve about the
# midpoint, which pushes light coverage lighter and heavy coverage heavier, so
# an edge hardens instead of smearing.
#
# INK_WEIGHT is MacType's RenderWeight. Above 1.0 the whole letter darkens.
# INK_CONTRAST is MacType's Contrast. Above 1.0 the S curve steepens.
# Both at 1.0 leave the coverage exactly as FreeType made it.
#
# DENSEPACK_INK_WEIGHT and DENSEPACK_INK_CONTRAST override these, so the
# curve can be swept without an edit.
#
# Both sit above MacType's default of 1.0 on purpose. MacType tunes for an eye
# reading a physical display, where the grey transition pixels of an
# anti-aliased edge are what make a stroke look smooth. This image is read by
# a model from a PNG, where those grey pixels buy little and cost edge
# definition.
#
# THE TWO FIGHT EACH OTHER ABOVE A WEIGHT OF ABOUT 2. RenderWeight is a gamma
# exponent, so it lifts every partly covered pixel; Contrast is an S curve
# about the midpoint, so it pushes the lower half back toward paper. Once the
# weight has carried the mid pixels up, more contrast sends the ones just
# under half back down.
#
# The pair depends on the size and the face and does not carry across. A
# curve built to rescue a thin face pushes the edge pixels of a heavier face
# into the grey band: at 11 px with weight 2.2 and contrast 1.2, Regular 400
# lays 70.2 per cent solid ink, Medium 500 lays 56.0 and SemiBold 600 lays
# 47.5. Changing CODE_PX or the face means sweeping both again, starting from
# MacType's default.
#
# Neither knob changes a metric, so the image is the same size at every value.
#
# INK_WEIGHT is MacType RenderWeight, a gamma on coverage: above 1 it darkens
# every partly covered pixel.
INK_WEIGHT = float(os.environ.get("DENSEPACK_INK_WEIGHT") or 1.1)
# INK_CONTRAST is MacType Contrast. Above 1 it pushes a partly covered pixel
# toward full ink or full paper. On the snapped image that is the intent:
# solid ink goes from 45.6 per cent at contrast 1.0 to 68.5 at 3.0, and the
# faintest edge pixels go to paper rather than staying as grey.
#
# ON AN UNSNAPPED IMAGE THE SAME VALUE DELETES THE ANTIALIASED RIM and the
# letters come out stepped. The two settings belong together.
INK_CONTRAST = float(os.environ.get("DENSEPACK_INK_CONTRAST") or 3.0)


# ------------------------------------------------------------------ caches --

# True once the library level properties are set. They are set once a process.
_library_properties_set = [False]

# One open FreeType face for each font file. Opening a face reads the file.
_open_faces = {}

# One kept answer for each distinct call, so a page pays for a character once.
_kept_masks = {}
_kept_advances = {}


# ----------------------------------------------------------------- helpers --

def apply_library_properties():
    """Set the auto-hinter properties this file depends on, once per process.

    Both properties live on the library, not on a face, so they are set once
    and every face that is opened afterwards uses them.
    """
    if _library_properties_set[0] or freetype is None:
        return
    _library_properties_set[0] = True
    library = freetype.get_handle()

    # The TrueType interpreter version. It must be set before any face is
    # loaded, because a face caches the version it was opened under.
    try:
        version = ctypes.c_uint(int(TT_INTERPRETER_VERSION))
        freetype.FT_Property_Set(library, b"truetype", b"interpreter-version",
                                 ctypes.byref(version))
    except Exception:
        # A build without the TrueType driver, or an older FreeType. The page
        # still draws, at whatever version that build defaults to.
        pass

    # no-stem-darkening takes TRUE for off. Pass FALSE to turn darkening on.
    darkening_off = ctypes.c_bool(not STEM_DARKENING)
    try:
        freetype.FT_Property_Set(library, b"autofitter", b"no-stem-darkening",
                                 ctypes.byref(darkening_off))
    except Exception:
        # An older FreeType has no such property. The page still draws.
        pass

    # darkening-parameters takes eight integers, four (width, amount) pairs.
    try:
        curve = (ctypes.c_int * 8)(*DARKENING_PARAMETERS)
        freetype.FT_Property_Set(library, b"autofitter",
                                 b"darkening-parameters", ctypes.byref(curve))
    except Exception:
        pass


def apply_face_properties(face):
    """Set the properties that live on one face.

    increase-x-height is set for each face. The FreeType documentation says to
    set it after the size is set and before a glyph is loaded.
    """
    if not INCREASE_X_HEIGHT_LIMIT or freetype is None:
        return

    class IncreaseXHeight(ctypes.Structure):
        """FT_Prop_IncreaseXHeight, which the binding does not declare."""
        _fields_ = [("face", ctypes.c_void_p), ("limit", ctypes.c_uint)]

    try:
        request = IncreaseXHeight(ctypes.cast(face._FT_Face, ctypes.c_void_p),
                                  int(INCREASE_X_HEIGHT_LIMIT))
        freetype.FT_Property_Set(freetype.get_handle(), b"autofitter",
                                 b"increase-x-height", ctypes.byref(request))
    except Exception:
        pass


def open_face(font_file):
    """The open FreeType face for this font file, opened once and kept."""
    face = _open_faces.get(font_file)
    if face is None:
        apply_library_properties()
        face = freetype.Face(font_file)
        _open_faces[font_file] = face
    return face


# The share of a text's non-space characters the font may lack. A few emoji
# convert to boxes and the reader pulls those lines as text. A file mostly in
# Chinese, Japanese or Korean would convert to nothing but boxes.
MISSING_GLYPH_MAX = 0.02


def font_covers(text, font_file):
    """True when the font can draw all but MISSING_GLYPH_MAX of the text.

    It lives here, not in codepack, so the Read gate can ask before it loads
    the renderer and NumPy."""
    return missing_share(text, font_file) <= MISSING_GLYPH_MAX


def missing_share(text, font_file):
    """The share of the text's non-space characters this font has no glyph for.

    Inter has no Chinese, Japanese, Korean or emoji glyphs, and each of those
    characters draws as an empty box. 0.0 when FreeType or the font is missing,
    because the caller then cannot measure coverage at all."""
    if not available(font_file):
        return 0.0
    face = open_face(font_file)
    seen = {}
    total = missing = 0
    for ch in text:
        if ch.isspace():
            continue
        total += 1
        if ord(ch) < 128:
            continue
        if ch not in seen:
            seen[ch] = face.get_char_index(ord(ch)) == 0
        missing += seen[ch]
    return missing / total if total else 0.0


def load_flags_and_render_mode():
    """The FreeType load flags and render mode the two settings ask for.

    Returns a pair. The first is the flags for FT_Load_Char. The second is the
    mode for FT_Render_Glyph.
    """
    load_flags = LOAD_FLAGS_ALWAYS

    if HINTING_MODE == HINTING_OFF:
        load_flags |= freetype.FT_LOAD_NO_HINTING
    elif HINTING_MODE in (HINTING_AUTO, HINTING_AUTO_LIGHT):
        load_flags |= freetype.FT_LOAD_FORCE_AUTOHINT

    # Mode 3 forces the light target. MacType
    # documents it as "use freetype light autohinter to generate hinting. This
    # options must be used together with 'AntiAliasMode' light mode", so the
    # light target is forced here rather than left to the antialias setting:
    # the two are one mode, and mode 3 with a normal target is just mode 2.
    #
    # FT_LOAD_TARGET_LIGHT grid-fits vertically only and leaves the horizontal
    # alone, which is what MacType and fontconfig's hintslight both mean by
    # light hinting.
    if HINTING_MODE == HINTING_AUTO_LIGHT:
        return (load_flags | freetype.FT_LOAD_TARGET_LIGHT,
                freetype.FT_RENDER_MODE_NORMAL)

    if ANTIALIAS_MODE == ANTIALIAS_BILEVEL:
        return (load_flags | freetype.FT_LOAD_TARGET_MONO,
                freetype.FT_RENDER_MODE_MONO)
    if ANTIALIAS_MODE == ANTIALIAS_GREY_LIGHT:
        return (load_flags | freetype.FT_LOAD_TARGET_LIGHT,
                freetype.FT_RENDER_MODE_NORMAL)
    return (load_flags | freetype.FT_LOAD_TARGET_NORMAL,
            freetype.FT_RENDER_MODE_NORMAL)


def load_character(font_file, pixel_size, character, make_bold=False,
                   width_scale=1.0, phase=0.0):
    """Load one character into the face's glyph slot, and say how to render it.

    The glyph is loaded but not yet rendered, so the outline can be made
    bolder first. Returns the face and the render mode.

    phase is where between two whole pixels the pen sits, 0.0 up to 1.0. The
    outline is shifted right by that fraction before it renders, so a glyph
    whose pen lands at x.5 is drawn half a pixel along rather than snapped
    back to x. Without it every pen step has to be a whole number and the
    font's real advances, which are fractions, are lost to rounding.
    """
    face = open_face(font_file)
    size_fixed = int(round(pixel_size * FIXED_POINT_26_6))
    face.set_char_size(width=int(round(size_fixed * float(width_scale))),
                       height=size_fixed,
                       hres=RESOLUTION_DPI, vres=RESOLUTION_DPI)
    apply_face_properties(face)

    load_flags, render_mode = load_flags_and_render_mode()

    # A look-alike character draws Inter's own alternate, by glyph index.
    index = alternate_index(face, character)
    if index:
        face.load_glyph(index, load_flags)
    else:
        face.load_char(character, load_flags)

    # MacType widens the outline before it renders, in ft.cpp, in
    # New_FT_Outline_Embolden:
    #
    #     if (font_size < FT_BOLD_LOW && str_h > 32)
    #         FT_Outline_EmboldenXY(outline, str_h, Min(long(32), str_v));
    #     else
    #         FT_Outline_Embolden(outline, str_h);
    #
    # FT_BOLD_LOW is 15. So below 15 px MacType caps the VERTICAL widening at
    # 32 units, which is 0.5 px in 26.6 fixed point, and leaves the horizontal
    # alone. Capping the vertical is what keeps a horizontal bar thin and a
    # counter open at a small size: widening y as hard as x fills the hole in
    # an e and fattens the crossbar of a 3.
    #
    # MacType's own strength comes from CalcNormalWeight(), and NormalWeight
    # defaults to 0, so stock MacType emboldens nothing. STEM_FRACTION and
    # EMBOLDEN_FRACTION are this renderer's own choice; the vertical cap
    # follows MacType.
    fraction = STEM_FRACTION + (EMBOLDEN_FRACTION if make_bold else 0.0)
    if fraction:
        if pixel_size < EMBOLDEN_SIZE_LIMIT_PX:
            step_h = int(round(pixel_size * FIXED_POINT_26_6 * fraction))
            # MacType's Min(32, str_v), the half pixel ceiling
            step_v = min(EMBOLDEN_VERTICAL_CAP, step_h)
        else:
            step_h = int(round(FIXED_POINT_26_6 * fraction
                               * EMBOLDEN_SIZE_LIMIT_PX))
            step_v = step_h
        try:
            freetype.FT_Outline_EmboldenXY(face.glyph.outline._FT_Outline,
                                           step_h, step_v)
        except Exception:
            # An older binding may not expose the call. A glyph that is not
            # made bolder still draws correctly, so this is not an error.
            pass

    # The subpixel shift, last, so it moves the outline the embolden widened.
    # FreeType works out bitmap_left from the shifted outline, so the caller
    # pastes at the whole pixel below the pen and the fraction is already in
    # the mask.
    if phase:
        try:
            freetype.FT_Outline_Translate(
                face.glyph.outline._FT_Outline,
                int(round(phase * FIXED_POINT_26_6)), 0)
        except Exception:
            # Without the call the glyph draws on the whole pixel.
            pass

    return face, render_mode


# THE LOOK-ALIKE GLYPHS
#
# Two pairs confuse a reader at a small size, and a reader that mistakes one
# of them writes a wrong character, which costs a rebuild:
#
#   the digit zero against the capital O
#   the digit one against the lowercase l
#
# Inter draws alternates in the same file at the same size:
#
#   zero.slash  the zero with a slash through it
#   one.ss01    the one with a foot, so it is not a bare stem
#
# Read at 7 times size on the plain glyphs, the digit zero could not be told
# from the capital O in any row. No ink curve fixes this, because the marks
# are simply not drawn.
#
# l.ss02, the l with a tail, is not used. At 9 px it inks two columns where
# the plain l inks one, at the same 3 px advance and the same left bearing,
# so it fills its cell and leaves no clear column on its right. one.ss01
# already separates the pair: a 3 column wide digit with a foot against a 1
# column bare stem. The two alternates used cost nothing, since their metrics
# match the plain glyph exactly:
#
#   0   plain adv 5 w 5 left 0    zero.slash adv 5 w 5 left 0    identical
#   1   plain adv 4 w 3 left 0    one.ss01   adv 4 w 3 left 0    identical
#   l   plain adv 3 w 1 left 1    l.ss02     adv 3 w 2 left 1    ONE WIDER
GLYPH_ALTERNATES = {
    "0": "zero.slash",
    "1": "one.ss01",
}

_kept_curve = {}
_kept_alternates = {}


def alternate_index(face, character):
    """The glyph index of this character's alternate, or None.

    A face that does not carry the alternate gives None, and the character
    then draws its plain glyph.
    """
    name = GLYPH_ALTERNATES.get(character)
    if not name:
        return None
    key = (id(face), character)
    if key in _kept_alternates:
        return _kept_alternates[key]
    index = face.get_name_index(name.encode("ascii"))
    index = index or None
    _kept_alternates[key] = index
    return index


def ink_curve(weight=None, contrast=None):
    """MacType's CAlphaBlend table as 256 entries, for Image.point.

    The entry at i is what a coverage of i becomes. Weight 1.0 with contrast
    1.0 gives the identity, so the coverage passes through untouched.
    """
    weight = INK_WEIGHT if weight is None else float(weight)
    contrast = INK_CONTRAST if contrast is None else float(contrast)
    kept = _kept_curve.get((weight, contrast))
    if kept is not None:
        return kept
    table = []
    for level in range(256):
        temp = pow(level / 255.0, 1.0 / weight) if weight else 0.0
        if temp < 0.5:
            alpha = pow(temp * 2.0, contrast) / 2.0
        else:
            alpha = 1.0 - pow((1.0 - temp) * 2.0, contrast) / 2.0
        table.append(max(0, min(255, int(round(alpha * 255.0)))))
    _kept_curve[(weight, contrast)] = table
    return table


def coverage_from_bitmap(bitmap, render_mode):
    """The bitmap's bytes as one row-packed coverage string, 0 paper 255 ink.

    A grey bitmap holds one byte a pixel already. Each row is bitmap.pitch
    bytes long, and that may be wider than the glyph, so each row is cut to
    the glyph's own width.

    A bilevel bitmap holds one bit a pixel, most significant bit first. Each
    bit becomes one byte, either 0 or 255.
    """
    buffer_bytes = bytes(bytearray(bitmap.buffer))

    if render_mode == freetype.FT_RENDER_MODE_MONO:
        bitmap_rows = []
        for row_index in range(bitmap.rows):
            row_bytes = buffer_bytes[row_index * bitmap.pitch:
                                     (row_index + 1) * bitmap.pitch]
            bitmap_rows.append(bytes(
                255 if row_bytes[column >> 3] & (0x80 >> (column & 7)) else 0
                for column in range(bitmap.width)))
        return b"".join(bitmap_rows)

    return b"".join(
        buffer_bytes[row_index * bitmap.pitch:
                     row_index * bitmap.pitch + bitmap.width]
        for row_index in range(bitmap.rows))


# -------------------------------------------------------------- the calls --

def available(font_file):
    """True when FreeType can open this font file."""
    if freetype is None or not font_file or not os.path.exists(font_file):
        return False
    try:
        open_face(font_file)
        return True
    except Exception:
        return False


def advance(font_file, pixel_size, character, make_bold=False,
            width_scale=1.0):
    """The pen step for one character, in pixels, as a float.

    The answer is kept for each distinct call, so a page reads a character's
    step once however many times that character appears.
    """
    cache_key = (font_file, pixel_size, character, bool(make_bold),
                 float(width_scale), HINTING_MODE, ANTIALIAS_MODE,
                 SUBPIXEL_STEPS)
    kept = _kept_advances.get(cache_key)
    if kept is None:
        face, _render_mode = load_character(font_file, pixel_size, character,
                                            make_bold, width_scale)
        # THE DESIGN ADVANCE, not the hinted one, while subpixel placement is
        # on. The hinter grid-fits advance.x to a whole pixel, so with
        # bytecode hinting every step comes back an integer however the caller
        # rounds, and Inter's real steps, 7.488 px for a b and 4.664 for an f
        # at 12 px, are already gone by here.
        # linearHoriAdvance is the design advance scaled to the size, in 16.16
        # fixed point, and the hinter does not touch it. That is the number
        # the font's spacing is drawn from, and drawing the glyph at its
        # fraction is what split_pen() and the phase exist to do.
        if SUBPIXEL_STEPS > 1:
            kept = face.glyph.linearHoriAdvance / 65536.0
        else:
            kept = face.glyph.advance.x / float(FIXED_POINT_26_6)
        _kept_advances[cache_key] = kept
    return kept


def ascent(font_file, pixel_size):
    """The rows from the top of the face's line box down to the baseline."""
    face = open_face(font_file)
    face.set_char_size(height=int(round(pixel_size * FIXED_POINT_26_6)),
                       hres=RESOLUTION_DPI, vres=RESOLUTION_DPI)
    return face.size.ascender / float(FIXED_POINT_26_6)


def glyph(character, font_file, pixel_size, make_bold=False, width_scale=1.0,
          ink_weight=1.0, phase=0.0):
    """One character drawn by FreeType, as (mask, left, top).

    mask is a Pillow image in mode L covering the character's ink, 0 paper and
    255 full ink, or None when the character inks nothing.

    left and top are the offsets from the pen on the baseline. A caller whose
    baseline is on row b pastes the mask at (x + left, b + top). The value of
    top is negative when the ink is above the baseline.

    ink_weight multiplies every coverage value. A value of 1.0 leaves the
    coverage as FreeType made it.

    phase is the fraction of a pixel the pen sits past the whole pixel the
    caller pastes on. It is snapped to one of SUBPIXEL_STEPS positions, so a
    page draws at most that many masks per character instead of one.
    """
    phase = snap_phase(phase)
    cache_key = (character, font_file, pixel_size, bool(make_bold),
                 float(width_scale), float(ink_weight),
                 HINTING_MODE, ANTIALIAS_MODE, INK_WEIGHT, INK_CONTRAST,
                 phase)
    kept = _kept_masks.get(cache_key)
    if kept is not None:
        return kept

    face, render_mode = load_character(font_file, pixel_size, character,
                                       make_bold, width_scale, phase)
    glyph_slot = face.glyph
    glyph_slot.render(render_mode)
    bitmap = glyph_slot.bitmap

    if not bitmap.width or not bitmap.rows:
        answer = (None, 0, 0)
        _kept_masks[cache_key] = answer
        return answer

    mask = Image.frombytes("L", (bitmap.width, bitmap.rows),
                           coverage_from_bitmap(bitmap, render_mode))

    # MacType's curve turns coverage into ink. It runs before the caller's own
    # ink_weight, which is a plain multiplier the renderer uses on a few marks.
    if INK_WEIGHT != 1.0 or INK_CONTRAST != 1.0:
        mask = mask.point(ink_curve())

    if ink_weight and ink_weight != 1.0:
        mask = mask.point([min(255, int(round(level * ink_weight)))
                           for level in range(256)])

    # FreeType counts bitmap_top upward from the baseline. The contract counts
    # top downward, so the sign is turned over here.
    answer = (mask, glyph_slot.bitmap_left, -glyph_slot.bitmap_top)
    _kept_masks[cache_key] = answer
    return answer


# ------------------------------------------------------------------ check --

def demo():
    """Draw one line and assert the contract. Run this file to check it."""
    font_file = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "fonts", "Inter-SemiBold.ttf")
    if not available(font_file):
        print("no Inter at %s" % font_file)
        return 1

    text = "owed = json.loads(path.read_text())  told 1l0O"
    pixel_size = 9

    # every visible character steps the pen forward
    for character in "ow1l":
        step = advance(font_file, pixel_size, character)
        assert step > 0, "advance for %r was %r" % (character, step)

    # a space inks nothing, a letter inks something
    assert glyph(" ", font_file, pixel_size)[0] is None, "the space drew ink"

    mask, _left, top = glyph("o", font_file, pixel_size)
    assert mask is not None, "the o drew no mask"
    assert mask.mode == "L", "the mask is mode %s, not L" % mask.mode
    assert top < 0, "top is %d, it must be negative above the baseline" % top
    assert max(mask.getdata()) > 200, "the o never reached full ink"

    # every hinting mode draws the same character
    global HINTING_MODE
    kept_mode = HINTING_MODE
    try:
        for mode in (HINTING_FONT_BYTECODE, HINTING_OFF, HINTING_AUTO):
            HINTING_MODE = mode
            probe, _l, _t = glyph("H", font_file, pixel_size)
            assert probe is not None, "hinting mode %d drew no H" % mode
    finally:
        HINTING_MODE = kept_mode

    # draw the line and prove ink landed on the page
    line_width = int(sum(advance(font_file, pixel_size, c) for c in text)) + 8
    page = Image.new("L", (line_width, pixel_size * 3), 255)
    pen_x = 4.0
    baseline_row = int(pixel_size * 1.9)
    for character in text:
        mask, left, top = glyph(character, font_file, pixel_size)
        if mask is not None:
            page.paste(0, (int(round(pen_x)) + left, baseline_row + top,
                           int(round(pen_x)) + left + mask.width,
                           baseline_row + top + mask.height), mask)
        pen_x += advance(font_file, pixel_size, character)

    inked_pixels = sum(1 for level in page.getdata() if level < 250)
    assert inked_pixels > 400, \
        "only %d inked pixels, the line did not draw" % inked_pixels

    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "freetype_demo.png")
    page.save(out_file)
    print("hinting %d, antialias %d, %d inked pixels"
          % (HINTING_MODE, ANTIALIAS_MODE, inked_pixels))
    print("wrote %s" % out_file)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(demo())
