# Hermes Trader Hourly Cycle — runs via Windows Task Scheduler
# Executes trade cycle and pokes Hermes agent to wake up

$ErrorActionPreference = "Stop"

# Run the cycle script
$cycleScript = "$env:USERPROFILE\.claude\skills\xau-ai-trader\tools\auto_cycle.py"
$python = "py"
$workDir = "$env:USERPROFILE\.claude\skills\xau-ai-trader"

# Execute cycle
Set-Location $workDir
& $python $cycleScript 2>&1 | Out-File -FilePath "$workDir\tools\last_cycle.log" -Encoding utf8

# Wake Hermes agent with cycle results
$logContent = Get-Content "$workDir\tools\last_cycle.log" -Raw
$shortLog = $logContent.Substring(0, [Math]::Min(500, $logContent.Length))

& hermes chat -q "Торговый цикл выполнен. Результаты: $shortLog`nПроверь позиции, открой addon'ы если нужно, отправь отчёт в Telegram. После завершения назначь следующий цикл через cronjob на +1 час." 2>&1 | Out-Null