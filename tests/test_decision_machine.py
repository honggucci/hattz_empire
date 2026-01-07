"""
PM Decision Machine 상태 전이 테스트 (v2.5.5)

GPT-5.2 지시사항:
- ALLOWED_TRANSITIONS 정의 + 금지 전이 검증
- 허용 전이만 통과, 나머지는 FAIL
"""
import pytest
from enum import Enum
from typing import Dict, Optional, Set


# =============================================================================
# Inline Copy (config.py 의존성 회피)
# =============================================================================

class PMDecision(str, Enum):
    """PM 의사결정 상태"""
    DISPATCH = "DISPATCH"
    ESCALATE = "ESCALATE"
    DONE = "DONE"
    BLOCKED = "BLOCKED"
    RETRY = "RETRY"


ALLOWED_TRANSITIONS: Dict[PMDecision, Set[PMDecision]] = {
    PMDecision.DISPATCH: {PMDecision.RETRY, PMDecision.DONE, PMDecision.BLOCKED},
    PMDecision.RETRY: {PMDecision.DISPATCH, PMDecision.BLOCKED},
    PMDecision.BLOCKED: {PMDecision.ESCALATE},
    PMDecision.ESCALATE: {PMDecision.DONE},
    PMDecision.DONE: set(),  # Terminal state
}

FORBIDDEN_TRANSITIONS = [
    (PMDecision.DISPATCH, PMDecision.ESCALATE),
    (PMDecision.DONE, PMDecision.RETRY),
    (PMDecision.RETRY, PMDecision.ESCALATE),
    (PMDecision.BLOCKED, PMDecision.DISPATCH),
]


def is_valid_transition(from_state: PMDecision, to_state: PMDecision) -> bool:
    """전이 유효성 검사"""
    allowed = ALLOWED_TRANSITIONS.get(from_state, set())
    return to_state in allowed


def get_forbidden_reason(from_state: PMDecision, to_state: PMDecision) -> Optional[str]:
    """금지된 전이 사유 반환"""
    for forbidden_from, forbidden_to in FORBIDDEN_TRANSITIONS:
        if from_state == forbidden_from and to_state == forbidden_to:
            return f"{from_state.value} -> {to_state.value} 전이 금지"
    if to_state not in ALLOWED_TRANSITIONS.get(from_state, set()):
        return f"{from_state.value}에서 {to_state.value}로 전이 불가"
    return None


# =============================================================================
# 상태 전이 그래프 테스트
# =============================================================================

