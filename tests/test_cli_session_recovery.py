"""
CLI 세션 복구 테스트 (v2.6.8)

테스트 항목:
1. DB 기반 세션 생성/조회/업데이트
2. 세션 만료 감지 및 JSONL 폴백
3. 서버 재시작 시 세션 복구
4. 세션 리셋 기능
"""

import pytest
import uuid
import time
import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestCLISessionDB:
    """DB 기반 CLI 세션 관리 테스트"""

    def test_create_cli_sessions_table(self):
        """cli_sessions 테이블 생성 테스트"""
        from src.services.database import create_cli_sessions_table

        result = create_cli_sessions_table()
        assert result is True, "테이블 생성 실패"

    def test_upsert_and_get_cli_session(self):
        """CLI 세션 저장 및 조회 테스트"""
        from src.services.database import (
            create_cli_sessions_table,
            upsert_cli_session,
            get_cli_session,
            delete_cli_session
        )

        # 테이블 생성
        create_cli_sessions_table()

        # 테스트 데이터
        test_key = f"test_session:{uuid.uuid4().hex[:8]}:coder"
        test_uuid = str(uuid.uuid4())
        test_profile = "coder"
        test_chat_session = f"test_{uuid.uuid4().hex[:8]}"

        try:
            # 저장
            result = upsert_cli_session(
                session_key=test_key,
                cli_uuid=test_uuid,
                call_count=0,
                profile=test_profile,
                chat_session_id=test_chat_session
            )
            assert result is True, "세션 저장 실패"

            # 조회
            session = get_cli_session(test_key)
            assert session is not None, "세션 조회 실패"
            assert session["cli_uuid"] == test_uuid, "UUID 불일치"
            assert session["call_count"] == 0, "호출 횟수 불일치"
            assert session["profile"] == test_profile, "프로필 불일치"

            # 업데이트 (UPSERT)
            result = upsert_cli_session(
                session_key=test_key,
                cli_uuid=test_uuid,
                call_count=5,
                profile=test_profile,
                chat_session_id=test_chat_session
            )
            assert result is True, "세션 업데이트 실패"

            # 업데이트 확인
            session = get_cli_session(test_key)
            assert session["call_count"] == 5, "호출 횟수 업데이트 실패"

        finally:
            # 정리
            delete_cli_session(session_key=test_key)

    def test_increment_call_count(self):
        """호출 횟수 증가 테스트"""
        from src.services.database import (
            create_cli_sessions_table,
            upsert_cli_session,
            get_cli_session,
            increment_cli_session_call_count,
            delete_cli_session
        )

        create_cli_sessions_table()

        test_key = f"test_increment:{uuid.uuid4().hex[:8]}:qa"
        test_uuid = str(uuid.uuid4())

        try:
            # 초기 생성
            upsert_cli_session(
                session_key=test_key,
                cli_uuid=test_uuid,
                call_count=0,
                profile="qa",
                chat_session_id=None
            )

            # 3번 증가
            for i in range(3):
                new_count = increment_cli_session_call_count(test_key)
                assert new_count == i + 1, f"증가 후 횟수 불일치: {new_count} != {i + 1}"

            # 최종 확인
            session = get_cli_session(test_key)
            assert session["call_count"] == 3, "최종 호출 횟수 불일치"

        finally:
            delete_cli_session(session_key=test_key)

    def test_delete_cli_session(self):
        """CLI 세션 삭제 테스트"""
        from src.services.database import (
            create_cli_sessions_table,
            upsert_cli_session,
            get_cli_session,
            delete_cli_session
        )

        create_cli_sessions_table()

        # 여러 세션 생성
        test_session_id = f"test_delete_{uuid.uuid4().hex[:8]}"
        keys = []

        for profile in ["coder", "qa", "reviewer"]:
            key = f"{test_session_id}:{profile}"
            keys.append(key)
            upsert_cli_session(
                session_key=key,
                cli_uuid=str(uuid.uuid4()),
                call_count=0,
                profile=profile,
                chat_session_id=test_session_id
            )

        # 특정 키 삭제
        deleted = delete_cli_session(session_key=keys[0])
        assert deleted == 1, "단일 세션 삭제 실패"
        assert get_cli_session(keys[0]) is None, "삭제된 세션 조회됨"

        # 나머지 세션 전체 삭제 (chat_session_id 기준)
        deleted = delete_cli_session(chat_session_id=test_session_id)
        assert deleted == 2, f"전체 삭제 실패: {deleted}개"

        # 모두 삭제 확인
        for key in keys:
            assert get_cli_session(key) is None, f"삭제 안 됨: {key}"


