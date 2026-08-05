#!/usr/bin/env python3
"""supervisor.py — главный цикл Hermes FX AI Supervisor.

Раз в decision_interval_min:
  1. Подключаемся к MT5 (терминал Hermes FX deploy).
  2. Для каждой пары: читаем state (MT5 positions + heartbeat), market (TF), news.
  3. Rules = safety floor (детерминированно). LLM (Sonnet) = контекст-решение.
     Safety floor: LLM не может ослабить критическое rules-решение.
     Opus-эскалация при KILL_NEW с conf<порога.
  4. Пишем permissions_<sym>.json (atomic). EA читает на следующем H1-баре.
  5. Пишем supervisor_heartbeat.json (мониторинг).

Constrictive-only (Bridge.mqh инвариант): только тормозим/стопаем новые входы,
позиции не закрываем. «Полный газ» = ALLOW = risk_multiplier=1.0 = валидированный baseline.

Использование:
  py -3 supervisor.py --config config.yaml --once     # разовый прогон (debug)
  py -3 supervisor.py --config config.yaml             # цикл (cron/scheduled task)
  py -3 supervisor.py --config config.yaml --dry-run  # не писать permissions (только лог)
"""
import argparse
import json
import logging
import logging.config
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from models import State, SymbolState, AccountInfo, Decision
from mt5_state import MT5StateReader, DEPLOY_MAGIC_BASE, DEPLOY_TACTIC
from news import NewsProvider
from bridge import HermesBridge
from agent import AIAgent
import rules as rules_module

logger = logging.getLogger("hermes_supervisor")

# tactic -> display name (для permissions + prompt)
TACTIC_NAMES = {"C1": "C1_TrendPullback", "C2": "C2_RangeReversion", "S1": "S1_EMA_VWAP",
                "S2": "S2_DualMode", "S3": "S3_UTBot_ADX", "S4": "S4_MadCharts",
                "S5": "S5_UTBot_STC", "S6": "S6_NY_ORB", "S7": "S7_GateBreaker",
                "S8": "S8_SmartTrend"}


