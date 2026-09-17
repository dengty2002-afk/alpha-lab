$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$statePath = Join-Path $projectRoot 'workspace\runtime\server.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Output '没有此项目的运行记录。'; return }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ([IO.Path]::GetFullPath($state.project) -ne [IO.Path]::GetFullPath($projectRoot)) { throw '运行记录不属于此项目' }
$baseUrl = 'http://127.0.0.1:' + [int]$state.port
try { $health = Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 3 } catch { Write-Output '服务当前未响应；请检查日志。'; return }
if (-not $health.workspace -or [IO.Path]::GetFullPath($health.workspace) -ne [IO.Path]::GetFullPath((Join-Path $projectRoot 'workspace'))) { throw '端口服务不属于当前项目，未停止。' }
Invoke-RestMethod -Uri "$baseUrl/api/shutdown" -Method Post -ContentType 'application/json' -Body '{}' -TimeoutSec 10 | Out-Null
Write-Output '已请求服务正常退出并结束其管理的计算任务。'
