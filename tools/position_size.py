"""Position sizing + EV/RR for multi-instrument AI trader.

v3 — Supports averaging mode (lot sized for 3 positions × 1.5×ATR SL each).

Usage:
  # Fixed mode (1 position):
  py -3 position_size.py --equity 100000 --risk-pct 0.25 --entry 1.0850 --sl 1.0820 --contract-size 100000

  # Averaging mode (3 positions, max total loss = 1.7% equity):
  py -3 position_size.py --avg-mode --equity 100000 --max-loss-pct 1.7 --atr 0.0030 --contract-size 100000

  # EV calculator:
  py -3 position_size.py --ev --p-win 0.45 --rr 2.0 --entry 1.0850 --sl 1.0820 --contract-size 100000
"""
import argparse, math


def _floor_lot(lot, lot_step=0.01):
    lot = math.floor(lot / lot_step) * lot_step
    return round(lot, 2)


def cmd_size(args):
    """Fixed mode: 1 position, risk-pct of equity."""
    risk_amt = args.equity * (args.risk_pct / 100.0)
    stop_dist = abs(args.entry - args.sl)
    if stop_dist <= 0:
        print("INVALID: stop distance <= 0"); return
    contract = args.contract_size
    raw_lot = risk_amt / (stop_dist * contract)
    lot = _floor_lot(raw_lot, args.lot_step)
    actual_risk = lot * stop_dist * contract
    rr = (args.tp - args.entry) / stop_dist if (args.tp and args.sl < args.entry) \
        else (args.entry - args.tp) / stop_dist if (args.tp and args.sl > args.entry) \
        else None
    print(f"=== POSITION SIZE (fixed) ===")
    print(f"equity={args.equity:.2f} risk%={args.risk_pct} -> risk_amt=${risk_amt:.2f}")
    print(f"entry={args.entry} sl={args.sl} stop_dist={stop_dist} contract={contract}")
    print(f"raw_lot={raw_lot:.4f} -> rounded_lot={lot:.2f}")
    print(f"actual_risk@lot=${actual_risk:.2f} ({actual_risk/args.equity*100:.3f}% of equity)")
    if rr is not None:
        print(f"tp={args.tp} RR={rr:.2f}")
    if lot < args.lot_min:
        print(f"VERDICT: SKIP (lot {lot} below minimum {args.lot_min})")
    else:
        print(f"VERDICT: OK lot={lot:.2f}")


def cmd_avg_size(args):
    """Averaging mode: lot sized for 3 positions × 1.5×ATR SL = max_loss_pct of equity.
    
    lot = (equity × max_loss_pct/100) / (3 × 1.5 × ATR × contract)
    """
    max_positions = 3  # 1 main + 2 addons
    sl_atr_mult = 2.5
    max_loss_usd = args.equity * (args.max_loss_pct / 100.0)
    sl_dist = sl_atr_mult * args.atr
    denom = max_positions * sl_dist * args.contract_size
    if denom <= 0:
        print("INVALID: ATR or contract size <= 0"); return
    
    raw_lot = max_loss_usd / denom
    lot = _floor_lot(raw_lot, args.lot_step)
    
    # Actual max loss if all 3 SLs hit
    actual_max_loss = max_positions * lot * sl_dist * args.contract_size
    actual_loss_pct = actual_max_loss / args.equity * 100
    
    # Per-position risk
    per_pos_risk = lot * sl_dist * args.contract_size
    
    # TP distance (weighted avg + 0.5×ATR, approximate)
    tp_dist = 0.5 * args.atr
    
    print(f"=== POSITION SIZE (averaging) ===")
    print(f"equity={args.equity:.2f} max_loss%={args.max_loss_pct} -> max_loss${max_loss_usd:.2f}")
    print(f"ATR={args.atr} sl_dist={sl_dist:.6f} (1.5×ATR)")
    print(f"contract={args.contract_size} max_positions={max_positions}")
    print(f"raw_lot={raw_lot:.6f} -> rounded_lot={lot:.2f}")
    print(f"per_position_risk=${per_pos_risk:.2f}")
    print(f"worst_case_3xSL=${actual_max_loss:.2f} ({actual_loss_pct:.3f}% of equity)")
    print(f"addon1_at=-1.0×ATR={args.atr:.6f} addon2_at=-2.0×ATR={2*args.atr:.6f}")
    print(f"tp_dist=0.5×ATR={tp_dist:.6f} from weighted_avg")
    
    if lot < args.lot_min:
        print(f"VERDICT: SKIP (lot {lot} below minimum {args.lot_min})")
    elif actual_loss_pct > args.max_loss_pct + 0.3:
        print(f"VERDICT: SKIP (actual loss {actual_loss_pct:.3f}% exceeds limit)")
    else:
        print(f"VERDICT: OK lot={lot:.2f} per_position max_3xSL={actual_loss_pct:.3f}%")


def cmd_ev(args):
    stop_dist = abs(args.entry - args.sl)
    if stop_dist <= 0:
        print("INVALID: stop distance <= 0"); return
    contract = args.contract_size
    cost_usd_per_lot = (args.commission_per_lot or 0.0) + (args.slippage_usd or 0.0) * contract
    spread_usd_per_lot = (args.spread_usd or 0.20) * contract
    costs_usd_per_lot = cost_usd_per_lot + spread_usd_per_lot
    costs_r = costs_usd_per_lot / (stop_dist * contract)
    rr = args.rr
    p = args.p_win
    ev_r = p * rr - (1 - p) * 1 - costs_r
    be_p = (1 + costs_r) / (1 + rr)
    print(f"=== EV / RR ===")
    print(f"p_win={p} RR={rr} stop_dist={stop_dist} contract={contract}")
    print(f"costs_R={costs_r:.4f}  (spread={args.spread_usd or 0.20} comm={args.commission_per_lot or 0} slip={args.slippage_usd or 0})")
    print(f"EV_R={ev_r:+.4f}  (need >= +0.25)")
    print(f"breakeven_P={be_p:.4f}  edge_over_be={(p-be_p)*100:+.2f}%  (need >= +5%)")
    print("VERDICT:", "OK" if (ev_r >= 0.25 and (p - be_p) >= 0.05) else "FAIL")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--equity", type=float)
    ap.add_argument("--risk-pct", type=float)
    ap.add_argument("--entry", type=float)
    ap.add_argument("--sl", type=float)
    ap.add_argument("--tp", type=float)
    ap.add_argument("--contract-size", type=float, default=100000.0, help="100000=FX pairs")
    ap.add_argument("--lot-step", type=float, default=0.01)
    ap.add_argument("--lot-min", type=float, default=0.01)
    ap.add_argument("--commission-per-lot", type=float, default=0.0)
    ap.add_argument("--slippage-usd", type=float, default=0.0)
    ap.add_argument("--spread-usd", type=float, default=0.0001, help="0.0001=FX 5-digit")
    ap.add_argument("--ev", action="store_true")
    ap.add_argument("--p-win", type=float)
    ap.add_argument("--rr", type=float)
    # Averaging mode
    ap.add_argument("--avg-mode", action="store_true")
    ap.add_argument("--max-loss-pct", type=float, default=1.7, help="Max total loss % for 3 positions")
    ap.add_argument("--atr", type=float, help="ATR value for averaging mode")
    a = ap.parse_args()
    
    if a.ev:
        cmd_ev(a)
    elif a.avg_mode:
        if not a.atr:
            print("ERROR: --atr required for --avg-mode"); exit(1)
        cmd_avg_size(a)
    else:
        cmd_size(a)