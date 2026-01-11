"""
Session Memory QA 테스트 (v2.6.9)

완벽주의자 페르소나 - 모든 엣지케이스와 실패 시나리오 검증

테스트 범위:
1. 단위 테스트: count_tokens, SessionMemory 메서드
2. 기능 테스트: DB 함수, 요약 생성
3. 통합 테스트: chat.py 트리거, CLI 컨텍스트 주입
4. 엣지케이스: 빈 세션, 누락된 parent, 토큰 제한
"""

import pytest
import uuid
from unittest.mock import patch, MagicMock
from datetime import datetime


# =============================================================================
# 1. 단위 테스트: count_tokens
# =============================================================================

class TestCountTokens:
    """count_tokens 함수 단위 테스트"""

    def test_empty_string(self):
        """빈 문자열 → 0 토큰"""
        from src.services.session_memory import count_tokens
        assert count_tokens("") == 0
        assert count_tokens(None) == 0 if count_tokens(None) is not None else True

    def test_english_only(self):
        """영어만 있는 경우 (~4글자/토큰)"""
        from src.services.session_memory import count_tokens

        # "hello world" = 11글자 → ~2-3 토큰
        result = count_tokens("hello world")
        assert 2 <= result <= 4, f"Expected 2-4 tokens, got {result}"

    def test_korean_only(self):
        """한글만 있는 경우 (~2글자/토큰)"""
        from src.services.session_memory import count_tokens

        # "안녕하세요" = 5글자 → ~2-3 토큰
        result = count_tokens("안녕하세요")
        assert 2 <= result <= 4, f"Expected 2-4 tokens, got {result}"

    def test_mixed_language(self):
        """혼합 언어"""
        from src.services.session_memory import count_tokens

        # "Hello 안녕" = 혼합
        result = count_tokens("Hello 안녕")
        assert result >= 2, f"Expected at least 2 tokens, got {result}"

    def test_long_text(self):
        """긴 텍스트"""
        from src.services.session_memory import count_tokens

        # 1000글자 영어 → ~250 토큰
        long_text = "a" * 1000
        result = count_tokens(long_text)
        assert 200 <= result <= 300, f"Expected 200-300 tokens, got {result}"

    def test_unicode_characters(self):
        """유니코드 특수 문자"""
        from src.services.session_memory import count_tokens

        # 이모지 포함
        result = count_tokens("Hello 👋 World 🌍")
        assert result >= 2, f"Expected at least 2 tokens, got {result}"


# =============================================================================
# 2. 단위 테스트: SessionMemory 클래스
# =============================================================================

class TestSessionMemoryClass:
    """SessionMemory 클래스 단위 테스트"""

    def test_singleton_pattern(self):
        """싱글톤 패턴 검증"""
        from src.services.session_memory import get_session_memory

        memory1 = get_session_memory()
        memory2 = get_session_memory()
        assert memory1 is memory2, "싱글톤이 아님"

    def test_check_and_generate_summaries_empty_session(self):
        """빈 세션에서 요약 생성 시도"""
        from src.services.session_memory import SessionMemory
        from src.services.database import create_session, delete_session

        memory = SessionMemory()
        # 실제 DB 세션 생성 (uniqueidentifier 타입 호환)
        test_session_id = create_session(name="Empty Test Session", agent="pm")

        try:
            result = memory.check_and_generate_summaries(test_session_id)

            assert "generated" in result, "generated 키 없음"
            assert "turn_count" in result, "turn_count 키 없음"
            assert result["turn_count"] == 0, "빈 세션인데 턴 수가 0이 아님"
            assert result["generated"] == [], "빈 세션인데 요약이 생성됨"
        finally:
            delete_session(test_session_id)

    def test_get_session_context_nonexistent(self):
        """존재하지 않는 세션 컨텍스트 조회"""
        from src.services.session_memory import SessionMemory
        from src.services.database import create_session, delete_session

        memory = SessionMemory()
        # 실제 DB 세션 생성 (메시지 없음 → 빈 컨텍스트)
        test_session_id = create_session(name="No Messages Session", agent="pm")

        try:
            context = memory.get_session_context(test_session_id)

            # 빈 문자열 또는 기본 컨텍스트 반환
            assert isinstance(context, str), "문자열이 아님"
        finally:
            delete_session(test_session_id)


# =============================================================================
# 3. 기능 테스트: DB 함수
# =============================================================================

