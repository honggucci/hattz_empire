"""
decision_machine.py 전체 커버리지 테스트
목표: 95%+ 커버리지
"""
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

import pytest
from src.core.decision_machine import (
    # Enums
    PMDecision, DispatchTarget, EscalationReason,
    # Classes
    DecisionOutput, PMDecisionMachine,
    # Functions
    is_valid_transition, get_forbidden_reason,
    get_decision_machine, process_pm_output, infer_agent, check_escalation,
    # Constants
    ALLOWED_TRANSITIONS, FORBIDDEN_TRANSITIONS
)


# =============================================================================
# PMDecision Enum Tests
# =============================================================================

class TestPMDecisionEnum:
    """PMDecision enum 테스트"""

    def test_all_values(self):
        """모든 PMDecision 값 확인"""
        assert PMDecision.DISPATCH.value == "DISPATCH"
        assert PMDecision.ESCALATE.value == "ESCALATE"
        assert PMDecision.DONE.value == "DONE"
        assert PMDecision.BLOCKED.value == "BLOCKED"
        assert PMDecision.RETRY.value == "RETRY"

    def test_enum_count(self):
        """PMDecision 개수 확인"""
        assert len(PMDecision) == 5


class TestDispatchTargetEnum:
    """DispatchTarget enum 테스트"""

    def test_all_values(self):
        """모든 DispatchTarget 값 확인"""
        assert DispatchTarget.CODER.value == "coder"
        assert DispatchTarget.QA.value == "qa"
        assert DispatchTarget.REVIEWER.value == "reviewer"
        assert DispatchTarget.STRATEGIST.value == "strategist"
        assert DispatchTarget.ANALYST.value == "analyst"
        assert DispatchTarget.RESEARCHER.value == "researcher"
        assert DispatchTarget.EXCAVATOR.value == "excavator"

    def test_enum_count(self):
        """DispatchTarget 개수 확인"""
        assert len(DispatchTarget) == 7


class TestEscalationReasonEnum:
    """EscalationReason enum 테스트"""

    def test_all_values(self):
        """모든 EscalationReason 값 확인"""
        assert EscalationReason.DEPLOY.value == "deploy"
        assert EscalationReason.API_KEY.value == "api_key"
        assert EscalationReason.PAYMENT.value == "payment"
        assert EscalationReason.DATA_DELETE.value == "data_delete"
        assert EscalationReason.DEPENDENCY.value == "dependency"
        assert EscalationReason.SECURITY.value == "security"
        assert EscalationReason.UNCLEAR.value == "unclear"
        assert EscalationReason.RISK.value == "risk"


# =============================================================================
# State Transition Tests
# =============================================================================

