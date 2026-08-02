#!/usr/bin/env python3
"""
Position Acceleration simulator: tests pyramid-into-profit vs averaging-down.

Method:
  1. Entry: 0.01 lot, SL = 1.5×ATR, risk = $15
  2. Price reaches +1×ATR → accelerate: lot ×8 (0.01 → 0.08)
  3. SL on 0.08 pulled tight: max loss ≤ initial risk ($15)
     SL = current_price - (initial_risk / (new_lot × contract))
  4. If reversal → close at SL, loss = $15 (or $0 if BE)
  5. If trend continues → profit = 0.08 × distance × contract
  6. No fixed TP — ride until SL hit or trend reversal (EMA cross)

Variants tested:
  A) Fixed: 0.01 lot, SL=1.5×ATR, TP=2×ATR (baseline)
  B) Averaging down: 3 positions at -1/-2×ATR (current v3 system)
  C) Position Acceleration: 0.01 → 0.08 at +1×ATR, tight SL, ride trend
  D) Position Acceleration multi-step: 0.01 → 0.08 → 0.30 at +1/+2×ATR
"""
import os, sys, json, datetime, math
from collections import defaultdict

def load_env():
    p = os.path.expanduser("~/.claude/skills/xau-ai-trader/.env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k] = v

def fetch_h1(symbol, bars):
    import MetaTrader5 as mt5
    terminal = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")
    if not mt5.initialize(terminal):
        print(f"MT5 init failed: {mt5.last_error()}")
        sys.exit(1)
    if not mt5.symbol_select(symbol, True):
        mt5.shutdown(); return None
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, bars)
    mt5.shutdown()
    if rates is None or len(rates) < 250: return None
    candles = []
    for r in rates:
        candles.append({
            "time": int(r[0]), "open": float(r[1]), "high": float(r[2]),
            "low": float(r[3]), "close": float(r[4]), "tickvol": float(r[5]),
            "spread": float(r[6]),
        })
    return candles

def ema(values, period):
    out = [None] * len(values)
    k = 2 / (period + 1)
    for i in range(len(values)):
        if i == period - 1: out[i] = sum(values[:period]) / period
        elif i >= period: out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out

def atr(candles, period=14):
    trs = []
    for i in range(len(candles)):
        if i == 0: trs.append(candles[i]["high"] - candles[i]["low"])
        else:
            h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    out = [None] * len(trs)
    k = 1 / period
    for i in range(period - 1, len(trs)):
        if i == period - 1: out[i] = sum(trs[:period]) / period
        else: out[i] = trs[i] * k + out[i-1] * (1 - k)
    return out

def adx(candles, period=14):
    n = len(candles)
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, n):
        up = candles[i]["high"] - candles[i-1]["high"]
        down = candles[i-1]["low"] - candles[i]["low"]
        plus_dm.append(up if (up > down and up > 0) else 0)
        minus_dm.append(down if (down > up and down > 0) else 0)
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr_s = [0]*n; plus_s = [0]*n; minus_s = [0]*n; adx_s = [None]*n
    for i in range(period, n):
        if i == period:
            atr_s[i] = sum(tr[:period]); plus_s[i] = sum(plus_dm[:period]); minus_s[i] = sum(minus_dm[:period])
        else:
            atr_s[i] = atr_s[i-1] - atr_s[i-1]/period + tr[i-1]
            plus_s[i] = plus_s[i-1] - plus_s[i-1]/period + plus_dm[i-1]
            minus_s[i] = minus_s[i-1] - minus_s[i-1]/period + minus_dm[i-1]
    dx = [None]*n
    for i in range(period, n):
        if atr_s[i] > 0:
            pdi = 100*plus_s[i]/atr_s[i]; mdi = 100*minus_s[i]/atr_s[i]
            if pdi+mdi > 0: dx[i] = 100*abs(pdi-mdi)/(pdi+mdi)
    for i in range(period*2, n):
        if i == period*2:
            vals = [dx[j] for j in range(period, period*2) if dx[j] is not None]
            if vals: adx_s[i] = sum(vals)/len(vals)
        else:
            if adx_s[i-1] and dx[i-1]: adx_s[i] = (adx_s[i-1]*(period-1)+dx[i-1])/period
    return adx_s

