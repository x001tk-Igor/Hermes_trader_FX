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
//  СЕССИОННЫЕ УТИЛИТЫ (для S6, S7 и всех будущих сессионных тактик)
//==================================================================

//+------------------------------------------------------------------+
//| Смещение сервера от UTC в часах.                                 |
//|                                                                  |
//| ГРАБЛЯ, СНИМАЕМАЯ ЗДЕСЬ РАЗ И НАВСЕГДА: бары MT5 приходят в       |
//| СЕРВЕРНОМ времени, а все окна в ТЗ заданы в UTC. У RoboForex это  |
//| +3 часа — то есть окно NY 13:00-14:00 UTC на баре выглядит как    |
//| 16:00-17:00. Тактика, сравнивающая dt.hour напрямую, построит     |
//| диапазон не того часа и будет уверенно торговать чужое окно.      |
//|                                                                  |
//| Считается из разницы TimeCurrent и TimeGMT, а не задаётся         |
//| параметром: параметр пришлось бы менять при смене брокера и при   |
//| переходе на летнее время, и однажды его забудут.                  |
//+------------------------------------------------------------------+
int ServerUTCOffsetHours()
{
   long diff = (long)TimeCurrent() - (long)TimeGMT();
   return((int)MathRound((double)diff / 3600.0));
}

//+------------------------------------------------------------------+
//| Час UTC по серверному времени бара.                              |
//+------------------------------------------------------------------+
int BarHourUTC(const datetime server_time)
{
   datetime utc = server_time - (datetime)(ServerUTCOffsetHours() * 3600);
   MqlDateTime dt;
   TimeToStruct(utc, dt);
   return(dt.hour);
}

//+------------------------------------------------------------------+
//| Диапазон сессии: max/min по барам сегодняшнего окна [from; to).   |
//+------------------------------------------------------------------+
bool SessionRange(const string symbol, const int from_hour_utc, const int to_hour_utc,
                  double &out_high, double &out_low, int &bars_found)
{
   out_high = 0.0; out_low = 0.0; bars_found = 0;

   MqlRates r[];
   if(CopyRates(symbol, PERIOD_CURRENT, 1, 60, r) < 1) return(false);

   int offset = ServerUTCOffsetHours();
   long today_utc = ((long)TimeCurrent() - (long)offset * 3600) / 86400 * 86400;

   for(int i = ArraySize(r) - 1; i >= 0; i--)
   {
      long bar_utc = (long)r[i].time - (long)offset * 3600;
      if(bar_utc < today_utc) continue;

      MqlDateTime dt;
      TimeToStruct((datetime)bar_utc, dt);
      if(dt.hour < from_hour_utc || dt.hour >= to_hour_utc) continue;

      if(bars_found == 0) { out_high = r[i].high; out_low = r[i].low; }
      else
      {
         if(r[i].high > out_high) out_high = r[i].high;
         if(r[i].low  < out_low ) out_low  = r[i].low;
      }
      bars_found++;
   }
   return(bars_found > 0);
}

//+------------------------------------------------------------------+
//| Средний тиковый объём за N закрытых баров.                       |
//+------------------------------------------------------------------+
bool AvgTickVolume(const string symbol, const int lookback, double &out_avg)
{
   out_avg = 0.0;
   long v[];
   if(CopyTickVolume(symbol, PERIOD_CURRENT, 1, lookback, v) != lookback) return(false);
   double sum = 0.0;
   for(int i = 0; i < lookback; i++) sum += (double)v[i];
   out_avg = sum / (double)lookback;
   return(out_avg > 0.0);
}

//--- "уже входили сегодня" для сессионных тактик (один вход в день)
datetime g_last_entry_day[TACTIC_COUNT];

long TodayUTCStamp()
{
   return(((long)TimeCurrent() - (long)ServerUTCOffsetHours() * 3600) / 86400 * 86400);
}

bool AlreadyEnteredToday(const ENUM_TACTIC t)
{
   int idx = TacticIndex(t);
   if(idx < 0) return(false);
   return((long)g_last_entry_day[idx] == TodayUTCStamp());
}

void MarkEnteredToday(const ENUM_TACTIC t)
{
   int idx = TacticIndex(t);
   if(idx < 0) return;
   g_last_entry_day[idx] = (datetime)TodayUTCStamp();
}


//==================================================================
//  ОБЩИЕ ВЫЧИСЛЕНИЯ ДЛЯ НЕСКОЛЬКИХ ТАКТИК
//==================================================================

