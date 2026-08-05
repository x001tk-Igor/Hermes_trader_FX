"""models.py — dataclasses для Hermes FX AI Supervisor.

Hermes bridge беднее Setura: heartbeat_<sym>.json = {ts, symbol, tick, baskets, equity,
last_action, magic_base}. Нет per-symbol float_pnl / grid_count / virtual_tp.
Поэтому state достаём из MT5 напрямую (mt5_state.py), а heartbeat используем как alive-пульс.

Решение = constrictive-only режим (Hermes Bridge.mqh инвариант: только сужает, никогда
не расширяет). 7 действий, все в рамках 4 рычагов Bridge.mqh:
  trading_enabled, risk_multiplier (0..1), tactic_enabled[by name], allowed_direction.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict


# ── действия (constrictive-only, no position closing) ──────────────────────────
# ALLOW         -> risk_multiplier=1.0, full gas (= валидированный baseline)
# BRAKE_LIGHT   -> risk_multiplier=0.6
# BRAKE_MODERATE-> risk_multiplier=0.4
# BRAKE_HEAVY   -> risk_multiplier=0.2
# LONG_ONLY     -> allowed_direction=long  (блок SELL-входов)
# SHORT_ONLY    -> allowed_direction=short (блок BUY-входов)
# KILL_NEW      -> trading_enabled=false (стоп новые входы+addons; позиции дойдут до виртуального TP)
REGIME_RISK = {
    "ALLOW":          1.0,
    "BRAKE_LIGHT":    0.6,
    "BRAKE_MODERATE": 0.4,
    "BRAKE_HEAVY":    0.2,
}
DIRECTION_ONLY = {"LONG_ONLY": "long", "SHORT_ONLY": "short"}
KILL_ACTION = "KILL_NEW"
ALL_ACTIONS = list(REGIME_RISK.keys()) + list(DIRECTION_ONLY.keys()) + [KILL_ACTION]


@dataclass
class TFData:
    timeframe: str = ""
    trend: int = 0          # -1 short, 0 none, +1 long (EMA fast vs slow)
    rsi: float = 50.0
    atr: float = 0.0


@dataclass
class MarketContext:
    symbol: str = ""
    timeframes: Dict[str, TFData] = field(default_factory=dict)
    atr_d1_avg_30d: float = 0.0
    atr_burst: bool = False
    last_d1_candle_size_atr: float = 0.0
    impulse_detected: bool = False
    spread_points: int = 0


@dataclass
class NewsEvent:
    title: str = ""
    country: str = ""
    currency: str = ""
    impact: str = ""                       # "high" / "medium" / "low" / "holiday"
    timestamp_utc: Optional[datetime] = None


@dataclass
class NewsContext:
    upcoming: List[NewsEvent] = field(default_factory=list)
    high_impact_within_60min: List[NewsEvent] = field(default_factory=list)
    high_impact_within_30min: List[NewsEvent] = field(default_factory=list)


@dataclass
class PositionInfo:
    buy_count: int = 0
    sell_count: int = 0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    floating_profit: float = 0.0
    buy_avg_price: float = 0.0
    sell_avg_price: float = 0.0


@dataclass
class SymbolState:
    symbol: str = ""
    magic: int = 0
    positions: PositionInfo = field(default_factory=PositionInfo)
    baskets_open: int = 0                  # из heartbeat (basket count)
    heartbeat_alive: bool = False
    heartbeat_age_sec: float = 0.0
    last_action: str = ""


@dataclass
class AccountInfo:
    balance: float = 0.0
    equity: float = 0.0
    margin_level_pct: float = 0.0
    floating_pnl: float = 0.0
    drawdown_pct: float = 0.0              # equity DD от пика (сессии)
    today_profit: float = 0.0


@dataclass
class State:
    timestamp_utc: Optional[datetime] = None
    account: AccountInfo = field(default_factory=AccountInfo)
    symbols: List[SymbolState] = field(default_factory=list)


@dataclass
class Decision:
    symbol: str = ""
    action: str = "ALLOW"                 # одно из ALL_ACTIONS
    reason: str = ""
    duration_minutes: int = 0             # сколько действия валидны (supervisor сам переоценит)
    confidence: float = 1.0


@dataclass
class HistoryEntry:
    timestamp_utc: datetime
    action: str
    reason: str
    confidence: float
    state_summary: str


# ── маппинг Decision -> permissions.json (Bridge.mqh формат) ───────────────────
def decision_to_permissions(dec: Decision, tactic_name: str) -> dict:
    """Вернёт dict, который bridge.py сериализует в permissions_<symbol>.json.

    Bridge.mqh парсит подстроками:
      "trading_enabled": false   -> глобальный стоп новых входов
      "risk_multiplier": 0.4     -> масштаб лот ВНИЗ (0<v<1; >1 игнор)
      "<TacticName>": false      -> отключить тактик (per-chart, т.к. SoloTactic)
      "allowed_direction": "long"|"short" -> только одна сторона
    """
    perm = {"trading_enabled": True, "risk_multiplier": 1.0}
    a = dec.action
    if a == KILL_ACTION:
        perm["trading_enabled"] = False
    elif a in DIRECTION_ONLY:
        perm["allowed_direction"] = DIRECTION_ONLY[a]
    elif a in REGIME_RISK:
        perm["risk_multiplier"] = REGIME_RISK[a]
    # tactic_name для контекста (супервизор не отключает тактик — это per-pair deploy-решение)
    perm["_tactic"] = tactic_name
    perm["_reason"] = dec.reason[:200]
    return perm