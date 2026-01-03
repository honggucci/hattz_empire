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

# .env 파일 경로를 명시적으로 지정
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path, override=True)


def get_connection_string() -> str:
    """MSSQL 연결 문자열 생성"""
    server = os.getenv("MSSQL_SERVER")
    database = os.getenv("MSSQL_DATABASE")
    user = os.getenv("MSSQL_USER")
    password = os.getenv("MSSQL_PASSWORD")
    return f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};UID={user};PWD={password}"


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

def add_message(session_id: str, role: str, content: str, agent: Optional[str] = None) -> int:
    """메시지 추가, message_id 반환"""
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

        # 첫 메시지면 세션 이름 자동 설정
        cursor.execute("""
            SELECT name FROM chat_sessions WHERE id = ?
        """, (session_id,))
        row = cursor.fetchone()
        if row and row.name is None and role == "user":
            # 첫 30자를 세션 이름으로
            auto_name = content[:30] + ("..." if len(content) > 30 else "")
            cursor.execute("""
                UPDATE chat_sessions SET name = ? WHERE id = ?
            """, (auto_name, session_id))

        conn.commit()
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
