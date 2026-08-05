//+------------------------------------------------------------------+
//|                                                    Hermes_FX.mq5 |
//|  Мультитактический советник под управлением ИИ-портфельщика.     |
//|                                                                  |
//|  ОДИН ИНСТРУМЕНТ НА ГРАФИК. Двенадцать тактик внутри, у каждой    |
//|  свой magic — то есть каждая ведёт СВОЮ корзину и не мешает       |
//|  соседям. Связывает их не счётчик позиций, а общий бюджет риска.  |
//|                                                                  |
//|  ЧЕТЫРЕ СЛОЯ С ЖЁСТКОЙ ГРАНИЦЕЙ:                                 |
//|    1. Сигнальный   — тактики, чистые функции баров (Tactics.mqh)  |
//|    2. Арбитр       — кого пустить в остаток бюджета               |
//|    3. Движок       — корзина, виртуальный TP (Basket.mqh)         |
//|    4. Мост         — разрешения внутрь, журнал наружу (Bridge)    |
//|                                                                  |
//|  Граница нужна ради измеримости: тактику можно прогнать в         |
//|  изоляции только если она не знает о позициях и лотах.           |
//|                                                                  |
//|  РАБОТАЕТ БЕЗ УПРАВЛЯЮЩЕГО. В тестере стратегий моста нет —       |
//|  советник обязан торговать автономно, иначе оптимизация           |
//|  невозможна. Разрешения только сужают, никогда не расширяют.      |
//+------------------------------------------------------------------+
#property copyright "Hermes FX"
#property link      "https://github.com/x001tk-Igor/Hermes_trader_FX"
#property version   "1.01"
#property strict
#property description "Мультитактический советник: 12 тактик, раздельные magic, бюджет риска"

#include "Modules/Types.mqh"
#include "Modules/Config.mqh"
#include "Modules/Indicators.mqh"
#include "Modules/RiskBudget.mqh"
#include "Modules/Basket.mqh"
#include "Modules/Execute.mqh"
#include "Modules/Tactics.mqh"
#include "Modules/Bridge.mqh"

//--- глобальное состояние -------------------------------------------
CTrade        g_trade;
CIndicators   g_ind;
Permissions   g_perm;
BasketState   g_baskets[TACTIC_COUNT];
datetime      g_last_bar_time = 0;
datetime      g_cooldown_until[TACTIC_COUNT];
long          g_tick_no       = 0;
string        g_last_action   = "init";
string        g_symbol;
BarContext    g_ctx;                       // контекст закрытого бара, обновляется раз в бар
bool          ctx_ok          = false;
bool          g_addons_blocked[TACTIC_COUNT];

//+------------------------------------------------------------------+
//| Инициализация                                                    |
//+------------------------------------------------------------------+
int OnInit()
{
   g_symbol = _Symbol;

   //--- проверки, без которых торговля была бы торговлей вслепую
   if(MaxOrdersPerBasket < 1)
   {
      Print("ОШИБКА: MaxOrdersPerBasket должен быть >= 1");
      return(INIT_PARAMETERS_INCORRECT);
   }
   if(SL_ATR_Mult <= 0.0)
   {
      Print("ОШИБКА: SL_ATR_Mult должен быть > 0 — позиция без стопа недопустима");
      return(INIT_PARAMETERS_INCORRECT);
   }
   if(EnableRiskBudget && MaxPortfolioRiskPct <= 0.0)
   {
      Print("ОШИБКА: бюджет риска включён, но MaxPortfolioRiskPct <= 0");
      return(INIT_PARAMETERS_INCORRECT);
   }

   g_ind.Init(g_symbol, PERIOD_CURRENT);
   g_perm.SetPermissive();

   for(int i = 0; i < TACTIC_COUNT; i++)
   {
      g_baskets[i].Clear();
      g_baskets[i].tactic = TacticByIndex(i);
      g_baskets[i].magic  = TacticMagic(TacticByIndex(i));
      g_cooldown_until[i] = 0;
      g_addons_blocked[i] = false;
   }

   g_trade.SetExpertMagicNumber(MagicBase);   // конкретный magic ставится перед каждым приказом
   g_trade.SetMarginMode();
   g_trade.SetTypeFillingBySymbol(g_symbol);
   g_trade.SetDeviationInPoints(20);

   EnsureBridgeFolder();

   if(PollSeconds > 0) EventSetTimer(PollSeconds);

   PrintFormat("Hermes FX v1.01 (Ф2) старт | %s | magic база %d | усреднение %s | бюджет риска %s",
               g_symbol, MagicBase,
               (EnableAveraging ? "ВКЛ" : "выкл"),
               (EnableRiskBudget ? "ВКЛ" : "выкл"));

   int active = 0;
   for(int i = 0; i < TACTIC_COUNT; i++)
      if(TacticEnabled(TacticByIndex(i))) active++;
   PrintFormat("Активных тактик: %d из %d", active, TACTIC_COUNT);

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Деинициализация                                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   JournalFlush(g_symbol, true);
   g_ind.Release();
   PrintFormat("Hermes FX стоп | причина %d | тиков %I64d", reason, g_tick_no);
}

