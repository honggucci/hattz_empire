"""
QWAS AI Team Session Manager v2
YAML 기반 대화 백업 시스템

구조:
  conversations/
  ├── README.yaml           # 새 세션 시작시 읽을 파일
  ├── index.yaml            # 전체 세션 인덱스
  └── daily/
      └── YYYY/MM/DD/
          └── session_HHMMSS_title.yaml
"""
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

try:
    import yaml
except ImportError:
    yaml = None
    print("[WARNING] PyYAML not installed. Run: pip install pyyaml")


@dataclass
class Message:
    """단일 메시지"""
    role: str  # user, assistant, system
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    agent: Optional[str] = None  # PM, Secretary, QA, Strategist, etc.
    metadata: dict = field(default_factory=dict)


@dataclass
class Session:
    """세션 정보"""
    session_id: str
    timestamp: str
    title: str
    status: str  # in_progress, completed, archived
    messages: list[Message]
    summary: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    changes: dict = field(default_factory=dict)
    decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)


class SessionManager:
    """
    세션 관리자 v2 - YAML 기반, 날짜별 폴더 구조

    사용법:
        sm = SessionManager()
        sm.start_session("RSI 전략 개발")
        sm.add_message("user", "RSI 기반 진입 조건 만들어줘")
        sm.add_message("assistant", "RSI 전략을 설계하겠습니다.", agent="PM")
        sm.complete_session(summary="RSI 전략 초안 완성", decisions=["RSI 30/70 사용"])
    """

    def __init__(self, base_dir: str = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path(__file__).parent / "conversations"
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # daily 폴더 생성
        (self.base_dir / "daily").mkdir(exist_ok=True)

        self.current_session: Optional[Session] = None
        self._auto_save = True

        # 초기화시 README, index 생성
        self._ensure_meta_files()

    def _ensure_meta_files(self):
        """README.yaml, index.yaml 생성"""
        readme_file = self.base_dir / "README.yaml"
        if not readme_file.exists():
            readme = {
                "_instruction": "새 세션 시작 시 이 파일들을 순서대로 읽으세요",
                "read_order": [
                    {"file": "index.yaml", "purpose": "최근 세션 목록", "when": "컨텍스트 파악"},
                ],
                "project_summary": {
                    "name": "QWAS AI Team",
                    "description": "Multi-AI Collaboration System",
                    "agents": ["PM (Claude)", "Secretary (GPT)", "QA (GPT-o1)", "Strategist (GPT-o1)", "Archivist (Gemini)"]
                },
                "folder_structure": {
                    "daily/YYYY/MM/DD/": "날짜별 세션 저장",
                    "session_HHMMSS_title.yaml": "개별 세션 파일"
                }
            }
            self._write_yaml(readme_file, readme)

        index_file = self.base_dir / "index.yaml"
        if not index_file.exists():
            index = {
                "total_sessions": 0,
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "daily_sessions": {},
                "tags": {},
                "topics": {}
            }
            self._write_yaml(index_file, index)

    def start_session(self, title: str = "Untitled Session", tags: list = None) -> str:
        """
        새 세션 시작

        Args:
            title: 세션 제목 (예: "RSI 전략 개발", "버그 수정")
            tags: 태그 목록 (예: ["strategy", "rsi", "backtest"])

        Returns:
            session_id
        """
        now = datetime.now()
        session_id = now.strftime("%Y-%m-%d_%H%M%S")

        self.current_session = Session(
            session_id=session_id,
            timestamp=now.isoformat(),
            title=title,
            status="in_progress",
            messages=[],
            tags=tags or []
        )

        # 날짜별 폴더 생성
        date_path = self.base_dir / "daily" / now.strftime("%Y/%m/%d")
        date_path.mkdir(parents=True, exist_ok=True)

        self._save_session()
        print(f"[Session] Started: {session_id} - {title}")
        return session_id

    def add_message(
        self,
        role: str,
        content: str,
        agent: str = None,
        metadata: dict = None
    ) -> Message:
        """
        메시지 추가

        Args:
            role: user, assistant, system
            content: 메시지 내용
            agent: 에이전트 이름 (PM, Secretary, QA, Strategist, Archivist)
            metadata: 추가 메타데이터

        Returns:
            Message
        """
        if not self.current_session:
            self.start_session()

        msg = Message(
            role=role,
            content=content,
            agent=agent,
            metadata=metadata or {}
        )

        self.current_session.messages.append(msg)

        if self._auto_save:
            self._save_session()

        return msg

    def complete_session(
        self,
        summary: str = None,
        decisions: list = None,
        action_items: list = None,
        changes: dict = None
    ):
        """
        세션 완료 처리

        Args:
            summary: 세션 요약
            decisions: 결정사항 목록
            action_items: 후속 작업 목록
            changes: 변경된 파일/내용
        """
        if not self.current_session:
            return

        self.current_session.status = "completed"

        if summary:
            self.current_session.summary = {"description": summary}
        if decisions:
            self.current_session.decisions = decisions
        if action_items:
            self.current_session.action_items = action_items
        if changes:
            self.current_session.changes = changes

        self._save_session()
        self._update_index()

        print(f"[Session] Completed: {self.current_session.session_id}")

    def _save_session(self):
        """현재 세션을 YAML로 저장"""
        if not self.current_session or not yaml:
            return

        s = self.current_session
        now = datetime.fromisoformat(s.timestamp)

        # 파일 경로: daily/YYYY/MM/DD/session_HHMMSS_title.yaml
        date_path = self.base_dir / "daily" / now.strftime("%Y/%m/%d")
        date_path.mkdir(parents=True, exist_ok=True)

        # 제목에서 파일명 안전하게 생성
        safe_title = "".join(c if c.isalnum() or c in "._- " else "_" for c in s.title)[:30]
        safe_title = safe_title.strip().replace(" ", "_")

        filename = f"session_{now.strftime('%H%M%S')}_{safe_title}.yaml"
        filepath = date_path / filename

        # 세션 데이터 구성
        session_data = {
            "session_id": s.session_id,
            "timestamp": s.timestamp,
            "title": s.title,
            "status": s.status,
            "tags": s.tags,
            "summary": s.summary if s.summary else None,
            "decisions": s.decisions if s.decisions else None,
            "action_items": s.action_items if s.action_items else None,
            "changes": s.changes if s.changes else None,
            "messages": [
                {
                    "role": m.role,
                    "agent": m.agent,
                    "timestamp": m.timestamp,
                    "content": m.content
                }
                for m in s.messages
            ]
        }

        # None 값 제거
        session_data = {k: v for k, v in session_data.items() if v is not None}

        self._write_yaml(filepath, session_data)

    def _update_index(self):
        """index.yaml 업데이트"""
        if not self.current_session or not yaml:
            return

        index_file = self.base_dir / "index.yaml"

        # 기존 인덱스 로드
        if index_file.exists():
            index = self._read_yaml(index_file)
        else:
            index = {"total_sessions": 0, "daily_sessions": {}, "tags": {}, "topics": {}}

        s = self.current_session
        date_str = s.session_id.split("_")[0]  # YYYY-MM-DD

        # daily_sessions 업데이트
        if date_str not in index.get("daily_sessions", {}):
            index["daily_sessions"][date_str] = {
                "path": f"daily/{date_str.replace('-', '/')}/",
                "files": [],
                "count": 0,
                "topics": []
            }

        day_info = index["daily_sessions"][date_str]

        # 파일명 추가
        now = datetime.fromisoformat(s.timestamp)
        safe_title = "".join(c if c.isalnum() or c in "._- " else "_" for c in s.title)[:30]
        safe_title = safe_title.strip().replace(" ", "_")
        filename = f"session_{now.strftime('%H%M%S')}_{safe_title}.yaml"

        if filename not in day_info["files"]:
            day_info["files"].append(filename)
            day_info["count"] = len(day_info["files"])

        # topics 업데이트
        if s.title not in day_info["topics"]:
            day_info["topics"].append(s.title)

        # tags 인덱스 업데이트
        for tag in s.tags:
            if tag not in index.get("tags", {}):
                index["tags"][tag] = []
            if date_str not in index["tags"][tag]:
                index["tags"][tag].append(date_str)

        # 총 세션 수 업데이트
        total = sum(d.get("count", 0) for d in index.get("daily_sessions", {}).values())
        index["total_sessions"] = total
        index["last_updated"] = datetime.now().strftime("%Y-%m-%d")

        self._write_yaml(index_file, index)

    def _write_yaml(self, filepath: Path, data: dict):
        """YAML 파일 쓰기"""
        if not yaml:
            return
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def _read_yaml(self, filepath: Path) -> dict:
        """YAML 파일 읽기"""
        if not yaml:
            return {}
        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def load_session(self, session_id: str) -> Optional[Session]:
        """
        세션 로드

        Args:
            session_id: YYYY-MM-DD_HHMMSS 형식

        Returns:
            Session or None
        """
        # session_id에서 날짜/시간 파싱
        try:
            date_part, time_part = session_id.split("_")
            date_path = self.base_dir / "daily" / date_part.replace("-", "/")
        except ValueError:
            print(f"[Session] Invalid session_id format: {session_id}")
            return None

        if not date_path.exists():
            print(f"[Session] Date path not found: {date_path}")
            return None

        # 해당 시간으로 시작하는 파일 찾기
        for filepath in date_path.glob(f"session_{time_part}_*.yaml"):
            data = self._read_yaml(filepath)

            messages = [
                Message(
                    role=m["role"],
                    content=m["content"],
                    agent=m.get("agent"),
                    timestamp=m.get("timestamp", "")
                )
                for m in data.get("messages", [])
            ]

            self.current_session = Session(
                session_id=data["session_id"],
                timestamp=data["timestamp"],
                title=data["title"],
                status=data.get("status", "completed"),
                messages=messages,
                summary=data.get("summary", {}),
                tags=data.get("tags", []),
                decisions=data.get("decisions", []),
                action_items=data.get("action_items", [])
            )

            print(f"[Session] Loaded: {session_id} ({len(messages)} messages)")
            return self.current_session

        print(f"[Session] Session file not found: {session_id}")
        return None

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """최근 세션 목록"""
        index_file = self.base_dir / "index.yaml"
        if not index_file.exists():
            return []

        index = self._read_yaml(index_file)
        sessions = []

        # 날짜 역순으로 정렬
        for date_str in sorted(index.get("daily_sessions", {}).keys(), reverse=True):
            day_info = index["daily_sessions"][date_str]
            for filename in reversed(day_info.get("files", [])):
                sessions.append({
                    "date": date_str,
                    "file": filename,
                    "path": day_info["path"] + filename
                })
                if len(sessions) >= limit:
                    return sessions

        return sessions

    def get_context(self, max_messages: int = 50) -> str:
        """현재 세션 컨텍스트 (AI에게 전달용)"""
        if not self.current_session:
            return ""

        messages = self.current_session.messages[-max_messages:]

        lines = [f"# Session: {self.current_session.title}", ""]
        for msg in messages:
            agent_str = f"[{msg.agent}]" if msg.agent else ""
            lines.append(f"**{msg.role.upper()}** {agent_str}")
            lines.append(msg.content[:1000])
            lines.append("")

        return "\n".join(lines)

    def export_yaml(self, session_id: str = None) -> str:
        """세션을 YAML 문자열로 내보내기"""
        if session_id:
            self.load_session(session_id)

        if not self.current_session or not yaml:
            return ""

        s = self.current_session
        data = {
            "session_id": s.session_id,
            "title": s.title,
            "status": s.status,
            "summary": s.summary,
            "decisions": s.decisions,
            "action_items": s.action_items,
            "messages": [
                {"role": m.role, "agent": m.agent, "content": m.content[:500]}
                for m in s.messages
            ]
        }
        return yaml.dump(data, allow_unicode=True, default_flow_style=False)


# =============================================================================
# Singleton & Quick Access
# =============================================================================

_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """SessionManager 싱글톤"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def quick_log(role: str, content: str, agent: str = None):
    """빠른 메시지 저장"""
    sm = get_session_manager()
    if not sm.current_session:
        sm.start_session("Auto Session")
    sm.add_message(role, content, agent)


# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI entry point"""
    import sys

    sm = SessionManager()

    if len(sys.argv) < 2:
        print("""
QWAS Session Manager v2 (YAML)

Usage:
  python session_manager.py list              - List recent sessions
  python session_manager.py show <id>         - Show session (YYYY-MM-DD_HHMMSS)
  python session_manager.py new <title>       - Start new session
  python session_manager.py complete          - Complete current session
""")
        return

    cmd = sys.argv[1]

    if cmd == "list":
        sessions = sm.list_sessions()
        print(f"\n{'='*60}")
        print("Recent Sessions")
        print(f"{'='*60}")
        for s in sessions:
            print(f"  [{s['date']}] {s['file']}")
        print()

    elif cmd == "show" and len(sys.argv) > 2:
        session_id = sys.argv[2]
        session = sm.load_session(session_id)
        if session:
            print(sm.export_yaml())

    elif cmd == "new" and len(sys.argv) > 2:
        title = " ".join(sys.argv[2:])
        sm.start_session(title)

    elif cmd == "complete":
        if sm.current_session:
            sm.complete_session()
        else:
            print("No active session")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
