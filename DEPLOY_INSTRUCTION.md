# Hermes FX — Инструкция по разворачиванию и запуску в MT5

Эта инструкция — для LLM (или человека), разворачивающего автономную систему **Hermes FX EA
+ AI Supervisor** на MT5-терминале с нуля. Выполняй по порядку. Каждый шаг имеет
критерий проверки — не пропускай проверки (no-fake-checkmarks: ✅ только когда файл/скрипт
подтвердил).

---

## 0. Что это такое

- **Hermes FX EA** — мультотактический averaging-down советник (12 тактик, 1 main + 2 addon
  на -1/-2 ATR, виртуальный TP на средневзвешенной цене). Бюджет риска в ДЕНЬГАХ.
- **5 валидированных пар** (holdout PASS 2026.05-2026.08, portfolio sim +$4547.83 / +45.5%
  на $10k / 2.57yr, combined maxDD 3.57%, CAGR ~15.7%):

  | Пара | Тактика | Magic | .set |
  |------|---------|-------|------|
  | EURAUD | S2 DualMode | 77212 | sets/HermesFX_EURAUD_S2.set |
  | EURUSD | S8 SmartTrend | 77118 | sets/HermesFX_EURUSD_S8.set |
  | GBPUSD | S8 SmartTrend | 77018 | sets/HermesFX_GBPUSD_S8.set |
  | NZDCAD | C2 RangeReversion | 77402 | sets/HermesFX_NZDCAD_C2.set |
  | USDCAD | S6 NY_ORB | 77316 | sets/HermesFX_USDCAD_S6.set |

  EURGBP = NO TRADE (regime-сдвиг 2026.05-08, 7/8 конфиг FAIL на holdout).

- **AI Supervisor** — context-overlay governor. Читает внешний контекст (FF-calendar,
  ATR/volatility, equity DD, margin, session-open, multi-TF trend+RSI) и решает per-pair:
  **полный газ / тормоз / стоп новых входов**. Пишет `permissions_<pair>.json` в мост EA;
  EA читает на каждом H1-баре и применяет. **Constrictive-only**: только сужает, никогда
  не расширяет; позиций не закрывает. «Полный газ» = ALLOW = risk_multiplier=1.0 =
  валидированный baseline.

### Структура папки проекта
```
Hermes_FX_DEPLOY/
├── DEPLOY_INSTRUCTION.md          # этот файл
├── EA/                            # советник
│   ├── Hermes_FX.mq5              # исходник (с per-symbol Bridge.mqh правкой)
│   ├── Hermes_FX.ex5              # СКОМПИЛИРОВАННЫЙ бинарь (готов к деплою)
│   ├── ontester_template.mqh      # OnTester-коллектор (нужен для компиляции)
│   └── Modules/*.mqh              # 8 модулей
├── sets/                          # 5 .set + DEPLOY_README.md
├── supervisor/                    # AI supervisor (Python)
│   ├── supervisor.py              # главный цикл
│   ├── rules.py / agent.py / mt5_state.py / news.py / bridge.py / models.py
│   ├── config.yaml                # НАСТРОИТЬ под терминал (путь к MQL5\Files)
│   ├── test_format.py             # валидация формата моста
│   ├── requirements.txt
│   └── run_supervisor.ps1         # launcher
└── examples/permissions_sample.json
```

---

## 1. Предварительные требования

### 1.1 MT5 терминал
- Отдельный MT5-терминал для Hermes FX (демо или реал). **НЕ <TERMINAL_ID_XAU>** — там автономный
  XAU trader (account <ACCOUNT_XAU>), его НЕ ТРОГАТЬ.
- Терминал должен быть запущен во время работы EA и supervisor-а (supervisor подключается
  к нему через `mt5.initialize(path=...)`).
- Символы EURAUD/EURUSD/GBPUSD/NZDCAD/USDCAD доступны, H1-история загружена.

### 1.2 Python окружение
- Python 3.10+ (на этой машине `py -3` = Python 3.13).
- Зависимости:
  ```pwsh
  cd <путь>\Hermes_FX_DEPLOY\supervisor
  py -3 -m pip install -r requirements.txt
  ```
  (MetaTrader5, PyYAML, requests, openai)

### 1.3 OpenRouter API key (для LLM-слоя supervisor-а)
- env var `OPENROUTER_API_KEY` с ключом OpenRouter (модели Sonnet/Opus).
- Если хочешь стартовать БЕЗ LLM (только детерминированные rules, 0 API cost) — ключ не
  нужен, запускай с `--rules-only` (см. §3.3).

