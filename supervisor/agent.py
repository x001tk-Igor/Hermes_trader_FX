"""agent.py — LLM-слой решений (Hermes FX supervisor).

Hybrid: rules.py = safety floor (детерминированно, всегда; LLM не может снять safety).
LLM (Sonnet через OpenRouter) = читает контекст (новости/вол/корреляция/сессия/позиции)
и выбирает режим газ/тормоз в серой зоне. Opus-эскалация при KILL_NEW с conf<порога.

Действия = constrictive-only (Hermes Bridge.mqh инвариант: только сужает, никогда не
расширяет; позиций не закрывает — только стоп новые входы/тормоз лота/блок стороны):
  ALLOW / BRAKE_LIGHT / BRAKE_MODERATE / BRAKE_HEAVY / LONG_ONLY / SHORT_ONLY / KILL_NEW

«Полный газ» = ALLOW (risk_multiplier=1.0 = валидированный baseline, бюджетный лот).
Превышение baseline (>1.0) НЕ поддерживается мостом — baseline уже валидированный edge.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from openai import OpenAI

from models import (Decision, MarketContext, NewsContext, State, ALL_ACTIONS,
                    KILL_ACTION)
from news import format_news_list
import rules as rules_module

_log = logging.getLogger("hermes_supervisor")

SYSTEM_PROMPT = """\
Ты — стратегический менеджер риска советника Hermes FX на форекс-паре.

Советник: мультотактический averaging-down. Входит по сигналу тактики, добирает 2 addon-\
позиции на -1/-2 ATR, выходит по виртуальному TP на средневзвешенной цене. Реального SL \
нет — защита через SymbolDDStopPct и MaxBarsInTrade. Бюджет риска в ДЕНЬГАХ (BasketRiskPct).

Главная уязвимость — сильное направленное движение (новости, сессия, шок), при котором \
усреднение накапливает позиции до срабатывания TP. Это главный сценарий убытков.

Твоя задача — раз в час оценивать риски КОНКРЕТНОЙ пары и выбирать режим работы.

ВАЖНО: ты можешь ТОЛЬКО СУЖАТЬ (тормозить), никогда расширять. «Полный газ» = ALLOW \
(risk_multiplier=1.0 = валидированный baseline лот). Ты не можешь поднять лот выше \
baseline. Позиции ты не закрываешь — только стоп новые входы / тормоз лота / блок стороны.

Доступные действия (одно из):
- ALLOW           — полный газ, risk_multiplier=1.0 (baseline, валидированный edge)
- BRAKE_LIGHT     — лёгкий тормоз, risk_multiplier=0.6 (серая зона, умеренный риск)
- BRAKE_MODERATE  — средний тормоз, risk_multiplier=0.4 (видимая угроза)
- BRAKE_HEAVY     — тяжёлый тормоз, risk_multiplier=0.2 (явный риск, но не стоп)
- LONG_ONLY       — только BUY-входы (блок SELL) — при бычьем H4+D1 + RSI экстремум + SELL-позиции
- SHORT_ONLY      — только SELL-входы (блок BUY) — при медвежьем H4+D1 + RSI экстремум + BUY-позиции
- KILL_NEW        — стоп новые входы и addon (существующие корзины дойдут до виртуального TP)

Эвристики (применяй с контекстом):
1. NEWS: high-impact по валютам пары в ближайшие 60 мин (FOMC/NFP/CPI/ставка/GDP) → KILL_NEW на 150 мин.
   Кластер ≥2 medium → BRAKE_MODERATE на 90 мин.
2. VOLATILITY: ATR D1 > 2× среднего 30д → BRAKE_HEAVY на 24ч. D1 свеча > 2× ATR → BRAKE_MODERATE на 8ч.
3. DRAWDOWN: >4% или (grid≥6 + DD>2%) → BRAKE_HEAVY/KILL_NEW. >2.5% → BRAKE_MODERATE. >1.5% → BRAKE_LIGHT.
4. MULTI-TF (направленная): H4+D1 один тренд + RSI D1 экстремальный (>70/<30) + есть контр-тренд позиции →
   LONG_ONLY/SHORT_ONLY (блокируй входы ПРОТИВ тренда, по тренду разрешай).
