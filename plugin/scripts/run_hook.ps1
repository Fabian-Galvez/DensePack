# Start one DensePack hook script with the first working Python on Windows,
# when Claude Code runs hooks through PowerShell because Git Bash is not
# installed. run_hook.sh does the same job when a hook runs through sh.
#
# Each hooks.json line is "exec sh run_hook.sh ... ; powershell -File
# run_hook.ps1 ...". sh replaces itself at exec and never reaches this file.
# PowerShell has no exec command, skips that word, and runs this file.
#
# The search treats two kinds of PATH entry as unsafe. A relative entry
# resolves inside the project folder. A cloned repository can put its own
# python there. The WindowsApps folder holds python.exe and python3.exe
# stubs that run no script. Those entries count only after a test run
# succeeds. With no Python, this script exits 0 and prints nothing.
# ensure_python.ps1 tells you what to install.

$ErrorActionPreference = 'SilentlyContinue'
# A full path starts with a drive such as C:\ or with \\ for a network share.
# The test is a plain text match, not a .NET call. A locked-down PowerShell
# still runs it.
# The Python that ensure_python.ps1 chose at session start, the first Python
# 3.10 or newer on this PATH. The file is under the home folder, where a
# project cannot write. With a stale entry, the search below runs.
if ($env:USERPROFILE) {
    $cache = Join-Path $env:USERPROFILE '.claude\densepack-state\python-path-win'
    if (Test-Path -LiteralPath $cache) {
        $cached = ([IO.File]::ReadAllText($cache)).Trim()
        # A regular file with bytes in it. For a 0-byte stub or a folder, the
        # search below runs.
        if ($cached -match '^[A-Za-z]:[\\/]' -and (Test-Path -LiteralPath $cached -PathType Leaf) -and
                ((Get-Item -LiteralPath $cached).Length -gt 0)) {
            & $cached @args
            exit $LASTEXITCODE
        }
    }
}
# Windows allows a PATH entry in double quotes. The script removes the quotes
# first.
$dirs = @($env:PATH -split ';' | ForEach-Object { $_.Trim('"') } | Where-Object { $_ -match '^([A-Za-z]:[\\/]|\\\\)' })
foreach ($pass in @('plain', 'store')) {
    foreach ($name in @('python3', 'python', 'py')) {
        foreach ($dir in $dirs) {
            $isStore = $dir -match 'WindowsApps'
            if (($pass -eq 'store') -ne $isStore) { continue }
            $candidate = Join-Path $dir "$name.exe"
            if (-not (Test-Path -LiteralPath $candidate)) { continue }
            # Only a Python 3.10 or newer runs a hook. The Store stub fails
            # this test too. This extra start happens only when the saved path
            # above is missing or stale. The search then skips an old Python
            # first on PATH. The probe has a time limit. A candidate that
            # never returns holds this hook until its timeout. The script
            # kills a probe after 10 seconds.
            $si = New-Object Diagnostics.ProcessStartInfo
            $si.FileName = $candidate
            $si.Arguments = '-c "import sys; sys.exit(sys.version_info < (3, 10))"'
            $si.UseShellExecute = $false
            $si.RedirectStandardOutput = $true
            $si.RedirectStandardError = $true
            $si.CreateNoWindow = $true
            try { $probe = [Diagnostics.Process]::Start($si) } catch { continue }
            # The script drains BOTH streams. Without that, a Python that
            # writes at startup fills the pipe and blocks until the kill, and
            # the hook runs nothing.
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