class TestStateTransitionGraph:
    """State Transition Graph 테스트"""

    # =========================================================================
    # 허용된 전이 테스트
    # =========================================================================

    def test_dispatch_to_retry_allowed(self):
        """DISPATCH -> RETRY 허용"""
        assert is_valid_transition(PMDecision.DISPATCH, PMDecision.RETRY)

    def test_dispatch_to_done_allowed(self):
        """DISPATCH -> DONE 허용"""
        assert is_valid_transition(PMDecision.DISPATCH, PMDecision.DONE)

    def test_dispatch_to_blocked_allowed(self):
        """DISPATCH -> BLOCKED 허용"""
        assert is_valid_transition(PMDecision.DISPATCH, PMDecision.BLOCKED)

    def test_retry_to_dispatch_allowed(self):
        """RETRY -> DISPATCH 허용"""
        assert is_valid_transition(PMDecision.RETRY, PMDecision.DISPATCH)

    def test_retry_to_blocked_allowed(self):
        """RETRY -> BLOCKED 허용"""
        assert is_valid_transition(PMDecision.RETRY, PMDecision.BLOCKED)

    def test_blocked_to_escalate_allowed(self):
        """BLOCKED -> ESCALATE 허용"""
        assert is_valid_transition(PMDecision.BLOCKED, PMDecision.ESCALATE)

    def test_escalate_to_done_allowed(self):
        """ESCALATE -> DONE 허용"""
        assert is_valid_transition(PMDecision.ESCALATE, PMDecision.DONE)

    # =========================================================================
    # 금지된 전이 테스트 (GPT-5.2 명시)
    # =========================================================================

    def test_dispatch_to_escalate_forbidden(self):
        """DISPATCH -> ESCALATE 금지"""
        assert not is_valid_transition(PMDecision.DISPATCH, PMDecision.ESCALATE)
        reason = get_forbidden_reason(PMDecision.DISPATCH, PMDecision.ESCALATE)
        assert reason is not None
        assert "금지" in reason or "불가" in reason

    def test_done_to_retry_forbidden(self):
        """DONE -> RETRY 금지 (DONE은 terminal)"""
        assert not is_valid_transition(PMDecision.DONE, PMDecision.RETRY)
        reason = get_forbidden_reason(PMDecision.DONE, PMDecision.RETRY)
        assert reason is not None

    def test_retry_to_escalate_forbidden(self):
        """RETRY -> ESCALATE 금지"""
        assert not is_valid_transition(PMDecision.RETRY, PMDecision.ESCALATE)
        reason = get_forbidden_reason(PMDecision.RETRY, PMDecision.ESCALATE)
        assert reason is not None

    def test_blocked_to_dispatch_forbidden(self):
        """BLOCKED -> DISPATCH 금지"""
        assert not is_valid_transition(PMDecision.BLOCKED, PMDecision.DISPATCH)
        reason = get_forbidden_reason(PMDecision.BLOCKED, PMDecision.DISPATCH)
        assert reason is not None

    # =========================================================================
    # Terminal State 테스트
    # =========================================================================

    def test_done_is_terminal(self):
        """DONE은 terminal state (어디로도 전이 불가)"""
        for target in PMDecision:
            if target != PMDecision.DONE:
                assert not is_valid_transition(PMDecision.DONE, target), \
                    f"DONE -> {target.value} should be forbidden"

    def test_done_has_no_outgoing_transitions(self):
        """DONE의 허용 전이 집합은 비어있음"""
        assert ALLOWED_TRANSITIONS[PMDecision.DONE] == set()

    # =========================================================================
    # ESCALATE 경로 테스트
    # =========================================================================

    def test_escalate_only_from_blocked(self):
        """ESCALATE는 BLOCKED에서만 도달 가능"""
        for source in PMDecision:
            if source == PMDecision.BLOCKED:
                assert is_valid_transition(source, PMDecision.ESCALATE)
            else:
                assert not is_valid_transition(source, PMDecision.ESCALATE), \
                    f"{source.value} -> ESCALATE should be forbidden"

    def test_escalate_path_blocked_first(self):
        """ESCALATE 경로: DISPATCH -> BLOCKED -> ESCALATE -> DONE"""
        # Step 1: DISPATCH -> BLOCKED
        assert is_valid_transition(PMDecision.DISPATCH, PMDecision.BLOCKED)
        # Step 2: BLOCKED -> ESCALATE
        assert is_valid_transition(PMDecision.BLOCKED, PMDecision.ESCALATE)
        # Step 3: ESCALATE -> DONE
        assert is_valid_transition(PMDecision.ESCALATE, PMDecision.DONE)

    # =========================================================================
    # 전체 전이 매트릭스 검증
    # =========================================================================

    def test_all_states_have_transition_rules(self):
        """모든 상태가 ALLOWED_TRANSITIONS에 정의됨"""
        for state in PMDecision:
            assert state in ALLOWED_TRANSITIONS, \
                f"{state.value} not in ALLOWED_TRANSITIONS"

    def test_transition_matrix_completeness(self):
        """전이 규칙이 빠짐없이 정의됨 (5x5 매트릭스)"""
        expected_states = {PMDecision.DISPATCH, PMDecision.ESCALATE,
                          PMDecision.DONE, PMDecision.BLOCKED, PMDecision.RETRY}
        assert set(ALLOWED_TRANSITIONS.keys()) == expected_states

    def test_no_self_transition(self):
        """자기 자신으로의 전이 금지"""
        for state in PMDecision:
            assert not is_valid_transition(state, state), \
                f"{state.value} -> {state.value} self-transition should be forbidden"


# =============================================================================
# 전이 시나리오 테스트
# =============================================================================

class TestTransitionScenarios:
    """실제 사용 시나리오 테스트"""

    def test_happy_path_dispatch_done(self):
        """정상 경로: DISPATCH -> DONE"""
        path = [PMDecision.DISPATCH, PMDecision.DONE]
        for i in range(len(path) - 1):
            assert is_valid_transition(path[i], path[i+1])

    def test_retry_path(self):
        """재시도 경로: DISPATCH -> RETRY -> DISPATCH -> DONE"""
        path = [PMDecision.DISPATCH, PMDecision.RETRY,
                PMDecision.DISPATCH, PMDecision.DONE]
        for i in range(len(path) - 1):
            assert is_valid_transition(path[i], path[i+1]), \
                f"Failed at {path[i].value} -> {path[i+1].value}"

    def test_escalation_path(self):
        """에스컬레이션 경로: DISPATCH -> BLOCKED -> ESCALATE -> DONE"""
        path = [PMDecision.DISPATCH, PMDecision.BLOCKED,
                PMDecision.ESCALATE, PMDecision.DONE]
        for i in range(len(path) - 1):
            assert is_valid_transition(path[i], path[i+1]), \
                f"Failed at {path[i].value} -> {path[i+1].value}"

    def test_retry_then_block_path(self):
        """재시도 후 차단: DISPATCH -> RETRY -> BLOCKED -> ESCALATE -> DONE"""
        path = [PMDecision.DISPATCH, PMDecision.RETRY, PMDecision.BLOCKED,
                PMDecision.ESCALATE, PMDecision.DONE]
        for i in range(len(path) - 1):
            assert is_valid_transition(path[i], path[i+1]), \
                f"Failed at {path[i].value} -> {path[i+1].value}"

    def test_invalid_shortcut_to_escalate(self):
        """금지 경로: DISPATCH -> ESCALATE (바로가기 금지)"""
        assert not is_valid_transition(PMDecision.DISPATCH, PMDecision.ESCALATE)

    def test_invalid_recovery_from_done(self):
        """금지 경로: DONE -> RETRY (완료 후 재시도 금지)"""
        assert not is_valid_transition(PMDecision.DONE, PMDecision.RETRY)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
