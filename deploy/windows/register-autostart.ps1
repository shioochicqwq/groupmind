# Register logon tasks that keep AstrBot and SnowLuma running on an always-on PC.
# Run as the Windows user that runs QQ, without elevation if QQ is not elevated:
# SnowLuma can only inject into QQ at the same user and privilege level.
#
# Usage:
#   pwsh -File deploy/windows/register-autostart.ps1
#   pwsh -File deploy/windows/register-autostart.ps1 -Unregister
param(
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'

$tasks = @{
    'qqbot-astrbot'  = Join-Path $PSScriptRoot 'start-astrbot.ps1'
    'qqbot-snowluma' = Join-Path $PSScriptRoot 'start-snowluma.ps1'
}

foreach ($name in $tasks.Keys) {
    if ($Unregister) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "unregistered: $name"
        continue
    }

    $pwsh = (Get-Command pwsh).Source
    $action = New-ScheduledTaskAction -Execute $pwsh `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$($tasks[$name])`" -KeepAlive"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host "registered: $name"
}
