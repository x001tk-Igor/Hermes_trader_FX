# Hermes Trader Hourly Cycle — runs via Windows Task Scheduler
# Wakes Hermes agent for full constitution-compliant trade cycle

$ErrorActionPreference = "Stop"

$workDir = "$env:USERPROFILE\.claude\skills\xau-ai-trader"

# Run state check first
Set-Location $workDir
$gateOutput = & py -3 tools\state.py gate 2>&1 | Out-String

# Wake Hermes agent with gate results and full cycle instruction
$prompt = @"
Торговый цикл. Выполни ПОЛНЫЙ цикл по loop.md (7 шагов, не пропускать):
1. Gate (уже выполнен, результат ниже)
2. News: py -3 tools/calendar.py symbols
3. Macro: py -3 tools/state.py market + DXY/yields/risk sentiment
4. Regime: определи режим по каждой паре
5. Setup: ищи конкретный ценовой паттерн (не 'EMA cross')
6. Confluence + EV: минимум 4/6 confluence, EV >= +0.25R
7. Execute: открой только если ВСЕ шаги пройдены. Управляй существующими позициями (addon, DD, TP).

Gate результат:
$gateOutput

Помни: НЕТ СДЕЛКИ БЕЗ ПОЛНОГО АНАЛИЗА. 'Нет сделки' — это решение.
Отправь краткий отчёт в Telegram после цикла.
"@

& hermes chat -q $prompt 2>&1 | Out-Null