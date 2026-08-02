#!/usr/bin/env python3
"""
Backtest engine for 10 trading tactics (5 trend + 5 counter-trend).
Loads H1 data from MT5, computes indicators, runs tactics, reports PF/winrate/EV.

Usage:
  py -3 backtest_tactics.py              # all tactics, all pairs, 1 year
  py -3 backtest_tactics.py --pairs XAUUSD,EURUSD --days 365
  py -3 backtest_tactics.py --tactics T1,T2,C1 --pairs XAUUSD
"""
import os, sys, json, argparse, datetime, math
from collections import defaultdict

# ── MT5 data loader ──────────────────────────────────────────────────────
def load_env():
    p = os.path.expanduser("~/.claude/skills/xau-ai-trader/.env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k] = v

def fetch_h1(symbol, bars):
    import MetaTrader5 as mt5
    terminal = os.environ.get("MT5_TERMINAL_PATH", r"C:\Program Files\RoboForex MT5 Terminal\terminal64.exe")
    if not mt5.initialize(terminal):
        print(f"MT5 init failed: {mt5.last_error()}")
        sys.exit(1)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, bars)
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        print(f"No data for {symbol}")
        sys.exit(1)
    # Convert to list of dicts
    candles = []
    for r in rates:
        candles.append({
            "time": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "tickvol": float(r[5]),
            "spread": float(r[6]),
        })
    return candles

# ── Indicators ──────────────────────────────────────────────────────────
def sma(values, period):
    out = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i - period + 1 : i + 1]) / period
    return out

def ema(values, period):
    out = [None] * len(values)
    k = 2 / (period + 1)
    for i in range(len(values)):
        if i == period - 1:
            out[i] = sum(values[:period]) / period
        elif i >= period:
            out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out

def atr(candles, period=14):
    """ATR(14) — average true range."""
    trs = []
    for i in range(len(candles)):
        if i == 0:
            trs.append(candles[i]["high"] - candles[i]["low"])
        else:
            h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
    return sma(trs, period)

def rsi(closes, period=14):
    out = [None] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(0, ch))
        losses.append(max(0, -ch))
    # Wilder's smoothing
    for i in range(period, len(closes)):
        if i == period:
            avg_g = sum(gains[:period]) / period
            avg_l = sum(losses[:period]) / period
        else:
            avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
            avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        if avg_l == 0:
            out[i] = 100.0
        else:
            rs = avg_g / avg_l
            out[i] = 100 - 100 / (1 + rs)
    return out

def adx(candles, period=14):
    """ADX(14) — trend strength."""
    n = len(candles)
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, n):
        up = candles[i]["high"] - candles[i - 1]["high"]
        down = candles[i - 1]["low"] - candles[i]["low"]
        if up > down and up > 0:
            plus_dm.append(up)
        else:
            plus_dm.append(0)
        if down > up and down > 0:
            minus_dm.append(down)
        else:
            minus_dm.append(0)
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))

    atr_s = [None] * n
    plus_s = [None] * n
    minus_s = [None] * n
    adx_s = [None] * n

    # Wilder smoothing
    for i in range(period, n):
        if i == period:
            atr_s[i] = sum(tr[:period])
            plus_s[i] = sum(plus_dm[:period])
            minus_s[i] = sum(minus_dm[:period])
        else:
            atr_s[i] = atr_s[i-1] - atr_s[i-1]/period + tr[i-1]
            plus_s[i] = plus_s[i-1] - plus_s[i-1]/period + plus_dm[i-1]
            minus_s[i] = minus_s[i-1] - minus_s[i-1]/period + minus_dm[i-1]

    dx = [None] * n
    for i in range(period, n):
        if atr_s[i] and atr_s[i] > 0:
            pdi = 100 * plus_s[i] / atr_s[i]
            mdi = 100 * minus_s[i] / atr_s[i]
            if pdi + mdi > 0:
                dx[i] = 100 * abs(pdi - mdi) / (pdi + mdi)

    # ADX = smoothed DX
    for i in range(period * 2, n):
        if i == period * 2:
            vals = [dx[j] for j in range(period, period * 2) if dx[j] is not None]
            if vals:
                adx_s[i] = sum(vals) / len(vals)
        else:
            if adx_s[i-1] and dx[i-1]:
                adx_s[i] = (adx_s[i-1] * (period - 1) + dx[i-1]) / period
    return adx_s

