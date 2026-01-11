"""
Hattz Empire - Pre-Review Hook
CEO 완성본 - StaticChecker 우선 실행 → 위반 시 LLM 없이 REJECT

기능:
1. StaticChecker로 0원 1차 게이트 실행
2. 위반 발견 시 즉시 REJECT (LLM 호출 안 함)
3. 위반 없으면 LLM Reviewer로 진행 허용
"""
from __future__ import annotations
from typing import List

from .base import Hook, HookContext, HookResult, HookStage


class PreReviewHook(Hook):
    """
    Pre-Review Hook (0원 1차 게이트)

    Worker 출력물을 LLM Reviewer에 보내기 전 Static Check 수행
    위반 시 즉시 REJECT → 비용 절감
    """

    def __init__(self, session_rules=None):
        """
        Args:
            session_rules: SessionRules 인스턴스 (pre_run에서 전달받음)
        """
        self._session_rules = session_rules

    @property
    def stage(self) -> HookStage:
        return HookStage.PRE_REVIEW

    def execute(self, context: HookContext) -> HookResult:
        """
        실행:
        1. Worker 출력물에서 코드 추출
        2. StaticChecker로 검사
        3. 위반 시 should_abort=True로 반환
        """
        try:
            # Session Rules 가져오기 (pre_run output에서)
            session_rules = self._session_rules
            if session_rules is None:
                # context.metadata에서 가져오기 시도
                session_rules = context.metadata.get("session_rules")

            if session_rules is None:
                return HookResult(
                    success=False,
                    stage=self.stage,
                    context=context,
                    error="No session_rules available for static check"
                )

            # StaticChecker 실행
            from src.control.static_check import StaticChecker
            static_checker = StaticChecker(session_rules.rules.code)
            violations = static_checker.check(context.worker_output)

            if violations:
                # 위반 발견 → 즉시 REJECT
                context.static_violations = [
                    {
                        "key": v.key,
                        "detail": v.detail,
                        "evidence": v.evidence,
                        "line": v.line,
                    }
                    for v in violations
                ]

                return HookResult(
                    success=True,  # Hook 자체는 성공
                    stage=self.stage,
                    context=context,
                    should_abort=True,
                    abort_reason=f"STATIC_REJECT: {len(violations)} violation(s) found",
                    output={
                        "verdict": "REJECT",
                        "violations": context.static_violations,
                        "gate": "static",
                        "llm_skipped": True,
                    }
                )

            # 위반 없음 → LLM Reviewer로 진행
            return HookResult(
                success=True,
                stage=self.stage,
                context=context,
                should_abort=False,
                output={
                    "static_check": "PASS",
                    "violations_count": 0,
                    "proceed_to_llm": True,
                }
            )

        except Exception as e:
            return self.on_error(context, e)

    def validate(self, context: HookContext) -> bool:
        """worker_output이 있어야 실행"""
        return bool(context.worker_output)

    @staticmethod
    def quick_check(code: str, code_rules=None) -> List[dict]:
        """
        빠른 정적 검사 (편의 메서드)

        Args:
            code: 검사할 코드
            code_rules: CodeRules 인스턴스 (없으면 기본값)

        Returns:
            List of violation dicts
        """
        from src.control.static_check import StaticChecker
        from src.control.rules import CodeRules

        rules = code_rules or CodeRules()
        checker = StaticChecker(rules)
        violations = checker.check(code)

        return [
            {
                "key": v.key,
                "detail": v.detail,
                "evidence": v.evidence,
                "line": v.line,
            }
            for v in violations
        ]
