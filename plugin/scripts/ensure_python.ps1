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
function Find-Python {
    foreach ($name in @('python', 'python3')) {
        foreach ($c in @(Get-Command $name -All -ErrorAction SilentlyContinue |
                         ForEach-Object { $_.Source })) {
            if ($c -and $c -notmatch 'WindowsApps' -and (Test-Path $c)) { return $c }
        }
    }
    $found = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Filter 'python.exe' `
                -Recurse -Depth 1 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.FullName }
    return $null
}

function Say($text) {
    $payload = @{ systemMessage = $text } | ConvertTo-Json -Compress
    [Console]::Out.Write($payload)
}

if (Find-Python) { exit 0 }

# One attempt per machine. winget takes about a minute, and repeating it at
# every session start on a machine where it cannot succeed would delay every
# session for no gain. Delete this file to let it try again.
$data = $env:CLAUDE_PLUGIN_DATA
if (-not $data) { $data = Join-Path $env:LOCALAPPDATA 'densepack' }
$null = New-Item -ItemType Directory -Force -Path $data
$tried = Join-Path $data 'python-install-tried'
if (Test-Path $tried) {
    Say ("DensePack found no Python, so none of its hooks run and reports " +
         "arrive as plain text. It already tried to install Python once on " +
         "this machine. Install Python 3.8 or newer, then restart Claude Code.")
    exit 0
}
Set-Content -Path $tried -Value 'tried' -Encoding utf8

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Say ("DensePack needs Python 3.8 or newer and this machine has none, so " +
         "none of its hooks run and reports arrive as plain text. winget is " +
         "not here either. Install Python from python.org, then restart " +
         "Claude Code.")
    exit 0
}

winget install --id Python.Python.3.13 -e --source winget --scope user `
    --accept-package-agreements --accept-source-agreements 2>$null | Out-Null

$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
            [Environment]::GetEnvironmentVariable('Path', 'User')

if (Find-Python) {
    # This session's other hooks already started without an interpreter, so
    # they cannot be rescued now. The next session picks the new Python up.
    Say ("DensePack installed Python 3.13, which its hooks need. Restart " +
         "Claude Code and packing starts working. Nothing was packed this " +
         "session.")
} else {
    Say ("DensePack tried to install Python 3.13 and it did not appear, so " +
         "none of its hooks run and reports arrive as plain text. Install " +
         "Python 3.8 or newer, then restart Claude Code.")
}
exit 0
