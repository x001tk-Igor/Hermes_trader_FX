//+------------------------------------------------------------------+
//|                                                      Tactics.mqh |
//|  Сигнальный слой: двенадцать тактик за одним интерфейсом.        |
//|                                                                  |
//|  КОНТРАКТ ТАКТИКИ, нарушать который нельзя:                       |
//|                                                                  |
//|  1. Тактика — ЧИСТАЯ функция баров и индикаторов. Она не знает    |
//|     про открытые позиции, лоты, бюджет и разрешения. Как только   |
//|     тактика начинает смотреть на свои позиции, её нельзя          |
//|     прогнать в изоляции — а изоляция и есть единственный способ   |
//|     узнать, есть ли у неё эдж.                                    |
//|                                                                  |
//|  2. Тактика возвращает РАССТОЯНИЯ до стопа и цели, а не цены.     |
//|     Цену входа определяет исполнение (ask/bid на момент приказа), |
//|     и тактика о ней знать не должна.                              |
//|                                                                  |
//|  3. Тактика работает по ЗАКРЫТОМУ бару (shift >= 1). Обращение к  |
//|     формирующемуся бару даёт сигналы, которые в тестере есть, а   |
//|     на реале исчезают — самый дорогой класс самообмана.           |
//+------------------------------------------------------------------+
#property strict

#include "Types.mqh"
#include "Config.mqh"
#include "Indicators.mqh"

//+------------------------------------------------------------------+
//| Контекст бара, общий для всех тактик. Считается ОДИН раз за бар.  |
//+------------------------------------------------------------------+
struct BarContext
{
   string   symbol;
   datetime bar_time;
   double   atr;
   double   close;
   double   open;
   double   high;
   double   low;
   double   prev_close;
   bool     valid;
};

//+------------------------------------------------------------------+
//| Наполнить контекст по закрытому бару (shift=1).                  |
//+------------------------------------------------------------------+
bool BuildBarContext(const string symbol, CIndicators &ind, BarContext &ctx)
{
   ctx.valid  = false;
   ctx.symbol = symbol;

   MqlRates r[];
   if(CopyRates(symbol, PERIOD_CURRENT, 1, 2, r) != 2) return(false);

   ctx.bar_time   = r[1].time;
   ctx.open       = r[1].open;
   ctx.high       = r[1].high;
   ctx.low        = r[1].low;
   ctx.close      = r[1].close;
   ctx.prev_close = r[0].close;

   if(!IndValue(ind.ATR(ATR_Period), 0, 1, ctx.atr)) return(false);
   if(ctx.atr <= 0.0) return(false);

   ctx.valid = true;
   return(true);
}

//+------------------------------------------------------------------+
//| Общий фильтр аномального ATR — применяется до любой тактики.     |
//+------------------------------------------------------------------+
bool ATRAnomaly(const BarContext &ctx)
{
   if(ATR_AnomalyPct <= 0.0) return(false);
   if(ctx.close <= 0.0) return(true);
   return((ctx.atr / ctx.close * 100.0) > ATR_AnomalyPct);
}

//==================================================================
//  ТАКТИКИ. Ф0: каркас и сигнатуры. Логика — Ф2.
//==================================================================

//+------------------------------------------------------------------+
//| C1 — Trend Pullback Continuation.                                |
//| EMA20/EMA200 тренд + откат в зону EMA20 + триггер + ADX.          |
//+------------------------------------------------------------------+
bool Tactic_C1(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_C1;
   return(false);   // Ф2
}

//+------------------------------------------------------------------+
//| C2 — Range Mean Reversion. Границы диапазона при низком ADX.      |
//+------------------------------------------------------------------+
bool Tactic_C2(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_C2;
   return(false);   // Ф2
}

//+------------------------------------------------------------------+
//| S6 — NY Opening Range Breakout.                                  |
//+------------------------------------------------------------------+
bool Tactic_S6(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_S6;
   return(false);   // Ф2
}

