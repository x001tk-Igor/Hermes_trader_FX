# Техническое задание: Портфельный менеджер (Управляющий)

## Версия: 1.0
## Дата: 2026-08-04
## Роль: Hermes Agent — портфельный менеджер над 12 торговыми советниками

---

## 1. Общая архитектура

### 1.1. Роль

Портфельный менеджер (далее PM) — это ИИ-агент (Hermes), который работает поверх 12 автономных торговых советников (EA). EA торгуют по механическим правилам. PM не заменяет EA — он управляет ими: разрешает, запрещает, ограничивает, мониторит, корректирует и сообщает.

### 1.2. Принцип разделения

| Компонент | Что делает | Что НЕ делает |
|-----------|-----------|---------------|
| EA | Определяет сигнал, открывает/закрывает позиции, управляет addon'ами | Оценивает макро, определяет режим, считает корреляцию |
| PM | Оценивает макро, определяет режим, управляет разрешениями, контролирует риск, сообщает | Не открывает позиции напрямую (кроме аварийных закрытий) |
| Watchdog | Следит за живостью EA и PM, перезапускает при сбое | Не торгует, не принимает решений |

### 1.3. Каданс работы PM

- **Каждый час** (на :00 UTC, 05:00-20:00): полный цикл управления
- **Каждые 5 минут**: watchdog проверка EA heartbeats
- **Непрерывно**: приём алертов от EA (через sensor/heartbeat)
- **По событию**: аварийное реагирование (DD stop, аномалия, сбой)

---

## 2. Функция 1: РИСК-МЕНЕДЖМЕНТ ПОРТФЕЛЯ

### 2.1. Глобальные лимиты

PM устанавливает и контролирует:

| Параметр | Значение | Действие при нарушении |
|----------|----------|----------------------|
| Daily loss | 3% equity | HALT_ALL — отключить все EA, закрыть опционально |
| Weekly loss | 5% equity | HALT_ALL до конца недели |
| Max DD from peak | 5% | FORCE_FLAT — закрыть все позиции |
| Max instruments open | 3 (без addons) | BLOCK_NEW — запретить новые входы |
| Max new entries/day | 8 | BLOCK_NEW до конца дня |
| Max positions/symbol | 3 | BLOCK_NEW для этого символа |
| DD stop per symbol | 2.5% equity | CLOSE_SYMBOL — закрыть все позиции по символу |

### 2.2. Распределение риска между EA

PM распределяет риск через `risk_multiplier` в permissions.json:

- **Нормальный режим**: все EA risk_multiplier=1.0
- **Повышенная волатильность** (ATR > 2× 20-bar SMA): risk_multiplier=0.5 для всех EA
- **После убытка**: если портфель -1.5% за день → risk_multiplier=0.5 для всех EA
- **После серии убытков EA**: если конкретный EA дал 3 убытка подряд → risk_multiplier=0.25
- **Восстановление**: если EA даёт 2 прибыли подряд после снижения → risk_multiplier возвращается к 1.0

### 2.3. Корреляционный контроль

PM проверяет корреляцию перед разрешением новых входов:

- Вычисляет корреляцию дневных log-returns для всех 6 пар
- Если 2 пары с корреляцией > 0.7 оба хотят вход в одну сторону → разрешает только тот EA, у которого выше confluence
- Пример: EURUSD long и EURGBP long коррелированы (EUR компонент) → разрешает только один
- Обновляет матрицу корреляции еженедельно

### 2.4. Кильватерная балансировка (drawdown ladder)

| Портфель DD | Действие |
|------------|---------|
| 0-1% | Нормальный риск (multiplier=1.0) |
| 1-2% | Снижение риска (multiplier=0.5) |
| 2-3% | Минимальный риск (multiplier=0.25), запрет новых инструментов |
| 3%+ | HALT_ALL — все EA отключены, позиции управляются только вручную |

---

## 3. Функция 2: РАЗРЕШЕНИЯ И ЗАПРЕТЫ (GATEKEEPER)

### 3.1. Структура permissions.json

PM обновляет этот файл каждый цикл:

