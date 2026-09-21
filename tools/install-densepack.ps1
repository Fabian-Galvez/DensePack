# Install everything the DensePack right-click tool needs, in one run.
#
#   .\install-densepack.ps1             install all of it
#   .\install-densepack.ps1 -NoCard     skip the Claude Code reading card
#   .\install-densepack.ps1 -NoHotkey   skip AutoHotkey and the Ctrl+Shift+D hotkey
#   .\install-densepack.ps1 -Remove     take all of it back out
#
# This script installs Python 3.13 and AutoHotkey v2 with winget, and Pillow,
# freetype-py and NumPy with pip, when they are missing. Python and the
# packages install for the current user. AutoHotkey installs for the whole
# machine, so Windows can ask for administrator rights for that one step.
#
# The script writes three things, all under the current user and none of them
# machine-wide:
#
#   HKCU\Software\Classes\*\shell\DensePack   the right-click entry
#   the Startup folder                        the hotkey shortcut
#   ~\.claude\hooks and ~\.claude\settings.json   the reading card
#
# -Remove undoes all three.

param([switch]$Remove, [switch]$NoCard, [switch]$NoHotkey)

$ErrorActionPreference = 'Stop'

$tools  = $PSScriptRoot
$packer = Join-Path $tools 'densepack.py'
$clip   = Join-Path $tools 'densepack-clip.ps1'
$ahk    = Join-Path $tools 'DensePack.ahk'
$card   = Join-Path $tools 'reading_card.py'

$fileKey = 'HKCU:\Software\Classes\*\shell\DensePack'
$startup = [Environment]::GetFolderPath('Startup')
$link    = Join-Path $startup 'DensePack.lnk'

# The reading card is a Claude Code hook, so it lives beside Claude Code's own
# settings rather than in this folder. Installed here because packing an image
# is only half the job: without a standing instruction Claude can describe a
# condensed image, this tool's name for text drawn as a small picture,
# instead of acting on it, and the user would have to type an
# explanation every time.
$claudeHooks = Join-Path $HOME '.claude\hooks'
$cardTarget  = Join-Path $claudeHooks 'densepack_reading_card.py'
$claudeSettings = Join-Path $HOME '.claude\settings.json'

# The reading card hook is registered in $claudeSettings by Python, never by
# PowerShell. PowerShell 5.1's Set-Content -Encoding utf8 put a UTF-8 BOM on
# the file, Claude Code then rejected the whole file, ignored every setting in
# it, model included, and ran the default model. Python's json writes the
# file back exactly, adds or removes the one entry, and writes no BOM.
# argv: settings path, "add" or "remove", python path, card path.
# Single quotes only: PowerShell strips double quotes from an argument it
# hands a native command, and the snippet travels as one -c argument.
$hookEdit = @'
import json, sys
p, op = sys.argv[1], sys.argv[2]
try:
    d = json.loads(open(p, encoding='utf-8-sig').read())
except FileNotFoundError:
    d = {}
hooks = d.setdefault('hooks', {}).setdefault('UserPromptSubmit', [])
hooks[:] = [h for h in hooks if 'densepack_reading_card' not in json.dumps(h)]
if op == 'add':
    hooks.append({'hooks': [{'type': 'command', 'command': sys.argv[3], 'args': [sys.argv[4]]}]})
s = json.dumps(d, indent=2) + chr(10)
json.loads(s)
open(p, 'w', encoding='utf-8', newline=chr(10)).write(s)
'@

function Remove-ReadingCard {
    if (Test-Path $cardTarget) { Remove-Item $cardTarget -Force }
    # -Remove runs before Find-Python is defined, so look Python up here.
    $py = @(Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source } |
            Where-Object { $_ -notmatch 'WindowsApps' })[0]
    if ($py -and (Test-Path $claudeSettings)) {
        & $py -c $hookEdit $claudeSettings remove
        'removed the reading card hook'
    } else {
        "no Python found, so the reading card entry in $claudeSettings was left in place"
    }
}

if ($Remove) {
    if (Test-Path -LiteralPath $fileKey) { Remove-Item -LiteralPath $fileKey -Recurse -Force; 'removed the right-click entry' }
    if (Test-Path $link)    { Remove-Item $link -Force; 'removed the startup entry' }
    Remove-ReadingCard
    # Stop only the AutoHotkey process that runs DensePack.ahk, never the user's other scripts.
    Get-CimInstance Win32_Process -Filter "Name LIKE 'AutoHotkey%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*DensePack.ahk*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    # The hotkey's two small files. The vault folders stay: they contain the user's text.
    foreach ($f in @('tool.ini', 'last-pack.txt')) {
        $p = Join-Path (Join-Path $env:LOCALAPPDATA 'DensePack') $f
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force }
    }
    'done'
    return
}