//+------------------------------------------------------------------+
//| Новый бар?                                                       |
//|                                                                  |
//| Вся сигнальная работа — РАЗ В БАР. Опрос двенадцати тактик на     |
//| каждом тике превратил бы годовой прогон в часы (см. mt5-env,      |
//| грабля «бэктест ползёт часами»): там это дало 27-кратную разницу. |
//+------------------------------------------------------------------+
bool IsNewBar()
{
   datetime t = iTime(g_symbol, PERIOD_CURRENT, 0);
   if(t == 0 || t == g_last_bar_time) return(false);
   g_last_bar_time = t;
   return(true);
}

//+------------------------------------------------------------------+
//| Торговое окно                                                    |
//+------------------------------------------------------------------+
bool InTradeWindow()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(TradeStartHourUTC == TradeEndHourUTC) return(true);        // окно не задано
   if(TradeStartHourUTC < TradeEndHourUTC)
      return(dt.hour >= TradeStartHourUTC && dt.hour < TradeEndHourUTC);
   return(dt.hour >= TradeStartHourUTC || dt.hour < TradeEndHourUTC);
}

//+------------------------------------------------------------------+
//| Ведение открытых корзин: доливки, цель, таймаут, аварийный стоп. |
//|                                                                  |
//| Идёт ПЕРЕД поиском новых входов: защитить уже вложенные деньги    |
//| важнее, чем найти новые. Тот же порядок, что у стоп-крана в       |
//| предыдущем проекте, и по той же причине.                          |
//+------------------------------------------------------------------+
void ManageBaskets()
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);

   for(int i = 0; i < TACTIC_COUNT; i++)
   {
      if(!RecalcBasket(g_symbol, g_baskets[i].magic, g_baskets[i]))
      {
         //--- корзины нет: сбросить память о ней
         if(g_baskets[i].first_entry > 0.0)
         {
            g_baskets[i].first_entry  = 0.0;
            g_baskets[i].addons_done  = 0;
            g_baskets[i].atr_at_entry = 0.0;
            g_addons_blocked[i]       = false;
            g_cooldown_until[i] = TimeCurrent() + CooldownBars * PeriodSeconds(PERIOD_CURRENT);
         }
         continue;
      }

      string tname = TacticName(g_baskets[i].tactic);

      //--- 1. аварийный стоп по просадке символа
      if(SymbolDDStopPct > 0.0)
      {
         double pnl = BasketFloatingPnL(g_symbol, g_baskets[i].magic);
         if(pnl <= -equity * SymbolDDStopPct / 100.0)
         {
            int n = CloseBasket(g_trade, g_symbol, g_baskets[i].magic);
            JournalWrite(g_symbol, "DD_STOP", tname,
                         StringFormat("\"closed\":%d,\"pnl\":%.2f", n, pnl));
            g_last_action = "DD_STOP " + tname;
            continue;
         }
      }

      //--- 2. виртуальная цель
      if(VirtualTPReached(g_symbol, g_baskets[i]))
      {
         double pnl = BasketFloatingPnL(g_symbol, g_baskets[i].magic);
         int n = CloseBasket(g_trade, g_symbol, g_baskets[i].magic);
         JournalWrite(g_symbol, "TP_HIT", tname,
                      StringFormat("\"closed\":%d,\"pnl\":%.2f,\"tp\":%.5f",
                                   n, pnl, g_baskets[i].virtual_tp));
         g_last_action = "TP " + tname;
         continue;
      }

      //--- 3. таймаут
      if(MaxBarsInTrade > 0 && g_baskets[i].opened_at > 0)
      {
         int held = (int)((TimeCurrent() - g_baskets[i].opened_at) / PeriodSeconds(PERIOD_CURRENT));
         if(held >= MaxBarsInTrade)
         {
            double pnl = BasketFloatingPnL(g_symbol, g_baskets[i].magic);
            int n = CloseBasket(g_trade, g_symbol, g_baskets[i].magic);
            JournalWrite(g_symbol, "TIMEOUT", tname,
                         StringFormat("\"closed\":%d,\"pnl\":%.2f,\"bars\":%d", n, pnl, held));
            g_last_action = "TIMEOUT " + tname;
            continue;
         }
      }

      //--- 4. жива ли гипотеза тактики
      if(ctx_ok)
      {
         ENUM_HYPOTHESIS hyp = EvalHypothesis(g_baskets[i].tactic, g_ctx, g_ind,
                                              g_baskets[i].direction);
         if(hyp == HYP_CLOSE)
         {
            double pnl = BasketFloatingPnL(g_symbol, g_baskets[i].magic);
            int n = CloseBasket(g_trade, g_symbol, g_baskets[i].magic);
            JournalWrite(g_symbol, "HYPOTHESIS_DEAD", tname,
                         StringFormat("\"closed\":%d,\"pnl\":%.2f", n, pnl));
            g_last_action = "HYP_DEAD " + tname;
            continue;
         }
         if(hyp == HYP_NO_ADDONS) g_addons_blocked[i] = true;
      }

      //--- 5. трейлинг по средней (по умолчанию выключен)
      double trail = TrailingStopLevel(g_symbol, g_baskets[i]);
      if(trail > 0.0)
      {
         int moved = MoveBasketStops(g_trade, g_symbol, g_baskets[i].magic,
                                     trail, g_baskets[i].direction);
         if(moved > 0)
            JournalWrite(g_symbol, "TRAIL", tname,
                         StringFormat("\"moved\":%d,\"sl\":%.5f", moved, trail));
      }

      //--- 6. доливка
      if(EnableAveraging && !g_addons_blocked[i] && AddonDue(g_symbol, g_baskets[i]))
         ExecuteAddon(i);
   }
}

