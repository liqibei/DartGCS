# Dart GCS：Windows "移动热点" 开关（供后端 hotspot.py 调用）
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File hotspot_win.ps1 -Action on|off|status
# 依赖: Win10/11 移动热点功能；PC 需存在网络连接配置文件（以太网/已保存的 Wi-Fi 均可）
param([string]$Action = "status")

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
$null = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
$null = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]

# WinRT IAsyncOperation 在 PowerShell 里的 await 辅助
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
                   $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

try {
    $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if (-not $profile) { Write-Output "ERROR:no-network-profile"; exit 1 }
    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)

    switch ($Action) {
        "on" {
            try {
                # SSID/密码/频段(2=5GHz)：失败不致命，沿用系统现有配置
                $cfgTask = $mgr.ConfigureAccessPointAsync("dart-gcs", [Windows.Networking.NetworkOperators.NetworkOperatorTetheringWiFiAccessPointKeyKind]::Wpa2, "dart2027", [Windows.Networking.NetworkOperators.TetheringWiFiBand]::FiveGHz)
                Await $cfgTask ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringConfiguration]) | Out-Null
            } catch {}
            $null = Await ($mgr.StartTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
            Write-Output "STATE:$($mgr.TetheringOperationalState)"
        }
        "off" {
            $null = Await ($mgr.StopTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
            Write-Output "STATE:$($mgr.TetheringOperationalState)"
        }
        "status" { Write-Output "STATE:$($mgr.TetheringOperationalState)" }
        default  { Write-Output "ERROR:bad-action"; exit 1 }
    }
} catch {
    Write-Output "ERROR:$($_.Exception.Message)"
    exit 1
}
