---
name: xau-ai-trader
description: "Use when running the autonomous intraday AI trader on MetaTrader5 — the recurring cron trade cycle during the 07:00–20:00 UTC window, or when the user asks to run a trade cycle / check the gold trader / manage an open position. Enforces the gold trading constitution (risk 0.25%/trade, daily loss 1%, weekly 2.5%, max DD 5%, 1 active position, EV≥+0.25R after costs, RR≥1.5, confluence≥4/6, news blackouts, spread limits). MULTI-INSTRUMENT: XAUUSD/USDJPY/USDCAD/GBPJPY→TREND, EURUSD→COUNTER (assigned by yearly backtest). Filters A (sweep vs breakout) + B (SL vs noise). Executed via trade.py with --terminal. NOT for other FX accounts (separate skill stack)."
---

# xau-ai-trader — автономный ИИ-трейдер по золоту (XAUUSD)

Торговая конституция (полный регламент, источник истины):
`constitution/Qwen_markdown_Ai_trader_XAU.md` (внутри проекта)
Выжимка хард-чисел — `tools/hard_limits.md`. При конфликте полный регламент старше.

## Счёт и терминал (см. `tools/env.md`)
- MT5 login **YOUR_MT5_LOGIN** (set in .env), RoboForex-Pro, USD, плечо 1:1000
- Терминал: **non-`_BIN`** install → data-dir hash `5FFA568149E88FCD5B44D926DCFEAA79`,
  exe `C:\Program Files\RoboForex MT5 Terminal\terminal64.exe`
- `account_info().trade_mode == 0` (сервер пишет REAL), **но пользователь подтвердил:
  это demo/бумажные деньги**. Торгую по полной риск-конституции; на статус не снижаю.
- **Инструменты и назначенные режимы (годовой backtest):**
  XAUUSD→TREND, EURUSD→COUNTER, USDJPY→TREND, USDCAD→TREND, GBPJPY→TREND
  TREND тактики: London Breakout, Trend Pullback, NY Macro
  COUNTER тактики: Liquidity Sweep Reversal, Range Mean Reversion
  (EURUSD — единственный counter-trend, PF 1.03 vs 0.86 trend)
- trade.py: `py -3 tools/trade.py <cmd> --terminal "$MT5_TERMINAL_PATH"`
  (trade.py теперь в tools/ — самодостаточный проект, не зависит от внешних skills)
- **ТОЛЬКО счёт из .env. Другие счета и их cron/скиллы НЕ трогать.**

## ⚠️ Два жёстких факта (урок 2026-07-24, больше не повторять)
1. **Крон — в ЛОКАЛЬНОМ времени машины. Машина в UTC** (Windows TimeZoneKeyName="UTC",
   `date -u` == `date`). Поэтому cron-поля пишутся в UTC напрямую: цикл
   `1,16,31,46 7-19`, pre-market `33 6`, report `33 20`. НИКОГДА не пиши cron в MSK
   (UTC+3) — будет сдвиг 3 часа и система промахнётся мимо окна.
2. **Крон стреляет ТОЛЬКО пока процесс Claude Code открыт и простаивает.** Это не
   OS-демон. Закрыл терминал → уснул, recurring НЕ добивает пропущенные слоты. Поэтому:
   - терминал должен быть открыт в торговые часы;
   - **на ЛЮБОМ запуске** (user msg ИЛИ cron fire) ПЕРВЫМ делом — resume-шаг 0 ниже.

## Шаг 0. Resume — на любом запуске, НЕ ждать слота
При ЛЮБОМ вызове скилла (пользователь написал / сработал крон / новый сеанс):
1. `py -3 tools/state.py gate` немедленно.
2. Если `NEW_TRADES_OK` и в окне 07:00–20:00 UTC → выполни полный цикл loop.md СЕЙЧАС
   (ловит пропущенные из-за того, что терминал был закрыт между слотами).
