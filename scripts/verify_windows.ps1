param(
    [string]$Python = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'),
    [string]$MpiExec = 'mpiexec',
    [string]$OutputDir = (Join-Path $PSScriptRoot '..\benchmark-results\preflight')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepoRoot = Split-Path $PSScriptRoot -Parent
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Exe $($Arguments -join ' ')"
    }
}

Push-Location $RepoRoot
try {
    Invoke-Checked -Exe $Python -Arguments @('-c', 'import sys; assert sys.version_info[:2] == (3,11), sys.version; from mpi4py import MPI; print(sys.executable); print(MPI.Get_library_version())')
    Invoke-Checked -Exe $Python -Arguments @('-m', 'unittest', 'discover', '-s', 'tests', '-v')
    Invoke-Checked -Exe $Python -Arguments @('tests/protocol_param_smoke.py', '--mpiexec', $MpiExec)
    foreach ($Protocol in @('lwa', 'tesla', 'tls')) {
        $Report = Join-Path $OutputDir "$Protocol.json"
        Invoke-Checked -Exe $Python -Arguments @('benchmarks/benchmark_protocols.py', '--protocol', $Protocol,
            '--smoke', '--repeats', '1', '--key-chain-length', '128', '--mpiexec', $MpiExec, '--output', $Report)
    }
    Write-Host "Windows MPI preflight passed. Reports: $OutputDir"
} finally {
    Pop-Location
}
