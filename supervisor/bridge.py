"""bridge.py — файловый мост EA↔supervisor (Hermes FX).

EA пишет (в <DataDir>/MQL5/Files/HermesFX/):
  heartbeat_<sym>.json  — {ts, symbol, tick, baskets, equity, last_action, magic_base}
  journal_<sym>.jsonl   — построчный лог действий (OPEN/ADDON/TP_HIT/SKIP/...)

Supervisor пишет:
  permissions_<sym>.json — constrictive-only рычаги (Bridge.mqh парсит подстроками)
  supervisor_heartbeat.json — пульс супервизора (для мониторинга)

Atomic write (.tmp → rename) — EA читает без гонок. Per-symbol файлы (Bridge.mqh
после правки читает permissions_<sym>.json первым, permissions.json как global fallback).
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from models import Decision, decision_to_permissions

logger = logging.getLogger("hermes_supervisor")


class HermesBridge:
    def __init__(self, folder: str, state_max_age_sec: int = 300):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.state_max_age_sec = state_max_age_sec

    # ── paths ───────────────────────────────────────────────────────────────
    def heartbeat_path(self, symbol: str) -> Path:
        return self.folder / f"heartbeat_{symbol}.json"

    def permissions_path(self, symbol: str) -> Path:
        return self.folder / f"permissions_{symbol}.json"

    def global_permissions_path(self) -> Path:
        return self.folder / "permissions.json"

    def supervisor_heartbeat_path(self) -> Path:
        return self.folder / "supervisor_heartbeat.json"

    # ── read EA heartbeat ───────────────────────────────────────────────────
    def read_heartbeat(self, symbol: str) -> Optional[dict]:
        p = self.heartbeat_path(symbol)
        if not p.exists():
            return None
        age = time.time() - p.stat().st_mtime
        if age > self.state_max_age_sec:
            return {"_stale": True, "age_sec": age}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    # ── write permissions_<sym>.json (atomic) ───────────────────────────────
    def write_permissions(self, symbol: str, dec: Decision, tactic_name: str) -> Path:
        perm = decision_to_permissions(dec, tactic_name)
        # убираем служебные поля из JSON (EA парсит подстроками — служебные не мешают,
        # но чище без них в реальном файле)
        reason = perm.pop("_reason", "")
        tactic = perm.pop("_tactic", "")
        body = {
            "trading_enabled": perm.get("trading_enabled", True),
            "risk_multiplier": perm.get("risk_multiplier", 1.0),
            "_meta": {
                "symbol": symbol, "tactic": tactic, "reason": reason,
                "action": dec.action, "confidence": dec.confidence,
                "issued_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "duration_minutes": dec.duration_minutes,
            }
        }
        if "allowed_direction" in perm:
            body["allowed_direction"] = perm["allowed_direction"]
        return self._atomic_write(self.permissions_path(symbol), body)

    def write_global_kill(self, reason: str) -> Path:
        """Глобальный стоп на все 5 (emergency)."""
        body = {"trading_enabled": False,
                "_meta": {"reason": reason, "issued_utc":
                          datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}}
        return self._atomic_write(self.global_permissions_path(), body)

    def clear_global(self) -> None:
        """Снять global permissions.json (вернуть per-symbol управление)."""
        p = self.global_permissions_path()
        if p.exists():
            p.unlink()

    def write_supervisor_heartbeat(self, status: str, decisions: list) -> None:
        body = {
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": status,
            "decisions": [{"symbol": d["symbol"], "action": d["action"],
                           "reason": d["reason"]} for d in decisions],
        }
        self._atomic_write(self.supervisor_heartbeat_path(), body)

    # ── internal ─────────────────────────────────────────────────────────────
    def _atomic_write(self, path: Path, body: dict) -> Path:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        if path.exists():
            path.unlink()
        tmp.rename(path)
        return path