foreach ($f in @($packer, $clip, $ahk, $card)) {
    if (-not (Test-Path $f)) { throw "Missing $f" }
}

# ---------------------------------------------------------------- what this tool needs
# Python and Pillow are installed here, so the whole install is one
# double-click on a machine that has neither. It used to stop with "Install
# Python, then rerun", and it never installed Pillow at all, so the right-click
# entry failed on its first use even after the user installed Python by hand.
#
# The bare name "python" can resolve to the Windows Store alias stub, whose only
# behavior is to open the Microsoft Store. Explorer and AutoHotkey launch with
# their own PATH, so the real interpreter's full path is written in instead.
# A candidate has to print its own version. A python.bat that ignores its
# arguments and exits 0 is not an interpreter, and Pillow cannot install into it.
function Test-RealPython($c) {
    if ($c -notmatch '\.exe$') { return $false }
    $out = (& $c -c "import sys; print('DENSEPACKPY', sys.version_info[0], sys.version_info[1])" 2>$null |
            Select-Object -Last 1)
    if ("$out" -match '^DENSEPACKPY (\d+) (\d+)$') {
        return ([int]$Matches[1] -gt 3) -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10)
    }
    return $false
}

function Find-Python {
    # python3 and py as well: a machine whose only Python answers to py.exe
    # would otherwise be sent to winget to install a Python it already has.
    $candidates = @(Get-Command python, python3, py -All -ErrorAction SilentlyContinue |
                    ForEach-Object { $_.Source })
    $candidates += @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Filter 'python.exe' `
                        -Recurse -Depth 1 -ErrorAction SilentlyContinue |
                     ForEach-Object { $_.FullName })
    foreach ($c in $candidates) {
        if ($c -and $c -notmatch 'WindowsApps' -and (Test-Path $c) -and (Test-RealPython $c)) { return $c }
    }
    return $null
}

# winget ships with Windows 10 1809 and every Windows 11. User scope means no
# administrator prompt.
function Install-WithWinget($id, $label, $userScope) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "$label is missing and winget is not on this machine. Install $label, then run this installer again."
    }
    "installing $label"
    $winArgs = @('install', '--id', $id, '-e', '--source', 'winget',
                 '--accept-package-agreements', '--accept-source-agreements')
    if ($userScope) { $winArgs += @('--scope', 'user') }
    & winget @winArgs | Out-Null
}

$python = Find-Python
if (-not $python) {
    Install-WithWinget 'Python.Python.3.13' 'Python 3.13' $true
    # winget updates PATH for new processes only, so this one reloads it.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
    $python = Find-Python
}
if (-not $python) { throw 'Python installed but no python.exe was found. Run this installer again.' }
"using $python"

# Pillow draws the image. find_spec returns without raising and the exit code
# stays 0 either way, so this check never trips $ErrorActionPreference.
$havePillow = & $python -c "import importlib.util,sys; sys.stdout.write('yes' if importlib.util.find_spec('PIL') else 'no')"
if ($havePillow -ne 'yes') {
    'installing Pillow'
    & $python -m pip install --quiet --user --only-binary :all: "pillow>=12" | Out-Null
    $havePillow = & $python -c "import importlib.util,sys; sys.stdout.write('yes' if importlib.util.find_spec('PIL') else 'no')"
}
if ($havePillow -ne 'yes') { throw "Pillow did not install. Run: `"$python`" -m pip install pillow" }
'Pillow ready'

# freetype-py draws the glyphs. Without it the image falls back to Pillow and
# differs from the plugin's image.
$haveFreetype = & $python -c "import importlib.util,sys; sys.stdout.write('yes' if importlib.util.find_spec('freetype') else 'no')"
if ($haveFreetype -ne 'yes') {
    'installing freetype-py'
    & $python -m pip install --quiet --user --only-binary :all: "freetype-py>=2" | Out-Null
    $haveFreetype = & $python -c "import importlib.util,sys; sys.stdout.write('yes' if importlib.util.find_spec('freetype') else 'no')"
}
if ($haveFreetype -ne 'yes') { throw "freetype-py did not install. Run: `"$python`" -m pip install freetype-py" }
'freetype-py ready'

# NumPy blends each glyph into the image.
$haveNumpy = & $python -c "import importlib.util,sys; sys.stdout.write('yes' if importlib.util.find_spec('numpy') else 'no')"
if ($haveNumpy -ne 'yes') {
    'installing numpy'
    & $python -m pip install --quiet --user --only-binary :all: "numpy>=2" | Out-Null
    $haveNumpy = & $python -c "import importlib.util,sys; sys.stdout.write('yes' if importlib.util.find_spec('numpy') else 'no')"
}
if ($haveNumpy -ne 'yes') { throw "numpy did not install. Run: `"$python`" -m pip install numpy" }
'numpy ready'

# ---------------------------------------------------------------- right-click on a file
# One menu item, DensePack it. It runs the packer with no size, so the packer
# draws the plugin's one page: common.CODE_PX, 17 px unless DENSEPACK_CODE_PX
# names another number. The item held a per-model size menu until
# 12 September 2026.
if (Test-Path -LiteralPath $fileKey) { Remove-Item -LiteralPath $fileKey -Recurse -Force }
New-Item -Path $fileKey -Force | Out-Null
Set-ItemProperty -LiteralPath $fileKey -Name 'MUIVerb' -Value 'DensePack it'
$icon = Join-Path (Split-Path $PSScriptRoot -Parent) 'icon\DensePack.ico'
if (Test-Path $icon) { Set-ItemProperty -LiteralPath $fileKey -Name 'Icon' -Value $icon }
else { Set-ItemProperty -LiteralPath $fileKey -Name 'Icon' -Value 'imageres.dll,-72' }
$c = Join-Path $fileKey 'command'
New-Item -Path $c -Force | Out-Null
$cmd = '"' + $python + '" "' + $packer + '" "%1" --out "%1.densepack"'
Set-ItemProperty -LiteralPath $c -Name '(Default)' -Value $cmd
'right-click entry added: DensePack it, on any file'

# ---------------------------------------------------------------- the hotkey
# AutoHotkey runs Ctrl+Shift+D. It is installed here too, so one double-click
# covers the hotkey as well as the right-click entry. A failed AutoHotkey
# install never stops the installer, because the right-click entry works
# without it. -NoHotkey skips this whole section.
function Find-AutoHotkey {
    foreach ($p in @("$env:ProgramFiles\AutoHotkey\v2\AutoHotkey64.exe",
                     "$env:ProgramFiles\AutoHotkey\AutoHotkey.exe",
                     "$env:ProgramFiles\AutoHotkey\v2\AutoHotkey32.exe",
                     "$env:LOCALAPPDATA\Programs\AutoHotkey\v2\AutoHotkey64.exe")) {
        if (Test-Path $p) { return $p }
    }
    foreach ($root in @("$env:ProgramFiles\AutoHotkey",
                        "$env:LOCALAPPDATA\Programs\AutoHotkey")) {
        $found = Get-ChildItem $root -Filter 'AutoHotkey*.exe' -Recurse -ErrorAction SilentlyContinue |
                 Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

$ahkExe = $null
if ($NoHotkey) {
    'hotkey skipped, -NoHotkey was passed'
} else {
    $ahkExe = Find-AutoHotkey
    if (-not $ahkExe) {
        try {
            Install-WithWinget 'AutoHotkey.AutoHotkey' 'AutoHotkey v2' $false
            $ahkExe = Find-AutoHotkey
        } catch {
            'AutoHotkey did not install. The right-click entry still works.'
        }
    }
}

if ($ahkExe) {
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut($link)
    $s.TargetPath = $ahkExe
    $s.Arguments = '"' + $ahk + '"'
    $s.WorkingDirectory = $tools
    $s.Save()
    Start-Process $ahkExe -ArgumentList "`"$ahk`""
    "hotkey running and set to start with Windows, using $ahkExe"
    'Ctrl+Shift+D packs the selection and replaces it. Ctrl+Shift+C packs to the clipboard.'
} else {
    'AutoHotkey was not found, so the hotkey was skipped. The right-click entry still works.'
}

# ---------------------------------------------------------------- the reading card
# A UserPromptSubmit hook that tells Claude, in every project, that a condensed
# color coded image from the user IS the user's prompt. Without it Claude can
# read a packed image as a picture to describe rather than instructions to act
# on, and the user would have to explain that by hand each time.
#
# It stays quiet wherever the DensePack PLUGIN is running, because the plugin's
# own standing reminder, the short text sent before each message, says the same
# thing and more, and two of them would arrive on every message and cost twice.
if ($NoCard) {
    'reading card skipped, -NoCard was passed'
} else {
    New-Item -ItemType Directory -Force -Path $claudeHooks | Out-Null
    Copy-Item $card $cardTarget -Force

    # Exec form, not a shell string. A single shell string is a parse error
    # under PowerShell, which Claude Code uses on Windows when Git Bash is
    # absent, and then the hook never runs at all. Re-running the installer
    # replaces the entry rather than stacking a second copy.
    & $python -c $hookEdit $claudeSettings add $python $cardTarget
    if ($LASTEXITCODE -ne 0) { throw "could not register the reading card hook in $claudeSettings" }

    "reading card installed to $cardTarget and registered in $claudeSettings"
    'Paste a packed image into any Claude Code session and it is read as your prompt.'
}
