# Start one DensePack hook script with the first working Python on Windows,
# when Claude Code runs hooks through PowerShell because Git Bash is not
# installed. run_hook.sh does the same job when a hook runs through sh.
#
# Each hooks.json line is "exec sh run_hook.sh ... ; powershell -File
# run_hook.ps1 ...". sh replaces itself at exec and never reaches this file.
# PowerShell has no exec command, skips that word, and runs this file.
#
# Two kinds of PATH entry are not trusted. A relative entry resolves inside
# the project folder, so a cloned repository could put its own python there.
# The WindowsApps folder holds python.exe and python3.exe stubs that run no
# script, so those entries count only after a test run succeeds. With no
# Python at all this exits 0 and prints nothing; ensure_python.ps1 tells the
# user what to install.

$ErrorActionPreference = 'SilentlyContinue'
# A full path starts with a drive such as C:\ or with \\ for a network share.
# A plain text match, not a .NET call, so a locked-down PowerShell still runs it.
# The Python ensure_python.ps1 chose at session start: the first Python 3.10
# or newer on this PATH. It sits under the home folder, where a project
# cannot write. A stale entry falls through to the search below.
if ($env:USERPROFILE) {
    $cache = Join-Path $env:USERPROFILE '.claude\densepack-state\python-path-win'
    if (Test-Path -LiteralPath $cache) {
        $cached = ([IO.File]::ReadAllText($cache)).Trim()
        # A regular file with bytes in it: a 0-byte stub or a folder falls
        # through to the search below.
        if ($cached -match '^[A-Za-z]:[\\/]' -and (Test-Path -LiteralPath $cached -PathType Leaf) -and
                ((Get-Item -LiteralPath $cached).Length -gt 0)) {
            & $cached @args
            exit $LASTEXITCODE
        }
    }
}
# Windows allows a PATH entry in double quotes, so the quotes come off first.
$dirs = @($env:PATH -split ';' | ForEach-Object { $_.Trim('"') } | Where-Object { $_ -match '^([A-Za-z]:[\\/]|\\\\)' })
foreach ($pass in @('plain', 'store')) {
    foreach ($name in @('python3', 'python', 'py')) {
        foreach ($dir in $dirs) {
            $isStore = $dir -match 'WindowsApps'
            if (($pass -eq 'store') -ne $isStore) { continue }
            $candidate = Join-Path $dir "$name.exe"
            if (-not (Test-Path -LiteralPath $candidate)) { continue }
            # Only a Python 3.10 or newer runs a hook. The Store stub fails this
            # too. This extra start happens only when the saved path above is
            # missing or stale, so an old Python first on PATH is skipped then.
            # Bounded: a candidate that never returns would hold this hook
            # until its timeout, so a probe over 10 seconds is killed.
            $si = New-Object Diagnostics.ProcessStartInfo
            $si.FileName = $candidate
            $si.Arguments = '-c "import sys; sys.exit(sys.version_info < (3, 10))"'
            $si.UseShellExecute = $false
            $si.RedirectStandardOutput = $true
            $si.RedirectStandardError = $true
            $si.CreateNoWindow = $true
            try { $probe = [Diagnostics.Process]::Start($si) } catch { continue }
            # BOTH streams are drained. A Python that writes at startup fills
            # the pipe and blocks until the kill, and the hook runs nothing.
            $null = $probe.StandardOutput.ReadToEndAsync()
            $null = $probe.StandardError.ReadToEndAsync()
            if (-not $probe.WaitForExit(10000)) {
                try { $probe.Kill() } catch { }
                continue
            }
            if ($probe.ExitCode -ne 0) { continue }
            & $candidate @args
            exit $LASTEXITCODE
        }
    }
}
exit 0
