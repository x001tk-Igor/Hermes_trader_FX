"""Economic calendar blackout windows for the XAUUSD AI trader.

Source: ForexFactory public JSON (nfs.faireconomy.media) — fetched directly from
the machine (WebFetch blocks the domain). Times are US local with offset; we
convert to UTC.

Usage:
  py -3 calendar.py today       -> today's USD high-impact + extended events, blackout windows in UTC
  py -3 calendar.py check <iso> -> is the given UTC datetime inside any blackout window?
  py -3 calendar.py next        -> next upcoming blackout window (within 7 days)
"""
import sys, json, urllib.request, datetime
import xau_env as E

URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]


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
    evs = [e for e in _all_events() if e.get("country") == "USD"]
    wins = []
    for ev in evs:
        b = _blackout(ev)
        if b:
            start, end, kind, title = b
            wins.append((start, end, kind, title))
    return wins


def cmd_today():
    now = datetime.datetime.now(datetime.timezone.utc)
    wins = _windows(2)
    print("=== TODAY USD BLACKOUT WINDOWS (UTC) ===")
    any_ = False
    for start, end, kind, title in sorted(wins):
        # show today's + tomorrow's relevant
        if (start.date() == now.date()) or (start.date() == (now+datetime.timedelta(days=1)).date()):
            any_ = True
            print(f"{start.isoformat()}  ->  {end.isoformat()}  [{kind}] {title}")
    if not any_: print("(no blackout windows today/tomorrow)")
    # is now inside?
    inside = [w for w in wins if w[0] <= now <= w[1]]
    print(f"NOW_INSIDE_BLACKOUT: {bool(inside)}")
    for w in inside: print(f"  -> {w[3]} until {w[1].isoformat()}")


def cmd_check(iso):
    try:
        t = datetime.datetime.fromisoformat(iso)
        if t.tzinfo is None: t = t.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        print("bad iso dt"); return
    wins = _windows(2)
    hit = [w for w in wins if w[0] <= t <= w[1]]
    print(f"INSIDE_BLACKOUT({iso}): {bool(hit)}")
    for start,end,kind,title in hit:
        print(f"  {start.isoformat()}->{end.isoformat()} [{kind}] {title}")


def cmd_next():
    now = datetime.datetime.now(datetime.timezone.utc)
    wins = [w for w in _windows(7) if w[1] > now]
    if not wins:
        print("(no upcoming blackout in next week)"); return
    start,end,kind,title = sorted(wins)[0]
    print(f"NEXT BLACKOUT: {title} [{kind}]")
    print(f"  starts {start.isoformat()} (in {(start-now).total_seconds()/60:.0f} min)")
    print(f"  ends   {end.isoformat()}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "today"
    if cmd == "check": cmd_check(sys.argv[2])
    elif cmd == "next": cmd_next()
    else: cmd_today()