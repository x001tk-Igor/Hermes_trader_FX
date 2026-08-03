#!/usr/bin/env python3
"""Multi-instrument state/gate for AI trader (account YOUR_MT5_LOGIN).

v3 — 6 FX pairs, averaging support.

Usage:
  py -3 state.py gate              -> hard-limit gate verdict
  py -3 state.py positions         -> open positions (all symbols)
  py -3 state.py window [SYM]      -> is now inside trading window for SYM (or all)
  py -3 state.py avg-positions SYM -> all positions for symbol with grouping
  py -3 state.py avg-risk SYM      -> total risk/PnL for symbol's averaging group
  py -3 state.py dd-monitor        -> check 1.7% DD stop for all symbols with positions
  py -3 state.py market [SYM]      -> market data: bid/ask/spread/ATR/EMA/ADX
"""
import sys, os, datetime, json, csv as csvmod
import MetaTrader5 as mt5

EXE = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")

# v3 instruments
INSTRUMENTS = ["EURUSD", "GBPUSD", "USDCAD", "EURGBP", "NZDCAD", "EURAUD"]
REGIMES = {s: "TREND" for s in INSTRUMENTS}
WIN_START = {s: 5 for s in INSTRUMENTS}
WIN_END = {s: 20 for s in INSTRUMENTS}
CONTRACT = {s: 100000 for s in INSTRUMENTS}
DIGITS = {s: 5 for s in INSTRUMENTS}

# Risk limits (v3)
DAILY_LOSS_HALT = 0.03       # 3%
WEEKLY_LOSS_HALT = 0.05      # 5%
DD_HALT5 = 0.05              # 5%
MAX_NEW_TRADES_DAY = 8
AVG_DD_STOP = 0.025          # 2.5% per symbol
AVG_MAX_POSITIONS = 3

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
JOURNAL_CSV = os.path.join(SKILL_DIR, "journal", "trades.csv")
PEAK_FILE = os.path.join(SKILL_DIR, "peak_equity.txt")
SOD_FILE = os.path.join(SKILL_DIR, "sod_equity.txt")


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def init_mt5():
    mt5.shutdown()
    import time; time.sleep(0.3)
    if not mt5.initialize(path=EXE):
        print("INIT FAIL:", mt5.last_error()); sys.exit(2)


def cmd_gate():
    init_mt5()
    ai = mt5.account_info()
    all_pos = mt5.positions_get() or ()
    mt5.shutdown()

    now = now_utc()
    weekday = now.strftime("%A")
    is_friday = weekday == "Friday"
    fri_no_new = is_friday and now.hour >= 19
    fri_must_close = is_friday and (now.hour > 19 or (now.hour == 19 and now.minute >= 30))

    for sym in INSTRUMENTS:
        in_win = WIN_START[sym] <= now.hour < WIN_END[sym]
        blocked = fri_no_new or not in_win
        print(f"  {sym:7s} {REGIMES[sym]:7s} {'BLOCKED' if blocked else 'OPEN'}")

    # SOD equity
    today = now.date().isoformat()
    try:
        d = json.loads(open(SOD_FILE).read()) if os.path.exists(SOD_FILE) else {}
    except:
        d = {}
    if d.get("date") != today:
        d = {"date": today, "equity": ai.equity}
        open(SOD_FILE, "w").write(json.dumps(d))
    sod = d["equity"]

    # Peak equity
    try:
        peak_d = json.loads(open(PEAK_FILE).read()) if os.path.exists(PEAK_FILE) else {}
    except:
        peak_d = {}
    peak = max(float(peak_d.get("peak", ai.equity)), ai.equity)
    peak_d["peak"] = peak
    open(PEAK_FILE, "w").write(json.dumps(peak_d))
    dd = (peak - ai.equity) / peak if peak else 0.0

    # Daily PnL
    daily_pnl_pct = (ai.equity - sod) / sod * 100 if sod else 0

    # Trades today
    trades_today = 0
    if os.path.exists(JOURNAL_CSV):
        with open(JOURNAL_CSV, newline="") as f:
            for row in csvmod.DictReader(f):
                if row.get("entry_date", "").startswith(today) and row.get("action") in ("OPEN", "ADDON"):
                    trades_today += 1

    # Count positions per symbol
    pos_by_sym = {}
    for p in all_pos:
        pos_by_sym[p.symbol] = pos_by_sym.get(p.symbol, 0) + 1

    print(f"  eq={ai.equity:.2f} sod={sod:.2f} peak={peak:.2f} DD={dd*100:.2f}% dailyPnL={daily_pnl_pct:+.2f}%")
    print(f"  positions={len(all_pos)} trades_today={trades_today}/{MAX_NEW_TRADES_DAY} fri={is_friday}")
    for sym, cnt in pos_by_sym.items():
        print(f"    {sym}: {cnt} positions")

    if dd >= DD_HALT5:
        print("VERDICT: FORCE_FLAT")
    elif daily_pnl_pct <= -DAILY_LOSS_HALT * 100:
        print("VERDICT: HALT_NEW (daily loss limit)")
    elif fri_no_new:
        print("VERDICT: HALT_NEW (Friday cutoff)")
    elif trades_today >= MAX_NEW_TRADES_DAY:
        print("VERDICT: HALT_NEW (max trades today)")
    else:
        print("VERDICT: NEW_TRADES_OK")


