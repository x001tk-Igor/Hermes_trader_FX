#!/usr/bin/env python3
"""Price alert sensor for multi-instrument XAU AI trader. Monitors key levels.

Reads alert levels from alerts.json, polls MT5 ticks every 20s.
When a level is crossed, sends Telegram alert and exits (wakes the agent).

alerts.json format:
{
  "levels": [
    {"symbol": "XAUUSD", "price": 4040.00, "direction": "below", "name": "Asian low breakdown", "action": "SHORT"},
    {"symbol": "EURUSD", "price": 1.1530, "direction": "above", "name": "EUR resistance break", "action": "LONG"}
  ],
  "expires_at": "2026-08-03T10:01:00Z"
}

If "symbol" is missing, defaults to "XAUUSD" (backward compat).

Usage: py -3 alert_sensor.py [--interval 20] [--max-runtime 3600]
"""
import json, os, sys, datetime, time, urllib.request, urllib.parse

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
ALERTS_FILE = os.path.join(SKILL_DIR, "alerts.json")
EXE = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PROXY = os.environ.get("TELEGRAM_PROXY", "")

import MetaTrader5 as mt5

def send_tg(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": "true"}).encode()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": PROXY, "http": PROXY}))
        opener.open(urllib.request.Request(url, data=data), timeout=10)
    except:
        pass

def load_alerts():
    if not os.path.exists(ALERTS_FILE):
        return None
    with open(ALERTS_FILE, "r") as f:
        return json.load(f)

def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)

def main():
    interval = 20
    max_runtime = 3600  # 1 hour max
    if "--interval" in sys.argv:
        interval = int(sys.argv[sys.argv.index("--interval") + 1])
    if "--max-runtime" in sys.argv:
        max_runtime = int(sys.argv[sys.argv.index("--max-runtime") + 1])

    alerts = load_alerts()
    if not alerts or "levels" not in alerts:
        print("No alerts.json or no levels — sensor idle")
        return

    # Check expiry
    expires = alerts.get("expires_at")
    if expires:
        exp_dt = datetime.datetime.fromisoformat(expires.replace("Z", "+00:00"))
        if now_utc() > exp_dt:
            print(f"Alerts expired at {expires}")
            return

    levels = alerts["levels"]
    # Collect all unique symbols to subscribe
    symbols = list(set(lv.get("symbol", "XAUUSD") for lv in levels))
    print(f"Sensor started: {len(levels)} levels, {len(symbols)} symbols, interval={interval}s, max={max_runtime}s")
    for lv in levels:
        sym = lv.get("symbol", "XAUUSD")
        print(f"  {sym:7s} {lv['name']}: {lv['price']} {lv['direction']} -> {lv.get('action', '?')}")

    # Init MT5
    mt5.shutdown(); time.sleep(0.3)
    if not mt5.initialize(path=EXE):
        print(f"INIT FAIL: {mt5.last_error()}")
        send_tg("Alert sensor: MT5 init failed")
        return

    # Subscribe all symbols
    for sym in symbols:
        mt5.symbol_select(sym, True)

    # Track previous prices PER SYMBOL
    prev_prices = {}
    triggered = set()
    t_start = time.time()

    # Get initial prices
    for sym in symbols:
        tick = mt5.symbol_info_tick(sym)
        if tick and tick.bid > 0:
            prev_prices[sym] = tick.bid
            # Check if price is ALREADY past any levels for this symbol
            for i, lv in enumerate(levels):
                if lv.get("symbol", "XAUUSD") != sym:
                    continue
                lvl_price = lv["price"]
                direction = lv["direction"]
                if direction == "above" and prev_prices[sym] >= lvl_price:
                    triggered.add(i)
                elif direction == "below" and prev_prices[sym] <= lvl_price:
                    triggered.add(i)
            print(f"  {sym}: initial={prev_prices[sym]}")

    while True:
        # Check max runtime
        if time.time() - t_start > max_runtime:
            print("Max runtime reached — exiting")
            mt5.shutdown()
            return

        for i, lv in enumerate(levels):
            if i in triggered:
                continue

            sym = lv.get("symbol", "XAUUSD")
            tick = mt5.symbol_info_tick(sym)
            if not tick or tick.bid == 0:
                continue

            price = tick.bid
            lvl_price = lv["price"]
            direction = lv["direction"]
            name = lv.get("name", f"level_{lvl_price}")
            action = lv.get("action", "?")
            prev_price = prev_prices.get(sym)

            if direction == "above" and prev_price is not None:
                if prev_price < lvl_price <= price:
                    msg = f"🔔 {sym}: {name}\nPrice {price} crossed ABOVE {lvl_price}\nAction: {action}\nTime: {now_utc().strftime('%H:%M')}Z"
                    print(msg); send_tg(msg); triggered.add(i)

            elif direction == "below" and prev_price is not None:
                if prev_price > lvl_price >= price:
                    msg = f"🔔 {sym}: {name}\nPrice {price} crossed BELOW {lvl_price}\nAction: {action}\nTime: {now_utc().strftime('%H:%M')}Z"
                    print(msg); send_tg(msg); triggered.add(i)

            elif direction == "touch":
                touch_dist = abs(price - lvl_price) / lvl_price * 100  # % distance
                if touch_dist <= 0.05:  # within 0.05% of level
                    msg = f"🔔 {sym}: {name}\nPrice {price} TOUCHED {lvl_price}\nAction: {action}\nTime: {now_utc().strftime('%H:%M')}Z"
                    print(msg); send_tg(msg); triggered.add(i)

            prev_prices[sym] = price

        # If ANY level triggered, exit immediately to wake the agent
        if len(triggered) > 0:
            print(f"{len(triggered)} level(s) triggered — exiting to wake agent")
            mt5.shutdown()
            return

        time.sleep(interval)

if __name__ == "__main__":
    main()