def bollinger_bands(closes, period=20, std_mult=2.0):
    n = len(closes)
    upper = [None] * n
    lower = [None] * n
    mid = sma(closes, period)
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        m = mid[i]
        var = sum((x - m) ** 2 for x in window) / period
        sd = math.sqrt(var)
        upper[i] = m + std_mult * sd
        lower[i] = m - std_mult * sd
    return upper, mid, lower

def donchian(candles, period=20):
    n = len(candles)
    dh = [None] * n
    dl = [None] * n
    for i in range(period - 1, n):
        window = candles[i - period + 1 : i + 1]
        dh[i] = max(c["high"] for c in window)
        dl[i] = min(c["low"] for c in window)
    return dh, dl

def vwap(candles, start_idx, end_idx):
    """Session VWAP from start_idx to end_idx."""
    pv = 0
    vol = 0
    for i in range(start_idx, end_idx + 1):
        tp = (candles[i]["high"] + candles[i]["low"] + candles[i]["close"]) / 3
        pv += tp * candles[i]["tickvol"]
        vol += candles[i]["tickvol"]
    return pv / vol if vol > 0 else candles[end_idx]["close"]

def sma_range(candles, period, idx):
    """Average range over last `period` bars ending at idx."""
    if idx < period:
        return None
    ranges = [candles[i]["high"] - candles[i]["low"] for i in range(idx - period, idx)]
    return sum(ranges) / period

def sma_volume(candles, period, idx):
    if idx < period:
        return None
    vols = [candles[i]["tickvol"] for i in range(idx - period, idx)]
    return sum(vols) / period

# ── Spread cost ────────────────────────────────────────────────────────
def spread_cost(candles, idx, symbol):
    """Return spread in price units at bar idx."""
    return candles[idx]["spread"]

# ── Trade result ───────────────────────────────────────────────────────
def check_trade(entry, sl, tp, candles, idx, direction, max_bars=48):
    """
    Simulate trade from bar idx+1 forward.
    Returns (result, exit_idx, pnl_price)
    result: 'win' (TP hit), 'loss' (SL hit), 'timeout' (neither in max_bars)
    pnl_price: positive for win, negative for loss (in price units, before spread)
    """
    for j in range(idx + 1, min(idx + 1 + max_bars, len(candles))):
        c = candles[j]
        if direction == 1:  # long: SL below entry, TP above
            # Check both in same bar — conservative: SL first if both hit
            if c["low"] <= sl:
                return "loss", j, sl - entry
            if c["high"] >= tp:
                return "win", j, tp - entry
        else:  # short: SL above entry, TP below
            if c["high"] >= sl:
                return "loss", j, entry - sl
            if c["low"] <= tp:
                return "win", j, entry - tp
    # Timeout: exit at close of last bar
    exit_price = candles[min(idx + max_bars, len(candles) - 1)]["close"]
    if direction == 1:
        return "timeout", min(idx + max_bars, len(candles) - 1), exit_price - entry
    else:
        return "timeout", min(idx + max_bars, len(candles) - 1), entry - exit_price

# ── TACTICS ────────────────────────────────────────────────────────────
# Each tactic function: takes candles + precomputed indicators at bar idx
# Returns (direction, entry, sl, tp, tactic_name) or None

