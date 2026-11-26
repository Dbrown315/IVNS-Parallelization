# Windows benchmarking

Use a 64-bit Windows machine, **CPython 3.11 x64**, and the **Microsoft MS-MPI
runtime**. Install the runtime from
[Microsoft's MS-MPI download page](https://learn.microsoft.com/en-us/message-passing-interface/microsoft-mpi).
The pinned mpi4py package uses the installed runtime; the MS-MPI SDK is not
needed when pip installs a compatible wheel. Use the same Python and MPI
versions for every comparison.

## Install and check

Run from the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-mpi.txt
$env:PYTHONUTF8 = '1'
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
Get-Command mpiexec
.\.venv\Scripts\python.exe -c "from mpi4py import MPI; print(MPI.Get_library_version())"
```

Calling the virtual environment interpreter directly avoids activation-policy
and wrong-interpreter problems. If MS-MPI is not on PATH, set it for the current
PowerShell session:

```powershell
$env:Path = "$env:ProgramFiles\Microsoft MPI\Bin;$env:Path"
```

## Preflight before collecting timings

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_windows.ps1
```

The execution-policy option applies only to that PowerShell process. The script
checks Python/MPI, runs unit tests, checks TESLA/TLS delivery and semantic traces
on several rank counts, then runs small LWA/TESLA/TLS benchmark checks on one
and two ranks. JSON reports go to `benchmark-results/preflight`. A failed native
command makes preflight fail; a success message requires all checks to complete.

For custom installation paths:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_windows.ps1 -Python "C:\IVNS Tools\.venv\Scripts\python.exe" -MpiExec "C:\Program Files\Microsoft MPI\Bin\mpiexec.exe"
```

The [Windows CI workflow](../.github/workflows/windows-benchmark-smoke.yml)
installs Python 3.11/MS-MPI on a Windows runner and invokes the same preflight.
Its reports are uploaded as the `windows-mpi-preflight` artifact. CI is a
portability/correctness check, not performance evidence for the lab machines.
Run preflight on those machines even when CI passes. Native Windows validation
status is visible in the repository's Actions tab; the development workspace
cannot itself substitute for a Windows run.

## Launch the scenarios

```powershell
mpiexec -n 4 .\.venv\Scripts\python.exe main_lwa_param.py --ecus 12 --buses 4 --output-dir "benchmark-results\LWA run"
mpiexec -n 4 .\.venv\Scripts\python.exe main_tesla_param.py --ecus 12 --buses 4 --output-dir "benchmark-results\TESLA run"
mpiexec -n 4 .\.venv\Scripts\python.exe main_tls_param.py --ecus 12 --buses 4 --output-dir "benchmark-results\TLS run"
```

LWA uses a gateway-connected chain and a cross-bus ring. TESLA/TLS use independent
bus-local protocol rings; see [scenario differences and parameters](protocol-scenarios.md).
Do not compare the protocols' raw times as equivalent workloads.

## Collect repeated benchmarks

```powershell
.\.venv\Scripts\python.exe benchmarks/benchmark_protocols.py --protocol lwa --suite factors --repeats 3 --output benchmark-results/lwa.json
.\.venv\Scripts\python.exe benchmarks/benchmark_protocols.py --protocol tesla --suite strong --repeats 3 --output benchmark-results/tesla.json
.\.venv\Scripts\python.exe benchmarks/benchmark_protocols.py --protocol tls --suite strong --repeats 3 --output benchmark-results/tls.json
```

Use `--mpiexec "C:\Program Files\Microsoft MPI\Bin\mpiexec.exe"` when needed.
The driver launches `sys.executable`, passes arguments as a list without a shell,
uses UTF-8 subprocess output, and handles paths containing spaces. CSV writers
use explicit UTF-8 and `newline=''`, avoiding doubled newlines on Windows.
Temporary output files are closed before merging and process completion before
benchmark cleanup. No Unix process APIs or system filesystem paths are required.

Each workload is compared to its own one-rank baseline. Reports retain protocol,
traffic layout, interpreter, platform, package versions, CPU count, raw timings,
medians, and source fingerprint. Timing includes the launcher and cleanup; a
separate loop metric excludes setup/export. Failed runs, missing application
reception, or semantic trace changes do not count as benchmark samples.

Keep hardware/power settings, inputs, CPU allocation, and thread limits constant.
Avoid unrelated jobs during timing and use enough repetitions to quantify
variation. More ranks than buses cannot create additional independent work.
Historical [cloud measurements](partitioned-scaling.md) are retained with their
original provenance; they are not Windows measurements or predictions of your
machines' speedup. Generate fresh reports for the Windows benchmark results.
