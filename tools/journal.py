"""Trade journal + daily stats for the XAUUSD AI trader (§16).

CSV columns (§16.1):
  action, entry_date, exit_date, tactic, direction, regime, daily_bias,
  dxy_ctx, y10_ctx, real_yield_ctx, risk_sentiment, confluence, rr, ev_r,
  p_win, entry, sl, tp, sl_dist, risk_pct, lot, spread_in, spread_out,
  atr, session, round_level, liq_sweep, reason_in, reason_out, pnl_usd, pnl_r,
  errors, notes

Usage:
  py -3 journal.py add <field=value> ...      -> append a row
  py -3 journal.py stats                      -> today's closed-trade stats + gate hint
  py -3 journal.py weekly                     -> last 7 days realized PnL
  py -3 journal.py last [N]                   -> last N rows
"""
import sys, csv, datetime, json
import xau_env as E

FIELDS = [
 "action","entry_date","exit_date","tactic","direction","regime","daily_bias",
 "dxy_ctx","y10_ctx","real_yield_ctx","risk_sentiment","confluence","rr","ev_r",
 "p_win","entry","sl","tp","sl_dist","risk_pct","lot","spread_in","spread_out",
 "atr","session","round_level","liq_sweep","reason_in","reason_out","pnl_usd","pnl_r",
 "errors","notes",
]


def _ensure():
    E.JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    if not E.JOURNAL_CSV.exists():
        with open(E.JOURNAL_CSV, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def cmd_add(kvs):
    _ensure()
    row = {k: "" for k in FIELDS}
    now = _now().isoformat()
    for kv in kvs:
        if "=" not in kv: continue
        k, v = kv.split("=", 1)
        if k in row: row[k] = v
    if row["action"] == "OPEN" and not row["entry_date"]: row["entry_date"] = now
    if row["action"] == "CLOSE" and not row["exit_date"]: row["exit_date"] = now
    with open(E.JOURNAL_CSV, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(row)
    print("APPENDED:", row["action"], row.get("tactic"), row.get("direction"),
          row.get("entry"), row.get("sl"))


def _rows():
    _ensure()
    with open(E.JOURNAL_CSV, newline="") as f:
        return list(csv.DictReader(f))


def _closed_today():
    today = _now().date().isoformat()
    return [r for r in _rows() if r["action"]=="CLOSE" and r["exit_date"].startswith(today)]


def cmd_stats():
    rows = _closed_today()
    pnls = [float(r["pnl_usd"]) for r in rows if r["pnl_usd"]]
    pnlrs = [float(r["pnl_r"]) for r in rows if r["pnl_r"]]
    wins = [x for x in pnls if x > 0]; losses = [x for x in pnls if x < 0]
    gross_w = sum(wins); gross_l = -sum(losses)
    pf = gross_w / gross_l if gross_l > 0 else float("inf")
    # consecutive losses streak (tail)
    consec = 0
    for r in rows[::-1]:
        try:
            if float(r["pnl_usd"]) < 0: consec += 1
            else: break
        except: break
    sod = json.loads(E.SOD_FILE.read_text())["equity"] if E.SOD_FILE.exists() else None
    realized = sum(pnls)
    daily_loss_pct = -realized / sod if sod else 0.0
    print("=== TODAY STATS ===")
    print(f"closed_trades={len(rows)} pnl_usd={realized:+.2f} pnl_r={sum(pnlrs):+.2f}")
    print(f"win_rate={len(wins)}/{len(rows)} avg_win={sum(wins)/len(wins) if wins else 0:.2f} "
          f"avg_loss={sum(losses)/len(losses) if losses else 0:.2f} PF={pf:.2f}")
    print(f"consec_losses={consec} realized_today={realized:+.2f} daily_loss%={daily_loss_pct*100:+.2f}%")
    # gate hint
    flags = []
    if daily_loss_pct >= E.DAILY_LOSS_HALT: flags.append("DAILY_LOSS_HALT>=1%")
    elif daily_loss_pct >= 0.005: flags.append("DAILY_LOSS_>=0.5%:risk<=0.15%,A-only")
    if consec >= 4: flags.append("4LOSSES:halt new today")
    elif consec == 3: flags.append("3LOSSES:pause 1h")
    elif consec == 2: flags.append("2LOSSES:risk<=0.15% next 2h")
    print("GATE_HINT:", ", ".join(flags) if flags else "OK")


def cmd_weekly():
    since = (_now() - datetime.timedelta(days=7)).date().isoformat()
    rows = [r for r in _rows() if r["action"]=="CLOSE" and r["exit_date"] >= since]
    pnl = sum(float(r["pnl_usd"]) for r in rows if r["pnl_usd"])
    print(f"weekly_realized_pnl(7d)={pnl:+.2f}  closed={len(rows)}")


def cmd_last(n=10):
    for r in _rows()[-n:]:
        print(r["entry_date"][:16], r["action"], r.get("tactic"), r.get("direction"),
              r.get("entry"), "->", r.get("pnl_usd"))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "add": cmd_add(sys.argv[2:])
    elif cmd == "weekly": cmd_weekly()
    elif cmd == "last": cmd_last(int(sys.argv[2]) if len(sys.argv)>2 else 10)
    else: cmd_stats()