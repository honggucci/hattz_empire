"""
Hattz Empire - Pre-Run Hook
CEO 완성본 - 세션 규정 로드 → 해시 계산 → 컨텍스트 헤더 생성

기능:
1. Session Rules JSON 로드
2. rules_hash 계산 (감사 추적용)
3. Constitution + Rules 기반 컨텍스트 헤더 생성
4. Worker에게 전달할 InjectedContext 준비
"""
from __future__ import annotations

from .base import Hook, HookContext, HookResult, HookStage


class PreRunHook(Hook):
    """
    Pre-Run Hook

    Worker 실행 전 세션 규정 로드 및 컨텍스트 준비
    """

    def __init__(self, rules_store=None):
        """
        Args:
            rules_store: RulesStore 인스턴스 (없으면 자동 생성)
        """
        self._rules_store = rules_store

    @property
    def stage(self) -> HookStage:
        return HookStage.PRE_RUN

    @property
    def rules_store(self):
        """Lazy loading for RulesStore"""
        if self._rules_store is None:
            from src.control.rules_store import RulesStore
            self._rules_store = RulesStore()
        return self._rules_store

    def execute(self, context: HookContext) -> HookResult:
        """
        실행:
        1. session_id로 규정 JSON 로드
        2. rules_hash 계산
        3. 컨텍스트 헤더 빌드
        """
        try:
            # 1) Session Rules 로드
            session_rules = self.rules_store.load(context.session_id)

            # 2) rules_hash 계산 (감사 추적용)
            rules_hash = session_rules.rules_hash()

            # 3) 컨텍스트 업데이트
            context.rules_hash = rules_hash
            context.mode = session_rules.mode  # Literal type (문자열)
            context.risk_profile = session_rules.risk_profile  # Literal type (문자열)

            # 4) InjectedContext 빌드 (Worker 프롬프트용)
            from src.control.prompt_injector import build_injected_context, make_worker_context
            injected_ctx = build_injected_context(session_rules)
            worker_header = make_worker_context(session_rules)  # SessionRules 전달

            # 5) 결과 반환
            return HookResult(
                success=True,
                stage=self.stage,
                context=context,
                output={
                    "session_rules": session_rules,
                    "injected_context": injected_ctx,
                    "worker_header": worker_header,
                    "rules_hash": rules_hash,
                    "mode": session_rules.mode,
                    "risk_profile": session_rules.risk_profile,
                }
            )

        except FileNotFoundError as e:
            # 규정 파일 없음 → 기본 규정 사용
            return self._use_default_rules(context, str(e))

        except Exception as e:
            return self.on_error(context, e)

    def _use_default_rules(self, context: HookContext, reason: str) -> HookResult:
        """
        규정 파일 없을 때 기본값 사용

        dev-default를 기본값으로 시도, 그것도 없으면 인메모리 기본값
        """
        try:
            # dev-default 시도
            default_rules = self.rules_store.load("dev-default")
            rules_hash = default_rules.rules_hash()

            context.rules_hash = rules_hash
            context.mode = default_rules.mode
            context.risk_profile = default_rules.risk_profile

            from src.control.prompt_injector import build_injected_context, make_worker_context
            injected_ctx = build_injected_context(default_rules)
            worker_header = make_worker_context(default_rules)  # SessionRules 전달

            return HookResult(
                success=True,
                stage=self.stage,
                context=context,
                output={
                    "session_rules": default_rules,
                    "injected_context": injected_ctx,
                    "worker_header": worker_header,
                    "rules_hash": rules_hash,
                    "fallback_reason": reason,
                    "using_default": True,
                }
            )

        except Exception:
            # 모든 규정 로드 실패 → 인메모리 기본값
            from src.control.rules import SessionRules, Mode, RiskProfile

            default_rules = SessionRules(
                session_id=context.session_id,
                mode=Mode.DEV,
                risk_profile=RiskProfile.NORMAL,
            )
            rules_hash = default_rules.rules_hash()

            context.rules_hash = rules_hash
            context.mode = "dev"
            context.risk_profile = "normal"

            from src.control.prompt_injector import build_injected_context, make_worker_context
            injected_ctx = build_injected_context(default_rules)
            worker_header = make_worker_context(default_rules)  # SessionRules 전달

            return HookResult(
                success=True,
                stage=self.stage,
                context=context,
                output={
                    "session_rules": default_rules,
                    "injected_context": injected_ctx,
                    "worker_header": worker_header,
                    "rules_hash": rules_hash,
                    "fallback_reason": f"{reason} + dev-default also not found",
                    "using_inmemory_default": True,
                }
            )

    def validate(self, context: HookContext) -> bool:
        """session_id가 있어야 실행"""
        return bool(context.session_id)
