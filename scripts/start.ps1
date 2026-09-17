param([int]$Port = 8080, [switch]$Build, [switch]$NoBrowser, [string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw '端口须在 1024—65535 之间' }
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ($Build) { & (Join-Path $PSScriptRoot 'build.ps1') }
$jarPath = Join-Path $projectRoot 'backend\target\quant-platform.jar'
if (-not (Test-Path -LiteralPath $jarPath)) { throw '尚无构建产物；请执行 scripts/build.ps1 或 start.ps1 -Build。' }
$jdk = Get-ChildItem -LiteralPath (Join-Path $projectRoot 'backend\.tools') -Directory -Filter 'jdk*' | Select-Object -First 1
$java = if ($jdk) { Join-Path $jdk.FullName 'bin\java.exe' } else { (Get-Command java -ErrorAction Stop).Source }
if (-not $PythonPath) { $PythonPath = Join-Path $projectRoot 'research\.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw '研究 Python 环境不存在；请先执行 bootstrap.ps1。' }
$baseUrl = "http://127.0.0.1:$Port"
$existing = $null
try { $existing = Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 2 } catch { }
if ($existing) {
    if ($existing.workspace -and [IO.Path]::GetFullPath($existing.workspace) -eq [IO.Path]::GetFullPath((Join-Path $projectRoot 'workspace'))) {
        Write-Output "应用已经运行：$baseUrl"
        if (-not $NoBrowser) { Start-Process $baseUrl }
        return
    }
    throw "端口 $Port 已有服务，请指定其他端口。"
}
$runtimeDir = Join-Path $projectRoot 'workspace\runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$env:QUANT_PROJECT_DIR = $projectRoot
$env:QUANT_PYTHON = (Resolve-Path -LiteralPath $PythonPath).Path
$env:QUANT_PORT = [string]$Port
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdout = Join-Path $runtimeDir "server-$stamp.out.log"
$stderr = Join-Path $runtimeDir "server-$stamp.err.log"
$process = Start-Process -FilePath $java -ArgumentList @('-Xmx768m', '-Dfile.encoding=UTF-8', '-jar', "`"$jarPath`"") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
$state = @{ pid = $process.Id; port = $Port; project = $projectRoot; java = $java; startedAt = $process.StartTime.ToUniversalTime().ToString('o'); stdout = $stdout; stderr = $stderr }
$state | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimeDir 'server.json') -Encoding utf8
$ready = $false
for ($attempt = 0; $attempt -lt 45; $attempt++) {
    $process.Refresh()
    if ($process.HasExited) { throw "服务启动失败，请查看 $stdout 和 $stderr" }
    try {
        $health = Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 2
        if ($health.status) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw "服务尚未就绪，请查看 $stdout 和 $stderr" }
Write-Output "应用已启动：$baseUrl"
Write-Output "日志：$stdout"
if (-not $NoBrowser) { Start-Process $baseUrl }
