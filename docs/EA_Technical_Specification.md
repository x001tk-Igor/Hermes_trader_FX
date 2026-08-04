# Техническое задание: Торговые советники для MT5

## Версия: 1.0
## Дата: 2026-08-04
## Автор: Hermes Agent (портфельный менеджер)

---

## 1. Общая архитектура

### 1.1. Платформа
- MetaTrader5 терминал (RoboForex-Pro)
- Python 3.11+ с библиотекой MetaTrader5
- Внешние процессы (Python EAs), опрашивающие MT5 через Python API
- Каждый EA — независимый процесс со своим циклом опроса

### 1.2. Инструменты
6 FX пар (XAUUSD исключён — усреднения убыточны на золоте):

| Пара | Contract | Digits | Окно UTC |
|------|----------|--------|----------|
| EURUSD | 100,000 | 5 | 05:00-20:00 |
| GBPUSD | 100,000 | 5 | 05:00-20:00 |
| USDCAD | 100,000 | 5 | 05:00-20:00 |
| EURGBP | 100,000 | 5 | 05:00-20:00 |
| NZDCAD | 100,000 | 5 | 05:00-20:00 |
| EURAUD | 100,000 | 5 | 05:00-20:00 |

### 1.3. Усреднение (общее для всех советников)

Все советники используют averaging-down систему:

| Параметр | Значение |
|----------|----------|
| Max позиций на символ | 3 (1 main + 2 addon) |
| Addon 1 | На -1.0×ATR от main entry |
| Addon 2 | На -2.0×ATR от main entry |
| SL (каждая позиция) | 2.5×ATR от своего entry |
| TP (все позиции) | weighted_avg + 0.5×ATR (пересчёт после addon) |
| DD stop | 2.5% equity per symbol → close all |
| Lot | (equity × 2.5%) / (3 × 2.5×ATR × contract) / 2 |
| Min lot | 0.01 (если меньше → пропуск) |
| ATR anomaly | ATR > 5% цены → пропуск |

### 1.4. Таймфрейм
H1 (основной). M15 — для точных триггеров (London Breakout, NY ORB).

### 1.5. Общие правила для всех EA

1. EA читает permissions.json перед каждым действием:
   - `enabled`: true/false — разрешён ли EA вообще
   - `allowed_symbols`: список разрешённых пар
   - `allowed_direction`: "long", "short", "both" — разрешённые направления
   - `max_positions`: лимит одновременных позиций
   - `risk_multiplier`: множитель риска (0.5 = половина базового лота)

2. EA читает ea_config.json для своих параметров

3. EA не открывает сделки если:
   - Symbol в blackout (новости)
   - Вне торгового окна (05:00-20:00 UTC)
   - Уже 3 инструмента открыто (портфельный лимит)
   - Permission = false

4. EA пишет в журнал каждое действие: OPEN, ADDON, CLOSE, DD_STOP, SKIP

5. EA отправляет алерт в portfolio_manager.py при:
   - Открытии сделки
   - Открытии addon
   - Закрытии сделки (TP/SL)
   - DD stop срабатывании
   - Аномалии (spread, data stale, connection lost)

---

## 2. Советник C1: Trend Pullback Continuation

### 2.1. Источник
Конституция §8.2, тактика 2. Лучшая по бэктесту: PF 2.67, +$144K, 6/6 пар.

### 2.2. Назначение
Вход по тренду после коррекции к EMA20.

### 2.3. Параметры (ea_config.json)

```json
{
  "ea_c1_trend_pullback": {
    "ema_fast": 20,
    "ema_slow": 200,
    "ema_pullback_zone_atr": 0.5,
    "atr_period": 14,
    "sl_atr_mult": 2.5,
    "tp_atr_mult": 0.5,
    "adx_min": 20,
    "rsi_long_zone": [35, 55],
    "rsi_short_zone": [45, 65],
    "min_body_atr": 0.2,
    "pin_wick_ratio": 2.0,
    "cooldown_bars": 2,
    "max_bars_in_trade": 72,
    "timeframes": ["H1"]
  }
}
```

### 2.4. Условия входа LONG

Все условия должны выполняться одновременно:

