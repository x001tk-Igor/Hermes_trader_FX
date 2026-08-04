#!/usr/bin/env python3
"""
trade_sensor.py — событийный датчик для Hermes FX трейдера v4.

Архитектура (по образу ai-trader-skillset):
1. Датчик крутится фоном, опрашивает MT5 каждые 10 секунд.
2. Печатает в stdout ТОЛЬКО при срабатывании условия — это будит агент.
3. Пишет heartbeat в sensor_heartbeat.json — watchdog проверяет живость.
4. DD stop 2.5% — единственное действие датчика (закрытие позиций).
5. Алерты: цена пересекла уровень, addon готов, DD приближается, позиция закрылась.

Условия алертов задаются в alerts_config.json — агент переписывает их каждый цикл.
"""
import os, sys, json, time, datetime, urllib.request, urllib.parse
import MetaTrader5 as mt5

UTC = datetime.timezone.utc
HEARTBEAT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensor_heartbeat.json")
ALERTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alerts_config.json")
POLL_SECONDS = 10
STALE_THRESHOLD = 60  # heartbeat older than 60s = stale

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
    if not token or not chat: return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except: pass

def load_alerts():
    if not os.path.exists(ALERTS_FILE): return {"levels": [], "dd_warning_pct": 2.0}
    try:
        with open(ALERTS_FILE, "r") as f: return json.load(f)
    except: return {"levels": [], "dd_warning_pct": 2.0}

def write_heartbeat(tick, walls_checked, positions_count, equity, errors=None):
    hb = {
        "ts": datetime.datetime.now(UTC).isoformat(),
        "tick": tick,
        "pid": os.getpid(),
        "walls_checked": walls_checked,
        "positions": positions_count,
        "equity": equity,
        "errors": errors or [],
    }
    try:
        with open(HEARTBEAT_FILE, "w") as f: json.dump(hb, f)
    except: pass

def init_mt5():
    terminal = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")
    return mt5.initialize(terminal)

def get_positions_for_symbol(all_pos, sym):
    return [p for p in all_pos if p.symbol == sym]

def check_dd_stop(positions, equity, cfg):
    """DD stop 2.5% per symbol — close all if exceeded. Returns list of actions."""
    actions = []
    max_loss_pct = cfg.get("dd_stop_pct", 2.5)
    max_loss_usd = equity * max_loss_pct / 100.0
    symbols = set(p.symbol for p in positions)
    for sym in sorted(symbols):
        sym_positions = get_positions_for_symbol(positions, sym)
        total_pnl = sum(p.profit for p in sym_positions)
        if total_pnl <= -max_loss_usd:
            # Close all positions on this symbol
            tick = mt5.symbol_info_tick(sym)
            info = mt5.symbol_info(sym)
            filling = mt5.ORDER_FILLING_FOK
            if info.filling_mode & 2: filling = mt5.ORDER_FILLING_IOC
            for p in sym_positions:
                is_buy = p.type == 0
                price = tick.bid if is_buy else tick.ask
                otype = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
                req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": sym,
                       "position": p.ticket, "volume": p.volume, "type": otype,
                       "price": price, "deviation": 100, "filling": filling}
                mt5.order_send(req)
            actions.append(f"DD_STOP {sym}: closed {len(sym_positions)} pos, PnL={total_pnl:+.2f}")
    return actions

def check_price_levels(positions, equity, prev_prices, cfg):
    """Check price level alerts from alerts_config.json. Returns list of alert messages."""
    alerts = []
    levels = cfg.get("levels", [])
    if not levels: return alerts
    
    for lvl in levels:
        sym = lvl.get("symbol", "")
        price_target = lvl.get("price", 0)
        direction = lvl.get("direction", "above")  # above, below, touch
        name = lvl.get("name", "")
        action = lvl.get("action", "")
        expires_at = lvl.get("expires_at", "")
        
        if not sym or not price_target: continue
        if expires_at:
            try:
                exp = datetime.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if datetime.datetime.now(UTC) > exp: continue
            except: pass
        
        tick = mt5.symbol_info_tick(sym)
        if not tick: continue
        current = tick.bid
        
        prev = prev_prices.get(sym)
        if prev is None:
            prev_prices[sym] = current
            continue
        
        triggered = False
        if direction == "above" and prev < price_target <= current:
            triggered = True
        elif direction == "below" and prev > price_target >= current:
            triggered = True
        elif direction == "touch" and abs(current - price_target) < 0.0001:
            triggered = True
        
        if triggered:
            msg = f"ALERT {sym} {direction} {price_target:.5f} ({name})"
            if action: msg += f" → {action}"
            alerts.append(msg)
            lvl["_triggered"] = True
    
    # Update prev prices
    for sym in set(l.get("symbol", "") for l in levels):
        tick = mt5.symbol_info_tick(sym)
        if tick: prev_prices[sym] = tick.bid
    
    return alerts

