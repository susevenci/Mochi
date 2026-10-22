# 窗口形态取证（T0-09 / T2-09）：启动壳，枚举该进程的所有顶层窗口并读取样式。
# 透明 = WS_EX_LAYERED(0x80000)；置顶 = WS_EX_TOPMOST(0x8)；不占任务栏 = WS_EX_TOOLWINDOW(0x80)。
param(
    [string]$Exe = "",
    [int]$WaitSeconds = 20
)

$ErrorActionPreference = 'Stop'
if (-not $Exe) { $Exe = Join-Path $PSScriptRoot '..\desktop\src-tauri\target\x86_64-pc-windows-gnu\debug\mochi.exe' }
$Exe = [System.IO.Path]::GetFullPath($Exe)

Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WinEnum {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr hWnd, int nIndex);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr hWnd, StringBuilder sb, int max);
    [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int max);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    public static List<string> List(uint targetPid) {
        var rows = new List<string>();
        EnumWindows((h, l) => {
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid != targetPid) return true;
            var cls = new StringBuilder(256); GetClassName(h, cls, 256);
            var title = new StringBuilder(256); GetWindowText(h, title, 256);
            RECT r; GetWindowRect(h, out r);
            int ex = GetWindowLong(h, -20);
            rows.Add(string.Format(
                "hwnd={0} class={1} title='{2}' visible={3} size={4}x{5} pos={6},{7} exstyle=0x{8:X} layered={9} topmost={10} toolwin={11}",
                h, cls, title, IsWindowVisible(h), r.Right - r.Left, r.Bottom - r.Top, r.Left, r.Top,
                ex, (ex & 0x80000) != 0, (ex & 0x8) != 0, (ex & 0x80) != 0));
            return true;
        }, IntPtr.Zero);
        return rows;
    }
}
"@

$proc = Start-Process -FilePath $Exe -PassThru
Write-Host "[win] started pid=$($proc.Id)"
Start-Sleep -Seconds $WaitSeconds

if ($proc.HasExited) {
    Write-Host "[win] FAIL: 进程已退出 exit=$($proc.ExitCode)"
    exit 1
}

$rows = [WinEnum]::List([uint32]$proc.Id)
$rows | ForEach-Object { Write-Host "[win] $_" }

# 主窗口特征：可见 + 宽度 > 300（Tauri 的辅助窗口只有 15x15）
$main = $rows | Where-Object { $_ -match 'visible=True' -and $_ -match 'size=(\d+)x' -and [int]$Matches[1] -gt 300 }
$ok = $false
if ($main) {
    $ok = ($main -match 'topmost=True')
    Write-Host "[win] main => $main"

    # 透明取证：比较窗口左上角内侧与窗口外侧同一点的像素颜色
    if ($main -match 'size=\d+x\d+ pos=(-?\d+),(-?\d+)') {
        $left = [int]$Matches[1]; $top = [int]$Matches[2]
        Add-Type -AssemblyName System.Drawing
        $bmp = New-Object System.Drawing.Bitmap 1, 1
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($left + 4, $top + 4, 0, 0, $bmp.Size)
        $inside = $bmp.GetPixel(0, 0)
        $g.CopyFromScreen([math]::Max($left - 8, 0), $top + 4, 0, 0, $bmp.Size)
        $outside = $bmp.GetPixel(0, 0)
        $g.Dispose(); $bmp.Dispose()
        $diff = [math]::Abs($inside.R - $outside.R) + [math]::Abs($inside.G - $outside.G) + [math]::Abs($inside.B - $outside.B)
        Write-Host "[win] corner inside=($($inside.R),$($inside.G),$($inside.B)) outside=($($outside.R),$($outside.G),$($outside.B)) diff=$diff"
        if ($diff -le 24) { Write-Host "[win] 透明判定：角落露出桌面 => PASS"; $ok = $true }
        else { Write-Host "[win] 透明判定：角落被不透明背景遮住 => 待人工确认（截图目视）"; $ok = $false }
    }
}

Start-Sleep -Seconds 1
$proc.Kill()
Write-Host "[win] closed (verdict=$(if ($ok) { 'PASS' } else { 'CHECK' }))"
if (-not $ok) { exit 2 }
exit 0
