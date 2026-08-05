//+------------------------------------------------------------------+
//|                                                      Execute.mqh |
//|  Исполнение приказов. Единственное место, где советник трогает    |
//|  деньги.                                                          |
//|                                                                   |
//|  ПОЧЕМУ ОТДЕЛЬНЫЙ МОДУЛЬ. Узкая поверхность: чем меньше мест,     |
//|  откуда уходит OrderSend, тем меньше способов протащить в сделку  |
//|  необработанный отказ. Всё, что выше по слоям, решает «войти» —    |
//|  но послать приказ может только этот файл.                        |
//|                                                                   |
//|  СТОП ВСЕГДА БРОКЕРСКИЙ И ВСЕГДА ВМЕСТЕ С ОРДЕРОМ. Позиция,       |
//|  открытая без стопа с намерением «доставить его следующим          |
//|  запросом», — это позиция без стопа ровно до тех пор, пока второй  |
//|  запрос не прошёл. А он может не пройти.                          |
//+------------------------------------------------------------------+
#property strict

#include <Trade\Trade.mqh>
#include "Types.mqh"
#include "Config.mqh"

//+------------------------------------------------------------------+
//| Результат попытки исполнения.                                    |
//+------------------------------------------------------------------+
struct ExecResult
{
   bool     ok;
   ulong    ticket;
   double   price;
   double   sl;
   double   lot;
   int      retcode;
   string   error;

   void Clear()
   {
      ok = false; ticket = 0; price = 0.0; sl = 0.0; lot = 0.0;
      retcode = 0; error = "";
   }
};

//+------------------------------------------------------------------+
//| Нормализация лота под требования символа.                        |
//| Перенос NormalizeLot из Setura — обкатано на реальных отказах.    |
//+------------------------------------------------------------------+
double NormalizeLotForSymbol(const string symbol, const double lot)
{
   double lmin  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double lmax  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double lstep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(lstep <= 0.0) lstep = 0.01;

   double v = MathFloor(lot / lstep) * lstep;
   //--- знаков ровно столько, сколько в шаге: 0.01 -> 2, 0.001 -> 3
   int digits = (int)MathMax(0, MathCeil(-MathLog10(lstep) - 0.0000001));
   v = NormalizeDouble(v, digits);

   if(v < lmin) return(0.0);        // ноль = «нельзя открыть», а не «открой минимум»
   if(v > lmax) v = lmax;
   return(v);
}

//+------------------------------------------------------------------+
//| Проверка спреда перед приказом.                                  |
//+------------------------------------------------------------------+
bool SpreadAcceptable(const string symbol)
{
   if(MaxSpreadPoints <= 0) return(true);
   long spread = SymbolInfoInteger(symbol, SYMBOL_SPREAD);
   return(spread <= MaxSpreadPoints);
}

//+------------------------------------------------------------------+
//| Стоп на дистанции от цены с учётом минимального отступа брокера.  |
//|                                                                  |
//| Брокер не примет стоп ближе SYMBOL_TRADE_STOPS_LEVEL. Молча       |
//| подвинуть его дальше нельзя — это увеличит риск сверх              |
//| рассчитанного бюджета. Поэтому здесь стоп ОТОДВИГАЕТСЯ, а         |
//| вызывающий обязан пересчитать лот под новую дистанцию.            |
//+------------------------------------------------------------------+
double StopPriceFor(const string symbol, const int direction, const double entry,
                    const double distance, double &actual_distance)
{
   int    digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double point  = SymbolInfoDouble(symbol, SYMBOL_POINT);
   long   stops  = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);

   double min_dist = (double)stops * point;
   actual_distance = MathMax(distance, min_dist);

   double sl = (direction == DIR_LONG) ? entry - actual_distance
                                       : entry + actual_distance;
   return(NormalizeDouble(sl, digits));
}

