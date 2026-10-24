# Start NapCat (NTQQ protocol side) on Windows.
# Mirrors D:\Apps\NapCat\启动NapCat.bat but without its interactive `pause`,
# so it can run as a background job / scheduled task.
# Usage: pwsh -File deploy/windows/start-napcat.ps1
param(
    [switch]$KillExisting
)

$ErrorActionPreference = 'Stop'

$napcat = 'D:\Apps\NapCat'
$qq = 'C:\Program Files\Tencent\QQNT\QQ.exe'
$launcher = Join-Path $napcat 'NapCatWinBootMain.exe'
$hook = Join-Path $napcat 'NapCatWinBootHook.dll'
$main = (Join-Path $napcat 'napcat.mjs').Replace('\', '/')
$load = Join-Path $napcat 'loadNapCat.js'

foreach ($p in @($qq, $launcher, $hook, (Join-Path $napcat 'napcat.mjs'))) {
    if (-not (Test-Path $p)) { throw "missing file: $p" }
}

if ($KillExisting) {
    Get-Process -Name 'QQ' -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
}

$env:NAPCAT_PATCH_PACKAGE = Join-Path $napcat 'qqnt.json'
$env:NAPCAT_LOAD_PATH = $load
$env:NAPCAT_INJECT_PATH = $hook
$env:NAPCAT_LAUNCHER_PATH = $launcher
$env:NAPCAT_MAIN_PATH = $main

# QQ's main entry is patched to import this loader, which then loads NapCat.
Set-Content -Path $load -Value "(async () => {await import(""file:///$main"")})()" -Encoding utf8NoBOM

$env:PYTHONIOENCODING = 'utf-8'
chcp 65001 > $null

# Runs in the foreground; NapCat logs (including the login QR) go to stdout.
& $launcher $qq $hook
