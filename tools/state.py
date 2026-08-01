#!/usr/bin/env python3
"""Multi-instrument state/gate for XAU AI trader (account YOUR_MT5_LOGIN).

Usage:
  py -3 state.py gate          -> hard-limit gate verdict
  py -3 state.py positions     -> open positions (all symbols)
  py -3 state.py window [SYM]  -> is now inside trading window for SYM (or all)
"""
import sys, os, datetime, MetaTrader5 as mt5

EXE = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")
INSTRUMENTS = ["XAUUSD", "EURUSD", "USDJPY", "USDCAD", "GBPJPY"]
REGIMES = {"XAUUSD": "TREND", "EURUSD": "COUNTER", "USDJPY": "TREND", "USDCAD": "TREND", "GBPJPY": "TREND"}
WIN_START = {"XAUUSD": 7, "EURUSD": 6, "USDJPY": 6, "USDCAD": 6, "GBPJPY": 6}
WIN_END   = {"XAUUSD": 20, "EURUSD": 22, "USDJPY": 22, "USDCAD": 22, "GBPJPY": 22}

RISK_PER_TRADE_MAX = 0.0025
DAILY_LOSS_HALT = 0.01
MAX_NEW_TRADES_DAY = 4
MAX_POSITIONS = 1

JOURNAL_CSV = None  # set below
import os
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
JOURNAL_CSV = os.path.join(SKILL_DIR, "journal", "trades.csv")
PEAK_FILE = os.path.join(SKILL_DIR, "peak_equity.txt")
SOD_FILE = os.path.join(SKILL_DIR, "sod_equity.txt")


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def cmd_gate():
    mt5.shutdown()
    import time; time.sleep(0.3)
    if not mt5.initialize(path=EXE):
        print("INIT FAIL:", mt5.last_error()); sys.exit(2)
    ai = mt5.account_info()
    all_pos = mt5.positions_get() or ()
    mt5.shutdown()

    now = now_utc()
    weekday = now.strftime("%A")
    is_friday = weekday == "Friday"
    fri_no_new = is_friday and now.hour >= 19
    fri_must_close = is_friday and (now.hour > 19 or (now.hour == 19 and now.minute >= 30))

    # Per-instrument window
    for sym in INSTRUMENTS:
        in_win = WIN_START[sym] <= now.hour < WIN_END[sym]
        blocked = fri_no_new or not in_win
        print(f"  {sym:7s} {REGIMES[sym]:7s} {'BLOCKED' if blocked else 'OPEN'}")

    # SOD
    import json
    today = now.date().isoformat()
    try:
        d = json.loads(open(SOD_FILE).read()) if os.path.exists(SOD_FILE) else {}
    except:
        d = {}
    if d.get("date") != today:
        d = {"date": today, "equity": ai.equity}
        open(SOD_FILE, "w").write(json.dumps(d))
    sod = d["equity"]

    # Peak
    try:
        peak_d = json.loads(open(PEAK_FILE).read()) if os.path.exists(PEAK_FILE) else {}
    except:
        peak_d = {}
    peak = max(float(peak_d.get("peak", ai.equity)), ai.equity)
    peak_d["peak"] = peak
    open(PEAK_FILE, "w").write(json.dumps(peak_d))
    dd = (peak - ai.equity) / peak if peak else 0.0

    # Trades today
    import csv as csvmod
    trades_today = 0
    if os.path.exists(JOURNAL_CSV):
        with open(JOURNAL_CSV, newline="") as f:
            for row in csvmod.DictReader(f):
                if row.get("entry_date", "").startswith(today) and row.get("action") == "OPEN":
                    trades_today += 1

    print(f"  eq={ai.equity:.2f} sod={sod:.2f} peak={peak:.2f} DD={dd*100:.2f}%")
    print(f"  positions={len(all_pos)} trades_today={trades_today}/{MAX_NEW_TRADES_DAY} fri={is_friday}")

    if dd >= 0.05:
        print("VERDICT: FORCE_FLAT")
    elif len(all_pos) >= 1 or trades_today >= MAX_NEW_TRADES_DAY or dd >= 0.04:
        print("VERDICT: HALT_NEW")
    elif fri_no_new:
        print("VERDICT: HALT_NEW (Friday cutoff)")
    else:
        print("VERDICT: NEW_TRADES_OK")


def cmd_positions():
    mt5.shutdown()
    import time; time.sleep(0.3)
    if not mt5.initialize(path=EXE):
        print("INIT FAIL:", mt5.last_error()); sys.exit(2)
    ps = mt5.positions_get() or ()
    mt5.shutdown()
    if not ps:
        print("no open positions"); return
    print(f"=== {len(ps)} OPEN POSITION(S) ===")
    for p in ps:
        side = "BUY" if p.type == 0 else "SELL"
        print(f"ticket={p.ticket} {side} {p.symbol} vol={p.volume} open={p.price_open} sl={p.sl} tp={p.tp} profit={p.profit:.2f}")


def cmd_window(sym=None):
    now = now_utc()
    if sym:
        syms = [sym]
    else:
        syms = INSTRUMENTS
    for s in syms:
        in_win = WIN_START[s] <= now.hour < WIN_END[s]
        print(f"  {s:7s} {'OPEN' if in_win else 'CLOSED'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "gate"
    if cmd == "gate":
        cmd_gate()
    elif cmd == "positions":
        cmd_positions()
    elif cmd == "window":
        sym = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_window(sym)
    else:
        print(f"unknown: {cmd}. Use: gate | positions | window [SYM]")