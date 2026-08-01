# Hard limits digest (full reglament in Qwen_markdown_Ai_trader_XAU.md)

## Hierarchy (§1)
Capital preservation > risk limits > execution/costs > +EV after costs >
stable/reproducible > profit. Conflict → choose the higher item. Unclear market → no trade.

## Instrument & style (§2.1–2.2)
- Instruments with ASSIGNED REGimes (yearly backtest, H1, with costs):
  XAUUSD→TREND, EURUSD→COUNTER, USDJPY→TREND, USDCAD→TREND, GBPJPY→TREND
- TREND-FOLLOWING instruments: London Breakout, Trend Pullback, NY Macro only
- COUNTER-TREND instruments (EURUSD): Liquidity Sweep Reversal, Range Mean Reversion only
- NO mixing regimes on one instrument. NO switching without new backtest (monthly).
- Intraday, horizon 15min–24h. No weekend hold, no swap/rollover hold.
- Close all intraday before end of day.

## Psychological / round levels (§4.7, §8 тактика 6)
- The reglament lists 2000/2050/.../2500 — **STALE** (gold was ~$2000-2500 when written).
- Gold is now ~$4000+. Current relevant round levels (steps of 50/100): **4000, 4050,
  4100, 4150, 4200**, plus every $100. $4,000 is the major psychological support.
- Round level = CONFIRMATION only, never a standalone entry reason.

## Time (UTC, §2.3)
- XAUUSD: new entries 07:00–20:00 UTC only. Outside: manage/close/trail/BE allowed.
- FX pairs (EURUSD, USDJPY, USDCAD, GBPJPY): new entries 06:00–22:00 UTC only.
- Best: 07–10 (London open), 12:30–16:00 (NY), 13:30–15:30 (max liquidity).
- Friday: no new entries after 19:00 UTC; close ALL by 19:30 UTC (all instruments).

## Risk (§2.4–2.8)
- Risk/trade: 0.25% max. Counter-trend/reversal/news: 0.10–0.15%.
- Daily loss: 1.0% halt new (+manage/reduce/observe/alert). At 0.5%: risk→0.15%, A-only.
- Weekly loss: 2.5% → halt to end of week, close speculative, audit.
- Max DD from equity peak: 5%. At 3%→0.15% A-only; 4%→0.10% strong-only; 5%→stop+close+safe+alert.
- Max 1 active XAUUSD position. No 2nd same dir, no hedge-averaging, no grid, no martingale.
- Max 4 new trades/day.

## Spread/liquidity (§2.9)
- No new trade if spread > 1.5× 5d median OR > $0.35. Halt fully if > $0.50.
- No new trades on low liquidity, spikes, anomalous candles, high slippage, pre-news, panic/gap.

## News (§2.10–2.11)
- No new trades 30min before / 15min after high-impact. Extended (FOMC, CPI, Core CPI,
  PCE, NFP, Fed rate decision, Fed press conf, Fed chair speech, US GDP, Retail Sales,
  ISM PMI): 60min before / 30min after. calendar.py maps these.
- Geo shock: reduce/close, no new until spread+liquidity normalize.

## Minimum trade quality (§2.11, §10)
- RR after costs ≥ 1.5. EV after costs ≥ +0.25R. Confluence ≥ 4/6. P(success) ≥
  breakeven-P + 5%. Counter-trend/reversal: confluence ≥ 5/6, risk 0.10–0.15%.

## Confluence factors (§10 шаг5) — 1 pt each, max 6
1. trend H1/H4 alignment  2. regime+session fit  3. DXY alignment  4. US/real yields alignment
5. safe news + normal spread  6. quality trigger + RR≥1.5 + EV≥+0.25R
- 5–6 = A, 4 = B, 0–3 = no trade. Counter-trend needs ≥5.

## ⚠️ Two critical filters (added 2026-07-28 after 2 SL losses, per parallel AI trader review)

### Filter A: Sweep vs Confirmed Breakout
Before entering on a "retest of broken level" (continuation trade), check:
- **Spread vs median**: if current spread > 2× typical spread (e.g. $0.45 vs $0.20 median = ×2.25),
  the breakout was likely a thin-liquidity sweep, NOT a trend move. Price will revert.
- **ADX M5 direction**: if ADX is FALLING at the moment of level touch, the move is
  exhausting, not trending. A confirmed breakout has RISING ADX.
- If spread ×2+ median AND ADX falling → signal AGAINST continuation, even if
  confluence is 5/6. Do NOT enter. Wait for spread normalization + ADX confirmation.

### Filter B: Stop distance vs recent noise
Before placing SL, compare its distance to the ACTUAL range of the last volatile episode:
- Calculate the range of the last N bars (e.g. last 4 M15 bars high-low).
- If SL distance < recent noise range → SL is INSIDE the noise. It WILL get hit.
- Rule: SL distance must be ≥ 1.0× the recent noise range, OR don't enter.
- Example: recent spike 4011→4030 = $19 noise. SL at 12 from entry = inside noise = bad.
  SL at 20+ from entry, or skip the trade.

These two filters override confluence score when they conflict. A 5.5/6 setup
with wide spread + falling ADX + SL inside noise = FORBIDDEN.

## EV formula (§10 шаг6)
- EV_R = P_win×RR − (1−P_win)×1 − Costs_R
- Costs_R = (spread + commission + slippage) / stop_distance
- Breakeven P = (1 + Costs_R) / (1 + RR)
- position_size.py --ev computes this.

## Position size (§11)
- Position Size = (Equity × Risk%) / (|Entry−SL| × ContractSize), round DOWN to 0.01.
- Below min lot → skip. Too much margin → reduce risk or skip.

## Management (§12)
- SL mandatory from open. Never remove, never widen, never add to loser.
- Partial: +1R → close 40–50% + SL to BE+pad; +2R → close 30%, trail rest. News/reversal:
  +1R→50–70%, +1.5R→most.
- Trail: 1.2×ATR from extreme, or swing, or M15 structure break. Not too tight in high vol.
- Time stop: London break 90–120min; pullback 3–4h; news 60–90min; reversal 60–90min;
  range → end of session / range break.
- Invalidation (logic broken) → close immediately.

## After losses (§13.3)
- 2 in a row → risk 0.15% next 2h. 3 → pause 1h, audit. 4 → halt new trades to EOD.

## Forbidden (§19, full list in reglament)
No-trade-without-SL, remove/widen SL, martingale, grid, avg-down, revenge-size,
trade in uncertainty, trade pre-high-impact-news, other instruments, weekend hold,
ignore daily/DD limits, hidden exposure, ignore costs, emotion/improvisation,
change constitution without permission, hide errors/losses.