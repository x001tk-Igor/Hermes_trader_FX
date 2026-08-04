# Hermes Trader FX — Autonomous MT5 Trading System v4

Autonomous AI trader for MetaTrader5, running as a Hermes Agent skill.
Trades 6 FX pairs with a 3-position averaging-down system and 10 primary tactics (all backtested).

## Quick Start

### Prerequisites
- Windows with MetaTrader5 terminal installed and logged in
- Python 3.11+ with `MetaTrader5` package (`pip install MetaTrader5`)
- Hermes Agent (or any AI agent that supports skills + tool calling)

### Installation
```bash
# 1. Clone this repo into your Hermes skills directory
git clone https://github.com/x001tk-Igor/Hermes_trader_FX.git
cp -r Hermes_trader_FX ~/.claude/skills/xau-ai-trader

# 2. Copy .env.example to .env and fill in your values
cp skills/xau-ai-trader/.env.example skills/xau-ai-trader/.env
# Edit .env: MT5_TERMINAL_PATH, MT5_LOGIN, MT5_SERVER, TELEGRAM_BOT_TOKEN, etc.

# 3. Verify MT5 connection
py -3 skills/xau-ai-trader/tools/state.py gate

# 4. Run a market scan
py -3 skills/xau-ai-trader/tools/state.py market
```

## Instruments (v4 — 6 FX pairs only, NO XAUUSD)

| Pair | Contract | Window UTC |
|------|----------|------------|
| EURUSD | 100,000 | 05:00-20:00 |
| GBPUSD | 100,000 | 05:00-20:00 |
| USDCAD | 100,000 | 05:00-20:00 |
| EURGBP | 100,000 | 05:00-20:00 |
| NZDCAD | 100,000 | 05:00-20:00 |
| EURAUD | 100,000 | 05:00-20:00 |

**XAUUSD permanently excluded** — averaging-down is unprofitable on gold (all 12 strategies tested, all lose with averaging).

## Averaging-Down System

- Max 3 positions per symbol: 1 main + 2 addons
- Addon 1 at -1.0xATR, Addon 2 at -2.0xATR from main entry
- Each position: own SL = 2.5xATR from its own entry
- TP = weighted_average + 0.5xATR (recalculated after each addon)
- DD stop: total loss >= 2.5% equity per symbol -> close all
- Lot = (equity x 2.5%) / (3 x 2.5xATR x contract) / 2 (safety divisor)
- Max 3 instruments open simultaneously (excluding addons)
- Daily loss limit: 3% | Weekly: 5% | Max DD: 5%

## Tactic Arsenal (10 primary + 2 reserve, all backtested H1)

### TREND (4 primary)
| # | Tactic | Source | Trigger | PF | PnL |
|---|--------|--------|---------|-----|-----|
| C1 | Trend Pullback | Constitution | EMA20>EMA200, pullback to EMA20, trigger candle | 2.67 | +$144K |
| S1 | EMA 9 + VWAP | TradingView | EMA9 crosses session VWAP | 2.63 | +$120K |
| S2 | Gold Scalper | TradingView | EMA9/18 trend + RSI pullback / momentum breakout | 2.68 | +$107K |
| S3 | 200 EMA + UT Bot + ADX | TradingView | HTF 200 EMA + UT Bot flip + ADX>25 (3-layer) | 2.60 | +$46K |

### SESSION BREAKOUT (2 primary)
| # | Tactic | Source | Trigger | PF | PnL |
|---|--------|--------|---------|-----|-----|
| S7 | Gate Breaker | TradingView | Tokyo range -> London body break | 3.71 | +$121K |
| S6 | NY ORB | TradingView | 13:00-14:00 UTC OR + breakout + volume + compression | 3.73 | +$65K |

### RANGE / MEAN REVERSION (1 primary + 1 reserve)
| # | Tactic | Source | Trigger | PF | PnL |
|---|--------|--------|---------|-----|-----|
| C2 | Range Reversion | Constitution | ADX<20, 2+ boundary tests, rejection candle | 11.45 | +$36K |
| C3 | RSI + BB (reserve) | Constitution | Close beyond BB(20,2) + RSI extreme + RSI turn | inf | +$6.8K |

### TREND ENHANCED (2 primary)
| # | Tactic | Source | Trigger | PF | PnL |
|---|--------|--------|---------|-----|-----|
| S4 | MadCharts Baseline | TradingView | 50 EMA/SMA area + 9/18 EMA + close above fast EMAs | 3.17 | +$43K |
| S8 | Smart Trend | TradingView | EMA trend + ADX rising + BOS (5-bar high break) | 2.35 | +$43K |

### REVERSAL (2 reserve)
| # | Tactic | Source | Trigger | PF | PnL |
|---|--------|--------|---------|-----|-----|
| C4 | Liquidity Sweep (reserve) | Constitution | False breakout PDH/PDL + 13 EMA cross + 3-candle confirm | inf | +$2.6K |
| S5 | UT Bot + STC (reserve) | TradingView | UT Bot flip + STC extreme + 5-layer guard stack | 6.22 | +$30K |