//+------------------------------------------------------------------+
//| UT Bot trailing stop: флип тренда.                               |
//|                                                                  |
//| Нужен и S3, и S5 — поэтому живёт здесь, а не внутри тактики.      |
//| Алгоритм из ТЗ §5.6: трейл идёт за ценой на ATR*mult и цепляется  |
//| только в свою сторону; смена стороны и есть сигнал.               |
//|                                                                  |
//| Считается заново по N барам на каждом вызове. Это дороже, чем     |
//| хранить состояние, но состояние пришлось бы восстанавливать после |
//| каждого перезапуска и рассинхронизации — а тактика обязана быть   |
//| ЧИСТОЙ функцией баров, иначе её нельзя воспроизвести в тестере.   |
//+------------------------------------------------------------------+
bool UTBotTrend(const string symbol, const int atr_period, const double mult,
                const int bars, int &trend_now, int &trend_prev)
{
   trend_now = 0; trend_prev = 0;
   if(bars < atr_period + 3) return(false);

   double close[];
   if(CopyClose(symbol, PERIOD_CURRENT, 1, bars, close) != bars) return(false);

   int h = iATR(symbol, PERIOD_CURRENT, atr_period);
   if(h == INVALID_HANDLE) return(false);
   double atr[];
   if(CopyBuffer(h, 0, 1, bars, atr) != bars) return(false);

   //--- массивы идут от старых к новым: [0] — самый старый
   double trail = close[atr_period] - atr[atr_period] * mult;
   int    tr    = 1;
   int    prev  = 1;

   for(int i = atr_period + 1; i < bars; i++)
   {
      prev = tr;
      if(close[i] > trail)
      {
         tr = 1;
         trail = MathMax(trail, close[i] - atr[i] * mult);
      }
      else if(close[i] < trail)
      {
         tr = -1;
         trail = MathMin(trail, close[i] + atr[i] * mult);
      }
   }
   trend_now  = tr;
   trend_prev = prev;
   return(true);
}

//+------------------------------------------------------------------+
//| Session VWAP от начала суток UTC (для S1).                       |
//|                                                                  |
//| Считается по типичной цене и тиковому объёму — реального объёма   |
//| на форексе нет, и притворяться, что есть, было бы враньём в       |
//| названии переменной.                                             |
//+------------------------------------------------------------------+
bool SessionVWAP(const string symbol, const int start_hour_utc, const int shift, double &out_vwap)
{
   out_vwap = 0.0;
   MqlRates r[];
   if(CopyRates(symbol, PERIOD_CURRENT, shift, 60, r) < 2) return(false);
   long v[];
   if(CopyTickVolume(symbol, PERIOD_CURRENT, shift, 60, v) < 2) return(false);

   int offset = ServerUTCOffsetHours();
   long day_start = ((long)r[ArraySize(r) - 1].time - (long)offset * 3600) / 86400 * 86400
                    + (long)start_hour_utc * 3600;

   double pv = 0.0, vol = 0.0;
   for(int i = 0; i < ArraySize(r); i++)
   {
      long bar_utc = (long)r[i].time - (long)offset * 3600;
      if(bar_utc < day_start) continue;
      double tp = (r[i].high + r[i].low + r[i].close) / 3.0;
      pv  += tp * (double)v[i];
      vol += (double)v[i];
   }
   if(vol <= 0.0) return(false);
   out_vwap = pv / vol;
   return(true);
}

//+------------------------------------------------------------------+
//| Экстремум последних N закрытых баров (для BOS и пробоев).        |
//+------------------------------------------------------------------+
bool ExtremeOf(const string symbol, const int from_shift, const int count,
               double &out_high, double &out_low)
{
   double hi[], lo[];
   if(CopyHigh(symbol, PERIOD_CURRENT, from_shift, count, hi) != count) return(false);
   if(CopyLow (symbol, PERIOD_CURRENT, from_shift, count, lo) != count) return(false);
   out_high = hi[ArrayMaximum(hi)];
   out_low  = lo[ArrayMinimum(lo)];
   return(true);
}

//==================================================================
//  ТАКТИКИ
//==================================================================

