#!/usr/bin/env python3
"""
Averaging-down simulator v2: per-position SL + 2% equity drawdown stop.

Rules:
  - Each entry (main + addons) has its own physical SL at 1.5×ATR from its entry
  - Max 3 positions (1 main + 2 addons)
  - Lot size calculated so worst case (all 3 SLs hit) ≤ 2% of equity
  - If total unrealized loss across all positions ≥ 2% equity → close all immediately
  - TP = weighted_average + 0.5×ATR
  - Equity starts at $10,000 (configurable)
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
INSTRUMENT_CONTRACT = {
    "XAUUSD": 100, "USDJPY": 100000, "USDCAD": 100000, "GBPJPY": 100000, "EURUSD": 100000,
}

# ── Position sizing ─────────────────────────────────────────────────
def calc_lot(equity, max_loss_pct, atr_val, contract_size, max_positions=3, sl_atr_mult=1.5):
    """
    Calculate lot size so that worst case (all positions hit SL) = max_loss_pct of equity.
    worst_case_loss = max_positions × sl_atr_mult × atr_val × contract_size × lot
    lot = (equity × max_loss_pct) / (max_positions × sl_atr_mult × atr_val × contract_size)
    """
    max_loss = equity * max_loss_pct / 100.0
    denom = max_positions * sl_atr_mult * atr_val * contract_size
    if denom <= 0:
        return 0.01
    lot = max_loss / denom
    # Round down to 0.01
    lot = math.floor(lot * 100) / 100
    return max(lot, 0.01)

# ── Simulation ──────────────────────────────────────────────────────
def simulate_fixed_v2(entry, direction, atr_val, lot, contract_size, equity,
                      max_loss_pct, candles, idx, max_bars=48):
    """Scenario A: fixed SL/TP, 1 position, lot sized for 1 position only."""
    # For fair comparison: lot sized so 1 position SL = max_loss_pct / 3 (same per-trade risk)
    per_trade_risk = equity * (max_loss_pct / 100.0) / 3  # 1/3 of total budget
    sl_dist = 1.5 * atr_val
    fixed_lot = per_trade_risk / (sl_dist * contract_size)
    fixed_lot = max(math.floor(fixed_lot * 100) / 100, 0.01)

    if direction == 1:
        sl = entry - 1.5 * atr_val
        tp = entry + 2.0 * atr_val
        for j in range(idx + 1, min(idx + 1 + max_bars, len(candles))):
            c = candles[j]
            if c["low"] <= sl:
                pnl = (sl - entry) * contract_size * fixed_lot
                return "loss", pnl, fixed_lot, 1
            if c["high"] >= tp:
                pnl = (tp - entry) * contract_size * fixed_lot
                return "win", pnl, fixed_lot, 1
        exit_p = candles[min(idx + max_bars, len(candles)-1)]["close"]
        pnl = (exit_p - entry) * contract_size * fixed_lot
        return "timeout", pnl, fixed_lot, 1
    else:
        sl = entry + 1.5 * atr_val
        tp = entry - 2.0 * atr_val
        for j in range(idx + 1, min(idx + 1 + max_bars, len(candles))):
            c = candles[j]
            if c["high"] >= sl:
                pnl = (entry - sl) * contract_size * fixed_lot
                return "loss", pnl, fixed_lot, 1
            if c["low"] <= tp:
                pnl = (entry - tp) * contract_size * fixed_lot
                return "win", pnl, fixed_lot, 1
        exit_p = candles[min(idx + max_bars, len(candles)-1)]["close"]
        pnl = (entry - exit_p) * contract_size * fixed_lot
        return "timeout", pnl, fixed_lot, 1


def simulate_averaging_v2(entry, direction, atr_val, lot, contract_size, equity,
                          max_loss_pct, candles, idx, max_addons=2, max_bars=72):
    """
    Scenario B: averaging down with per-position SL + 2% equity drawdown stop.

    Each position has its own SL at 1.5×ATR from its own entry.
    Lot sized so worst case (all 3 SLs hit) = max_loss_pct of equity.
    DD stop checks intrabar (high/low), not just close.
    TP = weighted_avg + 0.5×ATR.
    """
    positions = []  # list of (entry_price, sl_price, lot)
    max_loss_usd = equity * max_loss_pct / 100.0
    realized_pnl = 0  # accumulated from SL hits

    # Main position
    if direction == 1:
        sl1 = entry - 1.5 * atr_val
    else:
        sl1 = entry + 1.5 * atr_val
    positions.append((entry, sl1, lot))

    # Addon levels
    if direction == 1:
        addon_levels = [entry - 1.0 * atr_val, entry - 2.0 * atr_val]
    else:
        addon_levels = [entry + 1.0 * atr_val, entry + 2.0 * atr_val]

    addons_added = 0

    for j in range(idx + 1, min(idx + 1 + max_bars, len(candles))):
        c = candles[j]

        # ── 1. Check per-position SLs (intrabar) ───────────────
        new_positions = []
        for p_entry, p_sl, p_lot in positions:
            sl_hit = False
            if direction == 1:
                if c["low"] <= p_sl:
                    sl_hit = True
                    pnl = (p_sl - p_entry) * contract_size * p_lot
            else:
                if c["high"] >= p_sl:
                    sl_hit = True
                    pnl = (p_entry - p_sl) * contract_size * p_lot

            if sl_hit:
                realized_pnl += pnl
            else:
                new_positions.append((p_entry, p_sl, p_lot))

        positions = new_positions

        # If all positions hit their SL → done
        if not positions:
            return "all_sl_hit", realized_pnl, lot, addons_added + 1

        # ── 2. Check 2% equity drawdown stop (intrabar) ─────────
        # Use worst case intrabar: for long, use low; for short, use high
        worst_price = c["low"] if direction == 1 else c["high"]
        total_unreal_worst = 0
        for p_entry, p_sl, p_lot in positions:
            if direction == 1:
                total_unreal_worst += (worst_price - p_entry) * contract_size * p_lot
            else:
                total_unreal_worst += (p_entry - worst_price) * contract_size * p_lot

        total_drawdown_worst = realized_pnl + total_unreal_worst

        if total_drawdown_worst <= -max_loss_usd:
            # Close all at worst price
            close_pnl = 0
            for p_entry, p_sl, p_lot in positions:
                if direction == 1:
                    close_pnl += (worst_price - p_entry) * contract_size * p_lot
                else:
                    close_pnl += (p_entry - worst_price) * contract_size * p_lot
            total = realized_pnl + close_pnl
            return "dd_stop", total, lot, addons_added + 1

        # ── 3. Check for addon opportunities ────────────────────
        if addons_added < max_addons:
            addon_price = addon_levels[addons_added]
            reached = False
            if direction == 1:
                if c["low"] <= addon_price:
                    reached = True
            else:
                if c["high"] >= addon_price:
                    reached = True

            if reached:
                if direction == 1:
                    addon_sl = addon_price - 1.5 * atr_val
                else:
                    addon_sl = addon_price + 1.5 * atr_val
                positions.append((addon_price, addon_sl, lot))
                addons_added += 1

        # ── 4. Check TP (weighted average + 0.5×ATR) ────────────
        total_lot = sum(p[2] for p in positions)
        weighted_avg = sum(p[0] * p[2] for p in positions) / total_lot
        if direction == 1:
            tp = weighted_avg + 0.5 * atr_val
            if c["high"] >= tp:
                total_pnl = realized_pnl
                for p_entry, p_sl, p_lot in positions:
                    total_pnl += (tp - p_entry) * contract_size * p_lot
                return "recovered", total_pnl, lot, addons_added + 1
        else:
            tp = weighted_avg - 0.5 * atr_val
            if c["low"] <= tp:
                total_pnl = realized_pnl
                for p_entry, p_sl, p_lot in positions:
                    total_pnl += (p_entry - tp) * contract_size * p_lot
                return "recovered", total_pnl, lot, addons_added + 1

    # Timeout: exit at close of last bar
    exit_p = candles[min(idx + max_bars, len(candles) - 1)]["close"]
    total_pnl = realized_pnl
    for p_entry, p_sl, p_lot in positions:
        if direction == 1:
            total_pnl += (exit_p - p_entry) * contract_size * p_lot
        else:
            total_pnl += (p_entry - exit_p) * contract_size * p_lot
    return "timeout", total_pnl, lot, addons_added + 1


# ── Runner ──────────────────────────────────────────────────────────
def run_comparison(symbol, candles, equity=10000.0, max_loss_pct=2.0, min_idx=210):
    closes = [c["close"] for c in candles]
    ema20 = ema(closes, 20)
    ema200 = ema(closes, 200)
    atr_vals = atr(candles, 14)

    digits = INSTRUMENT_DIGITS.get(symbol, 5)
    contract = INSTRUMENT_CONTRACT.get(symbol, 100000)
    spread_cost = lambda idx: candles[idx]["spread"] * (10 ** -digits) * contract

    results_a = []
    results_b = []
    outcomes_b = defaultdict(int)
    max_dd_per_trade = []

    cooldown = 0
    for idx in range(min_idx, len(candles) - 72):
        if cooldown > 0:
            cooldown -= 1
            continue

        if not (ema20[idx] and ema200[idx] and atr_vals[idx]):
            continue

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
        res_a, pnl_a, lot_a, n_a = simulate_fixed_v2(
            entry, direction, atr_val, 0.01, contract, equity, max_loss_pct, candles, idx)
        results_a.append({"result": res_a, "pnl": pnl_a - sc, "lot": lot_a, "positions": n_a})

        # Scenario B: averaging
        # Lot sized for 3 positions × 1.5×ATR SL each = max_loss_pct
        lot_b = calc_lot(equity, max_loss_pct, atr_val, contract, max_positions=3, sl_atr_mult=1.5)

        # Skip if lot rounds to 0 (too risky for equity size)
        if lot_b < 0.01:
            # Can't trade — skip both for fair comparison
            results_a_skip = results_a.pop() if results_a else None
            continue

        # Cap ATR to prevent anomalous gaps (max 3× recent median)
        # Simple cap: if ATR > 5% of price, skip
        if atr_val > entry * 0.05:
            continue

        res_b, pnl_b, lot_b_actual, n_b = simulate_averaging_v2(
            entry, direction, atr_val, lot_b, contract, equity, max_loss_pct, candles, idx)
        results_b.append({"result": res_b, "pnl": pnl_b - sc * n_b, "lot": lot_b, "positions": n_b})
        outcomes_b[res_b] += 1
        if pnl_b < 0:
            max_dd_per_trade.append(pnl_b)

    return results_a, results_b, outcomes_b, max_dd_per_trade


def analyze(results, label, equity=10000.0, max_loss_pct=2.0):
    if not results:
        print(f"  {label}: no trades")
        return {}

    n = len(results)
    wins = [r for r in results if r["pnl"] > 0]
    losses = [r for r in results if r["pnl"] <= 0]

    total_pnl = sum(r["pnl"] for r in results)
    gross_profit = sum(r["pnl"] for r in wins)
    gross_loss = abs(sum(r["pnl"] for r in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

    avg_win = sum(r["pnl"] for r in wins) / len(wins) if wins else 0
    avg_loss = sum(r["pnl"] for r in losses) / len(losses) if losses else 0
    worst = min(r["pnl"] for r in results)
    best = max(r["pnl"] for r in results)

    # Max drawdown in dollars and % of equity
    max_dd_dollars = abs(worst)
    max_dd_pct = max_dd_dollars / equity * 100

    avg_lot = sum(r["lot"] for r in results) / n
    avg_pos = sum(r["positions"] for r in results) / n

    stats = {
        "label": label, "trades": n,
        "win_rate": len(wins) / n * 100,
        "profit_factor": pf,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / n,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "worst": worst, "best": best,
        "max_dd_pct": max_dd_pct,
        "avg_lot": avg_lot, "avg_pos": avg_pos,
    }

    print(f"  {label:20s} | trades={n:5d} | WR={stats['win_rate']:5.1f}% | "
          f"PF={pf:5.2f} | PnL={total_pnl:+10.2f} | avgPnL={total_pnl/n:+.4f} | "
          f"avgLot={avg_lot:.3f} avgPos={avg_pos:.1f}")
    print(f"  {'':20s} | avgWin={avg_win:+.2f} avgLoss={avg_loss:+.2f} | "
          f"worst={worst:+.2f} ({max_dd_pct:.2f}% eq) | best={best:+.2f}")

    return stats


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", default="XAUUSD,EURUSD,USDJPY,USDCAD,GBPJPY")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--equity", type=float, default=10000.0)
    parser.add_argument("--max-loss", type=float, default=2.0, help="Max loss % per instrument")
    args = parser.parse_args()

    pairs = args.pairs.split(",")
    bars = 24 * args.days + 300

    load_env()

    all_stats = {}
    for symbol in pairs:
        print(f"\n{'='*90}")
        print(f"  {symbol} — Averaging v2: Per-position SL + {args.max_loss}% Equity Drawdown Stop")
        print(f"  Equity: ${args.equity:.0f} | Max loss per instrument: {args.max_loss}% = ${args.equity*args.max_loss/100:.0f}")
        print(f"{'='*90}")

        candles = fetch_h1(symbol, bars)
        print(f"  {len(candles)} H1 bars")

        results_a, results_b, outcomes_b, worst_losses = run_comparison(
            symbol, candles, args.equity, args.max_loss)

        print(f"\n  --- SCENARIO A: Fixed (1 position, 1/3 risk budget per trade) ---")
        stats_a = analyze(results_a, "Fixed", args.equity, args.max_loss)

        print(f"\n  --- SCENARIO B: Averaging (per-position SL + {args.max_loss}% DD stop) ---")
        stats_b = analyze(results_b, "Averaging", args.equity, args.max_loss)

        print(f"\n  --- OUTCOME DISTRIBUTION (Averaging) ---")
        total_b = sum(outcomes_b.values())
        for outcome, count in sorted(outcomes_b.items()):
            print(f"    {outcome:15s}: {count:4d} ({count/total_b*100:.1f}%)")

        print(f"\n  --- COMPARISON ---")
        print(f"    Fixed    → PnL=${stats_a['total_pnl']:+10.2f} | PF={stats_a['profit_factor']:5.2f} | "
              f"WR={stats_a['win_rate']:.1f}% | worst=${stats_a['worst']:+.2f} ({stats_a['max_dd_pct']:.2f}% eq)")
        print(f"    Averaging→ PnL=${stats_b['total_pnl']:+10.2f} | PF={stats_b['profit_factor']:5.2f} | "
              f"WR={stats_b['win_rate']:.1f}% | worst=${stats_b['worst']:+.2f} ({stats_b['max_dd_pct']:.2f}% eq)")
        diff = stats_b['total_pnl'] - stats_a['total_pnl']
        winner = "AVERAGING" if diff > 0 else "FIXED"
        print(f"    Delta    → PnL=${diff:+10.2f} ({winner})")
        print(f"    Worst trade: avg=${stats_b['worst']:+.2f} vs fixed=${stats_a['worst']:+.2f} "
              f"(ratio={abs(stats_b['worst']/stats_a['worst']):.1f}x)")
        print(f"    Max DD: avg={stats_b['max_dd_pct']:.2f}% vs fixed={stats_a['max_dd_pct']:.2f}% "
              f"(limit={args.max_loss}%)")

        all_stats[symbol] = {"fixed": stats_a, "averaging": stats_b, "outcomes": dict(outcomes_b)}

    # Summary
    print(f"\n{'='*90}")
    print(f"  CROSS-SYMBOL SUMMARY")
    print(f"{'='*90}")
    print(f"  {'Symbol':10s} | {'Fixed PnL':>12s} | {'Avg PnL':>12s} | {'Delta':>12s} | {'Winner':>10s} | "
          f"{'Avg WR':>6s} | {'Avg PF':>6s} | {'Avg MaxDD':>10s}")
    for sym, s in all_stats.items():
        f_pnl = s["fixed"]["total_pnl"]
        a_pnl = s["averaging"]["total_pnl"]
        delta = a_pnl - f_pnl
        winner = "AVERAGING" if delta > 0 else "FIXED"
        a_wr = s["averaging"]["win_rate"]
        a_pf = s["averaging"]["profit_factor"]
        a_dd = s["averaging"]["max_dd_pct"]
        print(f"  {sym:10s} | ${f_pnl:+11.2f} | ${a_pnl:+11.2f} | ${delta:+11.2f} | {winner:>10s} | "
              f"{a_wr:5.1f}% | {a_pf:5.2f} | {a_dd:9.2f}%")


if __name__ == "__main__":
    main()