# Install Python on Windows when the machine has none, so the plugin's hooks
# can run. SessionStart only.
#
# Every other script in this folder is Python, so none of them can fix a
# machine with no Python: the hook would never start. PowerShell ships with
# every Windows, so this one runs where they cannot.
#
# It writes nothing, changes no setting and blocks nothing. On a machine that
# already has Python it prints nothing at all and exits.
#
# Claude Code reads a hook's stdout as JSON, so the only output here is one
# JSON object carrying systemMessage, the field Claude Code shows the user.

$ErrorActionPreference = 'SilentlyContinue'

# The bare name "python" can resolve to the Windows Store alias stub, whose
# only behavior is to open the Microsoft Store, so a path under WindowsApps is
# never accepted as an interpreter.
#
# The folders are the ones run_hook.ps1 searches: quotes trimmed, absolute
# paths only, so this answer and the hooks agree. Every candidate gets a test
# run: the Store stub, a py launcher with no Python behind it, and a Python
# older than 3.10 (Pillow 12 has no wheel for it) all count as none.
function Test-Python($c) {
    # The version it prints, not the exit code. A .bat or .cmd that ignores
    # its arguments and exits 0 would otherwise pass as an interpreter, and
    # every hook would then start it and do nothing.
    # Bounded: one candidate that never returns would hold session start
    # until the hook timeout, so a probe that outlives 10 seconds is killed
    # and counts as no Python.
    $si = New-Object Diagnostics.ProcessStartInfo
    $si.FileName = $c
    $si.Arguments = '-c "import sys; print(''DENSEPACKPY'', sys.version_info[0], sys.version_info[1])"'
    $si.UseShellExecute = $false
    $si.RedirectStandardOutput = $true
    $si.RedirectStandardError = $true
    $si.CreateNoWindow = $true
    $si.WorkingDirectory = (Split-Path -LiteralPath $c)
    try { $p = [Diagnostics.Process]::Start($si) } catch { return $false }
    # BOTH streams are drained. A Python that writes to stderr at startup
    # fills the pipe and blocks until the kill below, and a working Python
    # would then count as none.
    $read = $p.StandardOutput.ReadToEndAsync()
    $null = $p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit(10000)) {
        try { $p.Kill() } catch { }
        return $false
    }
    $out = ($read.Result -split "`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
    if ("$out".Trim() -match '^DENSEPACKPY (\d+) (\d+)$') {
        return ([int]$Matches[1] -gt 3) -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10)
    }
    return $false
}

