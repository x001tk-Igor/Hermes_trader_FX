# Pre-trade decision template (§22)

Fill EVERY field before `trade.py open`. If any critical field is empty or a check
fails → trade is FORBIDDEN.

```
Instrument:         (XAUUSD/EURUSD/USDJPY/USDCAD/GBPJPY)
Assigned regime:    (TREND or COUNTER — from xau_env.REGIMES, MUST match)
Time UTC:
Regime:
Daily bias:
DXY context:
US 10Y context:
Real yield context:
Risk sentiment:
News check:        (calendar.py today -> NOW_INSIDE_BLACKOUT must be False)
Spread check:      (state.py market -> spread_verdict must be SPREAD_OK)
Liquidity check:
Tactic:            TREND instruments: LondonBreakout / TrendPullback / NYMacro
                   COUNTER instruments (EURUSD): LiquiditySweep / RangeReversion
                   (MUST match assigned regime — NO mixing)
Direction:
Setup description:
Technical trigger:
Key level:
Round level:
Liquidity sweep:
Entry:
Stop Loss:
Take Profit:
Stop distance:
Risk/Reward:        (must be >= 1.5)
Estimated P_win:
Estimated costs:
Estimated EV_R:     (position_size.py --ev; must be >= +0.25)
Edge over breakeven: (must be >= +5%)
Confluence score:   (A=5-6 / B=4 / forbidden<4; counter-trend needs >=5)
Risk %:             (0.25 / 0.15 / 0.10 per gate)
Position size:      (position_size.py; VERDICT OK, lot>=0.01)
Existing position check:  (state.py positions -> must be 0 open on this symbol)
Daily risk remaining:
Trades today:       (<=4)
Decision:           (OPEN / SKIP)
Reason:
```
Critical pass-list (all must be true to OPEN):
instrument in REGIMES · tactic matches assigned regime · window open · no position on this symbol ·
daily loss <1% · weekly <2.5% · DD<5% · trades<4 ·
not in blackout · spread OK · RR≥1.5 · EV≥+0.25R · edge≥+5% · confluence≥4 (≥5 counter-trend).

## ⚠️ Two override filters (added 2026-07-28, per parallel AI trader review)
Filter A — Sweep vs Breakout: if spread > 2× median AND ADX M5 falling at level touch → FORBIDDEN.
Filter B — SL vs noise: if |entry-SL| < recent 4-bar high-low range → SL inside noise → FORBIDDEN.
These OVERRIDE confluence. 5.5/6 with wide spread+falling ADX+SL inside noise = FORBIDDEN.