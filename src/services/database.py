"""
Hattz Empire - Database Module (MSSQL)
세션 및 메시지 저장/조회
"""
import os
import pyodbc
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 경로를 명시적으로 지정 (프로젝트 루트)
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path, override=True)


def get_connection_string() -> str:
    """MSSQL 연결 문자열 생성"""
    server = os.getenv("MSSQL_SERVER")
    database = os.getenv("MSSQL_DATABASE")
    user = os.getenv("MSSQL_USER")
    password = os.getenv("MSSQL_PASSWORD")
    # Docker: ODBC Driver 18, Windows: ODBC Driver 17
    driver = os.getenv("ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
    return f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};UID={user};PWD={password}"


@contextmanager
def get_db_connection():
    """DB 연결 컨텍스트 매니저"""
    conn = pyodbc.connect(get_connection_string())
    try:
        yield conn
    finally:
        conn.close()


# =============================================================================
# Session CRUD
# =============================================================================

def create_session(name: Optional[str] = None, project: Optional[str] = None, agent: str = "pm") -> str:
    """새 세션 생성, session_id 반환"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chat_sessions (name, project, agent)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?)
        """, (name, project, agent))
        session_id = str(cursor.fetchone()[0])
        conn.commit()
        return session_id


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """세션 조회"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, project, agent, created_at, updated_at
            FROM chat_sessions
            WHERE id = ?
        """, (session_id,))
        row = cursor.fetchone()
        if row:
            return {
                "id": str(row.id),
                "name": row.name,
                "project": row.project,
                "agent": row.agent,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        return None


def list_sessions(limit: int = 50, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """세션 목록 조회 (최근 순, 삭제된 세션 제외)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if include_deleted:
            cursor.execute("""
                SELECT TOP (?) id, name, project, agent, created_at, updated_at, is_deleted, deleted_at
                FROM chat_sessions
                ORDER BY updated_at DESC
            """, (limit,))
        else:
            cursor.execute("""
                SELECT TOP (?) id, name, project, agent, created_at, updated_at
                FROM chat_sessions
                WHERE is_deleted = 0 OR is_deleted IS NULL
                ORDER BY updated_at DESC
            """, (limit,))
        sessions = []
        for row in cursor.fetchall():
            sessions.append({
                "id": str(row.id),
                "name": row.name,
                "project": row.project,
                "agent": row.agent,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            })
        return sessions


def update_session(session_id: str, name: Optional[str] = None, project: Optional[str] = None, agent: Optional[str] = None) -> bool:
    """세션 업데이트"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        updates = ["updated_at = GETDATE()"]
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if project is not None:
            updates.append("project = ?")
            params.append(project)
        if agent is not None:
            updates.append("agent = ?")
            params.append(agent)

        params.append(session_id)
        cursor.execute(f"""
            UPDATE chat_sessions
            SET {', '.join(updates)}
            WHERE id = ?
        """, params)
        conn.commit()
        return cursor.rowcount > 0


def delete_session(session_id: str) -> bool:
    """세션 소프트 삭제 (DB에는 보관, UI에서만 숨김)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE chat_sessions
            SET is_deleted = 1, deleted_at = GETDATE()
            WHERE id = ? AND (is_deleted = 0 OR is_deleted IS NULL)
        """, (session_id,))
        conn.commit()
        return cursor.rowcount > 0


# =============================================================================
# Message CRUD
# =============================================================================

def add_message(session_id: str, role: str, content: str, agent: Optional[str] = None, project: Optional[str] = None) -> int:
    """메시지 추가, message_id 반환 + 임베딩 큐에 자동 추가"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 메시지 추가
        cursor.execute("""
            INSERT INTO chat_messages (session_id, role, content, agent)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?)
        """, (session_id, role, content, agent))
        message_id = cursor.fetchone()[0]

        # 세션 updated_at 갱신
        cursor.execute("""
            UPDATE chat_sessions
            SET updated_at = GETDATE()
            WHERE id = ?
        """, (session_id,))

        # 세션의 프로젝트 정보 가져오기 (임베딩용)
        cursor.execute("""
            SELECT name, project FROM chat_sessions WHERE id = ?
        """, (session_id,))
        row = cursor.fetchone()
        session_project = row.project if row else None

        # 첫 메시지면 세션 이름 자동 설정
        if row and row.name is None and role == "user":
            # 첫 30자를 세션 이름으로
            auto_name = content[:30] + ("..." if len(content) > 30 else "")
            cursor.execute("""
                UPDATE chat_sessions SET name = ? WHERE id = ?
            """, (auto_name, session_id))

        conn.commit()

        # 임베딩 큐에 비동기 추가 (10자 이상일 때만)
        if content and len(content) >= 10:
            try:
                from src.services.embedding_queue import get_embedding_queue
                eq = get_embedding_queue()
                if eq.is_running():
                    eq.enqueue_message(
                        message_id=message_id,
                        content=content,
                        session_id=session_id,
                        role=role,
                        agent=agent or "unknown",
                        project=project or session_project or "hattz_empire",
                    )
            except Exception as e:
                # 임베딩 실패해도 메시지 저장은 성공
                import logging
                logging.getLogger(__name__).warning(f"Failed to enqueue embedding: {e}")

        return message_id


def get_messages(session_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """세션의 메시지 목록 조회"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP (?) id, session_id, role, agent, content, timestamp
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY timestamp ASC
        """, (limit, session_id))
        messages = []
        for row in cursor.fetchall():
            messages.append({
                "id": row.id,
                "session_id": str(row.session_id),
                "role": row.role,
                "agent": row.agent,
                "content": row.content,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            })
        return messages


def clear_messages(session_id: str) -> int:
    """세션의 모든 메시지 삭제"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        count = cursor.rowcount
        conn.commit()
        return count


