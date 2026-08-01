#!/usr/bin/env python3
"""Live manual trading on MT5 via the Python MetaTrader5 library.

Generalized — no hardcoded terminal hash. Auto-discovers terminals from
%APPDATA%\\MetaQuotes\\Terminal\\ if --hash not given.

Usage:
  trade.py account [--hash H | --terminal PATH]
  trade.py positions [--symbol S] [--hash H]
  trade.py probe [--symbol S] [--hash H]
  trade.py open --symbol S --side buy|sell --lot L [--sl P --tp P]
                 [--wait-reopen] [--comment TXT] [--magic N] [--hash H | --terminal PATH]
  trade.py close --ticket N | --symbol S [--all] [--hash H | --terminal PATH]
  trade.py sltp --ticket N [--sl P] [--tp P] [--hash H | --terminal PATH]

Terminal selection (in order of priority):
  1. --terminal <path-to-terminal64.exe>
  2. --hash <data-dir-hash>  (looked up via origin.txt)
  3. Auto-discover: first terminal found in %APPDATA%\\MetaQuotes\\Terminal\\
"""
import argparse, os, sys, time, glob
import MetaTrader5 as mt5

TRADE_MODE_ACCT = {0: "REAL", 1: "DEMO", 2: "CONTEST"}
RETCODES = {
    10009: "DONE", 10013: "INVALID", 10014: "INVALID_VOLUME", 10015: "INVALID_PRICE",
    10016: "INVALID_STOPS", 10018: "MARKET_CLOSED", 10019: "NO_MONEY",
    10027: "AUTOTRADING_DISABLED", 10030: "INVALID_FILL", 10031: "NO_CONNECTION",
    10032: "PRICE_CHANGED", 10033: "PRICE_OFF",
}
FILLINGS = [
    ("FOK", mt5.ORDER_FILLING_FOK),
    ("IOC", mt5.ORDER_FILLING_IOC),
    ("RETURN", mt5.ORDER_FILLING_RETURN),
]


def _discover_first_terminal():
    """Auto-discover the first MT5 terminal on this machine."""
    base = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")
    if not os.path.isdir(base):
        return None
    for h in sorted(os.listdir(base)):
        origin = os.path.join(base, h, "origin.txt")
        if not os.path.isfile(origin):
            continue
        with open(origin, "r", errors="ignore") as f:
            exe = f.read().strip()
        if exe and os.path.exists(exe):
            return exe
    return None


def resolve_terminal(args):
    if args.terminal:
        return args.terminal
    h = getattr(args, "hash", None) or getattr(args, "_hash", None)
    if h:
        base = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal", h)
        origin = os.path.join(base, "origin.txt")
        if os.path.exists(origin):
            with open(origin, "r", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and os.path.exists(line):
                        return line
        raise SystemExit(f"unknown hash {h}; pass --terminal <path-to-terminal64.exe>")
    # Auto-discover
    exe = _discover_first_terminal()
    if exe:
        return exe
    raise SystemExit("No terminal found. Pass --hash <hash> or --terminal <path>.")


def init_mt5(args):
    exe = resolve_terminal(args)
    mt5.shutdown(); time.sleep(0.4)
    if not mt5.initialize(path=exe):
        print("INIT FAIL:", mt5.last_error()); mt5.shutdown(); raise SystemExit(1)
    return exe


def side_type(side):
    side = side.lower()
    if side in ("buy", "long"):
        return mt5.ORDER_TYPE_BUY
    if side in ("sell", "short"):
        return mt5.ORDER_TYPE_SELL
    raise SystemExit("--side must be buy|sell")


def send_with_filling(req_factory):
    """req_factory(filling_enum) -> request dict. Tries FOK, IOC, RETURN."""
    for name, f in FILLINGS:
        res = mt5.order_send(req_factory(f))
        rc = res.retcode if res else None
        print(f"   {name} rc={rc} ({RETCODES.get(rc, '?')}) "
              f"deal={res.deal if res else None} price={res.price if res else None}")
        if res and res.retcode == 10009:
            return res, name
        if rc == 10030:  # unsupported filling -> try next
            continue
        return res, name  # any other code -> stop, report
    return res, name


# ---------- commands ----------

def cmd_account(args):
    init_mt5(args)
    a = mt5.account_info(); t = mt5.terminal_info()
    print("=== ACCOUNT ===")
    print("login        :", a.login)
    print("server       :", a.server)
    print("name         :", a.name)
    print("company      :", a.company)
    print("currency     :", a.currency)
    print("trade_mode   :", TRADE_MODE_ACCT.get(a.trade_mode, f"?({a.trade_mode})"))
    print("balance      :", a.balance)
    print("equity       :", a.equity)
    print("margin       :", a.margin)
    print("margin_free  :", a.margin_free)
    print("profit       :", a.profit)
    print("leverage     :", a.leverage)
    print("connected    :", t.connected)
    mt5.shutdown()


def cmd_positions(args):
    init_mt5(args)
    if args.symbol:
        mt5.symbol_select(args.symbol, True)
        ps = mt5.positions_get(symbol=args.symbol)
    else:
        ps = mt5.positions_get()
    if not ps:
        print("no open positions"); mt5.shutdown(); return
    print(f"=== {len(ps)} OPEN POSITION(S) ===")
    for p in ps:
        d = p._asdict()
        print(f"ticket={d['ticket']} {'BUY' if d['type'] == 0 else 'SELL'} "
              f"sym={d['symbol']} vol={d['volume']} open={d['price_open']} "
              f"sl={d['sl']} tp={d['tp']} profit={d['profit']} comment={d['comment']!r}")
    mt5.shutdown()


def cmd_probe(args):
    init_mt5(args)
    syms = [args.symbol] if args.symbol else ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "XAGUSD"]
    rows = []
    for s in syms:
        if not mt5.symbol_select(s, True):
            rows.append((s, None)); continue
        t = mt5.symbol_info_tick(s)
        rows.append((s, t))
    max_t = max((t.time for (_, t) in rows if t and t.time > 0), default=0)
    for s, t in rows:
        if t is None:
            print(f"{s}: select FAIL"); continue
        if t.time == 0 or t.bid == 0:
            print(f"{s}: tick_time={t.time} bid={t.bid} -> NOT_SUBSCRIBED"); continue
        lag = max_t - t.time
        fresh = "OPEN" if lag <= 120 else "CLOSED/stale"
        print(f"{s}: bid={t.bid} ask={t.ask} tick_time={t.time} lag_s={lag} -> {fresh}")
    mt5.shutdown()