//+------------------------------------------------------------------+
//| C1 — Trend Pullback Continuation.                                |
//| EMA20/EMA200 тренд + откат в зону EMA20 + триггер + ADX.          |
//+------------------------------------------------------------------+
bool Tactic_C1(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_C1;

   double ema_f, ema_s, adx;
   if(!IndValue(ind.EMA(C1_EmaFast), 0, 1, ema_f)) return(false);
   if(!IndValue(ind.EMA(C1_EmaSlow), 0, 1, ema_s)) return(false);
   if(!IndValue(ind.ADX(14), 0, 1, adx))           return(false);

   if(adx < C1_AdxMin) return(false);              // тренда нет — не наш случай

   int dir = DIR_NONE;
   if(ema_f > ema_s) dir = DIR_LONG;
   else if(ema_f < ema_s) dir = DIR_SHORT;
   else return(false);

   //--- откат: цена вернулась в зону быстрой EMA
   double zone = ctx.atr * C1_PullbackZoneATR;
   bool in_zone = (MathAbs(ctx.close - ema_f) <= zone) ||
                  (dir == DIR_LONG  && ctx.low  <= ema_f && ctx.high >= ema_f) ||
                  (dir == DIR_SHORT && ctx.high >= ema_f && ctx.low  <= ema_f);
   if(!in_zone) return(false);

   //--- триггер: свеча по тренду, либо пин-бар, либо разворот RSI
   double body      = MathAbs(ctx.close - ctx.open);
   double upper_wick = ctx.high - MathMax(ctx.open, ctx.close);
   double lower_wick = MathMin(ctx.open, ctx.close) - ctx.low;
   double min_body  = ctx.atr * C1_MinBodyATR;

   bool trigger = false;
   string why = "";

   if(dir == DIR_LONG)
   {
      if(ctx.close > ctx.open && body >= min_body) { trigger = true; why = "bull_body"; }
      else if(lower_wick > C1_PinWickRatio * MathMax(body, _Point) && ctx.close > ctx.open)
      { trigger = true; why = "pin_bar"; }
   }
   else
   {
      if(ctx.close < ctx.open && body >= min_body) { trigger = true; why = "bear_body"; }
      else if(upper_wick > C1_PinWickRatio * MathMax(body, _Point) && ctx.close < ctx.open)
      { trigger = true; why = "pin_bar"; }
   }

   if(!trigger)
   {
      double rsi[];
      if(IndSeries(ind.RSI(14), 0, 1, 2, rsi))
      {
         //--- rsi[0] — бар 1 (свежий), rsi[1] — бар 2
         if(dir == DIR_LONG && rsi[0] >= 35.0 && rsi[0] <= 55.0 && rsi[0] > rsi[1])
         { trigger = true; why = "rsi_turn_up"; }
         if(dir == DIR_SHORT && rsi[0] >= 45.0 && rsi[0] <= 65.0 && rsi[0] < rsi[1])
         { trigger = true; why = "rsi_turn_down"; }
      }
   }
   if(!trigger) return(false);

   sig.valid       = true;
   sig.direction   = dir;
   sig.sl_distance = ctx.atr * SL_ATR_Mult;
   sig.tp_distance = 0.0;                          // цель по общему множителю ATR
   sig.confidence  = MathMin(1.0, adx / 40.0);
   sig.reason      = "pullback_to_ema" + IntegerToString(C1_EmaFast) + "_" + why +
                     "_adx" + DoubleToString(adx, 1);
   return(true);
}

