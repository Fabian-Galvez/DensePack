# Install all parts of the DensePack right-click tool in one run.
#
#   .\install-densepack.ps1             install all of it
#   .\install-densepack.ps1 -NoCard     skip the Claude Code reading card
#   .\install-densepack.ps1 -NoHotkey   skip AutoHotkey and the Ctrl+Shift+D hotkey
#   .\install-densepack.ps1 -Remove     remove all of it
#
# This script installs Python 3.13 and AutoHotkey v2 with winget, and Pillow,
# freetype-py and NumPy with pip, when they are missing. Python and the
# packages install for your Windows account only. AutoHotkey installs for the
# whole machine, and Windows can ask for administrator rights for that step.
#
# The script writes three things, all under your Windows account and none of
# them machine-wide:
#
#   HKCU\Software\Classes\*\shell\DensePack   the right-click entry
#   the Startup folder                        the hotkey shortcut
#   ~\.claude\hooks and ~\.claude\settings.json   the reading card
#
# -Remove removes all three.

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

# The reading card is a Claude Code hook. It goes beside the Claude Code
# settings, not in this folder. The installer adds it because the image alone
# is not enough. Without the card, the model can describe a packed image and
# not act on the text in it. You then must type an explanation each time.
$claudeHooks = Join-Path $HOME '.claude\hooks'
$cardTarget  = Join-Path $claudeHooks 'densepack_reading_card.py'
$claudeSettings = Join-Path $HOME '.claude\settings.json'

# Python registers the reading card hook in $claudeSettings. PowerShell does
# not. PowerShell 5.1's Set-Content -Encoding utf8 puts a UTF-8 BOM on the
# file. Claude Code rejects a settings file with a BOM, ignores all settings
# in it, the model included, and runs the default model. Python's json writes
# the file back exactly, adds or removes the one entry, and writes no BOM.
# argv: settings path, "add" or "remove", python path, card path.
# The snippet uses single quotes only. PowerShell strips double quotes from an
# argument that it passes to a native command, and the snippet goes as one -c
# argument.
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
    # -Remove runs before the script defines Find-Python. This function finds
    # Python itself.
    $py = @(Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source } |
            Where-Object { $_ -notmatch 'WindowsApps' })[0]
    if ($py -and (Test-Path $claudeSettings)) {
        & $py -c $hookEdit $claudeSettings remove
        'removed the reading card hook'
    } else {
        "no Python found. The installer left the reading card entry in $claudeSettings"
    }
}

if ($Remove) {
    if (Test-Path -LiteralPath $fileKey) { Remove-Item -LiteralPath $fileKey -Recurse -Force; 'removed the right-click entry' }
    if (Test-Path $link)    { Remove-Item $link -Force; 'removed the startup entry' }
    Remove-ReadingCard
    # Stop only the AutoHotkey process that runs DensePack.ahk, never your other scripts.
    Get-CimInstance Win32_Process -Filter "Name LIKE 'AutoHotkey%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*DensePack.ahk*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    # The hotkey's two small files. The vault folders stay because they contain your text.
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
# The script installs Python and Pillow. The whole install is one
# double-click, even on a machine that has neither. Without Pillow, the
# right-click entry fails on its first use, even with Python installed.
#
# The bare name "python" can resolve to the Windows Store alias stub, which
# only opens the Microsoft Store. Explorer and AutoHotkey start with their own
# PATH. For these two reasons, the script writes the full path of the real
# interpreter into the right-click entry.
# A candidate must print its own version. A python.bat that ignores its
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
    # The search includes python3 and py. Without them, a machine with only
    # py.exe gets a second Python from winget.
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

# Windows 10 1809 and all versions of Windows 11 include winget. An install in
# user scope shows no administrator prompt.
function Install-WithWinget($id, $label, $userScope) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "$label is missing and winget is not installed. Install $label, then run this installer again."
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
    # winget updates PATH for new processes only. This script reloads PATH itself.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
    $python = Find-Python
}
if (-not $python) { throw 'The Python install ran, but the installer found no python.exe. Run this installer again.' }
"using $python"

# Pillow makes the image. find_spec returns without an exception, and the exit
# code is 0 in the two cases. For that reason $ErrorActionPreference does not
# stop the script at this check.
$havePillow = & $python -c "import importlib.util,sys; sys.stdout.write('yes' if importlib.util.find_spec('PIL') else 'no')"
if ($havePillow -ne 'yes') {
    'installing Pillow'
    & $python -m pip install --quiet --user --only-binary :all: "pillow>=12" | Out-Null
    $havePillow = & $python -c "import importlib.util,sys; sys.stdout.write('yes' if importlib.util.find_spec('PIL') else 'no')"
}
if ($havePillow -ne 'yes') { throw "Pillow did not install. Run: `"$python`" -m pip install pillow" }
'Pillow ready'

# freetype-py renders the glyphs. Without it, Pillow renders them, and the
# image differs from the plugin's image.
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
# One menu item, DensePack it. It runs the packer with no size. The packer
# then makes the plugin's one page at common.CODE_PX. That size is 17 px unless
# DENSEPACK_CODE_PX names another number. The script deletes the old key
# first, which removes an older size submenu under it.
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
# AutoHotkey runs Ctrl+Shift+D. The script installs AutoHotkey too. One
# double-click installs the hotkey and the right-click entry. A failed
# AutoHotkey install does not stop the installer, because the right-click
# entry works without it. -NoHotkey skips this whole section.
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
    'skipped the hotkey because of -NoHotkey'
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
    "the hotkey runs now and starts with Windows, using $ahkExe"
    'Ctrl+Shift+D packs the selection and replaces it. Ctrl+Shift+C packs to the clipboard.'
} else {
    'The installer found no AutoHotkey and skipped the hotkey. The right-click entry still works.'
}

# ---------------------------------------------------------------- the reading card
# A UserPromptSubmit hook that tells the model, in each project, that a packed
# color coded image in the chat IS the prompt. Without it, the model can read a
# packed image as a picture to describe and not as instructions. You then must
# explain that by hand each time.
#
# The hook prints nothing in a project where the DensePack plugin runs. The
# plugin sends its own card before each message, with the same facts and more.
# Two cards on each message cost twice the tokens.
if ($NoCard) {
    'skipped the reading card because of -NoCard'
} else {
    New-Item -ItemType Directory -Force -Path $claudeHooks | Out-Null
    Copy-Item $card $cardTarget -Force

    # Exec form, not a shell string. Claude Code uses PowerShell on Windows when
    # Git Bash is absent. A single shell string gives a parse error in
    # PowerShell, and the hook then does not run. A second run of the installer
    # replaces the entry and does not add a second copy.
    & $python -c $hookEdit $claudeSettings add $python $cardTarget
    if ($LASTEXITCODE -ne 0) { throw "could not register the reading card hook in $claudeSettings" }

    "installed the reading card to $cardTarget and registered it in $claudeSettings"
    'Paste a packed image into any Claude Code session. The model reads it as your prompt.'
}