def tactic_T1_atr_trailing(candles, idx, ind):
    """T1: ATR Trailing Trend (UT Bot concept). ATR trail flip + ADX>20."""
    atr_val = ind["atr"][idx]
    adx_val = ind["adx"][idx]
    ema20 = ind["ema20"][idx]
    ema200 = ind["ema200"][idx]
    if not all([atr_val, adx_val, ema20, ema200]):
        return None
    if adx_val < 20:
        return None
    # ATR trailing: trail = close - n*ATR (for long), close + n*ATR (for short)
    # Simplified: if close > prev_close - 1.5*ATR and trend up (ema20>ema200) → long
    # If close < prev_close + 1.5*ATR and trend down (ema20<ema200) → short
    prev_close = candles[idx - 1]["close"] if idx > 0 else None
    if not prev_close:
        return None
    close = candles[idx]["close"]
    trail_long = prev_close - 1.5 * atr_val
    trail_short = prev_close + 1.5 * atr_val
    if close > trail_long and ema20 > ema200:
        direction = 1
        entry = close
        sl = entry - 1.5 * atr_val
        tp = entry + 2.0 * atr_val
        return direction, entry, sl, tp, "T1_ATR_Trail"
    elif close < trail_short and ema20 < ema200:
        direction = -1
        entry = close
        sl = entry + 1.5 * atr_val
        tp = entry - 2.0 * atr_val
        return direction, entry, sl, tp, "T1_ATR_Trail"
    return None

def tactic_T2_orb(candles, idx, ind):
    """T2: Opening Range Breakout. London open 07:00 UTC."""
    atr_val = ind["atr"][idx]
    if not atr_val:
        return None
    # Check if current bar is in London open window (07:00-10:00 UTC)
    dt = datetime.datetime.utcfromtimestamp(candles[idx]["time"])
    if not (7 <= dt.hour <= 10):
        return None
    # Build Asian range from 00:00-07:00 UTC of same day
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_ts = int(day_start.timestamp())
    asian_high = -float("inf")
    asian_low = float("inf")
    for j in range(idx, -1, -1):
        if candles[j]["time"] < day_start_ts:
            break
        asian_high = max(asian_high, candles[j]["high"])
        asian_low = min(asian_low, candles[j]["low"])
    asian_range = asian_high - asian_low
    if asian_range <= 0:
        return None
    # Filter: range > 0.3*ATR and < 1.5*ATR
    if asian_range < 0.3 * atr_val or asian_range > 1.5 * atr_val:
        return None
    # Volume filter
    vol_avg = sma_volume(candles, 20, idx)
    if not vol_avg or candles[idx]["tickvol"] < vol_avg:
        return None
    close = candles[idx]["close"]
    if close > asian_high:
        direction = 1
        entry = close
        sl = min(asian_low, entry - 1.2 * atr_val)
        tp = entry + 1.5 * atr_val
        return direction, entry, sl, tp, "T2_ORB"
    elif close < asian_low:
        direction = -1
        entry = close
        sl = max(asian_high, entry + 1.2 * atr_val)
        tp = entry - 1.5 * atr_val
        return direction, entry, sl, tp, "T2_ORB"
    return None

def tactic_T3_ema_pullback(candles, idx, ind):
    """T3: EMA Pullback Continuation. EMA20>EMA200, pullback to EMA20, M15 close above."""
    # We're on H1 — check EMA20 > EMA200 (trend up) and price pulled back to EMA20
    ema20 = ind["ema20"][idx]
    ema200 = ind["ema200"][idx]
    adx_val = ind["adx"][idx]
    atr_val = ind["atr"][idx]
    if not all([ema20, ema200, adx_val, atr_val]):
        return None
    if adx_val < 20:
        return None
    close = candles[idx]["close"]
    # EMA200 slope up: compare to 5 bars ago
    ema200_prev = ind["ema200"][idx - 5] if idx >= 5 else None
    if not ema200_prev:
        return None
    # Trend up: EMA20 > EMA200, EMA200 rising
    if ema20 > ema200 and ema200 > ema200_prev:
        # Pullback: low of this bar touched EMA20 ± 0.2*ATR
        pullback_zone_low = ema20 - 0.3 * atr_val
        pullback_zone_high = ema20 + 0.3 * atr_val
        if candles[idx]["low"] <= pullback_zone_high and close > ema20:
            direction = 1
            entry = close
            sl = min(candles[idx]["low"] - 0.1 * atr_val, entry - 1.2 * atr_val)
            tp = entry + 1.5 * atr_val
            return direction, entry, sl, tp, "T3_EMA_Pullback"
    # Trend down: EMA20 < EMA200, EMA200 falling
    if ema20 < ema200 and ema200 < ema200_prev:
        pullback_zone_low = ema20 - 0.3 * atr_val
        pullback_zone_high = ema20 + 0.3 * atr_val
        if candles[idx]["high"] >= pullback_zone_low and close < ema20:
            direction = -1
            entry = close
            sl = max(candles[idx]["high"] + 0.1 * atr_val, entry + 1.2 * atr_val)
            tp = entry - 1.5 * atr_val
            return direction, entry, sl, tp, "T3_EMA_Pullback"
    return None

