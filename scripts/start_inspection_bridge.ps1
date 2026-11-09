param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Create the MAEK .venv and install requirements.txt first.' }
$health = "http://127.0.0.1:$Port/health"
$existing = $null
try { $existing = Invoke-RestMethod -Uri $health -TimeoutSec 2 } catch { }
if ($null -ne $existing) {
    if ($existing.model -ne 'maek.camera.segment.segment_rust / HSV baseline') { throw 'Port occupied by a different service.' }
    if ($existing.capabilities -contains 'dashboard_v1') {
        Write-Output "MAEK bridge already running: $health"
        exit 0
    }
    $maekPidFile = Join-Path $projectRoot 'visualization/inspection_demo/bridge.pid'
    if (!(Test-Path -LiteralPath $maekPidFile)) { throw 'An older bridge owns this port. Stop that bridge before starting the dashboard-enabled version.' }
    $maekOwnedPid = [int](Get-Content -LiteralPath $maekPidFile -Raw).Trim()
    $maekOwnedProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$maekOwnedPid"
    if (!$maekOwnedProcess -or $maekOwnedProcess.ExecutablePath -ne $python -or $maekOwnedProcess.CommandLine -notmatch '-m\s+maek\.inspection_bridge' -or $maekOwnedProcess.CommandLine -notmatch "--port\s+$Port(?:\s|$)") {
        throw 'Older bridge ownership could not be verified. No process was stopped.'
    }
    Stop-Process -Id $maekOwnedPid
    for ($maekAttempt=0; $maekAttempt -lt 20; $maekAttempt++) {
        if (!(Get-Process -Id $maekOwnedPid -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 100
    }
    Write-Output 'Restarted the project-owned older bridge to enable dashboard APIs.'
}
$output = Join-Path $projectRoot 'visualization/inspection_demo'
New-Item -ItemType Directory -Force -Path $output | Out-Null
$process = Start-Process -FilePath $python -ArgumentList @('-m','maek.inspection_bridge','--port',"$Port") -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $output 'bridge.stdout.log') -RedirectStandardError (Join-Path $output 'bridge.stderr.log')
Set-Content -LiteralPath (Join-Path $output 'bridge.pid') -Value $process.Id
for ($attempt=0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    try { $reply = Invoke-RestMethod -Uri $health -TimeoutSec 1; if ($reply.status -eq 'ok') { Write-Output "MAEK bridge ready: $health (PID $($process.Id))"; exit 0 } } catch { }
}
throw 'Bridge did not become ready. Inspect bridge.stderr.log.'
