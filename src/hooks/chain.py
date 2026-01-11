"""
Hattz Empire - Hook Chain
CEO 완성본 - Worker 루프에 끼워넣을 훅 체인

기능:
1. Hook 등록 및 순차 실행
2. should_abort 시 조기 종료
3. 컨텍스트 전파 (이전 Hook → 다음 Hook)
4. 에러 핸들링 및 롤백
"""
from __future__ import annotations
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime

from .base import Hook, HookContext, HookResult, HookStage


@dataclass
class ChainResult:
    """Hook Chain 실행 결과"""
    success: bool
    completed_hooks: List[str]
    failed_hook: Optional[str] = None
    abort_hook: Optional[str] = None
    abort_reason: str = ""
    final_context: Optional[HookContext] = None
    results: Dict[str, HookResult] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: int = 0

    def __repr__(self) -> str:
        status = "✅" if self.success else "❌"
        hooks = ", ".join(self.completed_hooks) if self.completed_hooks else "none"
        abort = f" [ABORT: {self.abort_hook}]" if self.abort_hook else ""
        return f"ChainResult({status} hooks=[{hooks}]{abort})"


class HookChain:
    """
    Hook Chain

    Worker 실행 전/중/후에 Hook들을 순차적으로 실행
    """

    def __init__(self):
        """훅 체인 초기화"""
        self._hooks: Dict[HookStage, List[Hook]] = {
            HookStage.PRE_RUN: [],
            HookStage.PRE_REVIEW: [],
            HookStage.POST_REVIEW: [],
            HookStage.STOP: [],
        }
        self._error_handlers: List[Callable[[HookContext, Exception], None]] = []

    def register(self, hook: Hook) -> "HookChain":
        """
        Hook 등록

        Args:
            hook: 등록할 Hook

        Returns:
            self (체이닝용)
        """
        self._hooks[hook.stage].append(hook)
        return self

    def register_all(self, hooks: List[Hook]) -> "HookChain":
        """여러 Hook 일괄 등록"""
        for hook in hooks:
            self.register(hook)
        return self

    def on_error(self, handler: Callable[[HookContext, Exception], None]) -> "HookChain":
        """에러 핸들러 등록"""
        self._error_handlers.append(handler)
        return self

    def run_stage(
        self,
        stage: HookStage,
        context: HookContext,
        abort_on_failure: bool = True,
    ) -> ChainResult:
        """
        특정 단계의 Hook들 실행

        Args:
            stage: 실행할 단계
            context: 실행 컨텍스트
            abort_on_failure: 실패 시 중단 여부

        Returns:
            ChainResult
        """
        start_time = datetime.now()
        hooks = self._hooks.get(stage, [])
        completed = []
        results = {}

        for hook in hooks:
            # 유효성 검증
            if not hook.validate(context):
                print(f"[HookChain] Skipping {hook.name} (validation failed)")
                continue

            try:
                result = hook.execute(context)
                results[hook.name] = result
                completed.append(hook.name)

                # 컨텍스트 업데이트
                if result.context:
                    context = result.context

                # should_abort 체크
                if result.should_abort:
                    execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
                    return ChainResult(
                        success=True,  # Hook은 성공했지만 abort 요청
                        completed_hooks=completed,
                        abort_hook=hook.name,
                        abort_reason=result.abort_reason,
                        final_context=context,
                        results=results,
                        execution_time_ms=execution_time,
                    )

                # 실패 체크
                if not result.success and abort_on_failure:
                    execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
                    return ChainResult(
                        success=False,
                        completed_hooks=completed,
                        failed_hook=hook.name,
                        final_context=context,
                        results=results,
                        error=result.error,
                        execution_time_ms=execution_time,
                    )

            except Exception as e:
                # 에러 핸들러 호출
                for handler in self._error_handlers:
                    try:
                        handler(context, e)
                    except Exception:
                        pass

                # 에러 결과 반환
                execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
                return ChainResult(
                    success=False,
                    completed_hooks=completed,
                    failed_hook=hook.name,
                    final_context=context,
                    results=results,
                    error=str(e),
                    execution_time_ms=execution_time,
                )

        # 모든 Hook 성공
        execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
        return ChainResult(
            success=True,
            completed_hooks=completed,
            final_context=context,
            results=results,
            execution_time_ms=execution_time,
        )

    def run_pre_run(self, context: HookContext) -> ChainResult:
        """PRE_RUN 단계 실행"""
        return self.run_stage(HookStage.PRE_RUN, context)

    def run_pre_review(self, context: HookContext) -> ChainResult:
        """PRE_REVIEW 단계 실행 (Static Gate)"""
        return self.run_stage(HookStage.PRE_REVIEW, context)

    def run_post_review(self, context: HookContext) -> ChainResult:
        """POST_REVIEW 단계 실행"""
        return self.run_stage(HookStage.POST_REVIEW, context)

    def run_stop(self, context: HookContext) -> ChainResult:
        """STOP 단계 실행"""
        return self.run_stage(HookStage.STOP, context, abort_on_failure=False)

    def get_hooks(self, stage: HookStage) -> List[Hook]:
        """특정 단계의 Hook 목록 반환"""
        return self._hooks.get(stage, [])

    def clear(self, stage: Optional[HookStage] = None) -> "HookChain":
        """
        Hook 제거

        Args:
            stage: 제거할 단계 (None이면 전체)
        """
        if stage:
            self._hooks[stage] = []
        else:
            for s in HookStage:
                self._hooks[s] = []
        return self


# =============================================================================
# Default Chain Factory
# =============================================================================

def create_default_chain() -> HookChain:
    """
    기본 Hook Chain 생성

    Returns:
        PreRunHook + PreReviewHook + PostReviewHook + StopHook이 등록된 체인
    """
    from .pre_run import PreRunHook
    from .pre_review import PreReviewHook
    from .post_review import PostReviewHook
    from .stop import StopHook

    chain = HookChain()
    chain.register(PreRunHook())
    chain.register(PreReviewHook())
    chain.register(PostReviewHook())
    chain.register(StopHook())

    return chain


def create_minimal_chain() -> HookChain:
    """
    최소 Hook Chain (Static Gate만)

    비용 최적화용 - LLM 없이 Static Check만 수행
    """
    from .pre_review import PreReviewHook
    from .stop import StopHook

    chain = HookChain()
    chain.register(PreReviewHook())
    chain.register(StopHook())

    return chain