def tactic_T4_ema_vwap(candles, idx, ind):
    """T4: EMA9 + VWAP Cross. EMA9 crosses VWAP, ATR trail exit."""
    ema9 = ind["ema9"][idx]
    ema9_prev = ind["ema9"][idx - 1] if idx > 0 else None
    atr_val = ind["atr"][idx]
    if not all([ema9, ema9_prev, atr_val]):
        return None
    # Compute session VWAP (from 00:00 UTC of current day to current bar)
    dt = datetime.datetime.utcfromtimestamp(candles[idx]["time"])
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_ts = int(day_start.timestamp())
    vwap_start = idx
    for j in range(idx, -1, -1):
        if candles[j]["time"] < day_start_ts:
            vwap_start = j + 1
            break
    if vwap_start >= idx:
        return None
    v = vwap(candles, vwap_start, idx)
    v_prev = vwap(candles, vwap_start, max(idx - 1, vwap_start))
    # Cross: ema9 crosses above vwap
    if ema9_prev <= v_prev and ema9 > v:
        direction = 1
        entry = candles[idx]["close"]
        sl = entry - 1.0 * atr_val
        tp = entry + 1.5 * atr_val
        return direction, entry, sl, tp, "T4_EMA_VWAP"
    elif ema9_prev >= v_prev and ema9 < v:
        direction = -1
        entry = candles[idx]["close"]
        sl = entry + 1.0 * atr_val
        tp = entry - 1.5 * atr_val
        return direction, entry, sl, tp, "T4_EMA_VWAP"
    return None

def tactic_T5_post_news(candles, idx, ind):
    """T5: Post-News Momentum. Pre-news range breakout after cooldown.
    Simplified for backtest: check if bar is 30-90 min after a known news hour.
    We use 12:30, 13:30, 14:00 UTC as typical US news times."""
    atr_val = ind["atr"][idx]
    if not atr_val:
        return None
    dt = datetime.datetime.utcfromtimestamp(candles[idx]["time"])
    # Check if we're 30-90 min after a typical news release
    news_hours = [12, 13, 14]  # 12:30, 13:30, 14:00 UTC approximate
    news_offset = None
    for nh in news_hours:
        if dt.hour == nh and dt.minute >= 30:
            news_offset = (dt.hour - nh) * 60 + dt.minute
        elif dt.hour == nh + 1 and dt.minute < 30:
            news_offset = 60 + dt.minute
    if news_offset is None or news_offset < 30 or news_offset > 90:
        return None
    # Pre-news range: 30 min (2 H1 bars) before the news hour
    # Find the news bar index
    news_bar_idx = idx - max(0, int(news_offset / 60))
    if news_bar_idx < 3:
        return None
    pre_high = max(candles[news_bar_idx - 2]["high"], candles[news_bar_idx - 1]["high"])
    pre_low = min(candles[news_bar_idx - 2]["low"], candles[news_bar_idx - 1]["low"])
    close = candles[idx]["close"]
    if close > pre_high:
        direction = 1
        entry = close
        sl = pre_low
        tp = entry + 1.5 * atr_val
        return direction, entry, sl, tp, "T5_PostNews"
    elif close < pre_low:
        direction = -1
        entry = close
        sl = pre_high
        tp = entry - 1.5 * atr_val
        return direction, entry, sl, tp, "T5_PostNews"
    return None

