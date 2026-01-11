"""
현재 세션 백업 + RAG 임베딩 스크립트

사용법:
    python scripts/backup_current_session.py [session_id]
    session_id 없으면 최신 세션 사용
"""
import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.services.database import get_db_connection, get_messages
from src.services.rag import index_document


def get_latest_session_id() -> str:
    """최신 세션 ID 조회"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT TOP 1 id
            FROM chat_sessions
            WHERE is_deleted = 0
            ORDER BY updated_at DESC
        """)
        row = cursor.fetchone()
        if not row:
            raise ValueError("세션이 없습니다.")
        return str(row.id)


def get_session_info(session_id: str) -> dict:
    """세션 정보 조회"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, project, agent, created_at, updated_at
            FROM chat_sessions
            WHERE id = ?
        """, (session_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"세션 {session_id}를 찾을 수 없습니다.")
        return {
            "id": str(row.id),
            "name": row.name,
            "project": row.project,
            "agent": row.agent,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


def format_messages_as_markdown(messages: list, session_info: dict) -> str:
    """메시지를 마크다운 형식으로 변환"""
    lines = []

    # 헤더
    lines.append(f"# Hattz Empire Session Backup - {session_info['created_at'][:10]}")
    lines.append("")
    lines.append(f"**Session ID**: {session_info['id']}")
    lines.append(f"**Name**: {session_info.get('name', 'Untitled')}")
    lines.append(f"**Project**: {session_info.get('project', 'N/A')}")
    lines.append(f"**Agent**: {session_info['agent']}")
    lines.append(f"**Created**: {session_info['created_at']}")
    lines.append(f"**Updated**: {session_info['updated_at']}")
    lines.append(f"**Messages**: {len(messages)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 메시지
    for i, msg in enumerate(messages, 1):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        agent = msg.get("agent", "")
        model_id = msg.get("model_id", "")
        timestamp = msg.get("timestamp", "")

        # 메시지 헤더
        if role == "user":
            lines.append(f"## [{i}] User")
        elif role == "assistant":
            lines.append(f"## [{i}] Assistant")
            if agent:
                lines.append(f"**Agent**: {agent}")
            if model_id:
                lines.append(f"**Model**: {model_id}")
        else:
            lines.append(f"## [{i}] {role.upper()}")

        if timestamp:
            lines.append(f"**Time**: {timestamp}")

        lines.append("")

        # 메시지 내용
        lines.append(content)
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def backup_session(session_id: str) -> tuple[str, str]:
    """
    세션 백업

    Returns:
        (backup_file_path, content)
    """
    # 세션 정보 조회
    session_info = get_session_info(session_id)

    # 메시지 조회 (내부 메시지 포함)
    messages = get_messages(session_id, limit=10000, include_internal=True)

    if not messages:
        raise ValueError(f"세션 {session_id}에 메시지가 없습니다.")

    # 마크다운 생성
    content = format_messages_as_markdown(messages, session_info)

    # 파일 저장 (docs/archive/)
    date_str = session_info['created_at'][:10]  # YYYY-MM-DD
    backup_dir = project_root / "docs" / "archive"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 파일명: session_backup_YYYYMMDD_sessionid.md
    filename = f"session_backup_{date_str.replace('-', '')}_{session_id}.md"
    backup_path = backup_dir / filename

    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(content)

    return str(backup_path), content


def trigger_rag_embedding(session_id: str, content: str, session_info: dict):
    """RAG 임베딩 트리거"""
    print(f"\n[RAG] 임베딩 시작...")

    try:
        doc_id = index_document(
            source_type="session_backup",
            source_id=session_id,
            content=content,
            metadata={
                "session_id": session_id,
                "session_name": session_info.get("name", "Untitled"),
                "project": session_info.get("project", "hattz_empire"),
                "agent": session_info["agent"],
                "created_at": session_info["created_at"],
                "backup_type": "manual",
            },
            project=session_info.get("project", "hattz_empire"),
            source="session_backup"
        )

        print(f"[RAG] OK Embedding complete (doc_id: {doc_id})")
        return doc_id

    except Exception as e:
        print(f"[RAG] FAILED Embedding failed: {e}")
        return None


def main():
    # 세션 ID 인자 확인
    if len(sys.argv) > 1:
        session_id = sys.argv[1]
        print(f"[INFO] 지정된 세션: {session_id}")
    else:
        session_id = get_latest_session_id()
        print(f"[INFO] 최신 세션: {session_id}")

    # 백업
    print(f"\n[BACKUP] Session backup started...")
    backup_path, content = backup_session(session_id)
    print(f"[BACKUP] OK Backup complete: {backup_path}")
    print(f"[BACKUP] File size: {len(content):,} bytes")

    # RAG 임베딩
    session_info = get_session_info(session_id)
    doc_id = trigger_rag_embedding(session_id, content, session_info)

    # 요약
    print("\n" + "="*60)
    print("Backup Complete!")
    print("="*60)
    print(f"Session ID: {session_id}")
    print(f"Backup File: {backup_path}")
    print(f"RAG Embedding: {'OK Complete' if doc_id else 'FAILED'}")
    print("="*60)


if __name__ == "__main__":
    main()
