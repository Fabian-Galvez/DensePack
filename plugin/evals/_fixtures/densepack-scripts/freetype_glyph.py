"""Reads gray glyphs from FreeType as Pillow masks, on all platforms.

WHAT THIS FILE IS
    This file is the glyph backend, the only one. A glyph backend does one
    job. It gives the renderer the ink of one character and the pen step of
    one character. codepack.py does all other parts of the pack.

WHY THIS FILE EXISTS
    Pillow renders through FreeType, but Pillow does not let the caller pick
    the hinting target, pick the render mode, or make the outline bolder.
    Pillow's C source hardcodes FT_LOAD_DEFAULT. This file calls FreeType
    directly and takes all three settings.

WHAT IT DEPENDS ON
    freetype-py, which is a binding onto the same FreeType C library that
    Pillow already links. Nothing needs a compiler. Tests of this file used
    version 2.13.2.

THE CONTRACT THIS FILE ANSWERS
    Four calls, the one contract that the render loop in codepack.py calls.

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
    The test renders "owed = json.loads(path.read_text())  told 1l0O" in
    Inter at 9 px. It counts the share of inked pixels in the middle grays. A
    sharp glyph puts its pixels at the two ends. A blurred glyph puts them in
    the middle.

        FreeType, LIGHT hinting      66.5 percent of 821 ink pixels
        FreeType, NORMAL hinting     62.5 percent of 815 ink pixels
        FreeType, auto-hinter        44.2 percent of 708 ink pixels

    The auto-hinter is best on the two counts. It puts the least ink in the
    middle grays, and it uses the fewest ink pixels. Its ink is concentrated
    and not spread.

    LIGHT is worse than NORMAL at this size. The FreeType documentation gives
    the reason. LIGHT snaps "glyphs to the pixel grid only vertically". At
    9 px the horizontal snap is what puts a stem on one whole pixel column.

DO NOT SUPERSAMPLE
    A render at four times the size, then reduced to 9 px, is worse at 9 px,
    not better. The same string measures:

        FreeType NORMAL, rendered at 9 px                61.9 percent of  722
        FreeType NORMAL, rendered at 36 px, then to 9 px 51.7 percent of 1138

    The reduced image spreads the same glyphs over 58 percent more ink. Its
    lower middle-gray share is arithmetic, not sharpness. Hinting at 36 px
    fits each stem to the 36 px grid. That grid has no relation to the 9 px
    output grid, and the reduction averages each stem across two output
    columns. MacType does not supersample either. It renders at the size it
    shows.

HOW TO CHECK THIS FILE
    Run it. It renders one line and asserts the contract.

        python plugin/scripts/freetype_glyph.py
"""
import ctypes
import math
import os
import platform
import sys

if sys.platform == "win32":
    # The freetype package calls platform.system() on import. On Python 3.12
    # and later, that call queries the Windows WMI service for the OS version
    # before it checks anything else. One hook process pays for that query
    # once. When thirty-two hook processes query at the same moment, WMI can
    # return no answer to any of them for the length of the hook timeout.
    # Each process waits in platform._wmi_query, the Reads return text, and
    # the service reports "Shutting down" to each other caller on the
    # machine. With the _wmi module set to None, platform gets the version
    # from sys.getwindowsversion(), the path it takes on a Python built
    # without that module, and no hook touches WMI.
    platform._wmi = None

try:
    import freetype
except ImportError:  # pragma: no cover - the caller then uses Pillow
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

# The antialias modes, with MacType's own numbers. The file declares the LCD
# modes, and a setting written against MacType's documentation means the
# same thing here. They must never ship. They target the subpixel geometry of
# a physical display, and this page is a PNG that a model reads.
ANTIALIAS_BILEVEL = -1      # one bit a pixel, ink or paper, no gray
ANTIALIAS_GREY = 0          # eight bits a pixel, grid fitted on the two axes
ANTIALIAS_GREY_LIGHT = 1    # eight bits a pixel, grid fitted vertically only
ANTIALIAS_LCD_RGB = 2
ANTIALIAS_LCD_BGR = 3
ANTIALIAS_LCD_LIGHT_RGB = 4
ANTIALIAS_LCD_LIGHT_BGR = 5