# =============================================================================
# Migrations
# =============================================================================

def run_soft_delete_migration() -> Dict[str, Any]:
    """소프트 삭제 컬럼 마이그레이션 실행"""
    results = {"added_columns": [], "errors": []}

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # is_deleted 컬럼 확인 및 추가
        cursor.execute("""
            SELECT 1 FROM sys.columns
            WHERE object_id = OBJECT_ID('chat_sessions')
            AND name = 'is_deleted'
        """)
        if not cursor.fetchone():
            try:
                cursor.execute("ALTER TABLE chat_sessions ADD is_deleted BIT DEFAULT 0 NOT NULL")
                conn.commit()
                results["added_columns"].append("is_deleted")
            except Exception as e:
                results["errors"].append(f"is_deleted: {str(e)}")

        # deleted_at 컬럼 확인 및 추가
        cursor.execute("""
            SELECT 1 FROM sys.columns
            WHERE object_id = OBJECT_ID('chat_sessions')
            AND name = 'deleted_at'
        """)
        if not cursor.fetchone():
            try:
                cursor.execute("ALTER TABLE chat_sessions ADD deleted_at DATETIME NULL")
                conn.commit()
                results["added_columns"].append("deleted_at")
            except Exception as e:
                results["errors"].append(f"deleted_at: {str(e)}")

        # 기존 NULL 데이터 업데이트
        cursor.execute("UPDATE chat_sessions SET is_deleted = 0 WHERE is_deleted IS NULL")
        conn.commit()

    results["success"] = len(results["errors"]) == 0
    return results


# =============================================================================
# Agent Logs CRUD
# =============================================================================

def create_agent_logs_table() -> bool:
    """agent_logs 테이블 생성 (없으면)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'agent_logs')
            BEGIN
                CREATE TABLE agent_logs (
                    id VARCHAR(100) PRIMARY KEY,
                    session_id VARCHAR(50),
                    task_id VARCHAR(50),
                    role VARCHAR(30),
                    engine VARCHAR(20),
                    model VARCHAR(100),
                    task_type VARCHAR(30),
                    task_summary NVARCHAR(200),
                    input_tokens INT DEFAULT 0,
                    output_tokens INT DEFAULT 0,
                    latency_ms INT DEFAULT 0,
                    cost_usd DECIMAL(12, 6) DEFAULT 0,
                    result VARCHAR(20) DEFAULT 'pending',
                    result_code VARCHAR(50) NULL,
                    feedback VARCHAR(30) NULL,
                    feedback_timestamp DATETIME NULL,
                    feedback_note NVARCHAR(500) NULL,
                    score_delta INT DEFAULT 0,
                    created_at DATETIME DEFAULT GETDATE()
                );
                CREATE INDEX idx_agent_logs_session ON agent_logs(session_id);
                CREATE INDEX idx_agent_logs_role ON agent_logs(role);
                CREATE INDEX idx_agent_logs_model ON agent_logs(model);
                CREATE INDEX idx_agent_logs_created ON agent_logs(created_at);
            END
        """)
        conn.commit()
        return True


def add_agent_log(
    log_id: str,
    session_id: str,
    task_id: str,
    role: str,
    engine: str,
    model: str,
    task_type: str,
    task_summary: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    cost_usd: float = 0.0,
    result: str = "pending"
) -> bool:
    """에이전트 로그 추가"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO agent_logs (
                id, session_id, task_id, role, engine, model,
                task_type, task_summary, input_tokens, output_tokens,
                latency_ms, cost_usd, result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id, session_id, task_id, role, engine, model,
            task_type, task_summary[:200], input_tokens, output_tokens,
            latency_ms, cost_usd, result
        ))
        conn.commit()
        return True


def add_agent_feedback(
    log_id: str,
    feedback: str,
    score_delta: int,
    note: Optional[str] = None,
    result: Optional[str] = None
) -> bool:
    """에이전트 로그에 피드백 추가"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        updates = [
            "feedback = ?",
            "feedback_timestamp = GETDATE()",
            "score_delta = ?"
        ]
        params = [feedback, score_delta]

        if note:
            updates.append("feedback_note = ?")
            params.append(note)
        if result:
            updates.append("result = ?")
            params.append(result)

        params.append(log_id)
        cursor.execute(f"""
            UPDATE agent_logs
            SET {', '.join(updates)}
            WHERE id = ?
        """, params)
        conn.commit()
        return cursor.rowcount > 0


