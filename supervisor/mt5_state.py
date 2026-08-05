"""mt5_state.py — чтение state из MT5 напрямую (Hermes bridge heartbeat беден: только
equity + baskets count, без per-symbol float_pnl/grid_count/virtual_tp).

Подключаемся к терминалу по path/data_path, читаем:
  - AccountInfo (balance, equity, margin_level, floating_pnl, today_profit)
  - per-symbol positions (filter by magic = MagicBase + tactic_code) → PositionInfo
  - per-symbol TF market (M15/H1/H4/D1 trend/rsi/atr) для rules.py / agent.py
  - drawdown_pct = equity DD от пика сессии (peak tracking в рамках процесса)

Hermes deploy: 5 чартов, каждый со своим MagicBase (см. deploy/.set):
  EURUSD=77100, GBPUSD=77000, EURAUD=77200, USDCAD=77300, NZDCAD=77400
magic = MagicBase + TACTIC_CODE (C1=1..C4=4, S1=11..S8=18).
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import MetaTrader5 as mt5

from models import AccountInfo, MarketContext, PositionInfo, SymbolState, TFData

logger = logging.getLogger("hermes_supervisor")

TACTIC_CODE = {"C1": 1, "C2": 2, "C3": 3, "C4": 4, "S1": 11, "S2": 12, "S3": 13,
               "S4": 14, "S5": 15, "S6": 16, "S7": 17, "S8": 18}

# per-pair deploy magic_base (из make_deploy_sets.py)
DEPLOY_MAGIC_BASE = {"EURAUD": 77200, "EURUSD": 77100, "GBPUSD": 77000,
                     "NZDCAD": 77400, "USDCAD": 77300}
DEPLOY_TACTIC = {"EURAUD": "S2", "EURUSD": "S8", "GBPUSD": "S8",
                 "NZDCAD": "C2", "USDCAD": "S6"}


class MT5StateReader:
    def __init__(self, data_path: Optional[str] = None):
        self._data_path = data_path
        self._init_ok = False
        self._equity_peak = 0.0   # для drawdown tracking в рамках процесса

    def connect(self) -> bool:
        kwargs = {}
        if self._data_path:
            kwargs["path"] = self._data_path
        if not mt5.initialize(**kwargs):
            logger.error("mt5.initialize failed: %s", mt5.last_error())
            self._init_ok = False
            return False
        self._init_ok = True
        return True

    def shutdown(self):
        if self._init_ok:
            mt5.shutdown()
            self._init_ok = False

    # ── account ───────────────────────────────────────────────────────────────
    def read_account(self) -> AccountInfo:
        if not self._init_ok:
            return AccountInfo()
        info = mt5.account_info()
        if info is None:
            return AccountInfo()
        eq = info.equity
        if eq > self._equity_peak:
            self._equity_peak = eq
        dd_pct = ((self._equity_peak - eq) / self._equity_peak * 100.0
                  if self._equity_peak > 0 else 0.0)
        return AccountInfo(
            balance=float(info.balance), equity=float(eq),
            margin_level_pct=float(info.margin_level) if info.margin else 0.0,
            floating_pnl=float(info.profit) if hasattr(info, "profit") else 0.0,
            drawdown_pct=dd_pct,
            today_profit=0.0,  # не критично для rules
        )

    # ── per-symbol positions ─────────────────────────────────────────────────
    def read_symbol_state(self, symbol: str, magic_base: int, tactic: str) -> SymbolState:
        st = SymbolState(symbol=symbol, magic=magic_base + TACTIC_CODE[tactic])
        if not self._init_ok:
            return st
        magic = st.magic
        positions = mt5.positions_get(symbol=symbol) or []
        pos = PositionInfo()
        floating = 0.0
        for p in positions:
            if p.magic != magic:
                continue
            vol = p.volume
            if p.type == mt5.POSITION_TYPE_BUY:
                pos.buy_count += 1
                pos.buy_volume += vol
                pos.buy_avg_price += p.price_open * vol
            else:
                pos.sell_count += 1
                pos.sell_volume += vol
                pos.sell_avg_price += p.price_open * vol
            floating += p.profit + p.swap
        if pos.buy_volume > 0:
            pos.buy_avg_price /= pos.buy_volume
        if pos.sell_volume > 0:
            pos.sell_avg_price /= pos.sell_volume
        pos.floating_profit = floating
        st.positions = pos
        st.baskets_open = max(pos.buy_count, pos.sell_count)  # грубо: basket = open позиции по стороне
        return st

    # ── per-symbol market (TF trend/rsi/atr) ──────────────────────────────────
    def read_market(self, symbol: str, timeframes: List[str]) -> MarketContext:
        mk = MarketContext(symbol=symbol)
        if not self._init_ok:
            return mk
        for tf in timeframes:
            d = self._tf_data(symbol, tf)
            if d:
                mk.timeframes[tf] = d
        # D1 ATR avg 30d + burst + impulse
        d1 = mk.timeframes.get("D1")
        if d1:
            mk.atr_d1_avg_30d = self._atr_avg(symbol, "D1", 30)
            if mk.atr_d1_avg_30d > 0:
                mk.atr_burst = d1.atr > 2.0 * mk.atr_d1_avg_30d
            mk.last_d1_candle_size_atr = self._last_d1_size_atr(symbol, d1.atr)
            mk.impulse_detected = mk.last_d1_candle_size_atr > 2.0
        # spread
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            sp = tick.ask - tick.bid
            mk.spread_points = int(round(sp / mt5.symbol_info(symbol).point)) if mt5.symbol_info(symbol) else 0
        return mk

    def _tf_data(self, symbol: str, tf_name: str) -> Optional[TFData]:
        tf_map = {"M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
                  "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
        p = tf_map.get(tf_name)
        if p is None:
            return None
        rates = mt5.copy_rates_from_pos(symbol, p, 0, 250)
        if rates is None or len(rates) < 60:
            return None
        closes = [float(r["close"]) for r in rates]
        # trend = EMA fast vs slow (12 vs 50)
        ema_f = _ema(closes, 12)
        ema_s = _ema(closes, 50)
        trend = 1 if ema_f > ema_s else (-1 if ema_f < ema_s else 0)
        rsi = _rsi(closes, 14)
        atr = _atr(rates, 14)
        return TFData(timeframe=tf_name, trend=trend, rsi=rsi, atr=atr)

    def _atr_avg(self, symbol: str, tf_name: str, days: int) -> float:
        tf_map = {"D1": mt5.TIMEFRAME_D1, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
        p = tf_map.get(tf_name)
        if p is None:
            return 0.0
        rates = mt5.copy_rates_from_pos(symbol, p, 0, days + 14)
        if rates is None or len(rates) < days + 14:
            return 0.0
        atrs = _atr_series(rates, 14)
        if len(atrs) < days:
            return 0.0
        return sum(atrs[-days:]) / days

    def _last_d1_size_atr(self, symbol: str, atr_val: float) -> float:
        if atr_val <= 0:
            return 0.0
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 2)
        if rates is None or len(rates) < 1:
            return 0.0
        last = rates[-1]
        size = float(last["high"] - last["low"])
        return size / atr_val if atr_val > 0 else 0.0


# ── indicators (чистый python, без зависимостей) ─────────────────────────────
def _ema(values: list, period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _rsi(values: list, period: int) -> float:
    if len(values) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = values[i] - values[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_g = gains / period
    avg_l = losses / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - 100.0 / (1.0 + rs)


def _atr(rates, period: int) -> float:
    atrs = _atr_series(rates, period)
    return atrs[-1] if atrs else 0.0


def _atr_series(rates, period: int) -> list:
    if len(rates) < period + 1:
        return []
    trs = []
    for i in range(1, len(rates)):
        h, l = float(rates[i]["high"]), float(rates[i]["low"])
        pc = float(rates[i - 1]["close"])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    # Wilder smoothing
    atrs = [sum(trs[:period]) / period]
    for tr in trs[period:]:
        atrs.append((atrs[-1] * (period - 1) + tr) / period)
    return atrs