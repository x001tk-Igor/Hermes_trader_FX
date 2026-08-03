# Trade cycle v4 — full constitution-compliant cycle (one hour)

Run ALL 7 steps in order. Do NOT skip steps. No trade without full analysis.

## Step 1. Hard limits (gate)
```
py -3 tools/state.py gate
```
- VERDICT FORCE_FLAT → close all, alert, END.
- VERDICT HALT_NEW → skip to Step 7 (manage only). No new entries.
- VERDICT NEW_TRADES_OK → continue to Step 2.
- Check: open instruments ≤ 3 (excluding addons). If 3 open → no new entries.

## Step 2. News (calendar)
```
py -3 tools/calendar.py symbols
py -3 tools/calendar.py today
```
- Symbols in blackout → skip for new entries. Addons/management OK.
- Events in next 60 min → block affected pairs.
- Record in journal: `journal.py add action=NEWS notes="blocked=EURUSD,GBPUSD until 14:30"`

## Step 3. Market context + macro
### 3.1 Technical (every cycle)
```
py -3 tools/state.py market
```
- For each pair: bid/ask/spread/EMA20/EMA200/ADX/ATR
- Spread > limit → skip pair
- ATR > 5% of price → skip pair (anomaly)

### 3.2 Macro (update every 2-3 hours)
- DXY: rising / falling / flat
- US 10Y yields: rising / falling / flat
- Risk-on / risk-off: S&P futures, VIX
- Session: Asian / London / NY / overlap / low-liquidity
- Use web search if needed

### 3.3 Bias per pair
- EURUSD: DXY down + EUR strong → bullish. DXY up → bearish.
- GBPUSD: DXY down + GBP strong → bullish.
- USDCAD: DXY up + oil down → bullish (USDCAD up). CAD strong → bearish.
- EURGBP: EUR vs GBP dynamics, less USD-dependent.
- NZDCAD: NZD vs CAD — commodity currencies, risk sentiment.
- EURAUD: EUR vs AUD — risk-on → AUD strong, risk-off → EUR strong.

Record bias: `journal.py add action=BIAS notes="EURUSD=bullish GBPUSD=bullish..."`

## Step 4. Regime determination (per pair, for pairs without position)
Analyze H1 chart structure:
- TREND_UP: EMA20 > EMA200, ADX > 25, price above EMA20, higher highs/higher lows
- TREND_DOWN: EMA20 < EMA200, ADX > 25, price below EMA20, lower highs/lower lows
- RANGE: ADX < 20, price between EMAs, horizontal channel, 2+ tests
- BREAKOUT: price breaking key level (PDH/PDL/Donchian/round) with volume
- UNCLEAR: ADX 20-25, price around EMA20, no clear structure → NO TRADE

If UNCLEAR → skip pair. "No trade" is a decision.

## Step 5. Setup search (per pair, only if regime + bias align)
Match ONE tactic to current price action:

### TREND pairs:
- **Trend Pullback**: price returned to EMA20 on H1/M15, trigger candle (pin bar, engulfing, RSI reversal from 40-50 for long / 50-60 for short). DXY/yields support.
- **London Breakout**: price breaks Asian range (00:00-07:00 UTC), 07:00-10:00 UTC, M15 close beyond range. DXY/yields support.
- **NY Macro**: after US data (12:30-16:00 UTC), price breaks pre-news range, cooldown passed. DXY/yields confirm.

### RANGE pairs:
- **Range Mean Reversion**: ADX < 20, range exists 4+ hours, 2+ boundary tests, rejection candle at boundary. DXY/yields neutral.
- **RSI + BB**: close beyond BB(20,2) + RSI extreme (< 30 or > 70) + ADX < 20. Reversion to middle BB.

### BREAKOUT/REVERSAL:
- **Liquidity Sweep**: false break of PDH/PDL/session level, quick return inside, 3-candle confirmation. Confluence ≥ 5.
- **Donchian Breakout**: price breaks 20-bar Donchian channel, ADX rising, volume above average.

If NO setup matches current price action → NO TRADE. Do not force.

## Step 6. Confluence + EV
### Confluence Score (6 factors, 1 point each):
1. Trend H1/H4 aligns with trade direction
2. Regime + session fit the tactic
3. DXY supports (or neutral)
4. Yields / risk sentiment support (or neutral)
5. Safe news + normal spread
6. Quality technical trigger + RR ≥ 1.5 + EV ≥ +0.25R

Categories: A (5-6), B (4), FORBIDDEN (< 4). Counter-trend: minimum 5.

### EV calculation:
```
py -3 tools/position_size.py --ev --p-win P --rr R --entry E --sl S --contract-size 100000 --spread-usd 0.0001
```
- EV_R = P_win × RR − (1−P_win) × 1 − Costs_R
- Need: EV ≥ +0.25R, edge ≥ +5%
- If confluence < 4 OR EV < 0.25R → NO TRADE

## Step 7. Execution + management

### 7.1 New entry (if Steps 1-6 all passed):
```
py -3 tools/position_size.py --avg-mode --equity E --max-loss-pct 2.5 --atr A --contract-size 100000
py -3 tools/trade.py open --symbol S --side buy|sell --lot L --sl SL --tp TP --terminal "..."
```
- SL = 2.5 × ATR from entry
- TP = entry + 0.5 × ATR (initial, recalculated after addons)

### 7.2 Journal with FULL analysis:
```
py -3 tools/journal.py add action=OPEN symbol=EURUSD tactic=TrendPullback direction=long
  entry=... sl=... tp=... lot=... atr=... adx=... regime=TREND_UP
  dxy_ctx=falling y10_ctx=falling risk_sentiment=on
  confluence=5 ev_r=0.35 rr=2.0 p_win=0.55
  reason="Pullback to EMA20 on H1, pin bar on M15, DXY falling, no news"
```

### 7.3 Manage existing positions:
- Check addon distances: `state.py avg-positions SYMBOL`
- If price at -1×ATR and 1 position → addon 1 (same lot, own SL=2.5×ATR)
- If price at -2×ATR and 2 positions → addon 2
- After addon: `trade.py avg-tp --symbol SYMBOL` (recalculate TP)
- DD check: `state.py avg-risk SYMBOL` (2.5% → close all)
- Time stop: position open > 72 H1 bars and not developing → evaluate close
- Signal invalidation: H4 trend reversed → close all on that symbol

### 7.4 Telegram report:
- New entries: symbol, direction, tactic, confluence, EV, reason
- Addons: symbol, addon number, new TP
- DD stops: symbol, PnL
- TP/SL hits: symbol, PnL
- If nothing happened: brief status (equity, positions, next event)