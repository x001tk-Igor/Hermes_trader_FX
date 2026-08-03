#!/usr/bin/env python3
"""
Autonomous cycle runner — runs every N seconds, no cron needed.
Executes: gate, market scan, addon check, DD monitor, Telegram alerts.
Runs as background process via terminal(background=True).
"""
import os, sys, time, math, datetime, urllib.request, urllib.parse
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

def get_atr(symbol, mt5_inst):
    rates = mt5_inst.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 250)
    if rates is None or len(rates) < 15:
        return None
    trs = []
    for i in range(len(rates)):
        if i == 0:
            trs.append(float(rates[i][2]) - float(rates[i][3]))
        else:
            h, l, pc = float(rates[i][2]), float(rates[i][3]), float(rates[i-1][4])
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-14:]) / 14

def get_positions(sym, mt5_inst):
    all_pos = mt5_inst.positions_get()
    if not all_pos:
        return []
    return [p for p in all_pos if p.symbol == sym]

def run_cycle():
    terminal = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")
    if not mt5.initialize(terminal):
        send_tg("CYCLE: MT5 init FAILED")
        return

    ai = mt5.account_info()
    all_pos = mt5.positions_get() or []
    equity = ai.equity
    max_loss_usd = equity * 2.5 / 100.0
    now = datetime.datetime.now(datetime.timezone.utc)

    symbols = ["EURUSD", "GBPUSD", "USDCAD", "EURGBP", "NZDCAD", "EURAUD"]
    CONTRACT = 100000
    DIGITS = 5

    msg_parts = [f"CYCLE {now.strftime('%H:%M')} UTC | Eq={equity:.0f} | Pos={len(all_pos)}"]
    actions = []

    for sym in symbols:
        if not mt5.symbol_select(sym, True):
            continue
        tick = mt5.symbol_info_tick(sym)
        if not tick:
            continue
        atr_val = get_atr(sym, mt5)
        if not atr_val or atr_val > tick.bid * 0.05:
            continue

        positions = get_positions(sym, mt5)

        if positions:
            # --- EXISTING POSITION: check addon + DD ---
            entry = positions[0].price_open
            is_buy = positions[0].type == 0
            n_pos = len(positions)

            if is_buy:
                dist = (entry - tick.bid) / atr_val
            else:
                dist = (tick.ask - entry) / atr_val

            total_pnl = sum(p.profit for p in positions)
            pnl_pct = total_pnl / equity * 100

            # DD check
            if total_pnl <= -max_loss_usd:
                # Close all positions on this symbol
                info = mt5.symbol_info(sym)
                for p in positions:
                    if is_buy:
                        close_price = tick.bid
                        close_type = mt5.ORDER_TYPE_SELL
                    else:
                        close_price = tick.ask
                        close_type = mt5.ORDER_TYPE_BUY
                    filling = mt5.ORDER_FILLING_FOK
                    if info.filling_mode & 2:
                        filling = mt5.ORDER_FILLING_IOC
                    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym,
                           "position": p.ticket, "volume": p.volume, "type": close_type,
                           "price": close_price, "deviation": 50, "filling": filling}
                    mt5.order_send(req)
                actions.append(f"DD_STOP {sym}: closed {n_pos} positions, PnL={total_pnl:+.2f}")
                msg_parts.append(f"DD_STOP {sym} PnL={total_pnl:+.0f}")
                continue

            # Addon check
            if dist >= 1.0 and n_pos == 1:
                # Open addon 1 — same lot, SL relative to addon entry
                lot = positions[0].volume
                if is_buy:
                    addon_entry = tick.ask
                    sl = round(addon_entry - 2.5 * atr_val, DIGITS)
                    tp_temp = round(addon_entry + 0.5 * atr_val, DIGITS)
                    order_type = mt5.ORDER_TYPE_BUY
                    price = tick.ask
                else:
                    addon_entry = tick.bid
                    sl = round(addon_entry + 2.5 * atr_val, DIGITS)
                    tp_temp = round(addon_entry - 0.5 * atr_val, DIGITS)
                    order_type = mt5.ORDER_TYPE_SELL
                    price = tick.bid
                info = mt5.symbol_info(sym)
                filling = mt5.ORDER_FILLING_FOK
                if info.filling_mode & 2:
                    filling = mt5.ORDER_FILLING_IOC
                req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": lot,
                       "type": order_type, "price": price, "sl": sl, "tp": tp_temp,
                       "deviation": 50, "filling": filling, "comment": "addon1"}
                res = mt5.order_send(req)
                if res and res.retcode == 10009:
                    # Recalculate TP for all positions
                    all_sym_pos = get_positions(sym, mt5)
                    total_lot = sum(p.volume for p in all_sym_pos)
                    wavg = sum(p.price_open * p.volume for p in all_sym_pos) / total_lot
                    if is_buy:
                        new_tp = round(wavg + 0.5 * atr_val, DIGITS)
                    else:
                        new_tp = round(wavg - 0.5 * atr_val, DIGITS)
                    for p in all_sym_pos:
                        req2 = {"action": mt5.TRADE_ACTION_SLTP, "symbol": sym,
                                "position": p.ticket, "sl": p.sl, "tp": new_tp}
                        mt5.order_send(req2)
                    actions.append(f"ADDON1 {sym}: opened @ {price:.5f}, TP={new_tp:.5f}")
                    msg_parts.append(f"ADDON1 {sym} @ {price:.5f}")
                else:
                    actions.append(f"ADDON1 {sym} FAILED: {res.retcode if res else '?'}")

            elif dist >= 2.0 and n_pos == 2:
                # Open addon 2 — same lot, SL relative to addon entry
                lot = positions[0].volume
                if is_buy:
                    addon_entry = tick.ask
                    sl = round(addon_entry - 2.5 * atr_val, DIGITS)
                    tp_temp = round(addon_entry + 0.5 * atr_val, DIGITS)
                    order_type = mt5.ORDER_TYPE_BUY
                    price = tick.ask
                else:
                    addon_entry = tick.bid
                    sl = round(addon_entry + 2.5 * atr_val, DIGITS)
                    tp_temp = round(addon_entry - 0.5 * atr_val, DIGITS)
                    order_type = mt5.ORDER_TYPE_SELL
                    price = tick.bid
                info = mt5.symbol_info(sym)
                filling = mt5.ORDER_FILLING_FOK
                if info.filling_mode & 2:
                    filling = mt5.ORDER_FILLING_IOC
                req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": lot,
                       "type": order_type, "price": price, "sl": sl, "tp": tp_temp,
                       "deviation": 50, "filling": filling, "comment": "addon2"}
                res = mt5.order_send(req)
                if res and res.retcode == 10009:
                    all_sym_pos = get_positions(sym, mt5)
                    total_lot = sum(p.volume for p in all_sym_pos)
                    wavg = sum(p.price_open * p.volume for p in all_sym_pos) / total_lot
                    if is_buy:
                        new_tp = round(wavg + 0.5 * atr_val, DIGITS)
                    else:
                        new_tp = round(wavg - 0.5 * atr_val, DIGITS)
                    for p in all_sym_pos:
                        req2 = {"action": mt5.TRADE_ACTION_SLTP, "symbol": sym,
                                "position": p.ticket, "sl": p.sl, "tp": new_tp}
                        mt5.order_send(req2)
                    actions.append(f"ADDON2 {sym}: opened @ {price:.5f}, TP={new_tp:.5f}")
                    msg_parts.append(f"ADDON2 {sym} @ {price:.5f}")
                else:
                    actions.append(f"ADDON2 {sym} FAILED: {res.retcode if res else '?'}")

            else:
                msg_parts.append(f"{sym} {n_pos}pos dist={dist:+.2f}x PnL={total_pnl:+.0f}")

        else:
            # --- NO POSITION: check for new signal ---
            msg_parts.append(f"{sym}: no position")

    # Send Telegram if any actions
    if actions:
        msg = " | ".join(msg_parts) + "\n" + "\n".join(actions)
        send_tg(msg)

    mt5.shutdown()
    print(" | ".join(msg_parts))
    if actions:
        for a in actions:
            print(f"  ACTION: {a}")