```json
{
  "global": {
    "trading_enabled": true,
    "risk_multiplier": 1.0,
    "max_instruments_open": 3,
    "blocked_symbols": [],
    "blocked_directions": {}
  },
  "ea_c1_trend_pullback": {
    "enabled": true,
    "allowed_symbols": ["EURUSD", "GBPUSD", "USDCAD", "EURGBP", "NZDCAD", "EURAUD"],
    "allowed_direction": "both",
    "risk_multiplier": 1.0,
    "reason": "Trend regime, all pairs allowed"
  },
  "ea_s7_gate_breaker": {
    "enabled": true,
    "allowed_symbols": ["EURUSD", "GBPUSD"],
    "allowed_direction": "long",
    "risk_multiplier": 1.0,
    "reason": "London session, DXY falling → long bias for EUR/GBP"
  },
  "ea_c2_range_reversion": {
    "enabled": false,
    "reason": "ADX > 25 on all pairs, no range conditions"
  }
}
```

### 3.2. Типы запретов

| Тип | Пример | Источник |
|-----|--------|---------|
| Запрет EA | "Range Reversion отключён — все пары в тренде" | Режим рынка |
| Запрет символа | "USDCAD заблокирован — ISM PMI через 30 мин" | Календарь новостей |
| Запрет направления | "Long EURUSD запрещён — DXY растёт" | Макро bias |
| Запрет сессии | "Новые входы запрещены — Friday 19:00 UTC" | Временные правила |
| Запрет инструмента | "Уже 3 инструмента открыто" | Портфельный лимит |
| Запрет risk | "Risk multiplier 0.5 — портфель DD 1.5%" | Drawdown ladder |

### 3.3. Приоритет запретов

1. Force Flat (DD > 5%) → закрывает всё, блокирует все EA
2. Daily loss > 3% → блокирует все EA
3. News blackout → блокирует конкретные символы
4. Macro bias → блокирует направления
5. Portfolio limits → блокирует новые инструменты
6. EA-specific → блокирует конкретный EA

---

## 4. Функция 3: МАКРО-КОНТЕКСТ И РЕГИМОВЫЙ НАДЗОР

### 4.1. Ежедневный макро-брифинг (05:00 UTC)

PM формирует макро-карту каждый день:

```
МАКРО-БРИФИНГ 2026-08-04

DXY: 104.25, тренд ↓ (падение 3 дня)
US 10Y: 3.85%, тренд ↓
Risk sentiment: Risk-on (S&P futures +0.5%, VIX 12.3)
Сессия: London открытие

BIAS по парам:
  EURUSD: bullish (DXY ↓, EUR сильный)
  GBPUSD: bullish (DXY ↓, GBP сильный)
  USDCAD: bearish (DXY ↓ → CAD strong, USDCAD ↓)
  EURGBP: neutral (EUR и GBP оба сильные)
  NZDCAD: bullish (risk-on → NZD strong)
  EURAUD: neutral (risk-on → AUD strong, EUR strong)

РЕЖИМ: TREND (ADX > 25 на 4/6 пар)
АКТИВНЫЕ EA: C1, S1, S2, S3, S4, S8 (trend)
ПАУЗА: C2, C3 (range — ADX высокий)
РЕЗЕРВ: S5, C4, S6 (NY session), S7 (London breakout)
```

### 4.2. Источники макро-данных

| Данные | Источник | Частота |
|--------|---------|---------|
| DXY | Yahoo Finance (DX-Y.NYB) | Каждый цикл |
| US 10Y yield | Yahoo Finance (^TNX) | Каждый цикл |
| VIX | Yahoo Finance (^VIX) | Каждый цикл |
| S&P 500 | Yahoo Finance (^GSPC) | Каждый цикл |
| Экономический календарь | ForexFactory API | Ежедневно + проверка каждый цикл |
| Сессии | Внутренний расчёт (UTC) | Каждый цикл |

### 4.3. Режимный надзор

PM определяет общий режим рынка и переключает активные EA:

| Режим | ADX диапазон | Активные EA | Причина |
|-------|-------------|------------|--------|
| TREND | ADX > 25 на большинстве пар | C1, S1, S2, S3, S4, S8 | Trend tactics |
| RANGE | ADX < 20 на большинстве пар | C2, C3 | Range tactics |
| BREAKOUT | Цена пробивает key levels | S6 (NY), S7 (London) | Session breakout |
| REVERSAL | Sweep patterns | C4 | Liquidity sweep |
| UNCLEAR | ADX 20-25, mixed signals | NONE | Нет торговли |
| HIGH_VOL | ATR > 2× 20-bar SMA | All risk_multiplier=0.5 | Снижение риска |
| CRISIS | Геополитический шок, VIX > 30 | NONE | Закрыть всё |

