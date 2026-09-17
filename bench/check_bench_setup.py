"""Prove the renderer and the bench setup once, before any bench spends money.

    python bench/check_bench_setup.py

It converts bench/single-1000-token-file/subject-ab_run.py, the same bytes as
tools/ab_run.py, through the plugin folder Claude Code runs, with the
bench settings, and prints the image size, its visual tokens and its md5
against the image the benches were scored on. It then draws the instruction
cards into a fresh folder, which also fills the machine card cache under
~/.claude/densepack-cards so every later bench leg copies them in under a
second instead of drawing them. It prints PASS when every check holds.

The benches themselves never need the cards redrawn. This script is the one
place that proves they draw.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
# The same bytes as tools/ab_run.py, and this copy ships with the benches.
SOURCE = REPO / "bench" / "single-1000-token-file" / "subject-ab_run.py"
# The image the plugin ships. The benches scored md5 df949a325598, which
# differs only in the top line of the key row's two mark boxes. Update this
# line when the image changes on purpose. The check compares the decoded
# pixels, because Pillow builds compress the same pixels to different PNG
# bytes: Linux with Pillow 12.3.0 writes md5 a6b2b85b0b21 for this image.
EXPECTED = {"pixels": "fe3e6449f9e1", "md5": "ca66e198d2df", "size": (784, 896), "tokens": 896}
CODE_PX = "17"


def draw_page(env):
    code = (
        "import sys,hashlib;sys.path.insert(0,%r);import codepack,common;"
        "p,_t,_l=codepack.pack_code(open(%r,encoding='utf-8').read(),common.code_size(None,None),%r,python=False,legend=None,reader='sonnet',title='ab_run.py');"
        "print(p[0][0])"
    ) % (str(PLUGIN / "scripts"), str(SOURCE), str(Path(tempfile.mkdtemp()) / "setupcheck"))
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if r.returncode or not lines:
        print("FAIL  the page did not draw:", r.stderr[-600:])
        return None
    return Path(lines[-1])


def draw_cards(env):
    folder = Path(tempfile.mkdtemp(prefix="densepack-cards-"))
    code = (
        "import sys,os,io,json;sys.path.insert(0,%r);os.chdir(%r);os.environ['CLAUDE_PROJECT_DIR']=%r;"
        "import bootstrap;bootstrap.draw_instruction_images()"
    ) % (str(PLUGIN / "scripts"), str(folder), str(folder))
    t0 = time.time()
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=str(folder))
    secs = time.time() - t0
    pngs = sorted(folder.glob("**/*.png"))
    if r.returncode:
        print("FAIL  the cards did not draw:", r.stderr[-600:])
    shutil.rmtree(folder, ignore_errors=True)
    return len(pngs), secs


def main():
    ok = True
    # The recipe is the plugin's own defaults, so a download without it makes
    # the same bytes.
    env = dict(os.environ, DENSEPACK_CODE_PX=CODE_PX)
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    print("plugin folder :", PLUGIN)
    # /plugin install puts Pillow, freetype-py and NumPy in the plugin's own
    # data folder, where a plain python3 does not look. The hooks add it in
    # common.ensure_pillow(), and this check adds the same folder.
    data = os.environ.get("CLAUDE_PLUGIN_DATA") or str(
        Path.home() / ".claude" / "plugins" / "data" / "densepack-densepack-marketplace")
    pylibs = Path(data) / "pylibs"
    if pylibs.is_dir():
        sys.path.insert(0, str(pylibs))
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(pylibs), env.get("PYTHONPATH", "")) if part)
        print("packages from :", pylibs)
    try:
        from PIL import Image  # noqa: F401
        import PIL
        print("Pillow        :", PIL.__version__)
    except ImportError:
        print("FAIL  Pillow is not installed for", sys.executable)
        return 1
    # Without freetype-py the renderer falls back to Pillow and makes a
    # different image, so a missing package fails here by name.
    for module, name in (("freetype", "freetype-py"), ("numpy", "NumPy")):
        try:
            __import__(module)
        except ImportError:
            print("FAIL  %s is not installed for %s. Start Claude Code once with DensePack on, "
                  "so the plugin installs it, then run this check again." % (name, sys.executable))
            return 1
    sys.path.insert(0, str(PLUGIN / "scripts"))
    try:
        import freetype_glyph
        print("FreeType      : hinting mode %s, subpixel steps %s" % (freetype_glyph.HINTING_MODE, freetype_glyph.SUBPIXEL_STEPS))
    except Exception as exc:  # noqa: BLE001
        print("FAIL  freetype_glyph did not import:", exc)
        return 1

    page = draw_page(env)
    if page is None:
        return 1
    from PIL import Image
    with Image.open(page) as im:
        size = im.size
        pixels = hashlib.md5(im.convert("RGB").tobytes()).hexdigest()[:12]
    tokens = -(-size[0] // 28) * -(-size[1] // 28)
    md5 = hashlib.md5(page.read_bytes()).hexdigest()[:12]
    same = pixels == EXPECTED["pixels"]
    print("image         : %s by %s, %d visual tokens, pixel md5 %s, file md5 %s, %s"
          % (size[0], size[1], tokens, pixels, md5, "the shipped image" if same
             else "NOT the shipped image, pixel md5 %s" % EXPECTED["pixels"]))
    ok &= same
    shutil.rmtree(page.parent, ignore_errors=True)

    # Instruction cards exist only where plugin/instructions does. The
    # download ships none, so it checks no cards and prints no cards line.
    if (Path(__file__).resolve().parents[1] / "plugin" / "instructions").is_dir():
        count, secs = draw_cards(env)
        cache = Path.home() / ".claude" / "densepack-cards"
        cached = len(list(cache.iterdir())) if cache.is_dir() else 0
        print("cards         : %d images in %.1f seconds, %d cards in the machine cache %s" % (count, secs, cached, cache))
        ok &= count >= 7
        if secs > 5:
            print("                the first draw fills the cache; run this again and it should take under a second")

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
