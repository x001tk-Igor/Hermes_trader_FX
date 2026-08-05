//+------------------------------------------------------------------+
//|                                                       Basket.mqh |
//|  Движок корзины. Перенос ядра из Setura_M1_V5_EMA.mq5.           |
//|                                                                  |
//|  КОРЗИНА — это позиции ОДНОЙ тактики ОДНОГО направления на одном  |
//|  символе, управляемые как целое: общая цель от средневзвешенной   |
//|  цены, индивидуальный стоп у каждой позиции, ограниченная глубина.|
//|                                                                  |
//|  ВИРТУАЛЬНЫЙ TP, а не брокерский. Причина в том, что цель корзины |
//|  ДВИЖЕТСЯ: после каждой доливки средневзвешенная цена смещается,  |
//|  и общий TP надо пересчитать. Ставить его брокеру означало бы     |
//|  модифицировать N ордеров при каждой доливке — N лишних запросов, |
//|  каждый из которых может не пройти и оставить корзину с целями,   |
//|  часть которых от старой средней, а часть от новой. Виртуальный   |
//|  TP снимает этот класс отказов целиком: цель одна, живёт в памяти,|
//|  закрытие делается одним проходом.                                |
//|                                                                  |
//|  Стоп при этом ВСЕГДА брокерский: он обязан пережить обрыв связи  |
//|  и падение советника. Виртуальный стоп — это отсутствие стопа.     |
//+------------------------------------------------------------------+
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| Состояние одной корзины (на тактику × направление).              |
//+------------------------------------------------------------------+
struct BasketState
{
   ENUM_TACTIC tactic;
   int         magic;
   int         direction;        // DIR_LONG / DIR_SHORT
   int         positions;        // сколько позиций сейчас
   int         addons_done;      // сколько доливок сделано
   double      weighted_avg;     // средневзвешенная цена входа
   double      total_volume;
   double      virtual_tp;       // цель корзины (0 = нет корзины)
   double      first_entry;      // цена первого входа — от неё уровни доливок
   double      atr_at_entry;     // ATR на момент открытия: шаг доливок не должен «плыть»
   datetime    opened_at;
   int         bars_held;

   void Clear()
   {
      tactic       = TACTIC_NONE;
      magic        = 0;
      direction    = DIR_NONE;
      positions    = 0;
      addons_done  = 0;
      weighted_avg = 0.0;
      total_volume = 0.0;
      virtual_tp   = 0.0;
      first_entry  = 0.0;
      atr_at_entry = 0.0;
      opened_at    = 0;
      bars_held    = 0;
   }
};

//+------------------------------------------------------------------+
//| Пересчёт средневзвешенной и виртуальной цели по факту у брокера.  |
//|                                                                  |
//| Источник истины — ПОЗИЦИИ БРОКЕРА, а не память советника. После   |
//| перезапуска, ручного вмешательства или частичного отказа память   |
//| врёт, а брокер нет.                                              |
//+------------------------------------------------------------------+
bool RecalcBasket(const string symbol, const int magic, BasketState &st)
{
   double total_vol = 0.0, weighted = 0.0;
   int    count     = 0;
   int    dir       = DIR_NONE;
   double first     = 0.0;
   datetime earliest = 0;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != magic) continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol) continue;

      double vol   = PositionGetDouble(POSITION_VOLUME);
      double price = PositionGetDouble(POSITION_PRICE_OPEN);
      datetime t   = (datetime)PositionGetInteger(POSITION_TIME);
      ENUM_POSITION_TYPE ptype = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

      total_vol += vol;
      weighted  += price * vol;
      count++;
      dir = (ptype == POSITION_TYPE_BUY) ? DIR_LONG : DIR_SHORT;

      if(earliest == 0 || t < earliest) { earliest = t; first = price; }
   }

   if(count == 0 || total_vol <= 0.0)
   {
      st.positions    = 0;
      st.total_volume = 0.0;
      st.weighted_avg = 0.0;
      st.virtual_tp   = 0.0;
      return(false);
   }

   st.positions    = count;
   st.total_volume = total_vol;
   st.weighted_avg = weighted / total_vol;
   st.direction    = dir;
   st.opened_at    = earliest;
   if(st.first_entry <= 0.0) st.first_entry = first;

   //--- цель от средневзвешенной. ATR берётся тот, что был на входе:
   //    иначе цель «дышит» вместе с рынком и корзина никогда не
   //    закрывается по заранее известному уровню.
   double tp_dist = st.atr_at_entry * TP_ATR_Mult;
   if(tp_dist <= 0.0) { st.virtual_tp = 0.0; return(true); }

   st.virtual_tp = (dir == DIR_LONG) ? st.weighted_avg + tp_dist
                                     : st.weighted_avg - tp_dist;
   return(true);
}

//+------------------------------------------------------------------+
//| Достигнута ли виртуальная цель.                                  |
//+------------------------------------------------------------------+
bool VirtualTPReached(const string symbol, const BasketState &st)
{
   if(st.virtual_tp <= 0.0 || st.positions <= 0) return(false);

   if(st.direction == DIR_LONG)
   {
      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      return(bid >= st.virtual_tp);
   }
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   return(ask <= st.virtual_tp);
}