# The two settings that this file renders with. HINTING_MODE defaults to 2,
# the auto-hinter, where MacType's default is 0. DENSEPACK_HINTING overrides
# it. ANTIALIAS_MODE is grayscale, MacType's default.
#
# A measurement on Inter SemiBold at 12 px gives the share of glyph ink that
# lands on a WHOLE pixel and not on partial coverage. Mode 0 gives 17.7
# percent, mode 1 gives 13.4, mode 2 gives 24.0 and mode 3 gives 16.7. A
# stem on a whole pixel looks crisp.
#
# The auto-hinter snaps each stem to the same whole pixel, and it removes
# the difference between weights. At 11 px the widest solid run inside an n
# is 2 px for a 400, a 500 and a 600 face alike. The font's own bytecode
# gives 4 px for a 400 and a 500.
#
# The TrueType interpreter version does not change this. Versions 35 and 40
# render the identical bitmap on Inter, because Inter has little bytecode
# for the interpreter to run.
#
# The auto-hinter also activates two settings that the bytecode interpreter
# never reads, because FreeType defines the two on the auto-hinter. They are
# stem darkening and increase-x-height.
HINTING_MODE = int(os.environ.get("DENSEPACK_HINTING") or HINTING_AUTO)
ANTIALIAS_MODE = ANTIALIAS_GREY

# MacType's HintSmallFont. Its wiki says that it applies the font's embedded
# hinting to fonts below 12 pt, and that it "only functions when HintingMode
# is set to 1".
# Default 0. In ft.cpp the test is
#     if (pSettings->HintSmallFont() && font_type.height < 12)
# which clears FT_LOAD_NO_HINTING for that glyph.
HINT_SMALL_FONT = int(os.environ.get("DENSEPACK_HINT_SMALL_FONT") or 0)
HINT_SMALL_FONT_PT = 12

# MacType's LcdFilter: 0 none, 1 default, 2 light, 3 and 16 legacy. Default 0.
# It acts only in an LCD render mode. It does nothing while ANTIALIAS_MODE
# is grayscale, the one mode that this renderer ships.
LCD_FILTER_NONE, LCD_FILTER_DEFAULT, LCD_FILTER_LIGHT, LCD_FILTER_LEGACY = 0, 1, 2, 3
LCD_FILTER = int(os.environ.get("DENSEPACK_LCD_FILTER") or LCD_FILTER_NONE)

# MacType's GammaMode and GammaValue, from CAlphaBlend::init in ft.cpp:
#
#     if (mode < 0)        temp = (1.0f/255.0f) * i;                  linear
#     else if (mode == 1)  sRGB, with a knee at i <= 10
#     else if (mode == 2)  a hybrid of sRGB and linear
#     else                 temp = pow((1.0f/255.0f) * i, gamma);
#
# The table it fills, tbl1, is not an alpha table. It converts a COLOR to
# linear light. The blend then happens in linear space, and MacType converts
# the result back after it. This renderer never had that stage. Pillow
# composites in sRGB space, where a half-covered pixel looks far lighter than
# half ink.
#
# Default.ini ships GammaMode = -1 and GammaValue = 1.0. The default is a
# linear transfer, which is the same as no blend in linear space at all.
GAMMA_DISABLED, GAMMA_VALUE_MODE, GAMMA_SRGB, GAMMA_HYBRID = -1, 0, 1, 2
# At MacType's default of -1. Each MacType gamma setting here stays where
# Default.ini leaves it.
#
# -1 is a linear transfer. paste_ink() then blends the sRGB numbers directly
# and is arithmetically identical to Pillow's own composite. Mode 1, sRGB,
# converts the two colors to linear light, blends there and converts back.
# That is the physically correct method for an sRGB PNG. It measured 10.7
# percent solid ink against 53.5 percent gray, softer than the 44.8 and 26.9
# that the sRGB-number blend gives, because a blend in linear light makes a
# stroke thinner.
GAMMA_MODE = int(os.environ.get("DENSEPACK_GAMMA_MODE") or GAMMA_DISABLED)
GAMMA_VALUE = float(os.environ.get("DENSEPACK_GAMMA_VALUE") or 1.0)