//+------------------------------------------------------------------+
//| Доливка в существующую корзину.                                  |
//|                                                                  |
//| Лот берётся ТОТ ЖЕ, что у первой позиции: плоский набор, без      |
//| мартингейла. Решение принято на уровне проекта — множитель лота   |
//| превращает ограниченный риск в неограниченный, и никакой cap по   |
//| глубине этого не компенсирует.                                    |
//+------------------------------------------------------------------+
void ExecuteAddon(const int i)
{
   BasketState st = g_baskets[i];
   if(st.positions <= 0 || st.total_volume <= 0.0) return;

   double lot = st.total_volume / (double)st.positions;   // плоский лот корзины
   double sl_distance = st.atr_at_entry * SL_ATR_Mult;
   if(sl_distance <= 0.0) return;

   //--- доливка тоже обязана уложиться в бюджет: корзина могла быть
   //    открыта, когда свободных денег было больше
   if(EnableRiskBudget)
   {
      double rt = 0.0, rs = 0.0;
      CalcOpenRisk(g_symbol, MagicBase, rt, rs);
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      if(rt >= equity * MaxPortfolioRiskPct / 100.0 ||
         rs >= equity * MaxSymbolRiskPct    / 100.0)
      {
         if(LogSkips)
            JournalWrite(g_symbol, "SKIP", TacticName(st.tactic),
                         "\"stage\":\"addon\",\"reason\":\"risk_budget\"");
         return;
      }
   }

   string tag = OrderTag(st.tactic, true, st.addons_done + 1);
   ExecResult r = OpenPositionAt(g_trade, g_symbol, st.direction, st.magic,
                                 lot, sl_distance, tag);

   if(r.ok)
   {
      g_baskets[i].addons_done++;
      g_last_action = "ADDON " + TacticName(st.tactic);
      JournalWrite(g_symbol, "ADDON", TacticName(st.tactic),
                   StringFormat("\"n\":%d,\"price\":%.5f,\"sl\":%.5f,\"lot\":%.2f",
                                g_baskets[i].addons_done, r.price, r.sl, r.lot));
      //--- цель пересчитается на следующем проходе RecalcBasket
   }
   else
   {
      JournalWrite(g_symbol, "ADDON_FAIL", TacticName(st.tactic),
                   StringFormat("\"error\":\"%s\"", r.error));
   }
}