def cmd_positions():
    init_mt5()
    ps = mt5.positions_get() or ()
    mt5.shutdown()
    if not ps:
        print("no open positions"); return
    print(f"=== {len(ps)} OPEN POSITION(S) ===")
    for p in ps:
        side = "BUY" if p.type == 0 else "SELL"
        print(f"ticket={p.ticket} {side} {p.symbol} vol={p.volume} open={p.price_open} "
              f"sl={p.sl} tp={p.tp} profit={p.profit:.2f}")


def _get_positions_for_symbol(mt5, sym):
    """Get positions for a symbol, handling brokers where positions_get(sym) fails."""
    all_pos = mt5.positions_get()
    if not all_pos:
        return []
    return [p for p in all_pos if p.symbol == sym]


def cmd_avg_positions(sym):
    """Show all positions for a symbol, grouped as averaging set."""
    init_mt5()
    ps = _get_positions_for_symbol(mt5, sym)
    ai = mt5.account_info()
    mt5.shutdown()
    if not ps:
        print(f"no positions on {sym}"); return

    total_lot = sum(p.volume for p in ps)
    total_profit = sum(p.profit for p in ps)
    weighted_avg = sum(p.price_open * p.volume for p in ps) / total_lot

    print(f"=== {sym} AVERAGING GROUP ({len(ps)} positions) ===")
    for p in ps:
        side = "BUY" if p.type == 0 else "SELL"
        print(f"  ticket={p.ticket} {side} vol={p.volume} entry={p.price_open} "
              f"sl={p.sl} tp={p.tp} profit={p.profit:.2f}")
    print(f"  total_lot={total_lot:.2f} weighted_avg={weighted_avg:.5f} total_profit={total_profit:.2f}")
    print(f"  equity={ai.equity:.2f} profit_pct={total_profit/ai.equity*100:+.3f}%")


def cmd_avg_risk(sym, equity=None):
    """Calculate total risk/PnL for a symbol's averaging group."""
    init_mt5()
    ps = _get_positions_for_symbol(mt5, sym)
    ai = mt5.account_info()
    tick = mt5.symbol_info_tick(sym)
    mt5.shutdown()

    if not ps:
        print(f"no positions on {sym}"); return

    eq = equity or ai.equity
    total_profit = sum(p.profit for p in ps)
    total_profit_pct = total_profit / eq * 100

    # Get current price for unrealized calculation
    bid = tick.bid if tick else 0
    ask = tick.ask if tick else 0

    print(f"=== {sym} AVG RISK ===")
    print(f"  positions={len(ps)}/{AVG_MAX_POSITIONS}")
    print(f"  total_profit={total_profit:+.2f} ({total_profit_pct:+.3f}% of equity)")
    print(f"  dd_stop_limit={AVG_DD_STOP*100:.1f}% = ${eq*AVG_DD_STOP:.2f}")

    if total_profit_pct <= -AVG_DD_STOP * 100:
        print(f"  VERDICT: DD_STOP (loss {abs(total_profit_pct):.3f}% >= {AVG_DD_STOP*100:.1f}% limit)")
        print(f"  ACTION: CLOSE ALL {sym} positions")
    elif len(ps) >= AVG_MAX_POSITIONS:
        print(f"  VERDICT: MAX_POSITIONS (no more addons)")
    else:
        print(f"  VERDICT: OK (can add {AVG_MAX_POSITIONS - len(ps)} more positions)")


