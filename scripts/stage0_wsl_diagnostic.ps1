$ErrorActionPreference = 'Stop'
$result = [ordered]@{}
$result.features = @('VirtualMachinePlatform','Microsoft-Windows-Subsystem-Linux' | ForEach-Object { Get-WindowsOptionalFeature -Online -FeatureName $_ | Select-Object FeatureName,State })
$result.boot = (& bcdedit /enum '{current}' 2>&1 | Out-String)
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath 'D:\Codes\policytrace\reports\stage0\wsl_post_reboot_diagnostic.json' -Encoding UTF8