### 4.4. Внутридневная смена режима

PM проверяет режим каждый цикл. Если режим меняется:
- TREND → RANGE: отключает trend EA, включает range EA
- RANGE → TREND: отключает range EA, включает trend EA
- Любой → UNCLEAR: отключает все EA
- Любой → CRISIS: закрывает все позиции, отключает все EA

---

## 5. Функция 4: ОПТИМИЗАЦИЯ ПАРАМЕТРОВ

### 5.1. Периодичность

- **Еженедельная оптимизация** (воскресенье): бэктест всех EA с текущими параметрами
- **Ежемесячная оптимизация**: перебор параметров, поиск оптимальных
- **По событию**: если EA даёт PF < 0.5 за неделю → внеплановая оптимизация

### 5.2. Процесс оптимизации

1. Скачать исторические данные (1 год H1) через MT5
2. Запустить бэктест с текущими параметрами → baseline
3. Перебор параметров (grid search):
   - ATR period: [10, 14, 20]
   - SL mult: [1.5, 2.0, 2.5, 3.0]
   - TP mult: [0.3, 0.5, 0.7, 1.0]
   - ADX min: [15, 20, 25, 30]
4. Для каждой комбинации: PF, WR, max DD, total PnL
5. Выбрать параметры с PF > 1.0 и max DD < 3%
6. Out-of-sample тест: последние 2 месяца с выбранными параметрами
7. Если out-of-sample PF > 0.8 → обновить ea_config.json
8. Если out-of-sample PF < 0.8 → откатиться к предыдущим параметрам

### 5.3. Защита от overfitting

- Не использовать параметры с PF > 5 на истории (подозрительно)
- Не оптимизировать под конкретную пару (one rule set for all pairs)
- Проверять на разных периодах (1 год, 6 мес, 3 мес)
- Минимум 50 сделок для валидности статистики

### 5.4. Версионирование

```json
{
  "ea_c1_trend_pullback": {
    "version": "1.2",
    "params": {...},
    "backtest": {"pf": 2.67, "wr": 90.1, "pnl": 144651, "dd": 2.1},
    "optimized_at": "2026-08-04",
    "previous_version": "1.1",
    "previous_pf": 2.45,
    "change_reason": "Monthly optimization, ATR period 14→14 (no change), SL 2.5 (kept)"
  }
}
```

---

## 6. Функция 5: МОНИТОРИНГ И ДИАГНОСТИКА

### 6.1. Real-time мониторинг EA

PM мониторит каждого EA через heartbeat файлы:

| Метрика | Источник | Порог | Действие |
|---------|---------|------|---------|
| Heartbeat age | ea_heartbeat_{name}.json | > 60 сек | Перезапуск EA |
| walls_checked | heartbeat | false | Перезапуск EA |
| Errors count | heartbeat | > 0 | Лог + анализ |
| Position count | MT5 positions | > 3 per symbol | Close excess |
| Lot size | MT5 positions | > расчётного | Close excess |
| Spread | MT5 tick | > 2× median | Block new entries |

### 6.2. Performance tracking

PM ведёт статистику по каждому EA:

| Метрика | Описание | Частота обновления |
|---------|---------|-------------------|
| Live PF | Profit factor за текущую неделю | Каждый цикл |
| Live WR | Win rate за текущую неделю | Каждый цикл |
| Backtest ratio | Live PF / Backtest PF | Еженедельно |
| Trade frequency | Сделок в день (факт vs ожидание) | Каждый цикл |
| Slippage | Средний slippage на entry/exit | Еженедельно |
| DD per EA | Макс DD по позициям этого EA | Каждый цикл |

### 6.3. Аномалии и флаги