def cmd_dd_monitor():
    """Check DD stop for all symbols that have open positions."""
    init_mt5()
    all_pos = mt5.positions_get() or ()
    ai = mt5.account_info()
    mt5.shutdown()

    if not all_pos:
        print("no open positions — DD monitor OK"); return

    symbols_with_pos = set(p.symbol for p in all_pos)
    any_dd_stop = False

    print(f"=== DD MONITOR (equity={ai.equity:.2f}, limit={AVG_DD_STOP*100:.1f}%) ===")
    for sym in sorted(symbols_with_pos):
        init_mt5()
        ps = _get_positions_for_symbol(mt5, sym)
        mt5.shutdown()
        if not ps: continue

        total_profit = sum(p.profit for p in ps)
        pct = total_profit / ai.equity * 100
        status = "DD_STOP" if pct <= -AVG_DD_STOP * 100 else "OK"
        if status == "DD_STOP": any_dd_stop = True
        print(f"  {sym:7s} positions={len(ps)} pnl={total_profit:+.2f} ({pct:+.3f}%) → {status}")

    if any_dd_stop:
        print("ACTION: Close positions on DD_STOP symbols immediately")
    else:
        print("ALL OK — no DD stops triggered")


def cmd_market(sym=None):
    """Market data: bid/ask/spread/indicators for symbol(s)."""
    init_mt5()
    syms = [sym] if sym else INSTRUMENTS
    for s in syms:
        if s not in INSTRUMENTS:
            print(f"  {s}: not in instrument list"); continue
        tick = mt5.symbol_info_tick(s)
        if not tick:
            print(f"  {s}: no tick data"); continue

        # Get H1 bars for indicators
        rates = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, 250)
        if rates is None or len(rates) < 210:
            print(f"  {s}: not enough bars"); continue

        closes = [float(r[4]) for r in rates]
        bid, ask = tick.bid, tick.ask
        spread_points = int(tick.ask - tick.bid) * (10 ** DIGITS[s])

        # Simple EMA
        def ema(vals, period):
            k = 2 / (period + 1)
            out = [None] * len(vals)
            for i in range(period - 1, len(vals)):
                if i == period - 1:
                    out[i] = sum(vals[:period]) / period
                elif i >= period:
                    out[i] = vals[i] * k + out[i-1] * (1 - k)
            return out

        # ATR
        def atr(rates, period):
            trs = []
            for i in range(len(rates)):
                if i == 0:
                    trs.append(float(rates[i][2]) - float(rates[i][3]))
                else:
                    h, l, pc = float(rates[i][2]), float(rates[i][3]), float(rates[i-1][4])
                    trs.append(max(h-l, abs(h-pc), abs(l-pc)))
            out = [None] * len(trs)
            for i in range(period-1, len(trs)):
                if i == period-1:
                    out[i] = sum(trs[:period]) / period
                else:
                    out[i] = (out[i-1]*(period-1) + trs[i]) / period
            return out

        e20 = ema(closes, 20); e200 = ema(closes, 200)
        a14 = atr(rates, 14)

        i = len(closes) - 1
        ema20_val = e20[i]; ema200_val = e200[i]; atr_val = a14[i]
        trend = "UP" if ema20_val and ema200_val and ema20_val > ema200_val else \
                "DOWN" if ema20_val and ema200_val and ema20_val < ema200_val else "UNCLEAR"
        atr_pct = atr_val / closes[-1] * 100 if atr_val else 0
        spread_verdict = "OK" if spread_points <= 30 else "WIDE"

        print(f"  {s:7s} bid={bid:.5f} ask={ask:.5f} spread={spread_points}pts({spread_verdict}) "
              f"EMA20={ema20_val:.5f} EMA200={ema200_val:.5f} trend={trend} ATR={atr_val:.5f}({atr_pct:.2f}%)")

    mt5.shutdown()


def cmd_window(sym=None):
    now = now_utc()
    syms = [sym] if sym else INSTRUMENTS
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
    elif cmd == "avg-positions":
        sym = sys.argv[2] if len(sys.argv) > 2 else None
        if not sym: print("usage: avg-positions SYMBOL"); exit(1)
        cmd_avg_positions(sym)
    elif cmd == "avg-risk":
        sym = sys.argv[2] if len(sys.argv) > 2 else None
        if not sym: print("usage: avg-risk SYMBOL"); exit(1)
        cmd_avg_risk(sym)
    elif cmd == "dd-monitor":
        cmd_dd_monitor()
    elif cmd == "market":
        sym = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_market(sym)
    else:
        print(f"unknown: {cmd}. Use: gate | positions | window [SYM] | "
              f"avg-positions SYM | avg-risk SYM | dd-monitor | market [SYM]")