def tactic_C1_liquidity_sweep(candles, idx, ind):
    """C1: Liquidity Sweep + 3-Candle Confirmation. Sweep PDH/PDL, 3 candles back inside."""
    atr_val = ind["atr"][idx]
    if not atr_val:
        return None
    dt = datetime.datetime.utcfromtimestamp(candles[idx]["time"])
    # Session filter: London or NY open
    if not ((7 <= dt.hour <= 10) or (12 <= dt.hour <= 15)):
        return None
    # Previous day high/low
    prev_day = dt - datetime.timedelta(days=1)
    prev_day_start = prev_day.replace(hour=0, minute=0, second=0, microsecond=0)
    prev_day_end = prev_day.replace(hour=23, minute=59, second=59)
    prev_start_ts = int(prev_day_start.timestamp())
    prev_end_ts = int(prev_day_end.timestamp())
    pdh = -float("inf")
    pdl = float("inf")
    for j in range(idx, -1, -1):
        if candles[j]["time"] < prev_start_ts:
            break
        if prev_start_ts <= candles[j]["time"] <= prev_end_ts:
            pdh = max(pdh, candles[j]["high"])
            pdl = min(pdl, candles[j]["low"])
    if pdh == -float("inf"):
        return None
    # Check: 3 bars ago, did we sweep PDH? Then 3 candles closed back below?
    if idx < 3:
        return None
    sweep_bar = candles[idx - 3]
    if sweep_bar["high"] > pdh:
        # 3 candles after sweep all closed below PDH
        if all(candles[j]["close"] < pdh for j in range(idx - 2, idx + 1)):
            direction = -1
            entry = candles[idx]["close"]
            sl = sweep_bar["high"] + 0.3 * atr_val
            tp = entry - 1.0 * atr_val
            if tp < entry:
                return direction, entry, sl, tp, "C1_LiquiditySweep"
    if sweep_bar["low"] < pdl:
        if all(candles[j]["close"] > pdl for j in range(idx - 2, idx + 1)):
            direction = 1
            entry = candles[idx]["close"]
            sl = sweep_bar["low"] - 0.3 * atr_val
            tp = entry + 1.0 * atr_val
            if tp > entry:
                return direction, entry, sl, tp, "C1_LiquiditySweep"
    return None

def tactic_C2_rsi_bb(candles, idx, ind):
    """C2: RSI + Bollinger Band Reversion. BB+RSI double confirm + ADX<20."""
    rsi_val = ind["rsi"][idx]
    bb_upper = ind["bb_upper"][idx]
    bb_lower = ind["bb_lower"][idx]
    bb_mid = ind["bb_mid"][idx]
    adx_val = ind["adx"][idx]
    atr_val = ind["atr"][idx]
    if not all([rsi_val, bb_upper, bb_lower, bb_mid, adx_val, atr_val]):
        return None
    if adx_val >= 20:
        return None
    close = candles[idx]["close"]
    # Long: close below lower BB AND RSI < 30
    if close < bb_lower and rsi_val < 30:
        direction = 1
        entry = close
        sl = entry - 1.0 * atr_val
        tp = bb_mid
        if tp > entry:
            return direction, entry, sl, tp, "C2_RSI_BB"
    # Short: close above upper BB AND RSI > 70
    if close > bb_upper and rsi_val > 70:
        direction = -1
        entry = close
        sl = entry + 1.0 * atr_val
        tp = bb_mid
        if tp < entry:
            return direction, entry, sl, tp, "C2_RSI_BB"
    return None

def tactic_C3_volume_spike(candles, idx, ind):
    """C3: Volume Spike Fade. 3x volume + 3x range → fade."""
    atr_val = ind["atr"][idx]
    if not atr_val or idx < 20:
        return None
    dt = datetime.datetime.utcfromtimestamp(candles[idx]["time"])
    if not (7 <= dt.hour <= 20):
        return None
    vol_avg = sma_volume(candles, 20, idx)
    range_avg = sma_range(candles, 20, idx)
    if not vol_avg or not range_avg:
        return None
    bar_vol = candles[idx]["tickvol"]
    bar_range = candles[idx]["high"] - candles[idx]["low"]
    if bar_vol < 3 * vol_avg or bar_range < 3 * range_avg:
        return None
    # Check no cluster in last 5 bars
    for j in range(max(0, idx - 5), idx):
        if candles[j]["tickvol"] > 2 * vol_avg:
            return None
    # Fade: if bar is bullish (close > open) → short, if bearish → long
    close = candles[idx]["close"]
    open_ = candles[idx]["open"]
    if close > open_:
        direction = -1
        entry = close
        sl = candles[idx]["high"] + 0.3 * atr_val
        tp = entry - 1.0 * atr_val
        if tp < entry:
            return direction, entry, sl, tp, "C3_VolSpikeFade"
    else:
        direction = 1
        entry = close
        sl = candles[idx]["low"] - 0.3 * atr_val
        tp = entry + 1.0 * atr_val
        if tp > entry:
            return direction, entry, sl, tp, "C3_VolSpikeFade"
    return None

