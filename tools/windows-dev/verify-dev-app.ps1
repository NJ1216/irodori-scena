param([string]$RepositoryRoot = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))
$ErrorActionPreference = 'Stop'
$expected = Join-Path $RepositoryRoot 'src-tauri\target\debug\irodori-scena.exe'
$all = @(Get-CimInstance Win32_Process)
$apps = @($all | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.Equals($expected, [StringComparison]::OrdinalIgnoreCase) })
if ($apps.Count -eq 0) { throw 'no running development app in this Windows checkout' }
if ($apps.Count -ne 1) { throw 'ambiguous development app processes' }
$application = $apps[0]
$config = Get-Content (Join-Path $RepositoryRoot 'src-tauri\tauri.dev.conf.json') -Raw | ConvertFrom-Json
if ($config.identifier -ne 'com.irodori-scena.dev' -or $config.app.windows[0].title -ne 'irodori SCENA [DEV]') { throw 'development configuration identity mismatch' }
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class ScenaWindowProbe {
  public delegate bool Callback(IntPtr h, IntPtr p);
  [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool EnumWindows(Callback callback, IntPtr p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder text, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out Rect rect);
  [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetWindowDpiAwarenessContext(IntPtr h);
  [DllImport("user32.dll")] public static extern bool AreDpiAwarenessContextsEqual(IntPtr first, IntPtr second);
}
'@
$script:matched = @()
$expectedPid = [uint32]$application.ProcessId
[ScenaWindowProbe]::EnumWindows({ param($handle, $unused)
    $owner = [uint32]0
    [void][ScenaWindowProbe]::GetWindowThreadProcessId($handle, [ref]$owner)
    if ($owner -eq $expectedPid) {
        $title = New-Object Text.StringBuilder 1024
        [void][ScenaWindowProbe]::GetWindowText($handle, $title, 1024)
        if ($title.ToString() -eq 'irodori SCENA [DEV]' -and [ScenaWindowProbe]::IsWindowVisible($handle) -and -not [ScenaWindowProbe]::IsIconic($handle)) {
            $rect = New-Object ScenaWindowProbe+Rect
            [void][ScenaWindowProbe]::GetWindowRect($handle, [ref]$rect)
            if ($rect.Right -gt $rect.Left -and $rect.Bottom -gt $rect.Top) {
                $dpi = [ScenaWindowProbe]::GetDpiForWindow($handle)
                $dpiContext = [ScenaWindowProbe]::GetWindowDpiAwarenessContext($handle)
                $perMonitorV2 = [ScenaWindowProbe]::AreDpiAwarenessContextsEqual($dpiContext, [IntPtr](-4))
                $script:matched += @{x=$rect.Left; y=$rect.Top; width=$rect.Right-$rect.Left; height=$rect.Bottom-$rect.Top; dpi=$dpi; scaleFactor=$dpi/96; perMonitorV2=$perMonitorV2}
            }
        }
    }
    return $true
}, [IntPtr]::Zero) | Out-Null
if ($script:matched.Count -ne 1) { throw 'no unique visible development window titled irodori SCENA [DEV] in this desktop session' }
if (-not $script:matched[0].perMonitorV2) { throw 'development window is not Per-Monitor V2 DPI aware' }
if ($script:matched[0].dpi -lt 96) { throw 'development window returned an invalid DPI value' }
$descendants = [Collections.Generic.HashSet[uint32]]::new()
[void]$descendants.Add($expectedPid)
do {
    $before = $descendants.Count
    foreach ($item in $all) { if ($descendants.Contains([uint32]$item.ParentProcessId)) { [void]$descendants.Add([uint32]$item.ProcessId) } }
} while ($descendants.Count -gt $before)
$listeners = @(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $descendants.Contains([uint32]$_.OwningProcess) -and $_.OwningProcess -ne $expectedPid })
if ($listeners.Count -ne 1) { throw 'development app has no unique supervised API listener' }
$vite = Invoke-WebRequest 'http://127.0.0.1:5175/' -UseBasicParsing -TimeoutSec 3
if ($vite.StatusCode -ne 200) { throw 'development Vite is unavailable' }
@{bundleIdentifier=$config.identifier; identitySource='development configuration, exact checkout executable and window title'; pid=$expectedPid; windowTitle='irodori SCENA [DEV]'; visible=$true; windowBounds=$script:matched[0]; frontendUrl='http://127.0.0.1:5175/'; apiListeners=@($listeners | ForEach-Object { '127.0.0.1:'+$_.LocalPort })} | ConvertTo-Json -Depth 5