3. Если `FORCE_FLAT` → закрой всё + alert. Если `HALT_NEW` → только управление.
4. `CronList` раз в сессию: если кроны `2a43235f`/`51f7df66`/`20365e9e` пропали или
   близки к 7-дн экспайру — пересоздай durable (см. `tools/cron_template.txt`).
Потом — обычный цикл.

## Цикл (см. `tools/loop.md` — детально)
Каждый fire cron выполняет по порядку:
1. **Window gate** — `tools/state.py window`. Вне 07:00–20:00 UTC (или пятница после
   19:00 для новых входов / 19:30 для закрытия) → НЕТ новых сделок, только управление.
2. **Hard-limit gate** — `tools/state.py gate` (daily loss<1%, DD<5%, weekly<2.5%, нет
   открытой XAUUSD-позиции, ≤4 сделки/день, маржа). Любой пробой → halt новых.
3. **Calendar blackout** — `tools/calendar.py today`. Попал в окно high-impact → halt новых.
4. **Perceive** — `tools/state.py market` (tick/spread/regime inputs: bid/ask, spread,
   ATR-прокси через M15 свечи, DXY/10Y через web при необходимости).
5. **Regime + bias** — модель определяет режим (§6) и дневной bias (§7).
6. **Setup scan** — одна из 6 тактик (§8). Нет тактики → пропуск.
7. **Score** — Confluence 6-факторно (§10 шаг 5), EV/RR (§10 шаг 6, формула в
   `tools/position_size.py --ev`). A-сетап 5–6, B 4, <4 → запрет.
8. **Size** — `tools/position_size.py` (§11). Округление вниз до 0.01; <min → SKIP.
9. **Execute** — `trade.py open --symbol XAUUSD --side ... --lot ... --sl ... --tp ...`
   на хеше 5FFA5681…, `magic=0 comment=""` (внешний вид ручной сделки). Подтвердить
   ticket + fill (§no-fake-checkmarks). SL/TP — отдельной `sltp` если open без стопов.
10. **Manage** — для открытой позиции: частичная фиксация, BE, трейл, time stop,
    invalidation (§12). Управление разрешено ВНЕ окна.
11. **Journal** — `tools/journal.py add` (§16.1 поля). Пропуск названного сетапа тоже
    логируется. `tools/journal.py stats` — дневная статистика + gate-вердикт.

## Уведомления (выбор пользователя)
Дневной отчёт + тревоги ТОЛЬКО при: нарушении лимитов (0.5/1.0% daily, 3/4/5% DD,
2.5% weekly), аномалии спреда/данных/исполнения, геополитическом/макро-шоке,
деградации тактики, требовании изменить конституцию. Не докладывать про каждую сделку.

## Каданс (cron-поля в UTC — машина в UTC, НЕ MSK)
- цикл: `1,16,31,46 7-19 * * 1-5` (id `d1922ccf2838`) = 07:01–19:46 UTC
  (через 1 мин после закрытия M15 бара — анализируем закрытый бар, не формирующийся)
- pre-market: `33 6 * * 1-5` (id `bc6938631323`) = 06:33 UTC
- daily report: `33 20 * * 1-5` (id `a805ec0838f1`) = 20:33 UTC
Все durable, recurring, ⚠️ авто-экспайр 7 дней → self-heal в pre-market cron + шаг 0.
Шаблон пересоздания: `tools/cron_template.txt`.

## Запрещено (§19) — неполный список, полный в регламенте
Без SL • убирать/отодвигать SL • martingale • grid • усреднение убытка • >0.25%/сделку
• другой инструмент (не из REGIMES) • торговать инструмент в режиме, не присвоенном ему •
смешивать trend/counter-trend на одном инструменте • перенос через выходные •
торговля перед high-impact news • торговля без EV • увеличивать риск ради отыгрыша •
менять конституцию без разрешения.

## End-of-session
Спросить: что правил руками/объяснял дважды → вынести в `tools/` (скрипт) или
`tools/hard_limits.md`/`env.md` (факт), не в SKILL.md-прозу.