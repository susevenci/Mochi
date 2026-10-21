# 准备 Tauri 壳所需的 binutils（dlltool / ar / windres / ld）。
#
# 背景：本机没有 Visual Studio（`link.exe` 缺失），所以壳固定走 GNU 工具链
# （`desktop/src-tauri/rust-toolchain.toml`）。Rust 的 windows-gnu 目标自带
# self-contained 的 mingw 链接库，配合 `rust-lld` 即可完成链接，**不需要完整的 MinGW**；
# 只有 rustc 生成 raw-dylib 导入库时需要 `dlltool`，tauri-build 打资源时需要 `windres`。
#
# 因此这里只取 w64devkit（36MB，含 binutils）并解压，**不需要管理员权限**。
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts/setup_binutils.ps1
param(
    [string]$Destination = "$env:LOCALAPPDATA\MochiTools\w64devkit",
    [int]$Threads = 8
)

$ErrorActionPreference = 'Stop'
$tools = "$env:LOCALAPPDATA\MochiTools"
$exe = Join-Path $tools 'w64devkit.exe'
$url = 'https://github.com/skeeto/w64devkit/releases/download/v2.2.0/w64devkit-x64-2.2.0.7z.exe'
$expected = 38171793

$existing = Get-ChildItem $Destination -Recurse -Filter 'dlltool.exe' -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($existing) {
    Write-Host "[binutils] 已就绪：$($existing.Directory.FullName)" -ForegroundColor Green
    exit 0
}

New-Item -ItemType Directory -Force -Path $tools | Out-Null

if (-not (Test-Path $exe) -or (Get-Item $exe).Length -ne $expected) {
    Write-Host "[binutils] 并行下载 w64devkit（GitHub 单连接被限速，这里分 $Threads 块）…" -ForegroundColor Cyan
    $head = [System.Net.WebRequest]::Create($url)
    $head.Method = 'HEAD'
    $headResp = $head.GetResponse()
    $size = [long]$headResp.Headers['Content-Length']
    $headResp.Close()
    if ($size -le 0) { throw '拿不到文件大小' }

    $chunk = [math]::Ceiling($size / $Threads)
    $parts = @()
    $jobs = @()
    for ($i = 0; $i -lt $Threads; $i++) {
        $start = [long]($i * $chunk)
        $end = [long][math]::Min(($start + $chunk - 1), ($size - 1))
        if ($start -gt $end) { continue }
        $part = "$exe.part$i"
        $parts += $part
        $jobs += Start-Job -ScriptBlock {
            param($u, $s, $e, $p)
            $req = [System.Net.WebRequest]::Create($u)
            $req.AddRange($s, $e)
            $resp = $req.GetResponse()
            $in = $resp.GetResponseStream()
            $fs = [System.IO.File]::Create($p)
            $buf = New-Object byte[] 65536
            while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) { $fs.Write($buf, 0, $n) }
            $fs.Close(); $in.Close(); $resp.Close()
        } -ArgumentList $url, $start, $end, $part
    }
    $jobs | Wait-Job | Out-Null
    $jobs | Receive-Job -ErrorAction Stop | Out-Null
    $jobs | Remove-Job

    $fs = [System.IO.File]::Create($exe)
    foreach ($p in $parts) {
        $in = [System.IO.File]::OpenRead($p)
        $in.CopyTo($fs)
        $in.Close()
        Remove-Item $p -Force
    }
    $fs.Close()
    if ((Get-Item $exe).Length -ne $size) { throw '下载拼接后大小不符' }
}

Write-Host '[binutils] 解压…' -ForegroundColor Cyan
if (Test-Path $Destination) { Remove-Item $Destination -Recurse -Force }
& $exe -y -o"$Destination" | Out-Null

$dlltool = Get-ChildItem $Destination -Recurse -Filter 'dlltool.exe' | Select-Object -First 1
if (-not $dlltool) { throw '解压后未找到 dlltool.exe' }
Write-Host "[binutils] 完成：$($dlltool.Directory.FullName)" -ForegroundColor Green
Write-Host "[binutils] 构建时用 scripts/tauri.ps1（会自动注入 PATH）" -ForegroundColor Green
