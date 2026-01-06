"""
Hattz Empire - Post-Review Hook
CEO 완성본 - verdict + rules_hash + evidence + required_fixes 저장

기능:
1. Review 결과 (verdict) 감사 로그에 기록
2. rules_hash로 어떤 규정 버전에서 판정됐는지 추적
3. violations + evidence + required_fixes 구조화 저장
4. 이벤트 버스로 REVIEW_FINISHED 발행
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime

from .base import Hook, HookContext, HookResult, HookStage


class PostReviewHook(Hook):
    """
    Post-Review Hook

    LLM Reviewer 판정 후 감사 로그 기록 및 이벤트 발행
    """

    def __init__(self, audit_logger=None, event_bus=None):
        """
        Args:
            audit_logger: AuditLogger 인스턴스 (없으면 자동 생성)
            event_bus: EventBus 인스턴스 (없으면 자동 생성)
        """
        self._audit_logger = audit_logger
        self._event_bus = event_bus

    @property
    def stage(self) -> HookStage:
        return HookStage.POST_REVIEW

    @property
    def audit_logger(self):
        """Lazy loading for AuditLogger"""
        if self._audit_logger is None:
            from src.control.audit_log import AuditLogger
            self._audit_logger = AuditLogger()
        return self._audit_logger

    @property
    def event_bus(self):
        """Lazy loading for EventBus"""
        if self._event_bus is None:
            from src.control.event_bus import EventBus
            self._event_bus = EventBus()
        return self._event_bus

    def execute(self, context: HookContext) -> HookResult:
        """
        실행:
        1. Review 결과 구조화
        2. 감사 로그 기록
        3. 이벤트 발행
        """
        try:
            # 감사 로그 데이터 구조화
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "session_id": context.session_id,
                "task_id": context.task_id,
                "rules_hash": context.rules_hash,
                "mode": context.mode,
                "risk_profile": context.risk_profile,
                "worker_role": context.worker_role,
                "verdict": context.verdict,
                "violations": context.violations,
                "static_violations": context.static_violations,
                "required_fixes": context.required_fixes,
                "task_summary": context.task[:200] if context.task else "",
            }

            # 감사 로그 기록
            self.audit_logger.log("REVIEW_COMPLETE", log_entry)

            # 이벤트 발행
            event_type = "REVIEW_PASS" if context.verdict == "PASS" else "REVIEW_REJECT"
            self.event_bus.emit(event_type, {
                "session_id": context.session_id,
                "task_id": context.task_id,
                "rules_hash": context.rules_hash,
                "verdict": context.verdict,
                "violations_count": len(context.violations) + len(context.static_violations),
            })

            return HookResult(
                success=True,
                stage=self.stage,
                context=context,
                output={
                    "logged": True,
                    "event_emitted": event_type,
                    "log_entry": log_entry,
                }
            )

        except Exception as e:
            return self.on_error(context, e)

    def validate(self, context: HookContext) -> bool:
        """verdict가 설정되어 있어야 실행"""
        return bool(context.verdict)

    def log_static_reject(self, context: HookContext) -> HookResult:
        """
        Static Gate에서 REJECT된 경우 로깅

        pre_review에서 should_abort=True일 때 호출
        """
        try:
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "session_id": context.session_id,
                "task_id": context.task_id,
                "rules_hash": context.rules_hash,
                "mode": context.mode,
                "risk_profile": context.risk_profile,
                "verdict": "REJECT",
                "gate": "static",
                "static_violations": context.static_violations,
                "llm_skipped": True,
            }

            self.audit_logger.log("STATIC_REJECT", log_entry)
            self.event_bus.emit("STATIC_REJECT", {
                "session_id": context.session_id,
                "rules_hash": context.rules_hash,
                "violations_count": len(context.static_violations),
            })

            return HookResult(
                success=True,
                stage=self.stage,
                context=context,
                output={
                    "logged": True,
                    "event_emitted": "STATIC_REJECT",
                    "log_entry": log_entry,
                }
            )

        except Exception as e:
            return self.on_error(context, e)
