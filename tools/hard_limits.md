# Hard limits digest (v3 — averaging system, 6 FX pairs)

## Hierarchy (§1)
Capital preservation > risk limits > execution/costs > +EV after costs >
stable/reproducible > profit. Conflict → choose the higher item. Unclear market → no trade.

## Instruments & regime (v3 — backtest 2026-08-02)
- 6 FX pairs, ALL TREND regime (with averaging):
  EURUSD, GBPUSD, USDCAD, EURGBP, NZDCAD, EURAUD
- Tactic: T_EMA (EMA20 vs EMA200 + ADX>20 on H1)
- Secondary: C_RSI_BB, C_Sweep (only when ADX<20, range conditions)
- NO JPY pairs, NO XAUUSD (unviable with averaging on $100K equity)
- NO mixing regimes. NO switching without new backtest.

## Averaging rules (v3 — replaces old "no averaging" ban)
- Max 3 positions per symbol: 1 main + 2 addons
- Addon 1: at -1.0×ATR from main entry
- Addon 2: at -2.0×ATR from main entry
- Each position has its OWN physical SL = 1.5×ATR from its own entry
- SL is NEVER moved, NEVER widened, NEVER removed
- TP = weighted_average + 0.5×ATR (recalculated after each addon)
- TP applies to ALL open positions on that symbol simultaneously
- DD stop: if total unrealized+realized loss on symbol ≥ 2.5% equity → close ALL positions
- Lot is calculated ONCE for all 3 positions: lot = (equity × 2.5%) / (3 × 1.5×ATR × contract)
- If calculated lot < 0.01 → SKIP (too risky for equity size)
- If ATR > 5% of price → SKIP (anomaly/gap protection)

### FORBIDDEN within averaging:
- 4th addon (max 3 positions, hard limit)
- Increasing lot on addon (same lot for all 3)
- Expanding SL to "make room" for addon
- Averaging on counter-trend trades (only TREND T_EMA)
- Averaging across different symbols (each symbol independent)
- Averaging without per-position SL

## Risk limits
- Max total loss per symbol (3×SL): 2.5% equity
- Daily loss: 3.0% → halt new trades (6 pairs × ~0.5% = 3% max)
- Weekly loss: 5.0% → halt to end of week
- DD from equity peak: 5% → stop + close + alert
- Max 8 new entries per day (across all 6 pairs)
- Max 1 active averaging group per symbol (3 positions max)
- Max 6 symbols traded simultaneously

## Time (UTC)
- New entries: 06:00–22:00 UTC (all FX pairs)
- Best: 07–10 (London), 12:30–16:00 (NY), 13:30–15:30 (max liquidity)
- Friday: no new entries after 19:00 UTC; close ALL by 19:30 UTC
- No weekend hold, no swap/rollover hold

## Spread/liquidity
- No new trade if spread > instrument max (see xau_env.SPREAD_MAX_POINTS)
- No new trade if spread > 2.0× 5d median
- No new trades on low liquidity, spikes, anomalous candles, pre-news

## News
- No new trades 30min before / 15min after high-impact
- Extended (FOMC, CPI, PCE, NFP, Fed): 60min before / 30min after
- Currency mapping: EURUSD→EUR+USD, GBPUSD→GBP+USD, etc.
- Geo shock: reduce/close, no new until spread+liquidity normalize

## Minimum trade quality
- ADX(14) > 20 on H1 (trend confirmed)
- EMA20 vs EMA200 alignment (trend direction)
- RR after costs ≥ 1.5 (for fixed mode)
- For averaging: TP = weighted_avg + 0.5×ATR (no fixed RR requirement)
- Confluence ≥ 4/6 (model evaluates macro context)

## EV formula (§10 шаг6)
- EV_R = P_win×RR − (1−P_win)×1 − Costs_R
- Costs_R = (spread + commission + slippage) / stop_distance
- Breakeven P = (1 + Costs_R) / (1 + RR)

## Management with averaging
- TP hit → all positions close automatically (TP set on all)
- Per-position SL hit → that position closes, others remain
- DD stop (1.7%) → close all remaining manually
- Time stop: if no TP or all-SL in 72 bars (H1 = 3 days) → evaluate, possibly close
- Friday 19:30 UTC → close all regardless
- Invalidation (trend broken on H4) → close all

## After losses
- 2 symbols in DD stop same day → halt new trades 2 hours, audit
- 3 symbols in DD stop same day → halt to EOD
- Daily 3% hit → halt to next day
- Weekly 5% hit → halt to next week

## Forbidden
No-trade-without-SL, remove/widen SL, martingale (doubling lot),
4th addon, increasing lot on addon, revenge-size, trade in uncertainty,
trade pre-high-impact-news, JPY pairs, XAUUSD, weekend hold,
ignore daily/DD limits, hidden exposure, ignore costs,
change constitution without permission, hide errors/losses.