def tactic_C4_vwap_absorption(candles, idx, ind):
    """C4: VWAP Absorption Reversal. High volume + low body → fade to VWAP."""
    atr_val = ind["atr"][idx]
    if not atr_val or idx < 20:
        return None
    dt = datetime.datetime.utcfromtimestamp(candles[idx]["time"])
    if not (7 <= dt.hour <= 20):
        return None
    vol_avg = sma_volume(candles, 20, idx)
    if not vol_avg:
        return None
    bar_vol = candles[idx]["tickvol"]
    # Volume in top 90th percentile (simplified: > 2x average)
    if bar_vol < 2 * vol_avg:
        return None
    # Body / ATR < 0.30 (small body relative to ATR)
    body = abs(candles[idx]["close"] - candles[idx]["open"])
    if not atr_val or body / atr_val >= 0.30:
        return None
    # VWAP for session
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_ts = int(day_start.timestamp())
    vwap_start = idx
    for j in range(idx, -1, -1):
        if candles[j]["time"] < day_start_ts:
            vwap_start = j + 1
            break
    if vwap_start >= idx:
        return None
    v = vwap(candles, vwap_start, idx)
    close = candles[idx]["close"]
    # If bar below VWAP → long (fade up to VWAP)
    if close < v:
        direction = 1
        entry = close
        sl = entry - 1.0 * atr_val
        tp = v
        if tp > entry:
            return direction, entry, sl, tp, "C4_VWAP_Absorption"
    elif close > v:
        direction = -1
        entry = close
        sl = entry + 1.0 * atr_val
        tp = v
        if tp < entry:
            return direction, entry, sl, tp, "C4_VWAP_Absorption"
    return None

def tactic_C5_htf_divergence(candles, idx, ind):
    """C5: HTF Divergence Revert. Price diverged 2xATR from EMA200 → revert."""
    atr_val = ind["atr"][idx]
    ema200 = ind["ema200"][idx]
    rsi_val = ind["rsi"][idx]
    if not all([atr_val, ema200, rsi_val]):
        return None
    close = candles[idx]["close"]
    divergence = abs(close - ema200)
    if divergence < 2 * atr_val:
        return None
    # RSI confirms: < 30 for long (oversold), > 70 for short (overbought)
    if close < ema200 and rsi_val < 30:
        direction = 1
        entry = close
        sl = entry - 1.0 * atr_val
        tp = ema200
        if tp > entry:
            return direction, entry, sl, tp, "C5_HTF_Divergence"
    elif close > ema200 and rsi_val > 70:
        direction = -1
        entry = close
        sl = entry + 1.0 * atr_val
        tp = ema200
        if tp < entry:
            return direction, entry, sl, tp, "C5_HTF_Divergence"
    return None

# ── Tactic registry ───────────────────────────────────────────────────
TREND_TACTICS = {
    "T1": tactic_T1_atr_trailing,
    "T2": tactic_T2_orb,
    "T3": tactic_T3_ema_pullback,
    "T4": tactic_T4_ema_vwap,
    "T5": tactic_T5_post_news,
}
COUNTER_TACTICS = {
    "C1": tactic_C1_liquidity_sweep,
    "C2": tactic_C2_rsi_bb,
    "C3": tactic_C3_volume_spike,
    "C4": tactic_C4_vwap_absorption,
    "C5": tactic_C5_htf_divergence,
}
ALL_TACTICS = {**TREND_TACTICS, **COUNTER_TACTICS}

# Instrument → regime mapping
INSTRUMENT_REGIMES = {
    "XAUUSD": "TREND",
    "USDJPY": "TREND",
    "USDCAD": "TREND",
    "GBPJPY": "TREND",
    "EURUSD": "COUNTER",
}