## Backtest Results (H1, 1 year, 6 FX pairs, averaging mode)

All 12 tactics profitable with averaging on FX. All lose without averaging.
All lose on XAUUSD with averaging. XAUUSD excluded.

| Tactic | EURUSD | GBPUSD | USDCAD | EURGBP | NZDCAD | EURAUD | Total |
|--------|--------|--------|--------|--------|--------|--------|-------|
| C1 TrendPullback | +$17K | +$23K | +$23K | +$56K | +$17K | +$8K | +$144K |
| S7 GateBreaker | +$19K | +$29K | +$21K | +$26K | +$10K | +$18K | +$121K |
| S1 EMA_VWAP | +$21K | +$25K | +$12K | +$29K | +$8K | +$4K | +$120K |
| S2 GoldScalper | +$7K | +$19K | +$29K | +$30K | +$12K | +$12K | +$107K |
| S6 NY_ORB | +$11K | +$11K | +$15K | +$7K | +$5K | +$6K | +$65K |
| S3 200EMA_UTBot | +$8K | +$8K | +$9K | +$14K | +$2K | +$5K | +$46K |
| S4 MadCharts | +$5K | +$6K | +$6K | +$21K | +$2K | +$2K | +$43K |
| S8 SmartTrend | +$9K | +$4K | +$7K | +$11K | +$4K | +$9K | +$43K |
| S5 UTBot_STC | +$9K | +$3K | +$6K | +$6K | +$5K | +$1K | +$30K |
| C2 RangeReversion | +$2K | +$5K | +$8K | +$13K | +$5K | +$2K | +$36K |

## 7-Step Mandatory Cycle (no step may be skipped)

1. **Gate** — `state.py gate` (hard limits, daily loss, DD, positions)
2. **News** — `calendar.py symbols` (blackout check, 6 currencies)
3. **Macro + Bias** — `state.py market` + DXY/yields/risk/session + bias per pair
4. **Regime** — TREND/RANGE/BREAKOUT/UNCLEAR per pair (agent analysis)
5. **Setup** — specific tactic match (not "EMA cross = enter")
6. **Confluence + EV** — 6-factor score >= 4/6, EV >= +0.25R
7. **Execute** — only if ALL steps pass. Journal + Telegram.

**"No trade" is a valid decision.** Better to skip 10 cycles than open one blind trade.

## Architecture

```
xau-ai-trader/
├── SKILL.md              # v4 skill description + 7-step cycle
├── README.md             # this file
├── .env.example          # template (real .env is gitignored)
├── .gitignore
├── constitution/
│   └── Qwen_markdown_Ai_trader_XAU.md  # full trading constitution
├── tools/
│   ├── auto_cycle.py     # DD MONITOR ONLY (no trading decisions)
│   ├── state.py          # gate, positions, market, dd-monitor, avg-positions, avg-risk
│   ├── trade.py          # open, close, close-symbol, sltp, avg-tp
│   ├── position_size.py  # lot calc with --avg-mode + lot halving
│   ├── calendar.py       # economic calendar (6 currencies, symbol mapping)
│   ├── journal.py        # trade journal with averaging fields
│   ├── xau_env.py        # config: 6 pairs, AVERAGING_CONFIG, windows
│   ├── hard_limits.md    # v4 risk limits + full tactic list
│   ├── loop.md           # 7-step cycle playbook
│   ├── env.md            # environment setup guide
│   ├── cron_template.txt # cron schedule template
│   ├── wake_cycle.ps1    # Task Scheduler wake script (hourly)
│   ├── backtest_tactics.py      # original 10-tactic backtest engine
│   ├── tv_backtest_h1.py        # 9 TradingView strategies H1 screening
│   ├── tv_backtest_m15.py       # 8 TradingView strategies M15 detailed
│   ├── constitution_backtest_h1.py  # 4 constitution tactics H1
│   ├── sim_averaging.py         # averaging simulator v1
│   ├── sim_averaging_v2.py      # averaging simulator v2 (per-pos SL + DD)
│   ├── sim_acceleration.py      # Position Acceleration research (rejected)
│   ├── cross_pair_study.py      # 30-instrument study
│   └── tg_notify.py             # Telegram notification helper
```

## Key Design Decisions

1. **Averaging-down, not Position Acceleration** — tested both, averaging wins on H1 FX (87% recovery rate)
2. **XAUUSD excluded** — averaging kills on gold (all 12 strategies unprofitable)
3. **Lot halved (/2)** — multiple instruments open = total risk must stay < 4%
4. **auto_cycle.py = DD MONITOR ONLY** — agent does ALL analysis, script only protects against drawdown
5. **7-step mandatory cycle** — no trade without full analysis (gate -> news -> macro -> regime -> setup -> confluence -> EV -> execute)
6. **Max 3 instruments simultaneously** — portfolio risk management
7. **H1 timeframe** — better than M15 for most strategies (M15 tested, H1 wins)

## License

Personal use. Not financial advice. Trade at your own risk.