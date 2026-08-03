---
name: xau-ai-trader
description: "Use when running the autonomous intraday AI trader on MetaTrader5 — the recurring cron trade cycle during the 06:00–22:00 UTC window, or when the user asks to run a trade cycle / check the trader / manage open positions. v3: 6 FX pairs (EURUSD, GBPUSD, USDCAD, EURGBP, NZDCAD, EURAUD), all TREND regime, averaging-down system (3 positions per symbol). T_EMA tactic (EMA20 vs EMA200 + ADX>20). Risk: 1.7% max per symbol with averaging, 3% daily, 5% weekly, 5% max DD. Executed via trade.py with --terminal."
---

# xau-ai-trader — автономный ИИ-трейдер FX (v3)

Торговая конституция: `constitution/Qwen_markdown_Ai_trader_XAU.md` (внутри проекта)
Выжимка хард-чисел — `tools/hard_limits.md`. При конфликте полный регламент старше.

## Счёт и терминал (см. `tools/env.md`)
- MT5 login **YOUR_MT5_LOGIN** (set in .env), RoboForex-Pro, USD
- Терминал: non-`_BIN` install → `C:\Program Files\RoboForex MT5 Terminal\terminal64.exe`
- trade.py: `py -3 tools/trade.py <cmd> --terminal "C:/Program Files/RoboForex MT5 Terminal/terminal64.exe"`

## Инструменты (v3 — backtest 2026-08-02)
6 FX пар, все TREND regime с усреднением:
- EURUSD, GBPUSD, USDCAD, EURGBP, NZDCAD, EURAUD
- Tactic: T_EMA (EMA20 vs EMA200 on H1 + ADX(14)>20)
- PF 1.57-1.81 с усреднением (1 год backtest, $100K equity)
- NO JPY, NO XAUUSD (unviable with averaging)

## Усреднение (v3 — key change)
- Max 3 позиции на символ: 1 main + 2 addons
- Addon 1: -1.0×ATR от main entry
- Addon 2: -2.0×ATR от main entry
- Каждая позиция: свой SL = 1.5×ATR от своего entry
- TP = weighted_avg + 0.5×ATR (пересчёт после каждого addon)
- DD stop: суммарный убыток ≥ 2.5% equity → close all
- Lot = (equity × 2.5%) / (3 × 1.5×ATR × contract)

## ⚠️ Два жёстких факта
1. Крон — в ЛОКАЛЬНОМ времени машины. Машина в UTC.
2. Крон стреляет только пока процесс агента открыт. На ЛЮБОМ запуске —
   ПЕРВЫМ делом resume-шаг 0.

## Шаг 0. Resume — на любом запуске
1. `py -3 tools/state.py gate` немедленно.
2. Если `NEW_TRADES_OK` и в окне 06:00–22:00 UTC → выполни цикл loop.md.
3. Если `FORCE_FLAT` → закрой всё + alert. Если `HALT_NEW` → только управление.
4. `py -3 tools/state.py dd-monitor` — проверка DD stop по всем символам.

## Цикл (см. `tools/loop.md` — детально)
1. Window gate — `state.py gate`
2. Calendar blackout — `calendar.py today`
3. Market scan — `state.py market [SYM]` (bid/ask/spread/EMA/ADX/ATR)
4. T_EMA signal — EMA20 vs EMA200 + ADX>20 на H1 (код, не модель)
5. Size — `position_size.py --avg-mode --equity E --max-loss-pct 1.7 --atr A --contract-size C`
6. Execute — `trade.py open --symbol S --side ... --lot L --sl SL --tp TP --terminal ...`
7. Addon — если цена -1×ATR → addon 1; -2×ATR → addon 2. `trade.py avg-tp --symbol S` после.
8. DD check — `state.py avg-risk --symbol S --equity E` каждый цикл
9. TP/SL — TP на всех позициях, SL индивидуальный
10. Journal — `journal.py add` (action=OPEN/ADDON/SL_HIT/DD_STOP/CLOSE)

## Уведомления
Дневной отчёт + тревоги при: DD stop, daily 3%, weekly 5%, spread аномалия,
execution error, all-positions-closed. Не докладывать про каждую сделку.

## Каданс (cron-поля в UTC — машина в UTC)
- цикл: `1,16,31,46 6-21 * * 1-5` = 06:01–21:46 UTC (каждые 15 мин)
- pre-market: `50 5 * * 1-5` = 05:50 UTC
- daily report: `33 22 * * 1-5` = 22:33 UTC
Шаблон: `tools/cron_template.txt`.

## Запрещено
4-й addon • увеличивать lot на addon • расширять SL • martingale (doubling) •
торговать JPY/XAUUSD • перенос через выходные • торговля без SL •
игнорировать DD stop • изменять конституцию без разрешения.