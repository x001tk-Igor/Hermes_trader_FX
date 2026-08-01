#!/usr/bin/env python3
"""Multi-instrument cycle scanner for XAU AI trader.

Scans all 5 instruments in one tool call, returns compact summary.
Checks: gate, market (bid/ask/spread/ATR), positions, Asian range.

Usage: py -3 cycle_multi.py
Output: One line per instrument + gate + positions summary.
"""
import os, sys, datetime, json
import MetaTrader5 as mt5

EXE = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")
INSTRUMENTS = ["XAUUSD", "EURUSD", "USDJPY", "USDCAD", "GBPJPY"]
REGIMES = {"XAUUSD": "TREND", "EURUSD": "COUNTER", "USDJPY": "TREND", "USDCAD": "TREND", "GBPJPY": "TREND"}

# Windows UTC
WIN_START = {"XAUUSD": 7, "EURUSD": 6, "USDJPY": 6, "USDCAD": 6, "GBPJPY": 6}
WIN_END   = {"XAUUSD": 20, "EURUSD": 22, "USDJPY": 22, "USDCAD": 22, "GBPJPY": 22}

def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)

def in_window(sym, now):
    return WIN_START[sym] <= now.hour < WIN_END[sym]

def main():
    mt5.shutdown()
    import time; time.sleep(0.3)
    if not mt5.initialize(path=EXE):
        print(f"INIT FAIL: {mt5.last_error()}")
        return

    now = now_utc()
    ai = mt5.account_info()
    weekday = now.strftime("%A")
    is_friday = weekday == "Friday"

    # Positions
    all_pos = mt5.positions_get() or ()
    pos_by_sym = {}
    for p in all_pos:
        pos_by_sym.setdefault(p.symbol, []).append(p)

    # Account summary
    print(f"[{now.strftime('%H:%M')}Z {weekday}] eq={ai.equity:.0f} bal={ai.balance:.0f} pos={len(all_pos)}")

    # Friday cutoff
    fri_no_new = is_friday and now.hour >= 19
    fri_close = is_friday and now.hour >= 19 and now.minute >= 30

    # Per-instrument scan
    for sym in INSTRUMENTS:
        if not mt5.symbol_select(sym, True):
            print(f"  {sym}: SELECT FAIL")
            continue

        info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        if not tick or tick.bid == 0:
            print(f"  {sym}: NO TICK (market closed?)")
            continue

        spread = round(tick.ask - tick.bid, info.digits)
        spread_ok = spread < (0.35 if sym == "XAUUSD" else 0.0005)  # FX: 5 pips
        win = in_window(sym, now)
        has_pos = sym in pos_by_sym

        # ATR(14) on M15
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 200)
        atr = 0
        if rates is not None and len(rates) > 14:
            import numpy as np
            h = np.array([r['high'] for r in rates])
            l = np.array([r['low'] for r in rates])
            c = np.array([r['close'] for r in rates])
            tr = np.maximum(h[1:]-l[1:], np.maximum(abs(h[1:]-c[:-1]), abs(l[1:]-c[:-1])))
            atr = float(tr[-14:].mean())

        # Asian range (00:00-07:00 UTC today)
        today = now.date()
        asian_bars = [r for r in rates if datetime.datetime.fromtimestamp(r['time'], datetime.timezone.utc).date() == today and 0 <= datetime.datetime.fromtimestamp(r['time'], datetime.timezone.utc).hour < 7] if rates is not None else []
        asian_h = max(r['high'] for r in asian_bars) if asian_bars else 0
        asian_l = min(r['low'] for r in asian_bars) if asian_bars else 0

        # H1 EMA proxy
        h1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 220)
        h1_ema50 = h1_ema200 = 0
        if h1 is not None and len(h1):
            cc = np.array([r['close'] for r in h1])
            h1_ema50 = float(cc[-50:].mean())
            h1_ema200 = float(cc[-200:].mean()) if len(cc) >= 200 else float(cc.mean())

        # Status
        regime = REGIMES[sym]
        status = "OPEN" if win else "CLOSED"
        if fri_no_new:
            status = "FRI_NO_NEW"
        if fri_close:
            status = "FRI_CLOSE"

        # Position info
        pos_str = ""
        if has_pos:
            for p in pos_by_sym[sym]:
                side = "BUY" if p.type == 0 else "SELL"
                pos_str = f" POS:{side}@{p.volume}@{p.price_open} PnL={p.profit:.0f}"

        # Spread verdict
        sp_verdict = "OK" if spread_ok else "HIGH"

        print(f"  {sym:7s} {regime:6s} {status:10s} bid={tick.bid} sp={spread} spv={sp_verdict} ATR={atr:.2f} AsianH={asian_h} L={asian_l} H1ema50={h1_ema50:.2f} ema200={h1_ema200:.2f}{pos_str}")

    # Gate verdict
    can_trade = not fri_no_new
    print(f"  GATE: {'NEW_OK' if can_trade else 'HALT'} trades_today={0} fri={is_friday}")

    mt5.shutdown()

if __name__ == "__main__":
    main()