//+------------------------------------------------------------------+
//| C2 — Range Mean Reversion. Границы диапазона при низком ADX.      |
//+------------------------------------------------------------------+
bool Tactic_C2(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_C2;

   double adx;
   if(!IndValue(ind.ADX(14), 0, 1, adx)) return(false);
   if(adx > C2_AdxMax) return(false);               // тренд — диапазона нет

   int n = C2_RangeLookback;
   double hi[], lo[];
   if(CopyHigh(ctx.symbol, PERIOD_CURRENT, 1, n, hi) != n) return(false);
   if(CopyLow (ctx.symbol, PERIOD_CURRENT, 1, n, lo) != n) return(false);

   double rh = hi[ArrayMaximum(hi)];
   double rl = lo[ArrayMinimum(lo)];
   double size = rh - rl;
   if(size <= 0.0) return(false);
   if(size > ctx.atr * C2_RangeMaxATR) return(false);   // слишком широкий — не диапазон

   //--- границу надо ПОДТВЕРДИТЬ касаниями, иначе это просто экстремум
   double prox = ctx.atr * C2_BoundaryProximityATR;
   int upper_tests = 0, lower_tests = 0;
   for(int k = 0; k < n; k++)
   {
      if(hi[k] >= rh - prox) upper_tests++;
      if(lo[k] <= rl + prox) lower_tests++;
   }

   double body       = MathAbs(ctx.close - ctx.open);
   double lower_wick = MathMin(ctx.open, ctx.close) - ctx.low;
   double upper_wick = ctx.high - MathMax(ctx.open, ctx.close);
   double mid        = (rh + rl) / 2.0;

   //--- от нижней границы вверх
   if(ctx.low <= rl + prox && lower_tests >= C2_BoundaryTestMin)
   {
      bool rejection = (lower_wick > C2_RejectionWickRatio * MathMax(body, _Point)) &&
                       (ctx.close > rl);
      bool engulf    = (ctx.close > ctx.open) && (ctx.close > ctx.prev_close);
      if(rejection || engulf)
      {
         sig.valid       = true;
         sig.direction   = DIR_LONG;
         sig.sl_distance = ctx.atr * SL_ATR_Mult;
         sig.tp_distance = MathMax(mid - ctx.close, ctx.atr * 0.2);
         sig.confidence  = MathMin(1.0, (double)lower_tests / 5.0);
         sig.reason      = "range_low_" + (rejection ? "rejection" : "engulf") +
                           "_tests" + IntegerToString(lower_tests) +
                           "_adx" + DoubleToString(adx, 1);
         return(true);
      }
   }

   //--- от верхней границы вниз
   if(ctx.high >= rh - prox && upper_tests >= C2_BoundaryTestMin)
   {
      bool rejection = (upper_wick > C2_RejectionWickRatio * MathMax(body, _Point)) &&
                       (ctx.close < rh);
      bool engulf    = (ctx.close < ctx.open) && (ctx.close < ctx.prev_close);
      if(rejection || engulf)
      {
         sig.valid       = true;
         sig.direction   = DIR_SHORT;
         sig.sl_distance = ctx.atr * SL_ATR_Mult;
         sig.tp_distance = MathMax(ctx.close - mid, ctx.atr * 0.2);
         sig.confidence  = MathMin(1.0, (double)upper_tests / 5.0);
         sig.reason      = "range_high_" + (rejection ? "rejection" : "engulf") +
                           "_tests" + IntegerToString(upper_tests) +
                           "_adx" + DoubleToString(adx, 1);
         return(true);
      }
   }
   return(false);
}

//+------------------------------------------------------------------+
//| S6 — NY Opening Range Breakout.                                  |
//+------------------------------------------------------------------+
bool Tactic_S6(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_S6;

   int hour = BarHourUTC(ctx.bar_time);
   if(hour < S6_OR_EndHourUTC || hour >= S6_EntryEndHourUTC) return(false);
   if(S6_OneEntryPerDay && AlreadyEnteredToday(TACTIC_S6))   return(false);

   double orh, orl; int bars;
   if(!SessionRange(ctx.symbol, S6_OR_StartHourUTC, S6_OR_EndHourUTC, orh, orl, bars))
      return(false);

   double range = orh - orl;
   if(range <= 0.0) return(false);

   //--- сжатие: широкий диапазон открытия это не пружина, а уже движение
   if(range > ctx.atr * S6_CompressionMaxATR) return(false);

   //--- объём обязателен: пробой без него ненадёжен
   double avg_vol;
   if(!AvgTickVolume(ctx.symbol, S6_VolumeLookback, avg_vol)) return(false);
   long cur_vol[];
   if(CopyTickVolume(ctx.symbol, PERIOD_CURRENT, 1, 1, cur_vol) != 1) return(false);
   if((double)cur_vol[0] < avg_vol * S6_VolumeMult) return(false);

   int dir = DIR_NONE;
   if(ctx.close > orh) dir = DIR_LONG;
   else if(ctx.close < orl) dir = DIR_SHORT;
   else return(false);

   sig.valid       = true;
   sig.direction   = dir;
   sig.sl_distance = ctx.atr * SL_ATR_Mult;
   sig.tp_distance = 0.0;
   sig.confidence  = MathMin(1.0, (double)cur_vol[0] / MathMax(avg_vol * 2.0, 1.0));
   sig.reason      = "ny_orb_range" + DoubleToString(range / ctx.atr, 2) +
                     "atr_vol" + DoubleToString((double)cur_vol[0] / avg_vol, 2) + "x";
   MarkEnteredToday(TACTIC_S6);
   return(true);
}

