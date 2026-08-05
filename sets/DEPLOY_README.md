# Hermes FX — LIVE deploy set (5 пар)

Чемпионы валидированы на нетронутом holdout 2026.05.07-2026.08.05 (Model=4 real ticks).
Holdout-вердикт СТАРШЕ build_elite score (holdout переопределил EURUSD->S8, NZDCAD->C2).

## Deploy-конфиг (5 чартов, 1 экземпляр EA на пару)

| Pair | Tactic | Config | Magic | .set |
|------|--------|--------|-------|------|
| EURAUD | S2 | exit-opt | 77212 | HermesFX_EURAUD_S2.set |
| EURUSD | S8 | exit-opt | 77118 | HermesFX_EURUSD_S8.set |
| GBPUSD | S8 | default-exit | 77018 | HermesFX_GBPUSD_S8.set |
| NZDCAD | C2 | exit-opt | 77402 | HermesFX_NZDCAD_C2.set |
| USDCAD | S6 | exit-opt | 77316 | HermesFX_USDCAD_S6.set |

## Бюджет риска (MONEY, общий на все 5 экземпляров)
- EnableRiskBudget=1 (ON) — lot авто-считается из account equity и SL-расстояния.
- MaxPortfolioRiskPct=5%  — потолок одновременного риска по всем парам (портфельный fence).
- MaxSymbolRiskPct=2.5%   — потолок риска на одну пару.
- BasketRiskPct=1.25%     — риск на одну корзину (1 main + до 2 addons).
- MaxBasketsPerSymbol=3   — макс корзин на пару.
- Lot scale-инвариантен: .set НЕ зависит от размера счёта (risk % пропорционален equity).

## Magic
Magic = MagicBase + tactic_code (Types.mqh). Distinct MagicBase per pair -> ордера
читаемы в журнале. Basket.mqh:83 фильтрует позиции по (symbol AND magic), поэтому
даже одинаковый magic безопасен, но distinct = human-readable.

## Portfolio sim (Model=1, $10k, 2024.01.07-2026.08.05, budget ON)
Combined net +$4547.83 (+45.5% / 2.57yr), CAGR ~15.7%, combined balance maxDD 3.57%,
equity-DD upper bound 8.87% (decorrelated 4.74%). Deploy-grade.
Per-pair net (deals-based, надёжно):
  USDCAD S6 +$1532.51  GBPUSD S8 +$1453.23  EURUSD S8 +$680.33  EURAUD S2 +$474.92  NZDCAD C2 +$406.84

## Перед LIVE
1. Скопировать .set в <DataDir>/MQL5/Files/ (или открыть через Tester/EA inputs).
2. На каждый символ — свой чарт H1, свой экземпляр Hermes_FX, свой .set.
3. Сначала demo/forward 2-4 недели (Model=4 sim подтвердил edge, но live = спред/своп/проскальзывание).
4. EURGBP = NO TRADE (regime сдвиг 2026.05-08, 7/8 конфиг FAIL на holdout) — не деплоить.
5. Live-терминал <TERMINAL_ID_XAU> НЕ трогать (autonomous XAU trader). Hermes FX -> отдельный терминал/счёт.

## Source-of-truth params
phase2/oos_<T>_<P>_inputs.txt (2a default-exit) и phase2/2b_oos_<T>_<P>_inputs.txt (2b exit-opt).
CSV summary params-поля ОБРЕЗАНЫ до 500 символов -> НЕ использовать (см. memory hermes-fx-ea-harness).