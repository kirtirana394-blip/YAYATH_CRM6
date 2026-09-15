$ErrorActionPreference = 'Stop'

$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$configuredPython = 'C:\Users\Kirti\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe'
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
$pythonPath = if (Test-Path $configuredPython) { $configuredPython } elseif ($pythonCommand) { $pythonCommand.Source } else { $null }

if (-not $pythonPath) {
    Write-Error 'Python was not found. Install Python 3.11+ and run this script again.'
    exit 1
}

$backupScript = Join-Path $projectPath 'backup_database.py'
$taskName = '99Acres CRM Daily Backup'
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$backupScript`"" -WorkingDirectory $projectPath
$trigger = New-ScheduledTaskTrigger -Daily -At 2:00AM
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Description 'Back up the 99Acres CRM SQLite database daily.' -Force | Out-Null

& $pythonPath $backupScript
$backupDirectory = Join-Path ([Environment]::GetFolderPath('UserProfile')) 'Documents\99Acres CRM Backups'
Write-Host "Daily backup enabled. Backups are stored in: $backupDirectory"
Write-Host 'The next automatic backup will run daily at 2:00 AM.'