| Аномалия | Условие | Действие PM |
|----------|--------|------------|
| EA превышает лимит | Открывает позицию вопреки permissions | Закрыть позицию, флаг, уведомить |
| EA завис | Heartbeat stale > 60 сек | Перезапуск через watchdog |
| EA не отвечает | Нет heartbeat совсем | Перезапуск, уведомить |
| Данные стухли | MT5 не отдаёт тики > 60 сек | Пауза всех EA, уведомить |
| Терминал отвалился | MT5.initialize() fails | Уведомить владельца, retry каждые 30 сек |
| Position без SL | Открытая позиция без stop loss | Восстановить SL или закрыть |
| Чужая позиция | Позиция не от нашего EA | Уведомить владельца, не трогать |

---

## 7. Функция 6: УВЕДОМЛЕНИЯ И ОТЧЁТНОСТЬ

### 7.1. Telegram alerts (мгновенные)

| Событие | Сообщение | Приоритет |
|---------|---------|----------|
| EA открыл сделку | "C1 OPEN EURUSD long @ 1.15110, SL=1.14885, lot=1.30" | Info |
| EA открыл addon | "C1 ADDON1 EURUSD @ 1.15025, TP recalculated" | Info |
| Позиция закрылась TP | "C1 EURUSD TP hit, PnL=+$285" | Info |
| Позиция закрылась SL | "C1 EURUSD SL hit, PnL=-$220" | Warning |
| DD stop сработал | "DD STOP EURUSD: closed 2 pos, PnL=-$1,234" | Critical |
| EA превысил лимит | "ANOMALY: S2 opened position despite permission=false" | Critical |
| Терминал отвалился | "CRITICAL: MT5 connection lost, all EA paused" | Critical |
| Данные стухли | "WARNING: MT5 data stale > 60s, all EA paused" | Critical |
| Daily loss близко | "WARNING: Portfolio daily loss 2.8%, approaching 3% limit" | Warning |
| Watchdog перезапустил EA | "WATCHDOG: restarted ea_c1_trend_pullback (stale heartbeat)" | Warning |

### 7.2. Часовой отчёт

Каждый час PM отправляет в Telegram:

```
PORTFOLIO REPORT 12:00 UTC
Equity: $88,776 | Daily PnL: +$135 (+0.15%) | DD: 0%
Open positions: 2/3 instruments
  EURUSD: 2 pos (C1 long), PnL=-$85
  GBPUSD: 1 pos (S7 long), PnL=+$42
Active EA: C1, S1, S2, S3, S4, S7, S8 (7 running)
Paused EA: C2, C3 (range — ADX high), C4 (no sweep)
Blocked: USDCAD long (DXY falling), NZDCAD (news 22:15)
Next events: NZD Employment 22:15 UTC
Risk: multiplier=1.0, instruments=2/3, entries=2/8
```

### 7.3. Дневной отчёт

Ежедневно в 20:00 UTC:

```
DAILY REPORT 2026-08-04
Equity: $89,120 | Day PnL: +$344 (+0.39%) | DD: 0%
Trades: 5 opened, 3 closed (2 TP, 1 SL)
Win rate: 67% | PF: 1.85

By EA:
  C1 TrendPullback: 2 trades, +$285, 100% WR
  S7 GateBreaker: 1 trade, +$120, 100% WR
  S2 GoldScalper: 1 trade, -$85, 0% WR
  C2 RangeReversion: 1 trade, +$24, 100% WR

By pair:
  EURUSD: +$285 (2 trades)
  GBPUSD: +$120 (1 trade)
  EURAUD: -$85 (1 trade)
  EURGBP: +$24 (1 trade)

Risk: max DD 0.8%, max instruments 2, daily loss never > 0.5%
Tomorrow: NZD Employment 22:15 UTC → NZDCAD blackout
```

### 7.4. Недельный отчёт

Еженедельно (воскресенье):

```
WEEKLY REPORT 2026-08-04 to 2026-08-10
Equity: $91,250 | Week PnL: +$2,551 (+2.88%) | Max DD: 1.2%

By EA performance:
  EA          | Trades | WR   | PF   | PnL     | Live/BT
  C1 Pullback | 12     | 83%  | 2.1  | +$1,200 | 0.79
  S7 GateBrkr | 5      | 80%  | 3.5  | +$850   | 0.95
  S1 EMA_VWAP | 10     | 80%  | 1.8  | +$520   | 0.68
  S2 Scalper  | 8      | 50%  | 0.9  | -$120   | 0.34 ⚠
  C2 RangeRev | 4      | 100% | inf  | +$101   | 1.20

⚠ S2 GoldScalper: Live/BT ratio 0.34 — underperforming
  Action: risk_multiplier reduced to 0.5, monitoring

Optimization: C1 params unchanged (PF stable)
              S2 needs investigation (slippage? market regime change?)
```