INSTRUMENT_DIGITS = {"EURUSD":5,"GBPUSD":5,"USDCAD":5,"EURGBP":5,"NZDCAD":5,"EURAUD":5}
CONTRACT = {"EURUSD":100000,"GBPUSD":100000,"USDCAD":100000,"EURGBP":100000,"NZDCAD":100000,"EURAUD":100000}

# ── Scenario A: Fixed (baseline) ─────────────────────────────────────
def sim_fixed(entry, direction, atr_val, lot, contract, candles, idx, max_bars=48):
    sl_dist = 1.5 * atr_val
    tp_dist = 2.0 * atr_val
    if direction == 1:
        sl = entry - sl_dist; tp = entry + tp_dist
    else:
        sl = entry + sl_dist; tp = entry - tp_dist
    for j in range(idx+1, min(idx+1+max_bars, len(candles))):
        c = candles[j]
        if direction == 1:
            if c["low"] <= sl: return "loss", (sl-entry)*contract*lot
            if c["high"] >= tp: return "win", (tp-entry)*contract*lot
        else:
            if c["high"] >= sl: return "loss", (entry-sl)*contract*lot
            if c["low"] <= tp: return "win", (entry-tp)*contract*lot
    exit_p = candles[min(idx+max_bars, len(candles)-1)]["close"]
    if direction == 1: return "timeout", (exit_p-entry)*contract*lot
    return "timeout", (entry-exit_p)*contract*lot

# ── Scenario B: Averaging down (current v3) ──────────────────────────
def sim_avg_down(entry, direction, atr_val, lot, contract, equity, max_loss_pct,
                 candles, idx, max_addons=2, max_bars=72):
    positions = []
    max_loss_usd = equity * max_loss_pct / 100.0
    realized_pnl = 0.0
    sl_dist = 1.5 * atr_val
    if direction == 1: sl1 = entry - sl_dist
    else: sl1 = entry + sl_dist
    positions.append((entry, sl1, lot))
    addons = [entry - 1.0*atr_val if direction==1 else entry + 1.0*atr_val,
              entry - 2.0*atr_val if direction==1 else entry + 2.0*atr_val]
    n_addons = 0
    for j in range(idx+1, min(idx+1+max_bars, len(candles))):
        c = candles[j]
        new_pos = []
        for pe, ps, pl in positions:
            hit = False
            if direction == 1:
                if c["low"] <= ps: hit = True; realized_pnl += (ps-pe)*contract*pl
            else:
                if c["high"] >= ps: hit = True; realized_pnl += (pe-ps)*contract*pl
            if not hit: new_pos.append((pe, ps, pl))
        positions = new_pos
        if not positions: return "all_sl", realized_pnl, n_addons+1
        worst = c["low"] if direction==1 else c["high"]
        unreal = sum((worst-pe)*contract*pl if direction==1 else (pe-worst)*contract*pl for pe,ps,pl in positions)
        if realized_pnl + unreal <= -max_loss_usd:
            close = sum((worst-pe)*contract*pl if direction==1 else (pe-worst)*contract*pl for pe,ps,pl in positions)
            return "dd_stop", realized_pnl+close, n_addons+1
        if n_addons < max_addons:
            ap = addons[n_addons]
            reached = c["low"] <= ap if direction==1 else c["high"] >= ap
            if reached:
                asl = ap - sl_dist if direction==1 else ap + sl_dist
                positions.append((ap, asl, lot)); n_addons += 1
        tl = sum(p[2] for p in positions)
        wavg = sum(p[0]*p[2] for p in positions)/tl
        tp = wavg + 0.5*atr_val if direction==1 else wavg - 0.5*atr_val
        hit_tp = c["high"] >= tp if direction==1 else c["low"] <= tp
        if hit_tp:
            total = realized_pnl
            for pe,ps,pl in positions: total += (tp-pe)*contract*pl if direction==1 else (pe-tp)*contract*pl
            return "recovered", total, n_addons+1
    exit_p = candles[min(idx+max_bars, len(candles)-1)]["close"]
    total = realized_pnl
    for pe,ps,pl in positions: total += (exit_p-pe)*contract*pl if direction==1 else (pe-exit_p)*contract*pl
    return "timeout", total, n_addons+1