//+------------------------------------------------------------------+
//| S7 — Gate Breaker: пробой диапазона Токио в сессию Лондона.      |
//+------------------------------------------------------------------+
bool Tactic_S7(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_S7;
   return(false);   // Ф2
}

//+------------------------------------------------------------------+
//| Диспетчер: опросить одну тактику по её коду.                     |
//|                                                                  |
//| Тактики, до которых очередь не дошла (Ф2+), возвращают false —    |
//| это НЕ заглушка «на будущее», а честное «сигнала нет». Включённая |
//| параметром, но нереализованная тактика молчит и видна в журнале   |
//| как ноль сигналов, а не как ошибка.                               |
//+------------------------------------------------------------------+
bool EvalTactic(const ENUM_TACTIC t, const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   switch(t)
   {
      case TACTIC_C1: return(Tactic_C1(ctx, ind, sig));
      case TACTIC_C2: return(Tactic_C2(ctx, ind, sig));
      case TACTIC_S6: return(Tactic_S6(ctx, ind, sig));
      case TACTIC_S7: return(Tactic_S7(ctx, ind, sig));
   }
   sig.Clear();
   sig.tactic = t;
   return(false);
}

//==================================================================
//  ЖИВА ЛИ ГИПОТЕЗА ОТКРЫТОЙ КОРЗИНЫ
//==================================================================

//+------------------------------------------------------------------+
//| Вторая половина контракта тактики: сказать, что её тезис умер.    |
//|                                                                  |
//| ЗАЧЕМ ЭТО У ТАКТИКИ, А НЕ У ДВИЖКА. В Setura долив прекращался   |
//| по флипу её собственной EMA — то есть решение принимал мозг       |
//| советника. У нас мозгов двенадцать, и «разворот» для трендовой    |
//| тактики и для диапазонной означает противоположные вещи: для C1   |
//| это пересечение EMA, для C2 — пробой границы диапазона, который   |
//| для C1 был бы наоборот подтверждением.                            |
//|                                                                  |
//| Поэтому движок спрашивает, а отвечает тактика. Движок только      |
//| исполняет: перестаёт доливать (мягко) или закрывает корзину.      |
//|                                                                  |
//| Умолчание — ЖИВА. Тактика, не реализовавшая проверку, не должна   |
//| молча закрывать свои корзины: это выглядело бы как решение, а     |
//| было бы отсутствием кода.                                         |
//+------------------------------------------------------------------+
enum ENUM_HYPOTHESIS
{
   HYP_ALIVE = 0,       // тезис в силе — вести как обычно
   HYP_NO_ADDONS,       // долив прекратить, открытое вести до цели
   HYP_CLOSE            // тезис опровергнут — закрыть корзину
};

ENUM_HYPOTHESIS Hypothesis_C1(const BarContext &ctx, CIndicators &ind, const int direction)
{
   return(HYP_ALIVE);   // Ф2
}

ENUM_HYPOTHESIS Hypothesis_C2(const BarContext &ctx, CIndicators &ind, const int direction)
{
   return(HYP_ALIVE);   // Ф2
}

ENUM_HYPOTHESIS Hypothesis_S6(const BarContext &ctx, CIndicators &ind, const int direction)
{
   return(HYP_ALIVE);   // Ф2
}

ENUM_HYPOTHESIS Hypothesis_S7(const BarContext &ctx, CIndicators &ind, const int direction)
{
   return(HYP_ALIVE);   // Ф2
}

ENUM_HYPOTHESIS EvalHypothesis(const ENUM_TACTIC t, const BarContext &ctx,
                               CIndicators &ind, const int direction)
{
   if(!StopAddonsOnTrendFlip) return(HYP_ALIVE);

   switch(t)
   {
      case TACTIC_C1: return(Hypothesis_C1(ctx, ind, direction));
      case TACTIC_C2: return(Hypothesis_C2(ctx, ind, direction));
      case TACTIC_S6: return(Hypothesis_S6(ctx, ind, direction));
      case TACTIC_S7: return(Hypothesis_S7(ctx, ind, direction));
   }
   return(HYP_ALIVE);
}