1. **Trend filter**: EMA20 > EMA200 на H1
2. **Pullback**: цена (close) находится в зоне EMA20 ± 0.5×ATR
   - ИЛИ low свечи касается EMA20
3. **Trigger** (один из):
   - Bullish candle: close > open AND body > 0.2×ATR
   - Pin bar: lower wick > 2×|body| AND close > open
   - RSI turn: RSI поворачивает вверх из зоны 35-55 (RSI[i] > RSI[i-1])
4. **ADX**: ADX(14) > 20 (тренд подтверждён)
5. **ATR filter**: ATR ≤ 5% цены (нет аномалии)

### 2.5. Условия входа SHORT

Зеркально:
1. EMA20 < EMA200
2. Цена в зоне EMA20 ± 0.5×ATR
3. Trigger: bearish candle / pin bar (upper wick) / RSI turn down из 45-65
4. ADX > 20

### 2.6. Исполнение

- Entry: close триггерной свечи
- SL: entry - 2.5×ATR (long) / entry + 2.5×ATR (short)
- TP: entry + 0.5×ATR (long) / entry - 0.5×ATR (short)
- Lot: стандартный расчёт с safety divisor /2

### 2.7. Управление позициями

- Addon 1: цена на -1.0×ATR от entry → открыть addon с тем же lot, SL = addon_entry - 2.5×ATR
- Addon 2: цена на -2.0×ATR от entry → открыть addon
- После addon: пересчёт TP = weighted_avg + 0.5×ATR для всех позиций
- Time stop: 72 H1 бара (3 дня) без TP/SL → оценка закрытия
- Invalidation: H4 EMA20 пересекает EMA200 в обратную сторону → close all

### 2.8. Запреты

- Не входить если ADX < 20 (нет тренда)
- Не входить если ATR > 5% цены
- Не входить если уже 3 инструмента открыто
- Не входить в blackout по новостям
- Не входить вне окна 05:00-20:00 UTC
- Не входить если permission = false
- Не входить если direction запрещён permissions.json

---

## 3. Советник S1: EMA 9 + VWAP + ATR Trailing

### 3.1. Источник
TradingView, 189 лайков. PF 2.63, +$120K, 6/6 пар.

### 3.2. Назначение
Вход на пересечении EMA9 и session VWAP.

### 3.3. Параметры

```json
{
  "ea_s1_ema_vwap": {
    "ema_period": 9,
    "vwap_session_start_utc": 0,
    "atr_period": 14,
    "sl_atr_mult": 2.5,
    "tp_atr_mult": 0.5,
    "atr_anomaly_pct": 5.0,
    "cooldown_bars": 2,
    "max_bars_in_trade": 72
  }
}
```

### 3.4. Условия входа LONG

1. **Cross**: EMA9[i-1] ≤ VWAP[i-1] AND EMA9[i] > VWAP[i]
2. VWAP = session VWAP (с 00:00 UTC текущего дня)
3. **ATR filter**: ATR ≤ 5% цены

### 3.5. Условия входа SHORT

1. **Cross**: EMA9[i-1] ≥ VWAP[i-1] AND EMA9[i] < VWAP[i]

### 3.6. Исполнение и управление

- Entry: close свечи пересечения
- SL: 2.5×ATR, TP: 0.5×ATR
- Addons: стандартные (-1/-2×ATR)
- TP recalc после addon

### 3.7. Расчёт session VWAP

```
Для каждой свечи i в текущем дне (с 00:00 UTC):
  tp = (high + low + close) / 3
  cumulative_pv += tp × tick_volume
  cumulative_vol += tick_volume
VWAP = cumulative_pv / cumulative_vol
```

---

## 4. Советник S2: Gold Scalper (Dual Mode)

### 4.1. Источник
TradingView, 173 лайка. PF 2.68, +$107K, 6/6 пар.

### 4.2. Назначение
Двойной режим: RSI pullback или momentum breakout в рамках тренда EMA9/EMA18.

### 4.3. Параметры

```json
{
  "ea_s2_gold_scalper": {
    "ema_fast": 9,
    "ema_slow": 18,
    "rsi_period": 14,
    "rsi_long_threshold": 40,
    "rsi_short_threshold": 60,
    "breakout_lookback": 20,
    "atr_period": 14,
    "sl_atr_mult": 2.5,
    "tp_atr_mult": 0.5,
    "mode": "both",
    "cooldown_bars": 2,
    "max_bars_in_trade": 72
  }
}
```

