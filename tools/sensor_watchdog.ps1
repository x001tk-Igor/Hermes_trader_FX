# Trade Sensor Watchdog — проверяет живость датчика каждые 5 минут.
# По образу ai-trader-skillset/scripts/sensor_watchdog.ps1
#
# Проверяет НЕ "жив ли процесс", а "идёт ли работа":
# 1. Процесс существует?
# 2. Heartbeat свежий?
# 3. walls_checked = true (считает ли стены)?
#
# Регистрация:
# schtasks /Create /TN "TradeSensorWatchdog" /SC MINUTE /MO 5 /RL HIGHEST /F ^
#   /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\<USER>\.claude\skills\xau-ai-trader\tools\sensor_watchdog.ps1"

$ErrorActionPreference = "Stop"

$StateDir   = "$env:USERPROFILE\.claude\skills\xau-ai-trader\tools"
$Heartbeat  = Join-Path $StateDir "sensor_heartbeat.json"
$Python     = "py"
$Sensor     = "$env:USERPROFILE\.claude\skills\xau-ai-trader\tools\trade_sensor.py"
$WatchLog   = Join-Path $StateDir "watchdog.log"
$Hermes     = "$env:USERPROFILE\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe"

$StaleSeconds = 60

function Write-Log([string]$msg) {
    $line = "{0:yyyy-MM-dd HH:mm:ss}Z  {1}" -f (Get-Date).ToUniversalTime(), $msg
    Add-Content -Path $WatchLog -Value $line -Encoding utf8
}

function Restart-Sensor([string]$why) {
    Write-Log "ПЕРЕЗАПУСК: $why"
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*trade_sensor*" } |
        ForEach-Object {
            Write-Log "  снимаю старый PID $($_.ProcessId)"
            try { Stop-Process -Id $_.ProcessId -Force } catch {}
        }
    Start-Sleep -Seconds 2
    $p = Start-Process -FilePath $Python -ArgumentList $Sensor `
        -RedirectStandardOutput (Join-Path $StateDir "sensor_stdout.log") `
        -RedirectStandardError  (Join-Path $StateDir "sensor_stderr.log") `
        -WindowStyle Hidden -PassThru
    Write-Log "  поднят PID $($p.Id)"
}

# --- проверка ---

# 1. Процесс существует?
$alive = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
           Where-Object { $_.CommandLine -like "*trade_sensor*" })
if ($alive.Count -eq 0) {
    Restart-Sensor "процесса датчика нет"
    exit 0
}
if ($alive.Count -gt 1) {
    Restart-Sensor "датчиков запущено $($alive.Count) — должен быть один"
    exit 0
}

# 2. Heartbeat файл существует?
if (-not (Test-Path $Heartbeat)) {
    Restart-Sensor "файла пульса нет"
    exit 0
}

# 3. Heartbeat парсится?
try {
    $hb = Get-Content $Heartbeat -Raw -Encoding utf8 | ConvertFrom-Json
} catch {
    Restart-Sensor "пульс не разбирается: $($_.Exception.Message)"
    exit 0
}

# 4. Heartbeat свежий?
$age = ((Get-Date).ToUniversalTime() - [datetime]::Parse($hb.ts).ToUniversalTime()).TotalSeconds
if ($age -gt $StaleSeconds) {
    Restart-Sensor ("пульс протух: {0:N0} с при пороге {1} с" -f $age, $StaleSeconds)
    exit 0
}

# 5. walls_checked = true?
if ($hb.walls_checked -ne $true) {
    Restart-Sensor ("пульс свежий ({0:N0} с), но стены НЕ считаются" -f $age)
    exit 0
}

# Всё хорошо — тишина
exit 0