class TestStateTransitions:
    """상태 전이 테스트"""

    def test_allowed_transitions_structure(self):
        """ALLOWED_TRANSITIONS 구조 확인"""
        assert PMDecision.DISPATCH in ALLOWED_TRANSITIONS
        assert PMDecision.RETRY in ALLOWED_TRANSITIONS
        assert PMDecision.BLOCKED in ALLOWED_TRANSITIONS
        assert PMDecision.ESCALATE in ALLOWED_TRANSITIONS
        assert PMDecision.DONE in ALLOWED_TRANSITIONS

    def test_done_is_terminal(self):
        """DONE은 terminal state"""
        assert ALLOWED_TRANSITIONS[PMDecision.DONE] == set()

    def test_valid_transitions(self):
        """유효한 전이 테스트"""
        # DISPATCH -> RETRY, DONE, BLOCKED
        assert is_valid_transition(PMDecision.DISPATCH, PMDecision.RETRY) is True
        assert is_valid_transition(PMDecision.DISPATCH, PMDecision.DONE) is True
        assert is_valid_transition(PMDecision.DISPATCH, PMDecision.BLOCKED) is True

        # RETRY -> DISPATCH, BLOCKED
        assert is_valid_transition(PMDecision.RETRY, PMDecision.DISPATCH) is True
        assert is_valid_transition(PMDecision.RETRY, PMDecision.BLOCKED) is True

        # BLOCKED -> ESCALATE
        assert is_valid_transition(PMDecision.BLOCKED, PMDecision.ESCALATE) is True

        # ESCALATE -> DONE
        assert is_valid_transition(PMDecision.ESCALATE, PMDecision.DONE) is True

    def test_invalid_transitions(self):
        """무효한 전이 테스트"""
        # 금지된 전이
        assert is_valid_transition(PMDecision.DISPATCH, PMDecision.ESCALATE) is False
        assert is_valid_transition(PMDecision.DONE, PMDecision.RETRY) is False
        assert is_valid_transition(PMDecision.RETRY, PMDecision.ESCALATE) is False
        assert is_valid_transition(PMDecision.BLOCKED, PMDecision.DISPATCH) is False

        # DONE에서 아무 곳으로도 전이 불가
        assert is_valid_transition(PMDecision.DONE, PMDecision.DISPATCH) is False

    def test_get_forbidden_reason_direct_forbidden(self):
        """금지된 전이 사유 - 직접 금지"""
        reason = get_forbidden_reason(PMDecision.DISPATCH, PMDecision.ESCALATE)
        assert reason is not None
        assert "금지" in reason

    def test_get_forbidden_reason_not_allowed(self):
        """금지된 전이 사유 - 허용 목록에 없음"""
        reason = get_forbidden_reason(PMDecision.DONE, PMDecision.DISPATCH)
        assert reason is not None
        assert "전이 불가" in reason

    def test_get_forbidden_reason_valid(self):
        """유효한 전이는 None 반환"""
        reason = get_forbidden_reason(PMDecision.DISPATCH, PMDecision.DONE)
        assert reason is None


# =============================================================================
# DecisionOutput Tests
# =============================================================================

class TestDecisionOutput:
    """DecisionOutput dataclass 테스트"""

    def test_basic_creation(self):
        """기본 DecisionOutput 생성"""
        output = DecisionOutput(
            decision=PMDecision.DONE,
            targets=[]
        )
        assert output.decision == PMDecision.DONE
        assert output.targets == []
        assert output.escalation_reason is None
        assert output.summary == ""
        assert output.confidence == 1.0

    def test_full_creation(self):
        """모든 필드 포함 DecisionOutput 생성"""
        output = DecisionOutput(
            decision=PMDecision.ESCALATE,
            targets=[DispatchTarget.CODER],
            escalation_reason=EscalationReason.DEPLOY,
            summary="배포 승인 필요",
            confidence=0.8
        )
        assert output.decision == PMDecision.ESCALATE
        assert output.escalation_reason == EscalationReason.DEPLOY
        assert output.confidence == 0.8

    def test_to_dict(self):
        """to_dict() 메서드 테스트"""
        output = DecisionOutput(
            decision=PMDecision.DISPATCH,
            targets=[DispatchTarget.CODER, DispatchTarget.QA],
            summary="coder와 qa에게 작업 할당"
        )
        result = output.to_dict()

        assert result["decision"] == "DISPATCH"
        assert result["targets"] == ["coder", "qa"]
        assert result["escalation_reason"] is None
        assert result["summary"] == "coder와 qa에게 작업 할당"
        assert result["confidence"] == 1.0

    def test_to_dict_with_escalation(self):
        """to_dict() - escalation_reason 포함"""
        output = DecisionOutput(
            decision=PMDecision.ESCALATE,
            targets=[],
            escalation_reason=EscalationReason.SECURITY
        )
        result = output.to_dict()
        assert result["escalation_reason"] == "security"

    def test_to_dict_summary_truncation(self):
        """to_dict() - summary 100자 잘라내기"""
        long_summary = "x" * 200
        output = DecisionOutput(
            decision=PMDecision.DONE,
            targets=[],
            summary=long_summary
        )
        result = output.to_dict()
        assert len(result["summary"]) == 100


