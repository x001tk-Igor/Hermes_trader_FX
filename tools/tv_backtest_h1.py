#!/usr/bin/env python3
"""
Quick H1 screening backtest for 9 TradingView strategies.
Tests on 6 FX pairs + XAUUSD, 1 year, with and without averaging.

9 strategies:
  S1: EMA 9 + VWAP + ATR Trailing
  S2: Gold Scalper (EMA trend + RSI pullback / momentum breakout)
  S3: 200 EMA (HTF) + UT Bot + ADX
  S4: MadCharts Baseline (50 EMA/SMA + 9/18 EMA)
  S5: UT Bot + STC + Guard Stack
  S6: Gold NY ORB (13:00-14:00 range, breakout)
  S7: Gate Breaker (Tokyo range → London break)
  S8: Smart Trend julzALGO (BOS/CHoCH simplified)
  S9: VWAP SD2 Reversion (VWAP 2-SD + RSI + MACD)
"""
import os, sys, json, datetime, math
from collections import defaultdict

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
    if not mt5.symbol_select(symbol, True):
        mt5.shutdown(); return None
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, bars)
    mt5.shutdown()
    if rates is None or len(rates) < 250: return None
    candles = []
    for r in rates:
        candles.append({"time": int(r[0]), "open": float(r[1]), "high": float(r[2]),
                        "low": float(r[3]), "close": float(r[4]), "tickvol": float(r[5]),
                        "spread": float(r[6])})
    return candles

# ── Indicators ──────────────────────────────────────────────────────
def ema(values, period):
    out = [None] * len(values)
    k = 2 / (period + 1)
    for i in range(len(values)):
        if i == period - 1: out[i] = sum(values[:period]) / period
        elif i >= period: out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out

def sma(values, period):
    out = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i - period + 1 : i + 1]) / period
    return out

def atr(candles, period=14):
    trs = []
    for i in range(len(candles)):
        if i == 0: trs.append(candles[i]["high"] - candles[i]["low"])
        else:
            h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    out = [None] * len(trs)
    k = 1 / period
    for i in range(period - 1, len(trs)):
        if i == period - 1: out[i] = sum(trs[:period]) / period
        else: out[i] = trs[i] * k + out[i-1] * (1 - k)
    return out

def rsi(closes, period=14):
    out = [None] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(0, ch)); losses.append(max(0, -ch))
    for i in range(period, len(closes)):
        if i == period:
            avg_g = sum(gains[:period]) / period
            avg_l = sum(losses[:period]) / period
        else:
            avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
            avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out

def adx(candles, period=14):
    n = len(candles)
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, n):
        up = candles[i]["high"] - candles[i-1]["high"]
        down = candles[i-1]["low"] - candles[i]["low"]
        plus_dm.append(up if (up > down and up > 0) else 0)
        minus_dm.append(down if (down > up and down > 0) else 0)
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr_s = [0]*n; plus_s = [0]*n; minus_s = [0]*n; adx_s = [None]*n
    for i in range(period, n):
        if i == period:
            atr_s[i] = sum(tr[:period]); plus_s[i] = sum(plus_dm[:period]); minus_s[i] = sum(minus_dm[:period])
        else:
            atr_s[i] = atr_s[i-1] - atr_s[i-1]/period + tr[i-1]
            plus_s[i] = plus_s[i-1] - plus_s[i-1]/period + plus_dm[i-1]
            minus_s[i] = minus_s[i-1] - minus_s[i-1]/period + minus_dm[i-1]
    dx = [None]*n
    for i in range(period, n):
        if atr_s[i] > 0:
            pdi = 100*plus_s[i]/atr_s[i]; mdi = 100*minus_s[i]/atr_s[i]
            if pdi+mdi > 0: dx[i] = 100*abs(pdi-mdi)/(pdi+mdi)
    for i in range(period*2, n):
        if i == period*2:
            vals = [dx[j] for j in range(period, period*2) if dx[j] is not None]
            if vals: adx_s[i] = sum(vals)/len(vals)
        else:
            if adx_s[i-1] and dx[i-1]: adx_s[i] = (adx_s[i-1]*(period-1)+dx[i-1])/period
    return adx_s