class TestDatabaseFunctions:
    """database.py 세션 요약 함수 테스트"""

    def test_create_session_summaries_table(self):
        """테이블 생성 테스트"""
        from src.services.database import create_session_summaries_table

        result = create_session_summaries_table()
        assert result is True, "테이블 생성 실패"

    def test_add_and_get_session_summary(self):
        """요약 추가 및 조회"""
        from src.services.database import (
            create_session_summaries_table,
            add_session_summary,
            get_session_summaries,
            delete_session_summaries
        )

        create_session_summaries_table()

        test_session_id = f"test_summary_{uuid.uuid4().hex[:8]}"

        try:
            # Level 0 요약 추가
            summary_id = add_session_summary(
                session_id=test_session_id,
                level=0,
                summary="테스트 요약 내용",
                chunk_start=1,
                chunk_end=10,
                token_count=50
            )

            assert summary_id > 0, "요약 ID가 0 이하"

            # 조회
            summaries = get_session_summaries(test_session_id, level=0)
            assert len(summaries) >= 1, "요약이 조회되지 않음"

            found = any(s["id"] == summary_id for s in summaries)
            assert found, "추가한 요약을 찾을 수 없음"

        finally:
            # 정리
            delete_session_summaries(test_session_id)

    def test_get_latest_summary(self):
        """최근 요약 조회"""
        from src.services.database import (
            create_session_summaries_table,
            add_session_summary,
            get_latest_summary,
            delete_session_summaries
        )

        create_session_summaries_table()

        # 고유한 세션 ID 사용
        test_session_id = f"test_latest_{uuid.uuid4().hex}"

        try:
            # 기존 데이터 삭제 (혹시 있다면)
            delete_session_summaries(test_session_id)

            # 여러 요약 추가
            add_session_summary(test_session_id, level=0, summary="첫 번째", chunk_start=1, chunk_end=10)
            add_session_summary(test_session_id, level=0, summary="두 번째", chunk_start=11, chunk_end=20)
            latest_id = add_session_summary(test_session_id, level=0, summary="세 번째", chunk_start=21, chunk_end=30)

            # 최근 조회
            latest = get_latest_summary(test_session_id, level=0)

            assert latest is not None, "최근 요약 조회 실패"
            assert latest["id"] == latest_id, f"최근 요약이 아님: {latest['id']} != {latest_id}"
            assert latest["summary"] == "세 번째", "내용 불일치"

        finally:
            delete_session_summaries(test_session_id)

    def test_get_session_turn_count(self):
        """세션 턴 수 조회"""
        from src.services.database import (
            get_session_turn_count,
            create_session,
            delete_session
        )

        # 실제 DB 세션 생성 (메시지 없음)
        test_session_id = create_session(name="Turn Count Test", agent="pm")

        try:
            count = get_session_turn_count(test_session_id)
            assert count == 0, f"빈 세션인데 턴 수가 {count}"
        finally:
            delete_session(test_session_id)

    def test_parent_session_id_column(self):
        """parent_session_id 컬럼 마이그레이션 테스트"""
        from src.services.database import add_parent_session_id_column

        result = add_parent_session_id_column()
        assert result is True, "마이그레이션 실패"

    def test_create_session_with_parent(self):
        """parent_session_id로 세션 생성"""
        from src.services.database import (
            create_session,
            get_session,
            delete_session,
            add_parent_session_id_column
        )

        # 마이그레이션 먼저
        add_parent_session_id_column()

        # 부모 세션 생성
        parent_id = create_session(name="Parent Session", agent="pm")

        try:
            # 자식 세션 생성
            child_id = create_session(
                name="Child Session",
                agent="pm",
                parent_session_id=parent_id
            )

            try:
                # 자식 세션 조회
                child = get_session(child_id)

                assert child is not None, "자식 세션 조회 실패"
                assert child.get("parent_session_id") == parent_id, \
                    f"parent_session_id 불일치: {child.get('parent_session_id')} != {parent_id}"

            finally:
                delete_session(child_id)
        finally:
            delete_session(parent_id)


# =============================================================================
# 4. 통합 테스트: chat.py 트리거
# =============================================================================

class TestChatTrigger:
    """chat.py 세션 요약 트리거 통합 테스트"""

    def test_trigger_session_summary_import(self):
        """트리거 함수 import 테스트"""
        from src.api.chat import trigger_session_summary

        assert callable(trigger_session_summary), "함수가 callable이 아님"

    def test_trigger_session_summary_empty_session(self):
        """빈 세션에서 트리거"""
        from src.api.chat import trigger_session_summary

        fake_session_id = f"trigger_test_{uuid.uuid4().hex[:8]}"

        result = trigger_session_summary(fake_session_id)

        assert isinstance(result, dict), "딕셔너리가 아님"
        assert "generated" in result, "generated 키 없음"
        assert "turn_count" in result, "turn_count 키 없음"

    def test_trigger_session_summary_error_handling(self):
        """트리거 에러 핸들링"""
        from src.api.chat import trigger_session_summary

        # None 세션 ID
        result = trigger_session_summary(None)

        # 에러가 발생해도 딕셔너리 반환해야 함
        assert isinstance(result, dict), "에러 시에도 딕셔너리 반환해야 함"


# =============================================================================
# 5. 통합 테스트: CLI 컨텍스트 주입
# =============================================================================