//+------------------------------------------------------------------+
//| S7 — Gate Breaker: пробой диапазона Токио в сессию Лондона.      |
//+------------------------------------------------------------------+
bool Tactic_S7(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_S7;

   int hour = BarHourUTC(ctx.bar_time);
   if(hour < S7_LondonStartHourUTC || hour >= S7_LondonEndHourUTC) return(false);
   if(S7_OneEntryPerDay && AlreadyEnteredToday(TACTIC_S7))        return(false);

   double th, tl; int bars;
   if(!SessionRange(ctx.symbol, S7_TokyoStartHourUTC, S7_TokyoEndHourUTC, th, tl, bars))
      return(false);
   if(th - tl <= 0.0) return(false);

   //--- ТЕЛОМ, а не фитилём: свеча открылась внутри диапазона и
   //    закрылась снаружи. Фитильный прокол это ложный пробой, и
   //    отличать его надо здесь, а не потом по убыткам.
   int dir = DIR_NONE;
   if(ctx.close > th && (!S7_BodyBreakRequired || ctx.open <= th)) dir = DIR_LONG;
   else if(ctx.close < tl && (!S7_BodyBreakRequired || ctx.open >= tl)) dir = DIR_SHORT;
   else return(false);

   sig.valid       = true;
   sig.direction   = dir;
   sig.sl_distance = ctx.atr * SL_ATR_Mult;
   sig.tp_distance = 0.0;
   sig.confidence  = 0.6;
   sig.reason      = "tokyo_gate_" + IntegerToString(bars) + "bars_range" +
                     DoubleToString((th - tl) / ctx.atr, 2) + "atr";
   MarkEnteredToday(TACTIC_S7);
   return(true);
}



//+------------------------------------------------------------------+
//| C3 — RSI + Bollinger Reversion. Возврат от края полосы в боковике.|
//+------------------------------------------------------------------+
bool Tactic_C3(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_C3;

   double adx;
   if(!IndValue(ind.ADX(14), 0, 1, adx)) return(false);
   if(adx > C3_AdxMax) return(false);

   int bb = ind.BB(C3_BB_Period, C3_BB_Std);
   double mid, upper, lower;
   if(!IndValue(bb, 0, 1, mid))   return(false);
   if(!IndValue(bb, 1, 1, upper)) return(false);
   if(!IndValue(bb, 2, 1, lower)) return(false);

   double rsi[];
   if(!IndSeries(ind.RSI(14), 0, 1, 2, rsi)) return(false);

   //--- лонг: цена ниже нижней полосы, RSI перепродан И разворачивается ВВЕРХ.
   //    Без разворота это ловля падающего ножа: цена под полосой может
   //    идти под ней ещё десяток баров.
   if(ctx.close < lower && rsi[0] < C3_RsiLongMax && rsi[0] > rsi[1])
   {
      sig.valid       = true;
      sig.direction   = DIR_LONG;
      sig.sl_distance = ctx.atr * SL_ATR_Mult;
      sig.tp_distance = MathMax(mid - ctx.close, ctx.atr * 0.2);
      sig.confidence  = MathMin(1.0, (C3_RsiLongMax - rsi[0]) / 20.0);
      sig.reason      = "bb_lower_rsi" + DoubleToString(rsi[0], 1) + "_turn_up";
      return(true);
   }

   if(ctx.close > upper && rsi[0] > C3_RsiShortMin && rsi[0] < rsi[1])
   {
      sig.valid       = true;
      sig.direction   = DIR_SHORT;
      sig.sl_distance = ctx.atr * SL_ATR_Mult;
      sig.tp_distance = MathMax(ctx.close - mid, ctx.atr * 0.2);
      sig.confidence  = MathMin(1.0, (rsi[0] - C3_RsiShortMin) / 20.0);
      sig.reason      = "bb_upper_rsi" + DoubleToString(rsi[0], 1) + "_turn_down";
      return(true);
   }
   return(false);
}