# MacType's TextTuning, range 0 to 12, default 0, with TextTuningR/G/B per
# channel. In ft.cpp it remaps the alpha before blending:
#     tunetbl[i] = Bound(0, alphatbl[Bound(table[i], 0, 255)], BASE)
# That shifts coverage up by a fixed amount before the lookup of the weight
# and contrast curve. 0 leaves coverage unchanged.
TEXT_TUNING = int(os.environ.get("DENSEPACK_TEXT_TUNING") or 0)

# THE TRUETYPE INTERPRETER VERSION
#
# This is a library property, not a per-load flag. The code sets it once per
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
# HINTING is defined", which each current build defines. A FreeType with no
# change to this property runs v40.
#
# v40 is the reduced subpixel path. It grid-fits vertically and does not
# change the horizontal. That is right for ClearType on a real display and
# wrong here. It lets a stem sit at a fractional horizontal position, and a
# one-pixel stem spreads across two columns of gray. v35 runs the font's
# bytecode fully on the two axes, and a stem snaps to whole pixels.
#
# Under HINTING_MODE 0 the interpreter runs the font's own bytecode, and
# this setting sets how much of it the interpreter runs. The auto-hinter
# modes do not read it.
TT_INTERPRETER_V35, TT_INTERPRETER_V40 = 35, 40
TT_INTERPRETER_VERSION = int(os.environ.get("DENSEPACK_TT_INTERPRETER")
                             or TT_INTERPRETER_V35)


# ------------------------------------------------------- the gamma transfer --
#
# MacType blends a glyph in LINEAR LIGHT. CAlphaBlend::init fills tbl1 with
# the transfer for the mode, the blend happens on those linear values, and
# MacType converts the result back. Pillow's Image.paste does none of that.
# It blends the sRGB numbers directly. A pixel at half coverage lands halfway
# between the two sRGB values, and the eye and a camera see that as far
# lighter than half ink. For that reason an anti-aliased edge looks soft next
# to a rendered rectangle, which has no partly covered pixels at all.
#
# transfer_to_linear() is tbl1. transfer_from_linear() is its inverse. MacType
# needs the inverse too, and ft.cpp builds it with a search of the same table.

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
            # ft.cpp calls this a hybrid of sRGB and linear. The code uses the
            # mean of the two transfers. The ft.cpp curve lies between them.
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
        # take whichever of the two neighbors is nearer in linear light
        if j < 255 and abs(forward[j + 1] - want) < abs(forward[j] - want):
            out.append(j + 1)
        else:
            out.append(j)
    _transfer_cache[key] = out
    return out


def tuning_table():
    """MacType's TextTuning, with coverage shifted up before the curve lookup."""
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

# HOW MANY PLACES INSIDE ONE PIXEL A GLYPH CAN START.
#
# A pen step is a fraction. Inter at 12 px has a step of 7.488 px for a b and
# 4.664 for an f. Rounding each step to a whole pixel makes the spacing
# uneven, because the error is not the same for each letter. b, d, p and q
# each lose 0.49 px. f, g and s gain 0.34, 0.49 and 0.41 px. The spread from
# b to g is 0.98 px on a letter only 7 px wide. At 4 places the pen keeps its fraction and the
# glyph renders at it, with at most an eighth of a pixel of placing error and
# at most four cached masks per character.
#
# The default is 1, WHOLE PIXELS. Subpixel placement renders a glyph at one
# of four offsets inside a pixel, chosen by where its pen lands. Two copies
# of the same letter in one line then have different weights. A snap of each
# glyph to a whole pixel makes each letter identical in all places.
#
# IT COSTS WIDTH. A whole-pixel step rounds each advance up, and an image is
# about 10 percent wider than at 4 steps.
SUBPIXEL_STEPS = int(os.environ.get("DENSEPACK_SUBPIXEL") or 1)


