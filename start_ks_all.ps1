# ================================================================
# KS Matrix + Hermes Gateway — One-click Sequential Startup
# ================================================================
# 按顺序启动:
#   1. 清理旧进程 (Hermes + Autopilot + Dashboard)
#   2. Hermes Gateway (端口 8642, 等 /health 通)
#   3. KS Autopilot (ControllerAgent 60s cycle + Phase 2 Executor)
#   4. KS Dashboard (端口 8080)
#   5. 打开浏览器
#   6. 前台 tail 4 条 log, 按 Ctrl+C 退出 (进程不关)
#
# 停所有: 运行 stop_ks_all.ps1
# ================================================================

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$PROJECT = 'D:\ks_automation'
$HERMES_VENV = 'D:\AIbot\swarmclaw-stack\.venv-hermes-win'
$HERMES_EXE = "$HERMES_VENV\Scripts\hermes.exe"
$HERMES_LOG_DIR = 'D:\hermes-gateway\logs'
$PY = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'
$KS_LOG_DIR = "$PROJECT\logs"
$HERMES_HOME = 'C:\Users\Administrator\.hermes'

# ============= 1. 清旧进程 =============
function Write-Banner($title) {
    Write-Host ''
    Write-Host ('=' * 64) -ForegroundColor Cyan
    Write-Host ('  ' + $title) -ForegroundColor Cyan
    Write-Host ('=' * 64) -ForegroundColor Cyan
}

Write-Banner 'KS Matrix + Hermes — One-click Start'

Write-Host '[0/5] Cleaning old processes...' -ForegroundColor Yellow
$killed = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'hermes.exe') -or
    ($_.Name -eq 'python.exe' -and $_.CommandLine -ne $null -and (
        $_.CommandLine -match 'run_autopilot' -or
        $_.CommandLine -match 'dashboard[\\/]app\.py' -or
        $_.CommandLine -match 'hermes gateway run'
    ))
}
foreach ($proc in $killed) {
    try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('    killed PID ' + $proc.ProcessId + ' ' + $proc.Name) -ForegroundColor DarkGray } catch {}
}
Remove-Item "$HERMES_HOME\gateway.pid" -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800
Write-Host '    ok' -ForegroundColor Green

New-Item -ItemType Directory -Force -Path $KS_LOG_DIR, $HERMES_LOG_DIR | Out-Null

# ============= 2. Hermes Gateway =============
Write-Host ''
Write-Host '[1/5] Starting Hermes Gateway (port 8642)...' -ForegroundColor Yellow
if (-not (Test-Path $HERMES_EXE)) {
    Write-Host ('    [ERR] Hermes venv not found: ' + $HERMES_EXE) -ForegroundColor Red
    Write-Host '    Reinstall: see docs/STARTUP_GUIDE.md' -ForegroundColor Red
    exit 1
}
$hermesStdout = "$HERMES_LOG_DIR\gateway.stdout.log"
$hermesStderr = "$HERMES_LOG_DIR\gateway.stderr.log"
Remove-Item $hermesStdout, $hermesStderr -Force -ErrorAction SilentlyContinue
$hermesProc = Start-Process -FilePath $HERMES_EXE -ArgumentList @('gateway','run','-v','--replace') -PassThru -NoNewWindow -RedirectStandardOutput $hermesStdout -RedirectStandardError $hermesStderr
Write-Host ('    Hermes PID: ' + $hermesProc.Id) -ForegroundColor DarkGray
$hermesProc.Id | Out-File "$HERMES_LOG_DIR\gateway.pid" -Encoding ascii

# 等 /health 通 (最多 30s)
Write-Host '    waiting for /health ...' -NoNewline
$hermesReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8642/health' -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $hermesReady = $true; break }
    } catch {}
    Write-Host '.' -NoNewline
}
Write-Host ''
if ($hermesReady) {
    Write-Host '    [OK] Hermes online — http://127.0.0.1:8642/v1 (model: gpt-5.4 via Codex)' -ForegroundColor Green
} else {
    Write-Host '    [WARN] Hermes /health not responding after 30s — continuing anyway (check logs)' -ForegroundColor Yellow
}

# ============= 3. KS Autopilot =============
Write-Host ''
Write-Host '[2/5] Starting KS Autopilot (ControllerAgent + Phase 2 Executor)...' -ForegroundColor Yellow
Set-Location $PROJECT
$autopilotLog = "$KS_LOG_DIR\autopilot_forever.log"
Remove-Item $autopilotLog -Force -ErrorAction SilentlyContinue
$autopilotProc = Start-Process -FilePath $PY -ArgumentList @('-u','-m','scripts.run_autopilot','--log-level','INFO') -PassThru -NoNewWindow -WorkingDirectory $PROJECT -RedirectStandardOutput $autopilotLog -RedirectStandardError "$KS_LOG_DIR\autopilot_err.log"
Write-Host ('    Autopilot PID: ' + $autopilotProc.Id) -ForegroundColor DarkGray
$autopilotProc.Id | Out-File "$KS_LOG_DIR\autopilot.pid" -Encoding ascii
Start-Sleep -Seconds 4
if (-not $autopilotProc.HasExited) {
    Write-Host '    [OK] Autopilot running — 60s cycle' -ForegroundColor Green
} else {
    Write-Host '    [ERR] Autopilot exited — see autopilot_err.log' -ForegroundColor Red
}

