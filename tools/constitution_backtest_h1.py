#!/usr/bin/env python3
"""
H1 backtest for 4 constitution tactics (not yet tested):
  C1: Trend Pullback Continuation
  C2: Range Mean Reversion
  C3: RSI + Bollinger Band Reversion
  C4: Liquidity Sweep (BTMM-enhanced)
Tests on 6 FX pairs only (XAUUSD dropped), 1 year H1, fixed + averaging.
"""
import os, sys, json, datetime, math

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
        print(f"MT5 init failed: {mt5.last_error()}"); sys.exit(1)
    if not mt5.symbol_select(symbol, True):
        mt5.shutdown(); return None
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, bars)
    mt5.shutdown()
    if rates is None or len(rates) < 250: return None
    candles = []
    for r in rates:
        candles.append({"time": int(r[0]), "open": float(r[1]), "high": float(r[2]),
                        "low": float(r[3]), "close": float(r[4]), "tickvol": float(r[5]),
                        "spread": float(r[6])})
    return candles

# ── Indicators ──────────────────────────────────────────────────────
def ema(values, period):
    out = [None] * len(values); k = 2 / (period + 1)
    for i in range(len(values)):
        if i == period - 1: out[i] = sum(values[:period]) / period
        elif i >= period: out[i] = values[i] * k + out[i-1] * (1 - k)
    return out

def sma(values, period):
    out = [None] * len(values)
    for i in range(period-1, len(values)):
        out[i] = sum(values[i-period+1:i+1]) / period
    return out

def atr(candles, period=14):
    trs = []
    for i in range(len(candles)):
        if i == 0: trs.append(candles[i]["high"] - candles[i]["low"])
        else:
            h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
            trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    out = [None] * len(trs); k = 1 / period
    for i in range(period-1, len(trs)):
        if i == period-1: out[i] = sum(trs[:period]) / period
        else: out[i] = trs[i] * k + out[i-1] * (1 - k)
    return out

def rsi(closes, period=14):
    out = [None] * len(closes); gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i-1]; gains.append(max(0, ch)); losses.append(max(0, -ch))
    for i in range(period, len(closes)):
        if i == period: avg_g = sum(gains[:period])/period; avg_l = sum(losses[:period])/period
        else: avg_g = (avg_g*(period-1)+gains[i-1])/period; avg_l = (avg_l*(period-1)+losses[i-1])/period
        out[i] = 100.0 if avg_l == 0 else 100 - 100/(1+avg_g/avg_l)
    return out

def adx(candles, period=14):
    n = len(candles); plus_dm, minus_dm, tr = [], [], []
    for i in range(1, n):
        up = candles[i]["high"] - candles[i-1]["high"]; down = candles[i-1]["low"] - candles[i]["low"]
        plus_dm.append(up if (up > down and up > 0) else 0)
        minus_dm.append(down if (down > up and down > 0) else 0)
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
        tr.append(max(h-l, abs(h-pc), abs(l-pc)))
    atr_s = [0]*n; plus_s = [0]*n; minus_s = [0]*n; adx_s = [None]*n
    for i in range(period, n):
        if i == period: atr_s[i] = sum(tr[:period]); plus_s[i] = sum(plus_dm[:period]); minus_s[i] = sum(minus_dm[:period])
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
    n = len(closes); upper = [None]*n; lower = [None]*n; mid = sma(closes, period)
    for i in range(period-1, n):
        w = closes[i-period+1:i+1]; m = mid[i]
        var = sum((x-m)**2 for x in w)/period; sd = math.sqrt(var)
        upper[i] = m+std_mult*sd; lower[i] = m-std_mult*sd
    return upper, mid, lower

# ── Strategy signals ────────────────────────────────────────────────

