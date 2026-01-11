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
    # Docker: msodbcsql18, Local: msodbcsql17
    driver = os.getenv("ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    return f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};UID={user};PWD={password};TrustServerCertificate=yes"


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

def create_session(
    name: Optional[str] = None,
    project: Optional[str] = None,
    agent: str = "pm",
    parent_session_id: Optional[str] = None  # v2.6.9: 이전 세션 이어가기
) -> str:
    """새 세션 생성, session_id 반환"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # v2.6.9: parent_session_id 지원
        if parent_session_id:
            cursor.execute("""
                INSERT INTO chat_sessions (name, project, agent, parent_session_id)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?)
            """, (name, project, agent, parent_session_id))
        else:
            cursor.execute("""
                INSERT INTO chat_sessions (name, project, agent)
                OUTPUT INSERTED.id
                VALUES (?, ?, ?)
            """, (name, project, agent))

        session_id = str(cursor.fetchone()[0])
        conn.commit()
        return session_id


def add_parent_session_id_column() -> bool:
    """chat_sessions 테이블에 parent_session_id 컬럼 추가 (v2.6.9 마이그레이션)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # 컬럼 존재 확인
            cursor.execute("""
                SELECT 1 FROM sys.columns
                WHERE object_id = OBJECT_ID('chat_sessions')
                AND name = 'parent_session_id'
            """)
            if not cursor.fetchone():
                cursor.execute("""
                    ALTER TABLE chat_sessions
                    ADD parent_session_id VARCHAR(50) NULL
                """)
                conn.commit()
                print("[Migration] Added parent_session_id column to chat_sessions")
            return True
        except Exception as e:
            print(f"[Migration] parent_session_id column error: {e}")
            return False


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """세션 조회"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # v2.6.9: parent_session_id 추가 (컬럼 없으면 NULL 반환)
        cursor.execute("""
            SELECT id, name, project, agent, created_at, updated_at,
                   CASE WHEN COL_LENGTH('chat_sessions', 'parent_session_id') IS NOT NULL
                        THEN parent_session_id ELSE NULL END as parent_session_id
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
                "parent_session_id": row.parent_session_id if hasattr(row, 'parent_session_id') else None,
            }
        return None


def list_sessions(limit: int = 50, include_deleted: bool = False, allowed_projects: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    세션 목록 조회 (최근 순, 삭제된 세션 제외)
    
    Args:
        limit: 최대 조회 개수
        include_deleted: 삭제된 세션 포함 여부
        allowed_projects: 접근 가능한 프로젝트 목록 (None이면 모든 프로젝트, RLS용)
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 프로젝트 필터링 조건 구성 (RLS)
        project_filter = ""
        params = [limit]
        
        if allowed_projects is not None:
            if not allowed_projects:
                return []  # 권한 없음
            placeholders = ", ".join(["?" for _ in allowed_projects])
            project_filter = f" AND project IN ({placeholders})"
            params.extend(allowed_projects)
        
        if include_deleted:
            cursor.execute(f"""
                SELECT TOP (?) id, name, project, agent, created_at, updated_at, is_deleted, deleted_at
                FROM chat_sessions
                WHERE 1=1 {project_filter}
                ORDER BY updated_at DESC
            """, params)
        else:
            cursor.execute(f"""
                SELECT TOP (?) id, name, project, agent, created_at, updated_at
                FROM chat_sessions
                WHERE (is_deleted = 0 OR is_deleted IS NULL) {project_filter}
                ORDER BY updated_at DESC
            """, params)
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

def add_message(
    session_id: str,
    role: str,
    content: str,
    agent: Optional[str] = None,
    project: Optional[str] = None,
    model_id: Optional[str] = None,
    task_id: Optional[str] = None,
    parent_id: Optional[int] = None,
    engine_role: Optional[str] = None,
    is_internal: bool = False
) -> int:
    """
    메시지 추가, message_id 반환 + 임베딩 큐에 자동 추가

    Args:
        session_id: 세션 ID
        role: user/assistant
        content: 메시지 내용
        agent: 에이전트 역할 (pm, coder, qa 등)
        project: 프로젝트명
        model_id: LLM 모델 ID (gpt-5-mini, claude-opus-4-5 등)
        task_id: 작업 단위 ID (PM→Coder 호출 추적용)
        parent_id: 부모 메시지 ID (에이전트 간 연결)
        engine_role: 듀얼 엔진 역할 (writer/auditor/single)
        is_internal: 내부 메시지 여부 (True면 웹 UI에 표시 안 함, DB/임베딩만)
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 다음 sequence 값 계산
        cursor.execute("SELECT ISNULL(MAX(sequence), 0) + 1 FROM chat_messages WHERE session_id = ?", (session_id,))
        next_sequence = cursor.fetchone()[0]

        # 메시지 추가 (is_internal 컬럼 포함)
        cursor.execute("""
            INSERT INTO chat_messages (session_id, role, content, agent, model_id, task_id, parent_id, sequence, engine_role, is_internal)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (session_id, role, content, agent, model_id, task_id, parent_id, next_sequence, engine_role, 1 if is_internal else 0))
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


