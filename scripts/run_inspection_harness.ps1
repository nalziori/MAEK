param(
    [switch]$Record,
    [string]$Unity = 'D:/obsd/Unity/Editors/6000.3.12f1/Editor/Unity.exe'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$unityProject = Join-Path $projectRoot 'unity/MAEKInspection'
$output = Join-Path $projectRoot 'visualization/inspection_demo'
if (!(Test-Path -LiteralPath $Unity)) { throw 'Pass the installed Unity 6000.3 editor with -Unity.' }
$openEditors = Get-CimInstance Win32_Process -Filter "Name='Unity.exe'" | Where-Object { $_.CommandLine -like '*MAEKInspection*' }
if ($openEditors) { throw 'Close the MAEK Unity project before the batch harness. No editor was terminated.' }
New-Item -ItemType Directory -Force -Path $output | Out-Null
Push-Location $projectRoot
try {
    & $python -m pytest tests/test_inspection_bridge.py tests/test_inspection_dashboard.py tests/test_inspection_scenarios.py tests/test_inspection_harness.py tests/test_inspection_access.py tests/test_worker_safety_context.py tests/test_supplementary_circuits.py -q
    if ($LASTEXITCODE -ne 0) { throw 'RGB contract tests failed.' }
    & (Join-Path $PSScriptRoot 'start_inspection_bridge.ps1')
    function Invoke-DemoUnity([string]$method,[string]$logName) {
        $arguments = @('-batchmode','-projectPath',('"'+$unityProject+'"'),'-executeMethod',$method,'-logFile',('"'+(Join-Path $output $logName)+'"'))
        $process = Start-Process -FilePath $Unity -ArgumentList $arguments -WindowStyle Hidden -PassThru
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw "Unity failed: $method; inspect $logName" }
    }
    Invoke-DemoUnity 'MAEK.Editor.BuildInspectionTour.Run' 'unity_build.log'
    $sitePlan = Join-Path $unityProject 'Assets/MAEK/Source/site_inspection_tour.json'
    if (!(Test-Path -LiteralPath $sitePlan)) { throw 'Build did not generate site_inspection_tour.json.' }
    & $python scripts/check_inspection_harness.py
    if ($LASTEXITCODE -ne 0) { throw 'Site-first access plan or frozen legacy contract failed.' }
    Invoke-DemoUnity 'MAEK.Editor.BuildInspectionTour.Verify' 'unity_verify.log'
    Invoke-DemoUnity 'MAEK.Editor.VerifyInspectionPlayMode.Run' 'unity_play.log'
    Invoke-DemoUnity 'MAEK.Editor.VerifyInspectionScenarios.Run' 'unity_scenarios.log'
    & $python scripts/check_inspection_harness.py --seal
    if ($LASTEXITCODE -ne 0) { throw 'Evidence sealing failed.' }
    if ($Record) {
        Invoke-DemoUnity 'MAEK.Editor.BuildInspectionTour.RecordDemo' 'unity_record.log'
        $session = (Get-Content -LiteralPath (Join-Path $output 'latest_recording.txt') -Raw).Trim()
        $video = Join-Path $session 'MAEK_inspection_demo.mp4'
        & $python scripts/encode_inspection_video.py (Join-Path $session 'video') --output $video
        if ($LASTEXITCODE -ne 0) { throw 'Video encoding/decoding failed.' }
    }
    & $python scripts/check_inspection_harness.py --evidence
    if ($LASTEXITCODE -ne 0) { throw 'Evidence drift check failed.' }
    Write-Output 'MAEK inspection harness PASS. This validates integration, not field defect accuracy.'
} finally { Pop-Location }
