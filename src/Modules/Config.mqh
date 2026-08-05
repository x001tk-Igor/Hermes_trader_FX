//+------------------------------------------------------------------+
//|                                                       Config.mqh |
//|  Входные параметры Hermes FX.                                    |
//|                                                                  |
//|  ДИСЦИПЛИНА ИМЁН. Оптимизацию проводят внешние ИИ-агенты через    |
//|  .set-файлы, а не человек глазами. Поэтому имена сгруппированы    |
//|  префиксом тактики (C1_, S6_...) — агент отбирает параметры       |
//|  одной тактики регуляркой, не зная семантики. Общие параметры     |
//|  без префикса. Переименование параметра ломает все ранее          |
//|  собранные .set — менять только с явной причиной.                |
//+------------------------------------------------------------------+
#property strict

//=== РЕЖИМ РАБОТЫ ==================================================
input group "=== РЕЖИМ ==="
input int    MagicBase              = 77000;   // База magic (тактика = база + её код)
input ENUM_TACTIC SoloTactic        = TACTIC_NONE; // ОДНА тактика (перекрывает выключатели ниже)
input bool   IndependentMode        = false;   // Независимый режим: каждая тактика как отдельный советник
input bool   EnableRiskBudget       = true;    // Бюджет риска (выключать ТОЛЬКО для одиночных прогонов)
input int    PollSeconds            = 5;       // Период таймера, сек
input bool   AllowBuy               = true;    // Разрешить лонги
input bool   AllowSell              = true;    // Разрешить шорты

//=== ВЫХОДЫ ========================================================
// Трейлинг по СРЕДНЕЙ цене корзины — второй механизм выхода помимо
// виртуальной цели. По умолчанию ВЫКЛЮЧЕН намеренно: включённый, он
// смешивает два эффекта в одном замере, и вклад усреднения станет
// неотделим от вклада трейлинга. Включается отдельным прогоном.
input group "=== ВЫХОДЫ ==="
input bool   EnableAvgTrailing      = false;   // Трейлинг по средней цене корзины
input bool   TrailOnlyInProfit      = true;    // Трейлить только когда корзина в плюсе
input double TrailStartATR          = 1.0;     // Запуск трейлинга: прибыль от средней, ATR
input double TrailDistanceATR       = 0.5;     // Дистанция трейлинга от цены, ATR
input double BrokerCommission       = 7.0;     // Комиссия за лот в одну сторону (для честного безубытка)
input bool   CloseAllFriday         = false;   // Закрывать всё в пятницу
input int    FridayCloseHourUTC     = 19;      // Час закрытия в пятницу, UTC

//=== БЮДЖЕТ РИСКА ==================================================
// Связывающий лимит — ДЕНЬГИ, а не число позиций.
//
// Причина в арифметике. Полный выбой одной корзины из 3 позиций по
// формуле ТЗ стоит ~1.25% депозита. Двенадцать тактик, открывших
// свои корзины на одном символе, дают 15%; на трёх символах — 45%
// при заявленной максимальной просадке 5%. Счётчик позиций такого
// не ловит, бюджет ловит по построению.
input group "=== БЮДЖЕТ РИСКА ==="
input double MaxPortfolioRiskPct    = 5.0;     // Макс. риск всего портфеля при одновременном выбое, %
input double MaxSymbolRiskPct       = 2.5;     // Макс. риск на символ, %
input double BasketRiskPct          = 1.25;    // Целевой риск одной корзины, %
input int    MaxBasketsPerSymbol    = 3;       // Макс. корзин на символ (0 = без лимита, ограничивает только бюджет)
input double MinLot                 = 0.01;    // Минимальный лот (меньше — пропуск входа)

//=== ДВИЖОК КОРЗИНЫ (перенос из Setura_M1_V5) ======================
input group "=== КОРЗИНА И УСРЕДНЕНИЕ ==="
input bool   EnableAveraging        = true;    // Усреднение (ВОРОТА Ф5: гонять A/B с ним и без)
input int    MaxOrdersPerBasket     = 3;       // Глубина корзины: 1 main + (N-1) доливок
input double AddonStepATR           = 1.0;     // Шаг доливки в ATR от входа (1.0 -> уровни 1x, 2x, 3x...)
input double AddonStepMultiplier    = 1.0;     // Множитель шага для каждой следующей доливки (1.0 = равномерно)
input double SL_ATR_Mult            = 2.5;     // Стоп каждой позиции, ATR
input double TP_ATR_Mult            = 0.5;     // Цель корзины от средневзвешенной, ATR
input bool   StopAddonsOnTrendFlip  = true;    // Прекратить долив при развороте тренда
input double SymbolDDStopPct        = 2.5;     // Аварийное закрытие символа при просадке, % (0 = выкл)
input int    MaxBarsInTrade         = 72;      // Таймаут корзины, баров (0 = выкл)

//=== ОБЩИЕ ФИЛЬТРЫ =================================================
input group "=== ФИЛЬТРЫ ==="
input int    ATR_Period             = 14;      // Период ATR
input double ATR_AnomalyPct         = 5.0;     // ATR больше % цены -> вход запрещён
input int    MaxSpreadPoints        = 0;       // Макс. спред в пунктах (0 = не ограничивать)
input int    CooldownBars           = 2;       // Пауза после закрытия корзины, баров
input int    TradeStartHourUTC      = 5;       // Начало торгового окна, UTC
input int    TradeEndHourUTC        = 20;      // Конец торгового окна, UTC
input bool   CloseAllAtWindowEnd    = false;   // Закрывать всё в конце окна

