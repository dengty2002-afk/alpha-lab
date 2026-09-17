$ErrorActionPreference = 'Continue'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot 'research\.venv\Scripts\python.exe'
$jdk = Get-ChildItem -LiteralPath (Join-Path $projectRoot 'backend\.tools') -Directory -Filter 'jdk*' | Select-Object -First 1
$result = [ordered]@{ project = $projectRoot; pythonExists = (Test-Path -LiteralPath $python); javaExists = [bool]$jdk; jarExists = (Test-Path -LiteralPath (Join-Path $projectRoot 'backend\target\quant-platform.jar')); snapshots = @(Get-ChildItem -Path (Join-Path $projectRoot 'workspace\snapshots\*\manifest.json') -ErrorAction SilentlyContinue).Count }
if ($jdk) { & (Join-Path $jdk.FullName 'bin\java.exe') -version }
if ($result.pythonExists) { & $python -c "import sys, qlib, lightgbm, pandas, pyarrow; print({'python':sys.version,'qlib':qlib.__version__,'lightgbm':lightgbm.__version__,'pandas':pandas.__version__,'pyarrow':pyarrow.__version__})" }
$result | ConvertTo-Json
