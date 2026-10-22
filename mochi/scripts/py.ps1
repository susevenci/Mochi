# 统一解析项目 Python：优先 mochi/.venv（conda 与 venv 两种布局），否则回落到 PATH。
# 用法：& mochi\scripts\py.ps1 -m pytest mochi
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$candidates = @(
    (Join-Path $root '.venv\Scripts\python.exe'),
    (Join-Path $root '.venv\python.exe')
)
$python = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

if ($Args.Count -eq 0) {
    $python
    exit 0
}
& $python @Args
exit $LASTEXITCODE
