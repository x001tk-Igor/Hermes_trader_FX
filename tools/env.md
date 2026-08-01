# XAU AI trader environment

## Account / terminal
- MT5 login **YOUR_MT5_LOGIN** (set in .env), server RoboForex-Pro, currency USD, leverage 1:1000
- Terminal: **non-`_BIN`** install
  - exe: `C:\Program Files\RoboForex MT5 Terminal\terminal64.exe`
  - data-dir hash: `5FFA568149E88FCD5B44D926DCFEAA79`
- `account_info().trade_mode == 0` → server REAL, **user confirmed: demo/paper money**.
- trade.py: `py -3 ./tools/trade.py <cmd> --terminal "C:/Program Files/RoboForex MT5 Terminal/terminal64.exe"`
  (Old `~/.claude/skills/mt5-manual-trading/tools/trade.py` DELETED. Use `--terminal`, NOT `--hash` — hash lookup broken.)
- **Scope: ONLY the account in .env. Do NOT touch other accounts / their crons / their skills.**

## Instruments and assigned regimes (yearly backtest 2026-07-31)
| Instrument | Regime | Window UTC | Digits | Contract |
|---|---|---|---|---|
| XAUUSD | TREND | 07:00-20:00 | 2 | 100 oz |
| EURUSD | COUNTER | 06:00-22:00 | 5 | 100000 |
| USDJPY | TREND | 06:00-22:00 | 3 | 100000 |
| USDCAD | TREND | 06:00-22:00 | 5 | 100000 |
| GBPJPY | TREND | 06:00-22:00 | 3 | 100000 |

## Python
- `py -3` (Python 3.13). `MetaTrader5` 5.0.5735.
- tools run from `~/.claude/skills/xau-ai-trader/tools/`

## Calendar source
- ForexFactory JSON: `https://nfs.faireconomy.media/ff_calendar_thisweek.json`
  and `..._nextweek.json`. Fetched locally. Times US-local → calendar.py converts to UTC.

## Time base
- Machine is UTC (Windows TimeZoneKeyName="UTC"). `date -u` == `date`.
- MT5 tick.time is SERVER time (EET=UTC+3 summer), not UTC.
- Friday: no new entries after 19:00 UTC, close all by 19:30 UTC (all instruments).