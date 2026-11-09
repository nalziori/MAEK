# Recompute existing MAEK demonstration cases; does not delete prior outputs.
$ErrorActionPreference = 'Stop'
$cfdRoot = $PSScriptRoot
$pythonPath = (Get-Command python).Source
function Run-Python([string[]]$Arguments) {
    & $pythonPath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python failed: $Arguments" }
}
Run-Python @((Join-Path $cfdRoot 'test_cfd.py'))
Run-Python @((Join-Path $cfdRoot 'reactive_shaft.py'))
Run-Python @((Join-Path $cfdRoot 'build_case.py'))
Run-Python @((Join-Path $cfdRoot 'build_case.py'), '--name', 'hearth_fine', '--cell', '0.25')
Run-Python @((Join-Path $cfdRoot 'build_case.py'), '--name', 'hearth_equilibrium', '--duration', '2', '--closed', '--flat')
foreach ($caseName in @('hearth', 'hearth_fine', 'hearth_equilibrium')) {
    $casePath = Join-Path $cfdRoot $caseName
    $linuxPath = (& wsl -d Ubuntu -- wslpath -a $casePath).Trim()
    if ($LASTEXITCODE -ne 0 -or $linuxPath.Contains("'")) { throw 'Invalid WSL path' }
    $command = "export HWLOC_COMPONENTS=-gl; source /opt/openfoam14/etc/bashrc; cd '$linuxPath' && blockMesh > log.blockMesh 2>&1 && checkMesh > log.checkMesh 2>&1 && foamRun > log.foamRun 2>&1 && foamPostProcess -func writeCellCentres -time 0 > log.centres 2>&1"
    & wsl -d Ubuntu -- bash -lc $command
    if ($LASTEXITCODE -ne 0) { throw "OpenFOAM failed in $caseName; inspect its log files" }
}
Run-Python @((Join-Path $cfdRoot 'export_results.py'))
Run-Python @((Join-Path $cfdRoot 'plot_results.py'))
Write-Output 'CFD verified. Rebuild the Unity scene / Blender playback to refresh deliverables.'
