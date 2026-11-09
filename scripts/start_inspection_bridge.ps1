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
    Write-Output "MAEK bridge already running: $health"
    exit 0
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
