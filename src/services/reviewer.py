"""
Hattz Empire - Reviewer Service
CEO 완성본 v2.3 - Hook Chain 통합 버전

Step 0: Static Checker (0원 1차 게이트) - AST + Regex
Step 1: LLM Reviewer (의미론/리스크/품질)

Hook Chain Integration:
- pre_run: 세션 규정 로드, 컨텍스트 헤더 생성
- pre_review: Static Gate 실행
- post_review: 감사 로그 기록
- stop: 실패/중단 사유 기록
"""
from __future__ import annotations
from typing import Optional

from src.control.static_check import StaticChecker
from src.control.prompt_injector import build_injected_context, make_reviewer_prompt
from src.control.verdict import parse_reviewer_output, ReviewVerdict, Violation
from src.control.event_bus import EventBus
from src.control.rules import SessionRules
from src.control.audit_log import AuditLogger

# Hook imports
from src.hooks import (
    HookContext,
    HookChain,
    PreRunHook,
    PreReviewHook,
    PostReviewHook,
    StopHook,
)
from src.hooks.chain import create_default_chain
from src.hooks.stop import StopCode


class ReviewerService:
    """
    3중 방어선 Reviewer

    1. Static Gate (0원): 기계적으로 잡을 수 있는 위반 즉시 REJECT
    2. LLM Reviewer: 의미론적 검토 (Constitution + Session Rules)
    3. Runtime Guard: 실제 API wrapper에서 마지막 방어
    """

    def __init__(
        self,
        llm_client=None,
        event_bus: EventBus = None,
        audit_logger: AuditLogger = None,
        use_hooks: bool = True,
    ):
        """
        Args:
            llm_client: LLM 호출 클라이언트 (call_agent 등)
            event_bus: 이벤트 버스 (없으면 자동 생성)
            audit_logger: 감사 로거 (없으면 자동 생성)
            use_hooks: Hook Chain 사용 여부
        """
        self.llm = llm_client
        self.event_bus = event_bus or EventBus()
        self.audit_logger = audit_logger or AuditLogger()
        self.use_hooks = use_hooks

        # Hook Chain 초기화
        if use_hooks:
            self.hook_chain = create_default_chain()
        else:
            self.hook_chain = None

    def review(
        self,
        session_rules: SessionRules,
        task: str,
        worker_output: str,
        diff_summary: str = "",
        test_results: str = "",
    ) -> ReviewVerdict:
        """
        Worker 출력물 검토

        Args:
            session_rules: 세션 규정
            task: 원래 태스크/요청
            worker_output: Worker의 출력물 (코드 등)
            diff_summary: 변경 파일 요약
            test_results: 테스트 결과

        Returns:
            ReviewVerdict: PASS | REJECT + violations
        """
        # =====================================================
        # [Step 0] Static Checker (0원 1차 게이트)
        # =====================================================
        static_checker = StaticChecker(session_rules.rules.code)
        static_violations = static_checker.check(worker_output)

        if static_violations:
            # Static Gate에서 위반 발견 → 즉시 REJECT (LLM 호출 안 함)
            self.event_bus.emit("STATIC_REJECT", {
                "session_id": session_rules.session_id,
                "rules_hash": session_rules.rules_hash(),
                "violations": [sv.__dict__ for sv in static_violations],
            })

            return ReviewVerdict(
                verdict="REJECT",
                violations=[
                    Violation(key=sv.key, detail=f"{sv.detail} | evidence: {sv.evidence}")
                    for sv in static_violations
                ],
                required_fixes=["Fix static gate violations, then re-run."],
                notes=["Auto-rejected by Static Checker (0원 1차 게이트)"]
            )

        # =====================================================
        # [Step 1] LLM Reviewer (의미론/리스크/품질)
        # =====================================================
        if self.llm is None:
            # LLM 클라이언트 없으면 Static만 통과로 처리
            self.event_bus.emit("REVIEW_SKIPPED", {
                "session_id": session_rules.session_id,
                "reason": "No LLM client configured",
            })
            return ReviewVerdict(
                verdict="PASS",
                violations=[],
                required_fixes=[],
                notes=["Static check passed. LLM review skipped (no client)."]
            )

        # LLM Reviewer 프롬프트 빌드
        ctx = build_injected_context(session_rules)
        static_gate_report = "STATIC_GATE: no violations found."

        prompt = make_reviewer_prompt(
            ctx=ctx,
            task=task,
            worker_output=worker_output,
            diff_summary=diff_summary,
            test_results=test_results,
            static_gate_report=static_gate_report,
        )

        # LLM 호출
        try:
            raw_response = self.llm(prompt)  # call_agent 등
        except Exception as e:
            self.event_bus.emit("REVIEW_ERROR", {
                "session_id": session_rules.session_id,
                "error": str(e),
            })
            return ReviewVerdict(
                verdict="REJECT",
                violations=[Violation(key="llm_error", detail=str(e))],
                required_fixes=["LLM review failed. Manual review required."],
                notes=[f"Error: {e}"]
            )

        # LLM 응답 파싱
        verdict = parse_reviewer_output(raw_response)

        # 이벤트 발행
        self.event_bus.emit("REVIEW_FINISHED", {
            "session_id": session_rules.session_id,
            "rules_hash": session_rules.rules_hash(),
            "verdict": verdict.verdict,
            "violations": [{"key": v.key, "detail": v.detail} for v in verdict.violations],
        })

        return verdict

    def static_check_only(
        self,
        session_rules: SessionRules,
        code: str,
    ) -> list:
        """
        Static Check만 수행 (LLM 없이)

        Returns:
            List[StaticViolation]
        """
        static_checker = StaticChecker(session_rules.rules.code)
        return static_checker.check(code)

    def review_with_hooks(
        self,
        session_id: str,
        task_id: str,
        task: str,
        worker_output: str,
        diff_summary: str = "",
        test_results: str = "",
    ) -> ReviewVerdict:
        """
        Hook Chain을 사용한 리뷰

        전체 흐름:
        1. pre_run: 세션 규정 로드 + 컨텍스트 준비
        2. pre_review: Static Gate 실행
        3. LLM Review (Static 통과 시)
        4. post_review: 감사 로그 기록
        5. stop: 종료 처리

        Args:
            session_id: 세션 ID (규정 로드용)
            task_id: 태스크 ID
            task: 원래 태스크
            worker_output: Worker 출력물
            diff_summary: 변경 파일 요약
            test_results: 테스트 결과

        Returns:
            ReviewVerdict
        """
        if not self.use_hooks or not self.hook_chain:
            # Hook 없으면 기존 방식 사용
            from src.control.rules_store import RulesStore
            store = RulesStore()
            session_rules = store.load(session_id)
            return self.review(session_rules, task, worker_output, diff_summary, test_results)

        # =====================================================
        # [Step 1] PRE_RUN Hook
        # =====================================================
        ctx = HookContext(
            session_id=session_id,
            task_id=task_id,
            task=task,
            worker_output=worker_output,
            diff_summary=diff_summary,
            test_results=test_results,
        )

        pre_run_result = self.hook_chain.run_pre_run(ctx)

        if not pre_run_result.success:
            return ReviewVerdict(
                verdict="REJECT",
                violations=[Violation(key="pre_run_error", detail=pre_run_result.error or "Unknown error")],
                required_fixes=["Fix pre_run hook error"],
                notes=["Pre-run hook failed"]
            )

        # session_rules 추출
        session_rules = pre_run_result.results.get("PreRunHook", {}).output.get("session_rules")
        if not session_rules:
            return ReviewVerdict(
                verdict="REJECT",
                violations=[Violation(key="no_session_rules", detail="Failed to load session rules")],
                required_fixes=["Ensure session rules exist"],
                notes=["Session rules not found"]
            )

        # 컨텍스트 업데이트
        ctx = pre_run_result.final_context
        ctx.metadata["session_rules"] = session_rules

        # =====================================================
        # [Step 2] PRE_REVIEW Hook (Static Gate)
        # =====================================================
        pre_review_result = self.hook_chain.run_pre_review(ctx)

        if pre_review_result.abort_hook:
            # Static Gate REJECT
            ctx.verdict = "REJECT"
            ctx.violations = ctx.static_violations

            # post_review 로깅
            self.hook_chain.run_post_review(ctx)

            return ReviewVerdict(
                verdict="REJECT",
                violations=[
                    Violation(key=v.get("key", "static"), detail=f"{v.get('detail', '')} | evidence: {v.get('evidence', '')}")
                    for v in ctx.static_violations
                ],
                required_fixes=["Fix static gate violations, then re-run."],
                notes=["Auto-rejected by Static Gate (Hook Chain)"]
            )

        # =====================================================
        # [Step 3] LLM Reviewer
        # =====================================================
        verdict = self.review(session_rules, task, worker_output, diff_summary, test_results)

        # =====================================================
        # [Step 4] POST_REVIEW Hook
        # =====================================================
        ctx.verdict = verdict.verdict
        ctx.violations = [{"key": v.key, "detail": v.detail} for v in verdict.violations]
        ctx.required_fixes = verdict.required_fixes

        self.hook_chain.run_post_review(ctx)

        # =====================================================
        # [Step 5] STOP Hook
        # =====================================================
        stop_code = StopCode.REVIEW_PASS if verdict.verdict == "PASS" else StopCode.LLM_REJECT
        ctx = StopHook.make_stop_context(
            ctx,
            stop_code=stop_code,
            stop_reason=f"Review completed: {verdict.verdict}",
            recoverable=(verdict.verdict == "REJECT"),
        )
        self.hook_chain.run_stop(ctx)

        return verdict


# 편의 함수
def quick_static_check(code: str) -> list:
    """
    기본 규칙으로 빠른 정적 검사

    Returns:
        List[StaticViolation]
    """
    from src.control.rules import CodeRules
    checker = StaticChecker(CodeRules())
    return checker.check(code)


def review_with_session(
    session_id: str,
    task: str,
    worker_output: str,
    llm_client=None,
) -> ReviewVerdict:
    """
    세션 ID로 빠른 리뷰

    Args:
        session_id: 세션 ID
        task: 태스크
        worker_output: Worker 출력물
        llm_client: LLM 클라이언트 (없으면 Static만)

    Returns:
        ReviewVerdict
    """
    service = ReviewerService(llm_client=llm_client, use_hooks=True)
    return service.review_with_hooks(
        session_id=session_id,
        task_id="quick-review",
        task=task,
        worker_output=worker_output,
    )
