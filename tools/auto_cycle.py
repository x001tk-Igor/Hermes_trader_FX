#!/usr/bin/env python3
"""
auto_cycle.py v4 — DD MONITOR ONLY.

Does NOT open new positions.
Does NOT open addons.
Only: checks DD stop 2.5% per symbol, closes if exceeded, sends Telegram alert.
Position management (addons, TP, new entries) is done by the AI agent.

Runs as background process, checks every 5 minutes.
"""
import os, sys, time, datetime, urllib.request, urllib.parse
import MetaTrader5 as mt5

def load_env():
    p = os.path.expanduser("~/.claude/skills/xau-ai-trader/.env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k] = v

def send_tg(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except:
        pass

def get_positions_for_symbol(all_pos, sym):
    return [p for p in all_pos if p.symbol == sym]

def run_dd_check():
    """Check DD stop for all symbols with open positions. Close if > 2.5%."""
    terminal = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")
    if not mt5.initialize(terminal):
        return

    ai = mt5.account_info()
    all_pos = mt5.positions_get() or []
    
    if not all_pos:
        mt5.shutdown()
        return

    equity = ai.equity
    max_loss_usd = equity * 2.5 / 100.0
    symbols_with_pos = set(p.symbol for p in all_pos)
    alerts = []

    for sym in sorted(symbols_with_pos):
        positions = get_positions_for_symbol(all_pos, sym)
        if not positions:
            continue

        total_pnl = sum(p.profit for p in positions)
        pnl_pct = total_pnl / equity * 100

        if total_pnl <= -max_loss_usd:
            # DD STOP — close all positions on this symbol
            tick = mt5.symbol_info_tick(sym)
            info = mt5.symbol_info(sym)
            filling = mt5.ORDER_FILLING_FOK
            if info.filling_mode & 2:
                filling = mt5.ORDER_FILLING_IOC

            for p in positions:
                is_buy = p.type == 0
                if is_buy:
                    close_price = tick.bid
                    close_type = mt5.ORDER_TYPE_SELL
                else:
                    close_price = tick.ask
                    close_type = mt5.ORDER_TYPE_BUY
                req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym,
                       "position": p.ticket, "volume": p.volume, "type": close_type,
                       "price": close_price, "deviation": 100, "filling": filling}
                mt5.order_send(req)

            alerts.append(f"DD_STOP {sym}: closed {len(positions)} pos, PnL={total_pnl:+.2f} ({pnl_pct:+.2f}%)")

    mt5.shutdown()

    if alerts:
        msg = f"DD MONITOR {datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M')} UTC\n" + "\n".join(alerts)
        send_tg(msg)
        for a in alerts:
            print(f"  ALERT: {a}")

# ── Main loop ────────────────────────────────────────────────────────
if __name__ == "__main__":
    load_env()
    print(f"DD Monitor started. Checks every 5 minutes during trading hours.")
    print(f"Does NOT open positions or addons. Only DD stop protection.")

    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        
        if 6 <= now.hour <= 21 and now.weekday() < 5:
            try:
                run_dd_check()
            except Exception as e:
                print(f"DD check error: {e}")
                send_tg(f"DD MONITOR ERROR: {e}")
        
        time.sleep(300)  # 5 minutes