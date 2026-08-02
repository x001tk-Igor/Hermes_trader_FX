# Trade cycle v3 — averaging-down system (one cron fire)

Run in order. Stop the cycle at the first hard block. Log every meaningful decision
(open, addon, skip, close) via `journal.py add`.

## 0. Window + hard gate
```
py -3 state.py gate
```
- VERDICT `FORCE_FLAT` → close all positions on all symbols, journal, alert, END.
- VERDICT `HALT_NEW` → manage open positions only (step 7-8), no new entries.
- VERDICT `NEW_TRADES_OK` → continue.

## 1. Calendar blackout
```
py -3 calendar.py today
```
- `NOW_INSIDE_BLACKOUT: True` for any currency in CURRENCY_MAP → no new entries for
  affected symbols this fire; manage existing only.

## 2. Perceive market (per symbol)
```
py -3 state.py market [SYMBOL]
```
- Get bid/ask, spread, H1 EMA20/EMA200, ADX(14), ATR(14) for each symbol.
- If spread > SPREAD_MAX_POINTS[symbol] → no new entries for this symbol.
- If ATR > 5% of price → SKIP (anomaly cap).

## 3. T_EMA signal scan (per symbol, TREND regime)
For EACH symbol in xau_env.REGIMES:
- H1: EMA20 > EMA200 AND ADX(14) > 20 → long bias
- H1: EMA20 < EMA200 AND ADX(14) > 20 → short bias
- ADX < 20 → no T_EMA signal (range — check secondary tactics C_RSI_BB/C_Sweep)
- If no existing position on this symbol AND signal present → proceed to step 4.
- If existing position on this symbol → skip to step 6 (addon/management).

## 4. Size (averaging mode)
```
py -3 position_size.py --avg-mode --equity E --max-loss-pct 1.7 --atr A --contract-size C
```
- lot = (equity × 1.7%) / (3 × 1.5×ATR × contract)
- If lot < 0.01 → SKIP (too risky for equity).
- Record lot for all 3 potential positions.

## 5. Execute main entry
```
py -3 trade.py open --symbol SYMBOL --side buy|sell --lot LOT --sl SL --tp TP --terminal "..."
```
- SL = entry − 1.5×ATR (long) or entry + 1.5×ATR (short)
- TP = entry + 0.5×ATR (long) or entry − 0.5×ATR (short) — initial, will be recalculated
- Confirm ticket + fill (no fake checkmarks).
- Journal OPEN: `journal.py add action=OPEN symbol=SYM tactic=T_EMA direction=...
  entry=... sl=... tp=... lot=... atr=... adx=... ema20=... ema200=... avg_group=1`

## 6. Addon management (if existing position on symbol)
```
py -3 state.py avg-positions --symbol SYMBOL
```
- Get all open positions for this symbol: tickets, entries, lots, PnL.
- Calculate current price distance from main entry in ATR units.
- If price is at -1.0×ATR from main entry AND only 1 position → ADDON 1:
  ```
  py -3 trade.py open --symbol SYMBOL --side buy|sell --lot LOT --sl SL2 --tp TP_new --terminal "..."
  ```
  - SL2 = addon1_entry − 1.5×ATR (own SL)
  - Recalculate TP: weighted_avg + 0.5×ATR → update TP on ALL positions
  - Journal ADDON: `journal.py add action=ADDON symbol=SYM addon=1 entry=... sl=... new_tp=...`
- If price is at -2.0×ATR from main entry AND only 2 positions → ADDON 2:
  - Same as above with SL3 = addon2_entry − 1.5×ATR
  - Recalculate TP: new weighted_avg + 0.5×ATR → update TP on ALL positions
  - Journal ADDON: `journal.py add action=ADDON symbol=SYM addon=2 ...`
- If 3 positions already → no more addons, just manage (step 7-8).

## 7. DD check (every fire, for each symbol with open positions)
```
py -3 state.py avg-risk --symbol SYMBOL --equity E
```
- Calculate total PnL (realized from SL hits + unrealized) for this symbol.
- If total loss ≥ 1.7% of equity → CLOSE ALL positions on this symbol:
  ```
  py -3 trade.py close --symbol SYMBOL --all --terminal "..."
  ```
  - Journal: `journal.py add action=DD_STOP symbol=SYM pnl=... reason=dd_stop_1.7pct`

## 8. TP / SL management
- If TP hit on all positions → trade complete, journal CLOSE with PnL.
- If per-position SL hit → that position closes automatically.
  - Remaining positions continue with their own SLs and updated TP.
  - Journal: `journal.py add action=SL_HIT symbol=SYM ticket=... pnl=...`
- Time stop: if 72 bars (H1) since first entry and no resolution → evaluate:
  - If trend still intact → hold.
  - If trend broken → close all, journal.
- Friday ≥19:00 UTC → no new; ≥19:30 → close all.
- Invalidation: H4 trend reversed (EMA20 crossed EMA200 on H4) → close all.

## 9. Report
- No per-trade chatter. Alert on: DD stop, daily 3%, weekly 5%, spread anomaly,
  execution error, all-positions-closed, model degradation.
- Daily report from 22:33 UTC cron.