//+------------------------------------------------------------------+
//| Поиск новых входов (Ф3: арбитраж и исполнение)                   |
//+------------------------------------------------------------------+
void LookForEntries()
{
   if(!g_perm.trading_enabled) return;
   if(!InTradeWindow()) return;

   if(!ctx_ok) return;
   if(ATRAnomaly(g_ctx)) return;

   for(int i = 0; i < TACTIC_COUNT; i++)
   {
      ENUM_TACTIC t = TacticByIndex(i);
      if(!TacticEnabled(t))        continue;
      if(!g_perm.tactic_enabled[i]) continue;
      if(g_baskets[i].positions > 0) continue;                 // корзина уже открыта
      if(TimeCurrent() < g_cooldown_until[i]) continue;

      Signal sig;
      if(!EvalTactic(t, g_ctx, g_ind, sig)) continue;
      if(!sig.valid) continue;

      //--- направление может быть запрещено параметром или управляющим
      if(sig.direction == DIR_LONG  && !AllowBuy)  continue;
      if(sig.direction == DIR_SHORT && !AllowSell) continue;
      if(g_perm.allowed_direction != DIR_NONE &&
         sig.direction != g_perm.allowed_direction) continue;

      OpenNewBasket(i, sig);
   }
}

//+------------------------------------------------------------------+
//| Открытие новой корзины по сигналу тактики.                       |
//|                                                                  |
//| Здесь сходятся все слои: тактика дала расстояние до стопа, бюджет |
//| превратил его в лот, исполнение отправило приказ. Тактика при     |
//| этом по-прежнему не знает ни про лот, ни про бюджет — граница     |
//| держится.                                                        |
//+------------------------------------------------------------------+
void OpenNewBasket(const int i, const Signal &sig)
{
   string tname = TacticName(sig.tactic);

   double sl_distance = sig.sl_distance;
   if(sl_distance <= 0.0) sl_distance = g_ctx.atr * SL_ATR_Mult;
   if(sl_distance <= 0.0) return;

   //--- лот из остатка бюджета, на ПОЛНУЮ глубину корзины
   double lot = 0.0;
   if(EnableRiskBudget)
   {
      double rt = 0.0, rs = 0.0;
      CalcOpenRisk(g_symbol, MagicBase, rt, rs);
      string why = "";
      lot = CalcBasketLot(g_symbol, sl_distance, PlannedBasketPositions(),
                          AccountInfoDouble(ACCOUNT_EQUITY), rt, rs, why);
      if(lot <= 0.0)
      {
         if(LogSkips)
            JournalWrite(g_symbol, "SKIP", tname,
                         StringFormat("\"stage\":\"entry\",\"reason\":\"%s\"", why));
         return;
      }
   }
   else
   {
      //--- бюджет выключен: одиночный исследовательский прогон.
      //    Минимальный лот, чтобы результат мерился в R, а не в деньгах.
      lot = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
   }

   //--- множитель управляющего только СУЖАЕТ
   if(g_perm.risk_multiplier > 0.0 && g_perm.risk_multiplier < 1.0)
      lot *= g_perm.risk_multiplier;

   ExecResult r = OpenPositionAt(g_trade, g_symbol, sig.direction, TacticMagic(sig.tactic),
                                 lot, sl_distance, OrderTag(sig.tactic, false, 0));

   if(r.ok)
   {
      //--- ATR фиксируется на входе: от него считаются и цель, и шаги
      //    доливок. Плавающий ATR сделал бы уровни непредсказуемыми.
      g_baskets[i].first_entry  = r.price;
      g_baskets[i].atr_at_entry = g_ctx.atr;
      g_baskets[i].tp_distance  = sig.tp_distance;
      g_baskets[i].direction    = sig.direction;
      g_baskets[i].addons_done  = 0;
      g_addons_blocked[i]       = false;

      g_last_action = "OPEN " + tname;
      JournalWrite(g_symbol, "OPEN", tname,
                   StringFormat("\"dir\":%d,\"price\":%.5f,\"sl\":%.5f,\"lot\":%.2f,"
                                "\"atr\":%.5f,\"conf\":%.2f,\"reason\":\"%s\"",
                                sig.direction, r.price, r.sl, r.lot,
                                g_ctx.atr, sig.confidence, sig.reason));
   }
   else
   {
      JournalWrite(g_symbol, "OPEN_FAIL", tname,
                   StringFormat("\"error\":\"%s\"", r.error));
   }
}