def cmd_open(args):
    init_mt5(args)
    S = args.symbol
    if not mt5.symbol_select(S, True):
        print(f"symbol_select FAIL for {S}:", mt5.last_error()); mt5.shutdown(); raise SystemExit(1)
    info = mt5.symbol_info(S)
    otype = side_type(args.side)
    is_buy = (otype == mt5.ORDER_TYPE_BUY)

    def attempt_send():
        t = mt5.symbol_info_tick(S)
        if not t or t.time == 0 or t.bid == 0:
            return None, "no tick (market closed / not subscribed)"
        price = round(t.ask if is_buy else t.bid, info.digits)
        def req(f):
            r = {"action": mt5.TRADE_ACTION_DEAL, "symbol": S, "volume": args.lot,
                 "type": otype, "price": price, "deviation": args.deviation,
                 "magic": args.magic, "comment": args.comment,
                 "type_time": mt5.ORDER_TIME_GTC, "type_filling": f}
            if args.sl: r["sl"] = round(args.sl, info.digits)
            if args.tp: r["tp"] = round(args.tp, info.digits)
            return r
        res, _ = send_with_filling(req)
        return res, None

    t0 = mt5.symbol_info_tick(S)
    last = t0.time if t0 else 0
    deadline = time.time() + (300 if args.wait_reopen else 0)
    while True:
        res, err = attempt_send()
        if err:
            print("tick:", err)
        if res and res.retcode == 10009:
            break
        rc = res.retcode if res else None
        if rc == 10018 or err:
            if not args.wait_reopen:
                print("MARKET_CLOSED (frozen tick). Re-run with --wait-reopen to poll, "
                      "or pick an open symbol via `probe`.")
                mt5.shutdown(); raise SystemExit(2)
            if time.time() >= deadline:
                print("still MARKET_CLOSED after 5 min; giving up.")
                mt5.shutdown(); raise SystemExit(2)
            time.sleep(5); continue
        print("order not filled. retcode:", rc, f"({RETCODES.get(rc, '?')})",
              "last_error:", mt5.last_error())
        mt5.shutdown(); raise SystemExit(1)

    print("=== FILLED ===")
    print("deal        :", res.deal)
    print("order       :", res.order)
    print("price_done  :", res.price)
    print("volume_done :", res.volume)
    time.sleep(0.8)
    ps = mt5.positions_get(symbol=S)
    if ps:
        for p in ps:
            d = p._asdict()
            print(f"POS ticket={d['ticket']} {'BUY' if d['type'] == 0 else 'SELL'} "
                  f"vol={d['volume']} open={d['price_open']} sl={d['sl']} tp={d['tp']} "
                  f"profit={d['profit']} comment={d['comment']!r}")
    else:
        print("WARNING: positions_get empty right after fill — confirm manually in terminal.")
    mt5.shutdown()


