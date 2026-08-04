//+------------------------------------------------------------------+
//|                                                       Bridge.mqh |
//|  Мост к ИИ-управляющему: разрешения внутрь, журнал и пульс наружу.|
//|                                                                  |
//|  ГЛАВНЫЙ ИНВАРИАНТ: разрешения только СУЖАЮТ то, что советник и   |
//|  так готов сделать, и никогда не расширяют. Отсюда следует, что   |
//|  отсутствие файла разрешений — это НЕ запрет, а «нечего сужать».  |
//|                                                                  |
//|  Иначе советник был бы неработоспособен в тестере стратегий, где  |
//|  управляющего нет вовсе, — то есть оптимизация, ради которой всё  |
//|  строится, стала бы невозможной. Это не послабление ради удобства:|
//|  запрет по умолчанию здесь означал бы, что проверить советник     |
//|  можно только на живом счёте.                                    |
//|                                                                  |
//|  ФАЙЛ НА СИМВОЛ, а не общий. Шесть графиков — шесть экземпляров   |
//|  советника, пишущих одновременно. Общий файл в MQL5 даёт гонку и  |
//|  потерянные записи; файл на символ гарантирует ровно одного       |
//|  писателя. Срез по тактике достаётся фильтром по полю.           |
//+------------------------------------------------------------------+
#property strict

#include "Types.mqh"
#include "Config.mqh"

//+------------------------------------------------------------------+
//| Разрешения, полученные от управляющего.                          |
//+------------------------------------------------------------------+
struct Permissions
{
   bool     loaded;              // файл прочитан хоть раз
   bool     trading_enabled;     // глобальный выключатель
   double   risk_multiplier;     // множитель лота, 0..1
   bool     tactic_enabled[TACTIC_COUNT];
   int      allowed_direction;   // DIR_NONE = обе стороны, иначе только эта
   datetime read_at;

   void SetPermissive()
   {
      loaded            = false;
      trading_enabled   = true;
      risk_multiplier   = 1.0;
      allowed_direction = DIR_NONE;
      for(int i = 0; i < TACTIC_COUNT; i++) tactic_enabled[i] = true;
      read_at = 0;
   }
};

//+------------------------------------------------------------------+
//| Путь внутри MQL5\Files.                                          |
//+------------------------------------------------------------------+
string BridgePath(const string name)
{
   return(BridgeFolder + "\\" + name);
}

//+------------------------------------------------------------------+
//| Чтение permissions.json.                                         |
//|                                                                  |
//| Разбор намеренно ПРИМИТИВНЫЙ (поиск подстрок), а не полноценный   |
//| JSON-парсер: у MQL5 его нет в стандартной поставке, а свой парсер |
//| — это триста строк и класс ошибок, которого мы не хотим в коде,   |
//| распоряжающемся деньгами. Формат файла пишет наш же управляющий,  |
//| поэтому договорённость о плоской структуре дешевле общности.      |
//|                                                                  |
//| В ТЕСТЕРЕ НЕ ЧИТАЕМ ВООБЩЕ: файловые операции на каждом тике —    |
//| главная причина прогонов длиной в часы (см. mt5-env, грабля       |
//| «бэктест ползёт часами»).                                        |
//+------------------------------------------------------------------+
bool ReadPermissions(Permissions &p)
{
   if(!EnableBridge)                     { p.SetPermissive(); return(false); }
   if(MQLInfoInteger(MQL_TESTER) != 0)   { p.SetPermissive(); return(false); }

   int h = FileOpen(BridgePath("permissions.json"), FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)               { p.SetPermissive(); return(false); }

   string body = "";
   while(!FileIsEnding(h)) body += FileReadString(h);
   FileClose(h);

   if(StringLen(body) < 2)               { p.SetPermissive(); return(false); }

   p.SetPermissive();
   p.loaded  = true;
   p.read_at = TimeCurrent();

   if(StringFind(body, "\"trading_enabled\": false") >= 0 ||
      StringFind(body, "\"trading_enabled\":false")  >= 0)
      p.trading_enabled = false;

   //--- множитель риска: только СУЖАЕТ, значения > 1 игнорируются
   int pos = StringFind(body, "\"risk_multiplier\"");
   if(pos >= 0)
   {
      int colon = StringFind(body, ":", pos);
      if(colon > 0)
      {
         string tail = StringSubstr(body, colon + 1, 12);
         double v = StringToDouble(tail);
         if(v > 0.0 && v < 1.0) p.risk_multiplier = v;
      }
   }

   //--- запрет отдельных тактик по имени
   for(int i = 0; i < TACTIC_COUNT; i++)
   {
      string marker = "\"" + TacticName(TacticByIndex(i)) + "\": false";
      if(StringFind(body, marker) >= 0) p.tactic_enabled[i] = false;
   }

   if(StringFind(body, "\"allowed_direction\": \"long\"")  >= 0) p.allowed_direction = DIR_LONG;
   if(StringFind(body, "\"allowed_direction\": \"short\"") >= 0) p.allowed_direction = DIR_SHORT;

   return(true);
}

