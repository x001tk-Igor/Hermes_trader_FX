//+------------------------------------------------------------------+
//|                                                   RiskBudget.mqh |
//|  Связывающий лимит советника — ДЕНЬГИ, а не число позиций.       |
//|                                                                  |
//|  ЗАЧЕМ ЭТОТ СЛОЙ СУЩЕСТВУЕТ. В ТЗ лимит задан счётчиком: три     |
//|  позиции на символ, три инструмента на портфель. При двенадцати   |
//|  тактиках с раздельными magic счётчик перестаёт что-либо          |
//|  ограничивать: каждая тактика открывает СВОЮ корзину, и полный    |
//|  выбой двенадцати корзин на одном символе стоит ~15% депозита при |
//|  заявленной максимальной просадке 5%. На трёх символах — 45%.     |
//|                                                                  |
//|  Поэтому здесь считается не «сколько открыто», а «сколько будет   |
//|  потеряно, если всё открытое выбьет одновременно». Новая корзина  |
//|  получает лот из ОСТАТКА бюджета. Кончился остаток — вход         |
//|  отклоняется, сколько бы тактик ни просилось.                     |
//|                                                                  |
//|  Свойство, ради которого всё это: просадка ограничена ПО         |
//|  ПОСТРОЕНИЮ, а не по совпадению параметров.                       |
//+------------------------------------------------------------------+
#property strict

//+------------------------------------------------------------------+
//| Риск открытой корзины в деньгах: сумма по всем её позициям        |
//| расстояния до стопа, умноженного на стоимость пункта.             |
//|                                                                   |
//| Позиция БЕЗ стопа считается риском на всю дистанцию до нуля —     |
//| это заведомо больше правды, и так и задумано: незнание не имеет   |
//| права выглядеть как отсутствие риска.                             |
//+------------------------------------------------------------------+
double PositionRiskMoney(const string symbol, const double open_price, const double sl,
                         const double volume, const ENUM_POSITION_TYPE type)
{
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_size <= 0.0 || tick_value <= 0.0) return(0.0);

   double distance;
   if(sl <= 0.0)
      distance = open_price;                        // стопа нет — считаем по-худшему
   else
      distance = (type == POSITION_TYPE_BUY) ? (open_price - sl) : (sl - open_price);

   if(distance <= 0.0) return(0.0);                 // стоп уже в прибыли — риска нет
   return(distance / tick_size * tick_value * volume);
}

//+------------------------------------------------------------------+
//| Суммарный риск по счёту и по символу.                            |
//| Считает ТОЛЬКО свои позиции (magic в диапазоне советника).        |
//| Чужие не наши: трогать нельзя, а считать в свой бюджет — значит   |
//| отдать управление риском постороннему коду.                       |
//+------------------------------------------------------------------+
void CalcOpenRisk(const string symbol, const int magic_base,
                  double &risk_total, double &risk_symbol)
{
   risk_total  = 0.0;
   risk_symbol = 0.0;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;

      long magic = PositionGetInteger(POSITION_MAGIC);
      if(magic < magic_base || magic > magic_base + 99) continue;   // не наша

      string sym   = PositionGetString(POSITION_SYMBOL);
      double price = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double vol   = PositionGetDouble(POSITION_VOLUME);
      ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

      double r = PositionRiskMoney(sym, price, sl, vol, type);
      risk_total += r;
      if(sym == symbol) risk_symbol += r;
   }
}

//+------------------------------------------------------------------+
//| Лот новой корзины из остатка бюджета.                            |
//|                                                                  |
//| sl_distance — расстояние до стопа В ЦЕНЕ для ОДНОЙ позиции.      |
//| planned_positions — сколько позиций корзина наберёт при полном   |
//| доливе (усреднение включено -> MaxOrdersPerBasket, иначе 1).     |
//|                                                                  |
//| Возвращает 0.0, если бюджета не хватает даже на минимальный лот. |
//| Ноль здесь — законный ответ «входа нет», а не ошибка.            |
//+------------------------------------------------------------------+
double CalcBasketLot(const string symbol, const double sl_distance,
                     const int planned_positions, const double equity,
                     const double risk_total_open, const double risk_symbol_open,
                     string &reject_reason)
{
   reject_reason = "";

   if(sl_distance <= 0.0 || planned_positions <= 0)
   {
      reject_reason = "bad_sl_or_positions";
      return(0.0);
   }

   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tick_size <= 0.0 || tick_value <= 0.0)
   {
      reject_reason = "no_tick_data";
      return(0.0);
   }

   //--- сколько денег ещё можно поставить под удар
   double cap_portfolio = equity * MaxPortfolioRiskPct / 100.0;
   double cap_symbol    = equity * MaxSymbolRiskPct    / 100.0;
   double want_basket   = equity * BasketRiskPct       / 100.0;

   double free_portfolio = cap_portfolio - risk_total_open;
   double free_symbol    = cap_symbol    - risk_symbol_open;

   double allowed = MathMin(want_basket, MathMin(free_portfolio, free_symbol));
   if(allowed <= 0.0)
   {
      reject_reason = (free_symbol <= 0.0) ? "symbol_budget_exhausted" : "portfolio_budget_exhausted";
      return(0.0);
   }

   //--- деньги -> лот. Риск считаем на ПОЛНУЮ глубину корзины: иначе
   //    бюджет будет исчерпан доливками, которых он не предвидел.
   double money_per_lot = (sl_distance / tick_size) * tick_value * (double)planned_positions;
   if(money_per_lot <= 0.0)
   {
      reject_reason = "zero_money_per_lot";
      return(0.0);
   }

   double lot = allowed / money_per_lot;

   //--- нормализация под требования символа
   double lot_min  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double lot_max  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(lot_step <= 0.0) lot_step = 0.01;

   lot = MathFloor(lot / lot_step) * lot_step;
   lot = NormalizeDouble(lot, 2);

   if(lot > lot_max) lot = lot_max;

   double floor_lot = MathMax(lot_min, MinLot);
   if(lot < floor_lot)
   {
      reject_reason = "lot_below_min";
      return(0.0);
   }

   return(lot);
}

//+------------------------------------------------------------------+
//| Сколько позиций корзина наберёт при полном доливе.                |
//+------------------------------------------------------------------+
int PlannedBasketPositions()
{
   if(!EnableAveraging) return(1);
   return(MathMax(1, MaxOrdersPerBasket));
}
