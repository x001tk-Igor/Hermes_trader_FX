#!/usr/bin/env python3
"""test_format.py — валидация что permissions_<sym>.json, который пишет supervisor,
корректно парсится Bridge.mqh (подстроками).

Bridge.mqh:87-112 ищет подстроки:
  "trading_enabled": false   /  "trading_enabled":false
  "risk_multiplier" : <val>  (0<v<1)
  "<TacticName>": false       (per-tactic disable)
  "allowed_direction": "long" / "allowed_direction": "short"

Этот тест прогоняет все 7 действий и проверяет, что Bridge.mqh-парсер извлечёт
ожидаемые рычаги. Запускать без MT5 / без API — чистая логика.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from models import Decision, decision_to_permissions


# эмуляция Bridge.mqh ReadPermissions парсера (подстроками)
def bridge_parse(body: str):
    p = {"trading_enabled": True, "risk_multiplier": 1.0,
         "allowed_direction": "none", "tactic_disabled": []}
    if '"trading_enabled": false' in body or '"trading_enabled":false' in body:
        p["trading_enabled"] = False
    import re
    m = re.search(r'"risk_multiplier"\s*:\s*([0-9.]+)', body)
    if m:
        try:
            v = float(m.group(1))
            if 0.0 < v < 1.0:
                p["risk_multiplier"] = v
        except ValueError:
            pass
    if '"allowed_direction": "long"' in body:
        p["allowed_direction"] = "long"
    elif '"allowed_direction": "short"' in body:
        p["allowed_direction"] = "short"
    return p


CASES = [
    ("ALLOW",          "S8_SmartTrend",      {"trading_enabled": True,  "risk_multiplier": 1.0, "allowed_direction": "none"}),
    ("BRAKE_LIGHT",    "S8_SmartTrend",      {"trading_enabled": True,  "risk_multiplier": 0.6, "allowed_direction": "none"}),
    ("BRAKE_MODERATE", "S2_DualMode",        {"trading_enabled": True,  "risk_multiplier": 0.4, "allowed_direction": "none"}),
    ("BRAKE_HEAVY",    "C2_RangeReversion",  {"trading_enabled": True,  "risk_multiplier": 0.2, "allowed_direction": "none"}),
    ("LONG_ONLY",      "S6_NY_ORB",          {"trading_enabled": True,  "risk_multiplier": 1.0, "allowed_direction": "long"}),
    ("SHORT_ONLY",     "S6_NY_ORB",          {"trading_enabled": True,  "risk_multiplier": 1.0, "allowed_direction": "short"}),
    ("KILL_NEW",       "S8_SmartTrend",      {"trading_enabled": False, "risk_multiplier": 1.0, "allowed_direction": "none"}),
]



# ─────────────────────────────────────────────────────────────────────────────
# ОБЪЕДИНЕНИЕ ДВУХ ФАЙЛОВ: глобального и по символу.
#
# Регресс, найденный аудитом 2026-08-05: EA читал персональный файл ВМЕСТО
# глобального. Управляющий переписывает персональные файлы каждый цикл, поэтому
# глобальный аварийный стоп перекрывался персональным ALLOW на следующем круге —
# стоп существовал и не останавливал.
#
# Теперь Bridge.mqh читает ОБА и применяет «побеждает строжайшее». Эти тесты
# фиксируют именно то свойство, ради которого правка делалась: результат НЕ
# зависит от порядка чтения файлов.
# ─────────────────────────────────────────────────────────────────────────────

def bridge_apply(body: str, p: dict) -> dict:
    """Эмуляция ApplyPermissionFile: только ужесточает, никогда не ослабляет."""
    import re
    if '"trading_enabled": false' in body or '"trading_enabled":false' in body:
        p["trading_enabled"] = False
    m = re.search(r'"risk_multiplier"\s*:\s*([0-9.]+)', body)
    if m:
        v = float(m.group(1))
        if 0.0 < v < 1.0 and v < p["risk_multiplier"]:
            p["risk_multiplier"] = v
    want = None
    if '"allowed_direction": "long"' in body:
        want = "long"
    elif '"allowed_direction": "short"' in body:
        want = "short"
    if want:
        if p["allowed_direction"] == "none":
            p["allowed_direction"] = want
        elif p["allowed_direction"] != want:
            # конфликт: разрешённого направления не осталось
            p["allowed_direction"] = "none"
            p["trading_enabled"] = False
    return p


def bridge_read(global_body, symbol_body, order="global_first"):
    p = {"trading_enabled": True, "risk_multiplier": 1.0,
         "allowed_direction": "none", "tactic_disabled": []}
    files = [global_body, symbol_body]
    if order == "symbol_first":
        files.reverse()
    for b in files:
        if b is not None:
            p = bridge_apply(b, p)
    return p


def j(**kw):
    return json.dumps(kw, ensure_ascii=False, indent=2)


COMBINE_CASES = [
    # (описание, глобальный, по символу, ожидание)
    ("global KILL перекрывает symbol ALLOW",
     j(trading_enabled=False),
     j(trading_enabled=True, risk_multiplier=1.0),
     {"trading_enabled": False}),

    ("нет глобального — работает персональный",
     None,
     j(trading_enabled=True, risk_multiplier=0.4),
     {"trading_enabled": True, "risk_multiplier": 0.4}),

    ("нет файлов вовсе — полное разрешение (тестер)",
     None, None,
     {"trading_enabled": True, "risk_multiplier": 1.0}),

    ("берётся МЕНЬШИЙ множитель, а не последний",
     j(trading_enabled=True, risk_multiplier=0.2),
     j(trading_enabled=True, risk_multiplier=0.6),
     {"risk_multiplier": 0.2}),

    ("множитель >= 1.0 не поднимает риск",
     j(trading_enabled=True, risk_multiplier=0.4),
     j(trading_enabled=True, risk_multiplier=1.0),
     {"risk_multiplier": 0.4}),

    ("противоречие направлений = входов нет",
     j(trading_enabled=True, allowed_direction="long"),
     j(trading_enabled=True, allowed_direction="short"),
     {"trading_enabled": False, "allowed_direction": "none"}),

    ("одно направление проходит",
     None,
     j(trading_enabled=True, allowed_direction="long"),
     {"trading_enabled": True, "allowed_direction": "long"}),
]


def test_combine():
    fails = 0
    print("\n--- объединение global + per-symbol (строжайшее побеждает) ---")
    for name, g, sy, expected in COMBINE_CASES:
        a = bridge_read(g, sy, "global_first")
        b = bridge_read(g, sy, "symbol_first")

        ok_expect = all(a[k] == v for k, v in expected.items())
        # ГЛАВНОЕ свойство: порядок чтения не влияет на результат
        ok_order = (a == b)

        status = "OK" if (ok_expect and ok_order) else "FAIL"
        if not (ok_expect and ok_order):
            fails += 1
        print(f"  [{status}] {name}")
        if not ok_expect:
            print(f"        ожидалось {expected}, получено {a}")
        if not ok_order:
            print(f"        ПОРЯДОК ВЛИЯЕТ: global_first={a} symbol_first={b}")
    return fails


def main():
    fails = 0
    for action, tactic, expected in CASES:
        dec = Decision(symbol="TEST", action=action, reason="test", duration_minutes=60,
                       confidence=0.9)
        perm = decision_to_permissions(dec, tactic)
        # сериализуем как bridge.write_permissions
        body = {"trading_enabled": perm.get("trading_enabled", True),
                "risk_multiplier": perm.get("risk_multiplier", 1.0)}
        if "allowed_direction" in perm:
            body["allowed_direction"] = perm["allowed_direction"]
        body["_meta"] = {"action": action, "reason": dec.reason}
        text = json.dumps(body, ensure_ascii=False, indent=2)
        parsed = bridge_parse(text)
        ok = all(parsed[k] == v for k, v in expected.items())
        status = "OK" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"  [{status}] {action:14s} -> risk={parsed['risk_multiplier']} "
              f"trade={parsed['trading_enabled']} dir={parsed['allowed_direction']}")
        if not ok:
            print(f"       expected: {expected}")
            print(f"       parsed:   {parsed}")
            print(f"       json: {text}")
    print()
    fails += test_combine()

    if fails:
        print(f"FAILED: {fails}/{len(CASES)} cases")
        sys.exit(1)
    print(f"ALL {len(CASES)} CASES PASS — permissions format совместим с Bridge.mqh")


if __name__ == "__main__":
    main()