class TestCLIContextInjection:
    """cli_supervisor.py 컨텍스트 주입 테스트"""

    def test_build_prompt_without_parent(self):
        """parent_session_id 없는 경우"""
        from src.services.cli_supervisor import CLISupervisor

        supervisor = CLISupervisor()
        supervisor._current_session_id = None

        # _get_previous_session_context 호출
        context = supervisor._get_previous_session_context()

        assert context == "", "세션 ID 없으면 빈 문자열 반환해야 함"

    def test_build_prompt_with_nonexistent_session(self):
        """존재하지 않는 세션"""
        from src.services.cli_supervisor import CLISupervisor

        supervisor = CLISupervisor()
        supervisor._current_session_id = f"nonexistent_{uuid.uuid4().hex[:8]}"

        context = supervisor._get_previous_session_context()

        # 존재하지 않는 세션이면 빈 문자열
        assert context == "", "없는 세션이면 빈 문자열 반환해야 함"


# =============================================================================
# 6. 엣지케이스 테스트
# =============================================================================

class TestEdgeCases:
    """엣지케이스 테스트"""

    def test_summary_with_very_long_content(self):
        """매우 긴 내용 요약"""
        from src.services.session_memory import count_tokens

        # 100,000자 텍스트
        very_long = "테스트 " * 20000
        tokens = count_tokens(very_long)

        # 계산이 에러 없이 완료되어야 함
        assert tokens > 0, "토큰 계산 실패"
        assert tokens < 100000, "토큰 수가 비정상적으로 큼"

    def test_summary_with_special_characters(self):
        """특수 문자 포함 요약"""
        from src.services.database import (
            create_session_summaries_table,
            add_session_summary,
            get_session_summaries,
            delete_session_summaries
        )

        create_session_summaries_table()
        test_session_id = f"special_{uuid.uuid4().hex[:8]}"

        try:
            # 특수 문자 포함 요약
            special_content = "테스트\n줄바꿈\t탭\r캐리지리턴'따옴표\"쌍따옴표"

            summary_id = add_session_summary(
                session_id=test_session_id,
                level=0,
                summary=special_content,
                chunk_start=1,
                chunk_end=10
            )

            # 조회
            summaries = get_session_summaries(test_session_id, level=0)
            found = next((s for s in summaries if s["id"] == summary_id), None)

            assert found is not None, "특수 문자 요약 저장/조회 실패"
            assert found["summary"] == special_content, "특수 문자 내용 불일치"

        finally:
            delete_session_summaries(test_session_id)

    def test_concurrent_summary_access(self):
        """동시 접근 (기본적인 검증)"""
        from src.services.session_memory import get_session_memory
        import threading

        results = []

        def access_memory():
            memory = get_session_memory()
            results.append(id(memory))

        threads = [threading.Thread(target=access_memory) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 모두 같은 인스턴스여야 함 (싱글톤)
        assert len(set(results)) == 1, "싱글톤이 동시 접근에서 깨짐"

    def test_summary_level_boundaries(self):
        """요약 레벨 경계값"""
        from src.services.database import (
            create_session_summaries_table,
            add_session_summary,
            get_session_summaries,
            delete_session_summaries
        )

        create_session_summaries_table()
        test_session_id = f"level_{uuid.uuid4().hex[:8]}"

        try:
            # 각 레벨 테스트
            for level in [0, 1, 2]:
                add_session_summary(
                    session_id=test_session_id,
                    level=level,
                    summary=f"Level {level} 요약",
                    chunk_start=1,
                    chunk_end=10
                )

            # 레벨별 조회
            for level in [0, 1, 2]:
                summaries = get_session_summaries(test_session_id, level=level)
                assert len(summaries) >= 1, f"Level {level} 요약 조회 실패"

        finally:
            delete_session_summaries(test_session_id)


# =============================================================================
# 7. 회귀 테스트
# =============================================================================

class TestRegression:
    """회귀 테스트 - 기존 기능 영향 없음 확인"""

    def test_chat_import_still_works(self):
        """chat.py import 정상 동작"""
        try:
            from src.api.chat import chat_bp, chat_stream
            assert chat_bp is not None
            assert chat_stream is not None
        except ImportError as e:
            pytest.fail(f"chat.py import 실패: {e}")

    def test_cli_supervisor_import_still_works(self):
        """cli_supervisor.py import 정상 동작"""
        try:
            from src.services.cli_supervisor import CLISupervisor, call_claude_cli
            assert CLISupervisor is not None
        except ImportError as e:
            pytest.fail(f"cli_supervisor.py import 실패: {e}")

    def test_database_import_still_works(self):
        """database.py import 정상 동작"""
        try:
            from src.services.database import (
                create_session,
                get_session,
                add_message,
                get_messages
            )
            assert create_session is not None
            assert get_session is not None
        except ImportError as e:
            pytest.fail(f"database.py import 실패: {e}")


# =============================================================================
# 메인 실행
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
