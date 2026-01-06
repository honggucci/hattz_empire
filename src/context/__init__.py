"""
Hattz Empire - Context Package (v2.3)
CEO 완성본 - Preemptive Compaction + Context Injector

v2.3 핵심 개선사항:
1. 세션 유지: 85% 도달 전 선제적 압축으로 긴 대화 지원
2. 비용 최적화: 휴리스틱 압축 우선, LLM 요약은 fallback
3. 프롬프트 표준화: Constitution + Session Rules 자동 주입

컴포넌트:
┌──────────────────────────────────────────────────────────────┐
│  TokenCounter   토큰 사용량 추적                            │
│                 - 75%: 경고 (should_warn)                   │
│                 - 85%: 압축 트리거 (should_compact)         │
├──────────────────────────────────────────────────────────────┤
│  Compactor      Preemptive Compaction                       │
│                 - 휴리스틱: 최근 N개 메시지 유지            │
│                 - LLM: Gemini로 요약 (fallback)             │
├──────────────────────────────────────────────────────────────┤
│  ContextInjector  프롬프트 주입                             │
│                 - Worker: Constitution + Rules Summary      │
│                 - Reviewer: Full Rules JSON + Check Order   │
└──────────────────────────────────────────────────────────────┘

연동 파일:
- src/api/chat.py: get_token_counter(), _session_counters
- src/hooks/pre_run.py: build_injected_context()
"""

from .counter import TokenCounter, estimate_tokens
from .compactor import Compactor, CompactionResult
from .injector import ContextInjector, InjectedPrompt

__all__ = [
    # Counter
    "TokenCounter",
    "estimate_tokens",
    # Compactor
    "Compactor",
    "CompactionResult",
    # Injector
    "ContextInjector",
    "InjectedPrompt",
]
