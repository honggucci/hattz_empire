"""
Hattz Empire - Hooks Package (v2.3)
CEO 완성본 - 집행 레이어 독립화

Hook Interface:
- pre_run: 세션 규정 로드 → 해시 계산 → 컨텍스트 헤더 생성
- pre_review: StaticChecker 우선 실행 → 위반 시 LLM 없이 REJECT
- post_review: verdict + rules_hash + evidence + required_fixes 저장
- stop: 실패/중단 사유 표준 코드로 기록
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