def bollinger_bands(closes, period=20, std_mult=2.0):
    n = len(closes); upper = [None]*n; lower = [None]*n; mid = sma(closes, period)
    for i in range(period-1, n):
        window = closes[i-period+1:i+1]; m = mid[i]
        var = sum((x-m)**2 for x in window)/period; sd = math.sqrt(var)
        upper[i] = m+std_mult*sd; lower[i] = m-std_mult*sd
    return upper, mid, lower

def donchian(candles, period=20):
    n = len(candles); dh = [None]*n; dl = [None]*n
    for i in range(period-1, n):
        w = candles[i-period+1:i+1]
        dh[i] = max(c["high"] for c in w); dl[i] = min(c["low"] for c in w)
    return dh, dl

def vwap_session(candles, idx):
    """Session VWAP from 00:00 UTC of current day to idx."""
    dt = datetime.datetime.utcfromtimestamp(candles[idx]["time"])
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_ts = int(day_start.timestamp())
    vwap_start = idx
    for j in range(idx, -1, -1):
        if candles[j]["time"] < day_start_ts:
            vwap_start = j + 1; break
    if vwap_start >= idx: return None
    pv = 0; vol = 0
    for i in range(vwap_start, idx + 1):
        tp = (candles[i]["high"] + candles[i]["low"] + candles[i]["close"]) / 3
        pv += tp * candles[i]["tickvol"]; vol += candles[i]["tickvol"]
    return pv / vol if vol > 0 else candles[idx]["close"]

def ut_bot_trailing(candles, atr_period=2, atr_mult=1):
    """UT Bot trailing stop — simplified for H1."""
    a = atr(candles, atr_period)
    n = len(candles)
    trail = [None] * n
    trend = [0] * n  # 1=up, -1=down
    for i in range(atr_period, n):
        if not a[i]: continue
        if i == atr_period:
            trail[i] = candles[i]["close"] - a[i] * atr_mult
            trend[i] = 1
        else:
            if candles[i]["close"] > trail[i-1]:
                trend[i] = 1
                trail[i] = max(trail[i-1], candles[i]["close"] - a[i] * atr_mult)
            elif candles[i]["close"] < trail[i-1]:
                trend[i] = -1
                trail[i] = min(trail[i-1], candles[i]["close"] + a[i] * atr_mult)
            else:
                trend[i] = trend[i-1]
                trail[i] = trail[i-1]
    return trail, trend

