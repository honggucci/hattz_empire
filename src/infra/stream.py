"""
Hattz Empire - Stream Logger
절대 유실 방지 append-only 로그

모든 메시지는 즉시 파일에 기록.
메모리에만 있으면 안 됨.

구조:
  conversations/
  ├── stream/
  │   └── 2026-01-02.jsonl    # 하루치 전체 (append-only)
  └── tasks/
      └── task_001.yaml       # Task별 정리
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, asdict, field
import uuid
import threading

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class Message:
    """로그 메시지"""
    id: str                          # 고유 ID
    t: str                           # 타임스탬프 (ISO format)
    task_id: Optional[str]           # Task ID (있으면)
    from_agent: str                  # 발신자
    to_agent: Optional[str]          # 수신자 (있으면)
    type: str                        # request/response/error/decision/state
    content: Any                     # 내용
    parent_id: Optional[str] = None  # 이전 메시지 참조
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """딕셔너리 변환 (None 제외)"""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    def to_json(self) -> str:
        """JSON 문자열"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class StreamLogger:
    """
    Append-only 스트림 로거

    규칙:
    - 모든 메시지 즉시 파일에 append
    - 절대 수정/삭제 안 함
    - 하루에 하나의 파일
    - 스레드 안전

    사용법:
        stream = StreamLogger()
        msg_id = stream.log("excavator", "pm", "response", {"result": "..."})
    """

    def __init__(self, base_dir: str = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path(__file__).parent / "conversations" / "stream"

        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._current_task_id: Optional[str] = None
        self._last_msg_id: Optional[str] = None

    def _get_today_file(self) -> Path:
        """오늘 날짜 파일"""
        return self.base_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"

    def _generate_id(self) -> str:
        """고유 메시지 ID 생성"""
        now = datetime.now()
        return f"msg_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    def set_task(self, task_id: str):
        """현재 Task 설정"""
        self._current_task_id = task_id

    def log(
        self,
        from_agent: str,
        to_agent: Optional[str],
        msg_type: str,
        content: Any,
        task_id: str = None,
        parent_id: str = None,
        metadata: dict = None
    ) -> str:
        """
        메시지 로그 (즉시 파일에 append)

        Args:
            from_agent: 발신자 (ceo, excavator.claude, pm, etc.)
            to_agent: 수신자 (없으면 None)
            msg_type: request, response, error, decision, state
            content: 내용 (문자열 또는 딕셔너리)
            task_id: Task ID (없으면 현재 Task 사용)
            parent_id: 이전 메시지 ID (체인 추적용)
            metadata: 추가 메타데이터

        Returns:
            생성된 메시지 ID
        """
        msg = Message(
            id=self._generate_id(),
            t=datetime.now().isoformat(),
            task_id=task_id or self._current_task_id,
            from_agent=from_agent,
            to_agent=to_agent,
            type=msg_type,
            content=content,
            parent_id=parent_id or self._last_msg_id,
            metadata=metadata or {}
        )

        # 즉시 파일에 append (스레드 안전)
        with self._lock:
            filepath = self._get_today_file()

            # 라인 번호 계산
            line_number = 0
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    line_number = sum(1 for _ in f)
            line_number += 1

            with open(filepath, "a", encoding="utf-8") as f:
                f.write(msg.to_json() + "\n")
            self._last_msg_id = msg.id

        # SQLite 인덱스에 추가 (Gemini 검색용)
        try:
            from .storage.index import get_index
            get_index().add(msg.to_dict(), str(filepath), line_number)
        except Exception:
            pass  # 인덱스 실패해도 로그는 유지

        return msg.id

    def log_dual_engine(
        self,
        role: str,
        input_data: Any,
        engine_1_output: Any,
        engine_2_output: Any,
        merged_output: Any,
        task_id: str = None
    ) -> str:
        """
        듀얼 엔진 결과 로그 (3개 메시지)

        Returns:
            merged 메시지 ID
        """
        tid = task_id or self._current_task_id

        # Engine 1
        id1 = self.log(
            f"{role}.engine_1", "merger", "response",
            engine_1_output, task_id=tid
        )

        # Engine 2
        id2 = self.log(
            f"{role}.engine_2", "merger", "response",
            engine_2_output, task_id=tid
        )

        # Merged
        id3 = self.log(
            f"{role}.merged", None, "response",
            merged_output, task_id=tid,
            metadata={"sources": [id1, id2]}
        )

        return id3

    def log_state_change(
        self,
        changed_by: str,
        before: Any,
        after: Any,
        reason: str = "",
        task_id: str = None
    ) -> str:
        """
        상태 변경 로그 (롤백용)
        """
        return self.log(
            changed_by, None, "state",
            {"before": before, "after": after, "reason": reason},
            task_id=task_id
        )

    def read_today(self) -> list[dict]:
        """오늘 로그 읽기"""
        filepath = self._get_today_file()
        if not filepath.exists():
            return []

        messages = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    messages.append(json.loads(line))
        return messages

    def read_date(self, date_str: str) -> list[dict]:
        """특정 날짜 로그 읽기 (YYYY-MM-DD)"""
        filepath = self.base_dir / f"{date_str}.jsonl"
        if not filepath.exists():
            return []

        messages = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    messages.append(json.loads(line))
        return messages

    def find_by_task(self, task_id: str, date_str: str = None) -> list[dict]:
        """Task ID로 메시지 찾기"""
        if date_str:
            messages = self.read_date(date_str)
        else:
            messages = self.read_today()

        return [m for m in messages if m.get("task_id") == task_id]

    def find_by_id(self, msg_id: str, date_str: str = None) -> Optional[dict]:
        """메시지 ID로 찾기"""
        if date_str:
            messages = self.read_date(date_str)
        else:
            messages = self.read_today()

        for m in messages:
            if m.get("id") == msg_id:
                return m
        return None

    def get_chain(self, msg_id: str, date_str: str = None) -> list[dict]:
        """메시지 체인 추적 (parent_id 따라가기)"""
        if date_str:
            messages = self.read_date(date_str)
        else:
            messages = self.read_today()

        # ID로 인덱싱
        by_id = {m["id"]: m for m in messages}

        chain = []
        current_id = msg_id

        while current_id and current_id in by_id:
            chain.insert(0, by_id[current_id])
            current_id = by_id[current_id].get("parent_id")

        return chain


class TaskTracker:
    """
    Task별 추적기

    stream에서 추출해서 Task별로 정리.
    조회/분석용.
    """

    def __init__(self, base_dir: str = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path(__file__).parent / "conversations" / "tasks"

        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.stream = StreamLogger()

    def create_task(self, title: str, created_by: str = "ceo") -> str:
        """
        새 Task 생성

        Returns:
            task_id
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        # 오늘 Task 수 카운트
        existing = list(self.base_dir.glob(f"{date_str}_*.yaml"))
        task_num = len(existing) + 1

        task_id = f"{date_str}_{task_num:03d}"

        task_data = {
            "task_id": task_id,
            "title": title,
            "status": "created",
            "created_at": now.isoformat(),
            "created_by": created_by,
            "updated_at": now.isoformat(),
        }

        # Task 파일 생성
        self._save_task(task_id, task_data)

        # Stream에 기록
        self.stream.set_task(task_id)
        self.stream.log(created_by, None, "task_created", {"title": title}, task_id=task_id)

        return task_id

    def _save_task(self, task_id: str, data: dict):
        """Task 파일 저장"""
        if not HAS_YAML:
            return

        filepath = self.base_dir / f"{task_id}.yaml"
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def _load_task(self, task_id: str) -> Optional[dict]:
        """Task 파일 로드"""
        if not HAS_YAML:
            return None

        filepath = self.base_dir / f"{task_id}.yaml"
        if not filepath.exists():
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def update_status(self, task_id: str, status: str, updated_by: str = "pm"):
        """Task 상태 업데이트"""
        data = self._load_task(task_id)
        if not data:
            return

        old_status = data.get("status")
        data["status"] = status
        data["updated_at"] = datetime.now().isoformat()

        self._save_task(task_id, data)

        # Stream에 상태 변경 기록
        self.stream.log_state_change(
            updated_by,
            {"status": old_status},
            {"status": status},
            task_id=task_id
        )

    def get_task_log(self, task_id: str) -> list[dict]:
        """Task의 전체 로그"""
        # 날짜 추출
        date_str = task_id.split("_")[0]  # "2026-01-02_001" -> "2026-01-02"
        return self.stream.find_by_task(task_id, date_str)

    def get_task_summary(self, task_id: str) -> dict:
        """Task 요약"""
        data = self._load_task(task_id)
        if not data:
            return {}

        logs = self.get_task_log(task_id)

        return {
            **data,
            "message_count": len(logs),
            "agents_involved": list(set(m.get("from_agent", "").split(".")[0] for m in logs)),
        }

    def list_tasks(self, date_str: str = None, status: str = None) -> list[dict]:
        """Task 목록"""
        if date_str:
            pattern = f"{date_str}_*.yaml"
        else:
            pattern = "*.yaml"

        tasks = []
        for filepath in sorted(self.base_dir.glob(pattern), reverse=True):
            data = self._load_task(filepath.stem)
            if data:
                if status is None or data.get("status") == status:
                    tasks.append(data)

        return tasks


# =============================================================================
# Singleton
# =============================================================================

_stream: Optional[StreamLogger] = None
_tracker: Optional[TaskTracker] = None


def get_stream() -> StreamLogger:
    """StreamLogger 싱글톤"""
    global _stream
    if _stream is None:
        _stream = StreamLogger()
    return _stream


def get_tracker() -> TaskTracker:
    """TaskTracker 싱글톤"""
    global _tracker
    if _tracker is None:
        _tracker = TaskTracker()
    return _tracker


# =============================================================================
# Quick API
# =============================================================================

def log(from_agent: str, to_agent: str, msg_type: str, content: Any) -> str:
    """빠른 로깅"""
    return get_stream().log(from_agent, to_agent, msg_type, content)


def new_task(title: str) -> str:
    """새 Task 생성"""
    return get_tracker().create_task(title)


# =============================================================================
# CLI
# =============================================================================

def main():
    """테스트"""
    print("\n" + "="*60)
    print("STREAM LOGGER TEST")
    print("="*60)

    stream = StreamLogger()
    tracker = TaskTracker()

    # Task 생성
    task_id = tracker.create_task("RSI 전략 개발", "ceo")
    print(f"\n[Task Created] {task_id}")

    # 메시지 로그
    msg1 = stream.log("ceo", "excavator", "request", "RSI 전략 만들어줘", task_id=task_id)
    print(f"[Logged] {msg1}")

    msg2 = stream.log("excavator.claude", "pm", "response", {"explicit": ["RSI", "전략"]}, task_id=task_id)
    print(f"[Logged] {msg2}")

    msg3 = stream.log("excavator.gpt", "pm", "response", {"structure": "feature"}, task_id=task_id)
    print(f"[Logged] {msg3}")

    # 읽기
    print(f"\n[Today's Log] {len(stream.read_today())} messages")

    # Task 로그
    task_log = tracker.get_task_log(task_id)
    print(f"[Task Log] {len(task_log)} messages for {task_id}")

    # 체인 추적
    chain = stream.get_chain(msg3)
    print(f"[Chain] {len(chain)} messages in chain")

    print("\nDone!")


if __name__ == "__main__":
    main()