def sig_C1_trend_pullback(candles, idx, ind):
    """C1: Trend Pullback — EMA20>EMA200, price returns to EMA20, trigger candle."""
    ema20 = ind["ema20"][idx]; ema200 = ind["ema200"][idx]
    ema50 = ind["ema50"][idx]; atr_val = ind["atr"][idx]; rsi_val = ind["rsi"][idx]
    if not all([ema20, ema200, ema50, atr_val, rsi_val]) or atr_val > candles[idx]["close"] * 0.05:
        return None
    if idx < 3: return None
    close = candles[idx]["close"]; high = candles[idx]["high"]; low = candles[idx]["low"]
    open_ = candles[idx]["open"]
    
    # Trend up: EMA20 > EMA200, price above EMA200
    if ema20 > ema200:
        # Price pulled back to EMA20 area (within 0.5×ATR of EMA20)
        if abs(close - ema20) <= 0.5 * atr_val or (low <= ema20 <= high):
            # Trigger: bullish candle (close > open) or pin bar (long lower wick)
            body = close - open_
            lower_wick = open_ - low if close > open_ else close - low
            is_bullish = close > open_ and body > 0.2 * atr_val
            is_pin = lower_wick > 2 * abs(body) and close > open_
            # RSI turning up from 40-50
            rsi_prev = ind["rsi"][idx-1] if idx > 0 else None
            rsi_turn = rsi_prev and rsi_val > rsi_prev and 35 <= rsi_val <= 55
            if is_bullish or is_pin or rsi_turn:
                return 1, close, close - 2.5*atr_val, close + 0.5*atr_val, "C1_TrendPullback"
    
    # Trend down: EMA20 < EMA200
    if ema20 < ema200:
        if abs(close - ema20) <= 0.5 * atr_val or (low <= ema20 <= high):
            body = open_ - close
            upper_wick = high - open_ if close < open_ else high - close
            is_bearish = close < open_ and body > 0.2 * atr_val
            is_pin = upper_wick > 2 * abs(body) and close < open_
            rsi_prev = ind["rsi"][idx-1] if idx > 0 else None
            rsi_turn = rsi_prev and rsi_val < rsi_prev and 45 <= rsi_val <= 65
            if is_bearish or is_pin or rsi_turn:
                return -1, close, close + 2.5*atr_val, close - 0.5*atr_val, "C1_TrendPullback"
    return None

def sig_C2_range_reversion(candles, idx, ind):
    """C2: Range Mean Reversion — ADX < 20, 2+ boundary tests, rejection candle."""
    adx_val = ind["adx"][idx]; atr_val = ind["atr"][idx]
    ema20 = ind["ema20"][idx]; ema200 = ind["ema200"][idx]
    if not all([adx_val, atr_val, ema20, ema200]) or atr_val > candles[idx]["close"] * 0.05:
        return None
    if adx_val >= 20: return None  # Only in range
    if idx < 20: return None
    
    close = candles[idx]["close"]; high = candles[idx]["high"]; low = candles[idx]["low"]
    open_ = candles[idx]["open"]
    
    # Find range: last 20 bars high/low (excluding current)
    range_high = max(candles[j]["high"] for j in range(idx-20, idx))
    range_low = min(candles[j]["low"] for j in range(idx-20, idx))
    range_mid = (range_high + range_low) / 2
    range_size = range_high - range_low
    if range_size <= 0 or range_size > 4 * atr_val: return None  # Range too wide
    
    # Count boundary tests (within 0.3×ATR of boundary)
    upper_tests = sum(1 for j in range(idx-20, idx) if candles[j]["high"] >= range_high - 0.3*atr_val)
    lower_tests = sum(1 for j in range(idx-20, idx) if candles[j]["low"] <= range_low + 0.3*atr_val)
    if upper_tests < 2 and lower_tests < 2: return None  # Need 2+ tests
    
    # Price at lower boundary + rejection (long)
    if low <= range_low + 0.3 * atr_val:
        # Rejection: long lower wick or bullish engulfing
        body = close - open_
        lower_wick = open_ - low if close > open_ else close - low
        is_rejection = lower_wick > 1.5 * abs(body) and close > range_low
        is_engulf = close > open_ and close > candles[idx-1]["open"] and open_ < candles[idx-1]["close"]
        if is_rejection or is_engulf:
            return 1, close, close - 2.5*atr_val, range_mid, "C2_RangeReversion"
    
    # Price at upper boundary + rejection (short)
    if high >= range_high - 0.3 * atr_val:
        body = open_ - close
        upper_wick = high - open_ if close < open_ else high - close
        is_rejection = upper_wick > 1.5 * abs(body) and close < range_high
        is_engulf = close < open_ and close < candles[idx-1]["open"] and open_ > candles[idx-1]["close"]
        if is_rejection or is_engulf:
            return -1, close, close + 2.5*atr_val, range_mid, "C2_RangeReversion"
    return None

