$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = $null
$candidates = @(@('py','-3.13'), @('py','-3.12'), @('py','-3'), @('python'), @('python3'))
foreach ($candidate in $candidates) {
    if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
    $arguments = @($candidate | Select-Object -Skip 1)
    try {
        $found = & $candidate[0] @arguments -c 'import sys; assert sys.version_info >= (3,10); print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { $pythonExe = [string]($found | Select-Object -Last 1); break }
    } catch { }
}
if (-not $pythonExe) { throw 'Python 3.10 or newer is required. Install Python from python.org (include pip and Tcl/Tk), then run setup again.' }
& $pythonExe (Join-Path $PSScriptRoot 'install.py')
if ($LASTEXITCODE -ne 0) { throw 'Installer did not finish successfully.' }