### 4.4. Условия входа LONG

**Trend filter**: EMA9 > EMA18 (бычий тренд)

**Mode A — RSI Pullback**:
1. RSI(14) < 40 (перепроданность в тренде)
2. Цена выше EMA18

**Mode B — Momentum Breakout**:
1. Close > max(high[1..20]) (пробой 20-барного максимума)
2. Цена выше EMA18

### 4.5. Условия входа SHORT

**Trend filter**: EMA9 < EMA18

**Mode A**: RSI > 60, цена ниже EMA18
**Mode B**: Close < min(low[1..20]), цена ниже EMA18

### 4.6. Исполнение и управление

- Стандартные SL/TP/addons
- При срабатывании Mode A и Mode B одновременно — приоритет Mode B (momentum сильнее)

---

## 5. Советник S3: 200 EMA + UT Bot + ADX (3-Layer)

### 5.1. Источник
TradingView, 134 лайка. PF 2.60, +$46K, 6/6 пар.

### 5.2. Назначение
3-слойный фильтр: HTF тренд + UT Bot триггер + ADX сила тренда.

### 5.3. Параметры

```json
{
  "ea_s3_200ema_utbot": {
    "htf_ema_period": 200,
    "htf_timeframe": "H1",
    "ut_bot_atr_period": 2,
    "ut_bot_atr_mult": 1,
    "adx_period": 14,
    "adx_min": 25,
    "atr_period": 14,
    "sl_atr_mult": 2.5,
    "tp_atr_mult": 0.5,
    "cooldown_bars": 2,
    "max_bars_in_trade": 72
  }
}
```

### 5.4. Условия входа LONG

Все 3 слоя должны совпасть одновременно:

1. **HTF Trend**: close(H1) > EMA200(H1)
2. **UT Bot trigger**: trailing stop flip из down в up (trend[i] = 1, trend[i-1] = -1)
3. **ADX filter**: ADX(14) > 25

### 5.5. Условия входа SHORT

1. close(H1) < EMA200(H1)
2. UT Bot flip из up в down
3. ADX > 25

### 5.6. UT Bot Trailing Stop алгоритм

```
ATR_val = ATR(candles, period=2)
если i == period:
    trail = close - ATR_val × mult
    trend = 1 (up)
иначе:
    если close > trail[i-1]:
        trend = 1
        trail = max(trail[i-1], close - ATR_val × mult)
    если close < trail[i-1]:
        trend = -1
        trail = min(trail[i-1], close + ATR_val × mult)
    иначе:
        trend = trend[i-1]
        trail = trail[i-1]

Сигнал: trend[i] ≠ trend[i-1] (flip)
```

---

## 6. Советник S4: MadCharts Baseline

### 6.1. Источник
TradingView, 83 лайка. PF 3.17, +$43K, 6/6 пар.

### 6.2. Назначение
Trend pullback с baseline зоной (50 EMA / 50 SMA) и подтверждением 9/18 EMA.

### 6.3. Параметры

```json
{
  "ea_s4_madcharts": {
    "baseline_ema": 50,
    "baseline_sma": 50,
    "fast_ema1": 9,
    "fast_ema2": 18,
    "atr_period": 14,
    "sl_atr_mult": 2.5,
    "tp_atr_mult": 0.5,
    "touch_lookback_bars": 3,
    "cooldown_bars": 2,
    "max_bars_in_trade": 72
  }
}
```

### 6.4. Условия входа LONG

1. **Baseline touch**: в последние 3 свечи цена касалась зоны между 50 EMA и 50 SMA
   - low ≤ max(EMA50, SMA50) AND high ≥ min(EMA50, SMA50)
2. **Fast EMAs alignment**: EMA9 > EMA18 (оба выше baseline)
   - EMA9 > max(EMA50, SMA50) AND EMA18 > max(EMA50, SMA50)
3. **Signal candle**: close > EMA9 AND close > EMA18
4. **ATR filter**: ATR ≤ 5% цены

### 6.5. Условия входа SHORT

