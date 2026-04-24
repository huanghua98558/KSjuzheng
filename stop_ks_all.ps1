# ================================================================
# Stop all KS Matrix + Hermes Gateway processes
# ================================================================
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ''
Write-Host '================================================================' -ForegroundColor Cyan
Write-Host '  KS Matrix + Hermes — Stopping all processes' -ForegroundColor Cyan
Write-Host '================================================================' -ForegroundColor Cyan
Write-Host ''

$killed = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'hermes.exe') -or
    ($_.Name -eq 'python.exe' -and $_.CommandLine -ne $null -and (
        $_.CommandLine -match 'run_autopilot' -or
        $_.CommandLine -match 'dashboard[\\/]app\.py' -or
        $_.CommandLine -match 'hermes gateway run'
    ))
}

if (-not $killed) {
    Write-Host '  (no running processes found)' -ForegroundColor Yellow
} else {
    foreach ($p in $killed) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host ('  killed PID ' + $p.ProcessId + ' ' + $p.Name) -ForegroundColor Green
        } catch {}
    }
}

# 清 PID 文件
Remove-Item 'D:\ks_automation\logs\autopilot.pid','D:\ks_automation\logs\dashboard.pid','D:\hermes-gateway\logs\gateway.pid','C:\Users\Administrator\.hermes\gateway.pid' -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host '  [OK] Stopped' -ForegroundColor Green
Write-Host ''
