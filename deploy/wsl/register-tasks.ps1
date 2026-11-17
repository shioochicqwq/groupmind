# Register the three logon tasks on the Windows PC. Run as the user who logs on to the desktop (QQ runs in that session).
#   QQBot-SnowLuma      SnowLuma (OneBot bridge for the logged-in QQ client)
#   QQBotWsl-keepalive  keeps the WSL distro from shutting down when idle
#   QQBot-bothost       bothost inside WSL; restarted every minute if it exits
param([string]$SnowLuma = 'D:\qqbot-bothost\snowluma', [string]$Logs = 'D:\qqbot-bothost\logs', [string]$Distro = 'qqbot')
[Console]::OutputEncoding = [Text.Encoding]::UTF8
New-Item -ItemType Directory -Force $Logs | Out-Null

function Register($name, $command, [switch]$Elevated, [switch]$Restart) {
    $a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -Command `"$command`""
    $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $p = if ($Elevated) { New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest }
         else { New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive }
    $opts = @{ ExecutionTimeLimit = [TimeSpan]::Zero; AllowStartIfOnBatteries = $true; DontStopIfGoingOnBatteries = $true }
    if ($Restart) { $opts.RestartCount = 999; $opts.RestartInterval = New-TimeSpan -Minutes 1 }
    $s = New-ScheduledTaskSettingsSet @opts
    Register-ScheduledTask -TaskName $name -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null
    Start-ScheduledTask -TaskName $name
    "$name : " + (Get-ScheduledTask -TaskName $name).State
}

Register 'QQBot-SnowLuma' "Set-Location $SnowLuma; `$env:SNOWLUMA_TELEMETRY='0'; .\node.exe .\index.mjs *>> $Logs\snowluma.log" -Elevated
Register 'QQBotWsl-keepalive' "wsl.exe -d $Distro -u root -- sleep infinity"
Register 'QQBot-bothost' "wsl.exe -d $Distro -u bot -- /home/bot/qqbot/run.sh" -Restart
