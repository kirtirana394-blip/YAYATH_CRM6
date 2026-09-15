$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    Write-Error 'Python was not found.'
    exit 1
}
$action = New-ScheduledTaskAction -Execute $pythonCommand.Source -Argument 'sync_google_sheet.py' -WorkingDirectory $projectPath
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName '99Acres CRM Google Sheet Sync' -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Write-Host 'Google Sheet sync will run every 5 minutes.'