def setup_logging(log_cfg: dict):
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt)
    if log_cfg.get("folder"):
        fh = logging.FileHandler(Path(log_cfg["folder"]) / "supervisor.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt))
        logging.getLogger().addHandler(fh)


def build_state(reader: MT5StateReader, bridge: HermesBridge, symbols: list) -> State:
    acc = reader.read_account()
    sym_states = []
    for sym in symbols:
        magic_base = DEPLOY_MAGIC_BASE.get(sym, 0)
        tactic = DEPLOY_TACTIC.get(sym, "")
        if not tactic:
            continue
        st = reader.read_symbol_state(sym, magic_base, tactic)
        hb = bridge.read_heartbeat(sym)
        if hb:
            st.heartbeat_alive = not hb.get("_stale", False)
            st.heartbeat_age_sec = hb.get("age_sec", 0.0)
            st.baskets_open = hb.get("baskets", st.baskets_open)
            st.last_action = hb.get("last_action", "")
        else:
            st.heartbeat_alive = False
            st.heartbeat_age_sec = -1.0
        sym_states.append(st)
    return State(timestamp_utc=datetime.now(timezone.utc), account=acc, symbols=sym_states)


def run_cycle(config: dict, reader: MT5StateReader, bridge: HermesBridge,
              agent, news_prov: NewsProvider, dry_run: bool, rules_only: bool) -> list:
    symbols = config["agent"]["symbols"]
    timeframes = config.get("market", {}).get("timeframes", ["H1", "H4", "D1"])
    decisions = []
    state = build_state(reader, bridge, symbols)
    logger.info("Cycle start: %d symbols, equity=%.2f DD=%.2f%% margin=%.1f%%",
                len(symbols), state.account.equity, state.account.drawdown_pct,
                state.account.margin_level_pct)

    # ── ПОРТФЕЛЬНЫЙ АВАРИЙНЫЙ СТОП ───────────────────────────────────────
    # Просадка и маржа — величины СЧЁТА, а не символа. Пять независимых
    # решений по символам не складываются в одно портфельное: каждое видит
    # только свою пару. Поэтому счётный порог обрабатывается здесь, одним
    # глобальным файлом, который EA применяет ко всем парам сразу.
    #
    # Раньше write_global_kill() существовал, но не вызывался ниоткуда, и даже
    # при вызове не сработал бы: EA читал персональный файл вместо глобального.
    # Исправлено с обеих сторон (Bridge.mqh: строжайшее побеждает).
    thr = config.get("risk_thresholds", {})
    kill_dd = thr.get("drawdown_kill_pct", 6.0)
    kill_margin = thr.get("margin_kill_pct", 200)
    acc = state.account
    breach = None
    if acc.drawdown_pct >= kill_dd:
        breach = f"Просадка счёта {acc.drawdown_pct:.2f}% >= {kill_dd}%"
    elif 0 < acc.margin_level_pct < kill_margin:
        breach = f"Маржа {acc.margin_level_pct:.0f}% < {kill_margin}%"

    if breach:
        logger.error("ПОРТФЕЛЬНЫЙ СТОП: %s — глобальный запрет новых входов", breach)
        if not dry_run:
            bridge.write_global_kill(breach)
        decisions.append({"symbol": "*", "action": "KILL_NEW", "reason": breach,
                          "confidence": 1.0})
    else:
        # Снимаем глобальный запрет ТОЛЬКО когда порог больше не нарушен.
        # Персональные решения при этом продолжают действовать: глобальный
        # файл никогда не был разрешением, он был только запретом.
        if not dry_run:
            bridge.clear_global()

    for sym in symbols:
        tactic = DEPLOY_TACTIC.get(sym)
        if not tactic:
            continue
        try:
            market = reader.read_market(sym, timeframes)
            news = news_prov.get_context(sym, config.get("news", {}).get("hours_ahead", 4))
            if rules_only:
                dec = rules_module.make_decision(sym, state, market, news, config)
                raw = ""
            else:
                dec, raw = agent.decide(sym, state, market, news, config, tactic)
            decisions.append({"symbol": sym, "action": dec.action, "reason": dec.reason,
                              "confidence": dec.confidence})
            logger.info("  %s %s [%s]: %s (conf=%.2f) — %s", sym, tactic,
                        ("DRY" if dry_run else "WROTE"), dec.action, dec.confidence, dec.reason)
            if not dry_run:
                bridge.write_permissions(sym, dec, TACTIC_NAMES[tactic])
        except Exception as exc:
            # НЕ ПИШЕМ НИЧЕГО. Раньше здесь писался ALLOW с рассуждением
            # «лучше пропустить, чем ложно убить» — но это не «не вмешиваться»,
            # а активно поставить полный газ. Сценарий: цикл N видит опасный
            # режим и ставит BRAKE_HEAVY (0.2); цикл N+1 падает на чтении MT5
            # и переписывает файл на 1.0. Рынок прежний, тормоз снят ошибкой.
            #
            # Оставляя файл нетронутым, мы сохраняем последнее ОСОЗНАННОЕ
            # решение до следующего успешного цикла. Это и есть «не вмешиваться».
            logger.error("  %s: decision failed (%s) — файл НЕ трогаем, "
                         "остаётся прошлое решение", sym, exc)
            decisions.append({"symbol": sym, "action": "KEEP_PREVIOUS",
                              "reason": f"error: {exc}"[:200], "confidence": 0.0})

    if not dry_run:
        bridge.write_supervisor_heartbeat("OK", decisions)
    return decisions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--once", action="store_true", help="разовый цикл (debug)")
    ap.add_argument("--dry-run", action="store_true", help="не писать permissions")
    ap.add_argument("--rules-only", action="store_true",
                    help="обход LLM: только детерминированные rules (no API cost)")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    config = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    setup_logging(config.get("logging", {}))

    bridge_folder = config["bridge"]["folder"]
    data_path = config["bridge"].get("mt5_data_path")
    interval_min = config["agent"].get("decision_interval_min", 60)

    bridge = HermesBridge(bridge_folder, config["bridge"].get("state_max_age_sec", 300))
    news_prov = NewsProvider(config.get("news", {}), cache_dir=str(cfg_path.parent / "cache"))
    agent = None if args.rules_only else AIAgent(config.get("sonnet", {}))
    reader = MT5StateReader(data_path)

    if not reader.connect():
        logger.error("MT5 connect failed — exiting. Проверь mt5_data_path в config.")
        sys.exit(2)
    logger.info("MT5 connected: %s | rules_only=%s dry_run=%s",
                data_path or "default terminal", args.rules_only, args.dry_run)

    try:
        if args.once:
            run_cycle(config, reader, bridge, agent, news_prov, args.dry_run, args.rules_only)
        else:
            while True:
                try:
                    run_cycle(config, reader, bridge, agent, news_prov,
                              args.dry_run, args.rules_only)
                except Exception as exc:
                    logger.error("Cycle error: %s", exc, exc_info=True)
                logger.info("Sleep %d min until next cycle", interval_min)
                time.sleep(interval_min * 60)
    finally:
        reader.shutdown()


if __name__ == "__main__":
    main()