# ── Scenario C: Position Acceleration (single step) ──────────────────
def sim_acceleration(entry, direction, atr_val, lot_init, multiplier, contract,
                     candles, idx, max_bars=120):
    """
    1. Enter lot_init (0.01), SL = 1.5×ATR
    2. If price reaches +1×ATR → accelerate: lot = lot_init × multiplier
    3. SL on new position: max loss ≤ initial risk
       initial_risk = lot_init × 1.5×ATR × contract
       new_sl_dist = initial_risk / (new_lot × contract)
       new_sl = accel_price ± new_sl_dist
    4. Ride until SL hit or EMA cross (trend reversal)
    """
    sl_dist_init = 1.5 * atr_val
    initial_risk = lot_init * sl_dist_init * contract
    accel_level = entry + 1.0 * atr_val if direction == 1 else entry - 1.0 * atr_val
    new_lot = lot_init * multiplier

    # Phase 1: pre-acceleration (0.01 lot, SL = 1.5×ATR)
    for j in range(idx+1, min(idx+1+max_bars, len(candles))):
        c = candles[j]
        # Check initial SL
        if direction == 1:
            if c["low"] <= entry - sl_dist_init:
                return "loss_pre_accel", -(sl_dist_init)*contract*lot_init, 0.01
        else:
            if c["high"] >= entry + sl_dist_init:
                return "loss_pre_accel", -(sl_dist_init)*contract*lot_init, 0.01
        # Check acceleration trigger
        reached = c["high"] >= accel_level if direction == 1 else c["low"] <= accel_level
        if reached:
            # Phase 2: post-acceleration
            accel_price = accel_level
            # Calculate tight SL: max loss = initial_risk
            new_sl_dist = initial_risk / (new_lot * contract)
            if direction == 1:
                new_sl = accel_price - new_sl_dist
            else:
                new_sl = accel_price + new_sl_dist

            # Ride from here
            for k in range(j, min(j+max_bars, len(candles))):
                ck = candles[k]
                if direction == 1:
                    if ck["low"] <= new_sl:
                        # SL hit — loss limited to initial risk
                        pnl = (new_sl - accel_price) * contract * new_lot
                        # Add profit from initial lot (entry to accel_price)
                        pnl += (accel_price - entry) * contract * lot_init
                        return "loss_post_accel", pnl, new_lot
                else:
                    if ck["high"] >= new_sl:
                        pnl = (accel_price - new_sl) * contract * new_lot
                        pnl += (entry - accel_price) * contract * lot_init
                        return "loss_post_accel", pnl, new_lot
            # Timeout — exit at last close
            exit_p = candles[min(j+max_bars, len(candles)-1)]["close"]
            if direction == 1:
                pnl = (exit_p - accel_price) * contract * new_lot
                pnl += (accel_price - entry) * contract * lot_init
            else:
                pnl = (accel_price - exit_p) * contract * new_lot
                pnl += (entry - accel_price) * contract * lot_init
            return "timeout_accel", pnl, new_lot

    # Never reached acceleration
    exit_p = candles[min(idx+max_bars, len(candles)-1)]["close"]
    if direction == 1: return "timeout_no_accel", (exit_p-entry)*contract*lot_init, lot_init
    return "timeout_no_accel", (entry-exit_p)*contract*lot_init, lot_init