//=== ВЫКЛЮЧАТЕЛИ ТАКТИК ============================================
// Каждая включается независимо: так гоняются одиночные прогоны,
// на которых и проверяется наличие эджа у самой тактики.
input group "=== ТАКТИКИ ==="
input bool   Use_C1_TrendPullback   = true;    // C1 Trend Pullback
input bool   Use_C2_RangeReversion  = true;    // C2 Range Reversion
input bool   Use_C3_RSI_BB          = false;   // C3 RSI+Bollinger
input bool   Use_C4_LiquiditySweep  = false;   // C4 Liquidity Sweep
input bool   Use_S1_EMA_VWAP        = false;   // S1 EMA9 x VWAP
input bool   Use_S2_DualMode        = false;   // S2 Dual Mode
input bool   Use_S3_UTBot_ADX       = false;   // S3 200EMA+UTBot+ADX
input bool   Use_S4_MadCharts       = false;   // S4 MadCharts Baseline
input bool   Use_S5_UTBot_STC       = false;   // S5 UTBot+STC
input bool   Use_S6_NY_ORB          = true;    // S6 NY Opening Range
input bool   Use_S7_GateBreaker     = true;    // S7 Gate Breaker
input bool   Use_S8_SmartTrend      = false;   // S8 Smart Trend

//=== ПАРАМЕТРЫ ТАКТИК ==============================================
input group "=== C1 Trend Pullback ==="
input int    C1_EmaFast             = 20;
input int    C1_EmaSlow             = 200;
input double C1_PullbackZoneATR     = 0.5;
input int    C1_AdxMin              = 20;
input double C1_MinBodyATR          = 0.2;
input double C1_PinWickRatio        = 2.0;

input group "=== C2 Range Reversion ==="
input int    C2_AdxMax              = 20;
input int    C2_RangeLookback       = 20;
input double C2_RangeMaxATR         = 4.0;
input int    C2_BoundaryTestMin     = 2;
input double C2_BoundaryProximityATR= 0.3;
input double C2_RejectionWickRatio  = 1.5;

input group "=== S6 NY Opening Range ==="
input int    S6_OR_StartHourUTC     = 13;
input int    S6_OR_EndHourUTC       = 14;
input int    S6_EntryEndHourUTC     = 16;
input double S6_CompressionMaxATR   = 2.5;
input double S6_VolumeMult          = 1.5;
input int    S6_VolumeLookback      = 20;
input bool   S6_OneEntryPerDay      = true;

input group "=== S7 Gate Breaker ==="
input int    S7_TokyoStartHourUTC   = 0;
input int    S7_TokyoEndHourUTC     = 6;
input int    S7_LondonStartHourUTC  = 7;
input int    S7_LondonEndHourUTC    = 16;
input bool   S7_BodyBreakRequired   = true;
input bool   S7_OneEntryPerDay      = true;

//=== МОСТ К УПРАВЛЯЮЩЕМУ ===========================================
// ВАЖНО: в тестере стратегий управляющего НЕТ. Советник обязан
// работать автономно при отсутствии файлов — иначе оптимизации,
// ради которой всё строится, не будет вовсе.
//
// Отсюда инвариант: разрешения только СУЖАЮТ то, что советник и так
// готов сделать, и никогда не расширяют. Нет файла = ничего не сужаем.
input group "=== МОСТ К УПРАВЛЯЮЩЕМУ ==="
input bool   EnableBridge           = true;    // Читать permissions, писать журнал и пульс
input string BridgeFolder           = "HermesFX"; // Папка внутри MQL5\Files
input int    JournalFlushSeconds    = 30;      // Как часто сбрасывать журнал на диск

//=== ОТЛАДКА =======================================================
input group "=== ОТЛАДКА ==="
input bool   VerboseLog             = false;   // Подробный лог (в тестере тормозит)
input bool   LogSkips                = true;   // Писать отказы в журнал

//+------------------------------------------------------------------+
//| magic конкретной тактики.                                        |
//+------------------------------------------------------------------+
int TacticMagic(const ENUM_TACTIC t)
{
   if(t == TACTIC_NONE) return(0);
   return(MagicBase + (int)t);
}

//+------------------------------------------------------------------+
//| Включена ли тактика параметрами.                                 |
//|                                                                  |
//| SoloTactic ПЕРЕКРЫВАЕТ все выключатели. Заведено ради партийных   |
//| прогонов: выставлять двенадцать булевых значений перед каждым     |
//| одиночным тестом — гарантированная ошибка, и ошибка МОЛЧАЛИВАЯ:   |
//| прогон «одной тактики» окажется прогоном двух, а отчёт об этом    |
//| не скажет. Одно поле вместо двенадцати такую ошибку исключает.    |
//+------------------------------------------------------------------+
bool TacticEnabled(const ENUM_TACTIC t)
{
   if(SoloTactic != TACTIC_NONE) return(t == SoloTactic);

   switch(t)
   {
      case TACTIC_C1: return(Use_C1_TrendPullback);
      case TACTIC_C2: return(Use_C2_RangeReversion);
      case TACTIC_C3: return(Use_C3_RSI_BB);
      case TACTIC_C4: return(Use_C4_LiquiditySweep);
      case TACTIC_S1: return(Use_S1_EMA_VWAP);
      case TACTIC_S2: return(Use_S2_DualMode);
      case TACTIC_S3: return(Use_S3_UTBot_ADX);
      case TACTIC_S4: return(Use_S4_MadCharts);
      case TACTIC_S5: return(Use_S5_UTBot_STC);
      case TACTIC_S6: return(Use_S6_NY_ORB);
      case TACTIC_S7: return(Use_S7_GateBreaker);
      case TACTIC_S8: return(Use_S8_SmartTrend);
   }
   return(false);
}