//+------------------------------------------------------------------+
//| Пятничное закрытие. Одна проверка вместо шести параметров Setura. |
//+------------------------------------------------------------------+
void CheckFridayClose()
{
   if(!CloseAllFriday) return;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_week != 5 || dt.hour < FridayCloseHourUTC) return;

   for(int i = 0; i < TACTIC_COUNT; i++)
   {
      if(g_baskets[i].positions <= 0) continue;
      double pnl = BasketFloatingPnL(g_symbol, g_baskets[i].magic);
      int n = CloseBasket(g_trade, g_symbol, g_baskets[i].magic);
      JournalWrite(g_symbol, "FRIDAY_CLOSE", TacticName(g_baskets[i].tactic),
                   StringFormat("\"closed\":%d,\"pnl\":%.2f", n, pnl));
   }
   g_last_action = "FRIDAY_CLOSE";
}

//+------------------------------------------------------------------+
//| Основной цикл                                                    |
//+------------------------------------------------------------------+
void ProcessCycle()
{
   g_tick_no++;

   ManageBaskets();          // защита вложенного — всегда первым

   if(IsNewBar())
   {
      ctx_ok = BuildBarContext(g_symbol, g_ind, g_ctx);
      ReadPermissions(g_perm);
      CheckFridayClose();
      LookForEntries();
      JournalFlush(g_symbol, false);
   }
}

void OnTick()
{
   ProcessCycle();
}

//+------------------------------------------------------------------+
//| Таймер — для работы вне тиков (тихий рынок, ведение позиций).    |
//| В тестере таймер не нужен: там тики идут сплошным потоком.        |
//+------------------------------------------------------------------+
void OnTimer()
{
   if(MQLInfoInteger(MQL_TESTER) != 0) return;

   int open = 0;
   for(int i = 0; i < TACTIC_COUNT; i++)
      if(g_baskets[i].positions > 0) open++;

   WriteHeartbeat(g_symbol, g_tick_no, open,
                  AccountInfoDouble(ACCOUNT_EQUITY), g_last_action);
   JournalFlush(g_symbol, false);
}
