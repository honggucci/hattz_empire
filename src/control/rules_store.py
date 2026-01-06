"""
Hattz Empire - Rules Store
세션별 규정 JSON 파일 로딩
"""
from __future__ import annotations
import json
from pathlib import Path
from .rules import SessionRules


class RulesStore:
    def __init__(self, base_dir: str = "config/session_rules"):
        self.base_dir = Path(base_dir)

    def load(self, session_id: str) -> SessionRules:
        fp = self.base_dir / f"{session_id}.json"
        if not fp.exists():
            raise FileNotFoundError(f"Session rules not found: {fp}")
        data = json.loads(fp.read_text(encoding="utf-8"))
        return SessionRules(**data)

    def exists(self, session_id: str) -> bool:
        fp = self.base_dir / f"{session_id}.json"
        return fp.exists()

    def list_sessions(self) -> list[str]:
        """사용 가능한 세션 규정 목록"""
        if not self.base_dir.exists():
            return []
        return [f.stem for f in self.base_dir.glob("*.json")]