5. SESSION: London 07:00–07:30 UTC или NY 12:00–12:30 UTC + ATR H1 повышен → BRAKE_LIGHT на 30 мин.
6. MARGIN: <200% → KILL_NEW.
7. DEFAULT: нет триггеров → ALLOW, confidence=1.0.

Особенности форекс:
- USD-пары синхронно реагируют на USD-новости (NFP/FOMC). Кроссы (EURAUD/EURGBP) реагируют на EUR/своя валюта.
- London/NY открытия — повышенная волатильность для EUR/GBP пар.
- Нормальный ATR D1 мажоров: 50–150 пунктов; >300 = аномалия.

KILL_NEW только при реальной угрозе: high-impact новость, DD>4%, маржа<200%, ATR-burst.
KILL_NEW не закрывает позиции — он только стопает новые входы; существующие корзины безопасно дойдут до TP.

Отвечай СТРОГО ОДНИМ JSON без markdown:
{"action": "<ACTION>", "reason": "<русский, до 200 символов>", "duration_minutes": <int>, "confidence": <0.0-1.0>}
"""

_USER_PROMPT = """\
СНИМОК СОСТОЯНИЯ (UTC: {timestamp_utc})

СЧЁТ:
  Баланс: {balance} USD
  Equity: {equity} USD
  Просадка(сессия): {drawdown_pct}%
  Маржа: {margin_level_pct}%
  Floating P/L: {floating_pnl} USD

ПОЗИЦИИ ПО {symbol} (tactic={tactic}, magic={magic}):
  BUY:  count={buy_count}, volume={buy_volume}, avg={buy_avg_price}
  SELL: count={sell_count}, volume={sell_volume}, avg={sell_avg_price}
  Плавающий P/L: {floating_profit} USD
  Basket open (heartbeat): {baskets_open}, last_action={last_action}, heartbeat_age={heartbeat_age}s

РЫНОК {symbol}:
  H1: trend={h1_trend}, RSI={h1_rsi}, ATR={h1_atr}
  H4: trend={h4_trend}, RSI={h4_rsi}, ATR={h4_atr}
  D1: trend={d1_trend}, RSI={d1_rsi}, ATR={d1_atr}, atr_avg_30d={d1_atr_avg}, burst={atr_burst}
  Последняя D1 свеча: {last_d1_size}× ATR, импульс={impulse_detected}
  Спред: {spread_points} пунктов

НОВОСТИ (ближайшие 4ч по валютам {symbol}):
{news_list}

