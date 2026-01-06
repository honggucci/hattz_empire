"""
Hattz Empire - Context Compactor
CEO 완성본 - Preemptive Compaction (85% 임계치)

기능:
1. 85% 토큰 사용 시 선제적 압축
2. 대화 요약 + 핵심 컨텍스트 보존
3. LLM 기반 또는 휴리스틱 압축
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime

from .counter import TokenCounter, estimate_tokens


@dataclass
class Message:
    """대화 메시지"""
    role: str  # user, assistant, system
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    preserve: bool = False  # True면 압축에서 제외


@dataclass
class CompactionResult:
    """압축 결과"""
    success: bool
    original_tokens: int
    compacted_tokens: int
    reduction_ratio: float
    summary: str
    preserved_messages: int
    removed_messages: int
    method: str  # "llm", "heuristic", "none"


class Compactor:
    """
    컨텍스트 압축기

    85% 임계치에서 선제적으로 대화 컨텍스트 압축
    """

    def __init__(
        self,
        counter: Optional[TokenCounter] = None,
        llm_summarizer: Optional[Callable[[str], str]] = None,
        target_ratio: float = 0.5,
    ):
        """
        Args:
            counter: TokenCounter 인스턴스 (없으면 자동 생성)
            llm_summarizer: LLM 요약 함수 (prompt → summary)
            target_ratio: 압축 목표 비율 (기본 50%)
        """
        self.counter = counter or TokenCounter()
        self.llm_summarizer = llm_summarizer
        self.target_ratio = target_ratio

        self._messages: List[Message] = []

    def add_message(
        self,
        role: str,
        content: str,
        preserve: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Message:
        """
        메시지 추가

        Args:
            role: 역할 (user, assistant, system)
            content: 내용
            preserve: 압축에서 제외할지 여부
            metadata: 추가 메타데이터
        """
        msg = Message(
            role=role,
            content=content,
            preserve=preserve,
            metadata=metadata or {}
        )
        self._messages.append(msg)
        self.counter.add(role, content)
        return msg

    def should_compact(self) -> bool:
        """압축 필요 여부"""
        return self.counter.should_compact

    def compact(self) -> CompactionResult:
        """
        컨텍스트 압축 실행

        Returns:
            CompactionResult
        """
        if not self.should_compact():
            return CompactionResult(
                success=True,
                original_tokens=self.counter.total_tokens,
                compacted_tokens=self.counter.total_tokens,
                reduction_ratio=0.0,
                summary="",
                preserved_messages=len(self._messages),
                removed_messages=0,
                method="none"
            )

        original_tokens = self.counter.total_tokens

        # 보존할 메시지 분리
        preserved = [m for m in self._messages if m.preserve]
        compactable = [m for m in self._messages if not m.preserve]

        if not compactable:
            return CompactionResult(
                success=True,
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
                reduction_ratio=0.0,
                summary="",
                preserved_messages=len(preserved),
                removed_messages=0,
                method="none"
            )

        # LLM 요약 시도
        if self.llm_summarizer:
            result = self._compact_with_llm(compactable, preserved, original_tokens)
            if result.success:
                return result

        # 휴리스틱 압축 (LLM 실패 시 또는 LLM 없을 때)
        return self._compact_heuristic(compactable, preserved, original_tokens)

    def _compact_with_llm(
        self,
        compactable: List[Message],
        preserved: List[Message],
        original_tokens: int,
    ) -> CompactionResult:
        """LLM 기반 압축"""
        try:
            # 압축 대상 텍스트 구성
            text_to_summarize = self._format_messages(compactable)

            # 목표 토큰 수
            target_tokens = int(original_tokens * self.target_ratio)
            preserved_tokens = sum(estimate_tokens(m.content) for m in preserved)
            summary_budget = max(500, target_tokens - preserved_tokens)

            prompt = f"""다음 대화를 {summary_budget} 토큰 이내로 요약하세요.
핵심 정보, 결정 사항, 중요한 컨텍스트를 보존하세요.

[대화 내용]
{text_to_summarize}

[요약]"""

            summary = self.llm_summarizer(prompt)
            summary_tokens = estimate_tokens(summary)

            # 메시지 재구성
            self._messages = preserved.copy()
            self._messages.insert(0, Message(
                role="system",
                content=f"[이전 대화 요약]\n{summary}",
                preserve=True
            ))

            # 토큰 카운터 업데이트
            new_total = preserved_tokens + summary_tokens
            self.counter.set_tokens(new_total)

            return CompactionResult(
                success=True,
                original_tokens=original_tokens,
                compacted_tokens=new_total,
                reduction_ratio=(original_tokens - new_total) / original_tokens,
                summary=summary,
                preserved_messages=len(preserved),
                removed_messages=len(compactable),
                method="llm"
            )

        except Exception as e:
            return CompactionResult(
                success=False,
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
                reduction_ratio=0.0,
                summary=f"LLM error: {str(e)}",
                preserved_messages=len(preserved),
                removed_messages=0,
                method="llm"
            )

    def _compact_heuristic(
        self,
        compactable: List[Message],
        preserved: List[Message],
        original_tokens: int,
    ) -> CompactionResult:
        """휴리스틱 기반 압축 (최근 N개 유지)"""
        target_tokens = int(original_tokens * self.target_ratio)
        preserved_tokens = sum(estimate_tokens(m.content) for m in preserved)
        budget = target_tokens - preserved_tokens

        # 최근 메시지부터 budget 내에서 유지
        kept: List[Message] = []
        kept_tokens = 0

        for msg in reversed(compactable):
            msg_tokens = estimate_tokens(msg.content)
            if kept_tokens + msg_tokens <= budget:
                kept.insert(0, msg)
                kept_tokens += msg_tokens
            else:
                break

        removed_count = len(compactable) - len(kept)

        # 제거된 메시지 요약 (간단한 헤드라인)
        if removed_count > 0:
            summary = f"[이전 {removed_count}개 메시지 생략됨]"
            summary_msg = Message(
                role="system",
                content=summary,
                preserve=True
            )
            self._messages = [summary_msg] + preserved + kept
        else:
            self._messages = preserved + kept

        # 토큰 카운터 업데이트
        new_total = preserved_tokens + kept_tokens + (estimate_tokens(summary) if removed_count > 0 else 0)
        self.counter.set_tokens(new_total)

        return CompactionResult(
            success=True,
            original_tokens=original_tokens,
            compacted_tokens=new_total,
            reduction_ratio=(original_tokens - new_total) / original_tokens if original_tokens > 0 else 0,
            summary=f"Kept {len(kept)}/{len(compactable)} messages",
            preserved_messages=len(preserved),
            removed_messages=removed_count,
            method="heuristic"
        )

    def _format_messages(self, messages: List[Message]) -> str:
        """메시지를 텍스트로 포맷"""
        lines = []
        for msg in messages:
            role_label = {
                "user": "User",
                "assistant": "Assistant",
                "system": "System"
            }.get(msg.role, msg.role.capitalize())
            lines.append(f"[{role_label}]\n{msg.content}\n")
        return "\n".join(lines)

    def get_messages(self) -> List[Message]:
        """현재 메시지 목록"""
        return self._messages.copy()

    def get_context(self) -> str:
        """현재 컨텍스트를 텍스트로 반환"""
        return self._format_messages(self._messages)

    def clear(self) -> None:
        """모든 메시지 제거"""
        self._messages.clear()
        self.counter.reset()
