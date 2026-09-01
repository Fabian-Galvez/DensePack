# Pack whatever text is on the clipboard into an image and put that image back on
# the clipboard, so the next paste drops the image in place of the text.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File densepack-clip.ps1
#
# -Size sets the font in pixels. 10 is the default, because an image you paste
# can land in front of Opus 5 or Fable 5, and 10 px is the smallest size both
# read with every answer exact. The three measured floors are 8 px for Fable 5,
# 10 px for Opus 5 and 12 px for Sonnet 5. 9 px is read exactly by none of
# them: Opus scored 6 of 10 there.

param(
    [int]$Size = 10,
    [switch]$Quiet
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

$text = Get-ClipText
if (-not $text -or -not $text.Trim()) {
    if (-not $Quiet) { [System.Windows.Forms.MessageBox]::Show("No text on the clipboard.", "DensePack") | Out-Null }
    exit 1
}

# Never call bare "python": from AutoHotkey's environment that name can resolve to
# the Windows Store alias stub, which opens the Microsoft Store instead of running.
function Resolve-Python {
    $candidates = @(Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
    $candidates += "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
    foreach ($c in $candidates) {
        if ($c -and $c -notmatch 'WindowsApps' -and (Test-Path $c)) { return $c }
    }
    if (Test-Path "$env:WINDIR\py.exe") { return "$env:WINDIR\py.exe" }
    return $null
}

$python = Resolve-Python
if (-not $python) {
    if (-not $Quiet) { [System.Windows.Forms.MessageBox]::Show("No real Python found. Install Python, then retry.", "DensePack") | Out-Null }
    exit 1
}

$packer = Join-Path $PSScriptRoot 'densepack.py'
$work = Join-Path $env:TEMP ("densepack-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $work | Out-Null
$src = Join-Path $work 'in.txt'
Set-Content -Path $src -Value $text -Encoding utf8

Push-Location $work
$ErrorActionPreference = 'Continue'
$out = & $python $packer $src --size $Size --out packed --quiet
$code = $LASTEXITCODE
Pop-Location

if ($code -ne 0 -or -not $out) {
    if (-not $Quiet) { [System.Windows.Forms.MessageBox]::Show("Packing failed.", "DensePack") | Out-Null }
    exit 1
}

$images = @($out | Where-Object { $_ -match '\.png$' } | ForEach-Object { Join-Path $work $_ })

if ($images.Count -gt 1 -and -not $Quiet) {
    [System.Windows.Forms.MessageBox]::Show(
        "That text needed $($images.Count) images. Only the first is on the clipboard. The rest are in:`n$work",
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
    # stops matching it. It divided by 4 until 31 August 2026.
    $txtTokens = [math]::Round($chars / 2.40)
    Write-Output "$chars chars, $txtTokens tokens as text, $imgTokens tokens as image"
}
