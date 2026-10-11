# Install the signed Ubuntu application without launching it or restarting Windows.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$bundlePath = Join-Path $projectRoot 'external\installers\Ubuntu2204-221101.AppxBundle'
$manifestPath = Join-Path $projectRoot 'external\installers\Ubuntu2204-bundle-manifest.xml'
$reportPath = Join-Path $projectRoot 'reports\stage0\ubuntu_install.json'
$result = @{
    status = 'NOT_RUN'
    distribution = 'Ubuntu-22.04'
    application_installed = $false
    linux_initialized = $false
    automatic_restart = $false
    linux_validation = 'NOT_RUN; wait for user restart, then run small CPU checks'
}
try {
    [xml]$bundleManifest = Get-Content -Raw -LiteralPath $manifestPath
    $packageName = [string]$bundleManifest.Bundle.Identity.Name
    $packageVersion = [string]$bundleManifest.Bundle.Identity.Version
    if ($packageName -ne 'CanonicalGroupLimited.Ubuntu' -or $packageVersion -notlike '2204.*') { throw 'Unexpected identity in the official Ubuntu 22.04 bundle' }
    $existing = Get-AppxPackage -Name $packageName
    if ($existing -and $existing.Version.ToString() -ne $packageVersion) { throw 'Another Ubuntu application version is installed; preserve it and inspect before changing it' }
    if (-not $existing) {
        if (-not (Test-Path -LiteralPath $bundlePath)) { throw 'Official Ubuntu bundle is missing' }
        Add-AppxPackage -Path $bundlePath -ErrorAction Stop
        $existing = Get-AppxPackage -Name $packageName
    }
    if (-not $existing) { throw 'Ubuntu application was not found after package installation' }
    $result.application_installed = $true
    $result.package_name = $existing.Name
    $result.package_full_name = $existing.PackageFullName
    $result.package_version = $existing.Version.ToString()
    $result.install_location = $existing.InstallLocation
    $result.package_status = $existing.Status.ToString()
    $result.component_reboot_pending = Test-Path -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
    $result.status = if ($result.component_reboot_pending) { 'APP_INSTALLED_REBOOT_REQUIRED' } else { 'APP_INSTALLED_NOT_INITIALIZED' }
} catch {
    $result.status = 'FAIL'
    $result.error = $_.Exception.Message
}
$json = $result | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText($reportPath, $json, [Text.UTF8Encoding]::new($false))
Write-Output $json
if ($result.status -eq 'FAIL') { exit 1 }