# =============================================================================
# PMDecisionMachine Tests
# =============================================================================

class TestPMDecisionMachine:
    """PMDecisionMachine 테스트"""

    @pytest.fixture
    def machine(self):
        """테스트용 machine 인스턴스"""
        return PMDecisionMachine()

    # -------------------------------------------------------------------------
    # process() 테스트
    # -------------------------------------------------------------------------

    def test_process_dispatch_valid(self, machine):
        """DISPATCH - 정상 케이스"""
        pm_output = {
            "action": "DISPATCH",
            "tasks": [
                {"task_id": "T001", "agent": "coder", "instruction": "버그 수정"}
            ],
            "summary": "coder에게 버그 수정 할당",
            "requires_ceo": False
        }
        result = machine.process(pm_output)

        assert result.decision == PMDecision.DISPATCH
        assert DispatchTarget.CODER in result.targets
        assert result.confidence == 1.0

    def test_process_dispatch_multiple_agents(self, machine):
        """DISPATCH - 여러 에이전트"""
        pm_output = {
            "action": "DISPATCH",
            "tasks": [
                {"task_id": "T001", "agent": "coder", "instruction": "구현"},
                {"task_id": "T002", "agent": "qa", "instruction": "테스트"},
                {"task_id": "T003", "agent": "reviewer", "instruction": "리뷰"}
            ],
            "summary": "구현, 테스트, 리뷰 순으로 진행"
        }
        result = machine.process(pm_output)

        assert result.decision == PMDecision.DISPATCH
        assert len(result.targets) == 3
        assert DispatchTarget.CODER in result.targets
        assert DispatchTarget.QA in result.targets
        assert DispatchTarget.REVIEWER in result.targets

    def test_process_dispatch_no_tasks(self, machine):
        """DISPATCH - tasks 없음 → BLOCKED"""
        pm_output = {
            "action": "DISPATCH",
            "tasks": [],
            "summary": "할당할 작업 없음"
        }
        result = machine.process(pm_output)

        assert result.decision == PMDecision.BLOCKED
        assert result.confidence == 0.0

    def test_process_dispatch_invalid_agent(self, machine):
        """DISPATCH - 잘못된 에이전트 → BLOCKED"""
        pm_output = {
            "action": "DISPATCH",
            "tasks": [
                {"task_id": "T001", "agent": "unknown_agent", "instruction": "무언가"}
            ],
            "summary": "알 수 없는 에이전트"
        }
        result = machine.process(pm_output)

        assert result.decision == PMDecision.BLOCKED
        assert len(result.targets) == 0

    def test_process_dispatch_duplicate_agents(self, machine):
        """DISPATCH - 중복 에이전트 제거"""
        pm_output = {
            "action": "DISPATCH",
            "tasks": [
                {"task_id": "T001", "agent": "coder", "instruction": "작업1"},
                {"task_id": "T002", "agent": "coder", "instruction": "작업2"}
            ],
            "summary": "같은 에이전트에게 두 작업"
        }
        result = machine.process(pm_output)

        assert result.decision == PMDecision.DISPATCH
        assert len(result.targets) == 1  # 중복 제거

    def test_process_escalate_explicit(self, machine):
        """ESCALATE - action으로 명시"""
        pm_output = {
            "action": "ESCALATE",
            "tasks": [],
            "summary": "배포 승인 필요"
        }
        result = machine.process(pm_output)

        assert result.decision == PMDecision.ESCALATE
        assert result.escalation_reason == EscalationReason.DEPLOY

    def test_process_escalate_requires_ceo(self, machine):
        """ESCALATE - requires_ceo=True"""
        pm_output = {
            "action": "DISPATCH",
            "tasks": [],
            "summary": "API 키 변경 필요",
            "requires_ceo": True
        }
        result = machine.process(pm_output)

        assert result.decision == PMDecision.ESCALATE

    def test_process_done(self, machine):
        """DONE - 정상 케이스"""
        pm_output = {
            "action": "DONE",
            "tasks": [],
            "summary": "작업 완료되었습니다"
        }
        result = machine.process(pm_output)

        assert result.decision == PMDecision.DONE
        assert len(result.targets) == 0

    def test_process_unknown_action(self, machine):
        """알 수 없는 action → BLOCKED"""
        pm_output = {
            "action": "UNKNOWN",
            "tasks": [],
            "summary": "알 수 없는 액션"
        }
        result = machine.process(pm_output)

        assert result.decision == PMDecision.BLOCKED
        assert result.confidence == 0.0
        assert "Unknown action" in result.summary

    def test_process_null_summary_reduces_confidence(self, machine):
        """의미 없는 summary → confidence 감소"""
        pm_output = {
            "action": "DISPATCH",
            "tasks": [{"task_id": "T001", "agent": "coder", "instruction": "작업"}],
            "summary": "확인했습니다. 진행하겠습니다."
        }
        result = machine.process(pm_output)

        assert result.confidence == 0.5  # 의미 없는 summary

    def test_process_short_summary_reduces_confidence(self, machine):
        """짧은 summary → confidence 감소"""
        pm_output = {
            "action": "DONE",
            "tasks": [],
            "summary": "OK"  # 5자 미만
        }
        result = machine.process(pm_output)

        assert result.confidence == 0.5

    def test_process_empty_summary(self, machine):
        """빈 summary"""
        pm_output = {
            "action": "DONE",
            "tasks": [],
            "summary": ""
        }
        result = machine.process(pm_output)

        assert result.confidence == 0.5

    def test_process_lowercase_action(self, machine):
        """소문자 action 처리"""
        pm_output = {
            "action": "done",
            "tasks": [],
            "summary": "작업 완료"
        }
        result = machine.process(pm_output)

        assert result.decision == PMDecision.DONE

    # -------------------------------------------------------------------------
    # _validate_summary() 테스트
    # -------------------------------------------------------------------------

    def test_validate_summary_valid(self, machine):
        """유효한 summary"""
        valid, warning = machine._validate_summary("coder에게 로그인 버그 수정 할당")
        assert valid is True
        assert warning == ""

    def test_validate_summary_null_patterns(self, machine):
        """의미 없는 패턴 감지"""
        patterns = [
            "검토했습니다",
            "확인했습니다",
            "진행하겠습니다",
            "처리하겠습니다",
            "looks good",
            "will proceed",
            "I will do this",
        ]
        for pattern in patterns:
            valid, warning = machine._validate_summary(pattern)
            assert valid is False, f"'{pattern}' should be invalid"
            assert "의미 없는" in warning

    def test_validate_summary_too_short(self, machine):
        """너무 짧은 summary"""
        valid, warning = machine._validate_summary("OK")
        assert valid is False
        assert "짧음" in warning

    def test_validate_summary_empty(self, machine):
        """빈 summary"""
        valid, warning = machine._validate_summary("")
        assert valid is False

    def test_validate_summary_whitespace_only(self, machine):
        """공백만 있는 summary"""
        valid, warning = machine._validate_summary("    ")
        assert valid is False

    # -------------------------------------------------------------------------
    # _infer_escalation_reason() 테스트
    # -------------------------------------------------------------------------

    def test_infer_escalation_deploy(self, machine):
        """DEPLOY 사유 추론"""
        reason = machine._infer_escalation_reason("프로덕션 배포 필요", [])
        assert reason == EscalationReason.DEPLOY

        reason = machine._infer_escalation_reason("production release", [])
        assert reason == EscalationReason.DEPLOY

    def test_infer_escalation_api_key(self, machine):
        """API_KEY 사유 추론"""
        reason = machine._infer_escalation_reason("api_key 변경 필요", [])
        assert reason == EscalationReason.API_KEY

        reason = machine._infer_escalation_reason("토큰 발급", [])
        assert reason == EscalationReason.API_KEY

    def test_infer_escalation_payment(self, machine):
        """PAYMENT 사유 추론"""
        reason = machine._infer_escalation_reason("결제 처리 필요", [])
        assert reason == EscalationReason.PAYMENT

    def test_infer_escalation_data_delete(self, machine):
        """DATA_DELETE 사유 추론"""
        reason = machine._infer_escalation_reason("데이터 삭제 필요", [])
        assert reason == EscalationReason.DATA_DELETE

        reason = machine._infer_escalation_reason("DROP TABLE users", [])
        assert reason == EscalationReason.DATA_DELETE

    def test_infer_escalation_dependency(self, machine):
        """DEPENDENCY 사유 추론"""
        reason = machine._infer_escalation_reason("pip install requests 필요", [])
        assert reason == EscalationReason.DEPENDENCY

        reason = machine._infer_escalation_reason("npm install 실행", [])
        assert reason == EscalationReason.DEPENDENCY

    def test_infer_escalation_security(self, machine):
        """SECURITY 사유 추론"""
        reason = machine._infer_escalation_reason("보안 설정 변경", [])
        assert reason == EscalationReason.SECURITY

        reason = machine._infer_escalation_reason("권한 수정 필요", [])
        assert reason == EscalationReason.SECURITY

    def test_infer_escalation_from_tasks(self, machine):
        """tasks에서 사유 추론"""
        tasks = [
            {"instruction": "프로덕션 배포", "context": "운영 환경"}
        ]
        reason = machine._infer_escalation_reason("작업 진행", tasks)
        assert reason == EscalationReason.DEPLOY

    def test_infer_escalation_unclear(self, machine):
        """기본값 UNCLEAR"""
        reason = machine._infer_escalation_reason("일반적인 요청", [])
        assert reason == EscalationReason.UNCLEAR

    # -------------------------------------------------------------------------
    # infer_agent_from_prompt() 테스트
    # -------------------------------------------------------------------------

    def test_infer_agent_coder(self, machine):
        """CODER 추론"""
        agent = machine.infer_agent_from_prompt("버그 수정해줘")
        assert agent == DispatchTarget.CODER

        agent = machine.infer_agent_from_prompt("코드 구현해줘")
        assert agent == DispatchTarget.CODER

    def test_infer_agent_qa(self, machine):
        """QA 추론"""
        agent = machine.infer_agent_from_prompt("테스트 작성해줘")
        assert agent == DispatchTarget.QA

        agent = machine.infer_agent_from_prompt("이거 검증해줘")
        assert agent == DispatchTarget.QA

    def test_infer_agent_reviewer(self, machine):
        """REVIEWER 추론"""
        # "리뷰"만으로 명확하게 테스트
        agent = machine.infer_agent_from_prompt("보안 검토해줘")
        assert agent == DispatchTarget.REVIEWER

    def test_infer_agent_strategist(self, machine):
        """STRATEGIST 추론"""
        agent = machine.infer_agent_from_prompt("아키텍처 설계해줘")
        assert agent == DispatchTarget.STRATEGIST

        agent = machine.infer_agent_from_prompt("원인 분석해줘")
        assert agent == DispatchTarget.STRATEGIST

    def test_infer_agent_analyst(self, machine):
        """ANALYST 추론"""
        agent = machine.infer_agent_from_prompt("로그 요약해줘")
        assert agent == DispatchTarget.ANALYST

    def test_infer_agent_researcher(self, machine):
        """RESEARCHER 추론"""
        agent = machine.infer_agent_from_prompt("최신 문서 검색해줘")
        assert agent == DispatchTarget.RESEARCHER

    def test_infer_agent_excavator(self, machine):
        """EXCAVATOR 추론"""
        agent = machine.infer_agent_from_prompt("요구사항 정리해줘")
        assert agent == DispatchTarget.EXCAVATOR

    def test_infer_agent_none(self, machine):
        """추론 불가 → None"""
        agent = machine.infer_agent_from_prompt("안녕하세요")
        assert agent is None

    def test_infer_agent_highest_score(self, machine):
        """가장 높은 점수 에이전트 반환"""
        # "코드 버그 수정 구현" - coder 키워드 3개
        agent = machine.infer_agent_from_prompt("코드 버그 수정 구현")
        assert agent == DispatchTarget.CODER

    # -------------------------------------------------------------------------
    # should_escalate() 테스트
    # -------------------------------------------------------------------------

    def test_should_escalate_deploy(self, machine):
        """배포 에스컬레이션 감지"""
        needs, reason = machine.should_escalate("프로덕션 배포해줘")
        assert needs is True
        assert reason == EscalationReason.DEPLOY

    def test_should_escalate_api_key(self, machine):
        """API 키 에스컬레이션 감지"""
        needs, reason = machine.should_escalate("api_key 설정해줘")
        assert needs is True
        assert reason == EscalationReason.API_KEY

    def test_should_escalate_false(self, machine):
        """에스컬레이션 필요 없음"""
        needs, reason = machine.should_escalate("코드 수정해줘")
        assert needs is False
        assert reason is None


