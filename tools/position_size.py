"""Position sizing + EV/RR for multi-instrument XAU AI trader (§11, §10 шаг6).

Usage:
  py -3 position_size.py --equity 92874 --risk-pct 0.25 --entry 4026.76 --sl 4021.00 [--tp 4040.00] [--contract-size 100] [--spread-usd 0.20]
  py -3 position_size.py --ev --p-win 0.45 --rr 2.0 --entry 4026.76 --sl 4021.00 [--contract-size 100] [--spread-usd 0.20]

Defaults: contract-size=100 (XAUUSD), spread-usd=0.20, lot-step=0.01, lot-min=0.01.
For FX pairs: --contract-size 100000 --spread-usd 0.0001 (adjust per pair).
"""
import argparse, math


def _floor_lot(lot, lot_step=0.01):
    lot = math.floor(lot / lot_step) * lot_step
    return round(lot, 2)


def cmd_size(args):
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
    print(f"=== POSITION SIZE ===")
    print(f"equity={args.equity:.2f} risk%={args.risk_pct} -> risk_amt=${risk_amt:.2f}")
    print(f"entry={args.entry} sl={args.sl} stop_dist={stop_dist} contract={contract}")
    print(f"raw_lot={raw_lot:.4f} -> rounded_lot={lot:.2f}")
    print(f"actual_risk@lot=${actual_risk:.2f} ({actual_risk/args.equity*100:.3f}% of equity)")
    if rr is not None:
        print(f"tp={args.tp} RR={rr:.2f}  (need >=1.5)")
    if lot < args.lot_min:
        print(f"VERDICT: SKIP (lot {lot} below minimum {args.lot_min})")
    elif actual_risk / args.equity > 0.0025 + 1e-9:
        print(f"VERDICT: SKIP (actual risk {actual_risk/args.equity*100:.3f}% > 0.25% cap)")
    else:
        print(f"VERDICT: OK lot={lot:.2f}")


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
    ap.add_argument("--equity", type=float); ap.add_argument("--risk-pct", type=float)
    ap.add_argument("--entry", type=float); ap.add_argument("--sl", type=float); ap.add_argument("--tp", type=float)
    ap.add_argument("--contract-size", type=float, default=100.0, help="100=XAUUSD, 100000=FX pairs")
    ap.add_argument("--lot-step", type=float, default=0.01)
    ap.add_argument("--lot-min", type=float, default=0.01)
    ap.add_argument("--commission-per-lot", type=float, default=0.0)
    ap.add_argument("--slippage-usd", type=float, default=0.0)
    ap.add_argument("--spread-usd", type=float, default=0.20, help="0.20=XAUUSD, 0.0001=FX 5-digit")
    ap.add_argument("--ev", action="store_true")
    ap.add_argument("--p-win", type=float); ap.add_argument("--rr", type=float)
    a = ap.parse_args()
    if a.ev:
        cmd_ev(a)
    else:
        cmd_size(a)