"""
Hattz Empire - Session State
현재 세션 상태 관리 (전역 상태)
"""
from typing import Optional

# 현재 세션 ID (전역 상태)
_current_session_id: Optional[str] = None


def get_current_session() -> Optional[str]:
    """현재 세션 ID 조회"""
    global _current_session_id
    return _current_session_id


def set_current_session(session_id: Optional[str]) -> None:
    """현재 세션 ID 설정"""
    global _current_session_id
    _current_session_id = session_id
