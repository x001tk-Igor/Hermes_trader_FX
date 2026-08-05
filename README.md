# Hermes FX DEPLOY

Автономная торговая система: **Hermes FX EA** (5 валидированных пар) + **AI Supervisor**
(context-overlay governor: тормоз/газ по внешнему контексту).

## Структура
```
Hermes_FX_DEPLOY/
├── DEPLOY_INSTRUCTION.md   ← НАЧНИ ОТСЮДА (пошаговый деплой в MT5)
├── README.md               # этот файл
├── EA/                     # советник: .mq5 + скомпилированный .ex5 + Modules/*.mqh
├── sets/                   # 5 .set (EURAUD_S2 / EURUSD_S8 / GBPUSD_S8 / NZDCAD_C2 / USDCAD_S6) + DEPLOY_README.md
├── supervisor/             # AI supervisor (Python): supervisor.py + rules/agent/mt5_state/news/bridge/models + config.yaml
└── examples/               # permissions_sample.json
```

## Что валидировано
- 5 пар, holdout PASS 2026.05-2026.08 (нетронутый OOS).
- Portfolio sim 2.57yr: **+$4547.83 / +45.5% на $10k, combined maxDD 3.57%, CAGR ~15.7%**.
- EA-бинарь включает per-symbol Bridge.mqh правку (permissions_<sym>.json).
- Supervisor: hybrid rules+LLM+Opus, constrictive-only (только сужает, >1.0 лот недоступен).

## Быстрый старт
1. Прочитай **DEPLOY_INSTRUCTION.md** полностью (там критерии проверки на каждом шаге).
2. Фаза A — деплой EA (5 чартов H1 + .set).
3. Фаза B — supervisor (config.yaml → test_format.py → --once --dry-run → --once → цикл).
4. Фаза C — верификация (heartbeat + smoke-тормоз).

## ⚠ Безопасные границы
- **<TERMINAL_ID_XAU> НЕ трогать** — там автономный XAU trader (account <ACCOUNT_XAU>). Hermes FX = отдельный терминал.
- **EURGBP = NO TRADE** (regime-сдвиг 2026.05-08, 7/8 FAIL на holdout).
- **Constrictive-only**: supervisor не закрывает позиции и не поднимает лот >1.0.
- Перекомпиляция EA — только в data dir терминала Hermes FX.