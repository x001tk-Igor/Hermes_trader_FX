# FX AI trader environment (v3)

## Account / terminal
- MT5 login **YOUR_MT5_LOGIN** (set in .env), server RoboForex-Pro, currency USD
- Terminal: non-`_BIN` install
  - exe: `C:\Program Files\RoboForex MT5 Terminal\terminal64.exe`
  - data-dir hash: `5FFA568149E88FCD5B44D926DCFEAA79`
- trade.py: `py -3 ./tools/trade.py <cmd> --terminal "C:/Program Files/RoboForex MT5 Terminal/terminal64.exe"`
- **Scope: ONLY the account in .env. Do NOT touch other accounts.**

## Instruments (v3 — 6 FX pairs, all TREND)
| Instrument | Regime | Window UTC | Digits | Contract |
|---|---|---|---|---|
| EURUSD | TREND | 06:00-22:00 | 5 | 100000 |
| GBPUSD | TREND | 06:00-22:00 | 5 | 100000 |
| USDCAD | TREND | 06:00-22:00 | 5 | 100000 |
| EURGBP | TREND | 06:00-22:00 | 5 | 100000 |
| NZDCAD | TREND | 06:00-22:00 | 5 | 100000 |
| EURAUD | TREND | 06:00-22:00 | 5 | 100000 |

## Averaging system (v3)
- 3 positions per symbol max (1 main + 2 addons)
- Addons at -1×ATR and -2×ATR from main entry
- Per-position SL = 1.5×ATR
- TP = weighted_avg + 0.5×ATR
- DD stop: 1.7% equity per symbol
- Lot: (equity × 1.7%) / (3 × 1.5×ATR × contract)

## Backtest results (2026-08-02, H1, 1 year, with averaging)
| Pair | PF | WR | PnL ($100K) |
|---|---|---|---|
| EURUSD | 1.81 | 82.6% | +$190K |
| GBPUSD | 1.77 | 82.5% | +$178K |
| USDCAD | 1.69 | 83.1% | +$162K |
| EURGBP | 1.63 | 82.2% | +$148K |
| NZDCAD | 1.60 | 82.2% | +$139K |
| EURAUD | 1.57 | 81.5% | +$137K |

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