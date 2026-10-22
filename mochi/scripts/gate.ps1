# 质量门禁（计划 0.2）：quick 用于任务簇，full 用于阶段末。
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts/gate.ps1 -Quick
#   powershell -ExecutionPolicy Bypass -File scripts/gate.ps1 -Stage S3
param(
    [switch]$Quick,
    [string]$Stage = 'S3'
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Step([string]$Name, [scriptblock]$Block) {
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    & $Block
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    if ($code -ne 0) {
        Write-Host "FAILED: $Name (exit $code)" -ForegroundColor Red
        $script:failures += $Name
    }
    else {
        Write-Host "OK: $Name" -ForegroundColor Green
    }
}

$script:failures = @()
$py = Join-Path $PSScriptRoot 'py.ps1'

Invoke-Step 'ruff' {
    & $py -m ruff check server scripts --config pyproject.toml
}

if (-not $Quick) {
    Invoke-Step 'mypy' {
        & $py -m mypy server\app scripts --config-file pyproject.toml
    }
}

$covArgs = @('-m', 'pytest', 'server\tests', '-q')
if (-not $Quick -and $Stage -ne 'G0') {
    if ($Stage -in @('S6', 'S7')) {
        $covArgs += @('--cov=app', '--cov-report=term-missing', '--cov-fail-under=60')
    }
    else {
        $covArgs += @('--cov=app.emotion', '--cov-report=term-missing', '--cov-fail-under=80')
    }
}
Invoke-Step 'pytest' { & $py @covArgs }

if (-not $Quick) {
    Invoke-Step 'schema-export' { & $py scripts\export_schema.py }
    Invoke-Step 'ts-types' { node scripts\gen-types.mjs }
    Invoke-Step 'contract-drift' {
        git diff --exit-code -- shared frontend/src/types
    }
    Invoke-Step 'frontend-build' {
        npm.cmd --prefix frontend run build
    }
    $frontendPkg = Get-Content frontend\package.json -Raw | ConvertFrom-Json
    if ($frontendPkg.scripts.PSObject.Properties.Name -contains 'test') {
        Invoke-Step 'frontend-test' {
            npm.cmd --prefix frontend test -- --run
        }
    }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$evidenceDir = Join-Path $root '..\docs\evidence'
New-Item -ItemType Directory -Force $evidenceDir | Out-Null
$mode = if ($Quick) { 'quick' } else { 'full' }
$evidence = Join-Path $evidenceDir ("{0}-gate-{1}.txt" -f $Stage.ToLower(), $mode)
@(
    "stage=$Stage mode=$mode at=$(Get-Date -Format o)",
    "python=$(& $py)",
    "failures=$($script:failures -join ',')"
) | Set-Content -Encoding utf8 $evidence
Write-Host "`n证据：$evidence" -ForegroundColor DarkGray

if ($script:failures.Count -gt 0) {
    Write-Host "门禁失败：$($script:failures -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host '门禁全部通过' -ForegroundColor Green
exit 0
