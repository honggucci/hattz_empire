"""
Session Memory - Hierarchical Summary System (v2.6.9)

세션 대화의 계층적 요약을 생성하고 관리합니다.

Level 0: 10턴마다 턴 요약 (~200 토큰)
Level 1: 50턴마다 청크 요약 - Level 0들 압축 (~300 토큰)
Level 2: 세션 종료 시 메타 요약 - 전체 세션 (~500 토큰)

새 세션에서 이전 세션 이어가기:
- Level 2 (메타 요약) + 최근 Level 1 + 최근 10턴 → ~1000 토큰
"""

from typing import Optional, List, Dict, Any
from datetime import datetime

from src.services.database import (
    create_session_summaries_table,
    add_session_summary,
    get_session_summaries,
    get_latest_summary,
    get_session_turn_count,
    get_messages_by_turn_range,
    get_messages,
)


# =============================================================================
# Constants
# =============================================================================

LEVEL_0_INTERVAL = 10  # 10턴마다 Level 0 요약
LEVEL_1_INTERVAL = 50  # 50턴마다 Level 1 요약
MAX_TOKENS_LEVEL_0 = 200
MAX_TOKENS_LEVEL_1 = 300
MAX_TOKENS_LEVEL_2 = 500

# 요약 프롬프트
SUMMARY_PROMPT_LEVEL_0 = """다음 대화를 200토큰 이내로 요약해주세요.
핵심 주제, 결정사항, 미해결 과제를 포함하세요.

대화:
{conversation}

요약:"""

SUMMARY_PROMPT_LEVEL_1 = """다음 요약들을 300토큰 이내로 통합 요약해주세요.
전체 흐름과 핵심 인사이트를 유지하세요.

요약들:
{summaries}

통합 요약:"""

SUMMARY_PROMPT_LEVEL_2 = """다음은 세션 전체의 요약들입니다. 500토큰 이내로 메타 요약을 작성해주세요.

포함할 내용:
- 주요 주제
- 핵심 결정사항
- 중요 인사이트
- 미해결 과제/다음 단계

요약들:
{summaries}

메타 요약:"""


# =============================================================================
# Token Counter
# =============================================================================

def count_tokens(text: str, model: str = "gpt-4") -> int:
    """텍스트의 토큰 수 계산 (tiktoken 없이 추정)"""
    if not text:
        return 0

    # 간단한 휴리스틱:
    # - 영어: ~4글자 = 1토큰
    # - 한글: ~2글자 = 1토큰 (한글은 토큰당 평균 1-2자)
    # - 혼합: 평균 3글자 = 1토큰

    # 한글 비율 계산
    korean_chars = sum(1 for c in text if '\uac00' <= c <= '\ud7af')
    total_chars = len(text)

    if total_chars == 0:
        return 0

    korean_ratio = korean_chars / total_chars

    # 한글 비율에 따라 가중 평균
    # 영어 기준: 4글자/토큰, 한글 기준: 2글자/토큰
    chars_per_token = 4 * (1 - korean_ratio) + 2 * korean_ratio

    return max(1, int(total_chars / chars_per_token))


# =============================================================================
# Summary Generator
# =============================================================================

def generate_summary(prompt: str, max_tokens: int = 200) -> str:
    """LLM을 사용하여 요약 생성 (Claude CLI Sonnet 사용)"""
    try:
        from src.services.cli_supervisor import CLISupervisor

        cli = CLISupervisor()
        result = cli.call_cli(
            prompt=prompt,
            system_prompt="You are a concise summarizer. Output only the summary, no explanations.",
            profile="analyst",  # Analyst 프로필 사용 (Sonnet 4.5)
            task_context="Session Memory: Summary Generation"
        )

        if result.success:
            summary = result.output.strip()
            # 토큰 제한 확인
            if count_tokens(summary) > max_tokens * 1.5:
                # 너무 길면 자르기
                summary = summary[:max_tokens * 4] + "..."
            return summary
        else:
            return f"[요약 생성 실패: {result.error}]"

    except Exception as e:
        return f"[요약 생성 오류: {str(e)}]"


# =============================================================================
# Hierarchical Summary Manager
# =============================================================================

