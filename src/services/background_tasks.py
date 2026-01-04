"""
Hattz Empire - Background Task Manager

웹 페이지를 닫아도 서버에서 계속 실행되는 백그라운드 작업 관리
결과는 DB에 저장되어 나중에 확인 가능
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from enum import Enum
import traceback

from . import database as db


class TaskStatus(Enum):
    PENDING = "pending"      # 대기 중
    RUNNING = "running"      # 실행 중
    SUCCESS = "success"      # 성공
    FAILED = "failed"        # 실패
    CANCELLED = "cancelled"  # 취소됨


@dataclass
class BackgroundTask:
    """백그라운드 작업 데이터"""
    id: str
    session_id: str
    agent_role: str
    message: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    progress: int = 0  # 0-100
    stage: str = "waiting"
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# 메모리 내 작업 저장소 (서버 재시작 시 사라짐)
_tasks: Dict[str, BackgroundTask] = {}
_tasks_lock = threading.Lock()


def create_task(
    session_id: str,
    agent_role: str,
    message: str
) -> str:
    """
    새 백그라운드 작업 생성

    Returns:
        task_id: 작업 ID
    """
    task_id = f"bg_{int(time.time())}_{uuid.uuid4().hex[:8]}"

    task = BackgroundTask(
        id=task_id,
        session_id=session_id,
        agent_role=agent_role,
        message=message
    )

    with _tasks_lock:
        _tasks[task_id] = task

    # DB에도 저장 (영구 저장)
    _save_task_to_db(task)

    print(f"[BackgroundTask] Created: {task_id}")
    return task_id


def start_task(
    task_id: str,
    worker_fn: Callable[[str, str, Callable[[int, str], None]], str]
) -> bool:
    """
    백그라운드 작업 시작

    Args:
        task_id: 작업 ID
        worker_fn: 실제 작업 함수 (message, agent_role, progress_callback) -> result

    Returns:
        True if started, False if not found
    """
    with _tasks_lock:
        task = _tasks.get(task_id)
        if not task:
            return False

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        task.stage = "starting"

    def progress_callback(progress: int, stage: str):
        """진행률 업데이트 콜백"""
        with _tasks_lock:
            if task_id in _tasks:
                _tasks[task_id].progress = progress
                _tasks[task_id].stage = stage
                _update_task_in_db(task_id, progress=progress, stage=stage)

    def run_task():
        """쓰레드에서 실행될 함수"""
        try:
            # 실제 작업 실행
            result = worker_fn(task.message, task.agent_role, progress_callback)

            with _tasks_lock:
                if task_id in _tasks:
                    _tasks[task_id].status = TaskStatus.SUCCESS
                    _tasks[task_id].result = result
                    _tasks[task_id].completed_at = datetime.now()
                    _tasks[task_id].progress = 100
                    _tasks[task_id].stage = "completed"

            _update_task_in_db(
                task_id,
                status=TaskStatus.SUCCESS.value,
                result=result,
                progress=100,
                stage="completed"
            )
            print(f"[BackgroundTask] Completed: {task_id}")

        except Exception as e:
            error_msg = f"{str(e)}\n{traceback.format_exc()}"

            with _tasks_lock:
                if task_id in _tasks:
                    _tasks[task_id].status = TaskStatus.FAILED
                    _tasks[task_id].error = error_msg
                    _tasks[task_id].completed_at = datetime.now()
                    _tasks[task_id].stage = "failed"

            _update_task_in_db(
                task_id,
                status=TaskStatus.FAILED.value,
                error=error_msg,
                stage="failed"
            )
            print(f"[BackgroundTask] Failed: {task_id} - {str(e)}")

    # 쓰레드 시작
    thread = threading.Thread(target=run_task, daemon=True)
    thread.start()

    _update_task_in_db(task_id, status=TaskStatus.RUNNING.value, stage="running")
    print(f"[BackgroundTask] Started: {task_id}")

    return True


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """
    작업 상태 조회 (메모리 우선, 없으면 DB)
    """
    # 메모리에서 먼저 확인
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task:
            return _task_to_dict(task)

    # DB에서 조회
    return _get_task_from_db(task_id)


def get_tasks_by_session(session_id: str) -> list:
    """
    세션의 모든 작업 조회
    """
    result = []

    # 메모리에서 조회
    with _tasks_lock:
        for task in _tasks.values():
            if task.session_id == session_id:
                result.append(_task_to_dict(task))

    # DB에서도 조회 (메모리에 없는 것만)
    db_tasks = _get_tasks_from_db(session_id)
    existing_ids = {t['id'] for t in result}
    for db_task in db_tasks:
        if db_task['id'] not in existing_ids:
            result.append(db_task)

    # 생성일 기준 내림차순 정렬
    result.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    return result


def cancel_task(task_id: str) -> bool:
    """작업 취소 (실행 중인 작업은 중단 불가, 상태만 변경)"""
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task and task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now()
            task.stage = "cancelled"
            _update_task_in_db(task_id, status=TaskStatus.CANCELLED.value, stage="cancelled")
            return True
    return False


def cleanup_old_tasks(hours: int = 24):
    """오래된 작업 정리 (메모리에서만)"""
    cutoff = datetime.now().timestamp() - (hours * 3600)

    with _tasks_lock:
        to_remove = []
        for task_id, task in _tasks.items():
            if task.created_at.timestamp() < cutoff:
                to_remove.append(task_id)

        for task_id in to_remove:
            del _tasks[task_id]

        if to_remove:
            print(f"[BackgroundTask] Cleaned up {len(to_remove)} old tasks")


# =============================================================================
# Helper Functions
# =============================================================================

def _task_to_dict(task: BackgroundTask) -> Dict[str, Any]:
    """Task를 dict로 변환"""
    return {
        "id": task.id,
        "session_id": task.session_id,
        "agent_role": task.agent_role,
        "message": task.message[:100] + "..." if len(task.message) > 100 else task.message,
        "status": task.status.value,
        "result": task.result,
        "error": task.error,
        "progress": task.progress,
        "stage": task.stage,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


# =============================================================================
# Database Functions
# =============================================================================

def create_background_tasks_table() -> bool:
    """background_tasks 테이블 생성"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'background_tasks')
                BEGIN
                    CREATE TABLE background_tasks (
                        id VARCHAR(100) PRIMARY KEY,
                        session_id VARCHAR(50),
                        agent_role VARCHAR(30),
                        message NVARCHAR(MAX),
                        status VARCHAR(20) DEFAULT 'pending',
                        result NVARCHAR(MAX) NULL,
                        error NVARCHAR(MAX) NULL,
                        progress INT DEFAULT 0,
                        stage VARCHAR(50) DEFAULT 'waiting',
                        result_shown BIT DEFAULT 0,
                        created_at DATETIME DEFAULT GETDATE(),
                        started_at DATETIME NULL,
                        completed_at DATETIME NULL
                    );
                    CREATE INDEX idx_bg_tasks_session ON background_tasks(session_id);
                    CREATE INDEX idx_bg_tasks_status ON background_tasks(status);
                    CREATE INDEX idx_bg_tasks_created ON background_tasks(created_at);
                END
            """)
            conn.commit()

            # result_shown 컬럼 추가 (기존 테이블용)
            cursor.execute("""
                IF NOT EXISTS (
                    SELECT * FROM sys.columns
                    WHERE object_id = OBJECT_ID('background_tasks') AND name = 'result_shown'
                )
                BEGIN
                    ALTER TABLE background_tasks ADD result_shown BIT DEFAULT 0
                END
            """)
            conn.commit()

            print("[BackgroundTask] Table created/verified")
            return True
    except Exception as e:
        print(f"[BackgroundTask] Table creation error: {e}")
        return False


def _save_task_to_db(task: BackgroundTask):
    """작업을 DB에 저장"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO background_tasks (
                    id, session_id, agent_role, message, status, progress, stage, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.id, task.session_id, task.agent_role, task.message,
                task.status.value, task.progress, task.stage, task.created_at
            ))
            conn.commit()
    except Exception as e:
        print(f"[BackgroundTask] DB save error: {e}")