def get_messages(session_id: str, limit: int = 100, task_id: Optional[str] = None, include_internal: bool = False) -> List[Dict[str, Any]]:
    """
    세션의 메시지 목록 조회

    Args:
        session_id: 세션 ID
        limit: 최대 조회 개수
        task_id: 특정 작업의 메시지만 조회 (선택)
        include_internal: 내부 메시지 포함 여부 (기본 False = 웹 UI용)
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 내부 메시지 필터링 조건
        internal_filter = "" if include_internal else " AND (is_internal = 0 OR is_internal IS NULL)"

        if task_id:
            cursor.execute(f"""
                SELECT TOP (?) id, session_id, role, agent, content, timestamp,
                       model_id, task_id, parent_id, sequence, engine_role, is_internal
                FROM chat_messages
                WHERE session_id = ? AND task_id = ?{internal_filter}
                ORDER BY sequence ASC, timestamp ASC
            """, (limit, session_id, task_id))
        else:
            cursor.execute(f"""
                SELECT TOP (?) id, session_id, role, agent, content, timestamp,
                       model_id, task_id, parent_id, sequence, engine_role, is_internal
                FROM chat_messages
                WHERE session_id = ?{internal_filter}
                ORDER BY sequence ASC, timestamp ASC
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
                "model_id": row.model_id,
                "task_id": row.task_id,
                "parent_id": row.parent_id,
                "sequence": row.sequence,
                "engine_role": row.engine_role,
                "is_internal": bool(row.is_internal) if hasattr(row, 'is_internal') else False,
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


