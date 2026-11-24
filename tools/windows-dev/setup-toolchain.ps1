# Explicit developer-tool installation only. Default invocation prints the plan.
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$plan = @(
    @{tool='Visual Studio 2022 Build Tools'; source='Microsoft.VisualStudio.2022.BuildTools'; components=@('Microsoft.VisualStudio.Workload.VCTools', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', 'Microsoft.VisualStudio.Component.Windows11SDK.26100')},
    @{tool='Rust MSVC stable'; source='Rustlang.Rustup'; version='1.28.2'; profile='minimal'},
    @{tool='Git for Windows'; source='Git.Git'; purpose='Pinned TTS Git dependencies'},
    @{tool='FFmpeg Shared'; source='Gyan.FFmpeg.Shared'; version='8.1.2'; purpose='TorchCodec audio runtime; installed separately, not bundled'},
    @{tool='uv'; source='astral-sh.uv'; version='0.12.5'},
    @{tool='Python'; source='uv managed Python'; version='3.13.12'},
    @{tool='pnpm'; source='npm registry'; version='11.x'; scope='user-local prefix'}
)
if (!$Apply) { $plan | ConvertTo-Json -Depth 5; return }
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run in an explicitly approved elevated session' }
if (!(Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw 'winget is required' }
if (!(Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Existing Node.js/npm is required' }
if ((& node.exe --version) -notmatch '^v24\.') { throw 'This setup expects the verified Node.js 24 environment' }
function Invoke-Checked($Executable, $Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -eq 3010) { throw 'Installation requires a restart; no restart was performed. Stop here.' }
    if ($LASTEXITCODE -ne 0) { throw "Tool installation failed with exit code $LASTEXITCODE; stop and inspect before resuming" }
}
function Install-Package($Id, $Extra) {
    $arguments = @('install', '--id', $Id, '--exact', '--source', 'winget', '--silent', '--disable-interactivity', '--accept-package-agreements', '--accept-source-agreements') + $Extra
    Invoke-Checked 'winget.exe' $arguments
}
Install-Package 'Microsoft.VisualStudio.2022.BuildTools' @('--override', '--wait --quiet --norestart --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --add Microsoft.VisualStudio.Component.Windows11SDK.26100')
Install-Package 'Rustlang.Rustup' @('--version', '1.28.2', '--override', '-y --default-host x86_64-pc-windows-msvc --default-toolchain stable --profile minimal')
Install-Package 'Git.Git' @()
Install-Package 'Gyan.FFmpeg.Shared' @('--version', '8.1.2', '--scope', 'user')
Install-Package 'astral-sh.uv' @('--version', '0.12.5')
# Refresh this process only; installers own their normal PATH registration.
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
if (!(Get-Command uv.exe -ErrorAction SilentlyContinue)) { throw 'uv was installed but is not discoverable; inspect its location before continuing' }
Invoke-Checked 'uv.exe' @('python', 'install', '3.13.12')
$prefix = Join-Path $env:LOCALAPPDATA 'irodori-scena-dev-tools'
Invoke-Checked 'npm.cmd' @('install', '--global', '--prefix', $prefix, '--ignore-scripts', 'pnpm@11')
$env:Path = $prefix + ';' + $env:Path
Invoke-Checked 'rustc.exe' @('--version')
Invoke-Checked 'cargo.exe' @('--version')
Invoke-Checked 'uv.exe' @('--version')
Invoke-Checked (Join-Path $prefix 'pnpm.cmd') @('--version')
Write-Output 'Developer tools installed. No project dependency install, build, test, inference, or app launch was performed.'
