//+------------------------------------------------------------------+
//|                                                        Types.mqh |
//|  Общие типы Hermes FX: сигнал, реестр тактик, коды отказов.      |
//+------------------------------------------------------------------+
#property strict

//--- РЕЕСТР ТАКТИК -------------------------------------------------
// Каждая тактика получает СВОЙ magic. Это не удобство, а условие
// измеримости: без раздельных magic в истории сделок двенадцать
// механизмов лежат под одним номером, и вопрос «какая тактика
// работает» становится неотвечаемым — то есть оптимизация, ради
// которой строится советник, теряет смысл.
//
// База задаётся входным параметром MagicBase, смещения фиксированы:
// так на одном счёте можно развести несколько экземпляров советника,
// не переписывая код и не теряя привязку тактика→magic.
enum ENUM_TACTIC
{
   TACTIC_NONE = 0,
   TACTIC_C1   = 1,   // Trend Pullback Continuation (EMA20/200 + откат)
   TACTIC_C2   = 2,   // Range Mean Reversion (границы диапазона)
   TACTIC_C3   = 3,   // RSI + Bollinger Reversion
   TACTIC_C4   = 4,   // Liquidity Sweep
   TACTIC_S1   = 11,  // EMA9 x session VWAP
   TACTIC_S2   = 12,  // Dual Mode: RSI pullback / momentum breakout
   TACTIC_S3   = 13,  // 200EMA + UT Bot + ADX
   TACTIC_S4   = 14,  // MadCharts Baseline
   TACTIC_S5   = 15,  // UT Bot + STC + Guard Stack
   TACTIC_S6   = 16,  // NY Opening Range Breakout
   TACTIC_S7   = 17,  // Gate Breaker (Tokyo -> London)
   TACTIC_S8   = 18   // Smart Trend (BOS + ADX rising)
};

#define TACTIC_COUNT 12

//--- НАПРАВЛЕНИЕ ---------------------------------------------------
#define DIR_NONE   0
#define DIR_LONG   1
#define DIR_SHORT (-1)

//+------------------------------------------------------------------+
//| Сигнал одной тактики.                                            |
//|                                                                  |
//| Тактика НЕ знает про лоты, риск, разрешения и открытые позиции.   |
//| Она отвечает ровно на один вопрос: «есть ли вход и по какой цене  |
//| ставить защиту». Всё остальное решают слои ниже. Граница жёсткая  |
//| намеренно: как только тактика начинает считать лот, её нельзя     |
//| протестировать в изоляции, а именно изоляция и есть цель.         |
//+------------------------------------------------------------------+
struct Signal
{
   bool        valid;        // есть ли вход вообще
   ENUM_TACTIC tactic;       // кто дал сигнал
   int         direction;    // DIR_LONG / DIR_SHORT
   double      sl_distance;  // расстояние до стопа В ЦЕНЕ (не в пунктах!)
   double      tp_distance;  // расстояние до цели В ЦЕНЕ
   double      confidence;   // 0..1, для арбитража при нехватке бюджета
   string      reason;       // человекочитаемо, идёт в журнал

   void Clear()
   {
      valid       = false;
      tactic      = TACTIC_NONE;
      direction   = DIR_NONE;
      sl_distance = 0.0;
      tp_distance = 0.0;
      confidence  = 0.0;
      reason      = "";
   }
};

//+------------------------------------------------------------------+
//| Причина отказа во входе — пишется в журнал КАЖДЫЙ раз.           |
//|                                                                  |
//| Молчаливый пропуск неотличим от «сигнала не было»: при разборе    |
//| нельзя понять, тактика не сработала или её зарезал фильтр. Для    |
//| оптимизации это критично — доля отказов по каждой причине         |
//| показывает, какой фильтр реально связывает, а какой декоративен.  |
//+------------------------------------------------------------------+
enum ENUM_SKIP_REASON
{
   SKIP_NONE = 0,
   SKIP_NO_SIGNAL,        // тактика не дала сигнала
   SKIP_DISABLED,         // тактика выключена параметром
   SKIP_PERMISSION,       // запрещено управляющим (permissions.json)
   SKIP_SESSION,          // вне торгового окна
   SKIP_NEWS,             // новостной blackout
   SKIP_SPREAD,           // спред шире допустимого
   SKIP_ATR_ANOMALY,      // ATR аномален (> % цены)
   SKIP_RISK_BUDGET,      // бюджет риска исчерпан
   SKIP_MAX_BASKETS,      // достигнут лимит корзин
   SKIP_LOT_TOO_SMALL,    // расчётный лот меньше минимального
   SKIP_COOLDOWN,         // не истёк cooldown после прошлой сделки
   SKIP_ALREADY_OPEN,     // у этой тактики уже есть корзина
   SKIP_ARBITER           // проиграл арбитраж другому сигналу
};

