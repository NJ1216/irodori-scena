$ErrorActionPreference = 'Stop'
$repository = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$env:Path=(Join-Path $env:LOCALAPPDATA 'irodori-scena-dev-tools')+';'+[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')
Set-Location $repository
$expected = Join-Path $repository 'src-tauri\target\debug\irodori-scena.exe'
$running = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.Equals($expected, [StringComparison]::OrdinalIgnoreCase) })
if ($running.Count) {
    & node.exe tools/verify-dev-app.mjs
    if ($LASTEXITCODE -ne 0) { throw 'Existing development app could not be verified. No second app was started.' }
    Write-Output 'The development app is already running. Reuse its window.'
    exit 0
}
$occupied = @(Get-NetTCPConnection -State Listen -LocalPort 5175 -ErrorAction SilentlyContinue)
if ($occupied.Count) { throw 'Port 5175 is already occupied. No process was stopped or restarted.' }
if (-not (Test-Path scena_native.pyd) -or -not (Test-Path node_modules) -or -not (Test-Path .venv)) { throw 'Run pnpm install --frozen-lockfile, uv sync --frozen, and pnpm build:native first.' }
& pnpm.cmd tauri dev --no-watch
exit $LASTEXITCODE
