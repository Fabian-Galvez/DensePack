# Install everything the DensePack right-click tool needs, in one run.
#
#   .\install-densepack.ps1             install all of it
#   .\install-densepack.ps1 -NoCard     skip the Claude Code reading card
#   .\install-densepack.ps1 -NoHotkey   skip AutoHotkey and the Ctrl+Shift+D hotkey
#   .\install-densepack.ps1 -Remove     take all of it back out
#
# Python 3.13, Pillow and AutoHotkey v2 are installed here when they are
# missing, using winget, so nothing has to be installed by hand first.
#
# Three things are written, all under the current user and none of them
# machine-wide, so no administrator rights are needed:
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

function Remove-ReadingCard {
    if (Test-Path $cardTarget) { Remove-Item $cardTarget -Force }
    if (-not (Test-Path $claudeSettings)) { return }
    $json = Get-Content $claudeSettings -Raw | ConvertFrom-Json
    if (-not $json.hooks -or -not $json.hooks.UserPromptSubmit) { return }
    $kept = @($json.hooks.UserPromptSubmit | Where-Object {
        ($_ | ConvertTo-Json -Depth 10) -notmatch 'densepack_reading_card'
    })
    $json.hooks.UserPromptSubmit = $kept
    $json | ConvertTo-Json -Depth 10 | Set-Content $claudeSettings -Encoding utf8
    'removed the reading card hook'
}

if ($Remove) {
    if (Test-Path -LiteralPath $fileKey) { Remove-Item -LiteralPath $fileKey -Recurse -Force; 'removed the right-click entry' }
    if (Test-Path $link)    { Remove-Item $link -Force; 'removed the startup entry' }
    Remove-ReadingCard
    Get-Process AutoHotkey* -ErrorAction SilentlyContinue | Stop-Process -Force
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
function Find-Python {
    $candidates = @(Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
    $candidates += @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Filter 'python.exe' `
                        -Recurse -Depth 1 -ErrorAction SilentlyContinue |
                     ForEach-Object { $_.FullName })
    foreach ($c in $candidates) {
        if ($c -and $c -notmatch 'WindowsApps' -and (Test-Path $c)) { return $c }
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
    & $python -m pip install --quiet --user pillow | Out-Null
    $havePillow = & $python -c "import importlib.util,sys; sys.stdout.write('yes' if importlib.util.find_spec('PIL') else 'no')"
}
if ($havePillow -ne 'yes') { throw "Pillow did not install. Run: `"$python`" -m pip install pillow" }
'Pillow ready'

# ---------------------------------------------------------------- right-click on a file
# A side menu, the shape Windows draws for View, Sort by and New. Windows draws
# one when the parent key carries an EMPTY SubCommands value and the items sit
# under a "shell" subkey below it. The parent runs nothing itself, so it has no
# command subkey. Item order follows key name, so the keys are numbered.
#
# Three sizes, one per measured reading floor. Each floor is the smallest size
# at which that model read a packed image with every answer exact, so no one
# size covers all three models:
#
#    8 px  The smallest size two cold Fable 5 readers read with every answer
#          exact. The image is smaller, so it costs fewer tokens. Opus 5 read
#          1 of 10 at this size, so it is a Fable 5 choice only.
#   10 px  Opus 5 read 10 of 10 answers exactly here, and 6 of 10 at 9 px.
#          Fable 5 reads it too, so this is the size to pick when the image
#          could land in front of either of those two.
#   12 px  Sonnet 5 read every answer exactly here on two cold readers, and
#          dropped a word at 10 px. Opus 5 and Fable 5 read 12 px more easily
#          than the sizes they were scored at, so it is the safe size for any
#          reader and the largest image of the three.
#
# 9 px and 11 px are not offered. Each sits between two floors and neither was
# read exactly by any model.
if (Test-Path -LiteralPath $fileKey) { Remove-Item -LiteralPath $fileKey -Recurse -Force }
New-Item -Path $fileKey -Force | Out-Null
Set-ItemProperty -LiteralPath $fileKey -Name 'MUIVerb' -Value 'DensePack it'
Set-ItemProperty -LiteralPath $fileKey -Name 'Icon' -Value 'imageres.dll,-72'
Set-ItemProperty -LiteralPath $fileKey -Name 'SubCommands' -Value ''

# Item order follows key name, so the keys are numbered and the sizes run
# smallest first. The last item passes --pick instead of a size, which opens
# the packer's own three-button dialog. It is the fallback for a run that named
# no size, so no image is ever drawn at a size nobody chose.
$sizes = @(
    @{ Key = '01px08'; Px = 8;  Label = 'Fable 5, 8 px, smallest image' },
    @{ Key = '02px10'; Px = 10; Label = 'Opus 5, 10 px, read by Opus 5 and Fable 5' },
    @{ Key = '03px12'; Px = 12; Label = 'Sonnet 5, 12 px, read by all three' },
    @{ Key = '04pick'; Px = 0;  Label = 'Pick a size...' }
)
foreach ($s in $sizes) {
    $item = $fileKey + '\shell\' + $s.Key
    New-Item -Path $item -Force | Out-Null
    Set-ItemProperty -LiteralPath $item -Name 'MUIVerb' -Value $s.Label
    Set-ItemProperty -LiteralPath $item -Name 'Icon' -Value 'imageres.dll,-72'
    $c = Join-Path $item 'command'
    New-Item -Path $c -Force | Out-Null
    if ($s.Px -eq 0) { $choice = '--pick' } else { $choice = '--size ' + $s.Px }
    $cmd = '"' + $python + '" "' + $packer + '" "%1" ' + $choice +
           ' --out "%1.densepack"'
    Set-ItemProperty -LiteralPath $c -Name '(Default)' -Value $cmd
}
'right-click side menu added: DensePack it, on any file, 8 px, 10 px, 12 px and Pick a size'

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

    if (Test-Path $claudeSettings) {
        $json = Get-Content $claudeSettings -Raw | ConvertFrom-Json
    } else {
        $json = [pscustomobject]@{}
    }
    if (-not $json.PSObject.Properties['hooks']) {
        $json | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]@{})
    }
    if (-not $json.hooks.PSObject.Properties['UserPromptSubmit']) {
        $json.hooks | Add-Member -NotePropertyName UserPromptSubmit -NotePropertyValue @()
    }

    # Exec form, not a shell string. A single shell string is a parse error
    # under PowerShell, which Claude Code uses on Windows when Git Bash is
    # absent, and then the hook never runs at all.
    $entry = [pscustomobject]@{
        hooks = @([pscustomobject]@{
            type = 'command'
            command = $python
            args = @($cardTarget)
        })
    }

    # Re-running the installer must not stack a second copy.
    $existing = @($json.hooks.UserPromptSubmit | Where-Object {
        ($_ | ConvertTo-Json -Depth 10) -notmatch 'densepack_reading_card'
    })
    $json.hooks.UserPromptSubmit = @($existing + $entry)
    $json | ConvertTo-Json -Depth 10 | Set-Content $claudeSettings -Encoding utf8

    "reading card installed to $cardTarget and registered in $claudeSettings"
    'Paste a packed image into any Claude Code session and it is read as your prompt.'
}