//+------------------------------------------------------------------+
//| Строковое имя тактики — для журнала и комментариев к ордерам.    |
//+------------------------------------------------------------------+
string TacticName(const ENUM_TACTIC t)
{
   switch(t)
   {
      case TACTIC_C1: return("C1_TrendPullback");
      case TACTIC_C2: return("C2_RangeReversion");
      case TACTIC_C3: return("C3_RSI_BB");
      case TACTIC_C4: return("C4_LiquiditySweep");
      case TACTIC_S1: return("S1_EMA_VWAP");
      case TACTIC_S2: return("S2_DualMode");
      case TACTIC_S3: return("S3_UTBot_ADX");
      case TACTIC_S4: return("S4_MadCharts");
      case TACTIC_S5: return("S5_UTBot_STC");
      case TACTIC_S6: return("S6_NY_ORB");
      case TACTIC_S7: return("S7_GateBreaker");
      case TACTIC_S8: return("S8_SmartTrend");
   }
   return("NONE");
}

string SkipReasonName(const ENUM_SKIP_REASON r)
{
   switch(r)
   {
      case SKIP_NO_SIGNAL:     return("no_signal");
      case SKIP_DISABLED:      return("disabled");
      case SKIP_PERMISSION:    return("permission");
      case SKIP_SESSION:       return("session");
      case SKIP_NEWS:          return("news");
      case SKIP_SPREAD:        return("spread");
      case SKIP_ATR_ANOMALY:   return("atr_anomaly");
      case SKIP_RISK_BUDGET:   return("risk_budget");
      case SKIP_MAX_BASKETS:   return("max_baskets");
      case SKIP_LOT_TOO_SMALL: return("lot_too_small");
      case SKIP_COOLDOWN:      return("cooldown");
      case SKIP_ALREADY_OPEN:  return("already_open");
      case SKIP_ARBITER:       return("arbiter");
   }
   return("none");
}

//+------------------------------------------------------------------+
//| Порядковый номер тактики 0..TACTIC_COUNT-1 для массивов.        |
//| Возвращает -1 для TACTIC_NONE.                                   |
//+------------------------------------------------------------------+
int TacticIndex(const ENUM_TACTIC t)
{
   switch(t)
   {
      case TACTIC_C1: return(0);
      case TACTIC_C2: return(1);
      case TACTIC_C3: return(2);
      case TACTIC_C4: return(3);
      case TACTIC_S1: return(4);
      case TACTIC_S2: return(5);
      case TACTIC_S3: return(6);
      case TACTIC_S4: return(7);
      case TACTIC_S5: return(8);
      case TACTIC_S6: return(9);
      case TACTIC_S7: return(10);
      case TACTIC_S8: return(11);
   }
   return(-1);
}

ENUM_TACTIC TacticByIndex(const int i)
{
   switch(i)
   {
      case 0:  return(TACTIC_C1);
      case 1:  return(TACTIC_C2);
      case 2:  return(TACTIC_C3);
      case 3:  return(TACTIC_C4);
      case 4:  return(TACTIC_S1);
      case 5:  return(TACTIC_S2);
      case 6:  return(TACTIC_S3);
      case 7:  return(TACTIC_S4);
      case 8:  return(TACTIC_S5);
      case 9:  return(TACTIC_S6);
      case 10: return(TACTIC_S7);
      case 11: return(TACTIC_S8);
   }
   return(TACTIC_NONE);
}
