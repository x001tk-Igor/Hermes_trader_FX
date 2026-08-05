//+------------------------------------------------------------------+
//|  ontester_template.mqh  (Hermes FX — smoothness-aware variant)    |
//|  Сбор результатов оптимизации MT5 в CSV (скилл mt5-walkforward).   |
//|                                                                  |
//|  ПОДКЛЮЧЕНИЕ В СОВЕТНИК (1 строка после блока input):            |
//|     #include "ontester_template.mqh"                            |
//|                                                                  |
//|  При оптимизации каждый проход пишет строку в                   |
//|  <DataDir>\MQL5\Files\<OPT_CSV>. Формат (разделитель ';'):       |
//|     pass;params;profit;pf;recovery;dd_pct;trades;sharpe;         |
//|     winrate;avg_win;avg_loss;score                               |
//|                                                                  |
//|  Робастный критерий (score) = Recovery × Sharpe-фактор (ПЛАВНОСТЬ).|
//|  Гоняет генетику на гладкую эквити, не на lottery (high recovery  |
//|  + low sharpe = jagged). Sharpe~[-3,3] -> factor [0.2, 4].        |
//|  Штраф за <30 сделок сохранён (анти-оверфит). НЕ Net Profit.      |
//|  Доп. winrate/avg_win/avg_loss — для пост-анализа lottery-index    |
//|  (payoff*(1-WR)) из equity_smoothness.py.                         |
//+------------------------------------------------------------------+
#ifndef MT5_OPT_COLLECTOR_MQH
#define MT5_OPT_COLLECTOR_MQH

input string OPT_CSV = "opt_results.csv";   // выходной CSV результатов оптимизации

//--- АГЕНТ: критерий прохода + метрики во фрейм -------------------
double OnTester()
{
   double profit = TesterStatistics(STAT_PROFIT);
   double pf     = TesterStatistics(STAT_PROFIT_FACTOR);
   double rf     = TesterStatistics(STAT_RECOVERY_FACTOR);
   double dd     = TesterStatistics(STAT_EQUITYDD_PERCENT);
   double trades = TesterStatistics(STAT_TRADES);
   double sharpe = TesterStatistics(STAT_SHARPE_RATIO);
   double profTr = TesterStatistics(STAT_PROFIT_TRADES);
   double lossTr = TesterStatistics(STAT_LOSS_TRADES);
   double grossP = TesterStatistics(STAT_GROSS_PROFIT);
   double grossL = TesterStatistics(STAT_GROSS_LOSS);

   double winrate = (trades > 0) ? profTr / trades * 100.0 : 0.0;
   double avgWin  = (profTr > 0) ? grossP / profTr : 0.0;
   double avgLoss = (lossTr > 0) ? MathAbs(grossL) / lossTr : 0.0;

   // Smoothness-aware: recovery (profit/maxDD) × sharpe-фактор (return/vol).
   // Плавная+прибыльная эквити = high recovery AND high sharpe. Lottery
   // (high recovery + low sharpe = jagged) даунгейтится низким фактором.
   double smoothFactor = MathMax(0.2, sharpe + 1.0);
   double score = (trades >= 30.0) ? (rf * smoothFactor)
                                   : (rf * smoothFactor * (trades / 30.0));

   double payload[10];
   payload[0] = profit;
   payload[1] = pf;
   payload[2] = rf;
   payload[3] = dd;
   payload[4] = trades;
   payload[5] = sharpe;
   payload[6] = winrate;
   payload[7] = avgWin;
   payload[8] = avgLoss;
   FrameAdd("m", 1, score, payload);
   return score;
}

//--- ГЛАВНЫЙ: создать CSV с заголовком до оптимизации --------------
void OnTesterInit()
{
   int h = FileOpen(OPT_CSV, FILE_WRITE | FILE_CSV | FILE_ANSI, ';');
   if(h != INVALID_HANDLE)
   {
      FileWrite(h, "pass", "params", "profit", "pf", "recovery", "dd_pct", "trades", "sharpe",
                     "winrate", "avg_win", "avg_loss", "score");
      FileClose(h);
   }
}

//--- ГЛАВНЫЙ: после каждого прохода дописать строку в CSV ----------
void OnTesterPass()
{
   ulong  pass;
   string name;
   long   id;
   double value;
   double data[];

   while(FrameNext(pass, name, id, value, data))
   {
      if(name != "m" || ArraySize(data) < 9) continue;

      // значения оптимизируемых input этого прохода ("Name=Value" строки)
      string params[];
      uint   cnt = 0;
      string pstr = "";
      if(FrameInputs(pass, params, cnt))
         for(uint i = 0; i < cnt; i++)
            pstr += params[i] + " ";

      int h = FileOpen(OPT_CSV, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI, ';');
      if(h != INVALID_HANDLE)
      {
         FileSeek(h, 0, SEEK_END);
         FileWrite(h, (long)pass, pstr,
                   data[0], data[1], data[2], data[3], data[4], data[5],
                   data[6], data[7], data[8], value);
         FileClose(h);
      }
   }
}

//--- ГЛАВНЫЙ: финализация после всей оптимизации -------------------
void OnTesterDeinit()
{
   // CSV дописывается построчно в OnTesterPass — здесь ничего не требуется.
   // Хук обязателен парно с OnTesterInit (MQL5 error 375).
}

#endif // MT5_OPT_COLLECTOR_MQH