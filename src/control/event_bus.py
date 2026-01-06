"""
Hattz Empire - Event Bus
CEO 완성본 - 이벤트 발행 + Audit 연동
"""
from __future__ import annotations
from typing import Dict, Any
from .audit_log import AuditLogger


class EventBus:
    def __init__(self, logger: AuditLogger = None):
        self.logger = logger or AuditLogger()

    def emit(self, kind: str, payload: Dict[str, Any]) -> None:
        self.logger.write_event({"kind": kind, "payload": payload})
        print(f"[EventBus] {kind}: {payload.get('session_id', 'N/A')}")