def check_addon_ready(positions, equity, prev_addon_checked):
    """Check if any symbol is at addon distance (-1×ATR or -2×ATR)."""
    alerts = []
    symbols = set(p.symbol for p in positions)
    for sym in sorted(symbols):
        sym_positions = get_positions_for_symbol(positions, sym)
        if not sym_positions: continue
        n_pos = len(sym_positions)
        if n_pos >= 3: continue  # max positions reached
        
        # Calculate distance from first entry
        entry = sym_positions[0].price_open
        direction = 1 if sym_positions[0].type == 0 else -1  # buy=1, sell=-1
        tick = mt5.symbol_info_tick(sym)
        if not tick: continue
        current = tick.bid if direction == 1 else tick.ask
        
        # Get ATR
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 250)
        if rates is None or len(rates) < 14: continue
        trs = []
        for i in range(len(rates)):
            if i == 0: trs.append(float(rates[i][2]) - float(rates[i][3]))
            else:
                h, l, pc = float(rates[i][2]), float(rates[i][3]), float(rates[i-1][4])
                trs.append(max(h-l, abs(h-pc), abs(l-pc)))
        atr_val = sum(trs[-14:]) / 14
        
        if direction == 1:  # buy
            dist_atr = (entry - current) / atr_val if atr_val > 0 else 0
        else:  # sell
            dist_atr = (current - entry) / atr_val if atr_val > 0 else 0
        
        # Check addon levels
        if n_pos == 1 and dist_atr >= 1.0:
            key = f"{sym}_addon1"
            if prev_addon_checked.get(key) is None:
                alerts.append(f"ADDON1_READY {sym}: dist={dist_atr:.2f}×ATR, entry={entry:.5f}, current={current:.5f}")
                prev_addon_checked[key] = True
        elif n_pos == 2 and dist_atr >= 2.0:
            key = f"{sym}_addon2"
            if prev_addon_checked.get(key) is None:
                alerts.append(f"ADDON2_READY {sym}: dist={dist_atr:.2f}×ATR, entry={entry:.5f}, current={current:.5f}")
                prev_addon_checked[key] = True
        else:
            # Reset when distance drops below threshold
            if n_pos == 1 and dist_atr < 0.8:
                prev_addon_checked.pop(f"{sym}_addon1", None)
            if n_pos == 2 and dist_atr < 1.8:
                prev_addon_checked.pop(f"{sym}_addon2", None)
    
    return alerts

def check_positions_closed(prev_count, current_count, prev_tickets, current_tickets):
    """Detect TP/SL hits — positions that disappeared."""
    alerts = []
    closed = prev_tickets - current_tickets
    if closed:
        for ticket in closed:
            alerts.append(f"POSITION_CLOSED ticket={ticket} (TP/SL hit)")
    return alerts

def main():
    load_env()
    
    if not init_mt5():
        print("FATAL: MT5 init failed", flush=True)
        sys.exit(1)
    
    print(f"Trade sensor started. Poll every {POLL_SECONDS}s. Heartbeat: {HEARTBEAT_FILE}", flush=True)
    print(f"Alerts config: {ALERTS_FILE}", flush=True)
    
    tick = 0
    prev_prices = {}
    prev_addon_checked = {}
    prev_tickets = set()
    prev_position_count = 0
    
    while True:
        tick += 1
        now = datetime.datetime.now(UTC)
        errors = []
        
        # Trading hours check
        if not (5 <= now.hour <= 19 and now.weekday() < 5):
            write_heartbeat(tick, False, 0, 0, ["outside trading window"])
            time.sleep(POLL_SECONDS * 6)  # check less often outside window
            continue
        
        try:
            ai = mt5.account_info()
            if not ai:
                write_heartbeat(tick, False, 0, 0, ["no account info"])
                time.sleep(POLL_SECONDS)
                continue
            
            all_pos = mt5.positions_get() or []
            equity = ai.equity
            cfg = load_alerts()
            
            # 1. DD stop check (walls_checked = True means we successfully checked walls)
            dd_actions = check_dd_stop(all_pos, equity, cfg)
            for a in dd_actions:
                print(f"[{now:%H:%M:%S}] {a}", flush=True)
                send_tg(f"DD STOP: {a}")
            
            # 2. Price level alerts
            price_alerts = check_price_levels(all_pos, equity, prev_prices, cfg)
            for a in price_alerts:
                print(f"[{now:%H:%M:%S}] {a}", flush=True)
                send_tg(a)
            
            # 3. Addon ready alerts
            addon_alerts = check_addon_ready(all_pos, equity, prev_addon_checked)
            for a in addon_alerts:
                print(f"[{now:%H:%M:%S}] {a}", flush=True)
                send_tg(a)
            
            # 4. Position closed detection
            current_tickets = set(p.ticket for p in all_pos)
            close_alerts = check_positions_closed(prev_position_count, len(all_pos), prev_tickets, current_tickets)
            for a in close_alerts:
                print(f"[{now:%H:%M:%S}] {a}", flush=True)
                send_tg(a)
            
            prev_tickets = current_tickets
            prev_position_count = len(all_pos)
            
            # 5. Heartbeat
            write_heartbeat(tick, True, len(all_pos), equity, errors)
            
        except Exception as e:
            errors.append(str(e))
            write_heartbeat(tick, False, 0, 0, errors)
            print(f"[{now:%H:%M:%S}] ERROR: {e}", flush=True)
        
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()