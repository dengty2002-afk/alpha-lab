[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$toolsDirectory = Join-Path $PSScriptRoot '.tools'
New-Item -ItemType Directory -Path $toolsDirectory -Force | Out-Null
$packages = @(
    @{
        Name = 'Temurin JDK 21.0.12.1+1'
        Url = 'https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip'
        Archive = 'jdk21.zip'
        Directory = 'jdk-21.0.12.1+1'
        Check = 'bin/java.exe'
        Algorithm = 'SHA256'
        Hash = 'f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e'
    },
    @{
        Name = 'Apache Maven 3.9.16'
        Url = 'https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.16/apache-maven-3.9.16-bin.zip'
        Archive = 'maven.zip'
        Directory = 'apache-maven-3.9.16'
        Check = 'bin/mvn.cmd'
        Algorithm = 'SHA512'
        Hash = 'ed41650d42485cfc243fad22158caf9cbb5dc408ce7a09ddb94dd42a019de929ca43065bfa450612cf12bf78b5cafa3884b96c090de326ff590448c933454af3'
    }
)
foreach ($package in $packages) {
    $destination = Join-Path $toolsDirectory $package.Directory
    if (Test-Path -LiteralPath (Join-Path $destination $package.Check)) {
        Write-Host "$($package.Name) is already available at $destination"
        continue
    }
    $archivePath = Join-Path $toolsDirectory $package.Archive
    if (-not (Test-Path -LiteralPath $archivePath)) {
        Write-Host "Downloading $($package.Name) from its official distribution..."
        Invoke-WebRequest -Uri $package.Url -OutFile $archivePath -TimeoutSec 600
    }
    $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm $package.Algorithm).Hash.ToLowerInvariant()
    if ($actualHash -ne $package.Hash) { throw "Checksum mismatch for $archivePath. No archive was extracted." }
    Expand-Archive -LiteralPath $archivePath -DestinationPath $toolsDirectory -Force
    if (-not (Test-Path -LiteralPath (Join-Path $destination $package.Check))) { throw "Incomplete installation: $($package.Name)" }
    Write-Host "Verified and prepared $($package.Name)"
}
$javaExecutable = Join-Path $toolsDirectory 'jdk-21.0.12.1+1/bin/java.exe'
& $javaExecutable -version
if ($LASTEXITCODE -ne 0) { throw 'Java verification failed' }
