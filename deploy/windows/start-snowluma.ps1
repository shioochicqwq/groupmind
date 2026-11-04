# Start SnowLuma (QQ protocol side) on Windows.
# SnowLuma finds a running QQ.exe and injects its hook, so QQ can start before or
# after this script. Both must run as the same Windows user with the same privileges.
#
# Usage:
#   pwsh -File deploy/windows/start-snowluma.ps1
#   pwsh -File deploy/windows/start-snowluma.ps1 -SnowLumaHome D:\Apps\SnowLuma
#   pwsh -File deploy/windows/start-snowluma.ps1 -KeepAlive
param(
    [string]$SnowLumaHome = '',
    [switch]$KeepAlive
)

$ErrorActionPreference = 'Stop'

$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..')

if (-not $SnowLumaHome) {
    $envFile = Join-Path $repo '.env'
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match '^\s*SNOWLUMA_HOME\s*=' } | Select-Object -First 1
        if ($line) { $SnowLumaHome = ($line -split '=', 2)[1].Trim() }
    }
}
if (-not $SnowLumaHome) { $SnowLumaHome = 'C:\SnowLuma' }

$launcher = Join-Path $SnowLumaHome 'launcher.bat'
if (-not (Test-Path $launcher)) { throw "missing file: $launcher" }

# SnowLuma resolves config/ and its data from the working directory.
Set-Location $SnowLumaHome

chcp 65001 > $null

do {
    # launcher.bat ends with `pause`; NUL stdin lets it exit so KeepAlive can restart.
    cmd /c 'launcher.bat < NUL'
    if ($KeepAlive) {
        Write-Host "SnowLuma exited with code $LASTEXITCODE, restarting in 5s"
        Start-Sleep -Seconds 5
    }
} while ($KeepAlive)