def _update_task_in_db(
    task_id: str,
    status: Optional[str] = None,
    result: Optional[str] = None,
    error: Optional[str] = None,
    progress: Optional[int] = None,
    stage: Optional[str] = None
):
    """작업 상태를 DB에 업데이트"""
    try:
        updates = []
        params = []

        if status:
            updates.append("status = ?")
            params.append(status)
        if result is not None:
            updates.append("result = ?")
            params.append(result)
        if error is not None:
            updates.append("error = ?")
            params.append(error)
        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)
        if stage:
            updates.append("stage = ?")
            params.append(stage)

        if status in [TaskStatus.SUCCESS.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value]:
            updates.append("completed_at = GETDATE()")
        elif status == TaskStatus.RUNNING.value:
            updates.append("started_at = GETDATE()")

        if updates:
            params.append(task_id)
            with db.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    UPDATE background_tasks
                    SET {', '.join(updates)}
                    WHERE id = ?
                """, params)
                conn.commit()
    except Exception as e:
        print(f"[BackgroundTask] DB update error: {e}")


def _get_task_from_db(task_id: str) -> Optional[Dict[str, Any]]:
    """DB에서 작업 조회"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, session_id, agent_role, message, status, result, error,
                       progress, stage, created_at, started_at, completed_at,
                       ISNULL(result_shown, 0) as result_shown
                FROM background_tasks
                WHERE id = ?
            """, (task_id,))
            row = cursor.fetchone()

            if row:
                return {
                    "id": row.id,
                    "session_id": row.session_id,
                    "agent_role": row.agent_role,
                    "message": row.message[:100] + "..." if len(row.message or "") > 100 else row.message,
                    "status": row.status,
                    "result": row.result,
                    "error": row.error,
                    "progress": row.progress,
                    "stage": row.stage,
                    "result_shown": bool(row.result_shown),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                }
    except Exception as e:
        print(f"[BackgroundTask] DB get error: {e}")
    return None


def _get_tasks_from_db(session_id: str) -> list:
    """DB에서 세션의 모든 작업 조회"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, session_id, agent_role, message, status, result, error,
                       progress, stage, created_at, started_at, completed_at,
                       ISNULL(result_shown, 0) as result_shown
                FROM background_tasks
                WHERE session_id = ?
                ORDER BY created_at DESC
            """, (session_id,))

            tasks = []
            for row in cursor.fetchall():
                tasks.append({
                    "id": row.id,
                    "session_id": row.session_id,
                    "agent_role": row.agent_role,
                    "message": row.message[:100] + "..." if len(row.message or "") > 100 else row.message,
                    "status": row.status,
                    "result": row.result,
                    "error": row.error,
                    "progress": row.progress,
                    "stage": row.stage,
                    "result_shown": bool(row.result_shown),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                })
            return tasks
    except Exception as e:
        print(f"[BackgroundTask] DB list error: {e}")
    return []


def mark_result_shown(task_id: str) -> bool:
    """결과를 확인했음을 표시"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE background_tasks
                SET result_shown = 1
                WHERE id = ?
            """, (task_id,))
            conn.commit()
            return True
    except Exception as e:
        print(f"[BackgroundTask] Mark shown error: {e}")
        return False


def get_unshown_completed_tasks(session_id: str) -> list:
    """완료되었지만 아직 표시되지 않은 작업들 조회"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, session_id, agent_role, message, status, result, error,
                       progress, stage, created_at, started_at, completed_at
                FROM background_tasks
                WHERE session_id = ?
                  AND status = 'success'
                  AND (result_shown IS NULL OR result_shown = 0)
                ORDER BY completed_at ASC
            """, (session_id,))

            tasks = []
            for row in cursor.fetchall():
                tasks.append({
                    "id": row.id,
                    "session_id": row.session_id,
                    "agent_role": row.agent_role,
                    "message": row.message[:100] + "..." if len(row.message or "") > 100 else row.message,
                    "status": row.status,
                    "result": row.result,
                    "error": row.error,
                    "progress": row.progress,
                    "stage": row.stage,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                })
            return tasks
    except Exception as e:
        print(f"[BackgroundTask] Get unshown error: {e}")
    return []


# =============================================================================
# WPCN Background Workers
# =============================================================================

def wpcn_backtest_worker(
    message: str,
    agent_role: str,
    progress_callback: Callable[[int, str], None]
) -> str:
    """
    WPCN 백테스트 백그라운드 워커

    Args:
        message: "BTC-USDT:15m:90" 형식
        agent_role: 에이전트 역할
        progress_callback: 진행률 콜백

    Returns:
        백테스트 결과 문자열
    """
    from .executor import run_wpcn_backtest

    parts = message.split(":")
    symbol = parts[0] if len(parts) > 0 else "BTC-USDT"
    timeframe = parts[1] if len(parts) > 1 else "15m"
    days = int(parts[2]) if len(parts) > 2 else 90

    progress_callback(10, "데이터 로드 중...")
    time.sleep(0.5)

    progress_callback(30, "백테스트 실행 중...")
    result = run_wpcn_backtest(symbol, timeframe, days)

    progress_callback(90, "결과 정리 중...")
    time.sleep(0.3)

    if result.success:
        return result.output
    else:
        raise Exception(result.error or "백테스트 실패")


def wpcn_optimize_worker(
    message: str,
    agent_role: str,
    progress_callback: Callable[[int, str], None]
) -> str:
    """
    WPCN 파라미터 최적화 백그라운드 워커

    Args:
        message: "BTC-USDT:15m:optuna" 형식
        agent_role: 에이전트 역할
        progress_callback: 진행률 콜백

    Returns:
        최적화 결과 문자열
    """
    from .executor import run_wpcn_optimize

    parts = message.split(":")
    symbol = parts[0] if len(parts) > 0 else "BTC-USDT"
    timeframe = parts[1] if len(parts) > 1 else "15m"
    optimizer = parts[2] if len(parts) > 2 else "optuna"

    progress_callback(5, "최적화 준비 중...")
    time.sleep(0.5)

    progress_callback(10, f"{optimizer} 최적화 시작...")
    result = run_wpcn_optimize(symbol, timeframe, optimizer)

    progress_callback(95, "결과 저장 중...")
    time.sleep(0.3)

    if result.success:
        return result.output
    else:
        raise Exception(result.error or "최적화 실패")


def start_wpcn_backtest(session_id: str, symbol: str, timeframe: str, days: int = 90) -> str:
    """
    WPCN 백테스트를 백그라운드로 시작

    Returns:
        task_id
    """
    message = f"{symbol}:{timeframe}:{days}"
    task_id = create_task(session_id, "wpcn_backtest", message)
    start_task(task_id, wpcn_backtest_worker)
    return task_id


def start_wpcn_optimize(session_id: str, symbol: str, timeframe: str, optimizer: str = "optuna") -> str:
    """
    WPCN 최적화를 백그라운드로 시작

    Returns:
        task_id
    """
    message = f"{symbol}:{timeframe}:{optimizer}"
    task_id = create_task(session_id, "wpcn_optimize", message)
    start_task(task_id, wpcn_optimize_worker)
    return task_id


# 테이블 생성 (모듈 로드 시)
create_background_tasks_table()
