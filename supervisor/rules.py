"""rules.py — rule-based safety floor для Hermes FX supervisor.

Детерминированный, всегда применяется ПЕРЕД LLM. Если rules говорят KILL/BRAKE_HEAVY
при критическом состоянии (DD, маржа, high-impact новость) — LLM не может это отменить
(safety floor). LLM может только ДОБАВИТЬ тормоз в серой зоне, не снять safety.

Действия = constrictive-only (см. models.ALL_ACTIONS): ALLOW/BRAKE_LIGHT/MODERATE/HEAVY/
LONG_ONLY/SHORT_ONLY/KILL_NEW. Никаких CLOSE_ALL/EMERGENCY_STOP (Hermes bridge не закрывает
позиции — только стоп новые входы; позиции дойдут до виртуального TP).

Приоритет правил — сверху вниз (первое сработавшее = финал).
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from models import Decision, MarketContext, NewsContext, State

logger = logging.getLogger("hermes_supervisor")


def make_decision(symbol: str, state: State, market: Optional[MarketContext],
                   news: NewsContext, config: dict) -> Decision:
    thr = config.get("risk_thresholds", {})
    acc = state.account
    dd = acc.drawdown_pct
    margin = acc.margin_level_pct

    # найти символ в state
    sym = next((s for s in state.symbols if s.symbol == symbol), None)
    grid = (sym.positions.buy_count + sym.positions.sell_count) if sym else 0
    float_pnl = sym.positions.floating_profit if sym else 0.0

    close_all_dd = thr.get("drawdown_kill_pct", 6.0)       # KILL_NEW (не CLOSE — Hermes не умеет)
    pause_new_dd = thr.get("drawdown_brake_heavy_pct", 4.0)
    brake_mod_dd  = thr.get("drawdown_brake_moderate_pct", 2.5)
    brake_light_dd = thr.get("drawdown_brake_light_pct", 1.5)
    grid_warning = thr.get("grid_count_warning", 6)
    grid_combo_dd = thr.get("grid_dd_combo_pct", 2.0)
    margin_kill = thr.get("margin_kill_pct", 200)

    # ── 1. Margin критический ─────────────────────────────────────────────────
    if 0 < margin < margin_kill:
        return Decision(symbol=symbol, action="KILL_NEW", confidence=0.95,
                        reason=f"Маржа {margin:.0f}%<{margin_kill}% — стоп новые входы",
                        duration_minutes=60)

    # ── 2. Drawdown критический ────────────────────────────────────────────────
    if dd >= close_all_dd:
        return Decision(symbol=symbol, action="KILL_NEW", confidence=0.95,
                        reason=f"Просадка {dd:.1f}%>={close_all_dd}% — стоп новые входы",
                        duration_minutes=120)

    if grid >= grid_warning and dd >= grid_combo_dd:
        return Decision(symbol=symbol, action="KILL_NEW", confidence=0.90,
                        reason=f"Тяжёлая сетка {grid} поз + просадка {dd:.1f}%",
                        duration_minutes=120)

    if dd >= pause_new_dd:
        return Decision(symbol=symbol, action="BRAKE_HEAVY", confidence=0.90,
                        reason=f"Просадка {dd:.1f}%>={pause_new_dd}%",
                        duration_minutes=120)

    if dd >= brake_mod_dd:
        return Decision(symbol=symbol, action="BRAKE_MODERATE", confidence=0.85,
                        reason=f"Просадка {dd:.1f}%>={brake_mod_dd}%",
                        duration_minutes=90)

    if dd >= brake_light_dd:
        return Decision(symbol=symbol, action="BRAKE_LIGHT", confidence=0.80,
                        reason=f"Просадка {dd:.1f}%>={brake_light_dd}%",
                        duration_minutes=60)

    # ── 3. High-impact новость в ближайшие 60 мин ─────────────────────────────
    if news.high_impact_within_60min:
        ev = news.high_impact_within_60min[0]
        ts = ev.timestamp_utc.strftime("%H:%M UTC")
        return Decision(symbol=symbol, action="KILL_NEW", confidence=0.95,
                        reason=f"High-impact: {ev.title} в {ts}",
                        duration_minutes=150)

    # ── 4. Кластер medium новостей ───────────────────────────────────────────
    medium = [e for e in news.upcoming if e.impact == "medium"]
    if len(medium) >= 2:
        return Decision(symbol=symbol, action="BRAKE_MODERATE", confidence=0.70,
                        reason=f"Кластер medium-событий: {len(medium)} шт",
                        duration_minutes=90)

    # ── 5. ATR burst ─────────────────────────────────────────────────────────
    if market and market.atr_burst and market.atr_d1_avg_30d > 0:
        ratio = market.timeframes["D1"].atr / market.atr_d1_avg_30d
        return Decision(symbol=symbol, action="BRAKE_HEAVY", confidence=0.90,
                        reason=f"ATR D1 burst: {ratio:.1f}x>2x среднего 30д",
                        duration_minutes=1440)

    # ── 6. Импульсная D1 свеча ────────────────────────────────────────────────
    if market and market.impulse_detected:
        return Decision(symbol=symbol, action="BRAKE_MODERATE", confidence=0.85,
                        reason=f"Импульсная D1 свеча: {market.last_d1_candle_size_atr:.1f}x ATR",
                        duration_minutes=480)

    # ── 7. Сессионное открытие + повышенный ATR ───────────────────────────────
    if market and _near_session_open(datetime.now(timezone.utc), config):
        h1 = market.timeframes.get("H1")
        d1 = market.timeframes.get("D1")
        if h1 and d1 and d1.atr > 0 and h1.atr > d1.atr * 0.15:
            return Decision(symbol=symbol, action="BRAKE_LIGHT", confidence=0.75,
                            reason="Открытие сессии + ATR H1 повышен",
                            duration_minutes=30)

    # ── 8. Multi-TF направленная блокировка (только при наличии контр-тренд позиций)
    if market:
        h4 = market.timeframes.get("H4")
        d1 = market.timeframes.get("D1")
        if h4 and d1 and h4.trend == d1.trend and h4.trend != 0:
            if d1.rsi > 70 or d1.rsi < 30:
                pos = sym.positions if sym else None
                if h4.trend == 1 and pos and pos.sell_count > 0:
                    return Decision(symbol=symbol, action="LONG_ONLY", confidence=0.75,
                                    reason=f"H4+D1 бычий, RSI D1={d1.rsi:.0f} — блок SELL (контр-тренд)",
                                    duration_minutes=240)
                if h4.trend == -1 and pos and pos.buy_count > 0:
                    return Decision(symbol=symbol, action="SHORT_ONLY", confidence=0.75,
                                    reason=f"H4+D1 медвежий, RSI D1={d1.rsi:.0f} — блок BUY (контр-тренд)",
                                    duration_minutes=240)

    # ── 9. Default — полный газ ──────────────────────────────────────────────
    return Decision(symbol=symbol, action="ALLOW", confidence=1.0,
                    reason="Нет активных триггеров риска — полный газ",
                    duration_minutes=0)


def _near_session_open(now: datetime, config: dict) -> bool:
    sessions = config.get("sessions", {})
    pause_min = sessions.get("session_open_pause_min", 30)
    for key in ("london_open_utc", "ny_open_utc"):
        val = sessions.get(key, "")
        if not val:
            continue
        try:
            h, m = map(int, val.split(":"))
        except ValueError:
            continue
        open_s = h * 3600 + m * 60
        now_s = now.hour * 3600 + now.minute * 60
        diff_min = (now_s - open_s) / 60
        if 0 <= diff_min <= pause_min:
            return True
    return False