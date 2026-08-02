#!/usr/bin/env python3
"""
Comprehensive cross-pair study: 30 instruments × (trend + counter) × (fixed + averaging).
Finds optimal regime per pair WITH averaging.
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
        mt5.shutdown()
        return None
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, bars)
    mt5.shutdown()
    if rates is None or len(rates) < 250:
        return None
    candles = []
    for r in rates:
        candles.append({
            "time": int(r[0]), "open": float(r[1]), "high": float(r[2]),
            "low": float(r[3]), "close": float(r[4]), "tickvol": float(r[5]),
            "spread": float(r[6]),
        })
    return candles

# ── Indicators ──────────────────────────────────────────────────────
def ema(values, period):
    out = [None] * len(values)
    k = 2 / (period + 1)
    for i in range(len(values)):
        if i == period - 1:
            out[i] = sum(values[:period]) / period
        elif i >= period:
            out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out

def atr(candles, period=14):
    trs = []
    for i in range(len(candles)):
        if i == 0:
            trs.append(candles[i]["high"] - candles[i]["low"])
        else:
            h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    out = [None] * len(trs)
    k = 1 / period
    for i in range(period - 1, len(trs)):
        if i == period - 1:
            out[i] = sum(trs[:period]) / period
        else:
            out[i] = trs[i] * k + out[i-1] * (1 - k)
    return out

def rsi(closes, period=14):
    out = [None] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(0, ch))
        losses.append(max(0, -ch))
    for i in range(period, len(closes)):
        if i == period:
            avg_g = sum(gains[:period]) / period
            avg_l = sum(losses[:period]) / period
        else:
            avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
            avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        if avg_l == 0:
            out[i] = 100.0
        else:
            out[i] = 100 - 100 / (1 + avg_g / avg_l)
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

def bollinger_bands(closes, period=20, std_mult=2.0):
    n = len(closes); upper = [None]*n; lower = [None]*n; mid = [None]*n
    for i in range(period-1, n):
        window = closes[i-period+1:i+1]; m = sum(window)/period
        var = sum((x-m)**2 for x in window)/period; sd = math.sqrt(var)
        upper[i] = m+std_mult*sd; lower[i] = m-std_mult*sd; mid[i] = m
    return upper, mid, lower

# ── Symbol info ─────────────────────────────────────────────────────
def get_symbol_info(symbol):
    """Get digits and contract size from MT5."""
    import MetaTrader5 as mt5
    terminal = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")
    mt5.initialize(terminal)
    info = mt5.symbol_info(symbol)
    mt5.shutdown()
    if info:
        return info.digits, float(info.trade_contract_size)
    # Fallback
    defaults = {
        "XAUUSD": (2, 100), "USDJPY": (3, 100000), "EURUSD": (5, 100000),
        "USDCAD": (5, 100000), "GBPJPY": (3, 100000),
    }
    return defaults.get(symbol, (5, 100000))

# ── Position sizing ─────────────────────────────────────────────────
def calc_lot(equity, max_loss_pct, sl_dist, contract_size, max_positions=1):
    max_loss = equity * max_loss_pct / 100.0
    lot = max_loss / (sl_dist * contract_size * max_positions)
    return max(math.floor(lot * 100) / 100, 0.01)

# ── Trade simulation: fixed ─────────────────────────────────────────
def sim_fixed(entry, direction, sl, tp, lot, contract, candles, idx, max_bars=48):
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

# ── Trade simulation: averaging ─────────────────────────────────────
def sim_averaging(entry, direction, atr_val, lot, contract, equity, max_loss_pct,
                  candles, idx, max_addons=2, max_bars=72):
    positions = []
    max_loss_usd = equity * max_loss_pct / 100.0
    realized_pnl = 0.0
    sl_dist = 1.5 * atr_val

    if direction == 1:
        sl1 = entry - sl_dist
    else:
        sl1 = entry + sl_dist
    positions.append((entry, sl1, lot))

    addon_levels = [entry - 1.0*atr_val, entry - 2.0*atr_val] if direction == 1 \
        else [entry + 1.0*atr_val, entry + 2.0*atr_val]
    addons_added = 0

    for j in range(idx+1, min(idx+1+max_bars, len(candles))):
        c = candles[j]

        # 1. Per-position SLs
        new_pos = []
        for p_entry, p_sl, p_lot in positions:
            hit = False
            if direction == 1:
                if c["low"] <= p_sl: hit = True; realized_pnl += (p_sl-p_entry)*contract*p_lot
            else:
                if c["high"] >= p_sl: hit = True; realized_pnl += (p_entry-p_sl)*contract*p_lot
            if not hit: new_pos.append((p_entry, p_sl, p_lot))
        positions = new_pos
        if not positions: return "all_sl_hit", realized_pnl, addons_added+1

        # 2. DD stop (intrabar worst case)
        worst = c["low"] if direction == 1 else c["high"]
        unreal = sum((worst-pe)*contract*pl if direction==1 else (pe-worst)*contract*pl
                     for pe,ps,pl in positions)
        if realized_pnl + unreal <= -max_loss_usd:
            close_pnl = sum((worst-pe)*contract*pl if direction==1 else (pe-worst)*contract*pl
                           for pe,ps,pl in positions)
            return "dd_stop", realized_pnl+close_pnl, addons_added+1

        # 3. Addons
        if addons_added < max_addons:
            ap = addon_levels[addons_added]
            reached = c["low"] <= ap if direction == 1 else c["high"] >= ap
            if reached:
                asl = ap - sl_dist if direction == 1 else ap + sl_dist
                positions.append((ap, asl, lot))
                addons_added += 1

        # 4. TP = weighted avg + 0.5*ATR
        tl = sum(p[2] for p in positions)
        wavg = sum(p[0]*p[2] for p in positions)/tl
        tp = wavg + 0.5*atr_val if direction == 1 else wavg - 0.5*atr_val
        hit_tp = c["high"] >= tp if direction == 1 else c["low"] <= tp
        if hit_tp:
            total = realized_pnl
            for pe,ps,pl in positions:
                total += (tp-pe)*contract*pl if direction==1 else (pe-tp)*contract*pl
            return "recovered", total, addons_added+1

    exit_p = candles[min(idx+max_bars, len(candles)-1)]["close"]
    total = realized_pnl
    for pe,ps,pl in positions:
        total += (exit_p-pe)*contract*pl if direction==1 else (pe-exit_p)*contract*pl
    return "timeout", total, addons_added+1

# ── Tactic signals ──────────────────────────────────────────────────
def signal_trend_ema(candles, idx, ind):
    """TREND: EMA20 > EMA200 → long, EMA20 < EMA200 → short. ADX > 20."""
    if not (ind["ema20"][idx] and ind["ema200"][idx] and ind["adx"][idx] and ind["atr"][idx]):
        return None
    if ind["adx"][idx] < 20: return None
    if ind["atr"][idx] > candles[idx]["close"] * 0.05: return None  # anomaly cap
    close = candles[idx]["close"]; atr_val = ind["atr"][idx]
    if ind["ema20"][idx] > ind["ema200"][idx]:
        return 1, close, close - 1.5*atr_val, close + 2.0*atr_val, "T_EMA"
    elif ind["ema20"][idx] < ind["ema200"][idx]:
        return -1, close, close + 1.5*atr_val, close - 2.0*atr_val, "T_EMA"
    return None

def signal_trend_breakout(candles, idx, ind):
    """TREND: Donchian 20 breakout + ADX rising."""
    if not (ind["donchian_h"][idx] and ind["donchian_l"][idx] and ind["adx"][idx] and ind["atr"][idx]):
        return None
    if ind["adx"][idx] < 20: return None
    if ind["atr"][idx] > candles[idx]["close"] * 0.05: return None
    close = candles[idx]["close"]; atr_val = ind["atr"][idx]
    dh = ind["donchian_h"][idx]; dl = ind["donchian_l"][idx]
    if dh and dl and (dh - dl) < 0.3 * atr_val: return None  # too flat
    if close > dh:
        return 1, close, close - 1.5*atr_val, close + 2.0*atr_val, "T_Donchian"
    elif close < dl:
        return -1, close, close + 1.5*atr_val, close - 2.0*atr_val, "T_Donchian"
    return None

def signal_counter_rsi_bb(candles, idx, ind):
    """COUNTER: RSI + BB reversion. ADX < 20."""
    rsi_val = ind["rsi"][idx]; bb_u = ind["bb_upper"][idx]; bb_l = ind["bb_lower"][idx]
    bb_mid = ind["bb_mid"][idx]; adx_val = ind["adx"][idx]; atr_val = ind["atr"][idx]
    if not all([rsi_val, bb_u, bb_l, bb_mid, adx_val, atr_val]): return None
    if adx_val >= 20: return None
    if atr_val > candles[idx]["close"] * 0.05: return None
    close = candles[idx]["close"]
    if close < bb_l and rsi_val < 30:
        return 1, close, close - 1.5*atr_val, bb_mid, "C_RSI_BB"
    if close > bb_u and rsi_val > 70:
        return -1, close, close + 1.5*atr_val, bb_mid, "C_RSI_BB"
    return None

def signal_counter_divergence(candles, idx, ind):
    """COUNTER: HTF divergence. Price 2×ATR from EMA200 + RSI extreme."""
    rsi_val = ind["rsi"][idx]; ema200 = ind["ema200"][idx]; atr_val = ind["atr"][idx]
    if not all([rsi_val, ema200, atr_val]): return None
    if atr_val > candles[idx]["close"] * 0.05: return None
    close = candles[idx]["close"]
    if abs(close - ema200) < 2 * atr_val: return None
    if close < ema200 and rsi_val < 30:
        return 1, close, close - 1.5*atr_val, ema200, "C_Divergence"
    if close > ema200 and rsi_val > 70:
        return -1, close, close + 1.5*atr_val, ema200, "C_Divergence"
    return None

def signal_counter_sweep(candles, idx, ind):
    """COUNTER: Liquidity sweep. Previous day H/L sweep + 3 candle confirm."""
    atr_val = ind["atr"][idx]
    if not atr_val or atr_val > candles[idx]["close"] * 0.05: return None
    if idx < 5: return None
    dt = datetime.datetime.utcfromtimestamp(candles[idx]["time"])
    if not ((7 <= dt.hour <= 10) or (12 <= dt.hour <= 15)): return None
    prev_day = dt - datetime.timedelta(days=1)
    pd_start = int(prev_day.replace(hour=0,minute=0,second=0).timestamp())
    pd_end = int(prev_day.replace(hour=23,minute=59,second=59).timestamp())
    pdh = -float("inf"); pdl = float("inf")
    for j in range(idx, -1, -1):
        if candles[j]["time"] < pd_start: break
        if pd_start <= candles[j]["time"] <= pd_end:
            pdh = max(pdh, candles[j]["high"]); pdl = min(pdl, candles[j]["low"])
    if pdh == -float("inf"): return None
    sweep = candles[idx-3]
    if sweep["high"] > pdh and all(candles[j]["close"] < pdh for j in range(idx-2, idx+1)):
        close = candles[idx]["close"]
        return -1, close, sweep["high"] + 0.3*atr_val, close - 1.0*atr_val, "C_Sweep"
    if sweep["low"] < pdl and all(candles[j]["close"] > pdl for j in range(idx-2, idx+1)):
        close = candles[idx]["close"]
        return 1, close, sweep["low"] - 0.3*atr_val, close + 1.0*atr_val, "C_Sweep"
    return None

# ── All tactics ─────────────────────────────────────────────────────
TREND_TACTICS = {"T_EMA": signal_trend_ema, "T_Donchian": signal_trend_breakout}
COUNTER_TACTICS = {"C_RSI_BB": signal_counter_rsi_bb, "C_Divergence": signal_counter_divergence, "C_Sweep": signal_counter_sweep}

# ── Compute indicators ──────────────────────────────────────────────
def compute_ind(candles):
    closes = [c["close"] for c in candles]
    n = len(closes)
    dh = [None]*n; dl = [None]*n
    for i in range(19, n):
        w = candles[i-19:i+1]
        dh[i] = max(c["high"] for c in w); dl[i] = min(c["low"] for c in w)
    bb_u, bb_m, bb_l = bollinger_bands(closes, 20, 2.0)
    return {
        "atr": atr(candles, 14), "adx": adx(candles, 14),
        "rsi": rsi(closes, 14), "ema20": ema(closes, 20), "ema200": ema(closes, 200),
        "bb_upper": bb_u, "bb_mid": bb_m, "bb_lower": bb_l,
        "donchian_h": dh, "donchian_l": dl,
    }

# ── Run pair ────────────────────────────────────────────────────────
def run_pair(symbol, candles, digits, contract, equity, max_loss_pct):
    ind = compute_ind(candles)
    spread_cost = lambda idx: candles[idx]["spread"] * (10 ** -digits) * contract

    results = {}  # {tactic_mode: {"fixed": [...], "avg": [...]}}

    for mode_name, tactics in [("TREND", TREND_TACTICS), ("COUNTER", COUNTER_TACTICS)]:
        for tname, tfunc in tactics.items():
            key = f"{mode_name}/{tname}"
            res_fixed = []; res_avg = []
            cooldown = 0
            for idx in range(210, len(candles) - 72):
                if cooldown > 0: cooldown -= 1; continue
                sig = tfunc(candles, idx, ind)
                if not sig: continue
                direction, entry, sl, tp, label = sig
                atr_val = ind["atr"][idx]
                sc = spread_cost(idx)

                # Fixed: 1 position, 1/3 of max_loss budget
                fixed_risk = equity * (max_loss_pct/100.0) / 3
                sl_dist = abs(entry - sl)
                lot_fixed = calc_lot(equity, max_loss_pct/3, sl_dist, contract, 1)
                if lot_fixed < 0.01: continue
                r_f, pnl_f = sim_fixed(entry, direction, sl, tp, lot_fixed, contract, candles, idx)
                res_fixed.append({"result": r_f, "pnl": pnl_f - sc, "tactic": label})

                # Averaging: 3 positions, full max_loss budget
                lot_avg = calc_lot(equity, max_loss_pct, 1.5*atr_val, contract, 3)
                if lot_avg < 0.01: continue
                r_a, pnl_a, n_pos = sim_averaging(
                    entry, direction, atr_val, lot_avg, contract, equity, max_loss_pct, candles, idx)
                res_avg.append({"result": r_a, "pnl": pnl_a - sc*n_pos, "tactic": label, "n_pos": n_pos})

                cooldown = 2
            results[key] = {"fixed": res_fixed, "avg": res_avg}
    return results

# ── Stats ───────────────────────────────────────────────────────────
def calc_stats(trades):
    if not trades: return None
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = gp/gl if gl > 0 else float("inf") if gp > 0 else 0
    total = sum(t["pnl"] for t in trades)
    worst = min(t["pnl"] for t in trades)
    return {"trades": n, "wr": len(wins)/n*100, "pf": pf, "pnl": total, "worst": worst}

# ── Main ────────────────────────────────────────────────────────────
def main():
    all_symbols = [
        "AUDCAD","AUDCHF","AUDJPY","AUDNZD","AUDUSD","CADCHF","CADJPY","CHFJPY",
        "EURAUD","EURCAD","EURCHF","EURGBP","EURJPY","EURNZD","EURUSD",
        "GBPAUD","GBPCAD","GBPCHF","GBPJPY","GBPNZD","GBPUSD",
        "NZDCAD","NZDCHF","NZDJPY","NZDUSD","USDCAD","USDCHF","USDJPY",
        "XAUUSD",
    ]

    bars = 24 * 365 + 300  # 1 year H1
    equity = 100000.0
    max_loss = 2.0

    load_env()

    print(f"{'Symbol':10s} | {'Mode/Tactic':20s} | {'Fixed PF':>8s} {'Fixed WR':>8s} {'Fixed PnL':>12s} | "
          f"{'Avg PF':>8s} {'Avg WR':>8s} {'Avg PnL':>12s} {'Avg Worst':>10s} | {'Winner':>8s}")
    print("-" * 130)

    all_data = {}
    viable_pairs = []

    for symbol in all_symbols:
        candles = fetch_h1(symbol, bars)
        if not candles or len(candles) < 250:
            print(f"{symbol:10s} | NO DATA")
            continue

        digits, contract = get_symbol_info(symbol)
        results = run_pair(symbol, candles, digits, contract, equity, max_loss)

        best_mode = None
        best_pnl = -float("inf")
        pair_has_viable = False

        for key in sorted(results.keys()):
            rf = results[key]["fixed"]; ra = results[key]["avg"]
            sf = calc_stats(rf); sa = calc_stats(ra)
            if not sf and not sa: continue

            fpf = f"{sf['pf']:.2f}" if sf else "  -  "
            fwr = f"{sf['wr']:.1f}%" if sf else "  -  "
            fpnl = f"${sf['pnl']:+.0f}" if sf else "    -    "
            apf = f"{sa['pf']:.2f}" if sa else "  -  "
            awr = f"{sa['wr']:.1f}%" if sa else "  -  "
            apnl = f"${sa['pnl']:+.0f}" if sa else "    -    "
            aworst = f"${sa['worst']:+.0f}" if sa else "    -    "
            winner = "AVG" if (sa and sf and sa["pnl"] > sf["pnl"]) else "FIX" if (sf and sa) else "  -  "

            print(f"{symbol:10s} | {key:20s} | {fpf:>8s} {fwr:>8s} {fpnl:>12s} | "
                  f"{apf:>8s} {awr:>8s} {apnl:>12s} {aworst:>10s} | {winner:>8s}")

            # Track best averaging result per pair
            if sa and sa["pnl"] > best_pnl and sa["pf"] > 0.5:
                best_pnl = sa["pnl"]
                best_mode = key
                if sa["pf"] > 1.0:
                    pair_has_viable = True

            all_data[f"{symbol}/{key}"] = {"fixed": sf, "avg": sa}

        if best_mode:
            viable = "VIABLE" if pair_has_viable else ""
            print(f"{'':10s} | → Best: {best_mode:20s} | PnL=${best_pnl:+.0f} {viable}")
            viable_pairs.append({"symbol": symbol, "best_mode": best_mode, "best_pnl": best_pnl,
                                "viable": pair_has_viable})
        print()

    # ── Final ranking ────────────────────────────────────────────────
    print(f"\n{'='*100}")
    print(f"  FINAL RANKING — Best pairs with averaging (PF > 1.0)")
    print(f"{'='*100}")
    print(f"  {'Symbol':10s} | {'Best Mode':20s} | {'PnL':>12s} | {'Status':>8s}")
    print(f"  {'-'*10} | {'-'*20} | {'-'*12} | {'-'*8}")

    # Sort by PnL descending
    viable_pairs.sort(key=lambda x: x["best_pnl"], reverse=True)
    for vp in viable_pairs:
        status = "VIABLE" if vp["viable"] else "MARGINAL"
        print(f"  {vp['symbol']:10s} | {vp['best_mode']:20s} | ${vp['best_pnl']:+12.0f} | {status:>8s}")

    # Save
    out = os.path.join(os.path.dirname(__file__), "cross_pair_study.json")
    with open(out, "w") as f:
        json.dump({k: v for k, v in all_data.items()}, f, indent=2, default=str)
    print(f"\nSaved to {out}")

if __name__ == "__main__":
    main()