---

## 8. Функция 7: КОРРЕКТИРУЮЩИЕ ДЕЙСТВИЯ

### 8.1. Автоматические действия

| Ситуация | Действие | Уровень |
|----------|---------|---------|
| EA открыл сделку вопреки запрету | Закрыть позицию немедленно | Critical |
| EA превысил лимит лотов | Закрыть избыточную позицию | Critical |
| EA завис / не отвечает | Перезапуск через watchdog | Warning |
| Терминал отвалился | Retry каждые 30 сек, уведомить владельца | Critical |
| Данные стухли | Пауза всех EA (permissions global=false) | Critical |
| Позиция без SL | Восстановить SL из журнала или закрыть | Critical |
| Чужая позиция | Уведомить владельца, НЕ трогать | Warning |
| Daily loss > 3% | HALT_ALL, уведомить владельца | Critical |
| DD > 5% | FORCE_FLAT, закрыть все, уведомить | Critical |
| Spread > 2× median | Block new entries для этого символа | Info |

### 8.2. Ручные действия (по команде владельца)

| Команда | Действие |
|---------|---------|
| "Закрой все" | FORCE_FLAT, закрыть все позиции |
| "Останови EA X" | permissions: ea_X.enabled = false |
| "Запусти EA X" | permissions: ea_X.enabled = true |
| "Запрети long на EURUSD" | permissions: ea_*.allowed_direction = "short" для EURUSD |
| "Снизь риск до 0.5" | permissions: global.risk_multiplier = 0.5 |
| "Закрой символ X" | trade.py close-symbol --symbol X |
| "Отчёт" | Сформировать и отправить отчёт |
| "Пауза" | global.trading_enabled = false |
| "Продолжай" | global.trading_enabled = true |

---

## 9. Функция 8: СТРАТЕГИЧЕСКИЙ НАДЗОР

### 9.1. Переключение набора EA по режиму

PM каждый цикл определяет режим и включает/выключает EA:

```python
if regime == "TREND":
    enable_eas = ["C1", "S1", "S2", "S3", "S4", "S8"]
    disable_eas = ["C2", "C3"]
    reserve_eas = ["S6", "S7", "C4", "S5"]

elif regime == "RANGE":
    enable_eas = ["C2", "C3"]
    disable_eas = ["C1", "S1", "S2", "S3", "S4", "S8"]
    reserve_eas = ["S6", "S7", "C4", "S5"]

elif regime == "BREAKOUT":
    if session == "LONDON":
        enable_eas = ["S7"]
    elif session == "NY":
        enable_eas = ["S6"]
    disable_eas = ["C1", "S1", "S2", "S3", "S4", "S8", "C2", "C3"]
    reserve_eas = ["C4", "S5"]

elif regime == "UNCLEAR":
    disable_all_eas()

elif regime == "CRISIS":
    close_all_positions()
    disable_all_eas()
    notify_owner("CRISIS MODE: all positions closed, all EA disabled")
```

### 9.2. Волатильность-адаптивный риск

```python
current_atr = get_avg_atr(all_pairs)
atr_sma = get_atr_sma_20(all_pairs)

if current_atr > 2.0 * atr_sma:
    # Аномальная волатильность — снижаем риск
    set_global_risk_multiplier(0.5)
    notify("Volatility spike: ATR > 2x average, risk reduced to 50%")
elif current_atr < 0.5 * atr_sma:
    # Низкая волатильность — можно увеличить частоту
    # Но не риск (меньший ATR = меньший SL = тот же $ риск)
    pass
```

### 9.3. Сессионный контроль

| Сессия UTC | Разрешённые EA | Особенности |
|-----------|---------------|------------|
| 05:00-07:00 | C1, S1, S2, S3, S4, S8 | Frankfurt pre-market, низкая ликвидность |
| 07:00-10:00 | + S7 GateBreaker | London open — breakout время |
| 10:00-12:30 | C1, S1, S2, S3, S4, S8 | London mid-session |
| 12:30-16:30 | + S6 NY_ORB | NY open — ORB время |
| 16:30-19:00 | C1, S1, S2, S3, S4, S8 | NY afternoon |
| 19:00-20:00 | Management only | Friday cutoff, close all by 19:30 |

