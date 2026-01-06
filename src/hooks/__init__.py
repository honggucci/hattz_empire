"""
Hattz Empire - Hooks Package (v2.3)
CEO 완성본 - 집행 레이어 독립화

v2.3 핵심 개선사항:
1. 비용 절감: Static Gate로 LLM 없이 0원 1차 검사
2. 감사 추적: rules_hash로 어떤 규정 버전에서 판정됐는지 추적
3. 표준화된 실패 코드: StopCode Enum으로 실패 사유 구조화

Hook 실행 순서:
┌──────────────────────────────────────────────────────────────┐
│  PRE_RUN      세션 규정 로드 → rules_hash 계산              │
│      ↓                                                       │
│  PRE_REVIEW   Static Gate (0원) → 위반 시 즉시 REJECT       │
│      ↓                                                       │
│  [LLM 호출]   비용 발생 구간                                 │
│      ↓                                                       │
│  POST_REVIEW  verdict + evidence 감사 로그 기록              │
│      ↓                                                       │
│  STOP         실패/중단 사유 표준 코드로 기록                │
└──────────────────────────────────────────────────────────────┘

연동 파일:
- src/api/chat.py: run_pre_run_hook(), run_static_gate()
- src/services/reviewer.py: review_with_hooks()
- config/session_rules/*.json: 세션별 규정 파일
"""

from .base import Hook, HookContext, HookResult, HookStage
from .pre_run import PreRunHook
from .pre_review import PreReviewHook
from .post_review import PostReviewHook
from .stop import StopHook
from .chain import HookChain

__all__ = [
    # Base
    "Hook",
    "HookContext",
    "HookResult",
    "HookStage",
    # Hooks
    "PreRunHook",
    "PreReviewHook",
    "PostReviewHook",
    "StopHook",
    # Chain
    "HookChain",
]
