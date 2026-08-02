#!/usr/bin/env python3
"""
Averaging-down simulator: tests whether adding to losing positions
improves or worsens outcomes vs fixed SL.

Two scenarios per entry:
  A) Fixed: SL at 1.5×ATR, TP at 2×ATR, 1 position
  B) Average: add at -1×ATR and -2×ATR, TP at avg+0.5×ATR, hard SL at -3×ATR equivalent

Tracks: recovery rate, catastrophic loss, net PnL comparison.
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
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, bars)
    mt5.shutdown()
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

INSTRUMENT_DIGITS = {
    "XAUUSD": 2, "USDJPY": 3, "USDCAD": 5, "GBPJPY": 3, "EURUSD": 5,
}

def simulate_fixed(entry, direction, atr_val, candles, idx, max_bars=48):
    """Scenario A: fixed SL/TP, 1 position."""
    if direction == 1:  # long
        sl = entry - 1.5 * atr_val
        tp = entry + 2.0 * atr_val
        for j in range(idx + 1, min(idx + 1 + max_bars, len(candles))):
            c = candles[j]
            if c["low"] <= sl:
                return "loss", sl - entry, 1  # pnl, positions
            if c["high"] >= tp:
                return "win", tp - entry, 1
        exit_p = candles[min(idx + max_bars, len(candles)-1)]["close"]
        return "timeout", exit_p - entry, 1
    else:  # short
        sl = entry + 1.5 * atr_val
        tp = entry - 2.0 * atr_val
        for j in range(idx + 1, min(idx + 1 + max_bars, len(candles))):
            c = candles[j]
            if c["high"] >= sl:
                return "loss", entry - sl, 1
            if c["low"] <= tp:
                return "win", entry - tp, 1
        exit_p = candles[min(idx + max_bars, len(candles)-1)]["close"]
        return "timeout", entry - exit_p, 1

def simulate_averaging(entry, direction, atr_val, candles, idx, max_addons=2, max_bars=72):
    """
    Scenario B: averaging down.
    Add at -1×ATR and -2×ATR from original entry.
    TP = weighted_avg + 0.5×ATR
    Hard SL = -3×ATR from original entry (total risk cap)
    Returns (result, pnl_price, total_positions)
    """
    positions = [(entry, 1.0)]  # (price, lot_weight)
    original_risk = 1.5 * atr_val
    hard_sl_dist = 3.0 * atr_val  # max total loss distance

    if direction == 1:  # long
        hard_sl = entry - hard_sl_dist
        addon_levels = [entry - 1.0 * atr_val, entry - 2.0 * atr_val]
    else:
        hard_sl = entry + hard_sl_dist
        addon_levels = [entry + 1.0 * atr_val, entry + 2.0 * atr_val]

    addons_added = 0
    bars_elapsed = 0

    for j in range(idx + 1, min(idx + 1 + max_bars, len(candles))):
        c = candles[j]
        bars_elapsed = j - idx

        # Check hard SL first (catastrophic)
        if direction == 1:
            if c["low"] <= hard_sl:
                # Close all at hard SL
                total_pnl = 0
                for p, w in positions:
                    total_pnl += (hard_sl - p) * w
                total_w = sum(w for _, w in positions)
                return "catastrophic", total_pnl, len(positions)
        else:
            if c["high"] >= hard_sl:
                total_pnl = 0
                for p, w in positions:
                    total_pnl += (p - hard_sl) * w
                return "catastrophic", total_pnl, len(positions)

        # Check for addon opportunities (before checking TP)
        if addons_added < max_addons:
            addon_price = addon_levels[addons_added]
            if direction == 1:
                if c["low"] <= addon_price:
                    # Add position at addon price
                    positions.append((addon_price, 1.0))
                    addons_added += 1
            else:
                if c["high"] >= addon_price:
                    positions.append((addon_price, 1.0))
                    addons_added += 1

        # Calculate weighted average and TP
        total_w = sum(w for _, w in positions)
        weighted_avg = sum(p * w for p, w in positions) / total_w
        if direction == 1:
            tp = weighted_avg + 0.5 * atr_val
        else:
            tp = weighted_avg - 0.5 * atr_val

        # Check TP
        if direction == 1:
            if c["high"] >= tp:
                total_pnl = 0
                for p, w in positions:
                    total_pnl += (tp - p) * w
                return "recovered", total_pnl, len(positions)
        else:
            if c["low"] <= tp:
                total_pnl = 0
                for p, w in positions:
                    total_pnl += (p - tp) * w
                return "recovered", total_pnl, len(positions)

    # Timeout: exit at close of last bar
    exit_p = candles[min(idx + max_bars, len(candles) - 1)]["close"]
    total_pnl = 0
    for p, w in positions:
        if direction == 1:
            total_pnl += (exit_p - p) * w
        else:
            total_pnl += (p - exit_p) * w
    return "timeout", total_pnl, len(positions)


def run_comparison(symbol, candles, min_idx=210):
    """Run both scenarios on same entry points."""
    closes = [c["close"] for c in candles]
    ema20 = ema(closes, 20)
    ema200 = ema(closes, 200)
    atr_vals = atr(candles, 14)

    digits = INSTRUMENT_DIGITS.get(symbol, 5)
    spread_cost = lambda idx: candles[idx]["spread"] * (10 ** -digits)

    results_a = []  # fixed
    results_b = []  # averaging
    addons_count = defaultdict(int)

    cooldown = 0
    for idx in range(min_idx, len(candles) - 72):
        if cooldown > 0:
            cooldown -= 1
            continue

        if not (ema20[idx] and ema200[idx] and atr_vals[idx]):
            continue

        # Entry signal: EMA20 > EMA200 → long, EMA20 < EMA200 → short
        # Simple directional entry to test pure averaging effect
        if ema20[idx] > ema200[idx]:
            direction = 1
        elif ema20[idx] < ema200[idx]:
            direction = -1
        else:
            continue

        entry = candles[idx]["close"]
        atr_val = atr_vals[idx]
        sc = spread_cost(idx)

        # Scenario A: fixed
        res_a, pnl_a, n_a = simulate_fixed(entry, direction, atr_val, candles, idx)
        results_a.append({"result": res_a, "pnl": pnl_a - sc, "positions": n_a})

        # Scenario B: averaging
        res_b, pnl_b, n_b = simulate_averaging(entry, direction, atr_val, candles, idx)
        results_b.append({"result": res_b, "pnl": pnl_b - sc * n_b, "positions": n_b})
        addons_count[n_b] += 1

        cooldown = 2  # same cooldown for both

    return results_a, results_b, addons_count


def analyze(results, label):
    """Print statistics for a scenario."""
    if not results:
        print(f"  {label}: no trades")
        return {}

    n = len(results)
    wins = [r for r in results if r["pnl"] > 0]
    losses = [r for r in results if r["pnl"] <= 0]
    recoveries = [r for r in results if r["result"] == "recovered"]
    catastrophics = [r for r in results if r["result"] == "catastrophic"]
    timeouts = [r for r in results if r["result"] == "timeout"]
    regular_wins = [r for r in results if r["result"] == "win"]
    regular_losses = [r for r in results if r["result"] == "loss"]

    total_pnl = sum(r["pnl"] for r in results)
    gross_profit = sum(r["pnl"] for r in wins)
    gross_loss = abs(sum(r["pnl"] for r in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

    avg_pos = sum(r["positions"] for r in results) / n
    avg_win = sum(r["pnl"] for r in wins) / len(wins) if wins else 0
    avg_loss = sum(r["pnl"] for r in losses) / len(losses) if losses else 0

    worst = min(r["pnl"] for r in results)
    best = max(r["pnl"] for r in results)

    stats = {
        "label": label,
        "trades": n,
        "win_rate": len(wins) / n * 100,
        "profit_factor": pf,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / n,
        "avg_positions": avg_pos,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "worst_trade": worst,
        "best_trade": best,
        "recoveries": len(recoveries),
        "catastrophics": len(catastrophics),
    }

    print(f"  {label:20s} | trades={n:5d} | WR={stats['win_rate']:5.1f}% | "
          f"PF={pf:5.2f} | totalPnL={total_pnl:+10.4f} | avgPnL={total_pnl/n:+.4f} | "
          f"avgPos={avg_pos:.1f}")
    print(f"  {'':20s} | avgWin={avg_win:+.4f} avgLoss={avg_loss:+.4f} | "
          f"worst={worst:+.4f} best={best:+.4f} | "
          f"recov={len(recoveries)} catstr={len(catastrophics)} timeout={len(timeouts)}")

    return stats


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", default="XAUUSD,EURUSD,USDJPY,USDCAD,GBPJPY")
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()

    pairs = args.pairs.split(",")
    bars = 24 * args.days + 300

    load_env()

    all_stats = {}
    for symbol in pairs:
        print(f"\n{'='*80}")
        print(f"  {symbol} — Averaging-Down Simulation")
        print(f"{'='*80}")

        candles = fetch_h1(symbol, bars)
        print(f"  {len(candles)} H1 bars, "
              f"from {datetime.datetime.utcfromtimestamp(candles[0]['time'])} "
              f"to {datetime.datetime.utcfromtimestamp(candles[-1]['time'])}")

        results_a, results_b, addons = run_comparison(symbol, candles)

        print(f"\n  --- SCENARIO A: Fixed SL/TP (1 position, no averaging) ---")
        stats_a = analyze(results_a, "Fixed")

        print(f"\n  --- SCENARIO B: Averaging Down (up to 2 addons) ---")
        stats_b = analyze(results_b, "Averaging")

        print(f"\n  --- ADDON DISTRIBUTION ---")
        for n_pos, count in sorted(addons.items()):
            print(f"    {n_pos} positions: {count} trades ({count/len(results_b)*100:.1f}%)")

        print(f"\n  --- COMPARISON ---")
        print(f"    Fixed    → PnL={stats_a['total_pnl']:+10.4f} | PF={stats_a['profit_factor']:5.2f} | WR={stats_a['win_rate']:.1f}% | worst={stats_a['worst_trade']:+.4f}")
        print(f"    Averaging→ PnL={stats_b['total_pnl']:+10.4f} | PF={stats_b['profit_factor']:5.2f} | WR={stats_b['win_rate']:.1f}% | worst={stats_b['worst_trade']:+.4f}")
        diff = stats_b['total_pnl'] - stats_a['total_pnl']
        print(f"    Delta    → PnL={diff:+10.4f} ({'AVERAGING BETTER' if diff > 0 else 'FIXED BETTER'})")
        print(f"    Risk: worst trade averaging={stats_b['worst_trade']:+.4f} vs fixed={stats_a['worst_trade']:+.4f} "
              f"(ratio={abs(stats_b['worst_trade']/stats_a['worst_trade']):.1f}x)")

        all_stats[symbol] = {"fixed": stats_a, "averaging": stats_b}

    # Summary
    print(f"\n{'='*80}")
    print(f"  CROSS-SYMBOL SUMMARY")
    print(f"{'='*80}")
    print(f"  {'Symbol':10s} | {'Fixed PnL':>12s} | {'Avg PnL':>12s} | {'Delta':>12s} | {'Winner':>10s} | {'Worst ratio':>12s}")
    for sym, s in all_stats.items():
        f_pnl = s["fixed"]["total_pnl"]
        a_pnl = s["averaging"]["total_pnl"]
        delta = a_pnl - f_pnl
        winner = "AVERAGING" if delta > 0 else "FIXED"
        ratio = abs(s["averaging"]["worst_trade"] / s["fixed"]["worst_trade"]) if s["fixed"]["worst_trade"] != 0 else 0
        print(f"  {sym:10s} | {f_pnl:+12.4f} | {a_pnl:+12.4f} | {delta:+12.4f} | {winner:>10s} | {ratio:>11.1f}x")


if __name__ == "__main__":
    main()