# ── Scenario D: Multi-step acceleration ──────────────────────────────
def sim_acceleration_multi(entry, direction, atr_val, lot_init, contract,
                           candles, idx, max_bars=120, steps=[(1.0, 8), (2.0, 4)]):
    """
    Multi-step acceleration:
    Step 1: +1×ATR → lot × 8
    Step 2: +2×ATR → lot × 4 more (total × 32)
    SL after each step: max loss ≤ initial_risk
    """
    sl_dist_init = 1.5 * atr_val
    initial_risk = lot_init * sl_dist_init * contract
    current_lot = lot_init
    current_sl = entry - sl_dist_init if direction == 1 else entry + sl_dist_init
    step_idx = 0
    last_entry = entry
    total_pnl = 0.0

    for j in range(idx+1, min(idx+1+max_bars, len(candles))):
        c = candles[j]
        # Check SL
        if direction == 1:
            if c["low"] <= current_sl:
                return "loss", total_pnl + (current_sl - last_entry)*contract*current_lot, current_lot
        else:
            if c["high"] >= current_sl:
                return "loss", total_pnl + (last_entry - current_sl)*contract*current_lot, current_lot

        # Check for acceleration step
        if step_idx < len(steps):
            trigger_dist, mult = steps[step_idx]
            trigger = entry + trigger_dist * atr_val if direction == 1 else entry - trigger_dist * atr_val
            reached = c["high"] >= trigger if direction == 1 else c["low"] <= trigger
            if reached:
                # Book profit from previous lot
                total_pnl += (trigger - last_entry) * contract * current_lot if direction == 1 \
                    else (last_entry - trigger) * contract * current_lot
                # New lot
                new_lot = current_lot * mult
                new_sl_dist = initial_risk / (new_lot * contract)
                new_sl = trigger - new_sl_dist if direction == 1 else trigger + new_sl_dist
                current_lot = new_lot
                current_sl = new_sl
                last_entry = trigger
                step_idx += 1

    # Timeout
    exit_p = candles[min(idx+max_bars, len(candles)-1)]["close"]
    total_pnl += (exit_p - last_entry) * contract * current_lot if direction == 1 \
        else (last_entry - exit_p) * contract * current_lot
    return "timeout", total_pnl, current_lot

# ── Runner ───────────────────────────────────────────────────────────
def run_comparison(symbol, candles, equity=100000.0, max_loss_pct=1.7):
    closes = [c["close"] for c in candles]
    e20 = ema(closes, 20); e200 = ema(closes, 200)
    a14 = atr(candles, 14); adx_v = adx(candles, 14)

    digits = INSTRUMENT_DIGITS.get(symbol, 5)
    contract = CONTRACT.get(symbol, 100000)
    spread_cost = lambda idx: candles[idx]["spread"] * (10 ** -digits) * contract

    results = {"A_fixed": [], "B_avgdown": [], "C_accel": [], "D_accel_multi": []}
    cooldown = 0

    for idx in range(210, len(candles) - 120):
        if cooldown > 0: cooldown -= 1; continue
        if not (e20[idx] and e200[idx] and a14[idx] and adx_v[idx]): continue
        if adx_v[idx] < 20: continue
        if a14[idx] > closes[idx] * 0.05: continue

        # T_EMA signal
        if e20[idx] > e200[idx]: direction = 1
        elif e20[idx] < e200[idx]: direction = -1
        else: continue

        entry = closes[idx]; atr_val = a14[idx]; sc = spread_cost(idx)

        # A) Fixed: 0.01 lot, SL=1.5×ATR, TP=2×ATR
        lot_fixed = 0.01
        r_a, pnl_a = sim_fixed(entry, direction, atr_val, lot_fixed, contract, candles, idx)
        results["A_fixed"].append({"result": r_a, "pnl": pnl_a - sc, "lot": lot_fixed})

        # B) Averaging down: lot sized for 3 pos × 1.5×ATR = 1.7% equity
        lot_avg = max(math.floor((equity * max_loss_pct/100) / (3 * 1.5 * atr_val * contract) * 100) / 100, 0.01)
        if lot_avg >= 0.01:
            r_b, pnl_b, n_b = sim_avg_down(entry, direction, atr_val, lot_avg, contract, equity, max_loss_pct, candles, idx)
            results["B_avgdown"].append({"result": r_b, "pnl": pnl_b - sc*n_b, "lot": lot_avg, "n_pos": n_b})

        # C) Acceleration: 0.01 → 0.08
        r_c, pnl_c, lot_c = sim_acceleration(entry, direction, atr_val, 0.01, 8, contract, candles, idx)
        results["C_accel"].append({"result": r_c, "pnl": pnl_c - sc, "lot": lot_c})

        # D) Multi-step: 0.01 → 0.08 → 0.32
        r_d, pnl_d, lot_d = sim_acceleration_multi(entry, direction, atr_val, 0.01, contract, candles, idx)
        results["D_accel_multi"].append({"result": r_d, "pnl": pnl_d - sc, "lot": lot_d})

        cooldown = 2

    return results

