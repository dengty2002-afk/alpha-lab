param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$jdk = Get-ChildItem -LiteralPath (Join-Path $projectRoot 'backend\.tools') -Directory -Filter 'jdk*' | Select-Object -First 1
$maven = Get-ChildItem -LiteralPath (Join-Path $projectRoot 'backend\.tools') -Directory -Filter 'apache-maven*' | Select-Object -First 1
if (-not $jdk -or -not $maven) { throw '请先执行 scripts/bootstrap.ps1 准备本地 Java 与 Maven。' }
$env:JAVA_HOME = $jdk.FullName
$env:PATH = (Join-Path $jdk.FullName 'bin') + [IO.Path]::PathSeparator + $env:PATH
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$mvn = Join-Path $maven.FullName 'bin\mvn.cmd'
Push-Location (Join-Path $projectRoot 'frontend')
try {
    & $npm ci
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
    if (-not $SkipTests) {
        & $npm test
        if ($LASTEXITCODE -ne 0) { throw '前端验证失败' }
    }
} finally { Pop-Location }
Push-Location (Join-Path $projectRoot 'backend')
try {
    if ($SkipTests) { & $mvn package '-DskipTests' } else { & $mvn verify }
    if ($LASTEXITCODE -ne 0) { throw 'Java 构建/验证失败' }
} finally { Pop-Location }
if (-not $SkipTests) {
    $env:PYTHONUTF8 = '1'
    $env:PYTHONPATH = Join-Path $projectRoot 'research\src'
    $env:MPLCONFIGDIR = Join-Path $projectRoot 'workspace\cache\matplotlib'
    & (Join-Path $projectRoot 'research\.venv\Scripts\python.exe') -m pytest (Join-Path $projectRoot 'research\tests') -q
    if ($LASTEXITCODE -ne 0) { throw 'Python 验证失败' }
}
Write-Output ('构建完成：' + (Join-Path $projectRoot 'backend\target\quant-platform.jar'))