1. Baseline touch (те же 3 свечи)
2. EMA9 < EMA18 (оба ниже baseline)
3. Close < EMA9 AND close < EMA18

### 6.6. A/B Grading (опционально, для размера риска)

- **A setup**: все timeframes (M15, M30, H1, H4) выровнены в одном направлении → полный риск
- **B setup**: 1-2 timeframes против → половина риска
- **Запрет**: 3+ timeframes против → нет входа

---

## 7. Советник S5: UT Bot + STC + Guard Stack

### 7.1. Источник
TradingView, 80 лайков. PF 6.22, +$30K, 6/6 пар. Резерв.

### 7.2. Назначение
UT Bot триггер + Schaff Trend Cycle (RSI proxy) + 5-слойный guard stack.

### 7.3. Параметры

```json
{
  "ea_s5_utbot_stc": {
    "ut_bot_atr_period": 2,
    "ut_bot_atr_mult": 1,
    "stc_rsi_period": 14,
    "stc_long_threshold": 45,
    "stc_short_threshold": 55,
    "adx_period": 14,
    "adx_min": 20,
    "atr_period": 14,
    "candle_range_min_atr": 0.3,
    "candle_range_max_atr": 3.0,
    "volume_filter_mult": 0.8,
    "volume_lookback": 20,
    "sl_atr_mult": 2.5,
    "tp_atr_mult": 0.5,
    "cooldown_bars": 2,
    "max_bars_in_trade": 72
  }
}
```

### 7.4. Условия входа LONG

1. **UT Bot flip**: trend[i] = 1, trend[i-1] = -1
2. **STC (RSI proxy)**: RSI < 45 (oversold floor)
3. **Guard 1 — ADX**: ADX > 20
4. **Guard 2 — Candle range**: 0.3×ATR ≤ (high-low) ≤ 3.0×ATR
5. **Guard 3 — Volume**: tick_volume[i] > 0.8 × avg(volume[1..20])
6. **Guard 4 — Wick filter**: counter-wick < 50% of candle range (не толкается в сопротивление)

### 7.5. Условия входа SHORT

1. UT Bot flip: trend[i] = -1, trend[i-1] = 1
2. RSI > 55 (overbought ceiling)
3. Guards 1-4 те же

---

## 8. Советник S6: NY ORB (Opening Range Breakout)

### 8.1. Источник
TradingView, 60 лайков. PF 3.73, +$65K, 6/6 пар. Лучший PF.

### 8.2. Назначение
Пробой Opening Range в начале NY сессии с фильтрами.

### 8.3. Параметры

```json
{
  "ea_s6_ny_orb": {
    "or_start_utc": "13:00",
    "or_end_utc": "14:00",
    "entry_window_start_utc": "14:00",
    "entry_window_end_utc": "16:30",
    "hard_close_utc": "20:00",
    "compression_max_atr": 2.5,
    "regime_atr_sma_period": 20,
    "regime_atr_max_mult": 2.0,
    "volume_mult": 1.5,
    "volume_lookback": 20,
    "atr_period": 14,
    "sl_or_range_mult": 1.0,
    "tp_or_range_mult": 2.5,
    "long_only": false,
    "one_entry_per_day": true,
    "cooldown_bars": 2
  }
}
```

### 8.4. Алгоритм

1. **Build Open Range** (13:00-14:00 UTC):
   - OR_High = max(high) за все свечи в окне
   - OR_Low = min(low) за все свечи в окне
   - OR_Range = OR_High - OR_Low

2. **Compression filter**: OR_Range ≤ 2.5×ATR(14)
   - Если OR_Range > 2.5×ATR → пропуск (range слишком широкий, не пружина)

3. **Regime filter**: ATR(14) ≤ 2× ATR_SMA(20)
   - Если ATR > 2× среднего → пропуск (news spike, аномальная волатильность)

4. **Entry** (14:00-16:30 UTC):
   - LONG: close > OR_High AND tick_volume > 1.5× avg(volume[1..20])
   - SHORT: close < OR_Low AND tick_volume > 1.5× avg(volume[1..20])

