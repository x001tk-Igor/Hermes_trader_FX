# Hermes Trader Hourly Wake — будит агента в текущей сессии
# Запускается Task Scheduler каждый час 05:00-20:00 UTC

$ErrorActionPreference = "Stop"

$workDir = "$env:USERPROFILE\.claude\skills\xau-ai-trader"
$hermes = "$env:USERPROFILE\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe"
$python = "py"

Set-Location $workDir

# Run gate check
$gateOutput = & $python tools\state.py gate 2>&1 | Out-String

# Wake Hermes agent — continue current session (not create new one)
$prompt = @"
Торговый цикл. Выполни ПОЛНЫЙ цикл по loop.md (7 шагов, не пропускать):
1. Gate (результат ниже)
2. News: py -3 tools/calendar.py symbols
3. Macro: py -3 tools/state.py market + DXY/yields/risk sentiment
4. Regime: определи режим по каждой паре
5. Setup: ищи конкретный ценовой паттерн (не 'EMA cross')
6. Confluence + EV: минимум 4/6 confluence, EV >= +0.25R
7. Execute: открой только если ВСЕ шаги пройдены. Управляй существующими позициями (addon, DD, TP).
ОБЯЗАТЕЛЬНО отправь отчёт в Telegram после цикла (даже если нет сделки).
Gate результат:
$gateOutput
Помни: НЕТ СДЕЛКИ БЕЗ ПОЛНОГО АНАЛИЗА.
"@

# --continue: resume most recent session (wake current agent, not create new)
# --max-turns 10: limit tool calls per wake
# --yolo: skip approval prompts (non-interactive)
& $hermes chat -q $prompt --continue --max-turns 10 --yolo --cli 2>&1 | Out-Null