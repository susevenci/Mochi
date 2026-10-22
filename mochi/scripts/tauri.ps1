# Tauri 壳的统一入口：注入 binutils 到 PATH，再调用 desktop 的 tauri CLI。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts/tauri.ps1 dev
#   powershell -ExecutionPolicy Bypass -File scripts/tauri.ps1 build
#   powershell -ExecutionPolicy Bypass -File scripts/tauri.ps1 -- --no-watch
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$TauriArgs
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1) 找 binutils（可用 MOCHI_BINUTILS_BIN 覆盖）
$binutilsBin = $env:MOCHI_BINUTILS_BIN
if (-not $binutilsBin) {
    $candidate = Join-Path $env:LOCALAPPDATA 'MochiTools\w64devkit'
    $dlltool = Get-ChildItem $candidate -Recurse -Filter 'dlltool.exe' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($dlltool) { $binutilsBin = $dlltool.Directory.FullName }
}

if (-not $binutilsBin -or -not (Test-Path $binutilsBin)) {
    Write-Host '[tauri] 未找到 binutils（dlltool/windres），请先运行：' -ForegroundColor Yellow
    Write-Host '        powershell -ExecutionPolicy Bypass -File scripts/setup_binutils.ps1' -ForegroundColor Yellow
    exit 1
}

$env:PATH = "$binutilsBin;$env:PATH"
$env:MOCHI_ROOT = $root
$env:MOCHI_PYTHON = (Join-Path $root '.venv\python.exe')
Write-Host "[tauri] binutils: $binutilsBin" -ForegroundColor Cyan
Write-Host "[tauri] MOCHI_ROOT: $root" -ForegroundColor Cyan

# 2) 默认参数：dev
if ($TauriArgs.Count -eq 0) { $TauriArgs = @('dev') }
# 允许 `scripts/tauri.ps1 -- --no-watch` 这种写法
if ($TauriArgs[0] -eq '--') { $TauriArgs = $TauriArgs[1..($TauriArgs.Count - 1)] }

Write-Host "[tauri] tauri $($TauriArgs -join ' ')" -ForegroundColor Cyan
& npm.cmd --prefix desktop run tauri -- @TauriArgs
exit $LASTEXITCODE
