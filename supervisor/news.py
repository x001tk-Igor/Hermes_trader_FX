"""news.py — ForexFactory calendar provider (переиспользован из fx_agent_v2).

FF XML → события по валютам пары → high_impact 30/60 мин окна.
Кэш на диске (cache_ttl_sec), fallback на stale-кеш при сбое сети.
Все 5 Hermes-пар покрыты картой _SYMBOL_CURRENCIES.
"""
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Set
from zoneinfo import ZoneInfo

import requests

from models import NewsContext, NewsEvent

logger = logging.getLogger("hermes_supervisor")

_ET_TZ = ZoneInfo("America/New_York")

_SYMBOL_CURRENCIES: dict = {
    "EURUSD": {"EUR", "USD"}, "GBPUSD": {"GBP", "USD"}, "USDCAD": {"USD", "CAD"},
    "EURAUD": {"EUR", "AUD"}, "NZDCAD": {"NZD", "CAD"}, "EURGBP": {"EUR", "GBP"},
    "AUDUSD": {"AUD", "USD"}, "USDJPY": {"USD", "JPY"}, "USDCHF": {"USD", "CHF"},
    "GBPJPY": {"GBP", "JPY"}, "EURJPY": {"EUR", "JPY"}, "AUDCAD": {"AUD", "CAD"},
    "NZDUSD": {"NZD", "USD"}, "GBPCAD": {"GBP", "CAD"}, "EURCAD": {"EUR", "CAD"},
    "AUDNZD": {"AUD", "NZD"}, "CADCHF": {"CAD", "CHF"}, "CHFJPY": {"CHF", "JPY"},
    "EURCHF": {"EUR", "CHF"}, "GBPCHF": {"GBP", "CHF"}, "AUDCHF": {"AUD", "CHF"},
    "AUDJPY": {"AUD", "JPY"}, "CADJPY": {"CAD", "JPY"}, "NZDJPY": {"NZD", "JPY"},
    "EURNZD": {"EUR", "NZD"}, "NZDCHF": {"NZD", "CHF"}, "GBPAUD": {"GBP", "AUD"},
}


def symbol_currencies(symbol: str) -> Set[str]:
    if symbol in _SYMBOL_CURRENCIES:
        return _SYMBOL_CURRENCIES[symbol]
    s = symbol.upper()
    if len(s) == 6:
        return {s[:3], s[3:]}
    return set()


class NewsProvider:
    def __init__(self, config: dict, cache_dir: str = "cache"):
        self.cfg = config
        self._cache_path = Path(cache_dir) / "ff_calendar.xml"
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cached_xml: Optional[str] = None
        self._cache_fetched_at: Optional[datetime] = None

    def get_context(self, symbol: str, hours_ahead: int = 4,
                    _now: Optional[datetime] = None) -> NewsContext:
        now = _now or datetime.now(timezone.utc)
        window_end = now + timedelta(hours=hours_ahead)
        currencies = symbol_currencies(symbol)
        all_events = self._load_events()
        upcoming = [e for e in all_events
                    if now <= e.timestamp_utc <= window_end and e.currency in currencies]
        upcoming.sort(key=lambda e: e.timestamp_utc)
        high_60 = [e for e in upcoming
                   if e.impact == "high" and e.timestamp_utc <= now + timedelta(minutes=60)]
        high_30 = [e for e in upcoming
                   if e.impact == "high" and e.timestamp_utc <= now + timedelta(minutes=30)]
        return NewsContext(upcoming=upcoming, high_impact_within_60min=high_60,
                           high_impact_within_30min=high_30)

    def _load_events(self) -> List[NewsEvent]:
        xml_text = self._get_xml()
        return _parse_xml(xml_text) if xml_text else []

    def _get_xml(self) -> Optional[str]:
        ttl_sec = self.cfg.get("cache_ttl_sec", 3600)
        now = datetime.now(timezone.utc)
        if self._cached_xml and self._cache_fetched_at:
            if (now - self._cache_fetched_at).total_seconds() < ttl_sec:
                return self._cached_xml
        url = self.cfg.get("url", "https://nfs.faireconomy.media/ff_calendar_thisweek.xml")
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            text = resp.text
            self._cached_xml = text
            self._cache_fetched_at = now
            self._cache_path.write_text(text, encoding="utf-8")
            logger.info("FF calendar fetched (%d bytes)", len(text))
            return text
        except Exception as exc:
            logger.warning("FF fetch failed: %s — disk cache", exc)
        if self._cache_path.exists():
            age_sec = now.timestamp() - self._cache_path.stat().st_mtime
            if age_sec < 86400:
                return self._cache_path.read_text(encoding="utf-8")
            logger.warning("Disk cache too old (%.0fh)", age_sec / 3600)
        return None


def _parse_xml(xml_text: str) -> List[NewsEvent]:
    events: List[NewsEvent] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.error("FF XML parse error: %s", exc)
        return events
    for node in root.findall("event"):
        title = _text(node, "title")
        country = _text(node, "country").upper()
        date_s = _text(node, "date")
        time_s = _text(node, "time")
        impact_s = _text(node, "impact").lower()
        if not title or not country or not date_s:
            continue
        ts = _parse_event_utc(date_s, time_s)
        if ts is None:
            continue
        events.append(NewsEvent(title=title, country=country, currency=country,
                                 impact=impact_s, timestamp_utc=ts))
    return events


def _text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return child.text.strip() if (child is not None and child.text) else ""


def _parse_event_utc(date_str: str, time_str: str) -> Optional[datetime]:
    try:
        date = datetime.strptime(date_str.strip(), "%b %d, %Y")
    except ValueError:
        return None
    t = time_str.strip().lower()
    if not t or t in ("tentative", "all day"):
        hour, minute = 0, 0
    else:
        hour, minute = 0, 0
        for fmt in ("%I:%M%p", "%I%p"):
            try:
                p = datetime.strptime(t, fmt)
                hour, minute = p.hour, p.minute
                break
            except ValueError:
                continue
    dt_et = datetime(date.year, date.month, date.day, hour, minute, tzinfo=_ET_TZ)
    return dt_et.astimezone(timezone.utc)


def format_news_list(news: NewsContext) -> str:
    if not news.upcoming:
        return "  (нет событий в ближайшие часы)"
    lines = []
    for e in news.upcoming:
        lines.append(f"  {e.timestamp_utc.strftime('%H:%M')} UTC  impact={e.impact:<6}  "
                     f"{e.currency}  {e.title}")
    return "\n".join(lines)