{history_section}Прими решение по {symbol}.\
"""

_ESCALATION_ACTIONS = {KILL_ACTION}


class AIAgent:
    def __init__(self, config: dict):
        self._cfg = config
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.get("base_url", "https://openrouter.ai/api/v1"),
        )

    def decide(self, symbol: str, state: State, market: Optional[MarketContext],
               news: NewsContext, full_config: dict, tactic: str,
               history: Optional[list] = None) -> tuple:
        """Returns (Decision, raw). LLM; fallback to rules on any error.
        Safety floor: rules запускаются ПЕРВЫМИ (safety_decision). Если rules дали
        KILL_NEW/BRAKE_HEAVY при критическом состоянии — LLM не может это ослабить
        (берём max торможения rules vs LLM).
        """
        raw = ""
        # safety floor
        safety = rules_module.make_decision(symbol, state, market, news, full_config)
        try:
            user_prompt = self._build_user_prompt(symbol, state, market, news, tactic, history)
            resp = self._client.chat.completions.create(
                model=self._cfg.get("model", "anthropic/claude-sonnet-4-6"),
                max_tokens=self._cfg.get("max_tokens", 512),
                temperature=self._cfg.get("temperature", 0.0),
                timeout=self._cfg.get("timeout_sec", 45),
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": user_prompt}],
            )
            raw = (resp.choices[0].message.content or "").strip()
            llm = self._parse_response(symbol, raw)
            _log.info("%s LLM: action=%s conf=%.2f (safety=%s)", symbol, llm.action,
                      llm.confidence, safety.action)

            # Opus escalation on aggressive LLM action
            escal_cfg = full_config.get("escalation", {}) or {}
            llm, raw, _ = self._maybe_escalate(symbol, llm, raw, user_prompt, escal_cfg, full_config)

            # Safety floor: если safety жёстче LLM — берём safety (LLM не снимает тормоз)
            final = self._merge_safety(safety, llm)
            if final.action != llm.action:
                _log.info("%s safety-floor override: LLM=%s -> final=%s", symbol,
                          llm.action, final.action)
            return final, raw
        except Exception as exc:
            _log.warning("%s LLM failed (%s) — rules decision: %s", symbol, exc, safety.action)
            return safety, raw

    def _merge_safety(self, safety: Decision, llm: Decision) -> Decision:
        """Safety floor: LLM не может ослабить критическое rules-решение."""
        rank = {"ALLOW": 0, "BRAKE_LIGHT": 1, "BRAKE_MODERATE": 2, "BRAKE_HEAVY": 3,
                "LONG_ONLY": 2, "SHORT_ONLY": 2, "KILL_NEW": 4}
        if rank.get(safety.action, 0) >= rank.get(llm.action, 0):
            # safety жёстче или равно — берём safety, но reason сохраняем LLM-ный если совпадает уровень
            return Decision(symbol=safety.symbol, action=safety.action,
                            reason=f"[safety] {safety.reason}" if safety.action != llm.action
                                  else llm.reason,
                            duration_minutes=safety.duration_minutes,
                            confidence=max(safety.confidence, llm.confidence))
        return llm

    def _maybe_escalate(self, symbol, sonnet_dec, sonnet_raw, user_prompt,
                        escal_cfg, full_config):
        if not escal_cfg.get("enabled", False):
            return sonnet_dec, sonnet_raw, False
        if sonnet_dec.action not in _ESCALATION_ACTIONS:
            return sonnet_dec, sonnet_raw, False
        if sonnet_dec.confidence >= float(escal_cfg.get("conf_threshold", 0.85)):
            return sonnet_dec, sonnet_raw, False
        opus_cfg = full_config.get("opus", {}) or {}
        if not opus_cfg:
            return sonnet_dec, sonnet_raw, False
        try:
            resp = self._client.chat.completions.create(
                model=opus_cfg.get("model", "anthropic/claude-opus-4-8"),
                max_tokens=opus_cfg.get("max_tokens", 512),
                temperature=opus_cfg.get("temperature", 0.0),
                timeout=opus_cfg.get("timeout_sec", 60),
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": user_prompt}],
            )
            opus_raw = (resp.choices[0].message.content or "").strip()
            opus_dec = self._parse_response(symbol, opus_raw)
            _log.info("%s OPUS: action=%s conf=%.2f", symbol, opus_dec.action, opus_dec.confidence)
        except Exception as exc:
            _log.warning("%s Opus escalation failed (%s) — keeping Sonnet", symbol, exc)
            return sonnet_dec, sonnet_raw, False
        if opus_dec.action == sonnet_dec.action:
            return opus_dec, f"SONNET:\n{sonnet_raw}\n\nOPUS:\n{opus_raw}", True
        downgrade = escal_cfg.get("downgrade_to", "BRAKE_HEAVY")
        downgraded = Decision(symbol=sonnet_dec.symbol, action=downgrade,
                              reason=(f"DOWNGRADED {sonnet_dec.action} by Opus "
                                      f"({opus_dec.action}). {sonnet_dec.reason}"),
                              duration_minutes=max(60, sonnet_dec.duration_minutes // 2),
                              confidence=min(sonnet_dec.confidence, opus_dec.confidence))
        return downgraded, f"SONNET:\n{sonnet_raw}\n\nOPUS:\n{opus_raw}", True

    def _build_user_prompt(self, symbol, state, market, news, tactic, history):
        acc = state.account
        sym = next((s for s in state.symbols if s.symbol == symbol), None)
        pos = sym.positions if sym else None

        def _tf(name):
            if market and name in market.timeframes:
                tf = market.timeframes[name]
                return str(tf.trend), f"{tf.rsi:.1f}", f"{tf.atr:.5f}"
            return "n/a", "n/a", "n/a"
        h1_t, h1_r, h1_a = _tf("H1")
        h4_t, h4_r, h4_a = _tf("H4")
        d1_t, d1_r, d1_a = _tf("D1")
        news_text = format_news_list(news) if news.upcoming else "  (нет событий в горизонте)"
        history_section = ""
        if history:
            history_section = "ИСТОРИЯ РЕШЕНИЙ (24ч):\n" + "\n".join(
                f"  {h['ts']} {h['action']} ({h['conf']:.2f}): {h['reason']}" for h in history
            ) + "\n\n"
        return _USER_PROMPT.format(
            timestamp_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            balance=f"{acc.balance:.2f}", equity=f"{acc.equity:.2f}",
            drawdown_pct=f"{acc.drawdown_pct:.2f}", margin_level_pct=f"{acc.margin_level_pct:.1f}",
            floating_pnl=f"{acc.floating_pnl:.2f}", symbol=symbol, tactic=tactic,
            magic=(sym.magic if sym else 0),
            buy_count=pos.buy_count if pos else 0,
            buy_volume=f"{pos.buy_volume:.2f}" if pos else "0.00",
            buy_avg_price=f"{pos.buy_avg_price:.5f}" if pos else "0.00000",
            sell_count=pos.sell_count if pos else 0,
            sell_volume=f"{pos.sell_volume:.2f}" if pos else "0.00",
            sell_avg_price=f"{pos.sell_avg_price:.5f}" if pos else "0.00000",
            floating_profit=f"{pos.floating_profit:.2f}" if pos else "0.00",
            baskets_open=(sym.baskets_open if sym else 0),
            last_action=(sym.last_action if sym else ""),
            heartbeat_age=f"{sym.heartbeat_age_sec:.0f}" if sym else -1,
            h1_trend=h1_t, h1_rsi=h1_r, h1_atr=h1_a,
            h4_trend=h4_t, h4_rsi=h4_r, h4_atr=h4_a,
            d1_trend=d1_t, d1_rsi=d1_r, d1_atr=d1_a,
            d1_atr_avg=f"{market.atr_d1_avg_30d:.5f}" if market else "n/a",
            atr_burst=str(market.atr_burst) if market else "n/a",
            last_d1_size=f"{market.last_d1_candle_size_atr:.2f}" if market else "n/a",
            impulse_detected=str(market.impulse_detected) if market else "n/a",
            spread_points=(market.spread_points if market else 0),
            history_section=history_section, news_list=news_text,
        )

    def _parse_response(self, symbol, raw) -> Decision:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            start = next((i for i, ln in enumerate(lines) if ln.strip().startswith("{")), 1)
            end = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip().endswith("}")),
                       len(lines) - 1)
            text = "\n".join(lines[start:end + 1])
        data = json.loads(text)
        action = str(data["action"]).strip()
        if action not in ALL_ACTIONS:
            raise ValueError(f"Unknown action: {action!r}")
        return Decision(symbol=symbol, action=action,
                        reason=str(data.get("reason", ""))[:300],
                        duration_minutes=int(data.get("duration_minutes", 0)),
                        confidence=float(data.get("confidence", 0.5)))