def sig_C3_rsi_bb(candles, idx, ind):
    """C3: RSI + Bollinger Band Reversion — close beyond BB + RSI extreme + ADX < 20."""
    adx_val = ind["adx"][idx]; atr_val = ind["atr"][idx]
    rsi_val = ind["rsi"][idx]; bb_upper = ind["bb_upper"][idx]
    bb_lower = ind["bb_lower"][idx]; bb_mid = ind["bb_mid"][idx]
    if not all([adx_val, atr_val, rsi_val, bb_upper, bb_lower, bb_mid]):
        return None
    if atr_val > candles[idx]["close"] * 0.05: return None
    if adx_val >= 20: return None  # Only in range
    
    close = candles[idx]["close"]
    rsi_prev = ind["rsi"][idx-1] if idx > 0 else None
    
    # Long: close below lower BB + RSI < 30 + RSI turning up
    if close < bb_lower and rsi_val < 35:
        if rsi_prev and rsi_val > rsi_prev:  # RSI recovering
            return 1, close, close - 2.5*atr_val, bb_mid, "C3_RSI_BB"
    
    # Short: close above upper BB + RSI > 65 + RSI turning down
    if close > bb_upper and rsi_val > 65:
        if rsi_prev and rsi_val < rsi_prev:  # RSI dropping
            return -1, close, close + 2.5*atr_val, bb_mid, "C3_RSI_BB"
    return None

def sig_C4_liquidity_sweep(candles, idx, ind):
    """C4: Liquidity Sweep (BTMM-enhanced) — false breakout of PDH/PDL + return + 13 EMA cross."""
    atr_val = ind["atr"][idx]; ema13 = ind["ema13"][idx]
    if not all([atr_val, ema13]) or atr_val > candles[idx]["close"] * 0.05:
        return None
    if idx < 25: return None
    
    close = candles[idx]["close"]; high = candles[idx]["high"]; low = candles[idx]["low"]
    open_ = candles[idx]["open"]
    
    # Find previous day high/low (24 bars back on H1)
    pdh = max(candles[j]["high"] for j in range(idx-24, idx))
    pdl = min(candles[j]["low"] for j in range(idx-24, idx))
    
    # Also check session high/low (last 8 bars)
    sh = max(candles[j]["high"] for j in range(idx-8, idx))
    sl = min(candles[j]["low"] for j in range(idx-8, idx))
    
    # ADR exhaustion: price reached > 1.0×ATR beyond PDH/PDL
    adr_up = pdh + 1.0 * atr_val
    adr_dn = pdl - 1.0 * atr_val
    
    # Sweep low: price went below PDL (or session low) but closed back above
    sweep_low = low < pdl and close > pdl
    sweep_session_low = low < sl and close > sl and sl <= pdl + 0.5 * atr_val
    # BTMM: close back above 13 EMA after sweep
    ema_cross_up = False
    if idx > 0:
        ema_prev = ind["ema13"][idx-1]
        if ema_prev:
            ema_cross_up = close > ema13 and candles[idx-1]["close"] <= ema_prev
    
    if (sweep_low or sweep_session_low) and ema_cross_up:
        # 3-candle confirmation: last 3 candles, at least 2 bullish
        bulls = sum(1 for j in range(idx-2, idx+1) if candles[j]["close"] > candles[j]["open"])
        if bulls >= 2:
            return 1, close, close - 2.5*atr_val, close + 0.5*atr_val, "C4_LiquiditySweep"
    
    # Sweep high: price went above PDH (or session high) but closed back below
    sweep_high = high > pdh and close < pdh
    sweep_session_high = high > sh and close < sh and sh >= pdh - 0.5 * atr_val
    ema_cross_dn = False
    if idx > 0:
        ema_prev = ind["ema13"][idx-1]
        if ema_prev:
            ema_cross_dn = close < ema13 and candles[idx-1]["close"] >= ema_prev
    
    if (sweep_high or sweep_session_high) and ema_cross_dn:
        bears = sum(1 for j in range(idx-2, idx+1) if candles[j]["close"] < candles[j]["open"])
        if bears >= 2:
            return -1, close, close + 2.5*atr_val, close - 0.5*atr_val, "C4_LiquiditySweep"
    return None

STRATEGIES = {
    "C1_TrendPullback": sig_C1_trend_pullback,
    "C2_RangeReversion": sig_C2_range_reversion,
    "C3_RSI_BB": sig_C3_rsi_bb,
    "C4_LiquiditySweep": sig_C4_liquidity_sweep,
}

# ── Trade simulation ────────────────────────────────────────────────
def sim_trade(entry, sl, tp, candles, idx, direction, max_bars=48):
    for j in range(idx+1, min(idx+1+max_bars, len(candles))):
        c = candles[j]
        if direction == 1:
            if c["low"] <= sl: return "loss", (sl-entry)
            if c["high"] >= tp: return "win", (tp-entry)
        else:
            if c["high"] >= sl: return "loss", (entry-sl)
            if c["low"] <= tp: return "win", (entry-tp)
    exit_p = candles[min(idx+max_bars, len(candles)-1)]["close"]
    if direction == 1: return "timeout", (exit_p-entry)
    return "timeout", (entry-exit_p)

