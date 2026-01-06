"""
Hattz Empire - Stop Hook
CEO 완성본 - 실패/중단 사유 표준 코드로 기록

기능:
1. 태스크 실패/중단 시 표준 코드로 기록
2. 에러 컨텍스트 구조화 (traceback, last_output 등)
3. 복구 가능 여부 판단
4. 감사 로그 + 이벤트 발행
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime
from enum import Enum

from .base import Hook, HookContext, HookResult, HookStage


class StopCode(str, Enum):
    """표준 중단 코드"""
    # 정상 종료
    COMPLETED = "COMPLETED"              # 태스크 정상 완료
    REVIEW_PASS = "REVIEW_PASS"          # 리뷰 통과 후 종료

    # 정책 위반
    STATIC_REJECT = "STATIC_REJECT"      # Static Gate 위반
    LLM_REJECT = "LLM_REJECT"            # LLM Reviewer 거절
    CONSTITUTION_VIOLATION = "CONSTITUTION_VIOLATION"  # 헌법 위반

    # 시스템 제한
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"  # Circuit Breaker 발동
    TOKEN_LIMIT = "TOKEN_LIMIT"          # 토큰 한도 초과
    COST_LIMIT = "COST_LIMIT"            # 비용 한도 초과
    TIME_LIMIT = "TIME_LIMIT"            # 시간 한도 초과
    MAX_ROUNDS = "MAX_ROUNDS"            # 최대 라운드 초과

    # 사용자 액션
    USER_ABORT = "USER_ABORT"            # 사용자 중단
    USER_CANCEL = "USER_CANCEL"          # 사용자 취소

    # 에러
    LLM_ERROR = "LLM_ERROR"              # LLM 호출 실패
    SYSTEM_ERROR = "SYSTEM_ERROR"        # 시스템 에러
    UNKNOWN_ERROR = "UNKNOWN_ERROR"      # 알 수 없는 에러


class StopHook(Hook):
    """
    Stop Hook

    태스크 종료 시 실패/중단 사유 기록
    """

    def __init__(self, audit_logger=None, event_bus=None):
        """
        Args:
            audit_logger: AuditLogger 인스턴스
            event_bus: EventBus 인스턴스
        """
        self._audit_logger = audit_logger
        self._event_bus = event_bus

    @property
    def stage(self) -> HookStage:
        return HookStage.STOP

    @property
    def audit_logger(self):
        if self._audit_logger is None:
            from src.control.audit_log import AuditLogger
            self._audit_logger = AuditLogger()
        return self._audit_logger

    @property
    def event_bus(self):
        if self._event_bus is None:
            from src.control.event_bus import EventBus
            self._event_bus = EventBus()
        return self._event_bus

    def execute(self, context: HookContext) -> HookResult:
        """
        실행:
        1. 중단 코드 결정
        2. 컨텍스트 구조화
        3. 감사 로그 기록
        4. 이벤트 발행
        """
        try:
            # metadata에서 stop 정보 추출
            stop_code = context.metadata.get("stop_code", StopCode.UNKNOWN_ERROR)
            stop_reason = context.metadata.get("stop_reason", "")
            error_trace = context.metadata.get("error_trace", "")
            last_output = context.metadata.get("last_output", "")
            recoverable = context.metadata.get("recoverable", False)

            # 문자열을 StopCode로 변환
            if isinstance(stop_code, str):
                try:
                    stop_code = StopCode(stop_code)
                except ValueError:
                    stop_code = StopCode.UNKNOWN_ERROR

            # 감사 로그 데이터
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "session_id": context.session_id,
                "task_id": context.task_id,
                "rules_hash": context.rules_hash,
                "mode": context.mode,
                "risk_profile": context.risk_profile,
                "stop_code": stop_code.value,
                "stop_reason": stop_reason,
                "recoverable": recoverable,
                "verdict": context.verdict,
                "violations_count": len(context.violations) + len(context.static_violations),
                "error_trace": error_trace[:500] if error_trace else "",
                "last_output": last_output[:500] if last_output else "",
            }

            # 감사 로그 기록
            event_name = self._get_event_name(stop_code)
            self.audit_logger.log(event_name, log_entry)

            # 이벤트 발행
            self.event_bus.emit(event_name, {
                "session_id": context.session_id,
                "task_id": context.task_id,
                "stop_code": stop_code.value,
                "recoverable": recoverable,
            })

            return HookResult(
                success=True,
                stage=self.stage,
                context=context,
                output={
                    "stop_code": stop_code.value,
                    "stop_reason": stop_reason,
                    "recoverable": recoverable,
                    "event_emitted": event_name,
                    "log_entry": log_entry,
                }
            )

        except Exception as e:
            return self.on_error(context, e)

    def _get_event_name(self, stop_code: StopCode) -> str:
        """StopCode에 따른 이벤트 이름 결정"""
        event_map = {
            StopCode.COMPLETED: "TASK_COMPLETED",
            StopCode.REVIEW_PASS: "TASK_COMPLETED",
            StopCode.STATIC_REJECT: "TASK_REJECTED",
            StopCode.LLM_REJECT: "TASK_REJECTED",
            StopCode.CONSTITUTION_VIOLATION: "TASK_REJECTED",
            StopCode.CIRCUIT_BREAKER: "TASK_ABORTED",
            StopCode.TOKEN_LIMIT: "TASK_ABORTED",
            StopCode.COST_LIMIT: "TASK_ABORTED",
            StopCode.TIME_LIMIT: "TASK_ABORTED",
            StopCode.MAX_ROUNDS: "TASK_ABORTED",
            StopCode.USER_ABORT: "TASK_ABORTED",
            StopCode.USER_CANCEL: "TASK_CANCELLED",
            StopCode.LLM_ERROR: "TASK_ERROR",
            StopCode.SYSTEM_ERROR: "TASK_ERROR",
            StopCode.UNKNOWN_ERROR: "TASK_ERROR",
        }
        return event_map.get(stop_code, "TASK_STOPPED")

    def validate(self, context: HookContext) -> bool:
        """항상 실행 (종료 시점이므로)"""
        return True

    # 편의 메서드들
    @classmethod
    def make_stop_context(
        cls,
        context: HookContext,
        stop_code: StopCode,
        stop_reason: str = "",
        error_trace: str = "",
        last_output: str = "",
        recoverable: bool = False,
    ) -> HookContext:
        """
        Stop 정보가 설정된 컨텍스트 생성

        Args:
            context: 기존 컨텍스트
            stop_code: 중단 코드
            stop_reason: 중단 사유
            error_trace: 에러 트레이스백
            last_output: 마지막 출력
            recoverable: 복구 가능 여부

        Returns:
            stop 정보가 설정된 HookContext
        """
        context.metadata["stop_code"] = stop_code
        context.metadata["stop_reason"] = stop_reason
        context.metadata["error_trace"] = error_trace
        context.metadata["last_output"] = last_output
        context.metadata["recoverable"] = recoverable
        return context