def get_agent_logs(
    session_id: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """에이전트 로그 조회"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        where_clauses = []
        params = []

        if session_id:
            where_clauses.append("session_id = ?")
            params.append(session_id)
        if role:
            where_clauses.append("role = ?")
            params.append(role)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        params.append(limit)

        cursor.execute(f"""
            SELECT TOP (?)
                id, session_id, task_id, role, engine, model,
                task_type, task_summary, input_tokens, output_tokens,
                latency_ms, cost_usd, result, result_code,
                feedback, feedback_timestamp, feedback_note, score_delta,
                created_at
            FROM agent_logs
            {where_sql}
            ORDER BY created_at DESC
        """, params[::-1])  # limit을 마지막에서 처음으로

        logs = []
        for row in cursor.fetchall():
            logs.append({
                "id": row.id,
                "session_id": row.session_id,
                "task_id": row.task_id,
                "role": row.role,
                "engine": row.engine,
                "model": row.model,
                "task_type": row.task_type,
                "task_summary": row.task_summary,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "latency_ms": row.latency_ms,
                "cost_usd": float(row.cost_usd) if row.cost_usd else 0,
                "result": row.result,
                "result_code": row.result_code,
                "feedback": row.feedback,
                "feedback_timestamp": row.feedback_timestamp.isoformat() if row.feedback_timestamp else None,
                "feedback_note": row.feedback_note,
                "score_delta": row.score_delta or 0,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })
        return logs


def get_model_scores() -> List[Dict[str, Any]]:
    """모델별 점수 집계"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                model,
                role,
                100 + ISNULL(SUM(score_delta), 0) as total_score,
                COUNT(*) as total_tasks,
                SUM(CASE WHEN result = 'success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN result = 'failure' THEN 1 ELSE 0 END) as failure_count,
                SUM(CASE WHEN feedback = 'ceo_approve' THEN 1 ELSE 0 END) as ceo_approve_count,
                SUM(CASE WHEN feedback = 'ceo_reject' THEN 1 ELSE 0 END) as ceo_reject_count,
                SUM(cost_usd) as total_cost,
                AVG(latency_ms) as avg_latency
            FROM agent_logs
            GROUP BY model, role
            ORDER BY total_score DESC
        """)

        scores = []
        for row in cursor.fetchall():
            total = row.ceo_approve_count + row.ceo_reject_count
            approval_rate = row.ceo_approve_count / total if total > 0 else 0
            success_rate = row.success_count / row.total_tasks if row.total_tasks > 0 else 0

            scores.append({
                "model": row.model,
                "role": row.role,
                "total_score": row.total_score,
                "total_tasks": row.total_tasks,
                "success_rate": f"{success_rate:.1%}",
                "ceo_approval_rate": f"{approval_rate:.1%}",
                "total_cost_usd": f"${float(row.total_cost or 0):.4f}",
                "avg_latency_ms": f"{row.avg_latency or 0:.0f}ms",
            })
        return scores


def get_best_model_for_role(role: str) -> Optional[str]:
    """역할별 최고 점수 모델 조회"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 1 model
            FROM agent_logs
            WHERE role = ?
            GROUP BY model
            ORDER BY 100 + ISNULL(SUM(score_delta), 0) DESC
        """, (role,))
        row = cursor.fetchone()
        return row.model if row else None


def get_recent_log_id(session_id: Optional[str] = None) -> Optional[str]:
    """가장 최근 로그 ID 조회"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if session_id:
            cursor.execute("""
                SELECT TOP 1 id FROM agent_logs
                WHERE session_id = ?
                ORDER BY created_at DESC
            """, (session_id,))
        else:
            cursor.execute("""
                SELECT TOP 1 id FROM agent_logs
                ORDER BY created_at DESC
            """)
        row = cursor.fetchone()
        return row.id if row else None


# =============================================================================
# Health Check
# =============================================================================

def check_db_health() -> Dict[str, Any]:
    """DB 연결 상태 확인"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.execute("SELECT COUNT(*) FROM chat_sessions")
            session_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM chat_messages")
            message_count = cursor.fetchone()[0]
            return {
                "status": "ok",
                "database": os.getenv("MSSQL_DATABASE"),
                "sessions": session_count,
                "messages": message_count,
            }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }


if __name__ == "__main__":
    # 테스트
    print("DB Health:", check_db_health())

    # 세션 생성 테스트
    session_id = create_session(project="test", agent="pm")
    print(f"Created session: {session_id}")

    # 메시지 추가 테스트
    msg_id = add_message(session_id, "user", "테스트 메시지입니다")
    print(f"Added message: {msg_id}")

    # 세션 조회
    session = get_session(session_id)
    print(f"Session: {session}")

    # 메시지 조회
    messages = get_messages(session_id)
    print(f"Messages: {messages}")

    # 정리
    delete_session(session_id)
    print("Deleted test session")
