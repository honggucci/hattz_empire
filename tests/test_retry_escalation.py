"""
Retry Escalation 불변조건 테스트 (v2.5.5)

GPT-5.2 지시사항:
- monotonic: 에스컬레이션은 역행하지 않는다
- terminal: HARD_FAIL은 시스템 종료점
- once: ROLE_SWITCH는 1회만 허용
"""
import pytest
from enum import Enum, auto
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
import hashlib
import threading
import time


# =============================================================================
# Inline Copy (config.py 의존성 회피)
# =============================================================================

class EscalationLevel(Enum):
    """에스컬레이션 레벨"""
    SELF_REPAIR = auto()   # 1차: 에러 피드백 포함 재시도
    ROLE_SWITCH = auto()   # 2차: 다른 역할로 전환
    HARD_FAIL = auto()     # 3차: CEO 에스컬레이션


@dataclass(frozen=True)
class FailureSignature:
    """실패 시그니처 (해시 기반 중복 감지)"""
    error_type: str
    missing_fields: Tuple[str, ...]
    profile: str
    prompt_hash: str

    def to_dict(self) -> dict:
        return {
            "error_type": self.error_type,
            "missing_fields": list(self.missing_fields),
            "profile": self.profile,
            "prompt_hash": self.prompt_hash[:8]
        }


class RetryEscalator:
    """Retry Escalation Manager (테스트용 복사본)"""

    ROLE_SWITCH_MAP = {
        "coder": "reviewer",
        "reviewer": "coder",
        "qa": "coder",
        "council": "reviewer",
    }

    def __init__(self, max_same_signature: int = 2):
        self.max_same_signature = max_same_signature
        self._failure_history: Dict[FailureSignature, int] = {}
        self._escalation_log: List[Dict] = []
        self._lock = threading.Lock()
        self._role_switch_used: Dict[str, bool] = {}  # 프로필별 역할 전환 사용 여부

    def compute_signature(
        self,
        error_type: str,
        missing_fields: List[str],
        profile: str,
        prompt: str
    ) -> FailureSignature:
        prompt_snippet = prompt[:500] if prompt else ""
        prompt_hash = hashlib.md5(prompt_snippet.encode()).hexdigest()

        return FailureSignature(
            error_type=error_type,
            missing_fields=tuple(sorted(missing_fields)) if missing_fields else (),
            profile=profile,
            prompt_hash=prompt_hash
        )

    def record_failure(self, signature: FailureSignature) -> EscalationLevel:
        with self._lock:
            count = self._failure_history.get(signature, 0) + 1
            self._failure_history[signature] = count

            self._escalation_log.append({
                "timestamp": time.time(),
                "signature": signature.to_dict(),
                "count": count
            })

            if count >= self.max_same_signature + 1:
                level = EscalationLevel.HARD_FAIL
            elif count == self.max_same_signature:
                level = EscalationLevel.ROLE_SWITCH
            else:
                level = EscalationLevel.SELF_REPAIR

            return level

    def get_escalation_action(
        self,
        level: EscalationLevel,
        current_profile: str,
        original_prompt: str,
        error_message: str
    ) -> Dict[str, Any]:
        if level == EscalationLevel.HARD_FAIL:
            return {
                "action": "abort",
                "reason": f"동일 에러 반복 (max={self.max_same_signature}회 초과)",
                "error_type": "ESCALATION_HARD_FAIL"
            }

        elif level == EscalationLevel.ROLE_SWITCH:
            # 역할 전환 1회 제한 체크
            if self._role_switch_used.get(current_profile, False):
                return {
                    "action": "abort",
                    "reason": "역할 전환 이미 사용됨 (1회 제한)",
                    "error_type": "ROLE_SWITCH_EXHAUSTED"
                }

            self._role_switch_used[current_profile] = True
            new_profile = self.ROLE_SWITCH_MAP.get(current_profile, "reviewer")

            return {
                "action": "switch",
                "new_profile": new_profile,
                "modified_prompt": f"[ROLE_SWITCH] {original_prompt}",
                "reason": f"역할 전환: {current_profile} → {new_profile}"
            }

        else:  # SELF_REPAIR
            return {
                "action": "retry",
                "modified_prompt": f"[ERROR_FEEDBACK] {error_message}\n{original_prompt}",
                "reason": "에러 피드백 포함 재시도"
            }

    def clear_history(self, profile: str = None):
        with self._lock:
            if profile:
                keys_to_remove = [k for k in self._failure_history if k.profile == profile]
                for k in keys_to_remove:
                    del self._failure_history[k]
                if profile in self._role_switch_used:
                    del self._role_switch_used[profile]
            else:
                self._failure_history.clear()
                self._role_switch_used.clear()


