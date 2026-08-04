# FX AI trader environment (v4)

## Account / terminal
- MT5 login **YOUR_MT5_LOGIN** (set in .env), server RoboForex-Pro, currency USD
- Terminal: `C:\Program Files\RoboForex MT5 Terminal\terminal64.exe`
- trade.py: `py -3 ./tools/trade.py <cmd> --terminal "C:/Program Files/RoboForex MT5 Terminal/terminal64.exe"`
- **Scope: ONLY the account in .env. Do NOT touch other accounts.**

## Instruments (v4 — 6 FX pairs, NO XAUUSD)
- EURUSD, GBPUSD, USDCAD, EURGBP, NZDCAD, EURAUD
- Contract: 100,000 for all FX pairs
- Digits: 5 for all pairs
- Window: 05:00-20:00 UTC (all pairs)
- XAUUSD permanently excluded — averaging unprofitable on gold

## Tactics (v4 — 10 primary + 2 reserve)
- All backtested H1 with averaging-down on 6 FX pairs
- See hard_limits.md for full list and backtest results
- TREND: C1 TrendPullback, S1 EMA_VWAP, S2 GoldScalper, S3 200EMA_UTBot, S4 MadCharts, S8 SmartTrend
- BREAKOUT: S7 GateBreaker (London), S6 NY_ORB (NY)
- RANGE: C2 RangeReversion, C3 RSI+BB (reserve)
- REVERSAL: C4 LiquiditySweep (reserve), S5 UTBot_STC (reserve)

## Averaging
- 3 positions max per symbol (main + 2 addons at -1/-2×ATR)
- SL = 2.5×ATR per position
- TP = weighted_avg + 0.5×ATR (recalculated after addon)
- DD stop: 2.5% equity per symbol
- Lot = (equity × 2.5%) / (3 × 2.5×ATR × contract) / 2 (safety divisor)
- Max 3 instruments open simultaneously

## Risk limits
- Daily loss: 3% → halt new trades
- Weekly loss: 5% → halt to end of week
- Max DD from peak: 5% → force flat
- Max 8 new entries per day
- Friday: no new entries after 19:00 UTC, close ALL by 19:30

## Cycle
- 7-step mandatory: gate → news → macro/bias → regime → setup → confluence/EV → execute
- Hourly at :00 UTC, 05:00-20:00 window
- auto_cycle.py = DD MONITOR ONLY (no trading decisions)
- Task Scheduler: HermesTraderCycle, hourly 05-20 UTC

## .env variables
- MT5_TERMINAL_PATH, MT5_LOGIN, MT5_SERVER
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PROXY (optional)