# =============================================================================
# Singleton & Helper Function Tests
# =============================================================================

class TestSingletonAndHelpers:
    """싱글톤 및 헬퍼 함수 테스트"""

    def test_get_decision_machine_singleton(self):
        """get_decision_machine() 싱글톤 테스트"""
        m1 = get_decision_machine()
        m2 = get_decision_machine()
        assert m1 is m2

    def test_process_pm_output_helper(self):
        """process_pm_output() 헬퍼 함수"""
        pm_json = {
            "action": "DONE",
            "tasks": [],
            "summary": "완료"
        }
        result = process_pm_output(pm_json)
        assert result.decision == PMDecision.DONE

    def test_infer_agent_helper(self):
        """infer_agent() 헬퍼 함수"""
        agent = infer_agent("버그 수정해줘")
        assert agent == "coder"

        agent = infer_agent("안녕")
        assert agent is None

    def test_check_escalation_helper(self):
        """check_escalation() 헬퍼 함수"""
        needs, reason = check_escalation("프로덕션 배포")
        assert needs is True
        assert reason == "deploy"

        needs, reason = check_escalation("일반 작업")
        assert needs is False
        assert reason is None


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """엣지 케이스 테스트"""

    @pytest.fixture
    def machine(self):
        return PMDecisionMachine()

    def test_process_missing_action(self, machine):
        """action 필드 없음"""
        pm_output = {
            "tasks": [],
            "summary": "액션 없음"
        }
        result = machine.process(pm_output)
        assert result.decision == PMDecision.BLOCKED

    def test_process_missing_summary(self, machine):
        """summary 필드 없음"""
        pm_output = {
            "action": "DONE",
            "tasks": []
        }
        result = machine.process(pm_output)
        assert result.decision == PMDecision.DONE
        assert result.confidence == 0.5  # 빈 summary

    def test_process_missing_tasks(self, machine):
        """tasks 필드 없음"""
        pm_output = {
            "action": "DISPATCH",
            "summary": "tasks 없음"
        }
        result = machine.process(pm_output)
        assert result.decision == PMDecision.BLOCKED

    def test_process_task_missing_agent(self, machine):
        """task에 agent 필드 없음"""
        pm_output = {
            "action": "DISPATCH",
            "tasks": [{"task_id": "T001", "instruction": "무언가"}],
            "summary": "에이전트 없음"
        }
        result = machine.process(pm_output)
        assert result.decision == PMDecision.BLOCKED

    def test_infer_escalation_from_task_context(self, machine):
        """task context에서 에스컬레이션 사유 추론"""
        tasks = [
            {"instruction": "작업", "context": "api_key 필요"}
        ]
        reason = machine._infer_escalation_reason("일반 요청", tasks)
        assert reason == EscalationReason.API_KEY


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
