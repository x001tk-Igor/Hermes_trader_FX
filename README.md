# Hermes Trader FX — Autonomous MT5 Trading System v3

Autonomous AI trader for MetaTrader5, running as a Hermes Agent skill.
Trades 6 FX pairs with a 3-position averaging-down system and T_EMA trend signals.

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

## Instruments (v3 — 6 FX pairs, all TREND)

Selected by cross-pair backtest study (30 instruments, 5 tactics, 1 year H1).
All pairs trade in TREND regime with averaging-down.

| Instrument | Regime | Window UTC | Digits | Contract | PF (avg) | WR |
|---|---|---|---|---|---|---|
| EURUSD | TREND | 06:00–22:00 | 5 | 100,000 | 1.81 | 82.6% |
| GBPUSD | TREND | 06:00–22:00 | 5 | 100,000 | 1.77 | 82.5% |
| USDCAD | TREND | 06:00–22:00 | 5 | 100,000 | 1.69 | 83.1% |
| EURGBP | TREND | 06:00–22:00 | 5 | 100,000 | 1.63 | 82.2% |
| NZDCAD | TREND | 06:00–22:00 | 5 | 100,000 | 1.60 | 82.2% |
| EURAUD | TREND | 06:00–22:00 | 5 | 100,000 | 1.57 | 81.5% |

**Excluded:** JPY pairs (unviable on $100K equity — min lot too risky),
XAUUSD (PF 0.94 with averaging).

## Averaging-Down System (v3)

Each trade uses up to 3 positions with automatic averaging:

1. **Main entry:** lot sized for 3 positions, SL = 1.5×ATR
2. **Addon 1:** at -1.0×ATR from entry, own SL = 1.5×ATR
3. **Addon 2:** at -2.0×ATR from entry, own SL = 1.5×ATR
4. **TP** = weighted average + 0.5×ATR (recalculated after each addon)
5. **DD stop:** if total loss on symbol ≥ 1.7% equity → close all positions

**Lot calculation:**
```
lot = (equity × 1.7%) / (3 × 1.5 × ATR × contract_size)
```

**Tactic: T_EMA** — EMA20 vs EMA200 on H1 + ADX(14) > 20.
- EMA20 > EMA200 → long bias
- EMA20 < EMA200 → short bias
- ADX < 20 → no signal (range — secondary tactics C_RSI_BB/C_Sweep apply)

## Risk Management

- Max total loss per symbol (3×SL): **1.7% equity**
- Daily loss limit: **3.0%** → halt new trades
- Weekly loss limit: **5.0%** → halt to end of week
- Max drawdown: **5.0%** → stop + close all + alert
- Max 8 new entries per day (across all 6 pairs)
- Max 3 positions per symbol, max 6 symbols simultaneously
- Friday: no new entries after 19:00 UTC, close all by 19:30 UTC
- Mandatory per-position Stop Loss (never removed, never widened)
- ATR anomaly cap: skip if ATR > 5% of price (gap protection)

## Architecture

```
xau-ai-trader/
├── SKILL.md                 # Main skill: triggers, pairs, averaging, schedule
├── .env.example             # Template for secrets (copy to .env)
├── .gitignore
├── tools/
│   ├── xau_env.py           # Config: 6 pairs, AVERAGING, risk limits, currency map
│   ├── state.py             # Gate + positions + avg-positions + avg-risk + dd-monitor + market
│   ├── trade.py             # MT5 execution: open/close/sltp/avg-tp/close-symbol
│   ├── position_size.py     # Lot calculator: fixed mode + --avg-mode (3 positions)
│   ├── calendar.py          # Economic calendar: 6 currencies, symbol mapping, blackouts
│   ├── journal.py           # Trade journal with averaging fields (addon_number, avg_group)
│   ├── alert_sensor.py      # Background price level monitor → Telegram alerts
│   ├── tg_notify.py         # Telegram notifications
│   ├── cycle_multi.py       # Multi-instrument scanner (legacy)
│   ├── hard_limits.md       # Quick reference: all limits + averaging rules
│   ├── decide_template.md   # Pre-trade decision checklist
│   ├── loop.md              # Operational cycle v3 (addon management, DD check)
│   ├── env.md               # Environment reference
│   ├── cron_template.txt    # Cron job recreation templates
│   ├── backtest_tactics.py  # 10-tactic backtest engine
│   ├── sim_averaging.py     # Averaging-down simulator v1
│   ├── sim_averaging_v2.py  # v2: per-position SL + DD stop
│   ├── cross_pair_study.py  # 30-instrument cross-pair study
│   └── sim_acceleration.py  # Position Acceleration simulator (research)
├── constitution/            # Trading rules (source of truth)
│   └── Qwen_markdown_Ai_trader_XAU.md  # Full trading constitution
└── journal/                 # Runtime data (gitignored)
    └── trades.csv           # Trade log (generated at runtime)
```

## Operational Cycle (v3)

1. **Trading cycle** (06:01–21:46 UTC, every 15 min):
   - `state.py gate` — hard-limit check
   - `calendar.py symbols` — news blackout check
   - `state.py market` — bid/ask/spread/EMA/ADX/ATR for all 6 pairs
   - T_EMA signal scan → `position_size.py --avg-mode` → `trade.py open`
   - `state.py avg-positions` + `avg-risk` — addon management + DD check
   - `trade.py avg-tp` — recalculate TP after addon
   - `trade.py close-symbol` — if DD stop triggered
   - `journal.py add` — log all actions
2. **Pre-market** (05:50 UTC): macro scan, calendar, bias formation.
3. **Daily report** (22:33 UTC): close positions, stats, daily summary.

## Backtest Results (2026-08-02, H1, 1 year, $100K equity)

| Method | Total PnL | PF | WR | Worst Trade |
|---|---|---|---|---|
| Fixed 0.01 | -$181,976 | 0.00 | 0% | -$382 |
| **Averaging Down v3** | **+$764,790** | **1.50-1.78** | **81-83%** | **-$2,006** |
| Position Acceleration ×8 | -$195,787 | 0.00 | 0% | -$386 |
| Accel Multi-step | -$159,183 | 0.03-0.23 | 1-5% | -$374 |

Averaging down is the only profitable method on intraday FX with T_EMA.

## Configuration

All secrets in `.env` (see `.env.example`):
- `MT5_TERMINAL_PATH` — path to terminal64.exe
- `MT5_LOGIN` — account number
- `MT5_SERVER` — broker server name
- `TELEGRAM_BOT_TOKEN` — bot token from @BotFather
- `TELEGRAM_CHAT_ID` — destination chat ID
- `TELEGRAM_PROXY` — HTTP proxy if Telegram API is blocked

Instrument settings (contract size, digits, spread limits, averaging config)
in `tools/xau_env.py`. Adjust for your broker if different.

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