# =============================================================================
# 불변조건 테스트
# =============================================================================

class TestEscalationInvariants:
    """에스컬레이션 불변조건 테스트"""

    def setup_method(self):
        self.escalator = RetryEscalator(max_same_signature=2)

    # =========================================================================
    # MONOTONIC: 에스컬레이션은 역행하지 않는다
    # =========================================================================

    def test_escalation_is_monotonic(self):
        """에스컬레이션 레벨은 단조 증가만 허용"""
        sig = self.escalator.compute_signature(
            "JSON_PARSE_ERROR", ["summary"], "coder", "test prompt"
        )

        # 1차 실패: SELF_REPAIR
        level1 = self.escalator.record_failure(sig)
        assert level1 == EscalationLevel.SELF_REPAIR

        # 2차 실패: ROLE_SWITCH (증가)
        level2 = self.escalator.record_failure(sig)
        assert level2 == EscalationLevel.ROLE_SWITCH
        assert level2.value >= level1.value, "레벨은 단조 증가해야 함"

        # 3차 실패: HARD_FAIL (증가)
        level3 = self.escalator.record_failure(sig)
        assert level3 == EscalationLevel.HARD_FAIL
        assert level3.value >= level2.value, "레벨은 단조 증가해야 함"

    def test_level_never_decreases(self):
        """동일 시그니처에 대해 레벨이 절대 감소하지 않음"""
        sig = self.escalator.compute_signature(
            "SEMANTIC_NULL", [], "qa", "qa task"
        )

        prev_level = None
        for _ in range(5):  # 여러 번 실패
            level = self.escalator.record_failure(sig)
            if prev_level is not None:
                assert level.value >= prev_level.value, \
                    f"레벨 감소 감지: {prev_level} -> {level}"
            prev_level = level

    # =========================================================================
    # TERMINAL: HARD_FAIL은 시스템 종료점
    # =========================================================================

    def test_hard_fail_is_terminal(self):
        """HARD_FAIL 이후에는 action=abort만 반환"""
        sig = self.escalator.compute_signature(
            "FORMAT_ERROR", ["verdict"], "reviewer", "review task"
        )

        # HARD_FAIL까지 진행
        self.escalator.record_failure(sig)  # SELF_REPAIR
        self.escalator.record_failure(sig)  # ROLE_SWITCH
        level3 = self.escalator.record_failure(sig)  # HARD_FAIL

        assert level3 == EscalationLevel.HARD_FAIL

        # HARD_FAIL의 action은 abort
        action = self.escalator.get_escalation_action(
            level3, "reviewer", "original", "error"
        )
        assert action["action"] == "abort"
        assert "error_type" in action

    def test_hard_fail_no_recovery(self):
        """HARD_FAIL은 추가 실패해도 계속 HARD_FAIL"""
        sig = self.escalator.compute_signature(
            "TIMEOUT", [], "coder", "timeout task"
        )

        # HARD_FAIL까지 진행
        for _ in range(3):
            self.escalator.record_failure(sig)

        # 추가 실패해도 HARD_FAIL 유지
        for _ in range(10):
            level = self.escalator.record_failure(sig)
            assert level == EscalationLevel.HARD_FAIL, \
                "HARD_FAIL 이후에도 HARD_FAIL 유지해야 함"

    # =========================================================================
    # ONCE: ROLE_SWITCH는 1회만 허용
    # =========================================================================

    def test_role_switch_only_once(self):
        """역할 전환은 프로필당 1회만 허용"""
        escalator = RetryEscalator(max_same_signature=2)

        # 첫 번째 ROLE_SWITCH
        action1 = escalator.get_escalation_action(
            EscalationLevel.ROLE_SWITCH, "coder", "task1", "error1"
        )
        assert action1["action"] == "switch"
        assert action1["new_profile"] == "reviewer"

        # 두 번째 ROLE_SWITCH 시도 (같은 프로필)
        action2 = escalator.get_escalation_action(
            EscalationLevel.ROLE_SWITCH, "coder", "task2", "error2"
        )
        assert action2["action"] == "abort", "2번째 역할 전환은 abort"
        assert "ROLE_SWITCH_EXHAUSTED" in action2.get("error_type", "")

    def test_role_switch_per_profile(self):
        """역할 전환은 프로필별로 독립"""
        escalator = RetryEscalator(max_same_signature=2)

        # coder 역할 전환
        action_coder = escalator.get_escalation_action(
            EscalationLevel.ROLE_SWITCH, "coder", "coder task", "error"
        )
        assert action_coder["action"] == "switch"

        # qa 역할 전환 (다른 프로필이므로 허용)
        action_qa = escalator.get_escalation_action(
            EscalationLevel.ROLE_SWITCH, "qa", "qa task", "error"
        )
        assert action_qa["action"] == "switch", "다른 프로필은 별도 카운트"

        # coder 다시 시도 (이미 사용됨)
        action_coder2 = escalator.get_escalation_action(
            EscalationLevel.ROLE_SWITCH, "coder", "coder task2", "error"
        )
        assert action_coder2["action"] == "abort"

    def test_role_switch_clear_resets(self):
        """clear_history가 역할 전환 상태도 초기화"""
        escalator = RetryEscalator(max_same_signature=2)

        # 역할 전환 사용
        escalator.get_escalation_action(
            EscalationLevel.ROLE_SWITCH, "coder", "task", "error"
        )

        # 초기화
        escalator.clear_history("coder")

        # 다시 사용 가능해야 함
        action = escalator.get_escalation_action(
            EscalationLevel.ROLE_SWITCH, "coder", "task", "error"
        )
        assert action["action"] == "switch"