//+------------------------------------------------------------------+
//| Открыть позицию (первую в корзине или доливку).                  |
//|                                                                  |
//| Три попытки: реквота — обычное дело, а несостоявшийся вход по     |
//| реквоте означает пропуск сигнала без следа в журнале.             |
//+------------------------------------------------------------------+
ExecResult OpenPositionAt(CTrade &trade, const string symbol, const int direction,
                          const int magic, const double lot, const double sl_distance,
                          const string tag)
{
   ExecResult res; res.Clear();

   double vol = NormalizeLotForSymbol(symbol, lot);
   if(vol <= 0.0)
   {
      res.error = "lot_below_min";
      return(res);
   }

   if(!SpreadAcceptable(symbol))
   {
      res.error = "spread_too_wide";
      return(res);
   }

   trade.SetExpertMagicNumber(magic);
   trade.SetTypeFillingBySymbol(symbol);

   for(int attempt = 0; attempt < 3; attempt++)
   {
      double price = (direction == DIR_LONG)
                     ? SymbolInfoDouble(symbol, SYMBOL_ASK)
                     : SymbolInfoDouble(symbol, SYMBOL_BID);
      if(price <= 0.0) { res.error = "no_price"; return(res); }

      double actual_dist = 0.0;
      double sl = StopPriceFor(symbol, direction, price, sl_distance, actual_dist);

      bool sent = (direction == DIR_LONG)
                  ? trade.Buy(vol, symbol, price, sl, 0.0, tag)
                  : trade.Sell(vol, symbol, price, sl, 0.0, tag);

      res.retcode = (int)trade.ResultRetcode();

      if(sent && (res.retcode == TRADE_RETCODE_DONE ||
                  res.retcode == TRADE_RETCODE_PLACED ||
                  res.retcode == TRADE_RETCODE_DONE_PARTIAL))
      {
         res.ok     = true;
         res.ticket = trade.ResultOrder();
         res.price  = (trade.ResultPrice() > 0.0 ? trade.ResultPrice() : price);
         res.sl     = sl;
         res.lot    = (trade.ResultVolume() > 0.0 ? trade.ResultVolume() : vol);
         return(res);
      }

      //--- повторяем только то, что имеет смысл повторять
      if(res.retcode != TRADE_RETCODE_REQUOTE &&
         res.retcode != TRADE_RETCODE_PRICE_CHANGED &&
         res.retcode != TRADE_RETCODE_PRICE_OFF)
         break;
   }

   res.error = "send_failed_" + IntegerToString(res.retcode);
   return(res);
}

//+------------------------------------------------------------------+
//| Перенести стопы всех позиций корзины на общий уровень.           |
//|                                                                  |
//| Нужно трейлингу по средней: у корзины одна средневзвешенная, и    |
//| защищать её надо целиком, а не каждую позицию по отдельности.     |
//| Возвращает число реально изменённых.                              |
//+------------------------------------------------------------------+
int MoveBasketStops(CTrade &trade, const string symbol, const int magic,
                    const double new_sl, const int direction)
{
   int moved  = 0;
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double target = NormalizeDouble(new_sl, digits);

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != magic) continue;
      if(PositionGetString(POSITION_SYMBOL) != symbol) continue;

      double cur_sl = PositionGetDouble(POSITION_SL);
      double tp     = PositionGetDouble(POSITION_TP);

      //--- двигаем ТОЛЬКО в сторону защиты. Ослабление стопа —
      //    это увеличение риска сверх рассчитанного, и делать его
      //    молча внутри трейлинга недопустимо.
      bool improves = (direction == DIR_LONG) ? (cur_sl <= 0.0 || target > cur_sl)
                                              : (cur_sl <= 0.0 || target < cur_sl);
      if(!improves) continue;

      if(trade.PositionModify(ticket, target, tp)) moved++;
   }
   return(moved);
}

//+------------------------------------------------------------------+
//| Комментарий к ордеру: по нему видно тактику прямо в терминале.    |
//| Брокеры режут длину, поэтому коротко и без кириллицы.             |
//+------------------------------------------------------------------+
string OrderTag(const ENUM_TACTIC t, const bool is_addon, const int addon_no)
{
   string base = TacticName(t);
   if(StringLen(base) > 20) base = StringSubstr(base, 0, 20);
   if(is_addon) return(base + "#a" + IntegerToString(addon_no));
   return(base);
}
