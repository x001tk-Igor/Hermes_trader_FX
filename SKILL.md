---
name: xau-ai-trader
description: "Use when running the autonomous intraday AI trader on MetaTrader5 — the recurring cron trade cycle during the 06:00–22:00 UTC window, or when the user asks to run a trade cycle / check the trader / manage open positions. v4: 6 FX pairs (EURUSD, GBPUSD, USDCAD, EURGBP, NZDCAD, EURAUD), all TREND regime, averaging-down system (3 positions per symbol). Full constitution-compliant cycle: limits → news → macro/bias → regime → setup → confluence/EV → execute. T_EMA/trend pullback/London breakout/NY macro/range reversion/liquidity sweep tactics. Risk: 2.5% max per symbol with averaging, 3% daily, 5% weekly, 5% max DD. Max 3 instruments open simultaneously. Executed via trade.py with --terminal."
---

# xau-ai-trader — автономный ИИ-трейдер FX (v4)

Торговая конституция: `constitution/Qwen_markdown_Ai_trader_XAU.md`
Выжимка хард-чисел — `tools/hard_limits.md`. При конфликте полный регламент старше.

## Счёт и терминал
- MT5 login **YOUR_MT5_LOGIN** (set in .env), RoboForex-Pro, USD
- Терминал: `C:\Program Files\RoboForex MT5 Terminal\terminal64.exe`
- trade.py: `py -3 tools/trade.py <cmd> --terminal "C:/Program Files/RoboForex MT5 Terminal/terminal64.exe"`

## Инструменты (v4 — 6 FX пар)
EURUSD, GBPUSD, USDCAD, EURGBP, NZDCAD, EURAUD — все TREND regime с усреднением.

## Усреднение (v3)
- Max 3 позиции на символ: 1 main + 2 addons (-1×ATR, -2×ATR)
- Каждая позиция: свой SL = 2.5×ATR
- TP = weighted_avg + 0.5×ATR (пересчёт после addon)
- DD stop: 2.5% equity per symbol → close all
- Lot = (equity × 2.5%) / (3 × 2.5×ATR × contract) / 2 (safety divisor)
- Max 3 инструмента одновременно (без учёта addon'ов)

## ⚠️ Главное правило v4
**НЕТ СДЕЛКИ БЕЗ ПОЛНОГО АНАЛИЗА.**

Цикл = 7 шагов, НЕ пропускать:
1. Gate (лимиты)
2. News (blackout)
3. Macro + bias (DXY, yields, risk, session)
4. Regime (TREND/RANGE/BREAKOUT/UNCLEAR)
5. Setup (конкретный ценовой паттерн, не "EMA cross")
6. Confluence (≥4/6) + EV (≥+0.25R)
7. Execute + manage

"Нет сделки — это торговое решение." Лучше пропустить 10 циклов, чем открыть сделку вслепую.

## Шаг 0. Resume
1. `py -3 tools/state.py gate` — проверить лимиты
2. Если NEW_TRADES_OK → полный цикл loop.md
3. Если HALT_NEW → только управление (шаг 7)
4. Если FORCE_FLAT → закрыть всё

## Цикл (см. `tools/loop.md` — детально)
Каждый час на :00 UTC:
1. Gate → 2. News → 3. Macro/bias → 4. Regime → 5. Setup → 6. Confluence/EV → 7. Execute

## Каданс
- Цикл: каждый час на :00 UTC (06:00-22:00, пн-пт)
- Pre-market: 05:50 UTC
- Daily report: 22:33 UTC
- DD monitor: auto_cycle.py (фоновый процесс, каждые 5 мин, только DD stop)

## Запрещено
Открывать сделку без macro анализа • открывать без regime определения •
открывать без setup • открывать без confluence ≥ 4 • открывать без EV ≥ +0.25R •
превышать 3 инструмента одновременно • 4-й addon • расширять SL •
торговать JPY/XAUUSD • торговать перед новостями • игнорировать DD stop