def snap_phase(phase):
    """Return one of SUBPIXEL_STEPS places inside a pixel, as a float in 0.0
    to 1.0.

    Snapping keeps the mask cache small. A value of 1 for SUBPIXEL_STEPS
    disables subpixel placement, and each glyph renders on the whole pixel
    again.

    A phase that snaps up to a whole pixel returns as 0.0. Callers must take
    the whole pixel from split_pen() and not floor the pen themselves. A floor
    first renders such a glyph a whole pixel early.
    """
    if SUBPIXEL_STEPS <= 1 or not phase:
        return 0.0
    phase -= int(phase)
    if phase < 0:
        phase += 1.0
    return round(phase * SUBPIXEL_STEPS) % SUBPIXEL_STEPS / float(SUBPIXEL_STEPS)


def split_pen(x):
    """Return a fractional pen position as (whole pixel to paste on, phase).

    The function picks the two together. It rounds the pen to the nearest of
    the SUBPIXEL_STEPS places first, and only then takes the whole pixel.
    That keeps a pen at x.9 on the pixel above x and not on x itself.
    """
    if SUBPIXEL_STEPS <= 1:
        return int(round(x)), 0.0
    snapped = round(x * SUBPIXEL_STEPS) / float(SUBPIXEL_STEPS)
    whole = int(math.floor(snapped))
    return whole, snapped - whole

# The resolution FreeType scales against. 72 dots an inch makes one point one
# pixel. A size given in pixels then arrives as that many pixels.
RESOLUTION_DPI = 72

# MacType makes a small face bolder by 1/36 of its size, in ft.cpp, for any
# size under 15 px. This file does not use that fraction. It uses its own,
# EMBOLDEN_FRACTION below, with a default of 0.18.
# MacType's BoldWeight, range -32 to +32, default 0. It emboldens a glyph
# marked bold, beyond NormalWeight.
#
# 0.18, to render the four dot marks bold. font.bold names the same file as
# font.regular. There is no bold face to switch to, and the code simulates
# bold with a wider outline. At MacType's default of 0, a character marked
# bold renders the same as one that is not.
#
# MacType's own vertical cap still applies below 15 px. The horizontal widens
# by the full fraction, and the vertical stays at half a pixel or less. That
# cap keeps a bold comma from closing into a blob.
EMBOLDEN_FRACTION = float(os.environ.get("DENSEPACK_BOLD") or 0.18)
# MacType's FT_BOLD_LOW. Below this size it caps the vertical widening.
EMBOLDEN_SIZE_LIMIT_PX = 15
# MacType's Min(long(32), str_v): 32 units in 26.6 fixed point is half a pixel.
EMBOLDEN_VERTICAL_CAP = 32

# STEM_FRACTION widens EACH glyph, not only the glyphs that the source text
# marks bold. It defaults to 0.0, MacType's NormalWeight default. Stock
# MacType emboldens nothing, and the weight of the face sets the stroke.
# DENSEPACK_STEM overrides it. A sweep of the fraction then needs no edit.
#
# FT_Outline_EmboldenXY is the call that adds a pixel to a stem. The ink
# curve cannot do it, because the curve only changes the gray of a pixel
# that the outline already covers.
#
# A sweep of the fraction on one code file measured:
#   0.000   stroke 1.92 px   49.5 percent of dark runs only one pixel wide
#   0.100   stroke 2.05 px   41.9 percent
#   0.220   stroke 2.32 px   27.2 percent
#
# Below 15 px the widening grows in proportion to the size. At 15 px and
# above it stays at the 15 px amount. See load_character().
STEM_FRACTION = float(os.environ.get("DENSEPACK_STEM") or 0.0)