class TestJSONLFallback:
    """JSONL 폴백 로직 테스트"""

    def test_load_jsonl_context_with_mock_missing_dir(self):
        """JSONL 디렉토리 없을 때 빈 리스트 반환"""
        from src.services.cli_supervisor import load_jsonl_context, JSONL_CONVERSATIONS_DIR

        # 디렉토리 존재 체크를 mock
        with patch.object(Path, 'exists', return_value=False):
            from src.services import cli_supervisor
            original_dir = cli_supervisor.JSONL_CONVERSATIONS_DIR
            cli_supervisor.JSONL_CONVERSATIONS_DIR = Path("/nonexistent/path")

            try:
                result = load_jsonl_context("nonexistent_session", "coder")
                assert result == [], "디렉토리 없을 때 빈 리스트 반환해야 함"
            finally:
                cli_supervisor.JSONL_CONVERSATIONS_DIR = original_dir

    def test_build_context_prompt_empty(self):
        """빈 컨텍스트 → 빈 문자열"""
        from src.services.cli_supervisor import build_context_prompt

        result = build_context_prompt([])
        assert result == "", "빈 컨텍스트는 빈 문자열 반환해야 함"

    def test_build_context_prompt_with_messages(self):
        """메시지 있을 때 프롬프트 생성"""
        from src.services.cli_supervisor import build_context_prompt

        messages = [
            {"role": "user", "content": "안녕하세요"},
            {"role": "assistant", "content": "안녕하세요! 무엇을 도와드릴까요?"},
            {"role": "user", "content": "코드를 작성해주세요"}
        ]

        result = build_context_prompt(messages)

        assert "[이전 대화 컨텍스트]" in result, "컨텍스트 시작 태그 없음"
        assert "[/이전 대화 컨텍스트]" in result, "컨텍스트 종료 태그 없음"
        assert "안녕하세요" in result, "사용자 메시지 없음"
        assert "무엇을 도와드릴까요?" in result, "어시스턴트 메시지 없음"

    def test_check_cli_session_expired_nonexistent(self):
        """존재하지 않는 세션 파일 → 만료"""
        from src.services.cli_supervisor import check_cli_session_expired

        # 존재하지 않는 UUID
        nonexistent_uuid = str(uuid.uuid4())
        result = check_cli_session_expired(nonexistent_uuid)
        assert result is True, "존재하지 않는 세션은 만료로 판정해야 함"


class TestCLISupervisorIntegration:
    """CLISupervisor 통합 테스트"""

    def test_get_or_create_session_uuid_new_session(self):
        """새 세션 생성 테스트"""
        from src.services.cli_supervisor import CLISupervisor
        from src.services.database import delete_cli_session

        supervisor = CLISupervisor()

        # 고유한 테스트 세션 ID
        test_session_id = f"test_new_{uuid.uuid4().hex[:8]}"
        test_profile = "coder"
        test_key = f"{test_session_id}:{test_profile}"

        try:
            # 세션 만료 체크 mock (만료되지 않은 것으로)
            with patch('src.services.cli_supervisor.check_cli_session_expired', return_value=False):
                # 첫 호출 - 새 세션 생성
                session_uuid, context = supervisor._get_or_create_session_uuid(
                    profile=test_profile,
                    session_id=test_session_id
                )

                assert session_uuid is not None, "세션 UUID 생성 실패"
                assert len(session_uuid) == 36, "UUID 형식 오류"  # UUID 표준 길이
                assert context == "", "새 세션에는 컨텍스트 없어야 함"

                # 두 번째 호출 - 같은 UUID 반환
                session_uuid2, context2 = supervisor._get_or_create_session_uuid(
                    profile=test_profile,
                    session_id=test_session_id
                )

                assert session_uuid == session_uuid2, "같은 세션 ID로 다른 UUID 반환"

        finally:
            delete_cli_session(session_key=test_key)

    def test_reset_session(self):
        """세션 리셋 테스트"""
        from src.services.cli_supervisor import CLISupervisor, _session_cache
        from src.services.database import delete_cli_session, get_cli_session

        supervisor = CLISupervisor()

        test_session_id = f"test_reset_{uuid.uuid4().hex[:8]}"
        test_profile = "qa"
        test_key = f"{test_session_id}:{test_profile}"

        try:
            # 세션 생성
            session_uuid, _ = supervisor._get_or_create_session_uuid(
                profile=test_profile,
                session_id=test_session_id
            )

            # 캐시에 있는지 확인
            assert test_key in _session_cache, "캐시에 세션 없음"

            # 리셋
            supervisor.reset_session(profile=test_profile, session_id=test_session_id)

            # 캐시에서 삭제 확인
            assert test_key not in _session_cache, "캐시에서 삭제 안 됨"

            # DB에서 삭제 확인
            db_session = get_cli_session(test_key)
            assert db_session is None, "DB에서 삭제 안 됨"

        finally:
            delete_cli_session(session_key=test_key)


class TestSessionRecoveryScenario:
    """세션 복구 시나리오 테스트"""

    def test_server_restart_recovery(self):
        """서버 재시작 후 세션 복구 시나리오"""
        from src.services.cli_supervisor import CLISupervisor, _session_cache
        from src.services.database import (
            create_cli_sessions_table,
            upsert_cli_session,
            get_cli_session,
            delete_cli_session
        )

        create_cli_sessions_table()

        test_session_id = f"test_restart_{uuid.uuid4().hex[:8]}"
        test_profile = "coder"
        test_key = f"{test_session_id}:{test_profile}"
        test_uuid = str(uuid.uuid4())

        try:
            # 1. DB에 직접 세션 저장 (서버 이전 상태 시뮬레이션)
            upsert_cli_session(
                session_key=test_key,
                cli_uuid=test_uuid,
                call_count=5,
                profile=test_profile,
                chat_session_id=test_session_id
            )

            # 2. 캐시 초기화 (서버 재시작 시뮬레이션)
            if test_key in _session_cache:
                del _session_cache[test_key]

            # 3. CLISupervisor로 세션 조회 (DB에서 복구)
            supervisor = CLISupervisor()

            # 세션 만료 체크를 우회하기 위해 mock
            with patch('src.services.cli_supervisor.check_cli_session_expired', return_value=False):
                session_uuid, context = supervisor._get_or_create_session_uuid(
                    profile=test_profile,
                    session_id=test_session_id
                )

            # 4. DB에서 복구된 UUID 확인
            assert session_uuid == test_uuid, f"복구된 UUID 불일치: {session_uuid} != {test_uuid}"

            # 5. 캐시에도 로드 확인
            assert test_key in _session_cache, "캐시에 복구 안 됨"
            assert _session_cache[test_key]["call_count"] == 5, "호출 횟수 복구 실패"

        finally:
            delete_cli_session(session_key=test_key)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