def sim_averaging(entry, direction, atr_val, candles, idx, contract, lot, equity, max_loss_pct=2.5, max_bars=72):
    positions = [(entry, entry - 2.5*atr_val if direction==1 else entry + 2.5*atr_val, lot)]
    realized = 0.0; n_addons = 0
    addon_levels = [entry - 1.0*atr_val if direction==1 else entry + 1.0*atr_val,
                    entry - 2.0*atr_val if direction==1 else entry + 2.0*atr_val]
    for j in range(idx+1, min(idx+1+max_bars, len(candles))):
        c = candles[j]
        new_pos = []
        for pe, ps, pl in positions:
            hit = False
            if direction == 1:
                if c["low"] <= ps: hit = True; realized += (ps-pe)*contract*pl
            else:
                if c["high"] >= ps: hit = True; realized += (pe-ps)*contract*pl
            if not hit: new_pos.append((pe, ps, pl))
        positions = new_pos
        if not positions: return "all_sl", realized, n_addons+1
        worst = c["low"] if direction==1 else c["high"]
        unreal = sum((worst-pe)*contract*pl if direction==1 else (pe-worst)*contract*pl for pe,ps,pl in positions)
        if realized + unreal <= -equity * max_loss_pct / 100:
            close = sum((worst-pe)*contract*pl if direction==1 else (pe-worst)*contract*pl for pe,ps,pl in positions)
            return "dd_stop", realized+close, n_addons+1
        if n_addons < 2:
            ap = addon_levels[n_addons]
            reached = c["low"] <= ap if direction==1 else c["high"] >= ap
            if reached:
                asl = ap - 2.5*atr_val if direction==1 else ap + 2.5*atr_val
                positions.append((ap, asl, lot)); n_addons += 1
        tl = sum(p[2] for p in positions)
        wavg = sum(p[0]*p[2] for p in positions)/tl
        tp = wavg + 0.5*atr_val if direction==1 else wavg - 0.5*atr_val
        hit_tp = c["high"] >= tp if direction==1 else c["low"] <= tp
        if hit_tp:
            total = realized
            for pe,ps,pl in positions: total += (tp-pe)*contract*pl if direction==1 else (pe-tp)*contract*pl
            return "recovered", total, n_addons+1
    exit_p = candles[min(idx+max_bars, len(candles)-1)]["close"]
    total = realized
    for pe,ps,pl in positions: total += (exit_p-pe)*contract*pl if direction==1 else (pe-exit_p)*contract*pl
    return "timeout", total, n_addons+1

def compute_ind(candles):
    closes = [c["close"] for c in candles]
    bb_u, bb_m, bb_l = bollinger_bands(closes, 20, 2.0)
    return {
        "atr": atr(candles, 14), "adx": adx(candles, 14), "rsi": rsi(closes, 14),
        "ema13": ema(closes, 13), "ema20": ema(closes, 20), "ema50": ema(closes, 50),
        "sma50": sma(closes, 50), "ema200": ema(closes, 200),
        "bb_upper": bb_u, "bb_mid": bb_m, "bb_lower": bb_l,
    }