# =============================================================================
# 시그니처 테스트
# =============================================================================

class TestFailureSignature:
    """실패 시그니처 테스트"""

    def setup_method(self):
        self.escalator = RetryEscalator()

    def test_same_error_same_signature(self):
        """동일한 에러는 동일한 시그니처"""
        sig1 = self.escalator.compute_signature(
            "JSON_PARSE_ERROR", ["field1"], "coder", "same prompt"
        )
        sig2 = self.escalator.compute_signature(
            "JSON_PARSE_ERROR", ["field1"], "coder", "same prompt"
        )
        assert sig1 == sig2

    def test_different_error_different_signature(self):
        """다른 에러 타입은 다른 시그니처"""
        sig1 = self.escalator.compute_signature(
            "JSON_PARSE_ERROR", [], "coder", "prompt"
        )
        sig2 = self.escalator.compute_signature(
            "SEMANTIC_NULL", [], "coder", "prompt"
        )
        assert sig1 != sig2

    def test_different_profile_different_signature(self):
        """다른 프로필은 다른 시그니처"""
        sig1 = self.escalator.compute_signature(
            "ERROR", [], "coder", "prompt"
        )
        sig2 = self.escalator.compute_signature(
            "ERROR", [], "qa", "prompt"
        )
        assert sig1 != sig2

    def test_different_prompt_different_signature(self):
        """다른 프롬프트는 다른 시그니처"""
        sig1 = self.escalator.compute_signature(
            "ERROR", [], "coder", "prompt A"
        )
        sig2 = self.escalator.compute_signature(
            "ERROR", [], "coder", "prompt B"
        )
        assert sig1 != sig2


# =============================================================================
# 액션 테스트
# =============================================================================

class TestEscalationActions:
    """에스컬레이션 액션 테스트"""

    def setup_method(self):
        self.escalator = RetryEscalator()

    def test_self_repair_returns_retry(self):
        """SELF_REPAIR는 retry 액션 반환"""
        action = self.escalator.get_escalation_action(
            EscalationLevel.SELF_REPAIR, "coder", "task", "error msg"
        )
        assert action["action"] == "retry"
        assert "modified_prompt" in action
        assert "ERROR_FEEDBACK" in action["modified_prompt"]

    def test_role_switch_returns_switch(self):
        """ROLE_SWITCH는 switch 액션 반환"""
        action = self.escalator.get_escalation_action(
            EscalationLevel.ROLE_SWITCH, "coder", "task", "error"
        )
        assert action["action"] == "switch"
        assert action["new_profile"] == "reviewer"

    def test_hard_fail_returns_abort(self):
        """HARD_FAIL은 abort 액션 반환"""
        action = self.escalator.get_escalation_action(
            EscalationLevel.HARD_FAIL, "coder", "task", "error"
        )
        assert action["action"] == "abort"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
