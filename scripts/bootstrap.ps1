param([string]$BasePython = '')
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$toolsSetup = Join-Path $projectRoot 'backend\setup-tools.ps1'
if (Test-Path -LiteralPath $toolsSetup) { & $toolsSetup } else { throw 'Java 工具链准备脚本缺失，请检查项目文件是否完整。' }
if (-not $BasePython) {
    $candidate = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.Source -notlike '*WindowsApps*') { $BasePython = $candidate.Source }
}
if (-not $BasePython) {
    $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundled) { $BasePython = $bundled }
}
if (-not $BasePython -or -not (Test-Path -LiteralPath $BasePython)) { throw '需要 CPython 3.12 x64。请安装后以 -BasePython C:\路径\python.exe 指定。' }
& $BasePython -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P')==8, 'CPython 3.12 x64 required for the locked environment'"
if ($LASTEXITCODE -ne 0) { throw 'Python 版本或架构不符合要求' }
$env:PYTHONUTF8 = '1'
$venv = Join-Path $projectRoot 'research\.venv'
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) {
    & $BasePython -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw '创建项目 Python 环境失败' }
}
$python = Join-Path $venv 'Scripts\python.exe'
$lock = Join-Path $projectRoot 'research\requirements-lock.txt'
if (-not (Test-Path -LiteralPath $lock)) { $lock = Join-Path $projectRoot 'research\requirements.txt' }
& $python -m pip install --disable-pip-version-check -r $lock
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败' }
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
Push-Location (Join-Path $projectRoot 'frontend')
try {
    & $npm ci
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
} finally { Pop-Location }
Write-Output '项目环境准备完成。接着运行 scripts/build.ps1 和 scripts/start.ps1。'