# Instrument → digits (for spread conversion: price = points * 10^-digits)
INSTRUMENT_DIGITS = {
    "XAUUSD": 2,
    "USDJPY": 3,
    "USDCAD": 5,
    "GBPJPY": 3,
    "EURUSD": 5,
}

# ── Precompute indicators ─────────────────────────────────────────────
def compute_indicators(candles):
    closes = [c["close"] for c in candles]
    return {
        "atr": atr(candles, 14),
        "adx": adx(candles, 14),
        "rsi": rsi(closes, 14),
        "ema9": ema(closes, 9),
        "ema20": ema(closes, 20),
        "ema200": ema(closes, 200),
        "bb_upper": bollinger_bands(closes, 20, 2.0)[0],
        "bb_mid": bollinger_bands(closes, 20, 2.0)[1],
        "bb_lower": bollinger_bands(closes, 20, 2.0)[2],
        "donchian_h": donchian(candles, 20)[0],
        "donchian_l": donchian(candles, 20)[1],
    }

# ── Backtest engine ──────────────────────────────────────────────────
def run_backtest(symbol, candles, tactics_to_run, regime):
    ind = compute_indicators(candles)
    results = []
    # Max 1 position at a time, no re-entry for N bars after exit
    cooldown = 0
    for idx in range(210, len(candles) - 50):  # need 200 bars for EMA200 + buffer
        if cooldown > 0:
            cooldown -= 1
            continue
        # Select tactics based on regime
        if regime == "TREND":
            pool = {k: TREND_TACTICS[k] for k in tactics_to_run if k in TREND_TACTICS}
        else:
            pool = {k: COUNTER_TACTICS[k] for k in tactics_to_run if k in COUNTER_TACTICS}
        # Also allow counter tactics on trend instruments if specified
        if regime == "TREND" and any(k in COUNTER_TACTICS for k in tactics_to_run):
            for k in tactics_to_run:
                if k in COUNTER_TACTICS:
                    pool[k] = COUNTER_TACTICS[k]
        if regime == "COUNTER" and any(k in TREND_TACTICS for k in tactics_to_run):
            for k in tactics_to_run:
                if k in TREND_TACTICS:
                    pool[k] = TREND_TACTICS[k]
        # Try each tactic, take first signal
        for tname, tfunc in pool.items():
            signal = tfunc(candles, idx, ind)
            if signal:
                direction, entry, sl, tp, tactic_label = signal
                # Add spread cost to entry
                spread_points = candles[idx]["spread"]
                digits = INSTRUMENT_DIGITS.get(symbol, 5)
                spread_price = spread_points * (10 ** -digits)
                if direction == 1:
                    entry_adj = entry + spread_price / 2
                else:
                    entry_adj = entry - spread_price / 2
                # Adjust SL/TP relative to adjusted entry
                if direction == 1:
                    sl_adj = sl  # SL stays at original level
                    tp_adj = tp
                else:
                    sl_adj = sl
                    tp_adj = tp
                result, exit_idx, pnl_price = check_trade(
                    entry_adj, sl_adj, tp_adj, candles, idx, direction, max_bars=48
                )
                # Spread cost
                if direction == 1:
                    net_pnl = pnl_price - spread_price
                else:
                    net_pnl = pnl_price - spread_price
                results.append({
                    "symbol": symbol,
                    "tactic": tactic_label,
                    "direction": "long" if direction == 1 else "short",
                    "bar_idx": idx,
                    "time": candles[idx]["time"],
                    "result": result,
                    "pnl_price": net_pnl,
                    "entry": entry_adj,
                    "sl": sl_adj,
                    "tp": tp_adj,
                    "atr": ind["atr"][idx],
                    "spread": spread_price,
                })
                cooldown = 2  # 2 bars cooldown after any trade
                break  # only 1 trade per bar
    return results