//+------------------------------------------------------------------+
//| Уровень следующей доливки от ПЕРВОГО входа.                      |
//|                                                                  |
//| От первого, а не от средневзвешенной — иначе уровни сползают за   |
//| ценой и корзина набирается бесконечно мелкими шагами, обходя      |
//| ограничение глубины по существу, соблюдая его по букве.           |
//+------------------------------------------------------------------+
double NextAddonPrice(const BasketState &st)
{
   if(!EnableAveraging) return(0.0);
   if(st.addons_done >= MaxOrdersPerBasket - 1) return(0.0);
   if(st.first_entry <= 0.0 || st.atr_at_entry <= 0.0) return(0.0);

   //--- шаг k-й доливки: base * mult^(k-1), при mult=1 равномерно
   double step = st.atr_at_entry * AddonStepATR;
   double cum  = 0.0;
   for(int k = 0; k <= st.addons_done; k++)
      cum += step * MathPow(AddonStepMultiplier, (double)k);

   return((st.direction == DIR_LONG) ? st.first_entry - cum : st.first_entry + cum);
}

//+------------------------------------------------------------------+
//| Пора ли доливать.                                                |
//+------------------------------------------------------------------+
bool AddonDue(const string symbol, const BasketState &st)
{
   double lvl = NextAddonPrice(st);
   if(lvl <= 0.0) return(false);

   if(st.direction == DIR_LONG)
      return(SymbolInfoDouble(symbol, SYMBOL_BID) <= lvl);
   return(SymbolInfoDouble(symbol, SYMBOL_ASK) >= lvl);
}

//+------------------------------------------------------------------+
//| Текущий плавающий результат корзины в деньгах.                   |
//+------------------------------------------------------------------+
double BasketFloatingPnL(const string symbol, const int magic)
{
   double pnl = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != magic) continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol) continue;
      pnl += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   return(pnl);
}

//+------------------------------------------------------------------+
//| Закрыть все позиции корзины. Возвращает число закрытых.          |
//|                                                                  |
//| Три попытки: реквота на закрытии — обычное дело, а недозакрытая   |
//| корзина опаснее незакрытой вовсе, потому что виртуальная цель уже |
//| снята и остаток остаётся без управления.                          |
//+------------------------------------------------------------------+
int CloseBasket(CTrade &trade, const string symbol, const int magic)
{
   int closed = 0;
   for(int attempt = 0; attempt < 3; attempt++)
   {
      bool any = false;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0) continue;
         if(PositionGetInteger(POSITION_MAGIC) != magic) continue;
         if(PositionGetString(POSITION_SYMBOL) != symbol) continue;
         any = true;
         if(trade.PositionClose(ticket)) closed++;
      }
      if(!any) break;
   }
   return(closed);
}

//+------------------------------------------------------------------+
//| Трейлинг по СРЕДНЕЙ цене корзины.                                |
//|                                                                  |
//| Перенос идеи из Setura (ManageTrailingStop), но с двумя отличиями.|
//|                                                                  |
//| ПЕРВОЕ: считаем от средневзвешенной, а не от каждой позиции по    |
//| отдельности. У корзины одна экономика — защищать её надо целиком, |
//| иначе первая позиция уйдёт в безубыток, пока последняя ещё глубоко|
//| в минусе, и «защищённость» окажется иллюзией.                     |
//|                                                                  |
//| ВТОРОЕ: в безубыток входит КОМИССИЯ. Стоп, выставленный ровно на  |
//| средней цене, закрывает корзину в минус на величину комиссии и    |
//| спреда — то есть «безубыток», который таковым не является. Это    |
//| тихая утечка, заметная только на длинной дистанции.               |
//+------------------------------------------------------------------+
double BreakevenPrice(const string symbol, const BasketState &st)
{
   if(st.positions <= 0 || st.total_volume <= 0.0) return(0.0);

   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_value <= 0.0 || tick_size <= 0.0) return(st.weighted_avg);

   //--- комиссия обеих сторон на весь объём корзины
   double commission = BrokerCommission * st.total_volume * 2.0;
   double price_per_money = tick_size / (tick_value * st.total_volume);
   double offset = commission * price_per_money;

   return((st.direction == DIR_LONG) ? st.weighted_avg + offset
                                     : st.weighted_avg - offset);
}

//+------------------------------------------------------------------+
//| Уровень трейлинга или 0, если трейлить рано.                     |
//+------------------------------------------------------------------+
double TrailingStopLevel(const string symbol, const BasketState &st)
{
   if(!EnableAvgTrailing || st.positions <= 0) return(0.0);
   if(st.atr_at_entry <= 0.0) return(0.0);

   double price = (st.direction == DIR_LONG)
                  ? SymbolInfoDouble(symbol, SYMBOL_BID)
                  : SymbolInfoDouble(symbol, SYMBOL_ASK);
   if(price <= 0.0) return(0.0);

   double be = BreakevenPrice(symbol, st);
   double progress = (st.direction == DIR_LONG) ? (price - be) : (be - price);

   //--- порог запуска отсчитывается от БЕЗУБЫТКА, а не от средней:
   //    иначе трейлинг стартует, когда корзина ещё в минусе на комиссию
   if(progress < st.atr_at_entry * TrailStartATR) return(0.0);

   double dist = st.atr_at_entry * TrailDistanceATR;
   double level = (st.direction == DIR_LONG) ? price - dist : price + dist;

   if(TrailOnlyInProfit)
   {
      bool protects = (st.direction == DIR_LONG) ? (level >= be) : (level <= be);
      if(!protects) return(0.0);
   }
   return(level);
}