//+------------------------------------------------------------------+
//| Журнал: одна строка JSONL на действие.                           |
//|                                                                  |
//| Пишется и в тестере тоже — именно из журнала внешний агент потом  |
//| считает статистику по тактикам. Но открытие файла на КАЖДУЮ       |
//| запись в тестере недопустимо дорого, поэтому строки копятся в     |
//| буфере и сбрасываются пачкой.                                     |
//+------------------------------------------------------------------+
string g_journal_buffer = "";
int    g_journal_lines  = 0;
datetime g_last_flush   = 0;

void JournalWrite(const string symbol, const string action, const string tactic,
                  const string payload)
{
   if(!EnableBridge) return;

   string line = StringFormat(
      "{\"ts\":\"%s\",\"symbol\":\"%s\",\"action\":\"%s\",\"tactic\":\"%s\"%s}\n",
      TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS),
      symbol, action, tactic,
      (StringLen(payload) > 0 ? "," + payload : ""));

   g_journal_buffer += line;
   g_journal_lines++;
}

void JournalFlush(const string symbol, const bool force)
{
   if(!EnableBridge || g_journal_lines == 0) return;
   if(!force && (TimeCurrent() - g_last_flush) < JournalFlushSeconds) return;

   int h = FileOpen(BridgePath("journal_" + symbol + ".jsonl"),
                    FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE) return;

   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, g_journal_buffer);
   FileClose(h);

   g_journal_buffer = "";
   g_journal_lines  = 0;
   g_last_flush     = TimeCurrent();
}

//+------------------------------------------------------------------+
//| Пульс: управляющему нужно знать, какой ИМЕННО график встал.      |
//| В тестере не пишем — там некому читать.                           |
//+------------------------------------------------------------------+
void WriteHeartbeat(const string symbol, const long tick_no, const int baskets,
                    const double equity, const string last_action)
{
   if(!EnableBridge) return;
   if(MQLInfoInteger(MQL_TESTER) != 0) return;

   int h = FileOpen(BridgePath("heartbeat_" + symbol + ".json"),
                    FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE) return;

   FileWriteString(h, StringFormat(
      "{\"ts\":\"%s\",\"symbol\":\"%s\",\"tick\":%I64d,\"baskets\":%d,"
      "\"equity\":%.2f,\"last_action\":\"%s\",\"magic_base\":%d}\n",
      TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS),
      symbol, tick_no, baskets, equity, last_action, MagicBase));
   FileClose(h);
}

//+------------------------------------------------------------------+
//| Создать папку моста при старте.                                  |
//+------------------------------------------------------------------+
void EnsureBridgeFolder()
{
   if(!EnableBridge) return;
   if(MQLInfoInteger(MQL_TESTER) != 0) return;
   FolderCreate(BridgeFolder);
}