# ── Stats ────────────────────────────────────────────────────────────
def stats(trades):
    if not trades: return None
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = gp/gl if gl > 0 else float("inf") if gp > 0 else 0
    total = sum(t["pnl"] for t in trades)
    worst = min(t["pnl"] for t in trades)
    best = max(t["pnl"] for t in trades)
    avg_win = sum(t["pnl"] for t in wins)/len(wins) if wins else 0
    avg_loss = sum(t["pnl"] for t in losses)/len(losses) if losses else 0
    return {"n":n, "wr":len(wins)/n*100, "pf":pf, "pnl":total, "worst":worst, "best":best,
            "avg_win":avg_win, "avg_loss":avg_loss, "wins":len(wins), "losses":len(losses)}

# ── Main ─────────────────────────────────────────────────────────────
def main():
    pairs = ["EURUSD","GBPUSD","USDCAD","EURGBP","NZDCAD","EURAUD"]
    bars = 24 * 365 + 300
    equity = 100000.0
    max_loss = 1.7

    load_env()

    print(f"\n{'='*120}")
    print(f"  POSITION ACCELERATION vs AVERAGING DOWN — 6 FX pairs, 1 year H1, T_EMA")
    print(f"  Equity: ${equity:.0f} | ATR anomaly cap: 5% | Cooldown: 2 bars")
    print(f"{'='*120}\n")

    all_stats = {}

    for symbol in pairs:
        candles = fetch_h1(symbol, bars)
        if not candles:
            print(f"  {symbol}: NO DATA"); continue

        results = run_comparison(symbol, candles, equity, max_loss)

        print(f"  {symbol} ({len(candles)} bars)")
        print(f"  {'Method':20s} | {'Trades':>6s} | {'WR':>6s} | {'PF':>6s} | "
              f"{'Total PnL':>12s} | {'Avg Win':>10s} | {'Avg Loss':>10s} | "
              f"{'Worst':>10s} | {'Best':>10s}")
        print(f"  {'-'*20} | {'-'*6} | {'-'*6} | {'-'*6} | {'-'*12} | {'-'*10} | {'-'*10} | {'-'*10} | {'-'*10}")

        sym_stats = {}
        for label, key in [("A) Fixed 0.01", "A_fixed"),
                           ("B) Avg Down v3", "B_avgdown"),
                           ("C) Acceleration ×8", "C_accel"),
                           ("D) Acceleration Multi", "D_accel_multi")]:
            s = stats(results[key])
            if not s: print(f"  {label:20s} | no trades"); continue
            print(f"  {label:20s} | {s['n']:6d} | {s['wr']:5.1f}% | {s['pf']:6.2f} | "
                  f"${s['pnl']:+11.0f} | ${s['avg_win']:+9.0f} | ${s['avg_loss']:+9.0f} | "
                  f"${s['worst']:+9.0f} | ${s['best']:+9.0f}")
            sym_stats[key] = s
        print()
        all_stats[symbol] = sym_stats

    # Cross-symbol summary
    print(f"\n{'='*120}")
    print(f"  CROSS-SYMBOL SUMMARY")
    print(f"{'='*120}")
    print(f"  {'Symbol':10s} | {'Fixed PnL':>12s} | {'AvgDown PnL':>12s} | {'Accel×8 PnL':>12s} | {'Accel Multi PnL':>14s} | {'Best Method':>14s}")
    print(f"  {'-'*10} | {'-'*12} | {'-'*12} | {'-'*12} | {'-'*14} | {'-'*14}")

    totals = {"A_fixed": 0, "B_avgdown": 0, "C_accel": 0, "D_accel_multi": 0}
    for sym, ss in all_stats.items():
        vals = {}
        for key in totals:
            vals[key] = ss.get(key, {}).get("pnl", 0) if ss.get(key) else 0
            totals[key] += vals[key]
        best = max(vals, key=vals.get)
        best_name = {"A_fixed":"Fixed","B_avgdown":"AvgDown","C_accel":"Accel×8","D_accel_multi":"Accel Multi"}[best]
        print(f"  {sym:10s} | ${vals['A_fixed']:+11.0f} | ${vals['B_avgdown']:+11.0f} | "
              f"${vals['C_accel']:+11.0f} | ${vals['D_accel_multi']:+13.0f} | {best_name:>14s}")

    print(f"  {'-'*10} | {'-'*12} | {'-'*12} | {'-'*12} | {'-'*14} | {'-'*14}")
    best_total = max(totals, key=totals.get)
    best_name = {"A_fixed":"Fixed","B_avgdown":"AvgDown","C_accel":"Accel×8","D_accel_multi":"Accel Multi"}[best_total]
    print(f"  {'TOTAL':10s} | ${totals['A_fixed']:+11.0f} | ${totals['B_avgdown']:+11.0f} | "
          f"${totals['C_accel']:+11.0f} | ${totals['D_accel_multi']:+13.0f} | {best_name:>14s}")

    # PF summary
    print(f"\n  {'Symbol':10s} | {'Fixed PF':>8s} | {'AvgDown PF':>10s} | {'Accel×8 PF':>10s} | {'Multi PF':>8s}")
    for sym, ss in all_stats.items():
        pfs = []
        for key in ["A_fixed","B_avgdown","C_accel","D_accel_multi"]:
            pfs.append(f"{ss.get(key,{}).get('pf',0):.2f}" if ss.get(key) else "  -  ")
        print(f"  {sym:10s} | {pfs[0]:>8s} | {pfs[1]:>10s} | {pfs[2]:>10s} | {pfs[3]:>8s}")

    # Risk comparison
    print(f"\n  RISK COMPARISON (worst single trade across all pairs)")
    for key, label in [("A_fixed","Fixed 0.01"),("B_avgdown","AvgDown v3"),
                       ("C_accel","Accel ×8"),("D_accel_multi","Accel Multi")]:
        worsts = [ss.get(key,{}).get("worst",0) for ss in all_stats.values() if ss.get(key)]
        if worsts:
            print(f"  {label:20s} | worst = ${min(worsts):+.0f} | best = ${max([ss.get(key,{}).get('best',0) for ss in all_stats.values() if ss.get(key)]):+.0f}")

    out = os.path.join(os.path.dirname(__file__), "acceleration_study.json")
    with open(out, "w") as f:
        json.dump({k: v for k, v in all_stats.items()}, f, indent=2, default=str)
    print(f"\n  Results saved to {out}")

if __name__ == "__main__":
    main()