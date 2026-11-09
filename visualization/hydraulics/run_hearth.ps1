$ErrorActionPreference = 'Stop'
$hydraulicRoot = $PSScriptRoot
$pythonExecutable = 'C:/Users/hyjuy/AppData/Local/Programs/Python/Python312/python.exe'
& $pythonExecutable (Join-Path $hydraulicRoot 'couple_hearth.py')
if ($LASTEXITCODE -ne 0) { throw 'Hearth preparation failed' }
$runPlan = Get-Content -LiteralPath (Join-Path $hydraulicRoot 'hearth_run_plan.json') -Raw | ConvertFrom-Json
foreach ($case in $runPlan.cases) {
    $windowsCase = $case.path.Replace('\','/')
    $linuxCase = (& wsl -d Ubuntu -- wslpath -a $windowsCase).Trim()
    if ($LASTEXITCODE -ne 0 -or $linuxCase.Contains("'")) { throw 'Invalid WSL case path' }
    $solverLog = Join-Path $case.path 'log.foamRun'
    $finished = (Test-Path -LiteralPath $solverLog) -and ((Get-Content -LiteralPath $solverLog -Tail 3) -contains 'End')
    if (-not $finished) {
        $foamCommand = "export HWLOC_COMPONENTS=-gl; source /opt/openfoam14/etc/bashrc; cd '$linuxCase' && blockMesh > log.blockMesh 2>&1 && checkMesh > log.checkMesh 2>&1 && foamRun > log.foamRun 2>&1 && foamPostProcess -func writeCellCentres -time 0 > log.centres 2>&1"
        & wsl -d Ubuntu -- bash -lc $foamCommand
        if ($LASTEXITCODE -ne 0) { throw "CFD failed: $($case.id)" }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $case.path '0/C'))) {
        & wsl -d Ubuntu -- bash -lc "export HWLOC_COMPONENTS=-gl; source /opt/openfoam14/etc/bashrc; cd '$linuxCase' && foamPostProcess -func writeCellCentres -time 0 > log.centres 2>&1"
        if ($LASTEXITCODE -ne 0) { throw 'Cell-centre export failed' }
    }
}
& $pythonExecutable (Join-Path $hydraulicRoot 'couple_hearth.py') --export
if ($LASTEXITCODE -ne 0) { throw 'Hearth export validation failed' }
