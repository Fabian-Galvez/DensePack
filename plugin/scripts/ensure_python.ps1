# Installs Python on Windows when the machine has none. The plugin hooks need
# Python to run. SessionStart only.
#
# Each other script in this folder is Python. On a machine with no Python,
# none of them can fix it, because the hook never starts. PowerShell ships
# with each Windows, and this script runs where they cannot.
#
# It writes only the saved Python path and one marker file, changes no
# setting and blocks nothing. On a machine that already has Python, it prints
# nothing and exits.
#
# Claude Code reads the stdout of a hook as JSON. The only output here is one
# JSON object with systemMessage, the field that Claude Code shows on screen.

$ErrorActionPreference = 'SilentlyContinue'

# The bare name "python" can resolve to the Windows Store alias stub, which
# only opens the Microsoft Store. The script accepts a path under WindowsApps
# only when the test run below passes.
#
# The folders are the ones that run_hook.ps1 searches, with quotes trimmed
# and absolute paths only. This script then finds the Python that the hooks
# find. Each candidate gets a test run. The Store stub, a py launcher with no
# Python behind it, and a Python older than 3.10 (Pillow 12 has no wheel for
# it) all count as none.
function Test-Python($c) {
    # The test reads the version that it prints, not the exit code.
    # Otherwise, a .bat or .cmd that ignores its arguments and exits 0 passes
    # as an interpreter, and each hook then starts it and does nothing.
    # The probe has a time limit. One candidate that never returns holds
    # session start until the hook timeout. The script kills a probe after 10
    # seconds, and that candidate counts as no Python.
    $si = New-Object Diagnostics.ProcessStartInfo
    $si.FileName = $c
    $si.Arguments = '-c "import sys; print(''DENSEPACKPY'', sys.version_info[0], sys.version_info[1])"'
    $si.UseShellExecute = $false
    $si.RedirectStandardOutput = $true
    $si.RedirectStandardError = $true
    $si.CreateNoWindow = $true
    $si.WorkingDirectory = (Split-Path -LiteralPath $c)
    try { $p = [Diagnostics.Process]::Start($si) } catch { return $false }
    # The script drains BOTH streams. Otherwise, a Python that writes to
    # stderr at startup fills the pipe and blocks until the kill below, and a
    # working Python then counts as none.
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
    # The same order as the run_hook.ps1 search, with plain folders first
    # and WindowsApps last.
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

# Save the chosen Python under the home folder, where a project cannot
# write. run_hook.ps1 starts the Windows form first, and run_hook.sh starts
# the Git Bash form first. An old Python earlier on PATH never runs a hook.
function Save-PythonPath($p) {
    # The function does not save the Python of a virtual environment. A saved
    # one starts in each later hook, also after that environment leaves PATH.
    # The function returns true, not false. This Python works, and the hooks
    # find it on PATH. Only the save is skipped, and the caller must not
    # report that there is no Python.
    & $p -c "import sys; sys.exit(sys.prefix != sys.base_prefix)" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { return $true }
    # The path of the interpreter, not of the launcher. py.exe and a
    # pyenv-win shim choose their Python from the project folder.
    $real = (& $p -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
    if ($real) { $p = "$real".Trim() }
    # run_hook.ps1 starts this path directly, and it starts an exe. The
    # function does not save a shim that names no exe. The hooks then search
    # PATH again.
    if ($p -notmatch '\.exe$') { return $false }
    # run_hook.ps1 reads USERPROFILE. Git Bash reads HOME.
    $homes = @($env:USERPROFILE)
    if ($env:HOME -and $env:HOME -match '^[A-Za-z]:[\\/]' -and $env:HOME -ne $env:USERPROFILE) { $homes += $env:HOME }
    foreach ($h in $homes) {
        if (-not $h) { continue }
        try {
            $dir = Join-Path $h '.claude\densepack-state'
            $null = New-Item -ItemType Directory -Force -Path $dir
            # The path goes to a file of its own and then moves into place.
            # A hook never reads a half-written path.
            $winfile = Join-Path $dir 'python-path-win'
            [IO.File]::WriteAllText("$winfile.$PID", $p + "`n")
            Move-Item -LiteralPath "$winfile.$PID" -Destination $winfile -Force
            $shfile = Join-Path $dir 'python-path'
            if ($p -match '^([A-Za-z]):[\\/](.*)$') {
                $sh = '/' + $Matches[1].ToLower() + '/' + ($Matches[2] -replace '\\', '/')
                [IO.File]::WriteAllText("$shfile.$PID", $sh + "`n")
                Move-Item -LiteralPath "$shfile.$PID" -Destination $shfile -Force
            } else {
                # A network path has no Git Bash form. An older saved path must
                # not stay.
                Remove-Item -LiteralPath $shfile -ErrorAction SilentlyContinue
            }
        } catch { }
    }
    return $true
}

# When the save fails, the script continues to the message below. A machine
# whose only candidate names no exe then gets the reason why its hooks do
# nothing.
$py = Find-Python
if ($py -and (Save-PythonPath $py)) { exit 0 }

# One attempt per machine. winget takes about a minute. On a machine where it
# cannot succeed, a repeat at each session start delays each session for no
# gain. Delete this file to let it try again.
$data = $env:CLAUDE_PLUGIN_DATA
if (-not $data) { $data = Join-Path $env:LOCALAPPDATA 'densepack' }
$null = New-Item -ItemType Directory -Force -Path $data
$tried = Join-Path $data 'python-install-tried'
if (Test-Path $tried) {
    Say ("DensePack found no Python 3.10 or newer. None of its hooks run, and reports " +
         "arrive as plain text. It already tried to install Python once on " +
         "this computer. Install Python 3.10 or newer, then restart Claude Code.")
    exit 0
}
Set-Content -Path $tried -Value 'tried' -Encoding utf8

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Say ("DensePack needs Python 3.10 or newer, and this computer has none. " +
         "None of its hooks run, and reports arrive as plain text. winget is " +
         "not installed either. Install Python from python.org, then restart " +
         "Claude Code.")
    exit 0
}

winget install --id Python.Python.3.13 -e --source winget --scope user `
    --accept-package-agreements --accept-source-agreements 2>$null | Out-Null

$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
            [Environment]::GetEnvironmentVariable('Path', 'User')

$py = Find-Python
if ($py) {
    # The function returns true or false. Without $null =, that value prints
    # before the JSON, and Claude Code cannot parse the message.
    $null = Save-PythonPath $py
    # The other hooks of this session already started without an interpreter.
    # They cannot run again now. The next session uses the new Python.
    Say ("DensePack installed Python 3.13, which its hooks need. Restart " +
         "Claude Code, and packing starts. DensePack packed nothing in this " +
         "session.")
} else {
    Say ("DensePack tried to install Python 3.13, and it did not appear. " +
         "None of its hooks run, and reports arrive as plain text. Install " +
         "Python 3.10 or newer, then restart Claude Code.")
}
exit 0
