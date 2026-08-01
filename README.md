# AI Trader — Autonomous Multi-Instrument MT5 Trading System

Autonomous AI trader for MetaTrader5, designed to run as a Hermes Agent skill.
Trades 5 instruments with assigned regimes (trend-following or counter-trend),
based on a yearly backtest. Enforces a strict trading constitution with risk
management, news blackouts, spread filters, and real-time price alerts.

## Quick Start

### Prerequisites
- Windows with MetaTrader5 terminal installed and logged in
- Python 3.11+ with `MetaTrader5` package (`pip install MetaTrader5`)
- Hermes Agent (or any AI agent that supports skills + tool calling)

### Installation
```bash
# 1. Clone this repo into your Hermes skills directory
git clone https://github.com/YOUR_USERNAME/ai-trader.git
cp -r ai-trader ~/.hermes/skills/  # or ~/.claude/skills/ for Claude Code

# 2. Copy .env.example to .env and fill in your values
cp skills/ai-trader/.env.example skills/ai-trader/.env
# Edit .env: MT5_TERMINAL_PATH, MT5_LOGIN, MT5_SERVER, TELEGRAM_BOT_TOKEN, etc.

# 3. Verify MT5 connection
py -3 skills/ai-trader/tools/state.py gate

# 4. Run a scan
py -3 skills/ai-trader/tools/cycle_multi.py
```

## Instruments and Assigned Regimes

Assigned by yearly H1 backtest (with spread costs). Each instrument trades
ONLY in its assigned regime — no mixing.

| Instrument | Regime | Window UTC | Tactics |
|---|---|---|---|
| XAUUSD | TREND | 07:00–20:00 | London Breakout, Trend Pullback, NY Macro |
| EURUSD | COUNTER | 06:00–22:00 | Liquidity Sweep Reversal, Range Mean Reversion |
| USDJPY | TREND | 06:00–22:00 | London Breakout, Trend Pullback, NY Macro |
| USDCAD | TREND | 06:00–22:00 | London Breakout, Trend Pullback, NY Macro |
| GBPJPY | TREND | 06:00–22:00 | London Breakout, Trend Pullback, NY Macro |

## Risk Management

- Risk per trade: 0.25% max (0.10–0.15% for counter-trend/news)
- Daily loss limit: 1.0% → halt new trades
- Weekly loss limit: 2.5% → halt to end of week
- Max drawdown: 5.0% → stop + close all + safe mode
- Max 1 active position per instrument
- Max 4 new trades per day
- Friday: no new entries after 19:00 UTC, close all by 19:30 UTC
- Mandatory Stop Loss on every trade
- EV after costs ≥ +0.25R, RR ≥ 1.5, confluence ≥ 4/6

### Override Filters (added after 3 SL losses in week 1)

**Filter A — Sweep vs Breakout:**
If spread > 2× median AND ADX M5 falling at level touch → FORBIDDEN.
Prevents entering on thin-liquidity sweeps that revert.

**Filter B — SL vs Recent Noise:**
If `|entry - SL|` < recent 4-bar high-low range → SL inside noise → FORBIDDEN.
Prevents stop-loss from being hit by normal volatility.

These filters OVERRIDE confluence score. A 5.5/6 setup with wide spread +
falling ADX + SL inside noise = FORBIDDEN.

## Architecture

```
ai-trader/
├── SKILL.md                 # Main skill: triggers, account, regimes, schedule
├── .env.example             # Template for secrets (copy to .env)
├── .gitignore
├── tools/
│   ├── xau_env.py           # Config: instruments, regimes, windows, limits
│   ├── state.py             # Gate verdict + positions + window check
│   ├── cycle_multi.py       # Scan all 5 instruments in one call
│   ├── alert_sensor.py      # Background price level monitor → wakes agent
│   ├── trade.py             # MT5 order execution (open/close/sltp/positions)
│   ├── position_size.py     # EV/RR/lot calculator (multi-contract)
│   ├── calendar.py          # Economic calendar + news blackout windows
│   ├── journal.py           # Trade journal (trades.csv)
│   ├── tg_notify.py         # Telegram notifications via proxy
│   ├── hard_limits.md       # Quick reference: all hard limits + filters A/B
│   ├── decide_template.md   # Pre-trade decision checklist
│   ├── loop.md              # Operational cycle steps (0-9)
│   ├── env.md               # Environment reference (terminal, Python, calendar)
│   └── cron_template.txt    # Cron job recreation templates
├── constitution/            # Trading rules (source of truth)
│   └── Qwen_markdown_Ai_trader_XAU.md  # Full trading constitution (2400+ lines)
└── journal/                 # Runtime data (gitignored)
    └── trades.csv           # Trade log (generated at runtime)
```

## Operational Cycle

1. **Hourly cycle** (06:01–21:46 UTC): `cycle_multi.py` scans all instruments,
   agent analyzes setups, opens trades if conditions met, journals everything.
2. **Alert sensor** (between cycles): `alert_sensor.py` monitors key price levels
   every 20s. When a level is crossed → sends Telegram alert + exits → wakes
   agent for immediate analysis.
3. **Pre-market** (05:50 UTC): macro scan, calendar check, bias formation.
4. **Daily report** (22:33 UTC): close any open positions, stats, report.

## Configuration

All secrets and environment-specific settings go in `.env` (see `.env.example`):
- `MT5_TERMINAL_PATH` — path to terminal64.exe
- `MT5_LOGIN` — account number
- `MT5_SERVER` — broker server name
- `TELEGRAM_BOT_TOKEN` — bot token from @BotFather
- `TELEGRAM_CHAT_ID` — destination chat ID
- `TELEGRAM_PROXY` — HTTP proxy if Telegram API is blocked

Instrument-specific settings (contract size, digits, spread limits) are in
`tools/xau_env.py`. Adjust for your broker if different.

## Deploying on Another Machine

1. Install MetaTrader5 terminal, log in to your account
2. `pip install MetaTrader5`
3. Clone this repo
4. Copy `.env.example` → `.env`, fill in your values
5. Set `MT5_TERMINAL_PATH` to your terminal64.exe path
6. Run `py -3 tools/state.py gate` to verify connection
7. Start the agent — it will load the skill and begin trading

## License

Private project. Not for redistribution.