"""
Hattz Empire - Agent Task Monitor
에이전트 작업 실시간 모니터링 시스템

각 에이전트가 무슨 작업을 하고 있는지, 상태가 어떤지 추적
"""
import threading
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import uuid
import logging

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"      # 대기 중
    RUNNING = "running"      # 실행 중
    SUCCESS = "success"      # 성공
    FAILED = "failed"        # 실패
    TIMEOUT = "timeout"      # 타임아웃
    CANCELLED = "cancelled"  # 취소됨


@dataclass
class AgentTask:
    """에이전트 작업 단위"""
    id: str
    agent: str                          # coder, qa, researcher 등
    parent_agent: Optional[str]         # 호출한 상위 에이전트 (pm 등)
    session_id: str
    task_type: str                      # call, execute, search 등
    description: str                    # 작업 설명
    status: TaskStatus = TaskStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    result_preview: Optional[str] = None  # 결과 미리보기 (200자)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent": self.agent,
            "parent_agent": self.parent_agent,
            "session_id": self.session_id,
            "task_type": self.task_type,
            "description": self.description,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self._get_duration_ms(),
            "error_message": self.error_message,
            "result_preview": self.result_preview,
            "metadata": self.metadata,
        }

    def _get_duration_ms(self) -> Optional[int]:
        if not self.started_at:
            return None
        end = self.completed_at or datetime.now()
        return int((end - self.started_at).total_seconds() * 1000)


