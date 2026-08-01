# Trade cycle (one cron fire)

Run in order. Stop the cycle at the first hard block. Log every meaningful decision
(open AND named skip) via `journal.py add`.

## 0. Window + hard gate
```
py -3 state.py gate
```
- VERDICT `FORCE_FLAT` → close all XAUUSD (trade.py close --symbol XAUUSD --all),
  journal, alert user, END.
- VERDICT `HALT_NEW` → manage open position only (step 8), no new entries, END after.
- VERDICT `NEW_TRADES_OK` → continue.

## 1. Calendar blackout
```
py -3 calendar.py today
```
- `NOW_INSIDE_BLACKOUT: True` → no new entries this fire; manage only.

## 2. Perceive market
```
py -3 state.py market
```
- Use bid/ask, spread_verdict, M15_atr14, H1/H4 EMA-proxy for regime.
- If spread_verdict ≠ SPREAD_OK → no new entries.
- DXY / US 10Y / real yields / VIX / risk sentiment: WebSearch when needed (model).

## 3. Regime + daily bias (§6, §7)
- For EACH instrument in xau_env.REGIMES, determine regime + bias:
  Regime ∈ {TREND_UP, TREND_DOWN, RANGE, BREAKOUT, HIGH_VOL, LOW_VOL, NEWS_RISK,
  LOW_LIQUIDITY, CRISIS_MODE, UNCLEAR}. UNCLEAR/NEWS_RISK/LOW_LIQ → no new trades.
  CRISIS → manage/reduce.
- Bias: bullish/bearish/neutral from DXY, 10Y/real yields, Fed exp, risk, geo.
- ONLY use tactics matching the assigned regime:
  TREND instruments (XAUUSD, USDJPY, USDCAD, GBPJPY): LondonBreakout, TrendPullback, NYMacro
  COUNTER instruments (EURUSD): LiquiditySweep, RangeReversion

## 4. Setup scan — match ONE tactic FOR THE ASSIGNED REGIME
TREND instruments:
1. London Gold Breakout (07–10 UTC, Asian range break)
2. Trend Pullback Continuation (08–18 UTC, H1 trend + M15 pullback trigger)
3. New York Macro Continuation (12:30–16 UTC, post-data direction)
COUNTER instruments (EURUSD):
4. Liquidity Sweep Reversal (07–20 UTC, false break of session/PD/round level)
5. Range Mean Reversion (range, ADX<20–25, ≥2 tests)
- Round Level = CONFIRMATION only, never standalone entry.
- None matches → SKIP (journal the named skip).

## 5. Score + EV (§10)
- Fill `decide_template.md` mentally.
- Confluence 6-factor → A(5–6)/B(4)/no(<4). Counter-trend/reversal needs ≥5.
- `py -3 position_size.py --ev --p-win P --rr R --entry E --sl S` → need EV≥+0.25R,
  edge over breakeven ≥+5%. Fail → SKIP.

## 6. Size
```
py -3 position_size.py --equity E --risk-pct R --entry E --sl S --tp TP
```
- risk-pct: 0.25 default; 0.15 if DD≥3% or daily≥0.5% or counter-trend; 0.10 if DD≥4%.
- VERDICT must be OK with a lot ≥0.01. SKIP/FAIL → skip.

## 7. Execute
```
py -3 trade.py open --symbol <SYMBOL> --side buy|sell --lot L --sl S --tp TP --terminal "C:/Program Files/RoboForex MT5 Terminal/terminal64.exe"
```
- `magic=0 comment=""` (trade.py defaults) → manual-trade appearance.
- Confirm `retcode==10009` + `trade.py positions` shows the ticket (no fake checkmarks).
- If open returned without SL/TP → `trade.py sltp --ticket N --sl S --tp TP`.
- Journal OPEN row immediately: `journal.py add action=OPEN symbol=<SYMBOL> tactic=... direction=...
  entry=... sl=... tp=... lot=... risk_pct=... confluence=... rr=... ev_r=...
  p_win=... regime=... daily_bias=... dxy_ctx=... y10_ctx=... spread_in=...
  atr=... session=... round_level=... liq_sweep=... reason_in=...`

## 8. Manage existing position (every fire, even if no new entry)
- `state.py positions` → ticket, profit, sl/tp, age.
- +1R → close 40–50% (trade.py close --ticket N --volume partial; if partial not
  supported, close full and journal), SL→BE+pad (trade.py sltp).
- +2R → close 30%, trail.
- Time stop exceeded → reduce/close. Invalidation → close immediately.
- Friday ≥19:00 UTC → no new; ≥19:30 → close all.
- On close: `journal.py add action=CLOSE exit_date=<now> pnl_usd=... pnl_r=...
  reason_out=... spread_out=...` ; then `journal.py stats`.

## 9. Report (per user choice: daily + alerts only)
- No per-trade chatter. Only alert on: limit breach (0.5/1/2.5%, 3/4/5% DD),
  spread/data/execution anomaly, geo/macro shock, tactic degradation, constitution
  change needed. Daily report comes from the 20:30 UTC cron.