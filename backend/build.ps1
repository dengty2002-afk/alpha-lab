[CmdletBinding()]
param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'setup-tools.ps1')
$oldJavaHome = $env:JAVA_HOME
$env:JAVA_HOME = Join-Path $PSScriptRoot '.tools/jdk-21.0.12.1+1'
Push-Location $PSScriptRoot
try {
    $maven = Join-Path $PSScriptRoot '.tools/apache-maven-3.9.16/bin/mvn.cmd'
    $mavenArguments = @('-B', '-ntp', '-Dmaven.repo.local=.m2', 'package')
    if ($SkipTests) { $mavenArguments += '-DskipTests' }
    & $maven @mavenArguments
    if ($LASTEXITCODE -ne 0) { throw "Maven build failed: $LASTEXITCODE" }
} finally {
    Pop-Location
    $env:JAVA_HOME = $oldJavaHome
}