class AgentMonitor:
    """싱글톤 에이전트 모니터"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._tasks: Dict[str, AgentTask] = {}  # task_id -> AgentTask
        self._active_by_agent: Dict[str, List[str]] = {}  # agent -> [task_ids]
        self._session_tasks: Dict[str, List[str]] = {}  # session_id -> [task_ids]
        self._lock = threading.Lock()
        self._max_history = 100  # 최근 N개 완료된 작업만 유지
        self._initialized = True
        logger.info("[AgentMonitor] Initialized")

    def start_task(
        self,
        agent: str,
        session_id: str,
        task_type: str,
        description: str,
        parent_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """새 작업 시작 등록"""
        task_id = str(uuid.uuid4())[:8]

        task = AgentTask(
            id=task_id,
            agent=agent,
            parent_agent=parent_agent,
            session_id=session_id,
            task_type=task_type,
            description=description[:200],
            status=TaskStatus.RUNNING,
            started_at=datetime.now(),
            metadata=metadata or {},
        )

        with self._lock:
            self._tasks[task_id] = task

            # 에이전트별 활성 작업 추적
            if agent not in self._active_by_agent:
                self._active_by_agent[agent] = []
            self._active_by_agent[agent].append(task_id)

            # 세션별 작업 추적
            if session_id not in self._session_tasks:
                self._session_tasks[session_id] = []
            self._session_tasks[session_id].append(task_id)

        logger.info(f"[AgentMonitor] Task started: {agent}/{task_id} - {description[:50]}")
        return task_id

    def complete_task(
        self,
        task_id: str,
        success: bool = True,
        result_preview: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """작업 완료 처리"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"[AgentMonitor] Task not found: {task_id}")
                return

            task.status = TaskStatus.SUCCESS if success else TaskStatus.FAILED
            task.completed_at = datetime.now()
            task.result_preview = result_preview[:200] if result_preview else None
            task.error_message = error_message

            # 활성 목록에서 제거
            if task.agent in self._active_by_agent:
                if task_id in self._active_by_agent[task.agent]:
                    self._active_by_agent[task.agent].remove(task_id)

        status_str = "SUCCESS" if success else "FAILED"
        logger.info(f"[AgentMonitor] Task {status_str}: {task.agent}/{task_id}")

        # DB에 저장 (선택적)
        self._save_to_db(task)

    def fail_task(self, task_id: str, error_message: str):
        """작업 실패 처리"""
        self.complete_task(task_id, success=False, error_message=error_message)

    def cancel_task(self, task_id: str):
        """작업 취소"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """특정 작업 조회"""
        task = self._tasks.get(task_id)
        return task.to_dict() if task else None

    def get_active_tasks(self, agent: Optional[str] = None) -> List[Dict[str, Any]]:
        """활성 작업 목록 조회"""
        with self._lock:
            if agent:
                task_ids = self._active_by_agent.get(agent, [])
            else:
                task_ids = []
                for ids in self._active_by_agent.values():
                    task_ids.extend(ids)

            return [
                self._tasks[tid].to_dict()
                for tid in task_ids
                if tid in self._tasks
            ]

    def get_session_tasks(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """세션별 작업 목록 조회"""
        with self._lock:
            task_ids = self._session_tasks.get(session_id, [])
            tasks = [
                self._tasks[tid].to_dict()
                for tid in task_ids[-limit:]
                if tid in self._tasks
            ]
            return sorted(tasks, key=lambda x: x.get("started_at") or "", reverse=True)

    def get_all_agents_status(self) -> Dict[str, Any]:
        """전체 에이전트 상태 요약"""
        with self._lock:
            status = {}
            for agent, task_ids in self._active_by_agent.items():
                active_tasks = [
                    self._tasks[tid].to_dict()
                    for tid in task_ids
                    if tid in self._tasks
                ]
                status[agent] = {
                    "active_count": len(active_tasks),
                    "tasks": active_tasks,
                }
            return status

    def get_dashboard_data(self) -> Dict[str, Any]:
        """대시보드용 종합 데이터"""
        with self._lock:
            # 활성 작업
            active = []
            for task_ids in self._active_by_agent.values():
                for tid in task_ids:
                    if tid in self._tasks:
                        active.append(self._tasks[tid].to_dict())

            # 최근 완료된 작업
            all_tasks = list(self._tasks.values())
            completed = [
                t.to_dict() for t in all_tasks
                if t.status in (TaskStatus.SUCCESS, TaskStatus.FAILED)
            ]
            completed.sort(key=lambda x: x.get("completed_at") or "", reverse=True)

            return {
                "timestamp": datetime.now().isoformat(),
                "active_tasks": active,
                "active_count": len(active),
                "recent_completed": completed[:10],
                "agents_summary": {
                    agent: len(ids)
                    for agent, ids in self._active_by_agent.items()
                },
            }

    def _save_to_db(self, task: AgentTask):
        """완료된 작업을 DB에 저장 (선택적)"""
        try:
            from src.services.database import get_db_connection
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'agent_tasks')
                    BEGIN
                        CREATE TABLE agent_tasks (
                            id VARCHAR(50) PRIMARY KEY,
                            agent VARCHAR(30),
                            parent_agent VARCHAR(30),
                            session_id VARCHAR(50),
                            task_type VARCHAR(30),
                            description NVARCHAR(500),
                            status VARCHAR(20),
                            started_at DATETIME,
                            completed_at DATETIME,
                            duration_ms INT,
                            error_message NVARCHAR(1000),
                            result_preview NVARCHAR(500),
                            created_at DATETIME DEFAULT GETDATE()
                        );
                        CREATE INDEX idx_agent_tasks_session ON agent_tasks(session_id);
                        CREATE INDEX idx_agent_tasks_agent ON agent_tasks(agent);
                        CREATE INDEX idx_agent_tasks_status ON agent_tasks(status);
                    END
                """)

                cursor.execute("""
                    MERGE agent_tasks AS target
                    USING (SELECT ? AS id) AS source
                    ON target.id = source.id
                    WHEN MATCHED THEN
                        UPDATE SET
                            status = ?,
                            completed_at = ?,
                            duration_ms = ?,
                            error_message = ?,
                            result_preview = ?
                    WHEN NOT MATCHED THEN
                        INSERT (id, agent, parent_agent, session_id, task_type, description, status, started_at, completed_at, duration_ms, error_message, result_preview)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    task.id,
                    task.status.value,
                    task.completed_at,
                    task._get_duration_ms(),
                    task.error_message,
                    task.result_preview,
                    task.id, task.agent, task.parent_agent, task.session_id,
                    task.task_type, task.description, task.status.value,
                    task.started_at, task.completed_at, task._get_duration_ms(),
                    task.error_message, task.result_preview
                ))
                conn.commit()
        except Exception as e:
            logger.warning(f"[AgentMonitor] Failed to save task to DB: {e}")

    def cleanup_old_tasks(self):
        """오래된 완료 작업 정리"""
        with self._lock:
            completed = [
                (tid, task) for tid, task in self._tasks.items()
                if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED)
            ]
            if len(completed) > self._max_history:
                # 가장 오래된 것부터 제거
                completed.sort(key=lambda x: x[1].completed_at or datetime.min)
                to_remove = len(completed) - self._max_history
                for tid, _ in completed[:to_remove]:
                    del self._tasks[tid]


# 전역 싱글톤
_monitor: Optional[AgentMonitor] = None


def get_agent_monitor() -> AgentMonitor:
    """에이전트 모니터 싱글톤 반환"""
    global _monitor
    if _monitor is None:
        _monitor = AgentMonitor()
    return _monitor