def macd_hist(closes, fast=12, slow=26, signal=9):
    """MACD histogram."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] and ema_slow[i]:
            macd_line[i] = ema_fast[i] - ema_slow[i]
    signal_line = ema([x if x is not None else 0 for x in macd_line], signal)
    hist = [None] * len(closes)
    for i in range(len(closes)):
        if macd_line[i] is not None and signal_line[i] is not None:
            hist[i] = macd_line[i] - signal_line[i]
    return hist

# ── Strategy signals ────────────────────────────────────────────────
# Each returns (direction, entry, sl, tp, name) or None

def sig_S1_ema_vwap(candles, idx, ind):
    """S1: EMA 9 + VWAP + ATR Trailing. EMA9 crosses VWAP."""
    ema9 = ind["ema9"][idx]; atr_val = ind["atr"][idx]
    ema9_prev = ind["ema9"][idx-1] if idx > 0 else None
    if not all([ema9, atr_val, ema9_prev]) or atr_val > candles[idx]["close"] * 0.05:
        return None
    v = vwap_session(candles, idx)
    v_prev = vwap_session(candles, idx - 1) if idx > 0 else None
    if not v or not v_prev: return None
    close = candles[idx]["close"]
    if ema9_prev <= v_prev and ema9 > v:
        return 1, close, close - 2.5*atr_val, close + 0.5*atr_val, "S1_EMA_VWAP"
    elif ema9_prev >= v_prev and ema9 < v:
        return -1, close, close + 2.5*atr_val, close - 0.5*atr_val, "S1_EMA_VWAP"
    return None

def sig_S2_gold_scalper(candles, idx, ind):
    """S2: Gold Scalper — EMA trend + RSI pullback / momentum breakout."""
    ema_fast = ind["ema9"][idx]; ema_slow = ind["ema18"][idx]
    rsi_val = ind["rsi"][idx]; atr_val = ind["atr"][idx]
    if not all([ema_fast, ema_slow, rsi_val, atr_val]) or atr_val > candles[idx]["close"] * 0.05:
        return None
    close = candles[idx]["close"]
    # Mode A: RSI Pullback in trend
    if ema_fast > ema_slow and rsi_val < 40:  # bullish trend + RSI dip
        return 1, close, close - 2.5*atr_val, close + 0.5*atr_val, "S2_GoldScalper_RSI"
    if ema_fast < ema_slow and rsi_val > 60:  # bearish trend + RSI pop
        return -1, close, close + 2.5*atr_val, close - 0.5*atr_val, "S2_GoldScalper_RSI"
    # Mode B: Momentum breakout — 20-bar high/low break
    if idx < 20: return None
    recent_high = max(candles[j]["high"] for j in range(idx-20, idx))
    recent_low = min(candles[j]["low"] for j in range(idx-20, idx))
    if ema_fast > ema_slow and close > recent_high:
        return 1, close, close - 2.5*atr_val, close + 0.5*atr_val, "S2_GoldScalper_Mom"
    if ema_fast < ema_slow and close < recent_low:
        return -1, close, close + 2.5*atr_val, close - 0.5*atr_val, "S2_GoldScalper_Mom"
    return None

def sig_S3_200ema_utbot_adx(candles, idx, ind):
    """S3: 200 EMA (HTF trend) + UT Bot trigger + ADX > 25."""
    ema200 = ind["ema200"][idx]; adx_val = ind["adx"][idx]; atr_val = ind["atr"][idx]
    trail, trend = ind["ut_trail"], ind["ut_trend"]
    if not all([ema200, adx_val, atr_val]) or atr_val > candles[idx]["close"] * 0.05:
        return None
    if adx_val < 25: return None
    close = candles[idx]["close"]
    # UT Bot flip detection
    if idx > 0 and trend[idx] != trend[idx-1]:
        if trend[idx] == 1 and close > ema200:  # HTF trend up + UT Bot flip up
            return 1, close, close - 2.5*atr_val, close + 0.5*atr_val, "S3_200EMA_UTBot"
        if trend[idx] == -1 and close < ema200:  # HTF trend down + UT Bot flip down
            return -1, close, close + 2.5*atr_val, close - 0.5*atr_val, "S3_200EMA_UTBot"
    return None

def sig_S4_madcharts(candles, idx, ind):
    """S4: MadCharts Baseline — 50 EMA/SMA area + 9/18 EMA confirmation."""
    ema50 = ind["ema50"][idx]; sma50 = ind["sma50"][idx]
    ema9 = ind["ema9"][idx]; ema18 = ind["ema18"][idx]
    atr_val = ind["atr"][idx]
    if not all([ema50, sma50, ema9, ema18, atr_val]) or atr_val > candles[idx]["close"] * 0.05:
        return None
    close = candles[idx]["close"]
    # Baseline = area between 50 EMA and 50 SMA
    bl_high = max(ema50, sma50); bl_low = min(ema50, sma50)
    # Price touched baseline area in last 3 bars
    touched = any(bl_low <= candles[j]["low"] <= bl_high or bl_low <= candles[j]["high"] <= bl_high
                  for j in range(max(0, idx-3), idx+1))
    if not touched: return None
    # Long: 9 EMA > 18 EMA, both above baseline, close above both fast EMAs
    if ema9 > ema18 and ema9 > bl_high and ema18 > bl_high and close > ema9:
        return 1, close, close - 2.5*atr_val, close + 0.5*atr_val, "S4_MadCharts"
    # Short: 9 EMA < 18 EMA, both below baseline, close below both fast EMAs
    if ema9 < ema18 and ema9 < bl_low and ema18 < bl_low and close < ema9:
        return -1, close, close + 2.5*atr_val, close - 0.5*atr_val, "S4_MadCharts"
    return None

def sig_S5_utbot_stc(candles, idx, ind):
    """S5: UT Bot + STC + Guard Stack (simplified — UT Bot flip + ADX + candle range)."""
    atr_val = ind["atr"][idx]; adx_val = ind["adx"][idx]
    trail, trend = ind["ut_trail"], ind["ut_trend"]
    if not all([atr_val, adx_val]) or atr_val > candles[idx]["close"] * 0.05:
        return None
    # STC simplified: RSI as proxy for Schaff Trend Cycle
    rsi_val = ind["rsi"][idx]
    if not rsi_val: return None
    # UT Bot flip
    if idx > 0 and trend[idx] != trend[idx-1]:
        # Guard 1: ADX > 20 (trend strength)
        if adx_val < 20: return None
        # Guard 2: Candle range within normal bounds (0.3× to 3× ATR)
        bar_range = candles[idx]["high"] - candles[idx]["low"]
        if bar_range < 0.3 * atr_val or bar_range > 3.0 * atr_val: return None
        # Guard 3: Volume above average (simplified)
        vol_avg = sum(candles[j]["tickvol"] for j in range(max(0, idx-20), idx)) / min(20, idx)
        if candles[idx]["tickvol"] < vol_avg * 0.8: return None
        close = candles[idx]["close"]
        if trend[idx] == 1 and rsi_val < 45:  # oversold floor
            return 1, close, close - 2.5*atr_val, close + 0.5*atr_val, "S5_UTBot_STC"
        if trend[idx] == -1 and rsi_val > 55:  # overbought ceiling
            return -1, close, close + 2.5*atr_val, close - 0.5*atr_val, "S5_UTBot_STC"
    return None

def sig_S6_ny_orb(candles, idx, ind):
    """S6: Gold NY ORB — 13:00-14:00 UTC range, breakout with volume + compression."""
    atr_val = ind["atr"][idx]
    if not atr_val or atr_val > candles[idx]["close"] * 0.05: return None
    dt = datetime.datetime.utcfromtimestamp(candles[idx]["time"])
    # Entry window: 14:00-16:30 UTC
    if not (14 <= dt.hour <= 16 and not (dt.hour == 16 and dt.minute > 30)): return None
    # Build OR from 13:00-14:00 UTC of same day
    day_start = dt.replace(hour=13, minute=0, second=0, microsecond=0)
    day_start_ts = int(day_start.timestamp())
    or_end_ts = int((day_start + datetime.timedelta(hours=1)).timestamp())
    or_high = -float("inf"); or_low = float("inf")
    for j in range(idx, -1, -1):
        if candles[j]["time"] < day_start_ts: break
        if candles[j]["time"] <= or_end_ts:
            or_high = max(or_high, candles[j]["high"])
            or_low = min(or_low, candles[j]["low"])
    if or_high == -float("inf"): return None
    or_range = or_high - or_low
    if or_range <= 0: return None
    # Compression filter: OR range ≤ 2.5×ATR
    if or_range > 2.5 * atr_val: return None
    # Regime filter: ATR ≤ 2× its 20-bar SMA
    if idx < 20: return None
    atr_sma = sum(ind["atr"][j] for j in range(idx-20, idx) if ind["atr"][j]) / 20
    if atr_val > 2 * atr_sma: return None
    close = candles[idx]["close"]
    vol_avg = sum(candles[j]["tickvol"] for j in range(max(0, idx-20), idx)) / min(20, idx)
    # Long: close above OR high + volume > 1.5× average
    if close > or_high and candles[idx]["tickvol"] > 1.5 * vol_avg:
        return 1, close, or_low, or_low + 2.5 * or_range, "S6_NY_ORB"
    # Short: close below OR low + volume
    if close < or_low and candles[idx]["tickvol"] > 1.5 * vol_avg:
        return -1, close, or_high, or_high - 2.5 * or_range, "S6_NY_ORB"
    return None

def sig_S7_gate_breaker(candles, idx, ind):
    """S7: Gate Breaker — Tokyo range → London body break."""
    atr_val = ind["atr"][idx]
    if not atr_val or atr_val > candles[idx]["close"] * 0.05: return None
    dt = datetime.datetime.utcfromtimestamp(candles[idx]["time"])
    # London session: 08:00-17:00 London = ~07:00-16:00 UTC (approximate)
    if not (7 <= dt.hour <= 16): return None
    # Build Tokyo range: 00:00-06:00 UTC (approximate Tokyo session)
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_ts = int(day_start.timestamp())
    tokyo_end_ts = int((day_start + datetime.timedelta(hours=6)).timestamp())
    tokyo_high = -float("inf"); tokyo_low = float("inf")
    for j in range(idx, -1, -1):
        if candles[j]["time"] < day_start_ts: break
        if candles[j]["time"] <= tokyo_end_ts:
            tokyo_high = max(tokyo_high, candles[j]["high"])
            tokyo_low = min(tokyo_low, candles[j]["low"])
    if tokyo_high == -float("inf"): return None
    close = candles[idx]["close"]
    open_ = candles[idx]["open"]
    # Body break: candle body closes above/below Tokyo range
    if close > tokyo_high and open_ <= tokyo_high:  # body breaks up
        return 1, close, tokyo_low, close + 2.5 * atr_val, "S7_GateBreaker"
    if close < tokyo_low and open_ >= tokyo_low:  # body breaks down
        return -1, close, tokyo_high, close - 2.5 * atr_val, "S7_GateBreaker"
    return None

def sig_S8_smart_trend(candles, idx, ind):
    """S8: Smart Trend julzALGO — trend + structure (simplified: EMA trend + ADX + M15 close confirmation)."""
    ema20 = ind["ema20"][idx]; ema200 = ind["ema200"][idx]
    adx_val = ind["adx"][idx]; atr_val = ind["atr"][idx]
    if not all([ema20, ema200, adx_val, atr_val]) or atr_val > candles[idx]["close"] * 0.05:
        return None
    if adx_val < 20: return None
    close = candles[idx]["close"]
    # Structure: higher highs/lower lows simplified
    if idx < 5: return None
    # Trend up: EMA20 > EMA200, price above EMA20, ADX rising
    adx_rising = ind["adx"][idx] and ind["adx"][idx-1] and ind["adx"][idx] > ind["adx"][idx-1]
    if ema20 > ema200 and close > ema20 and adx_rising:
        # Simple BOS: close above last 5-bar high
        recent_high = max(candles[j]["high"] for j in range(idx-5, idx))
        if close > recent_high:
            return 1, close, close - 2.5*atr_val, close + 0.5*atr_val, "S8_SmartTrend"
    if ema20 < ema200 and close < ema20 and adx_rising:
        recent_low = min(candles[j]["low"] for j in range(idx-5, idx))
        if close < recent_low:
            return -1, close, close + 2.5*atr_val, close - 0.5*atr_val, "S8_SmartTrend"
    return None

def sig_S9_vwap_sd2(candles, idx, ind):
    """S9: VWAP SD2 Reversion — price beyond 2-SD VWAP band + RSI recovery + MACD turn."""
    rsi_val = ind["rsi"][idx]; atr_val = ind["atr"][idx]
    hist = ind["macd_hist"]
    if not all([rsi_val, atr_val]) or atr_val > candles[idx]["close"] * 0.05: return None
    if idx < 2: return None
    # Calculate session VWAP and 2-SD bands
    v = vwap_session(candles, idx)
    if not v: return None
    # Simplified: use Bollinger-style bands around VWAP
    # Need session candles for std calc
    dt = datetime.datetime.utcfromtimestamp(candles[idx]["time"])
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_ts = int(day_start.timestamp())
    session_closes = []
    for j in range(idx, -1, -1):
        if candles[j]["time"] < day_start_ts: break
        session_closes.append(candles[j]["close"])
    if len(session_closes) < 10: return None
    session_std = math.sqrt(sum((c - v)**2 for c in session_closes) / len(session_closes))
    upper = v + 2 * session_std
    lower = v - 2 * session_std
    close = candles[idx]["close"]
    # Long: close below lower 2-SD band + RSI recovering + MACD turning bullish
    if close < lower and rsi_val > 30 and rsi_val < 40:
        if hist[idx] is not None and hist[idx-1] is not None and hist[idx] > hist[idx-1]:
            return 1, close, close - 2.5*atr_val, v, "S9_VWAP_SD2"
    # Short: close above upper 2-SD band + RSI dropping + MACD turning bearish
    if close > upper and rsi_val < 70 and rsi_val > 60:
        if hist[idx] is not None and hist[idx-1] is not None and hist[idx] < hist[idx-1]:
            return -1, close, close + 2.5*atr_val, v, "S9_VWAP_SD2"
    return None

# ── All strategies ──────────────────────────────────────────────────
STRATEGIES = {
    "S1_EMA_VWAP": sig_S1_ema_vwap,
    "S2_GoldScalper": sig_S2_gold_scalper,
    "S3_200EMA_UTBot": sig_S3_200ema_utbot_adx,
    "S4_MadCharts": sig_S4_madcharts,
    "S5_UTBot_STC": sig_S5_utbot_stc,
    "S6_NY_ORB": sig_S6_ny_orb,
    "S7_GateBreaker": sig_S7_gate_breaker,
    "S8_SmartTrend": sig_S8_smart_trend,
    "S9_VWAP_SD2": sig_S9_vwap_sd2,
}

# ── Trade simulation ────────────────────────────────────────────────
def sim_trade(entry, sl, tp, candles, idx, direction, max_bars=48):
    for j in range(idx+1, min(idx+1+max_bars, len(candles))):
        c = candles[j]
        if direction == 1:
            if c["low"] <= sl: return "loss", (sl-entry)
            if c["high"] >= tp: return "win", (tp-entry)
        else:
            if c["high"] >= sl: return "loss", (entry-sl)
            if c["low"] <= tp: return "win", (entry-tp)
    exit_p = candles[min(idx+max_bars, len(candles)-1)]["close"]
    if direction == 1: return "timeout", (exit_p-entry)
    return "timeout", (entry-exit_p)

def sim_averaging(entry, direction, atr_val, candles, idx, contract, lot, equity, max_loss_pct=2.5, max_bars=72):
    """Averaging down: 3 positions at -1/-2×ATR, SL=2.5×ATR each, TP=wavg+0.5×ATR."""
    positions = [(entry, entry - 2.5*atr_val if direction==1 else entry + 2.5*atr_val, lot)]
    realized = 0.0; n_addons = 0
    addon_levels = [entry - 1.0*atr_val if direction==1 else entry + 1.0*atr_val,
                    entry - 2.0*atr_val if direction==1 else entry + 2.0*atr_val]
    for j in range(idx+1, min(idx+1+max_bars, len(candles))):
        c = candles[j]
        new_pos = []
        for pe, ps, pl in positions:
            hit = False
            if direction == 1:
                if c["low"] <= ps: hit = True; realized += (ps-pe)*contract*pl
            else:
                if c["high"] >= ps: hit = True; realized += (pe-ps)*contract*pl
            if not hit: new_pos.append((pe, ps, pl))
        positions = new_pos
        if not positions: return "all_sl", realized, n_addons+1
        worst = c["low"] if direction==1 else c["high"]
        unreal = sum((worst-pe)*contract*pl if direction==1 else (pe-worst)*contract*pl for pe,ps,pl in positions)
        if realized + unreal <= -equity * max_loss_pct / 100:
            close = sum((worst-pe)*contract*pl if direction==1 else (pe-worst)*contract*pl for pe,ps,pl in positions)
            return "dd_stop", realized+close, n_addons+1
        if n_addons < 2:
            ap = addon_levels[n_addons]
            reached = c["low"] <= ap if direction==1 else c["high"] >= ap
            if reached:
                asl = ap - 2.5*atr_val if direction==1 else ap + 2.5*atr_val
                positions.append((ap, asl, lot)); n_addons += 1
        tl = sum(p[2] for p in positions)
        wavg = sum(p[0]*p[2] for p in positions)/tl
        tp = wavg + 0.5*atr_val if direction==1 else wavg - 0.5*atr_val
        hit_tp = c["high"] >= tp if direction==1 else c["low"] <= tp
        if hit_tp:
            total = realized
            for pe,ps,pl in positions: total += (tp-pe)*contract*pl if direction==1 else (pe-tp)*contract*pl
            return "recovered", total, n_addons+1
    exit_p = candles[min(idx+max_bars, len(candles)-1)]["close"]
    total = realized
    for pe,ps,pl in positions: total += (exit_p-pe)*contract*pl if direction==1 else (pe-exit_p)*contract*pl
    return "timeout", total, n_addons+1

# ── Indicators computation ──────────────────────────────────────────
def compute_ind(candles):
    closes = [c["close"] for c in candles]
    ut_trail, ut_trend = ut_bot_trailing(candles)
    return {
        "atr": atr(candles, 14), "adx": adx(candles, 14), "rsi": rsi(closes, 14),
        "ema9": ema(closes, 9), "ema18": ema(closes, 18), "ema20": ema(closes, 20),
        "ema50": ema(closes, 50), "sma50": sma(closes, 50), "ema200": ema(closes, 200),
        "bb_upper": bollinger_bands(closes, 20, 2.0)[0], "bb_mid": bollinger_bands(closes, 20, 2.0)[1],
        "bb_lower": bollinger_bands(closes, 20, 2.0)[2],
        "donchian_h": donchian(candles, 20)[0], "donchian_l": donchian(candles, 20)[1],
        "ut_trail": ut_trail, "ut_trend": ut_trend,
        "macd_hist": macd_hist(closes),
    }

# ── Main ────────────────────────────────────────────────────────────
def main():
    pairs = ["EURUSD", "GBPUSD", "USDCAD", "EURGBP", "NZDCAD", "EURAUD", "XAUUSD"]
    bars = 24 * 365 + 300
    equity = 88699.0
    contract_fx = 100000; contract_gold = 100

    load_env()

    print(f"\n{'='*130}")
    print(f"  H1 SCREENING — 9 TradingView strategies × 7 pairs × 1 year")
    print(f"  Equity: ${equity:.0f} | Fixed + Averaging modes")
    print(f"{'='*130}\n")

    all_results = {}

    for symbol in pairs:
        candles = fetch_h1(symbol, bars)
        if not candles:
            print(f"  {symbol}: NO DATA"); continue

        contract = contract_gold if "XAU" in symbol else contract_fx
        digits = 2 if "XAU" in symbol else 5
        spread_cost = lambda idx: candles[idx]["spread"] * (10 ** -digits) * contract
        ind = compute_ind(candles)

        print(f"  {symbol} ({len(candles)} bars)")
        print(f"  {'Strategy':20s} | {'Fixed PF':>8s} {'Fixed WR':>8s} {'Fixed PnL':>12s} | "
              f"{'Avg PF':>8s} {'Avg WR':>8s} {'Avg PnL':>12s} {'Avg Worst':>10s} | {'Winner':>8s}")
        print(f"  {'-'*20} | {'-'*8} {'-'*8} {'-'*12} | {'-'*8} {'-'*8} {'-'*12} {'-'*10} | {'-'*8}")

        for sname, sfunc in STRATEGIES.items():
            fixed_trades = []; avg_trades = []
            cooldown = 0
            for idx in range(210, len(candles) - 72):
                if cooldown > 0: cooldown -= 1; continue
                sig = sfunc(candles, idx, ind)
                if not sig: continue
                direction, entry, sl, tp, label = sig
                atr_val = ind["atr"][idx]; sc = spread_cost(idx)

                # Fixed: 0.01 lot
                r_f, pnl_f = sim_trade(entry, sl, tp, candles, idx, direction)
                fixed_trades.append({"pnl": pnl_f * contract * 0.01 - sc * 0.01})

                # Averaging: lot sized for 2.5% equity
                lot = max(math.floor((equity * 2.5 / 100) / (3 * 2.5 * atr_val * contract) * 100) / 100, 0.01)
                lot = max(math.floor(lot / 2 * 100) / 100, 0.01)  # safety divisor
                if lot >= 0.01:
                    r_a, pnl_a, n_a = sim_averaging(entry, direction, atr_val, candles, idx, contract, lot, equity)
                    avg_trades.append({"pnl": pnl_a - sc * n_a})

                cooldown = 2

            # Stats
            def stats(trades):
                if not trades: return None
                n = len(trades)
                wins = [t for t in trades if t["pnl"] > 0]
                losses = [t for t in trades if t["pnl"] <= 0]
                gp = sum(t["pnl"] for t in wins)
                gl = abs(sum(t["pnl"] for t in losses))
                pf = gp / gl if gl > 0 else float("inf") if gp > 0 else 0
                total = sum(t["pnl"] for t in trades)
                worst = min(t["pnl"] for t in trades) if trades else 0
                return {"n": n, "wr": len(wins)/n*100 if n else 0, "pf": pf, "pnl": total, "worst": worst}

            sf = stats(fixed_trades); sa = stats(avg_trades)
            fpf = f"{sf['pf']:.2f}" if sf else "  -  "
            fwr = f"{sf['wr']:.1f}%" if sf else "  -  "
            fpnl = f"${sf['pnl']:+.0f}" if sf else "    -    "
            apf = f"{sa['pf']:.2f}" if sa else "  -  "
            awr = f"{sa['wr']:.1f}%" if sa else "  -  "
            apnl = f"${sa['pnl']:+.0f}" if sa else "    -    "
            aworst = f"${sa['worst']:+.0f}" if sa else "    -    "
            winner = "AVG" if (sa and sf and sa["pnl"] > sf["pnl"]) else "FIX" if (sf and sa) else "  -  "
            print(f"  {sname:20s} | {fpf:>8s} {fwr:>8s} {fpnl:>12s} | "
                  f"{apf:>8s} {awr:>8s} {apnl:>12s} {aworst:>10s} | {winner:>8s}")

            all_results[f"{symbol}/{sname}"] = {"fixed": sf, "avg": sa}
        print()

    # Cross-strategy summary
    print(f"\n{'='*130}")
    print(f"  CROSS-STRATEGY SUMMARY (averaging mode, all pairs)")
    print(f"{'='*130}")
    print(f"  {'Strategy':20s} | {'Total PnL':>12s} | {'Best PF':>8s} | {'Pairs Profitable':>18s} | {'Verdict':>10s}")
    print(f"  {'-'*20} | {'-'*12} | {'-'*8} | {'-'*18} | {'-'*10}")
    for sname in STRATEGIES.keys():
        total_pnl = 0; best_pf = 0; profitable = 0; total_pairs = 0
        for sym in pairs:
            key = f"{sym}/{sname}"
            if key in all_results and all_results[key]["avg"]:
                sa = all_results[key]["avg"]
                total_pnl += sa["pnl"]; total_pairs += 1
                if sa["pf"] > best_pf: best_pf = sa["pf"]
                if sa["pnl"] > 0: profitable += 1
        verdict = "ALIVE" if total_pnl > 0 else "DEAD"
        print(f"  {sname:20s} | ${total_pnl:+11.0f} | {best_pf:8.2f} | {profitable}/{total_pairs:2d}             | {verdict:>10s}")

    out = os.path.join(os.path.dirname(__file__), "tv_backtest_h1.json")
    with open(out, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to {out}")

if __name__ == "__main__":
    main()