# ── Reporting ─────────────────────────────────────────────────────────
def report(results, symbol, tactic_filter=None):
    """Print results grouped by tactic."""
    print(f"\n{'='*70}")
    print(f"  {symbol}")
    print(f"{'='*70}")
    if not results:
        print("  No trades.")
        return
    by_tactic = defaultdict(list)
    for r in results:
        by_tactic[r["tactic"]].append(r)

    total_trades = 0
    total_wins = 0
    total_pnl = 0.0
    total_win_pnl = 0.0
    total_loss_pnl = 0.0

    for tname in sorted(by_tactic.keys()):
        trades = by_tactic[tname]
        if tactic_filter and tname not in tactic_filter:
            continue
        wins = [t for t in trades if t["result"] == "win"]
        losses = [t for t in trades if t["result"] == "loss"]
        timeouts = [t for t in trades if t["result"] == "timeout"]
        n = len(trades)
        nw = len(wins)
        nl = len(losses)
        nt = len(timeouts)
        pnl = sum(t["pnl_price"] for t in trades)
        win_pnl = sum(t["pnl_price"] for t in wins)
        loss_pnl = sum(t["pnl_price"] for t in losses)
        gross_profit = win_pnl if win_pnl > 0 else 0
        gross_loss = abs(loss_pnl) if loss_pnl < 0 else 0
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0
        wr = nw / n * 100 if n > 0 else 0
        avg_win = win_pnl / nw if nw > 0 else 0
        avg_loss = loss_pnl / nl if nl > 0 else 0
        avg_pnl = pnl / n if n > 0 else 0
        print(f"  {tname:25s} | trades={n:4d} | W={nw:3d} L={nl:3d} TO={nt:3d} | "
              f"WR={wr:5.1f}% | PF={pf:5.2f} | avgR={avg_pnl:+.4f} | "
              f"avgWin={avg_win:+.4f} avgLoss={avg_loss:+.4f}")
        total_trades += n
        total_wins += nw
        total_pnl += pnl
        total_win_pnl += win_pnl
        total_loss_pnl += loss_pnl

    gp = total_win_pnl if total_win_pnl > 0 else 0
    gl = abs(total_loss_pnl) if total_loss_pnl < 0 else 0
    total_pf = gp / gl if gl > 0 else float("inf") if gp > 0 else 0
    total_wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print(f"  {'TOTAL':25s} | trades={total_trades:4d} | W={total_wins:3d} "
          f"     | WR={total_wr:5.1f}% | PF={total_pf:5.2f} | "
          f"pnl={total_pnl:+.4f}")
    return {
        "symbol": symbol,
        "total_trades": total_trades,
        "win_rate": total_wr,
        "profit_factor": total_pf,
        "total_pnl": total_pnl,
        "by_tactic": {t: len(v) for t, v in by_tactic.items()},
    }

# ── Main ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", default="XAUUSD,EURUSD,USDJPY,USDCAD,GBPJPY")
    parser.add_argument("--tactics", default="T1,T2,T3,T4,T5,C1,C2,C3,C4,C5")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--bars", type=int, default=None, help="Override bars count")
    args = parser.parse_args()

    pairs = args.pairs.split(",")
    tactics = args.tactics.split(",")
    # H1 bars: 24 * days
    bars = args.bars or (24 * args.days + 300)  # +300 for indicator warmup

    load_env()

    all_results = {}
    for symbol in pairs:
        regime = INSTRUMENT_REGIMES.get(symbol, "TREND")
        print(f"\nFetching {symbol} ({bars} H1 bars, regime={regime})...")
        candles = fetch_h1(symbol, bars)
        print(f"  Got {len(candles)} bars, from {datetime.datetime.utcfromtimestamp(candles[0]['time'])} "
              f"to {datetime.datetime.utcfromtimestamp(candles[-1]['time'])}")
        results = run_backtest(symbol, candles, tactics, regime)
        summary = report(results, symbol)
        all_results[symbol] = summary

    # Cross-symbol summary
    print(f"\n{'='*70}")
    print(f"  CROSS-SYMBOL SUMMARY")
    print(f"{'='*70}")
    for sym, s in all_results.items():
        if s:
            print(f"  {sym:10s} | trades={s['total_trades']:4d} | WR={s['win_rate']:5.1f}% | "
                  f"PF={s['profit_factor']:5.2f} | pnl={s['total_pnl']:+.4f}")

    # Save detailed results
    out_path = os.path.join(os.path.dirname(__file__), "backtest_results.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

if __name__ == "__main__":
    main()