# ============= 4. KS Dashboard =============
Write-Host ''
Write-Host '[3/5] Starting KS Dashboard (port 8080)...' -ForegroundColor Yellow
$dashboardLog = "$KS_LOG_DIR\dashboard.log"
Remove-Item $dashboardLog -Force -ErrorAction SilentlyContinue
$env:DISABLE_AUTOPILOT = '1'
$env:DISABLE_WORKERS = '1'  # Dashboard 纯 web, 不跑 worker (避免和 autopilot 抢 DB / GIL)
$dashboardProc = Start-Process -FilePath $PY -ArgumentList @('-X','utf8','dashboard\app.py') -PassThru -NoNewWindow -WorkingDirectory $PROJECT -RedirectStandardOutput $dashboardLog -RedirectStandardError "$KS_LOG_DIR\dashboard_err.log"
Write-Host ('    Dashboard PID: ' + $dashboardProc.Id) -ForegroundColor DarkGray
$dashboardProc.Id | Out-File "$KS_LOG_DIR\dashboard.pid" -Encoding ascii
Start-Sleep -Seconds 4
if (-not $dashboardProc.HasExited) {
    Write-Host '    [OK] Dashboard running — http://127.0.0.1:8080/' -ForegroundColor Green
} else {
    Write-Host '    [ERR] Dashboard exited — see dashboard_err.log' -ForegroundColor Red
}

# ============= 5. 浏览器 + 总结 =============
Write-Host ''
Write-Host '[4/5] Opening browser...' -ForegroundColor Yellow
Start-Process 'http://127.0.0.1:8080/' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Write-Host '    ok' -ForegroundColor Green

Write-Banner '[OK] System started — live log monitoring below'
Write-Host ''
Write-Host '  Hermes LLM:  http://127.0.0.1:8642/v1           (Codex gpt-5.4)' -ForegroundColor Cyan
Write-Host '  Dashboard:   http://127.0.0.1:8080/' -ForegroundColor Cyan
Write-Host '  Autopilot:   running, cycle every 60s' -ForegroundColor Cyan
Write-Host ''
Write-Host '  Logs (tailed below):' -ForegroundColor DarkGray
Write-Host ('    [H] ' + $hermesStdout) -ForegroundColor DarkGray
Write-Host ('    [A] ' + $autopilotLog) -ForegroundColor DarkGray
Write-Host ('    [D] ' + $dashboardLog) -ForegroundColor DarkGray
Write-Host ''
Write-Host '  Press Ctrl+C to stop tailing (processes keep running).' -ForegroundColor Yellow
Write-Host '  Stop all: powershell -File D:\ks_automation\stop_ks_all.ps1' -ForegroundColor Yellow
Write-Host ''
Write-Banner '[LIVE] real-time logs — H=Hermes  A=Autopilot  D=Dashboard'

# ============= 6. Live tail with color coding =============
# 用 Start-Job 并行 tail 3 个 log, 主循环 Receive-Job
$jobs = @()
$jobs += Start-Job -Name 'hermes' -ArgumentList $hermesStdout -ScriptBlock {
    param($f)
    if (-not (Test-Path $f)) { New-Item -ItemType File -Path $f -Force | Out-Null }
    Get-Content -Path $f -Wait -Tail 10
}
$jobs += Start-Job -Name 'autopilot' -ArgumentList $autopilotLog -ScriptBlock {
    param($f)
    if (-not (Test-Path $f)) { New-Item -ItemType File -Path $f -Force | Out-Null }
    Get-Content -Path $f -Wait -Tail 20
}
$jobs += Start-Job -Name 'dashboard' -ArgumentList $dashboardLog -ScriptBlock {
    param($f)
    if (-not (Test-Path $f)) { New-Item -ItemType File -Path $f -Force | Out-Null }
    Get-Content -Path $f -Wait -Tail 5
}

try {
    while ($true) {
        foreach ($j in $jobs) {
            $out = Receive-Job -Job $j -ErrorAction SilentlyContinue
            if ($out) {
                foreach ($line in @($out)) {
                    $ts = (Get-Date).ToString('HH:mm:ss')
                    switch ($j.Name) {
                        'hermes'    { Write-Host ('[' + $ts + '][H] ' + $line) -ForegroundColor Magenta }
                        'autopilot' {
                            $c = 'White'
                            if ($line -match 'ERROR|FAIL|Traceback|Exception') { $c = 'Red' }
                            elseif ($line -match 'WARN|warning') { $c = 'Yellow' }
                            elseif ($line -match 'cycle #|✅|OK|started') { $c = 'Green' }
                            Write-Host ('[' + $ts + '][A] ' + $line) -ForegroundColor $c
                        }
                        'dashboard' { Write-Host ('[' + $ts + '][D] ' + $line) -ForegroundColor Cyan }
                    }
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }
} finally {
    foreach ($j in $jobs) { Stop-Job -Job $j -ErrorAction SilentlyContinue; Remove-Job -Job $j -Force -ErrorAction SilentlyContinue }
    Write-Host ''
    Write-Host '[tail stopped — backend processes still running]' -ForegroundColor Yellow
    Write-Host '  Stop all: powershell -File D:\ks_automation\stop_ks_all.ps1' -ForegroundColor Yellow
}