### 1.4 Критерий проверки §1
```pwsh
py -3 -c "import MetaTrader5,yaml,requests,openai; print('deps OK')"
echo $env:OPENROUTER_API_KEY   # должен быть непустой (если не --rules-only)
```
✅ `deps OK` + ключ есть (или явное решение `--rules-only`).

---

## 2. Фаза A — Деплой EA в MT5

### 2.1 Установить EA в терминал
1. Узнай data dir терминала Hermes FX: в MT5 **File → Open Data Folder**. Путь вида
   `C:\Users\<user>\AppData\Roaming\MetaQuotes\Terminal\<HASH>\`.
2. Скопируй **всю папку** `EA/` (включая `Modules/` и `ontester_template.mqh`) в
   `<DataDir>/MQL5/Experts/Hermes_FX/`. Структура:
   ```
   <DataDir>/MQL5/Experts/Hermes_FX/
   ├── Hermes_FX.mq5
   ├── Hermes_FX.ex5          # готовый бинарь — можно сразу, без компиляции
   ├── ontester_template.mqh
   └── Modules/*.mqh
   ```
3. (Опционально) Перекомпилировать в MetaEditor (F7) → убедиться `0 errors, 0 warnings`.
   Если бинарь уже скопирован — компиляция не обязательна, но рекомендуется для уверенности.
4. В MT5: **Ctrl+N** (Navigator) → Experts → `Hermes_FX` должен появиться.

### 2.2 Прикрепить 5 чартов
Для каждой пары из таблицы §0:
1. Открой чарт **<PAIR> H1**.
2. Перетащи `Hermes_FX` из Navigator на чарт.
3. Вкладка **Common**: ✅ Allow Algo Trading. Period H1.
4. Вкладка **Inputs** → **Load** → выбери `sets/HermesFX_<PAIR>_<TAC>.set`.
   ⚠ Убедись что `EnableBridge=1`, `BridgeFolder=HermesFX`, `EnableRiskBudget=1`,
   `SoloTactic` = код тактики (S2=12, S8=18, C2=2, S6=16), `MagicBase` = из таблицы §0.
5. ✅ Allow live trading (если реал).
6. OK — EA прикреплён. В правом верхнем углу чарта — смайлик 🙂 (algo trading on).

### 2.3 Включить AutoTrading
- Кнопка **AutoTrading** на панели MT5 = зелёная.
- Каждый чарт: галочка «Algo Trading» в верхнем углу включена.

### 2.4 Критерий проверки §2 (EA жив)
- На каждом из 5 чартов: смайлик 🙂 без十字.
- EA пишет heartbeat: проверь, что появился файл
  `<DataDir>/MQL5/Files/HermesFX/heartbeat_<PAIR>.json` (на каждом H1-баре или по таймеру).
  ```pwsh
  dir <DataDir>\MQL5\Files\HermesFX\heartbeat_*.json
  ```
✅ 5 heartbeat-файлов появляются/обновляются (возраст < 5 мин). Если пусто — EA не пишет
   мост: проверь `EnableBridge=1` в .set и что BridgeFolder=HermesFX.

---

## 3. Фаза B — Деплой AI Supervisor

### 3.1 Настроить config.yaml
Открой `supervisor/config.yaml`. КРИТИЧНО два поля:
```yaml
bridge:
  folder: "<DataDir>/MQL5/Files/HermesFX"     # ТА ЖЕ папка, куда EA пишет heartbeat
  mt5_data_path: "<полный путь к DataDir>"     # для mt5.initialize(path=...)
  # mt5_data_path: null  # = default запущенный терминал (если Hermes FX терминал один запущен)
```
⚠ `mt5_data_path` должен указывать на терминал **Hermes FX**, НЕ <TERMINAL_ID_XAU>. Если на машине
   одновременно запущен XAU trader (<TERMINAL_ID_XAU>) — ОБЯЗАТЕЛЬНО укажи `mt5_data_path` явно,
   иначе `mt5.initialize()` подключится к случайному (может к XAU — НЕЛЬЗЯ).
   Пример: `mt5_data_path: "C:/Users/<USER>/AppData/Roaming/MetaQuotes/Terminal/<HASH>"`.

Пороги `risk_thresholds` уже выставлены консервативно под validated maxDD 3.57%:
- DD≥1.5% → BRAKE_LIGHT, ≥2.5% → BRAKE_MODERATE, ≥4% → BRAKE_HEAVY, ≥6% → KILL_NEW.
- margin<200% → KILL_NEW. NFP/high-impact 60мин → KILL_NEW. ATR D1 >2× среднего 30д → BRAKE_HEAVY.

### 3.2 Валидация формата моста (обязательно перед первым запуском)
```pwsh
cd <путь>\Hermes_FX_DEPLOY\supervisor
py -3 test_format.py
```
✅ `ALL 7 CASES PASS — permissions format совместим с Bridge.mqh`.
   Если FAIL — не запускай supervisor (формат не парсится EA). Это значит test-парсер
   рассинхронизирован с models.py — почини перед деплоем.

### 3.3 Первый прогон — dry-run + rules-only (БЕЗ API, БЕЗ записи)
Безопасная проверка: supervisor читает state из MT5, новости, считает решения через rules
(детерминированно), НИЧЕГО не пишет в EA.
```pwsh
py -3 supervisor.py --config config.yaml --once --dry-run --rules-only
```
✅ Лог показывает 5 решений (по одной на пару), статус `DRY`, действия разумные
   (calm-рынок → ALLOW; если сейчас high-impact новость → KILL_NEW). Нет ошибок
   `MT5 connect failed`. Нет ошибок импорта.

### 3.4 Разовый прогон с записью (rules-only)
```pwsh
py -3 supervisor.py --config config.yaml --once --rules-only
```
✅ В `<DataDir>/MQL5/Files/HermesFX/` появились 5 файлов `permissions_<PAIR>.json` +
   `supervisor_heartbeat.json`. На следующем H1-баре EA их прочитает и применит.

### 3.5 Полный hybrid-режим (LLM + rules floor + Opus escalation)
```pwsh
$env:OPENROUTER_API_KEY = "<твой ключ>"
py -3 supervisor.py --config config.yaml --once
```
✅ Лог: `LLM: action=... confidence=...` для каждой пары. При KILL_NEW conf<0.85 —
   `OPUS: action=...` (escalation). Safety floor: если rules дали BRAKE_HEAVY, а LLM
   ALLOW — финал `safety-floor override: LLM=ALLOW -> final=BRAKE_HEAVY`.

### 3.6 Запуск в цикле (production)
Убери `--once` — supervisor крутится, раз в `decision_interval_min` (60 мин, выровнено с
H1-баром EA) переоценивает и переписывает permissions.

**Вариант A — окно Claude Code открыто постоянно:** через cron-эквивалент (CronCreate
durable) — supervisor как scheduled prompt. Необязательно; supervisor сам по себе цикл.

**Вариант B — scheduled task Windows (AtLogon + repeating):**
```pwsh
schtasks /Create /TN "HermesFX_Supervisor" /SC ONLOGON `
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File `"<путь>\supervisor\run_supervisor.ps1`"" `
  /RL HIGHEST
```
Или запусти `run_supervisor.ps1` вручную в открытом окне PowerShell.

⚠ **Терминал Hermes FX должен быть запущен** во время цикла supervisor-а (mt5.initialize
   подключается к нему). Если терминал закрыт — supervisor упадёт на connect; restart
   терминала → restart supervisor.

---

## 4. Фаза C — Полная верификация системы

После §3.4/3.5 (supervisor пишет permissions) подожди 1 H1-бар (≤60 мин) и проверь, что
EA их применил:

1. **EA лог (Journal/Experts tab в MT5):** нет ошибок чтения permissions. Если в EA логе
   `[BRIDGE]`-сообщения — мост читается (Hermes Bridge.mqh пишет Print при изменении).
2. **permissions_<PAIR>.json содержимое** — открой, проверь:
   - `trading_enabled: true` (если не KILL), `risk_multiplier: <0.2-1.0>`,
   - `_meta.action` = то, что supervisor решил, `_meta.issued_utc` свежее.
3. **Supervisor heartbeat:**
   ```pwsh
   type <DataDir>\MQL5\Files\HermesFX\supervisor_heartbeat.json
   ```
   ✅ `status: OK`, 5 decisions, timestamp свежий (< 60 мин).
4. **EA heartbeat (alive):**
   ```pwsh
   dir <DataDir>\MQL5\Files\HermesFX\heartbeat_*.json
   ```
   ✅ 5 файлов, возраст < 5 мин = EA жив и пишет пульс.
5. **Smoke: искусственный тормоз.** Временно в `permissions_EURUSD.json` поставь
   `"risk_multiplier": 0.3` → подожди H1-бар → новый ордер EURUSD откроется лотом 0.3×
   от baseline (если в этот бар будет сигнал). В EA логе — лот уменьшился. ✅ Мост работает
   в обе стороны. После проверки — удали permissions_EURUSD.json (supervisor перепишет на
   следующем цикле) или дай supervisor-у переписать.

✅ Вся система жива: EA торгует 5 пар, supervisor читает контекст и пишет permissions, EA
   применяет тормоз/газ на каждом H1-баре.

---

## 5. Эксплуатация и мониторинг

### Что мониторить (раз в день)
- `supervisor_heartbeat.json` — status=OK, timestamp свежий.
- 5 `heartbeat_<PAIR>.json` — EA жив.
- 5 `permissions_<PAIR>.json` — `_meta.issued_utc` обновляется раз в 60 мин.
- MT5 equity / DD — supervisor должен тормозить при DD>1.5% (BRAKE_LIGHT), >4% (HEAVY).
- Если supervisor давно не тормозил и рынок спокойный — это НОРМА (ALLOW = полный газ =
  baseline). Торможение включается ТОЛЬКО при триггерах (новости/ATR/DD/сессия).

### Логи
- `supervisor/logs/supervisor.log` — все решения + причины.
- MT5 Experts tab — EA действия (OPEN/ADDON/TP_HIT/SKIP/...).

### Если supervisor упал
1. Проверь, что терминал Hermes FX запущен.
2. `py -3 supervisor.py --config config.yaml --once --rules-only` — разовый прогон,
   посмотри ошибку.
3. При сбое supervisor НЕ снимает тормоз автоматически — последние permissions_<PAIR>.json
   остаются. Если supervisor лежал долго, а там `trading_enabled: false` (KILL) —
   либо почини supervisor, либо удали stale permissions-файлы (EA → permissive = полный газ).

---

## 6. Безопасные границы (ЧТО НЕ ДЕЛАТЬ)

1. **НЕ трогать терминал <TERMINAL_ID_XAU>** (account <ACCOUNT_XAU>, XAU autonomous trader). Всё
   Hermes-FX — в отдельном терминале/счёте.
2. **НЕ закрывать позиции через supervisor.** Мост только стопает новые входы/тормозит
   лот/блокирует сторону. Позиции доходят до виртуального TP. Закрытие = eject, не тормоз.
3. **НЕ поднимать risk_multiplier >1.0.** Мост не даст (инвариант Bridge.mqh: только
   сужает). Baseline = валидированный edge; >1 = риск профиля без доказательства.
4. **НЕ отключать safety floor.** rules.py ВСЕГДА跑 первым; LLM только добавляет тормоз в
   серой зоне, не снимает критическое rules-решение. Не правь `_merge_safety` в сторону
   «LLM может ослабить».
5. **НЕ запускать supervisor без проверки `mt5_data_path`.** null = default терминал —
   если XAU trader запущен, supervisor подключится к нему и будет читать чужие позиции
   (magic не совпадут → пустые state, но всё равно НЕЛЬЗЯ путать терминалы).
6. **НЕ править Bridge.mqh инвариант** (constrictive-only) без рекомпиляции + backtest
   smoke (что edge цел — tester skip ReadPermissions, но проверять обязательно).
7. **НЕ деплоить EURGBP.** Regime-сдвиг 2026.05-08, 7/8 конфиг FAIL на holdout.
8. **Перекомпиляция EA — только в data dir терминала Hermes FX.** НЕ в <TERMINAL_ID_XAU>.

---

## 7. Быстрая справка команд

```pwsh
# --- supervisor ---
# валидация формата (всегда перед запуском)
py -3 supervisor/test_format.py

# dry-run rules-only (без API, без записи — безопасная проверка)
py -3 supervisor/supervisor.py --config supervisor/config.yaml --once --dry-run --rules-only

# разовый rules-only (пишет permissions, 0 API cost)
py -3 supervisor/supervisor.py --config supervisor/config.yaml --once --rules-only

# разовый hybrid (LLM + rules + Opus escalation)
$env:OPENROUTER_API_KEY = "<key>"
py -3 supervisor/supervisor.py --config supervisor/config.yaml --once

# цикл (production, раз в 60 мин) — без --once
py -3 supervisor/supervisor.py --config supervisor/config.yaml
# или через launcher:
powershell -File supervisor/run_supervisor.ps1 -Config supervisor/config.yaml

# --- проверка состояния моста ---
dir <DataDir>\MQL5\Files\HermesFX\heartbeat_*.json      # EA alive
dir <DataDir>\MQL5\Files\HermesFX\permissions_*.json    # supervisor wrote
type <DataDir>\MQL5\Files\HermesFX\supervisor_heartbeat.json

# --- компиляция EA (если правил исходник) ---
& "<MetaEditor>\MetaEditor64.exe" /compile:"<DataDir>\MQL5\Experts\Hermes_FX\Hermes_FX.mq5" /log
# проверить: 0 errors, 0 warnings в логе
```

---

## 8. Действия supervisor (справка)

| Action | risk_mult | trading | direction | когда (пример) |
|--------|-----------|---------|-----------|----------------|
| ALLOW | 1.0 | true | обе | calm, нет триггеров = полный газ (baseline) |
| BRAKE_LIGHT | 0.6 | true | обе | DD 1.5-2.5%, session-open+ATR |
| BRAKE_MODERATE | 0.4 | true | обе | DD 2.5-4%, medium-news кластер, импульс D1 |
| BRAKE_HEAVY | 0.2 | true | обе | DD 4-6%, ATR D1 >2× среднего 30д |
| LONG_ONLY | 1.0 | true | long | H4+D1 бычий + RSI D1>70 + есть SELL-позиции |
| SHORT_ONLY | 1.0 | true | short | H4+D1 медвежий + RSI D1<30 + есть BUY-позиции |
| KILL_NEW | 1.0 | **false** | — | DD≥6%, margin<200%, high-impact новость 60мин |

Все действия — constrictive-only. Позиции не закрываются. >1.0 лот недоступен.

---

## 9. Если что-то сломалось — triage

| Симптом | Причина | Действие |
|---------|---------|----------|
| `MT5 connect failed` | терминал Hermes FX не запущен / неверный mt5_data_path | запусти терминал, проверь config.yaml |
| heartbeat_*.json не появляются | EA не пишет мост (EnableBridge=0 / BridgeFolder≠HermesFX) | проверь .set, перезагрузи EA на чарте |
| test_format.py FAIL | test-парсер рассинхронизирован с models.py | почини test_format.py, не запускай supervisor |
| supervisor пишет permissions, EA не реагирует | EA не на H1-баре ещё, или permissions в чужой папке | проверь bridge.folder = EA's MQL5\Files\HermesFX; подожди H1-бар |
| Все 5 пар в KILL_NEW постоянно | высоко-impact новость / DD≥6% / margin<200% / ATR-burst | это safety floor РАБОТАЕТ; проверь что триггер реален (новость в календаре) |
| LLM ошибки → fallback to rules | OpenRouter API сбой / неверный ключ | supervisor автоматически падает на rules; проверь OPENROUTER_API_KEY |
| LO trades на паре, хотя supervisor ALLOW | ALLOW = полный газ = baseline (это НОРМА) | ALLOW ≠ ошибка; тормоз только при триггерах |

---

## 10. Итоговый чек-лист деплоя

- [ ] §1: deps OK, OpenRouter key (или --rules-only)
- [ ] §2.1: EA скопирован в `<DataDir>/MQL5/Experts/Hermes_FX/`, виден в Navigator
- [ ] §2.2: 5 чартов H1 прикреплены, 5 .set загружены, EnableBridge=1, EnableRiskBudget=1
- [ ] §2.3: AutoTrading ON, 5 смайликов 🙂
- [ ] §2.4: 5 heartbeat_*.json появляются
- [ ] §3.1: config.yaml — bridge.folder + mt5_data_path указывают на Hermes FX терминал
- [ ] §3.2: test_format.py → ALL 7 CASES PASS
- [ ] §3.3: dry-run --rules-only → 5 решений, нет ошибок
- [ ] §3.4/3.5: --once → 5 permissions_*.json написаны
- [ ] §4: после H1-бара EA применяет (smoke: risk_multiplier 0.3 → лот уменьшился)
- [ ] §3.6: цикл запущен (scheduled task или открытое окно)
- [ ] §6: <TERMINAL_ID_XAU> не тронут, EURGBP не деплоится, инвариант constrictive-only соблюдён

✅ Система в production: 5 пар торгуют валидированный edge, AI supervisor тормозит/газует
по внешнему контексту, safety floor держит критические режимы.