def run_is_internal_migration() -> Dict[str, Any]:
    """chat_messages에 is_internal 컬럼 추가 (내부 에이전트 대화 필터링용)"""
    results = {"added_columns": [], "errors": []}

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # is_internal 컬럼 확인 및 추가
        cursor.execute("""
            SELECT 1 FROM sys.columns
            WHERE object_id = OBJECT_ID('chat_messages')
            AND name = 'is_internal'
        """)
        if not cursor.fetchone():
            try:
                cursor.execute("ALTER TABLE chat_messages ADD is_internal BIT DEFAULT 0 NOT NULL")
                conn.commit()
                results["added_columns"].append("is_internal")
                print("[Migration] Added is_internal column to chat_messages")
            except Exception as e:
                results["errors"].append(f"is_internal: {str(e)}")

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
    result: str = "pending",
    project: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    engine_role: Optional[str] = None
) -> bool:
    """
    에이전트 로그 추가

    Args:
        log_id: 로그 ID
        session_id: 세션 ID
        task_id: 작업 ID
        role: 에이전트 역할
        engine: 엔진 타입 (single/dual/router)
        model: 모델 ID
        task_type: 작업 유형
        task_summary: 작업 요약
        input_tokens: 입력 토큰
        output_tokens: 출력 토큰
        latency_ms: 응답 시간
        cost_usd: 비용
        result: 결과 상태
        project: 프로젝트명
        parent_task_id: PM 태스크 ID (하위 에이전트 연결용)
        engine_role: 듀얼 엔진 역할 (writer/auditor)
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO agent_logs (
                id, session_id, task_id, role, engine, model,
                task_type, task_summary, input_tokens, output_tokens,
                latency_ms, cost_usd, result, project, parent_task_id, engine_role
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id, session_id, task_id, role, engine, model,
            task_type, task_summary[:200], input_tokens, output_tokens,
            latency_ms, cost_usd, result, project, parent_task_id, engine_role
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
# CLI Sessions (v2.6.8 - 세션 영속화)
# =============================================================================

def create_cli_sessions_table() -> bool:
    """cli_sessions 테이블 생성 (서버 재시작 시 세션 UUID 유지용)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'cli_sessions')
            BEGIN
                CREATE TABLE cli_sessions (
                    session_key VARCHAR(200) PRIMARY KEY,
                    cli_uuid VARCHAR(50) NOT NULL,
                    call_count INT DEFAULT 0,
                    profile VARCHAR(50),
                    chat_session_id VARCHAR(50),
                    created_at DATETIME DEFAULT GETDATE(),
                    updated_at DATETIME DEFAULT GETDATE(),
                    last_used_at DATETIME DEFAULT GETDATE()
                );
                CREATE INDEX idx_cli_sessions_chat ON cli_sessions(chat_session_id);
                CREATE INDEX idx_cli_sessions_profile ON cli_sessions(profile);
            END
        """)
        conn.commit()
        return True


def get_cli_session(session_key: str) -> Optional[Dict[str, Any]]:
    """CLI 세션 UUID 조회"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT session_key, cli_uuid, call_count, profile, chat_session_id,
                   created_at, updated_at, last_used_at
            FROM cli_sessions
            WHERE session_key = ?
        """, (session_key,))
        row = cursor.fetchone()
        if row:
            return {
                "session_key": row.session_key,
                "cli_uuid": row.cli_uuid,
                "call_count": row.call_count,
                "profile": row.profile,
                "chat_session_id": row.chat_session_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            }
        return None


def upsert_cli_session(
    session_key: str,
    cli_uuid: str,
    call_count: int = 0,
    profile: str = None,
    chat_session_id: str = None
) -> bool:
    """CLI 세션 저장/업데이트 (UPSERT)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # MERGE 대신 간단한 DELETE + INSERT (MSSQL MERGE 문법 복잡)
        cursor.execute("""
            IF EXISTS (SELECT 1 FROM cli_sessions WHERE session_key = ?)
            BEGIN
                UPDATE cli_sessions
                SET call_count = ?, updated_at = GETDATE(), last_used_at = GETDATE()
                WHERE session_key = ?
            END
            ELSE
            BEGIN
                INSERT INTO cli_sessions (session_key, cli_uuid, call_count, profile, chat_session_id)
                VALUES (?, ?, ?, ?, ?)
            END
        """, (session_key, call_count, session_key, session_key, cli_uuid, call_count, profile, chat_session_id))
        conn.commit()
        return True


def increment_cli_session_call_count(session_key: str) -> int:
    """CLI 세션 호출 횟수 증가 (반환: 새 호출 횟수)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE cli_sessions
            SET call_count = call_count + 1, last_used_at = GETDATE()
            OUTPUT INSERTED.call_count
            WHERE session_key = ?
        """, (session_key,))
        row = cursor.fetchone()
        conn.commit()
        return row[0] if row else 0


def delete_cli_session(session_key: str = None, profile: str = None, chat_session_id: str = None) -> int:
    """CLI 세션 삭제 (조건별)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        if session_key:
            cursor.execute("DELETE FROM cli_sessions WHERE session_key = ?", (session_key,))
        elif profile:
            cursor.execute("DELETE FROM cli_sessions WHERE profile = ?", (profile,))
        elif chat_session_id:
            cursor.execute("DELETE FROM cli_sessions WHERE chat_session_id = ?", (chat_session_id,))
        else:
            cursor.execute("DELETE FROM cli_sessions")

        count = cursor.rowcount
        conn.commit()
        return count


def get_all_cli_sessions(chat_session_id: str = None) -> List[Dict[str, Any]]:
    """모든 CLI 세션 조회 (디버깅/모니터링용)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        if chat_session_id:
            cursor.execute("""
                SELECT session_key, cli_uuid, call_count, profile, chat_session_id, last_used_at
                FROM cli_sessions
                WHERE chat_session_id = ?
                ORDER BY last_used_at DESC
            """, (chat_session_id,))
        else:
            cursor.execute("""
                SELECT TOP 100 session_key, cli_uuid, call_count, profile, chat_session_id, last_used_at
                FROM cli_sessions
                ORDER BY last_used_at DESC
            """)

        sessions = []
        for row in cursor.fetchall():
            sessions.append({
                "session_key": row.session_key,
                "cli_uuid": row.cli_uuid,
                "call_count": row.call_count,
                "profile": row.profile,
                "chat_session_id": row.chat_session_id,
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            })
        return sessions


# =============================================================================
# Session Summaries (v2.6.9 - Hierarchical Summary)
# =============================================================================