//+------------------------------------------------------------------+
//| C4 — Liquidity Sweep. Прокол экстремума и возврат внутрь.        |
//+------------------------------------------------------------------+
bool Tactic_C4(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_C4;

   //--- экстремум ДО текущего бара: сравнивать бар сам с собой бессмысленно
   double ph, pl;
   if(!ExtremeOf(ctx.symbol, 2, C4_SweepLookback, ph, pl)) return(false);

   double ema;
   if(!IndValue(ind.EMA(C4_EmaTrigger), 0, 1, ema)) return(false);
   double ema_prev;
   if(!IndValue(ind.EMA(C4_EmaTrigger), 0, 2, ema_prev)) return(false);

   //--- подтверждение направления последними свечами
   MqlRates r[];
   if(CopyRates(ctx.symbol, PERIOD_CURRENT, 1, C4_ConfirmCandles, r) != C4_ConfirmCandles)
      return(false);
   int bull = 0, bear = 0;
   for(int i = 0; i < C4_ConfirmCandles; i++)
   {
      if(r[i].close > r[i].open) bull++;
      if(r[i].close < r[i].open) bear++;
   }

   //--- ЛОНГ: пробили минимум и вернулись выше него в том же баре
   bool sweep_low = (ctx.low < pl) && (ctx.close > pl);
   if(sweep_low && ctx.close > ema && ctx.prev_close <= ema_prev &&
      bull >= C4_ConfirmMinSameDir)
   {
      sig.valid       = true;
      sig.direction   = DIR_LONG;
      sig.sl_distance = ctx.atr * SL_ATR_Mult;
      sig.tp_distance = 0.0;
      sig.confidence  = MathMin(1.0, (double)bull / (double)C4_ConfirmCandles);
      sig.reason      = "sweep_low_return_ema" + IntegerToString(C4_EmaTrigger);
      return(true);
   }

   bool sweep_high = (ctx.high > ph) && (ctx.close < ph);
   if(sweep_high && ctx.close < ema && ctx.prev_close >= ema_prev &&
      bear >= C4_ConfirmMinSameDir)
   {
      sig.valid       = true;
      sig.direction   = DIR_SHORT;
      sig.sl_distance = ctx.atr * SL_ATR_Mult;
      sig.tp_distance = 0.0;
      sig.confidence  = MathMin(1.0, (double)bear / (double)C4_ConfirmCandles);
      sig.reason      = "sweep_high_return_ema" + IntegerToString(C4_EmaTrigger);
      return(true);
   }
   return(false);
}

//+------------------------------------------------------------------+
//| S1 — пересечение EMA9 и session VWAP.                            |
//+------------------------------------------------------------------+
bool Tactic_S1(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_S1;

   double ema_now, ema_prev, vwap_now, vwap_prev;
   if(!IndValue(ind.EMA(S1_EmaPeriod), 0, 1, ema_now))  return(false);
   if(!IndValue(ind.EMA(S1_EmaPeriod), 0, 2, ema_prev)) return(false);
   if(!SessionVWAP(ctx.symbol, S1_VwapStartHourUTC, 1, vwap_now))  return(false);
   if(!SessionVWAP(ctx.symbol, S1_VwapStartHourUTC, 2, vwap_prev)) return(false);

   int dir = DIR_NONE;
   if(ema_prev <= vwap_prev && ema_now > vwap_now) dir = DIR_LONG;
   else if(ema_prev >= vwap_prev && ema_now < vwap_now) dir = DIR_SHORT;
   else return(false);

   sig.valid       = true;
   sig.direction   = dir;
   sig.sl_distance = ctx.atr * SL_ATR_Mult;
   sig.tp_distance = 0.0;
   sig.confidence  = 0.5;
   sig.reason      = "ema" + IntegerToString(S1_EmaPeriod) + "_x_vwap";
   return(true);
}

//+------------------------------------------------------------------+
//| S2 — двойной режим: откат по RSI либо пробой, в рамках тренда.   |
//+------------------------------------------------------------------+
bool Tactic_S2(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_S2;

   double ema_f, ema_s, rsi;
   if(!IndValue(ind.EMA(S2_EmaFast), 0, 1, ema_f)) return(false);
   if(!IndValue(ind.EMA(S2_EmaSlow), 0, 1, ema_s)) return(false);
   if(!IndValue(ind.RSI(14), 0, 1, rsi))           return(false);

   int dir = DIR_NONE;
   if(ema_f > ema_s && ctx.close > ema_s) dir = DIR_LONG;
   else if(ema_f < ema_s && ctx.close < ema_s) dir = DIR_SHORT;
   else return(false);

   double bh, bl;
   if(!ExtremeOf(ctx.symbol, 2, S2_BreakoutLookback, bh, bl)) return(false);

   //--- приоритет у пробоя: импульс сильнее отката, и когда сработали оба,
   //    брать надо тот, что описывает более сильное движение (ТЗ §4.6)
   bool breakout = S2_ModeB_Breakout &&
                   ((dir == DIR_LONG && ctx.close > bh) ||
                    (dir == DIR_SHORT && ctx.close < bl));
   bool pullback = S2_ModeA_RsiPullback &&
                   ((dir == DIR_LONG && rsi < S2_RsiLongThreshold) ||
                    (dir == DIR_SHORT && rsi > S2_RsiShortThreshold));

   if(!breakout && !pullback) return(false);

   sig.valid       = true;
   sig.direction   = dir;
   sig.sl_distance = ctx.atr * SL_ATR_Mult;
   sig.tp_distance = 0.0;
   sig.confidence  = breakout ? 0.7 : 0.5;
   sig.reason      = breakout ? "s2_breakout" : ("s2_rsi_pullback" + DoubleToString(rsi, 1));
   return(true);
}

