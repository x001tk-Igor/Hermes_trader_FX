"""Economic calendar blackout windows for the FX AI trader (v3).

Source: ForexFactory public JSON (nfs.faireconomy.media) — fetched directly from
the machine. Times are US local with offset; we convert to UTC.

v3: filters for all 6 traded currencies (EUR, USD, GBP, CAD, AUD, NZD) and maps
events to affected symbols via CURRENCY_MAP.

Usage:
  py -3 calendar.py today       -> today's high-impact + extended events, blackout windows in UTC
  py -3 calendar.py check <iso> -> is the given UTC datetime inside any blackout window?
  py -3 calendar.py next        -> next upcoming blackout window (within 7 days)
  py -3 calendar.py symbols     -> which symbols are currently in blackout
"""
import sys, json, urllib.request, datetime
import xau_env as E

URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]

# v3: all currencies we trade
TRADED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD", "NZD"}


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _all_events():
    out = []
    for u in URLS:
        try:
            out.extend(_fetch(u))
        except Exception:
            # FF nextweek.json often 404s mid-week — silent skip (thisweek covers today/tomorrow)
            pass
    return out


def _is_extended(title):
    t = (title or "").lower()
    return any(k in t for k in E.EXTENDED_KEYWORDS)


def _to_utc(dt_str):
    """FF date like '2026-07-24T09:45:00-04:00'. Parse to aware UTC."""
    try:
        dt = datetime.datetime.fromisoformat(dt_str)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None


def _blackout(ev):
    """Return (start_utc, end_utc, kind, title) for a USD high/extended event."""
    t0 = _to_utc(ev.get("date"))
    if not t0: return None
    title = ev.get("title","?")
    impact = (ev.get("impact") or "").lower()
    if _is_extended(title) and impact in ("high","medium"):
        pre, post = E.EXTENDED_PRE_MIN, E.EXTENDED_POST_MIN
        kind = "EXTENDED(60/30)"
    elif impact == "high":
        pre, post = E.HIGH_PRE_MIN, E.HIGH_POST_MIN
        kind = "HIGH(30/15)"
    else:
        return None  # medium/low without extended name -> no formal blackout
    start = t0 - datetime.timedelta(minutes=pre)
    end   = t0 + datetime.timedelta(minutes=post)
    return start, end, kind, title


def _windows(days=2):
    """Get blackout windows for all traded currencies (v3)."""
    evs = [e for e in _all_events() if e.get("country") in TRADED_CURRENCIES]
    wins = []
    for ev in evs:
        b = _blackout(ev)
        if b:
            start, end, kind, title = b
            country = ev.get("country", "")
            wins.append((start, end, kind, title, country))
    return wins


def _affected_symbols(country):
    """Map currency code to affected trading symbols via CURRENCY_MAP."""
    affected = []
    for sym, currencies in E.CURRENCY_MAP.items():
        if country in currencies:
            affected.append(sym)
    return affected


def cmd_today():
    now = datetime.datetime.now(datetime.timezone.utc)
    wins = _windows(2)
    print("=== TODAY BLACKOUT WINDOWS (UTC, all traded currencies) ===")
    any_ = False
    for start, end, kind, title, country in sorted(wins):
        if (start.date() == now.date()) or (start.date() == (now+datetime.timedelta(days=1)).date()):
            any_ = True
            syms = ", ".join(_affected_symbols(country))
            print(f"{start.isoformat()}  ->  {end.isoformat()}  [{kind}] {country} {title}  → {syms}")
    if not any_: print("(no blackout windows today/tomorrow)")
    inside = [w for w in wins if w[0] <= now <= w[1]]
    print(f"NOW_INSIDE_BLACKOUT: {bool(inside)}")
    for w in inside:
        syms = ", ".join(_affected_symbols(w[4]))
        print(f"  -> {w[3]} ({w[4]}) until {w[1].isoformat()} → {syms}")


def cmd_check(iso):
    try:
        t = datetime.datetime.fromisoformat(iso)
        if t.tzinfo is None: t = t.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        print("bad iso dt"); return
    wins = _windows(2)
    hit = [w for w in wins if w[0] <= t <= w[1]]
    print(f"INSIDE_BLACKOUT({iso}): {bool(hit)}")
    for start,end,kind,title,country in hit:
        syms = ", ".join(_affected_symbols(country))
        print(f"  {start.isoformat()}->{end.isoformat()} [{kind}] {country} {title} → {syms}")


def cmd_next():
    now = datetime.datetime.now(datetime.timezone.utc)
    wins = [w for w in _windows(7) if w[1] > now]
    if not wins:
        print("(no upcoming blackout in next week)"); return
    start,end,kind,title,country = sorted(wins)[0]
    syms = ", ".join(_affected_symbols(country))
    print(f"NEXT BLACKOUT: {title} [{kind}] ({country})")
    print(f"  starts {start.isoformat()} (in {(start-now).total_seconds()/60:.0f} min)")
    print(f"  ends   {end.isoformat()}")
    print(f"  affected: {syms}")


def cmd_symbols():
    """Show which symbols are currently in blackout."""
    now = datetime.datetime.now(datetime.timezone.utc)
    wins = _windows(2)
    inside = [w for w in wins if w[0] <= now <= w[1]]
    if not inside:
        print("NO SYMBOLS IN BLACKOUT NOW")
        return
    blocked_symbols = set()
    print("=== SYMBOLS CURRENTLY IN BLACKOUT ===")
    for w in inside:
        syms = _affected_symbols(w[4])
        for s in syms:
            blocked_symbols.add(s)
            print(f"  {s}: {w[3]} ({w[4]}) until {w[1].isoformat()}")
    print(f"BLOCKED_SYMBOLS: {','.join(sorted(blocked_symbols))}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "today"
    if cmd == "check": cmd_check(sys.argv[2])
    elif cmd == "next": cmd_next()
    elif cmd == "symbols": cmd_symbols()
    else: cmd_today()