class SessionMemory:
    """세션 메모리 관리자 - 계층적 요약 생성 및 조회"""

    def __init__(self):
        # 테이블 생성 (없으면)
        create_session_summaries_table()

    def check_and_generate_summaries(self, session_id: str) -> Dict[str, Any]:
        """
        턴 수 확인 후 필요한 요약 생성

        Returns:
            {"generated": ["level_0", "level_1"], "turn_count": 45}
        """
        turn_count = get_session_turn_count(session_id)
        generated = []

        # Level 0 체크 (10턴마다)
        existing_level_0 = get_session_summaries(session_id, level=0)
        last_summarized_turn = max([s["chunk_end"] for s in existing_level_0], default=0)

        if turn_count >= last_summarized_turn + LEVEL_0_INTERVAL:
            # 새 Level 0 요약 생성
            start = last_summarized_turn + 1
            end = (turn_count // LEVEL_0_INTERVAL) * LEVEL_0_INTERVAL

            for chunk_start in range(start, end + 1, LEVEL_0_INTERVAL):
                chunk_end = min(chunk_start + LEVEL_0_INTERVAL - 1, turn_count)
                if chunk_end >= chunk_start:
                    self._generate_level_0(session_id, chunk_start, chunk_end)
                    generated.append(f"level_0_{chunk_start}-{chunk_end}")

        # Level 1 체크 (50턴마다)
        existing_level_1 = get_session_summaries(session_id, level=1)
        last_level_1_turn = max([s["chunk_end"] for s in existing_level_1], default=0)

        if turn_count >= last_level_1_turn + LEVEL_1_INTERVAL:
            # 새 Level 1 요약 생성
            start = last_level_1_turn + 1
            end = (turn_count // LEVEL_1_INTERVAL) * LEVEL_1_INTERVAL

            for chunk_start in range(start, end + 1, LEVEL_1_INTERVAL):
                chunk_end = min(chunk_start + LEVEL_1_INTERVAL - 1, turn_count)
                if chunk_end >= chunk_start:
                    self._generate_level_1(session_id, chunk_start, chunk_end)
                    generated.append(f"level_1_{chunk_start}-{chunk_end}")

        return {"generated": generated, "turn_count": turn_count}

    def _generate_level_0(self, session_id: str, start: int, end: int) -> int:
        """Level 0 요약 생성 (턴 범위)"""
        messages = get_messages_by_turn_range(session_id, start, end)
        if not messages:
            return 0

        # 대화 포맷팅
        conversation = "\n".join([
            f"[{m['role']}] {m['content'][:500]}..." if len(m['content']) > 500 else f"[{m['role']}] {m['content']}"
            for m in messages
        ])

        prompt = SUMMARY_PROMPT_LEVEL_0.format(conversation=conversation)
        summary = generate_summary(prompt, MAX_TOKENS_LEVEL_0)
        token_count = count_tokens(summary)

        return add_session_summary(
            session_id=session_id,
            level=0,
            summary=summary,
            chunk_start=start,
            chunk_end=end,
            token_count=token_count
        )

    def _generate_level_1(self, session_id: str, start: int, end: int) -> int:
        """Level 1 요약 생성 (Level 0들 통합)"""
        # 해당 범위의 Level 0 요약 조회
        all_level_0 = get_session_summaries(session_id, level=0)
        relevant = [s for s in all_level_0 if start <= s["chunk_start"] <= end]

        if not relevant:
            return 0

        summaries_text = "\n\n".join([
            f"[턴 {s['chunk_start']}-{s['chunk_end']}]\n{s['summary']}"
            for s in relevant
        ])

        prompt = SUMMARY_PROMPT_LEVEL_1.format(summaries=summaries_text)
        summary = generate_summary(prompt, MAX_TOKENS_LEVEL_1)
        token_count = count_tokens(summary)

        return add_session_summary(
            session_id=session_id,
            level=1,
            summary=summary,
            chunk_start=start,
            chunk_end=end,
            token_count=token_count
        )

    def generate_meta_summary(self, session_id: str) -> int:
        """Level 2 메타 요약 생성 (세션 종료 시)"""
        # 모든 Level 1 요약 수집 (없으면 Level 0)
        level_1 = get_session_summaries(session_id, level=1)
        level_0 = get_session_summaries(session_id, level=0)

        if level_1:
            summaries = level_1
        elif level_0:
            summaries = level_0
        else:
            # 요약 없으면 최근 메시지로 직접 생성
            messages = get_messages(session_id, limit=50)
            if not messages:
                return 0

            conversation = "\n".join([
                f"[{m['role']}] {m['content'][:300]}"
                for m in messages[-30:]
            ])

            prompt = SUMMARY_PROMPT_LEVEL_2.format(summaries=conversation)
            summary = generate_summary(prompt, MAX_TOKENS_LEVEL_2)
            token_count = count_tokens(summary)

            return add_session_summary(
                session_id=session_id,
                level=2,
                summary=summary,
                chunk_start=1,
                chunk_end=len(messages),
                token_count=token_count
            )

        # Level 1 또는 Level 0 요약 통합
        summaries_text = "\n\n".join([
            f"[턴 {s['chunk_start']}-{s['chunk_end']}]\n{s['summary']}"
            for s in summaries
        ])

        prompt = SUMMARY_PROMPT_LEVEL_2.format(summaries=summaries_text)
        summary = generate_summary(prompt, MAX_TOKENS_LEVEL_2)
        token_count = count_tokens(summary)

        turn_count = get_session_turn_count(session_id)

        return add_session_summary(
            session_id=session_id,
            level=2,
            summary=summary,
            chunk_start=1,
            chunk_end=turn_count,
            token_count=token_count
        )

    def get_session_context(self, session_id: str, include_recent_turns: int = 10) -> str:
        """
        새 세션에 주입할 컨텍스트 생성

        Args:
            session_id: 이전 세션 ID (parent_session_id)
            include_recent_turns: 포함할 최근 턴 수

        Returns:
            프롬프트에 주입할 컨텍스트 문자열 (~1000 토큰)
        """
        context_parts = []

        # 1. Level 2 메타 요약 (없으면 생성)
        meta = get_latest_summary(session_id, level=2)
        if not meta:
            # 메타 요약이 없으면 생성 시도
            self.generate_meta_summary(session_id)
            meta = get_latest_summary(session_id, level=2)

        if meta:
            context_parts.append(f"## 이전 세션 요약\n{meta['summary']}")

        # 2. 최근 Level 1 청크 요약
        recent_chunk = get_latest_summary(session_id, level=1)
        if recent_chunk:
            context_parts.append(f"## 최근 논의 (턴 {recent_chunk['chunk_start']}-{recent_chunk['chunk_end']})\n{recent_chunk['summary']}")

        # 3. 최근 N턴 원문
        messages = get_messages(session_id, limit=include_recent_turns * 2)
        if messages:
            recent_msgs = messages[-include_recent_turns * 2:]  # user + assistant 쌍
            turns_text = "\n".join([
                f"[{'사용자' if m['role'] == 'user' else '어시스턴트'}] {m['content'][:300]}..."
                if len(m['content']) > 300 else f"[{'사용자' if m['role'] == 'user' else '어시스턴트'}] {m['content']}"
                for m in recent_msgs
            ])
            context_parts.append(f"## 마지막 대화\n{turns_text}")

        if not context_parts:
            return ""

        return "[이전 세션 컨텍스트]\n\n" + "\n\n".join(context_parts) + "\n\n[/이전 세션 컨텍스트]\n\n위 컨텍스트를 참고하여 대화를 이어가세요."


# =============================================================================
# Singleton
# =============================================================================

_session_memory: Optional[SessionMemory] = None


def get_session_memory() -> SessionMemory:
    """SessionMemory 싱글톤 반환"""
    global _session_memory
    if _session_memory is None:
        _session_memory = SessionMemory()
    return _session_memory


# =============================================================================
# Convenience Functions
# =============================================================================

def check_and_summarize(session_id: str) -> Dict[str, Any]:
    """세션 요약 체크 및 생성 (chat.py에서 호출)"""
    return get_session_memory().check_and_generate_summaries(session_id)


def finalize_session(session_id: str) -> int:
    """세션 종료 시 메타 요약 생성"""
    return get_session_memory().generate_meta_summary(session_id)


def get_parent_session_context(parent_session_id: str) -> str:
    """이전 세션 컨텍스트 조회 (새 세션 시작 시)"""
    return get_session_memory().get_session_context(parent_session_id)


if __name__ == "__main__":
    # 테스트
    print("SessionMemory 테스트")
    memory = get_session_memory()

    # 테스트 세션 ID로 컨텍스트 생성 테스트
    test_context = memory.get_session_context("test-session-id")
    print(f"Context length: {len(test_context)} chars")
    print(test_context[:500] if test_context else "No context")