5. **SL**: OR_Low (long) / OR_High (short) — на противоположной стороне OR
6. **TP**: OR_Low + 2.5×OR_Range (long) / OR_High - 2.5×OR_Range (short)
7. **Hard close**: 20:00 UTC — закрыть все позиции (no overnight)

### 8.5. Особенности

- Один вход в день (one_entry_per_day)
- Long-only режим (опционально — для золота, но мы не торгуем золото)
- Volume filter обязателен — без объёма breakout ненадёжный
- Hard close в 20:00 UTC — нет переноса через ночь

### 8.6. Интеграция с усреднениями

При использовании averaging-down:
- SL заменяется на 2.5×ATR (вместо OR_Range)
- TP заменяется на weighted_avg + 0.5×ATR
- Addons на -1/-2×ATR как обычно
- Hard close в 20:00 UTC имеет приоритет над TP

---

## 9. Советник S7: Gate Breaker (Tokyo → London)

### 9.1. Источник
TradingView, 60 лайков. PF 3.71, +$121K, 6/6 пар. Лучший по PnL.

### 9.2. Назначение
Пробой Tokyo диапазона в London сессию (body break confirmation).

### 9.3. Параметры

```json
{
  "ea_s7_gate_breaker": {
    "tokyo_start_utc": "00:00",
    "tokyo_end_utc": "06:00",
    "london_start_utc": "07:00",
    "london_end_utc": "16:00",
    "body_break_required": true,
    "one_entry_per_day": true,
    "sl_mode": "tokyo_opposite",
    "tp_atr_mult": 2.5,
    "atr_period": 14,
    "sl_atr_mult": 2.5,
    "cooldown_bars": 2,
    "max_bars_in_trade": 72
  }
}
```

### 9.4. Алгоритм

1. **Build Tokyo Range** (00:00-06:00 UTC):
   - Tokyo_High = max(high) за окно
   - Tokyo_Low = min(low) за окно

2. **London session** (07:00-16:00 UTC):
   - Ждём свечу где body закрывается выше/ниже Tokyo range

3. **Entry LONG**:
   - close > Tokyo_High (body break, не wick)
   - open ≤ Tokyo_High (свеча открылась внутри range, закрылась снаружи)

4. **Entry SHORT**:
   - close < Tokyo_Low
   - open ≥ Tokyo_Low

5. **SL**: Tokyo_Low (long) / Tokyo_High (short) — противоположная сторона range
6. **TP**: close + 2.5×ATR (long) / close - 2.5×ATR (short)
7. Один вход в день

### 9.5. Интеграция с усреднениями

- SL: 2.5×ATR (вместо Tokyo opposite, если Tokyo range > 2.5×ATR)
- TP: weighted_avg + 0.5×ATR
- Addons: стандартные

---

## 10. Советник S8: Smart Trend (BOS + ADX Rising)

### 10.1. Источник
TradingView, 190 лайков. PF 2.35, +$43K, 6/6 пар.

### 10.2. Назначение
Trend continuation на Break of Structure (BOS) с ADX rising подтверждением.

### 10.3. Параметры

```json
{
  "ea_s8_smart_trend": {
    "ema_fast": 20,
    "ema_slow": 200,
    "adx_period": 14,
    "adx_min": 20,
    "bos_lookback": 5,
    "atr_period": 14,
    "sl_atr_mult": 2.5,
    "tp_atr_mult": 0.5,
    "cooldown_bars": 2,
    "max_bars_in_trade": 72
  }
}
```

### 10.4. Условия входа LONG

1. **Trend**: EMA20 > EMA200, close > EMA20
2. **ADX rising**: ADX[i] > ADX[i-1] (тренд усиливается)
3. **BOS**: close > max(high[i-5..i-1]) (break of structure — закрытие выше последних 5 баров)
4. **ADX min**: ADX > 20

### 10.5. Условия входа SHORT

1. EMA20 < EMA200, close < EMA20
2. ADX rising
3. close < min(low[i-5..i-1])
4. ADX > 20

---

## 11. Советник C2: Range Mean Reversion

### 11.1. Источник
Конституция §8.5. PF 11.45, +$36K, 6/6 пар.

### 11.2. Назначение
Торговля от границ диапазона в боковике (ADX < 20).

### 11.3. Параметры

