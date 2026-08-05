"""Shared constants for the multi-instrument AI trader (account YOUR_MT5_LOGIN).

v3 — Averaging-down system: 6 FX pairs, all TREND regime, 3-position averaging.
Backtested 2026-08-02: PF 1.57-1.81 with averaging on T_EMA tactic.
"""
from pathlib import Path
import os

# Terminal (configurable via env)
EXE = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")
HASH = "<TERMINAL_DATA_DIR_HASH>"  # data-dir hash (for reference)
LOGIN = int(os.environ.get("MT5_LOGIN", "0"))  # set via .env
SERVER = os.environ.get("MT5_SERVER", "RoboForex-Pro")

# ── Instruments: 6 FX pairs, all TREND regime ──────────────────────────
# Selected by cross_pair_study.py (2026-08-02): PF>1.5 with averaging, no JPY, no gold.
REGIMES = {
    "EURUSD": "TREND",
    "GBPUSD": "TREND",
    "USDCAD": "TREND",
    "EURGBP": "TREND",
    "NZDCAD": "TREND",
    "EURAUD": "TREND",
}

# Per-instrument metadata
INSTRUMENT_INFO = {
    "EURUSD": {"digits": 5, "contract": 100000, "window": (5, 0, 20, 0)},
    "GBPUSD": {"digits": 5, "contract": 100000, "window": (5, 0, 20, 0)},
    "USDCAD": {"digits": 5, "contract": 100000, "window": (5, 0, 20, 0)},
    "EURGBP": {"digits": 5, "contract": 100000, "window": (5, 0, 20, 0)},
    "NZDCAD": {"digits": 5, "contract": 100000, "window": (5, 0, 20, 0)},
    "EURAUD": {"digits": 5, "contract": 100000, "window": (5, 0, 20, 0)},
}

# Active tactics (v4: 10 primary + 2 reserve, all backtested H1)
# See hard_limits.md for full tactic list and backtest results
TREND_TACTICS = ("C1_TrendPullback", "S1_EMA_VWAP", "S2_GoldScalper", "S3_200EMA_UTBot", "S4_MadCharts", "S8_SmartTrend")
RANGE_TACTICS = ("C2_RangeReversion", "C3_RSI_BB")
BREAKOUT_TACTICS = ("S7_GateBreaker", "S6_NY_ORB")
REVERSAL_TACTICS = ("C4_LiquiditySweep", "S5_UTBot_STC")
COUNTER_TACTICS = ("C_RSI_BB", "C_Sweep")  # secondary, only when ADX<20

# ── Averaging configuration ───────────────────────────────────────────
AVERAGING = {
    "max_addons": 2,              # max 3 positions total (1 main + 2 addons)
    "addon1_atr_mult": 1.0,      # first addon at -1.0×ATR from entry
    "addon2_atr_mult": 2.0,      # second addon at -2.0×ATR from entry
    "sl_atr_mult": 2.5,          # each position SL = 2.5×ATR from its own entry (room for addons)
    "tp_atr_mult": 0.5,          # TP = weighted_avg + 0.5×ATR
    "dd_stop_pct": 2.5,          # close all if total loss ≥ 2.5% equity (room before 3% daily)
    "max_positions_per_symbol": 3,
    "lot_divisor": 2,            # divide calculated lot by 2 for safety (8 pos max)
    "atr_anomaly_pct": 5.0,      # skip if ATR > 5% of price (gap protection)
}

# ── Risk limits ───────────────────────────────────────────────────────
RISK_PER_TRADE_MAX = 0.0025    # 0.25% of equity (base, for fixed mode)
RISK_AVG_TOTAL = 0.025        # 2.5% max total loss per symbol with averaging
DAILY_LOSS_HALT = 0.03         # 3.0% daily loss → halt new trades
WEEKLY_LOSS_HALT = 0.05        # 5.0% weekly loss → halt to end of week
DD_WARN3 = 0.03
DD_WARN4 = 0.04
DD_HALT5 = 0.05
MAX_NEW_TRADES_DAY = 8         # 8 entries across 6 pairs (was 4 for single pair)
MAX_SYMBOLS_TRADED = 6
MAX_INSTRUMENTS_OPEN = 3  # max instruments with open positions (excluding addons)

# ── Trading window (UTC) ─────────────────────────────────────────────
# All FX pairs: 06:00-22:00 UTC
WINDOW_START_UTC = {sym: (info["window"][0], info["window"][1]) for sym, info in INSTRUMENT_INFO.items()}
WINDOW_END_UTC = {sym: (info["window"][2], info["window"][3]) for sym, info in INSTRUMENT_INFO.items()}
FRI_NO_NEW_AFTER_UTC = 19, 0   # Friday: no new entries after 19:00
FRI_CLOSE_BY_UTC = 19, 30      # Friday: close all by 19:30

# ── Spread limits ─────────────────────────────────────────────────────
# Per-instrument spread limits in points (configurable per broker)
SPREAD_MAX_POINTS = {
    "EURUSD": 20,   # 2.0 pips
    "GBPUSD": 25,   # 2.5 pips
    "USDCAD": 30,   # 3.0 pips
    "EURGBP": 20,   # 2.0 pips
    "NZDCAD": 35,   # 3.5 pips
    "EURAUD": 35,   # 3.5 pips
}
SPREAD_MEDIAN_X = 2.0  # also no trade if > 2.0× 5d median

# ── Lot settings ──────────────────────────────────────────────────────
LOT_MIN = 0.01
LOT_STEP = 0.01
LOT_MAX = 500.0

# ── Paths ─────────────────────────────────────────────────────────────
SKILL_DIR = Path(__file__).resolve().parent.parent
JOURNAL_DIR = SKILL_DIR / "journal"
JOURNAL_CSV = JOURNAL_DIR / "trades.csv"
PEAK_FILE = SKILL_DIR / "peak_equity.txt"
SOD_FILE = SKILL_DIR / "sod_equity.txt"
PROPOSALS_CSV = JOURNAL_DIR / "proposals.csv"

# trade.py (bundled in tools/)
TRADE_PY = str(Path(__file__).resolve().parent / "trade.py")

# ── News blackout ─────────────────────────────────────────────────────
EXTENDED_KEYWORDS = (
    "fomc", "fed rate", "interest rate", "press conference", "powell",
    "yellen", "cpi", "core cpi", "pce", "core pce", "non-farm", "nfp",
    "gdp", "retail sales", "ism",
)
EXTENDED_PRE_MIN = 60
EXTENDED_POST_MIN = 30
HIGH_PRE_MIN = 30
HIGH_POST_MIN = 15

# Currency mapping for news filter
CURRENCY_MAP = {
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "USDCAD": ["USD", "CAD"],
    "EURGBP": ["EUR", "GBP"],
    "NZDCAD": ["NZD", "CAD"],
    "EURAUD": ["EUR", "AUD"],
}