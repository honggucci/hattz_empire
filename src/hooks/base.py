"""
Hattz Empire - Hook Base Classes
CEO 완성본 - Hook 인터페이스 추상 클래스
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
from enum import Enum


class HookStage(str, Enum):
    """Hook 실행 단계"""
    PRE_RUN = "pre_run"
    PRE_REVIEW = "pre_review"
    POST_REVIEW = "post_review"
    STOP = "stop"


@dataclass
class HookContext:
    """
    Hook 실행 컨텍스트

    모든 Hook에서 공유하는 컨텍스트 객체
    """
    # 세션 정보
    session_id: str
    task_id: str = ""

    # 규정
    rules_hash: str = ""
    mode: str = ""  # live, dev, backtest
    risk_profile: str = ""  # strict, normal, fast

    # Worker 정보
    worker_role: str = ""
    worker_output: str = ""

    # 태스크 정보
    task: str = ""
    diff_summary: str = ""
    test_results: str = ""

    # Static Check 결과 (pre_review에서 설정)
    static_violations: List[Dict[str, Any]] = field(default_factory=list)

    # Review 결과 (post_review에서 사용)
    verdict: str = ""  # PASS, REJECT
    violations: List[Dict[str, Any]] = field(default_factory=list)
    required_fixes: List[str] = field(default_factory=list)

    # 추가 메타데이터
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환 (로깅용)"""
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "rules_hash": self.rules_hash,
            "mode": self.mode,
            "risk_profile": self.risk_profile,
            "worker_role": self.worker_role,
            "task": self.task[:200] if self.task else "",
            "verdict": self.verdict,
            "static_violations_count": len(self.static_violations),
            "violations_count": len(self.violations),
        }


@dataclass
class HookResult:
    """
    Hook 실행 결과
    """
    success: bool
    stage: HookStage

    # 다음 단계로 전달할 데이터
    context: Optional[HookContext] = None

    # 조기 종료 (pre_review에서 REJECT 등)
    should_abort: bool = False
    abort_reason: str = ""

    # 출력 데이터
    output: Dict[str, Any] = field(default_factory=dict)

    # 에러 정보
    error: Optional[str] = None

    def __repr__(self) -> str:
        status = "✅" if self.success else "❌"
        abort_info = f" [ABORT: {self.abort_reason}]" if self.should_abort else ""
        return f"HookResult({status} {self.stage.value}{abort_info})"


class Hook(ABC):
    """
    Hook 추상 베이스 클래스

    모든 Hook은 이 클래스를 상속하여 구현
    """

    @property
    @abstractmethod
    def stage(self) -> HookStage:
        """Hook 단계"""
        pass

    @property
    def name(self) -> str:
        """Hook 이름 (기본값: 클래스명)"""
        return self.__class__.__name__

    @abstractmethod
    def execute(self, context: HookContext) -> HookResult:
        """
        Hook 실행

        Args:
            context: 실행 컨텍스트

        Returns:
            HookResult: 실행 결과
        """
        pass

    def validate(self, context: HookContext) -> bool:
        """
        실행 전 유효성 검증 (오버라이드 가능)

        Returns:
            True: 실행 진행
            False: 스킵
        """
        return True

    def on_error(self, context: HookContext, error: Exception) -> HookResult:
        """
        에러 발생 시 처리 (오버라이드 가능)
        """
        return HookResult(
            success=False,
            stage=self.stage,
            context=context,
            error=str(error)
        )