# ── Main loop ────────────────────────────────────────────────────────
if __name__ == "__main__":
    load_env()
    print(f"Autonomous cycle runner started. Runs at :00 of each hour during trading window.")
    print(f"Press Ctrl+C to stop.")

    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Check if within trading hours (06:00-21:59 UTC, Mon-Fri)
        if not (6 <= now.hour <= 21 and now.weekday() < 5):
            print(f"[{now.strftime('%H:%M:%S')} UTC] Outside trading window, sleeping 5min...")
            time.sleep(300)
            continue
        
        # If we're in first 2 minutes of the hour (:00 or :01), run cycle
        if now.minute <= 1:
            try:
                run_cycle()
            except Exception as e:
                print(f"CYCLE ERROR: {e}")
                send_tg(f"CYCLE ERROR: {e}")
            # After cycle, sleep until next :00
            now_after = datetime.datetime.now(datetime.timezone.utc)
            # Next hour :00
            next_hour = now_after.hour + 1
            if next_hour > 23:
                next_run = now_after.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
            else:
                next_run = now_after.replace(hour=next_hour, minute=0, second=0, microsecond=0)
            wait = (next_run - now_after).total_seconds()
            print(f"[{now_after.strftime('%H:%M:%S')} UTC] Next cycle at {next_run.strftime('%H:%M')} UTC (in {wait/60:.0f} min)")
            time.sleep(max(wait, 60))
        else:
            # Not :00 yet — sleep until next :00
            next_hour = now.hour + 1 if now.hour < 23 else 0
            if next_hour == 0:
                next_run = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
            else:
                next_run = now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
            wait = (next_run - now).total_seconds()
            print(f"[{now.strftime('%H:%M:%S')} UTC] Waiting for {next_run.strftime('%H:%M')} UTC (in {wait/60:.0f} min)")
            time.sleep(max(wait, 1))