# STEM DARKENING
#
# A screen applies gamma correction. Gamma correction makes thin ink look
# thinner than it is. At a small size a stem is about one pixel wide. The
# whole letter is thin ink, and the letter looks faint. The FreeType
# documentation states the problem and the answer. Stem darkening "emboldens
# glyphs at smaller point sizes to counteract the visual thinning that
# occurs with gamma correction".
#
# The auto-hinter has stem darkening OFF by default. The property
# "no-stem-darkening" holds TRUE for the auto-hinter, and TRUE means off.
# FALSE activates the darkening.
#
# STEM_DARKENING True passes FALSE to that property, which activates the
# darkening. FreeType defines stem darkening only on the auto-hinter and the
# Adobe CFF/Type1/CID engines. It can act under HINTING_MODE 2 and 3 and does
# nothing under the TrueType bytecode interpreter. On the FreeType build of
# the measurements, the two values rendered identical bitmaps.
STEM_DARKENING = True

# The darkening curve, as pairs of (stem width, how much to darken), the two in
# thousandths of a pixel. These are Adobe's defaults, quoted in the FreeType
# properties reference:
#
#     stem 0.5 px or less  darken by 0.400 px
#     stem 1.000 px        darken by 0.275 px
#     stem 1.667 px        darken by 0.275 px
#     stem 2.333 px+       darken by 0.000 px
#
# A 9 px page renders stems near 1 px, and it gets the 0.275 px step.
DARKENING_PARAMETERS = (500, 400, 1000, 275, 1667, 275, 2333, 0)

# INCREASE X HEIGHT
#
# The FreeType documentation says this property "improves small font
# legibility" by rounding the font's x height up "much more often than
# normally" for sizes from 6 pixels up to the limit set here. A taller x
# height gives a lowercase letter more rows to hold its shape in.
# 14 is the size limit. FreeType's own default is 0, which means off.
# FreeType defines increase-x-height on the auto-hinter alone. It acts under
# HINTING_MODE 2 and 3 and not under the font's own bytecode.
INCREASE_X_HEIGHT_LIMIT = 14

# THE INK CURVE
#
# FreeType returns coverage, which is how much of a pixel the outline covers.
# Coverage is not ink. A screen applies gamma. A pixel at half coverage does
# not look like half ink. It looks much lighter. At 9 px most of a letter is
# partial coverage, and the whole letter looks light.
#
# MacType uses a table for this, in CAlphaBlend::init in ft.cpp:
#
#     temp = pow((1.0f / 255.0f) * i, 1.0f / weight);
#     if (temp < 0.5f)
#         alpha = pow(temp * 2, contrast) / 2.0f;
#     else
#         alpha = 1.0f - pow((1.0f - temp) * 2, contrast) / 2.0f;
#     alphatbl[i] = (int)(alpha * BASE);
#
# The first line is the gamma. The two after it are an S curve about the
# midpoint, which makes light coverage lighter and heavy coverage heavier.
# An edge then becomes sharper and does not smear.
#
# INK_WEIGHT is MacType's RenderWeight. Above 1.0 the whole letter darkens.
# INK_CONTRAST is MacType's Contrast. Above 1.0 the S curve steepens.
# The two at 1.0 leave the coverage exactly as FreeType made it.
#
# DENSEPACK_INK_WEIGHT and DENSEPACK_INK_CONTRAST override these. A sweep of
# the curve then needs no edit.
#
# The two are above MacType's default of 1.0 on purpose. MacType tunes for an
# eye that reads a physical display, where the gray transition pixels of an
# anti-aliased edge make a stroke look smooth. A model reads this image from
# a PNG, where those gray pixels give little and cost edge definition.
#
# THE TWO WORK AGAINST EACH OTHER ABOVE A WEIGHT OF ABOUT 2. RenderWeight is
# a gamma exponent, and it raises each partly covered pixel. Contrast is an S
# curve about the midpoint, and it moves the lower half back toward paper.
# After the weight raises the mid pixels, more contrast moves the pixels a
# little under half back down.
#
# The pair depends on the size and the face. A pair for one size and face
# does not work for another. A curve made to fix a thin face moves the edge
# pixels of a heavier face into the gray band. At 11 px with weight 2.2 and
# contrast 1.2, Regular 400 lays 70.2 percent solid ink, Medium 500 lays 56.0
# and SemiBold 600 lays 47.5. A change to CODE_PX or the face needs a new
# sweep of the two, from MacType's default.
#
# Neither knob changes a metric. The image is the same size at each value.
#
# INK_WEIGHT is MacType RenderWeight, a gamma on coverage. Above 1 it darkens
# each partly covered pixel.
INK_WEIGHT = float(os.environ.get("DENSEPACK_INK_WEIGHT") or 1.1)
# INK_CONTRAST is MacType Contrast. Above 1 it moves a partly covered pixel
# toward full ink or full paper. On the snapped image that is the intent.
# Solid ink goes from 45.6 percent at contrast 1.0 to 68.5 at 3.0, and the
# faintest edge pixels become paper and do not stay gray.
#
# ON AN UNSNAPPED IMAGE THE SAME VALUE DELETES THE ANTIALIASED RIM, and the
# letters look stepped. The two settings belong together.
INK_CONTRAST = float(os.environ.get("DENSEPACK_INK_CONTRAST") or 3.0)