//+------------------------------------------------------------------+
//| S3 — три слоя: HTF-тренд + флип UT Bot + сила тренда.            |
//+------------------------------------------------------------------+
bool Tactic_S3(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_S3;

   double ema, adx;
   if(!IndValue(ind.EMA(S3_HtfEmaPeriod), 0, 1, ema)) return(false);
   if(!IndValue(ind.ADX(14), 0, 1, adx))              return(false);
   if(adx < S3_AdxMin) return(false);

   int tr_now, tr_prev;
   if(!UTBotTrend(ctx.symbol, S3_UtBotAtrPeriod, S3_UtBotAtrMult, 200, tr_now, tr_prev))
      return(false);
   if(tr_now == tr_prev) return(false);            // флипа не было

   int dir = DIR_NONE;
   if(tr_now == 1 && ctx.close > ema) dir = DIR_LONG;
   else if(tr_now == -1 && ctx.close < ema) dir = DIR_SHORT;
   else return(false);

   sig.valid       = true;
   sig.direction   = dir;
   sig.sl_distance = ctx.atr * SL_ATR_Mult;
   sig.tp_distance = 0.0;
   sig.confidence  = MathMin(1.0, adx / 40.0);
   sig.reason      = "utbot_flip_ema" + IntegerToString(S3_HtfEmaPeriod) +
                     "_adx" + DoubleToString(adx, 1);
   return(true);
}

//+------------------------------------------------------------------+
//| S4 — MadCharts: касание базовой зоны + выравнивание быстрых EMA. |
//+------------------------------------------------------------------+
bool Tactic_S4(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_S4;

   double bema, bsma, f1, f2;
   if(!IndValue(ind.EMA(S4_BaselineEma), 0, 1, bema)) return(false);
   if(!IndValue(ind.SMA(S4_BaselineSma), 0, 1, bsma)) return(false);
   if(!IndValue(ind.EMA(S4_FastEma1), 0, 1, f1))      return(false);
   if(!IndValue(ind.EMA(S4_FastEma2), 0, 1, f2))      return(false);

   double zone_hi = MathMax(bema, bsma);
   double zone_lo = MathMin(bema, bsma);

   //--- касание зоны за последние N баров
   MqlRates r[];
   if(CopyRates(ctx.symbol, PERIOD_CURRENT, 1, S4_TouchLookback, r) != S4_TouchLookback)
      return(false);
   bool touched = false;
   for(int i = 0; i < S4_TouchLookback; i++)
      if(r[i].low <= zone_hi && r[i].high >= zone_lo) { touched = true; break; }
   if(!touched) return(false);

   if(f1 > f2 && f1 > zone_hi && f2 > zone_hi && ctx.close > f1 && ctx.close > f2)
   {
      sig.valid       = true;
      sig.direction   = DIR_LONG;
      sig.sl_distance = ctx.atr * SL_ATR_Mult;
      sig.tp_distance = 0.0;
      sig.confidence  = 0.6;
      sig.reason      = "baseline_touch_ema_aligned_up";
      return(true);
   }

   if(f1 < f2 && f1 < zone_lo && f2 < zone_lo && ctx.close < f1 && ctx.close < f2)
   {
      sig.valid       = true;
      sig.direction   = DIR_SHORT;
      sig.sl_distance = ctx.atr * SL_ATR_Mult;
      sig.tp_distance = 0.0;
      sig.confidence  = 0.6;
      sig.reason      = "baseline_touch_ema_aligned_down";
      return(true);
   }
   return(false);
}

