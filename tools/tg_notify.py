#!/usr/bin/env python3
"""Send a message to Telegram via Bot API with proxy support.

Usage:
  py -3 tg_notify.py "Cycle 07:16 SKIP: range 4090-4100, no trigger"
  py -3 tg_notify.py "OPEN SELL XAUUSD 0.01 @ 4063 SL 4072 TP 4040"
  echo "message" | py -3 tg_notify.py -

Environment:
  TELEGRAM_BOT_TOKEN  - bot token from BotFather
  TELEGRAM_CHAT_ID     - destination chat ID
  TELEGRAM_PROXY       - HTTP proxy URL (e.g. http://127.0.0.1:PROXY_PORT)
"""
import os, sys, json, urllib.request, urllib.parse

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PROXY = os.environ.get("TELEGRAM_PROXY", "")

def send(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    proxy_handler = urllib.request.ProxyHandler({"https": PROXY, "http": PROXY})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url, data=data)
    try:
        resp = opener.open(req, timeout=15)
        result = json.loads(resp.read())
        if result.get("ok"):
            return True
        else:
            print(f"Telegram API error: {result}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"Telegram send failed: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: tg_notify.py <message>", file=sys.stderr)
        sys.exit(1)
    msg = sys.argv[1]
    if msg == "-":
        msg = sys.stdin.read().strip()
    ok = send(msg)
    sys.exit(0 if ok else 1)