# ------------------------------------------------------------------ caches --

# True after the code sets the library level properties, once a process.
_library_properties_set = [False]

# One open FreeType face for each font file. Opening a face reads the file.
_open_faces = {}

# One kept answer for each distinct call. A page pays for a character once.
_kept_masks = {}
_kept_advances = {}


# ----------------------------------------------------------------- helpers --

def apply_library_properties():
    """Set the auto-hinter properties this file depends on, once per process.

    These properties belong to the library, not to a face. The function sets
    them once, and each face opened after that uses them.
    """
    if _library_properties_set[0] or freetype is None:
        return
    _library_properties_set[0] = True
    library = freetype.get_handle()

    # The TrueType interpreter version. The code must set it before it loads
    # any face, because a face caches the version that it opened under.
    try:
        version = ctypes.c_uint(int(TT_INTERPRETER_VERSION))
        freetype.FT_Property_Set(library, b"truetype", b"interpreter-version",
                                 ctypes.byref(version))
    except Exception:
        # A build without the TrueType driver, or an older FreeType. The page
        # still renders, at the default version of that build.
        pass

    # no-stem-darkening takes TRUE for off. Pass FALSE to activate darkening.
    darkening_off = ctypes.c_bool(not STEM_DARKENING)
    try:
        freetype.FT_Property_Set(library, b"autofitter", b"no-stem-darkening",
                                 ctypes.byref(darkening_off))
    except Exception:
        # An older FreeType has no such property. The page still renders.
        pass

    # darkening-parameters takes eight integers, four (width, amount) pairs.
    try:
        curve = (ctypes.c_int * 8)(*DARKENING_PARAMETERS)
        freetype.FT_Property_Set(library, b"autofitter",
                                 b"darkening-parameters", ctypes.byref(curve))
    except Exception:
        pass