//+------------------------------------------------------------------+
//| S5 — UT Bot + STC(прокси RSI) + стек из четырёх фильтров.        |
//+------------------------------------------------------------------+
bool Tactic_S5(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_S5;

   int tr_now, tr_prev;
   if(!UTBotTrend(ctx.symbol, S5_UtBotAtrPeriod, S5_UtBotAtrMult, 200, tr_now, tr_prev))
      return(false);
   if(tr_now == tr_prev) return(false);

   double rsi, adx;
   if(!IndValue(ind.RSI(14), 0, 1, rsi)) return(false);
   if(!IndValue(ind.ADX(14), 0, 1, adx)) return(false);

   //--- Guard 1: сила тренда
   if(adx < S5_AdxMin) return(false);

   //--- Guard 2: размах свечи в разумных пределах
   double range = ctx.high - ctx.low;
   if(range < ctx.atr * S5_CandleRangeMinATR) return(false);
   if(range > ctx.atr * S5_CandleRangeMaxATR) return(false);

   //--- Guard 3: объём не ниже среднего
   double avg_vol;
   if(!AvgTickVolume(ctx.symbol, S5_VolumeLookback, avg_vol)) return(false);
   long cur[];
   if(CopyTickVolume(ctx.symbol, PERIOD_CURRENT, 1, 1, cur) != 1) return(false);
   if((double)cur[0] < avg_vol * S5_VolumeFilterMult) return(false);

   double body       = MathAbs(ctx.close - ctx.open);
   double upper_wick = ctx.high - MathMax(ctx.open, ctx.close);
   double lower_wick = MathMin(ctx.open, ctx.close) - ctx.low;

   int dir = DIR_NONE;
   if(tr_now == 1 && rsi < S5_RsiLongMax)
   {
      //--- Guard 4: встречный фитиль не съедает половину свечи —
      //    иначе цена уже упёрлась в сопротивление
      if(upper_wick > range * 0.5) return(false);
      dir = DIR_LONG;
   }
   else if(tr_now == -1 && rsi > S5_RsiShortMin)
   {
      if(lower_wick > range * 0.5) return(false);
      dir = DIR_SHORT;
   }
   else return(false);

   sig.valid       = true;
   sig.direction   = dir;
   sig.sl_distance = ctx.atr * SL_ATR_Mult;
   sig.tp_distance = 0.0;
   sig.confidence  = MathMin(1.0, adx / 40.0);
   sig.reason      = "utbot_stc_guards_rsi" + DoubleToString(rsi, 1) +
                     "_adx" + DoubleToString(adx, 1);
   return(true);
}

//+------------------------------------------------------------------+
//| S8 — Smart Trend: пробой структуры при растущем ADX.             |
//+------------------------------------------------------------------+
bool Tactic_S8(const BarContext &ctx, CIndicators &ind, Signal &sig)
{
   sig.Clear();
   sig.tactic = TACTIC_S8;

   double ema_f, ema_s;
   if(!IndValue(ind.EMA(S8_EmaFast), 0, 1, ema_f)) return(false);
   if(!IndValue(ind.EMA(S8_EmaSlow), 0, 1, ema_s)) return(false);

   double adx[];
   if(!IndSeries(ind.ADX(14), 0, 1, 2, adx)) return(false);
   if(adx[0] < S8_AdxMin) return(false);
   if(adx[0] <= adx[1]) return(false);             // ADX обязан РАСТИ, а не просто быть высоким

   double bh, bl;
   if(!ExtremeOf(ctx.symbol, 2, S8_BosLookback, bh, bl)) return(false);

   int dir = DIR_NONE;
   if(ema_f > ema_s && ctx.close > ema_f && ctx.close > bh) dir = DIR_LONG;
   else if(ema_f < ema_s && ctx.close < ema_f && ctx.close < bl) dir = DIR_SHORT;
   else return(false);

   sig.valid       = true;
   sig.direction   = dir;
   sig.sl_distance = ctx.atr * SL_ATR_Mult;
   sig.tp_distance = 0.0;
   sig.confidence  = MathMin(1.0, adx[0] / 40.0);
   sig.reason      = "bos_" + IntegerToString(S8_BosLookback) + "bars_adx_rising" +
                     DoubleToString(adx[0], 1);
   return(true);
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
      case TACTIC_C3: return(Tactic_C3(ctx, ind, sig));
      case TACTIC_C4: return(Tactic_C4(ctx, ind, sig));
      case TACTIC_S1: return(Tactic_S1(ctx, ind, sig));
      case TACTIC_S2: return(Tactic_S2(ctx, ind, sig));
      case TACTIC_S3: return(Tactic_S3(ctx, ind, sig));
      case TACTIC_S4: return(Tactic_S4(ctx, ind, sig));
      case TACTIC_S5: return(Tactic_S5(ctx, ind, sig));
      case TACTIC_S6: return(Tactic_S6(ctx, ind, sig));
      case TACTIC_S7: return(Tactic_S7(ctx, ind, sig));
      case TACTIC_S8: return(Tactic_S8(ctx, ind, sig));
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