---

## 10. Функция 9: ВЕРСИОНИРОВАНИЕ И ТЕСТИРОВАНИЕ

### 10.1. Версии EA

Каждый EA имеет версию в ea_config.json:
- v1.0 — начальная версия (текущие параметры из бэктеста)
- v1.1 — minor changes (параметры)
- v2.0 — major changes (логика тактики)

### 10.2. Процесс обновления

1. PM предлагает изменения (на основе оптимизации или диагностики)
2. Бэктест с новыми параметрами → результаты
3. Out-of-sample тест → результаты
4. Если улучшение → обновить ea_config.json с новой версией
5. Paper trading 1 неделю (если major change)
6. Если paper trading подтверждает → full deploy
7. Если нет → откат к предыдущей версии

### 10.3. Журнал изменений

```
EA_VERSION_LOG:
  ea_c1_trend_pullback:
    v1.0 (2026-08-04): Initial, PF 2.67, SL=2.5xATR, TP=0.5xATR
    v1.1 (2026-08-11): Optimized ATR period 14→14 (no change), confirmed
    v1.2 (2026-08-18): Added RSI turn trigger, PF 2.67→2.45 (rollback)
    v1.1 (2026-08-18): Rolled back to v1.1

  ea_s2_gold_scalper:
    v1.0 (2026-08-04): Initial, PF 2.68, both modes
    v1.1 (2026-08-11): RSI threshold 40→35 (stricter), PF 2.68→2.90
```

---

## 11. Функция 10: ЖУРНАЛ И АУДИТ

### 11.1. Структура журнала

PM ведёт 3 журнала:

**trade_journal.jsonl** — все торговые действия EA:
```json
{"ts": "...", "ea": "C1", "action": "OPEN", "symbol": "EURUSD", "direction": "long", "entry": 1.15110, "sl": 1.14885, "tp": 1.15195, "lot": 1.30, "confluence": 5, "ev_r": 0.35, "reason": "..."}
```

**pm_journal.jsonl** — все решения PM:
```json
{"ts": "...", "action": "DISABLE_EA", "ea": "C2", "reason": "ADX > 25, no range conditions"}
{"ts": "...", "action": "BLOCK_DIRECTION", "symbol": "USDCAD", "direction": "long", "reason": "DXY falling, CAD strong"}
{"ts": "...", "action": "REDUCE_RISK", "multiplier": 0.5, "reason": "Portfolio DD 1.5%"}
{"ts": "...", "action": "FORCE_FLAT", "reason": "Daily loss 3.2%"}
```

**anomaly_journal.jsonl** — все аномалии:
```json
{"ts": "...", "type": "ea_exceeded_limit", "ea": "S2", "detail": "Opened position despite permission=false", "action_taken": "Closed position"}
{"ts": "...", "type": "data_stale", "detail": "MT5 no ticks for 90 seconds", "action_taken": "Paused all EA"}
```

### 11.2. Аудит-запросы

Владелец может в любой момент запросить:
- "Покажи все сделки за сегодня" → выгрузка trade_journal
- "Покажи все твои решения" → выгрузка pm_journal
- "Покажи аномалии" → выгрузка anomaly_journal
- "Покажи performance по EA" → сводная таблица
- "Покажи текущие permissions" → dump permissions.json

---

## 12. Функция 11: ВЗАИМОДЕЙСТВИЕ С ВЛАДЕЛЬЦЕМ

### 12.1. Каналы

- **Telegram**: алерты, отчёты, уведомления
- **CLI (эта сессия)**: команды, запросы, аудит
- **Email** (опционально): дневной/недельный отчёт

### 12.2. Типы взаимодействий

| Тип | Пример | Инициатор |
|-----|--------|----------|
| Алерт | "DD STOP EURUSD, closed 2 pos" | PM → владелец |
| Отчёт | "Дневной отчёт: +$344, 5 trades" | PM → владелец |
| Запрос | "Покажи все сделки" | Владелец → PM |
| Команда | "Останови S2" | Владелец → PM |
| Предупреждение | "S2 underperforming, recommend disable" | PM → владелец |
| Вопрос | "Почему EURUSD в убытке?" | Владелец → PM |
| Решение | "Утверди новый параметр SL=2.0" | PM → владелец → PM |

