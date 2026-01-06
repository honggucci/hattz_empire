"""
Hattz Empire - Token Counter
CEO 완성본 - 토큰 사용량 추적

기능:
1. 메시지별 토큰 추정
2. 세션 총 토큰 추적
3. 임계치 도달 알림
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


def estimate_tokens(text: str) -> int:
    """
    토큰 수 추정 (간단한 휴리스틱)

    - 영문: 4글자 ≈ 1토큰
    - 한글: 1.5글자 ≈ 1토큰
    - 코드: 3글자 ≈ 1토큰

    정확한 계산은 tiktoken 사용 필요하지만,
    의존성 최소화를 위해 휴리스틱 사용
    """
    if not text:
        return 0

    # 한글 카운트
    korean_chars = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
    # 나머지 (영문, 코드, 특수문자)
    other_chars = len(text) - korean_chars

    # 토큰 추정
    korean_tokens = korean_chars / 1.5
    other_tokens = other_chars / 4

    return int(korean_tokens + other_tokens)


@dataclass
class TokenUsage:
    """단일 메시지 토큰 사용량"""
    role: str  # user, assistant, system
    content_tokens: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class TokenCounter:
    """
    토큰 카운터

    세션 내 토큰 사용량을 추적하고 임계치 도달 시 알림
    """

    def __init__(
        self,
        max_tokens: int = 128000,
        warning_threshold: float = 0.75,
        compaction_threshold: float = 0.85,
    ):
        """
        Args:
            max_tokens: 최대 토큰 수 (기본값: 128K - Claude 3.5 Sonnet)
            warning_threshold: 경고 임계치 (75%)
            compaction_threshold: 압축 임계치 (85%)
        """
        self.max_tokens = max_tokens
        self.warning_threshold = warning_threshold
        self.compaction_threshold = compaction_threshold

        self._history: List[TokenUsage] = []
        self._total_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """현재 총 토큰 수"""
        return self._total_tokens

    @property
    def usage_ratio(self) -> float:
        """사용률 (0.0 ~ 1.0)"""
        return self._total_tokens / self.max_tokens if self.max_tokens > 0 else 0

    @property
    def remaining_tokens(self) -> int:
        """남은 토큰 수"""
        return max(0, self.max_tokens - self._total_tokens)

    @property
    def should_warn(self) -> bool:
        """경고 필요 여부"""
        return self.usage_ratio >= self.warning_threshold

    @property
    def should_compact(self) -> bool:
        """압축 필요 여부"""
        return self.usage_ratio >= self.compaction_threshold

    def add(
        self,
        role: str,
        content: str,
        tokens: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TokenUsage:
        """
        토큰 사용량 추가

        Args:
            role: 메시지 역할
            content: 메시지 내용
            tokens: 토큰 수 (None이면 자동 추정)
            metadata: 추가 메타데이터

        Returns:
            TokenUsage 객체
        """
        if tokens is None:
            tokens = estimate_tokens(content)

        usage = TokenUsage(
            role=role,
            content_tokens=tokens,
            metadata=metadata or {}
        )

        self._history.append(usage)
        self._total_tokens += tokens

        return usage

    def get_stats(self) -> Dict[str, Any]:
        """통계 반환"""
        return {
            "total_tokens": self._total_tokens,
            "max_tokens": self.max_tokens,
            "usage_ratio": round(self.usage_ratio, 4),
            "remaining_tokens": self.remaining_tokens,
            "message_count": len(self._history),
            "should_warn": self.should_warn,
            "should_compact": self.should_compact,
            "by_role": self._tokens_by_role(),
        }

    def _tokens_by_role(self) -> Dict[str, int]:
        """역할별 토큰 수"""
        result: Dict[str, int] = {}
        for usage in self._history:
            result[usage.role] = result.get(usage.role, 0) + usage.content_tokens
        return result

    def reset(self) -> None:
        """카운터 리셋"""
        self._history.clear()
        self._total_tokens = 0

    def set_tokens(self, tokens: int) -> None:
        """압축 후 토큰 수 직접 설정"""
        self._total_tokens = tokens

    def trim_history(self, keep_last: int = 10) -> int:
        """
        히스토리 트림 (오래된 것부터 제거)

        Args:
            keep_last: 유지할 최근 메시지 수

        Returns:
            제거된 토큰 수
        """
        if len(self._history) <= keep_last:
            return 0

        removed = self._history[:-keep_last]
        self._history = self._history[-keep_last:]

        removed_tokens = sum(u.content_tokens for u in removed)
        self._total_tokens -= removed_tokens

        return removed_tokens