# ── Main ────────────────────────────────────────────────────────────
def main():
    pairs = ["EURUSD", "GBPUSD", "USDCAD", "EURGBP", "NZDCAD", "EURAUD"]
    bars = 24 * 365 + 300
    equity = 88699.0
    contract_fx = 100000

    load_env()

    print(f"\n{'='*130}")
    print(f"  H1 BACKTEST — 4 Constitution tactics x 6 FX pairs x 1 year (NO XAUUSD)")
    print(f"  Equity: ${equity:.0f} | Fixed + Averaging modes")
    print(f"{'='*130}\n")

    all_results = {}

    for symbol in pairs:
        candles = fetch_h1(symbol, bars)
        if not candles:
            print(f"  {symbol}: NO DATA"); continue

        contract = contract_fx
        digits = 5
        spread_cost = lambda idx: candles[idx]["spread"] * (10 ** -digits) * contract
        ind = compute_ind(candles)

        print(f"  {symbol} ({len(candles)} bars)")
        print(f"  {'Strategy':20s} | {'#':>4s} {'Fix PF':>7s} {'Fix WR':>7s} {'Fix PnL':>10s} | "
              f"{'#':>4s} {'Avg PF':>7s} {'Avg WR':>7s} {'Avg PnL':>10s} {'Avg Worst':>10s} | {'Win':>5s}")
        print(f"  {'-'*20} | {'-'*4} {'-'*7} {'-'*7} {'-'*10} | {'-'*4} {'-'*7} {'-'*7} {'-'*10} {'-'*10} | {'-'*5}")

        for sname, sfunc in STRATEGIES.items():
            fixed_trades = []; avg_trades = []
            cooldown = 0
            for idx in range(210, len(candles) - 72):
                if cooldown > 0: cooldown -= 1; continue
                sig = sfunc(candles, idx, ind)
                if not sig: continue
                direction, entry, sl, tp, label = sig
                atr_val = ind["atr"][idx]; sc = spread_cost(idx)

                r_f, pnl_f = sim_trade(entry, sl, tp, candles, idx, direction)
                fixed_trades.append({"pnl": pnl_f * contract * 0.01 - sc * 0.01})

                lot = max(math.floor((equity * 2.5 / 100) / (3 * 2.5 * atr_val * contract) * 100) / 100, 0.01)
                lot = max(math.floor(lot / 2 * 100) / 100, 0.01)
                if lot >= 0.01:
                    r_a, pnl_a, n_a = sim_averaging(entry, direction, atr_val, candles, idx, contract, lot, equity)
                    avg_trades.append({"pnl": pnl_a - sc * n_a})

                cooldown = 2

            def stats(trades):
                if not trades: return None
                n = len(trades); wins = [t for t in trades if t["pnl"] > 0]
                gp = sum(t["pnl"] for t in wins); gl = abs(sum(t["pnl"] for t in trades) - gp)
                pf = gp/gl if gl > 0 else float("inf") if gp > 0 else 0
                total = sum(t["pnl"] for t in trades)
                worst = min(t["pnl"] for t in trades) if trades else 0
                return {"n": n, "wr": len(wins)/n*100, "pf": pf, "pnl": total, "worst": worst}

            sf = stats(fixed_trades); sa = stats(avg_trades)
            fn = f"{sf['n']}" if sf else "-"
            fpf = f"{sf['pf']:.2f}" if sf else "-"
            fwr = f"{sf['wr']:.0f}%" if sf else "-"
            fpnl = f"${sf['pnl']:+.0f}" if sf else "-"
            an = f"{sa['n']}" if sa else "-"
            apf = f"{sa['pf']:.2f}" if sa else "-"
            awr = f"{sa['wr']:.0f}%" if sa else "-"
            apnl = f"${sa['pnl']:+.0f}" if sa else "-"
            aworst = f"${sa['worst']:+.0f}" if sa else "-"
            winner = "AVG" if (sa and sf and sa["pnl"] > sf["pnl"]) else "FIX" if (sf and sa) else "-"
            print(f"  {sname:20s} | {fn:>4s} {fpf:>7s} {fwr:>7s} {fpnl:>10s} | "
                  f"{an:>4s} {apf:>7s} {awr:>7s} {apnl:>10s} {aworst:>10s} | {winner:>5s}")
            all_results[f"{symbol}/{sname}"] = {"fixed": sf, "avg": sa}
        print()

    # Cross-strategy summary
    print(f"\n{'='*130}")
    print(f"  CROSS-STRATEGY SUMMARY (H1, averaging mode, 6 FX pairs only)")
    print(f"{'='*130}")
    print(f"  {'Strategy':20s} | {'Total PnL':>12s} | {'Trades':>7s} | {'Best PF':>8s} | {'Avg WR':>7s} | {'Pairs+':>7s} | {'Verdict':>10s}")
    print(f"  {'-'*20} | {'-'*12} | {'-'*7} | {'-'*8} | {'-'*7} | {'-'*7} | {'-'*10}")
    for sname in STRATEGIES.keys():
        total_pnl = 0; total_trades = 0; best_pf = 0; profitable = 0; total_pairs = 0; wrs = []
        for sym in pairs:
            key = f"{sym}/{sname}"
            if key in all_results and all_results[key]["avg"]:
                sa = all_results[key]["avg"]; total_pnl += sa["pnl"]
                total_trades += sa["n"]; total_pairs += 1; wrs.append(sa["wr"])
                if sa["pf"] > best_pf: best_pf = sa["pf"]
                if sa["pnl"] > 0: profitable += 1
        avg_wr = sum(wrs)/len(wrs) if wrs else 0
        verdict = "ALIVE" if total_pnl > 0 else "DEAD"
        print(f"  {sname:20s} | ${total_pnl:+11.0f} | {total_trades:7d} | {best_pf:8.2f} | {avg_wr:6.1f}% | {profitable}/{total_pairs:2d} | {verdict:>10s}")

    out = os.path.join(os.path.dirname(__file__), "constitution_backtest_h1.json")
    with open(out, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to {out}")

if __name__ == "__main__":
    main()