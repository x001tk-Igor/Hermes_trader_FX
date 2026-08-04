# Hermes Trader Hourly Cycle — runs via Windows Task Scheduler
# Wakes Hermes agent for full constitution-compliant trade cycle

$ErrorActionPreference = "Stop"

$workDir = "$env:USERPROFILE\.claude\skills\xau-ai-trader"
$hermes = "$env:USERPROFILE\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe"
$python = "py"

Set-Location $workDir

# Run gate check
$gateOutput = & $python tools\state.py gate 2>&1 | Out-String

# Wake Hermes agent with full cycle instruction, max 5 turns, timeout 8 min
$prompt = @"
Торговый цикл. Выполни ПОЛНЫЙ цикл по loop.md (7 шагов, не пропускать):
1. Gate (результат ниже)
2. News: py -3 tools/calendar.py symbols
3. Macro: py -3 tools/state.py market + DXY/yields/risk sentiment
4. Regime: определи режим по каждой паре
5. Setup: ищи конкретный ценовой паттерн (не 'EMA cross')
6. Confluence + EV: минимум 4/6 confluence, EV >= +0.25R
7. Execute: открой только если ВСЕ шаги пройдены. Управляй существующими позициями.
ОБЯЗАТЕЛЬНО отправь отчёт в Telegram после цикла (даже если нет сделки).
Gate результат:
$gateOutput
Помни: НЕТ СДЕЛКИ БЕЗ ПОЛНОГО АНАЛИЗА.
"@

& $hermes chat -q $prompt --max-turns 10 --yolo 2>&1 | Out-Null