### 12.3. Эскалация

| Уровень | Когда | Кому |
|---------|------|------|
| Info | Нормальная торговля | Telegram |
| Warning | EA underperforming, spread anomaly | Telegram + CLI |
| Critical | DD stop, terminal lost, limit exceeded | Telegram + CLI + повторное уведомление через 5 мин |
| Emergency | Force flat, crisis mode | Telegram + CLI + повтор каждые 60 сек до подтверждения |

---

## 13. Функция 12: ЗАПУСК И ОСТАНОВКА

### 13.1. Утренний запуск (05:00 UTC)

1. PM проверяет MT5 соединение
2. Проверяет equity, daily loss, DD
3. Формирует макро-брифинг
4. Определяет режим рынка
5. Запускает EA согласно режиму (permissions.json)
6. Отправляет брифинг в Telegram
7. Запускает watchdog для EA

### 13.2. Вечерняя остановка (20:00 UTC)

1. Закрывает все позиции (hard close)
2. Останавливает все EA (permissions: global.trading_enabled = false)
3. Формирует дневной отчёт
4. Отправляет отчёт в Telegram
5. Сохраняет состояние (equity, peak, SOD)

### 13.3. Пятница (19:00 UTC cutoff)

1. В 19:00 UTC — запрет новых входов
2. В 19:30 UTC — закрыть все позиции
3. Остановить все EA
4. Недельный отчёт

---

## 14. Техническая реализация PM

### 14.1. Файлы

```
tools/
├── portfolio_manager.py     # Главный цикл PM
├── risk_engine.py           # Расчёт рисков, корреляции, DD
├── macro_context.py         # DXY, yields, VIX, сессии
├── permissions_manager.py   # Чтение/запись permissions.json
├── ea_monitor.py            # Мониторинг heartbeat всех EA
├── ea_watchdog.ps1          # Перезапуск EA при сбое
├── report_generator.py      # Часовые/дневные/недельные отчёты
├── trade_sensor.py          # Датчик (события, heartbeat)
├── config/
│   ├── ea_config.json       # Параметры EA
│   ├── permissions.json     # Текущие разрешения
│   ├── risk_limits.json     # Глобальные лимиты
│   └── correlation_matrix.json  # Матрица корреляции пар
├── journals/
│   ├── trade_journal.jsonl
│   ├── pm_journal.jsonl
│   └── anomaly_journal.jsonl
```

### 14.2. Главный цикл PM

```python
# portfolio_manager.py — псевдокод
def main_cycle():
    # 1. Gate
    gate = run_gate()
    if gate == "FORCE_FLAT": close_all(); return
    if gate == "HALT_NEW": manage_only = True
    else: manage_only = False

    # 2. News
    blackouts = check_calendar()

    # 3. Macro
    macro = fetch_macro()  # DXY, yields, VIX, session
    bias = form_bias(macro)

    # 4. Regime
    regime = determine_regime(bias)

    # 5. Update permissions
    permissions = build_permissions(regime, bias, blackouts, gate)
    write_permissions(permissions)

    # 6. Monitor EA
    ea_status = monitor_all_eas()

    # 7. Portfolio risk
    risk = calculate_portfolio_risk(ea_status)
    if risk.dd > 0.02: reduce_all_risk(0.5)
    if risk.daily_loss > 0.03: halt_all()

    # 8. Corrective actions
    handle_anomalies(ea_status)

    # 9. Report
    send_hourly_report(ea_status, risk, macro)

    # 10. Journal
    log_pm_decisions(permissions, risk, regime)
```

### 14.3. Запуск

PM запускается через cron с deliver='origin' (будит в текущей сессии):
- schedule: `0 5-20 * * 1-5` (каждый час 05-20 UTC, пн-пт)
- skills: xau-ai-trader
- prompt: "Выполни цикл портфельного менеджера по docs/PM_Functions.md"

EA запускаются как фоновые процессы:
- Каждый EA: `py -3 tools/eas/ea_{name}.py &`
- Watchdog: Task Scheduler каждые 5 мин, проверяет heartbeat
- Sensor: `py -3 tools/trade_sensor.py &` (события, DD stop)