$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $projectPath 'start_crm.ps1'
$taskName = '99Acres CRM'

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Days 3650)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "CRM will start automatically when $env:USERNAME logs into Windows."
Write-Host "You can still start it now with: .\start_crm.ps1"
