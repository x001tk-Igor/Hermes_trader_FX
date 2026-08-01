"""Shared constants for the multi-instrument AI trader (account YOUR_MT5_LOGIN)."""
from pathlib import Path
import os

# Terminal (configurable via env)
EXE = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")
HASH = "5FFA568149E88FCD5B44D926DCFEAA79"  # data-dir hash (for reference)
LOGIN = int(os.environ.get("MT5_LOGIN", "0"))  # set via .env
SERVER = os.environ.get("MT5_SERVER", "RoboForex-Pro")

SYMBOL = "XAUUSD"  # default, but now multi-symbol

# Assigned regimes (yearly backtest 2026-07-31)
REGIMES = {
    "XAUUSD": "TREND",
    "EURUSD": "COUNTER",
    "USDJPY": "TREND",
    "USDCAD": "TREND",
    "GBPJPY": "TREND",
}
TREND_TACTICS = ("LondonBreakout", "TrendPullbackContinuation", "NYMacroContinuation")
COUNTER_TACTICS = ("LiquiditySweepReversal", "RangeMeanReversion")
CONTRACT_SIZE = 100.0      # 1 lot = 100 oz
TICK_SIZE = 0.01           # price increment
TICK_VALUE = 1.0           # $ per 0.01 move per 1 lot (account USD)

LOT_MIN = 0.01
LOT_STEP = 0.01
LOT_MAX = 500.0

# Constitution hard limits (see hard_limits.md / full reglament)
RISK_PER_TRADE_MAX = 0.0025   # 0.25% of equity
RISK_REDUCE_05DD   = 0.0015   # 0.15% (drawdown>=3% or daily loss>=0.5%)
RISK_REDUCE_04DD   = 0.0010   # 0.10% (drawdown>=4%)
DAILY_LOSS_HALT    = 0.01     # 1.0% -> halt new trades
WEEKLY_LOSS_HALT   = 0.025    # 2.5%
DD_WARN3           = 0.03
DD_WARN4           = 0.04
DD_HALT5            = 0.05
MAX_NEW_TRADES_DAY  = 4
MAX_POSITIONS       = 1

# Trading window (UTC) — per instrument type
WINDOW_START_UTC = {"XAUUSD": (7, 0), "EURUSD": (6, 0), "USDJPY": (6, 0),
                     "USDCAD": (6, 0), "GBPJPY": (6, 0)}   # 07:00 gold, 06:00 FX
WINDOW_END_UTC   = {"XAUUSD": (20, 0), "EURUSD": (22, 0), "USDJPY": (22, 0),
                     "USDCAD": (22, 0), "GBPJPY": (22, 0)}  # 20:00 gold, 22:00 FX
FRI_NO_NEW_AFTER_UTC = 19, 0   # Friday: no new entries after 19:00
FRI_CLOSE_BY_UTC     = 19, 30  # Friday: close all by 19:30

# Spread limits (USD)
SPREAD_MAX_NORMAL = 0.35     # no trade above
SPREAD_HALT       = 0.50     # halt trading fully
SPREAD_MEDIAN_X   = 1.5      # also no trade if > 1.5x 5d median

# Paths
SKILL_DIR = Path(__file__).resolve().parent.parent
JOURNAL_DIR = SKILL_DIR / "journal"
JOURNAL_CSV = JOURNAL_DIR / "trades.csv"
PEAK_FILE = SKILL_DIR / "peak_equity.txt"
SOD_FILE = SKILL_DIR / "sod_equity.txt"  # start-of-day equity marker

# trade.py
TRADE_PY = str(Path.home() / ".claude" / "skills" / "mt5-manual-trading" / "tools" / "trade.py")

# Extended-impact events (§2.11) — 60 min before / 30 min after blackout
EXTENDED_KEYWORDS = (
    "fomc", "fed rate", "interest rate", "press conference", "powell",
    "yellen", "cpi", "core cpi", "pce", "core pce", "non-farm", "nfp",
    "gdp", "retail sales", "ism",
)
EXTENDED_PRE_MIN = 60
EXTENDED_POST_MIN = 30
# Other high-impact: 30 before / 15 after
HIGH_PRE_MIN = 30
HIGH_POST_MIN = 15