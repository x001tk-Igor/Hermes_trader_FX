//+------------------------------------------------------------------+
//|                                                   Indicators.mqh |
//|  Единая точка владения хэндлами индикаторов.                     |
//|                                                                  |
//|  ПОЧЕМУ ЦЕНТРАЛИЗОВАНО. Двенадцать тактик просят пересекающиеся   |
//|  наборы: ATR(14) нужен всем, EMA200 — четырём, ADX(14) — пяти.    |
//|  Если каждая заводит свой хэндл, терминал держит 30+ дублей на    |
//|  график, а в тестере это прямо переводится в часы прогона.        |
//|  Здесь хэндл создаётся один раз на (тип, период) и переиспользуется.|
//+------------------------------------------------------------------+
#property strict

#define IND_MAX 32

//+------------------------------------------------------------------+
//| Кэш хэндлов с ленивым созданием.                                 |
//+------------------------------------------------------------------+
class CIndicators
{
private:
   string            m_symbol;
   ENUM_TIMEFRAMES   m_tf;
   string            m_keys[IND_MAX];
   int               m_handles[IND_MAX];
   int               m_count;

   int               Find(const string key)
   {
      for(int i = 0; i < m_count; i++)
         if(m_keys[i] == key) return(m_handles[i]);
      return(INVALID_HANDLE);
   }

   int               Store(const string key, const int handle)
   {
      if(m_count >= IND_MAX)
      {
         Print("CIndicators: превышен лимит хэндлов ", IND_MAX, " — ключ ", key);
         return(handle);
      }
      m_keys[m_count]    = key;
      m_handles[m_count] = handle;
      m_count++;
      return(handle);
   }

public:
                     CIndicators() { m_count = 0; m_symbol = ""; m_tf = PERIOD_CURRENT; }

   void              Init(const string symbol, const ENUM_TIMEFRAMES tf)
   {
      m_symbol = symbol;
      m_tf     = tf;
      m_count  = 0;
   }

   void              Release()
   {
      for(int i = 0; i < m_count; i++)
         if(m_handles[i] != INVALID_HANDLE) IndicatorRelease(m_handles[i]);
      m_count = 0;
   }

   int               ATR(const int period)
   {
      string key = "ATR" + IntegerToString(period);
      int h = Find(key);
      if(h != INVALID_HANDLE) return(h);
      return(Store(key, iATR(m_symbol, m_tf, period)));
   }

   int               EMA(const int period)
   {
      string key = "EMA" + IntegerToString(period);
      int h = Find(key);
      if(h != INVALID_HANDLE) return(h);
      return(Store(key, iMA(m_symbol, m_tf, period, 0, MODE_EMA, PRICE_CLOSE)));
   }

   int               SMA(const int period)
   {
      string key = "SMA" + IntegerToString(period);
      int h = Find(key);
      if(h != INVALID_HANDLE) return(h);
      return(Store(key, iMA(m_symbol, m_tf, period, 0, MODE_SMA, PRICE_CLOSE)));
   }

   int               ADX(const int period)
   {
      string key = "ADX" + IntegerToString(period);
      int h = Find(key);
      if(h != INVALID_HANDLE) return(h);
      return(Store(key, iADX(m_symbol, m_tf, period)));
   }

   int               RSI(const int period)
   {
      string key = "RSI" + IntegerToString(period);
      int h = Find(key);
      if(h != INVALID_HANDLE) return(h);
      return(Store(key, iRSI(m_symbol, m_tf, period, PRICE_CLOSE)));
   }

   int               BB(const int period, const double deviation)
   {
      string key = "BB" + IntegerToString(period) + "_" + DoubleToString(deviation, 1);
      int h = Find(key);
      if(h != INVALID_HANDLE) return(h);
      return(Store(key, iBands(m_symbol, m_tf, period, 0, deviation, PRICE_CLOSE)));
   }

   int               Count() const { return(m_count); }
};

//+------------------------------------------------------------------+
//| Одно значение буфера индикатора со сдвигом.                      |
//|                                                                  |
//| Возвращает false при любой неудаче — вызывающий ОБЯЗАН проверить. |
//| Тихая подстановка нуля здесь означала бы торговлю по выдуманному  |
//| числу: ADX=0 прошёл бы любой фильтр «меньше порога».              |
//+------------------------------------------------------------------+
bool IndValue(const int handle, const int buffer, const int shift, double &out)
{
   out = 0.0;
   if(handle == INVALID_HANDLE) return(false);
   double tmp[];
   if(CopyBuffer(handle, buffer, shift, 1, tmp) != 1) return(false);
   if(!MathIsValidNumber(tmp[0])) return(false);
   out = tmp[0];
   return(true);
}

//+------------------------------------------------------------------+
//| Несколько значений подряд (для проверок «растёт/падает»).        |
//+------------------------------------------------------------------+
bool IndSeries(const int handle, const int buffer, const int shift, const int count, double &out[])
{
   ArrayFree(out);
   if(handle == INVALID_HANDLE || count <= 0) return(false);
   if(CopyBuffer(handle, buffer, shift, count, out) != count) return(false);
   for(int i = 0; i < count; i++)
      if(!MathIsValidNumber(out[i])) return(false);
   return(true);
}
