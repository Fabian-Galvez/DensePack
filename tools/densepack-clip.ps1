# Pack whatever text is on the clipboard into an image and put that image back on
# the clipboard, so the next paste puts the image in place of the text.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File densepack-clip.ps1
#
# -Size N sets the glyph size in px for one run. Without it the packer draws
# the plugin's one page: common.CODE_PX, 17 px unless DENSEPACK_CODE_PX names
# another number.
#
# -Vault NAME saves the text and every image in a new folder under
# tools\NAME. The folder name is the first three words of the text.
# DensePack.ahk passes ctrl-shift-vault for the hotkeys and
# ctrl-right_click-vault for the menu. Without -Vault the files go to a
# folder under %TEMP%.
#
# -SetImage PATH puts that one image on the clipboard and does nothing else.
# DensePack.ahk uses it to paste image 2 and every image after it.

param(
    [int]$Size = 0,
    [switch]$Quiet,
    [ValidatePattern('^[A-Za-z0-9_\-]*$')][string]$Vault = '',
    [string]$SetImage = ''
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Get-ClipText {
    $text = $null
    # The clipboard is single threaded apartment only, so it is read on an STA thread.
    $runspace = [runspacefactory]::CreateRunspace()
    $runspace.ApartmentState = 'STA'
    $runspace.ThreadOptions = 'ReuseThread'
    $runspace.Open()
    $ps = [powershell]::Create()
    $ps.Runspace = $runspace
    [void]$ps.AddScript({
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.Clipboard]::GetText()
    })
    $text = $ps.Invoke()
    $ps.Dispose()
    $runspace.Close()
    if ($text) { return ($text -join "`n") }
    return $null
}

function Set-ClipImage($path) {
    $runspace = [runspacefactory]::CreateRunspace()
    $runspace.ApartmentState = 'STA'
    $runspace.ThreadOptions = 'ReuseThread'
    $runspace.Open()
    $ps = [powershell]::Create()
    $ps.Runspace = $runspace
    [void]$ps.AddScript({
        param($p)
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $img = [System.Drawing.Image]::FromFile($p)
        $bmp = New-Object System.Drawing.Bitmap $img
        $img.Dispose()
        [System.Windows.Forms.Clipboard]::SetImage($bmp)
        $bmp.Dispose()
    }).AddArgument($path)
    [void]$ps.Invoke()
    $ps.Dispose()
    $runspace.Close()
}

if ($SetImage) {
    if (-not (Test-Path -LiteralPath $SetImage)) { exit 1 }
    Set-ClipImage $SetImage
    exit 0
}

# The folder name for one pack: the first three words of the text, with only
# letters, digits and hyphens, and 40 characters at most.
function Get-PackName($text) {
    $words = @($text -split '\s+' | Where-Object { $_ } | Select-Object -First 3)
    $name = (($words -join '-') -replace '[^\p{L}\p{Nd}\-]', '').Trim('-')
    if ($name.Length -gt 40) { $name = $name.Substring(0, 40).Trim('-') }
    # Windows refuses these names for a folder.
    if (-not $name -or $name -match '^(con|prn|aux|nul|com\d|lpt\d)$') { $name = "text-$name".Trim('-') }
    return $name
}

# tools\<vault>. When the tools folder is read-only, the vault is under
# %LOCALAPPDATA%\DensePack.
function Get-VaultRoot($vault) {
    $root = Join-Path $PSScriptRoot $vault
    try {
        New-Item -ItemType Directory -Path $root -Force -ErrorAction Stop | Out-Null
        return $root
    } catch {
        $root = Join-Path (Join-Path $env:LOCALAPPDATA 'DensePack') $vault
        New-Item -ItemType Directory -Path $root -Force | Out-Null
        return $root
    }
}

$text = Get-ClipText
if (-not $text -or -not $text.Trim()) {
    if (-not $Quiet) { [System.Windows.Forms.MessageBox]::Show("No text on the clipboard.", "DensePack") | Out-Null }
    exit 1
}