def create_session_summaries_table() -> bool:
    """session_summaries 테이블 생성 (계층적 요약 저장)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'session_summaries')
            BEGIN
                CREATE TABLE session_summaries (
                    id INT IDENTITY PRIMARY KEY,
                    session_id VARCHAR(50) NOT NULL,
                    level INT NOT NULL,              -- 0: 턴 요약, 1: 청크 요약, 2: 메타 요약
                    chunk_start INT,                 -- 시작 턴 번호
                    chunk_end INT,                   -- 끝 턴 번호
                    summary NVARCHAR(MAX),
                    token_count INT DEFAULT 0,
                    created_at DATETIME DEFAULT GETDATE()
                );
                CREATE INDEX idx_summaries_session ON session_summaries(session_id);
                CREATE INDEX idx_summaries_level ON session_summaries(session_id, level);
            END
        """)
        conn.commit()
        return True


def add_session_summary(
    session_id: str,
    level: int,
    summary: str,
    chunk_start: int = None,
    chunk_end: int = None,
    token_count: int = 0
) -> int:
    """세션 요약 추가"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO session_summaries (session_id, level, chunk_start, chunk_end, summary, token_count)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, level, chunk_start, chunk_end, summary, token_count))
        result = cursor.fetchone()
        conn.commit()
        return result[0] if result else 0


def get_session_summaries(session_id: str, level: int = None) -> List[Dict[str, Any]]:
    """세션 요약 조회 (레벨별 필터링 가능)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        if level is not None:
            cursor.execute("""
                SELECT id, session_id, level, chunk_start, chunk_end, summary, token_count, created_at
                FROM session_summaries
                WHERE session_id = ? AND level = ?
                ORDER BY chunk_start ASC, created_at ASC
            """, (session_id, level))
        else:
            cursor.execute("""
                SELECT id, session_id, level, chunk_start, chunk_end, summary, token_count, created_at
                FROM session_summaries
                WHERE session_id = ?
                ORDER BY level DESC, chunk_start ASC
            """, (session_id,))

        summaries = []
        for row in cursor.fetchall():
            summaries.append({
                "id": row.id,
                "session_id": row.session_id,
                "level": row.level,
                "chunk_start": row.chunk_start,
                "chunk_end": row.chunk_end,
                "summary": row.summary,
                "token_count": row.token_count,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })
        return summaries


def get_latest_summary(session_id: str, level: int) -> Optional[Dict[str, Any]]:
    """특정 레벨의 가장 최근 요약 조회"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 1 id, session_id, level, chunk_start, chunk_end, summary, token_count, created_at
            FROM session_summaries
            WHERE session_id = ? AND level = ?
            ORDER BY created_at DESC
        """, (session_id, level))
        row = cursor.fetchone()
        if row:
            return {
                "id": row.id,
                "session_id": row.session_id,
                "level": row.level,
                "chunk_start": row.chunk_start,
                "chunk_end": row.chunk_end,
                "summary": row.summary,
                "token_count": row.token_count,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        return None


def delete_session_summaries(session_id: str) -> int:
    """세션 요약 삭제"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM session_summaries WHERE session_id = ?", (session_id,))
        count = cursor.rowcount
        conn.commit()
        return count


def get_session_turn_count(session_id: str) -> int:
    """세션의 총 턴 수 (user 메시지 기준)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM chat_messages
            WHERE session_id = ? AND role = 'user'
        """, (session_id,))
        result = cursor.fetchone()
        return result[0] if result else 0


def get_messages_by_turn_range(session_id: str, start_turn: int, end_turn: int) -> List[Dict[str, Any]]:
    """턴 범위로 메시지 조회 (요약 생성용)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # ROW_NUMBER로 턴 번호 계산 후 필터링
        cursor.execute("""
            WITH numbered AS (
                SELECT id, session_id, role, content, timestamp,
                       ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY sequence, timestamp) as turn_num
                FROM chat_messages
                WHERE session_id = ?
            )
            SELECT id, session_id, role, content, timestamp, turn_num
            FROM numbered
            WHERE turn_num BETWEEN ? AND ?
            ORDER BY turn_num
        """, (session_id, start_turn, end_turn))

        messages = []
        for row in cursor.fetchall():
            messages.append({
                "id": row.id,
                "session_id": row.session_id,
                "role": row.role,
                "content": row.content,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "turn_num": row.turn_num,
            })
        return messages


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
