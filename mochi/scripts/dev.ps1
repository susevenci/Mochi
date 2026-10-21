# 一键启动开发环境（T0-12）
# 用法：powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
#      powershell ... -File scripts/dev.ps1 -BackendOnly
param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $FrontendOnly) {
    Write-Host '[mochi] backend  -> http://127.0.0.1:8765/health' -ForegroundColor Cyan
    Start-Process -NoNewWindow powershell -ArgumentList @(
        '-NoExit', '-Command',
        "Set-Location '$root'; python -m uvicorn --app-dir server app.main:create_app --factory --reload --host 127.0.0.1 --port 8765"
    )
}

if (-not $BackendOnly) {
    $pm = if (Get-Command pnpm -ErrorAction SilentlyContinue) { 'pnpm' } else { 'npm.cmd' }
    Write-Host "[mochi] frontend -> http://127.0.0.1:5173 (via $pm)" -ForegroundColor Cyan
    Start-Process -NoNewWindow powershell -ArgumentList @(
        '-NoExit', '-Command',
        "Set-Location '$root/frontend'; & $pm run dev"
    )
}

Write-Host '[mochi] 两个终端已启动；关闭对应窗口即可停止。' -ForegroundColor Green