# Never call bare "python": from AutoHotkey's environment that name can resolve to
# the Windows Store alias stub, which opens the Microsoft Store instead of running.
# A candidate has to print its own version, so a python.bat that ignores its
# arguments and exits 0 never becomes the interpreter.
function Test-RealPython($c) {
    if ($c -notmatch '\.exe$') { return $false }
    $out = (& $c -c "import sys; print('DENSEPACKPY', sys.version_info[0], sys.version_info[1])" 2>$null |
            Select-Object -Last 1)
    if ("$out" -match '^DENSEPACKPY (\d+) (\d+)$') {
        return ([int]$Matches[1] -gt 3) -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10)
    }
    return $false
}

function Resolve-Python {
    # python3 and py as well, the same list the installer searches: a machine
    # the installer accepted must not be told here that it has no Python.
    $candidates = @(Get-Command python, python3, py -All -ErrorAction SilentlyContinue |
                    ForEach-Object { $_.Source })
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
    foreach ($c in $candidates) {
        if ($c -and $c -notmatch 'WindowsApps' -and (Test-Path $c) -and (Test-RealPython $c)) { return $c }
    }
    if ((Test-Path "$env:WINDIR\py.exe") -and (Test-RealPython "$env:WINDIR\py.exe")) { return "$env:WINDIR\py.exe" }
    return $null
}

$python = Resolve-Python
if (-not $python) {
    if (-not $Quiet) { [System.Windows.Forms.MessageBox]::Show("No real Python found. Install Python, then retry.", "DensePack") | Out-Null }
    exit 1
}

$packer = Join-Path $PSScriptRoot 'densepack.py'
if ($Vault) {
    $root = Get-VaultRoot $Vault
    $name = Get-PackName $text
    $work = Join-Path $root $name
    $n = 2
    while (Test-Path -LiteralPath $work) { $work = Join-Path $root "$name-$n"; $n++ }
} else {
    $work = Join-Path $env:TEMP ("densepack-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
}
New-Item -ItemType Directory -Path $work | Out-Null
$src = Join-Path $work 'text.txt'
# UTF-8 with no byte order mark. PowerShell 5.1's Set-Content -Encoding utf8 writes one.
[System.IO.File]::WriteAllText($src, $text, (New-Object System.Text.UTF8Encoding $false))

Push-Location $work
$ErrorActionPreference = 'Continue'
$sizeArgs = @()
if ($Size -gt 0) { $sizeArgs = @('--size', $Size) }
$out = & $python $packer $src @sizeArgs --out image --quiet
$code = $LASTEXITCODE
Pop-Location

if ($code -ne 0 -or -not $out) {
    if (-not $Quiet) { [System.Windows.Forms.MessageBox]::Show("Packing failed.", "DensePack") | Out-Null }
    exit 1
}

$images = @($out | Where-Object { $_ -match '\.png$' } | ForEach-Object { Join-Path $work $_ })

# DensePack.ahk reads this file to find the folder and every image of this
# pack. Line 1 is the folder. Each later line is one image, in order.
$state = Join-Path $env:LOCALAPPDATA 'DensePack'
New-Item -ItemType Directory -Path $state -Force | Out-Null
[System.IO.File]::WriteAllLines((Join-Path $state 'last-pack.txt'), [string[]](@($work) + $images),
                                (New-Object System.Text.UTF8Encoding $false))

if ($images.Count -gt 1 -and -not $Quiet) {
    [System.Windows.Forms.MessageBox]::Show(
        "That text needed $($images.Count) images. Image 1 is on the clipboard. The text and every image are in:`n$work",
        "DensePack") | Out-Null
}

Set-ClipImage $images[0]

if (-not $Quiet) {
    $chars = $text.Length
    $img = [System.Drawing.Image]::FromFile($images[0])
    # The real charge: one token per 28 by 28 patch, partial patches rounded up.
    $imgTokens = [math]::Ceiling($img.Width / 28) * [math]::Ceiling($img.Height / 28)
    $img.Dispose()
    # Characters per token. PowerShell cannot import the Python constant, so
    # this line carries the number. plugin/scripts/densepack.py holds
    # CHARS_PER_TOKEN, and tests/test_divisor_agreement.py fails if this copy
    # stops matching it.
    $txtTokens = [math]::Round($chars / 2.40)
    Write-Output "$chars chars, $txtTokens tokens as text, $imgTokens tokens as image"
}