```json
{
  "ea_c2_range_reversion": {
    "adx_max": 20,
    "range_lookback": 20,
    "range_max_atr_mult": 4.0,
    "boundary_test_min": 2,
    "boundary_atr_proximity": 0.3,
    "rejection_wick_ratio": 1.5,
    "atr_period": 14,
    "sl_atr_mult": 2.5,
    "tp_mode": "range_mid",
    "cooldown_bars": 2,
    "max_bars_in_trade": 48
  }
}
```

### 11.4. Алгоритм

1. **Range detection**:
   - ADX(14) < 20 (range, не тренд)
   - Range_High = max(high[1..20]), Range_Low = min(low[1..20])
   - Range_Size = Range_High - Range_Low
   - Range_Size ≤ 4×ATR (не слишком широкий)

2. **Boundary test count**:
   - Upper_tests = количество свечей где high ≥ Range_High - 0.3×ATR
   - Lower_tests = количество свечей где low ≤ Range_Low + 0.3×ATR
   - Минимум 2 теста на соответствующей границе

3. **Entry LONG** (от нижней границы):
   - low ≤ Range_Low + 0.3×ATR (цена у нижней границы)
   - Rejection: lower wick > 1.5×|body| AND close > Range_Low
   - ИЛИ engulfing: close > open AND close > prev_open AND open < prev_close

4. **Entry SHORT** (от верхней границы):
   - high ≥ Range_High - 0.3×ATR
   - Rejection: upper wick > 1.5×|body| AND close < Range_High
   - ИЛИ engulfing: close < open AND close < prev_open AND open > prev_close

5. **SL**: 2.5×ATR
6. **TP**: Range_Mid = (Range_High + Range_Low) / 2

### 11.5. Особые правила