function Find-Python {
    $dirs = @($env:PATH -split ';' | ForEach-Object { $_.Trim('"') } |
              Where-Object { $_ -match '^([A-Za-z]:[\\/]|\\\\)' })
    # The same order run_hook.ps1 searches in.
    # Plain folders first, WindowsApps last, exactly as run_hook.ps1 does.
    foreach ($pass in @('plain', 'store')) {
        foreach ($name in @('python3', 'python', 'py')) {
            foreach ($dir in $dirs) {
                if (($pass -eq 'store') -ne ($dir -match 'WindowsApps')) { continue }
                # A pyenv-win shim is python.bat. Save-PythonPath stores the
                # real python.exe behind it, and run_hook.ps1 starts that.
                foreach ($ext in @('.exe', '.bat', '.cmd')) {
                    $c = Join-Path $dir "$name$ext"
                    if ((Test-Path -LiteralPath $c) -and (Test-Python $c)) { return $c }
                }
            }
        }
    }
    foreach ($found in @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Filter 'python.exe' `
                          -Recurse -Depth 1 -ErrorAction SilentlyContinue)) {
        if (Test-Python $found.FullName) { return $found.FullName }
    }
    return $null
}

function Say($text) {
    $payload = @{ systemMessage = $text } | ConvertTo-Json -Compress
    [Console]::Out.Write($payload)
}

# The chosen Python, saved under the home folder where a project cannot
# write. run_hook.ps1 starts the Windows form first and run_hook.sh the Git
# Bash form, so an old Python earlier on PATH never runs a hook.
function Save-PythonPath($p) {
    # A virtual environment's Python is not saved: every later hook would
    # start it after that environment has left PATH.
    # True, not false: this Python works and the hooks find it on PATH. Only
    # the saved path is declined, so the caller must not report no Python.
    & $p -c "import sys; sys.exit(sys.prefix != sys.base_prefix)" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { return $true }
    # The interpreter's own path, not the launcher's: py.exe and a pyenv-win
    # shim choose their Python from the project folder.
    $real = (& $p -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
    if ($real) { $p = "$real".Trim() }
    # run_hook.ps1 starts this path itself, and it starts an exe. A shim that
    # names no exe is not saved, so the hooks search PATH again instead.
    if ($p -notmatch '\.exe$') { return $false }
    # USERPROFILE is what run_hook.ps1 reads; HOME is what Git Bash reads.
    $homes = @($env:USERPROFILE)
    if ($env:HOME -and $env:HOME -match '^[A-Za-z]:[\\/]' -and $env:HOME -ne $env:USERPROFILE) { $homes += $env:HOME }
    foreach ($h in $homes) {
        if (-not $h) { continue }
        try {
            $dir = Join-Path $h '.claude\densepack-state'
            $null = New-Item -ItemType Directory -Force -Path $dir
            # Written to a file of its own, then moved into place, so a hook
            # never reads a half-written path.
            $winfile = Join-Path $dir 'python-path-win'
            [IO.File]::WriteAllText("$winfile.$PID", $p + "`n")
            Move-Item -LiteralPath "$winfile.$PID" -Destination $winfile -Force
            $shfile = Join-Path $dir 'python-path'
            if ($p -match '^([A-Za-z]):[\\/](.*)$') {
                $sh = '/' + $Matches[1].ToLower() + '/' + ($Matches[2] -replace '\\', '/')
                [IO.File]::WriteAllText("$shfile.$PID", $sh + "`n")
                Move-Item -LiteralPath "$shfile.$PID" -Destination $shfile -Force
            } else {
                # A network path has no Git Bash form; an older one must not stay.
                Remove-Item -LiteralPath $shfile -ErrorAction SilentlyContinue
            }
        } catch { }
    }
    return $true
}

# A save that did not happen falls through to the message below, so a machine
# whose only candidate names no exe hears why its hooks are quiet.
$py = Find-Python
if ($py -and (Save-PythonPath $py)) { exit 0 }

# One attempt per machine. winget takes about a minute, and repeating it at
# every session start on a machine where it cannot succeed would delay every
# session for no gain. Delete this file to let it try again.
$data = $env:CLAUDE_PLUGIN_DATA
if (-not $data) { $data = Join-Path $env:LOCALAPPDATA 'densepack' }
$null = New-Item -ItemType Directory -Force -Path $data
$tried = Join-Path $data 'python-install-tried'
if (Test-Path $tried) {
    Say ("DensePack found no Python 3.10 or newer, so none of its hooks run and reports " +
         "arrive as plain text. It already tried to install Python once on " +
         "this machine. Install Python 3.10 or newer, then restart Claude Code.")
    exit 0
}
Set-Content -Path $tried -Value 'tried' -Encoding utf8

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Say ("DensePack needs Python 3.10 or newer and this machine has none, so " +
         "none of its hooks run and reports arrive as plain text. winget is " +
         "not here either. Install Python from python.org, then restart " +
         "Claude Code.")
    exit 0
}

winget install --id Python.Python.3.13 -e --source winget --scope user `
    --accept-package-agreements --accept-source-agreements 2>$null | Out-Null

$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
            [Environment]::GetEnvironmentVariable('Path', 'User')

$py = Find-Python
if ($py) {
    Save-PythonPath $py
    # This session's other hooks already started without an interpreter, so
    # they cannot be rescued now. The next session picks the new Python up.
    Say ("DensePack installed Python 3.13, which its hooks need. Restart " +
         "Claude Code and packing starts working. Nothing was packed this " +
         "session.")
} else {
    Say ("DensePack tried to install Python 3.13 and it did not appear, so " +
         "none of its hooks run and reports arrive as plain text. Install " +
         "Python 3.10 or newer, then restart Claude Code.")
}
exit 0
