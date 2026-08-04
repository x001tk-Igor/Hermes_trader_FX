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
#property version   "1.00"
#property strict
#property description "Мультитактический советник: 12 тактик, раздельные magic, бюджет риска"

#include "Modules/Types.mqh"
#include "Modules/Config.mqh"
#include "Modules/Indicators.mqh"
#include "Modules/RiskBudget.mqh"
#include "Modules/Basket.mqh"
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
   }

   g_trade.SetExpertMagicNumber(MagicBase);   // конкретный magic ставится перед каждым приказом
   g_trade.SetMarginMode();
   g_trade.SetTypeFillingBySymbol(g_symbol);
   g_trade.SetDeviationInPoints(20);

   EnsureBridgeFolder();

   if(PollSeconds > 0) EventSetTimer(PollSeconds);

   PrintFormat("Hermes FX v1.00 (Ф0) старт | %s | magic база %d | усреднение %s | бюджет риска %s",
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

      //--- 4. доливка (Ф1: исполнение)
      if(EnableAveraging && AddonDue(g_symbol, g_baskets[i]))
      {
         // исполнение доливки — Ф1
      }
   }
}

//+------------------------------------------------------------------+
//| Поиск новых входов (Ф3: арбитраж и исполнение)                   |
//+------------------------------------------------------------------+
void LookForEntries()
{
   if(!g_perm.trading_enabled) return;
   if(!InTradeWindow()) return;

   BarContext ctx;
   if(!BuildBarContext(g_symbol, g_ind, ctx)) return;
   if(ATRAnomaly(ctx)) return;

   for(int i = 0; i < TACTIC_COUNT; i++)
   {
      ENUM_TACTIC t = TacticByIndex(i);
      if(!TacticEnabled(t))        continue;
      if(!g_perm.tactic_enabled[i]) continue;
      if(g_baskets[i].positions > 0) continue;                 // корзина уже открыта
      if(TimeCurrent() < g_cooldown_until[i]) continue;

      Signal sig;
      if(!EvalTactic(t, ctx, g_ind, sig)) continue;
      if(!sig.valid) continue;

      // арбитраж, расчёт лота и исполнение — Ф1.5 и Ф3
   }
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
      ReadPermissions(g_perm);
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
