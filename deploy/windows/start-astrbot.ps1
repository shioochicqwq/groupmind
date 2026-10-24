# Start AstrBot on Windows from the repo root, loading .env for provider keys.
# Usage: pwsh -File deploy/windows/start-astrbot.ps1
$ErrorActionPreference = 'Stop'

$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Set-Location $repo

# Load .env (KEY=VALUE lines, # comments) into the current process environment.
$envFile = Join-Path $repo '.env'
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
            $name, $value = $line -split '=', 2
            [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), 'Process')
        }
    }
}

# Avoid GBK console encoding errors in AstrBot's startup banner/logs.
$env:PYTHONIOENCODING = 'utf-8'
chcp 65001 > $null

astrbot run