def apply_face_properties(face):
    """Set the properties that belong to one face.

    The function sets increase-x-height for each face. The FreeType
    documentation says to set it after the size and before a glyph load.
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


# The share of a text's non-space characters that the font can lack. A few
# emoji become boxes, and the model reads those lines from the text. A file
# mostly in Chinese, Japanese or Korean becomes nothing but boxes.
MISSING_GLYPH_MAX = 0.02


def font_covers(text, font_file):
    """Return True when the font can render all but MISSING_GLYPH_MAX of the
    text.

    The function is here, not in codepack, and the Read gate can call it
    before it loads the renderer and NumPy."""
    return missing_share(text, font_file) <= MISSING_GLYPH_MAX


def missing_share(text, font_file):
    """Return the share of the text's non-space characters that this font has
    no glyph for.

    Inter has no Chinese, Japanese, Korean or emoji glyphs, and each of those
    characters renders as an empty box. Return 0.0 when FreeType or the font
    is missing, because the caller then cannot measure coverage at all."""
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
    """Return the FreeType load flags and render mode that the two settings
    select.

    Returns a pair. The first is the flags for FT_Load_Char. The second is the
    mode for FT_Render_Glyph.
    """
    load_flags = LOAD_FLAGS_ALWAYS

    if HINTING_MODE == HINTING_OFF:
        load_flags |= freetype.FT_LOAD_NO_HINTING
    elif HINTING_MODE in (HINTING_AUTO, HINTING_AUTO_LIGHT):
        load_flags |= freetype.FT_LOAD_FORCE_AUTOHINT

    # Mode 3 forces the light target. MacType documents it as "use freetype
    # light autohinter to generate hinting. This options must be used
    # together with 'AntiAliasMode' light mode". For that reason the code
    # forces the light target here and does not leave it to the antialias
    # setting. The two are one mode, and mode 3 with a normal target is the
    # same as mode 2.
    #
    # FT_LOAD_TARGET_LIGHT grid-fits vertically only and does not change the
    # horizontal. MacType and fontconfig's hintslight mean this by light
    # hinting.
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
    """Load one character into the face's glyph slot, and return how to
    render it.

    The function loads the glyph but does not render it yet. The code can
    then make the outline bolder first. Returns the face and the render mode.

    phase is where the pen is between two whole pixels, 0.0 up to 1.0. The
    function shifts the outline right by that fraction before the render. A
    glyph whose pen lands at x.5 then renders half a pixel along, not at x.
    Without it, each pen step must be a whole number, and rounding loses the
    font's real advances, which are fractions.
    """
    face = open_face(font_file)
    size_fixed = int(round(pixel_size * FIXED_POINT_26_6))
    face.set_char_size(width=int(round(size_fixed * float(width_scale))),
                       height=size_fixed,
                       hres=RESOLUTION_DPI, vres=RESOLUTION_DPI)
    apply_face_properties(face)

    load_flags, render_mode = load_flags_and_render_mode()

    # A look-alike character renders Inter's own alternate, by glyph index.
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
    # FT_BOLD_LOW is 15. Below 15 px, MacType caps the VERTICAL widening at
    # 32 units, which is 0.5 px in 26.6 fixed point, and does not cap the
    # horizontal. The vertical cap keeps a horizontal bar thin and a counter
    # open at a small size. Widening y as much as x fills the hole in an e and
    # makes the crossbar of a 3 thicker.
    #
    # MacType's own strength comes from CalcNormalWeight(), and NormalWeight
    # defaults to 0. Stock MacType emboldens nothing. STEM_FRACTION and
    # EMBOLDEN_FRACTION are this renderer's own choice. The vertical cap
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
            # An older binding can lack the call. A glyph that is not made
            # bolder still renders correctly. This is not an error.
            pass

    # The subpixel shift comes last. It then moves the outline that the
    # embolden step widened. FreeType computes bitmap_left from the shifted
    # outline. The caller pastes at the whole pixel below the pen, and the
    # fraction is already in the mask.
    if phase:
        try:
            freetype.FT_Outline_Translate(
                face.glyph.outline._FT_Outline,
                int(round(phase * FIXED_POINT_26_6)), 0)
        except Exception:
            # Without the call, the glyph renders on the whole pixel.
            pass

    return face, render_mode


# THE LOOK-ALIKE GLYPHS
#
# Two pairs confuse a model at a small size. A model that mistakes one of
# them writes a wrong character, and that costs a rebuild. The pairs are:
#
#   the digit zero against the capital O
#   the digit one against the lowercase l
#
# Inter has alternates in the same file at the same size:
#
#   zero.slash  the zero with a slash through it
#   one.ss01    the one with a foot, and not a bare stem
#
# On the plain glyphs, the digit zero and the capital O look the same in
# each row, even at 7 times size. No ink curve fixes this, because the plain
# glyphs do not have the marks.
#
# The code does not use l.ss02, the l with a tail. At 9 px it inks two
# columns where the plain l inks one, at the same 3 px advance and the same
# left bearing. It fills its cell and leaves no clear column on its right.
# one.ss01 already separates the pair, with a 3 column wide digit with a foot
# against a 1 column bare stem. The two alternates in use cost nothing,
# because their metrics match the plain glyph exactly:
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

    A face without the alternate gives None, and the character then renders
    its plain glyph.
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
    1.0 gives the identity, and the coverage stays unchanged.
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

    A gray bitmap already holds one byte a pixel. Each row is bitmap.pitch
    bytes long, which can be wider than the glyph. The function cuts each
    row to the glyph's own width.

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
    """Return the pen step for one character, in pixels, as a float.

    The function keeps the answer for each distinct call. A page reads a
    character's step once, however many times that character appears.
    """
    cache_key = (font_file, pixel_size, character, bool(make_bold),
                 float(width_scale), HINTING_MODE, ANTIALIAS_MODE,
                 SUBPIXEL_STEPS)
    kept = _kept_advances.get(cache_key)
    if kept is None:
        face, _render_mode = load_character(font_file, pixel_size, character,
                                            make_bold, width_scale)
        # THE DESIGN ADVANCE, not the hinted one, while subpixel placement is
        # on. The hinter grid-fits advance.x to a whole pixel. With bytecode
        # hinting, each step returns as an integer however the caller rounds,
        # and Inter's real steps, 7.488 px for a b and 4.664 for an f at
        # 12 px, are already gone at this point.
        # linearHoriAdvance is the design advance scaled to the size, in 16.16
        # fixed point, and the hinter does not touch it. The font's spacing
        # comes from that number. split_pen() and the phase exist to render
        # the glyph at its fraction.
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
    """Return one character rendered by FreeType, as (mask, left, top).

    mask is a Pillow image in mode L covering the character's ink, 0 paper and
    255 full ink, or None when the character inks nothing.

    left and top are the offsets from the pen on the baseline. A caller whose
    baseline is on row b pastes the mask at (x + left, b + top). The value of
    top is negative when the ink is above the baseline.

    ink_weight multiplies each coverage value. A value of 1.0 leaves the
    coverage as FreeType made it.

    phase is the fraction of a pixel that the pen is past the whole pixel the
    caller pastes on. The function snaps it to one of SUBPIXEL_STEPS
    positions. A page then renders at most that many masks per character
    instead of one.
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

    # MacType's curve converts coverage to ink. It runs before the caller's
    # own ink_weight, a plain multiplier that the renderer uses on a few marks.
    if INK_WEIGHT != 1.0 or INK_CONTRAST != 1.0:
        mask = mask.point(ink_curve())

    if ink_weight and ink_weight != 1.0:
        mask = mask.point([min(255, int(round(level * ink_weight)))
                           for level in range(256)])

    # FreeType counts bitmap_top upward from the baseline. The contract counts
    # top downward. The code reverses the sign here.
    answer = (mask, glyph_slot.bitmap_left, -glyph_slot.bitmap_top)
    _kept_masks[cache_key] = answer
    return answer


