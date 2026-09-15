$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$configuredPython = 'C:\Users\Kirti\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe'
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
$launcherCommand = Get-Command py.exe -ErrorAction SilentlyContinue
$pythonPath = if (Test-Path $configuredPython) { $configuredPython } elseif ($pythonCommand) { $pythonCommand.Source } elseif ($launcherCommand) { $launcherCommand.Source } else { $null }

if (-not $pythonPath) {
	Write-Error 'Python was not found. Install Python 3.11+ and run this script again.'
	exit 1
}

$instancePath = Join-Path $projectPath 'instance'
New-Item -ItemType Directory -Path $instancePath -Force | Out-Null
$envFile = Join-Path $projectPath '.env'
if (-not (Test-Path $envFile)) {
	$exampleFile = Join-Path $projectPath '.env.example'
	if (Test-Path $exampleFile) {
		Copy-Item $exampleFile $envFile
		Write-Warning 'Created .env from .env.example. Change ADMIN_EMAIL and ADMIN_PASSWORD before sharing the CRM.'
	} else {
		Write-Error 'Missing .env.example. Restore the project files and run this script again.'
		exit 1
	}
}

$env:FLASK_APP = 'app'
$pythonArguments = if ($pythonPath -eq $launcherCommand.Source) { @('-3', '-m', 'flask', 'init-db') } else { @('-m', 'flask', 'init-db') }
& $pythonPath @pythonArguments
if ($LASTEXITCODE -ne 0) {
	Write-Error 'Database initialization failed. Check the Python dependencies and .env settings.'
	exit 1
}

$errorLog = Join-Path $instancePath 'crm-error.log'
$outputLog = Join-Path $instancePath 'crm-output.log'
$serverArguments = if ($pythonPath -eq $launcherCommand.Source) { @('-3', 'app.py') } else { @('app.py') }
$server = Start-Process -FilePath $pythonPath -ArgumentList $serverArguments -WorkingDirectory $projectPath -WindowStyle Hidden -PassThru -RedirectStandardOutput $outputLog -RedirectStandardError $errorLog

$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
	try {
		$response = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/login' -UseBasicParsing -TimeoutSec 1
		if ($response.StatusCode -eq 200) {
			$ready = $true
			break
		}
	} catch {
		Start-Sleep -Milliseconds 250
	}
}

if (-not $ready) {
	Write-Error "CRM did not start. Check $errorLog"
	exit 1
}

$localUrl = 'http://127.0.0.1:5000/login'
$networkAddress = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*'} | Select-Object -First 1 -ExpandProperty IPAddress)
$phoneUrl = if ($networkAddress) { "http://$networkAddress`:5000/login" } else { 'unavailable' }
try {
	New-NetFirewallRule -DisplayName '99Acres CRM (TCP 5000)' -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private -ErrorAction Stop | Out-Null
} catch {
	Write-Warning 'Windows Firewall was not changed. Allow inbound TCP port 5000 on the Private network to use the CRM from another computer.'
}
Start-Process $localUrl
Write-Host "CRM started with process ID $($server.Id). Computer: $localUrl"
Write-Host "Other computer (same Wi-Fi): $phoneUrl"