- Если диапазон пробит импульсной свечой (close за границей + body > 1.5×ATR) → немедленно закрыть позицию
- Не усреднять если диапазон пробит (addon'ы только внутри диапазона)
- Time stop: 48 баров (2 дня) — короче чем для трендовых

---

## 12. Советник C3: RSI + Bollinger Band Reversion (резерв)

### 12.1. Источник
Конституция. 98.8% WR, +$6.8K. Мало сделок.

### 12.2. Параметры

```json
{
  "ea_c3_rsi_bb": {
    "bb_period": 20,
    "bb_std": 2.0,
    "rsi_period": 14,
    "rsi_long_max": 35,
    "rsi_short_min": 65,
    "adx_max": 20,
    "atr_period": 14,
    "sl_atr_mult": 2.5,
    "tp_target": "bb_mid",
    "cooldown_bars": 2,
    "max_bars_in_trade": 48
  }
}
```

### 12.3. Условия входа LONG

1. ADX < 20 (range)
2. close < BB_lower(20, 2.0)
3. RSI < 35
4. RSI[i] > RSI[i-1] (RSI разворачивается вверх)

### 12.4. Условия входа SHORT

1. ADX < 20
2. close > BB_upper(20, 2.0)
3. RSI > 65
4. RSI[i] < RSI[i-1] (RSI разворачивается вниз)

### 12.5. TP

Middle BB (SMA20). При достижении middle BB → закрыть все позиции.

---

## 13. Советник C4: Liquidity Sweep (резерв)

### 13.1. Источник
Конституция §8.4 + BTMM. +$2.6K, 4/6 пар. Маргинальна.

### 13.2. Параметры

```json
{
  "ea_c4_liquidity_sweep": {
    "pdh_lookback_bars": 24,
    "session_lookback_bars": 8,
    "ema_trigger": 13,
    "confirmation_candles": 3,
    "confirmation_min_same_dir": 2,
    "atr_period": 14,
    "sl_atr_mult": 2.5,
    "tp_atr_mult": 0.5,
    "confluence_min": 5,
    "cooldown_bars": 4,
    "max_bars_in_trade": 24
  }
}
```

### 13.3. Условия входа LONG

1. **Sweep**: low < PDL (Previous Day Low) AND close > PDL (возврат внутрь)
   - ИЛИ: low < Session_Low AND close > Session_Low
2. **13 EMA cross**: close > EMA13 AND prev_close ≤ prev_EMA13
3. **3-candle confirmation**: минимум 2 из последних 3 свечей bullish
4. **Confluence**: минимум 5/6 факторов (см. конституцию §10.5)

### 13.4. Условия входа SHORT

1. high > PDH AND close < PDH
2. close < EMA13 AND prev_close ≥ prev_EMA13
3. Минимум 2 из 3 свечей bearish
4. Confluence ≥ 5/6

### 13.5. Особенности

- Time stop: 24 бара (1 день) — короткое окно
- Confluence ≥ 5/6 — строже чем остальные EA (обычно ≥ 4/6)
- Резервная тактика — включается только при явных sweep условиях

---

## 14. Общий формат журнала (для всех EA)

Каждое действие EA записывается в JSONL:

```json
{
  "timestamp": "2026-08-04T12:00:00Z",
  "ea_name": "ea_c1_trend_pullback",
  "action": "OPEN",
  "symbol": "EURUSD",
  "direction": "long",
  "entry": 1.15110,
  "sl": 1.14885,
  "tp": 1.15195,
  "lot": 1.30,
  "atr": 0.00085,
  "adx": 28.5,
  "regime": "TREND_UP",
  "confluence": 5,
  "ev_r": 0.35,
  "reason": "Pullback to EMA20, pin bar, ADX rising"
}
```

Действия: OPEN, ADDON, CLOSE, DD_STOP, SKIP (с причиной), TIMEOUT

---

## 15. Конфигурационные файлы

### 15.1. ea_config.json (общий)

Содержит параметры всех 12 EA в одном файле. Портфельный менеджер может обновлять параметры.

### 15.2. permissions.json

```json
{
  "ea_c1_trend_pullback": {
    "enabled": true,
    "allowed_symbols": ["EURUSD", "GBPUSD", "USDCAD", "EURGBP", "NZDCAD", "EURAUD"],
    "allowed_direction": "both",
    "max_positions": 3,
    "risk_multiplier": 1.0
  },
  "ea_s7_gate_breaker": {
    "enabled": true,
    "allowed_symbols": ["EURUSD", "GBPUSD", "USDCAD", "EURGBP", "NZDCAD", "EURAUD"],
    "allowed_direction": "both",
    "max_positions": 1,
    "risk_multiplier": 1.0
  }
}
```

Портфельный менеджер обновляет permissions.json каждый цикл:
- Запрещает направления на основе макро bias
- Отключает EA после серии убытков
- Снижает risk_multiplier при повышенной волатильности
- Ограничивает allowed_symbols при корреляции

### 15.3. risk_limits.json

```json
{
  "max_daily_loss_pct": 3.0,
  "max_weekly_loss_pct": 5.0,
  "max_dd_pct": 5.0,
  "max_instruments_open": 3,
  "max_new_entries_per_day": 8,
  "max_positions_per_symbol": 3,
  "dd_stop_pct": 2.5,
  "lot_divisor": 2,
  "sl_atr_mult": 2.5,
  "tp_atr_mult": 0.5
}
```

---

## 16. Порядок загрузки и инициализации EA

1. EA запускается как Python процесс
2. Читает ea_config.json → свои параметры
3. Читает permissions.json → свои разрешения
4. Читает risk_limits.json → глобальные лимиты
5. Подключается к MT5 терминалу
6. Запускает цикл опроса (каждые N секунд, N настраивается)
7. На каждом тике:
   a. Читает permissions (могли измениться)
   b. Проверяет gate (лимиты, окно, новости)
   c. Проверяет сигнал по своей тактике
   d. Если сигнал + разрешение → открывает сделку
   e. Управляет существующими позициями (addons, DD, TP)
   f. Пишет heartbeat в ea_heartbeat_{name}.json

---

## 17. Watchdog для EA

Каждый EA имеет свой heartbeat файл: `ea_heartbeat_{name}.json`

```json
{
  "ts": "2026-08-04T12:00:00Z",
  "tick": 360,
  "pid": 12345,
  "walls_checked": true,
  "positions": 2,
  "equity": 88776.08,
  "last_action": "ADDON EURUSD @ 1.15025",
  "errors": []
}
```

Portfolio Manager watchdog проверяет все heartbeat файлы каждые 5 минут. Если EA завис/упал — перезапускает.