# ------------------------------------------------------------------ check --

def demo():
    """Render one line and assert the contract. Run this file to check it."""
    font_file = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "fonts", "Inter-SemiBold.ttf")
    if not available(font_file):
        print("no Inter at %s" % font_file)
        return 1

    text = "owed = json.loads(path.read_text())  told 1l0O"
    pixel_size = 9

    # each visible character moves the pen forward
    for character in "ow1l":
        step = advance(font_file, pixel_size, character)
        assert step > 0, "advance for %r was %r" % (character, step)

    # a space inks nothing, a letter inks something
    assert glyph(" ", font_file, pixel_size)[0] is None, "the space rendered ink"

    mask, _left, top = glyph("o", font_file, pixel_size)
    assert mask is not None, "the o rendered no mask"
    assert mask.mode == "L", "the mask is mode %s, not L" % mask.mode
    assert top < 0, "top is %d. It must be negative above the baseline." % top
    assert max(mask.getdata()) > 200, "the o never reached full ink"

    # each hinting mode renders the same character
    global HINTING_MODE
    kept_mode = HINTING_MODE
    try:
        for mode in (HINTING_FONT_BYTECODE, HINTING_OFF, HINTING_AUTO):
            HINTING_MODE = mode
            probe, _l, _t = glyph("H", font_file, pixel_size)
            assert probe is not None, "hinting mode %d rendered no H" % mode
    finally:
        HINTING_MODE = kept_mode

    # render the line and prove that ink landed on the page
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
        "only %d inked pixels, and the line did not render" % inked_pixels

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
