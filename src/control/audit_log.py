"""
Hattz Empire - Audit Logger
CEO 완성본 - JSONL 감사 로깅
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class AuditLogger:
    def __init__(self, out_dir: str = "logs/audit"):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.fp = self.out_dir / "events.jsonl"

    def write_event(self, event: Dict[str, Any]) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        line = json.dumps({"ts": ts, **event}, ensure_ascii=False)
        with self.fp.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