def cmd_close(args):
    init_mt5(args)
    targets = []
    if args.ticket:
        p = mt5.positions_get(ticket=args.ticket)
        if not p:
            print("no position with ticket", args.ticket); mt5.shutdown(); raise SystemExit(1)
        targets = list(p)
    elif args.symbol:
        mt5.symbol_select(args.symbol, True)
        ps = mt5.positions_get(symbol=args.symbol)
        if not ps:
            print("no open positions on", args.symbol); mt5.shutdown(); return
        targets = list(ps) if args.all else [ps[0]]
    else:
        raise SystemExit("close needs --ticket N or --symbol S")
    info = mt5.symbol_info(targets[0].symbol)
    for pos in targets:
        S = pos.symbol
        is_long = (pos.type == 0)
        close_type = mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY
        print(f"closing ticket={pos.ticket} {'LONG' if is_long else 'SHORT'} "
              f"vol={pos.volume} sym={S}")
        def req(f):
            t = mt5.symbol_info_tick(S)
            price = round(t.bid if is_long else t.ask, info.digits)
            return {"action": mt5.TRADE_ACTION_DEAL, "symbol": S, "volume": pos.volume,
                    "type": close_type, "position": pos.ticket, "price": price,
                    "deviation": args.deviation, "magic": 0, "comment": "",
                    "type_time": mt5.ORDER_TIME_GTC, "type_filling": f}
        res, _ = send_with_filling(req)
        if not (res and res.retcode == 10009):
            print("  CLOSE FAILED retcode:", res.retcode if res else None,
                  mt5.last_error())
    time.sleep(0.6)
    ps = mt5.positions_get()
    print("remaining open positions:", len(ps) if ps else 0)
    a = mt5.account_info()
    print("balance:", a.balance, "equity:", a.equity, "profit:", a.profit)
    mt5.shutdown()


def cmd_sltp(args):
    init_mt5(args)
    p = mt5.positions_get(ticket=args.ticket)
    if not p:
        print("no position", args.ticket); mt5.shutdown(); raise SystemExit(1)
    pos = p[0]; info = mt5.symbol_info(pos.symbol)
    req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": pos.symbol,
           "position": pos.ticket,
           "sl": round(args.sl, info.digits) if args.sl is not None else pos.sl,
           "tp": round(args.tp, info.digits) if args.tp is not None else pos.tp}
    res = mt5.order_send(req)
    print("sltp retcode:", res.retcode if res else None,
          mt5.last_error() if (not res or res.retcode != 10009) else "")
    mt5.shutdown()


def main():
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--hash", default=None)
    parent.add_argument("--terminal", default=None)

    ap = argparse.ArgumentParser(parents=[parent])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("account", parents=[parent])
    sp = sub.add_parser("positions", parents=[parent]); sp.add_argument("--symbol", default=None)
    sp = sub.add_parser("probe", parents=[parent]); sp.add_argument("--symbol", default=None)

    sp = sub.add_parser("open", parents=[parent])
    sp.add_argument("--symbol", required=True)
    sp.add_argument("--side", required=True)
    sp.add_argument("--lot", type=float, required=True)
    sp.add_argument("--sl", type=float, default=None)
    sp.add_argument("--tp", type=float, default=None)
    sp.add_argument("--comment", default="")
    sp.add_argument("--magic", type=int, default=0)
    sp.add_argument("--deviation", type=int, default=50)
    sp.add_argument("--wait-reopen", action="store_true")

    sp = sub.add_parser("close", parents=[parent])
    sp.add_argument("--ticket", type=int, default=None)
    sp.add_argument("--symbol", default=None)
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--deviation", type=int, default=50)

    sp = sub.add_parser("sltp", parents=[parent])
    sp.add_argument("--ticket", type=int, required=True)
    sp.add_argument("--sl", type=float, default=None)
    sp.add_argument("--tp", type=float, default=None)

    args = ap.parse_args()
    {"account": cmd_account, "positions": cmd_positions, "probe": cmd_probe,
     "open": cmd_open, "close": cmd_close, "sltp": cmd_sltp}[args.cmd](args)


if __name__ == "__main__":
    main()