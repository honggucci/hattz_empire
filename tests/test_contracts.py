"""
contracts.py 단위 테스트
테스트 커버리지 향상을 위한 핵심 모듈 테스트
"""
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

import pytest
from src.core.contracts import (
    # Enums
    Verdict, TestResult,
    # Models
    CoderOutput, QAOutput, ReviewerOutput, StrategistOutput,
    PMOutput, CouncilMemberOutput, DocumentorOutput,
    TaskSpec, TestCase, Risk, Option,
    # Functions
    get_contract, get_schema_prompt, validate_output, extract_json_from_output,
    # Registry
    CONTRACT_REGISTRY, FormatGateError
)


class TestEnums:
    """Enum 테스트"""

    def test_verdict_values(self):
        """Verdict enum 값 확인"""
        assert Verdict.APPROVE.value == "APPROVE"
        assert Verdict.REVISE.value == "REVISE"
        assert Verdict.REJECT.value == "REJECT"

    def test_test_result_values(self):
        """TestResult enum 값 확인"""
        assert TestResult.PASS.value == "PASS"
        assert TestResult.FAIL.value == "FAIL"
        assert TestResult.SKIP.value == "SKIP"


class TestCoderOutput:
    """CoderOutput 모델 테스트"""

    def test_valid_coder_output(self):
        """정상적인 Coder 출력 검증"""
        output = CoderOutput(
            summary="로그인 버그 수정",
            files_changed=["src/api/auth.py"],
            diff="--- a/src/api/auth.py\n+++ b/src/api/auth.py"
        )
        assert output.summary == "로그인 버그 수정"
        assert len(output.files_changed) == 1
        assert output.todo_next is None

    def test_coder_output_with_todo(self):
        """todo_next 포함된 Coder 출력"""
        output = CoderOutput(
            summary="기능 추가",
            files_changed=["src/feature.py"],
            diff="--- a/file\n+++ b/file",
            todo_next="테스트 작성 필요"
        )
        assert output.todo_next == "테스트 작성 필요"

    def test_coder_output_summary_max_length(self):
        """summary 최대 길이 (500자) 검증"""
        long_summary = "x" * 501
        with pytest.raises(Exception):
            CoderOutput(
                summary=long_summary,
                files_changed=["file.py"],
                diff="diff"
            )


class TestQAOutput:
    """QAOutput 모델 테스트"""

    def test_valid_qa_output_pass(self):
        """PASS 판정 QA 출력"""
        output = QAOutput(
            verdict=TestResult.PASS,
            tests=[
                TestCase(name="test_login", result=TestResult.PASS),
                TestCase(name="test_logout", result=TestResult.PASS)
            ]
        )
        assert output.verdict == TestResult.PASS
        assert len(output.tests) == 2

    def test_valid_qa_output_fail(self):
        """FAIL 판정 QA 출력"""
        output = QAOutput(
            verdict=TestResult.FAIL,
            tests=[
                TestCase(name="test_error", result=TestResult.FAIL, reason="AssertionError")
            ],
            issues_found=["인증 토큰 만료 미처리"]
        )
        assert output.verdict == TestResult.FAIL
        assert output.tests[0].reason == "AssertionError"
        assert len(output.issues_found) == 1

    def test_qa_output_with_coverage(self):
        """커버리지 정보 포함된 QA 출력"""
        output = QAOutput(
            verdict=TestResult.PASS,
            tests=[],
            coverage_summary="85% (34/40 lines)"
        )
        assert output.coverage_summary == "85% (34/40 lines)"


class TestReviewerOutput:
    """ReviewerOutput 모델 테스트"""

    def test_valid_reviewer_approve(self):
        """APPROVE 판정 Reviewer 출력"""
        output = ReviewerOutput(
            verdict=Verdict.APPROVE,
            risks=[],
            security_score=9,
            approved_files=["src/api/auth.py"]
        )
        assert output.verdict == Verdict.APPROVE
        assert output.security_score == 9

    def test_reviewer_with_risks(self):
        """리스크 포함된 Reviewer 출력"""
        output = ReviewerOutput(
            verdict=Verdict.REVISE,
            risks=[
                Risk(
                    severity="HIGH",
                    file="src/api/auth.py",
                    line=42,
                    issue="SQL Injection 취약점",
                    fix_suggestion="Prepared statement 사용"
                )
            ],
            security_score=3,
            blocked_files=["src/api/auth.py"]
        )
        assert output.verdict == Verdict.REVISE
        assert len(output.risks) == 1
        assert output.risks[0].severity == "HIGH"

    def test_security_score_bounds(self):
        """보안 점수 범위 검증 (0-10)"""
        # 정상 범위
        output = ReviewerOutput(
            verdict=Verdict.APPROVE,
            risks=[],
            security_score=10
        )
        assert output.security_score == 10

        # 범위 초과
        with pytest.raises(Exception):
            ReviewerOutput(
                verdict=Verdict.APPROVE,
                risks=[],
                security_score=11
            )


class TestStrategistOutput:
    """StrategistOutput 모델 테스트"""

    def test_valid_strategist_output(self):
        """정상적인 Strategist 출력"""
        output = StrategistOutput(
            problem_summary="인증 시스템 리팩토링 필요",
            options=[
                Option(name="JWT 도입", pros=["확장성"], cons=["복잡도"], effort="MEDIUM", risk="LOW"),
                Option(name="세션 유지", pros=["단순"], cons=["확장 한계"], effort="LOW", risk="LOW")
            ],
            recommendation="JWT 도입",
            reasoning="확장성이 중요하므로 JWT를 추천합니다."
        )
        assert len(output.options) == 2
        assert output.recommendation == "JWT 도입"

    def test_strategist_min_options(self):
        """최소 2개 옵션 필요"""
        with pytest.raises(Exception):
            StrategistOutput(
                problem_summary="문제",
                options=[
                    Option(name="유일한 옵션", pros=[], cons=[], effort="LOW", risk="LOW")
                ],
                recommendation="유일한 옵션",
                reasoning="이유"
            )


class TestPMOutput:
    """PMOutput 모델 테스트"""

    def test_valid_pm_dispatch(self):
        """DISPATCH 액션 PM 출력"""
        output = PMOutput(
            action="DISPATCH",
            tasks=[
                TaskSpec(
                    task_id="T001",
                    agent="coder",
                    instruction="로그인 버그 수정",
                    priority="HIGH"
                )
            ],
            summary="coder에게 로그인 버그 수정 할당"
        )
        assert output.action == "DISPATCH"
        assert len(output.tasks) == 1
        assert output.requires_ceo is False

    def test_valid_pm_done(self):
        """DONE 액션 PM 출력"""
        output = PMOutput(
            action="DONE",
            tasks=[],
            summary="간단한 질문에 직접 답변 완료"
        )
        assert output.action == "DONE"
        assert len(output.tasks) == 0

    def test_pm_escalate_requires_ceo(self):
        """ESCALATE 시 CEO 승인 필요"""
        output = PMOutput(
            action="ESCALATE",
            tasks=[],
            summary="배포 작업은 CEO 승인 필요",
            requires_ceo=True
        )
        assert output.action == "ESCALATE"
        assert output.requires_ceo is True

    def test_pm_summary_truncation(self):
        """v2.6.5: summary 300자 초과 시 자동 잘라내기"""
        long_summary = "x" * 400
        output = PMOutput(
            action="DONE",
            tasks=[],
            summary=long_summary
        )
        assert len(output.summary) == 300  # 297 + "..."
        assert output.summary.endswith("...")

    def test_pm_blocked_action(self):
        """BLOCKED 액션 테스트"""
        output = PMOutput(
            action="BLOCKED",
            tasks=[],
            summary="정보 부족으로 진행 불가"
        )
        assert output.action == "BLOCKED"

    def test_pm_retry_action(self):
        """RETRY 액션 테스트"""
        output = PMOutput(
            action="RETRY",
            tasks=[],
            summary="이전 작업 재시도"
        )
        assert output.action == "RETRY"


class TestCouncilMemberOutput:
    """CouncilMemberOutput 모델 테스트"""

    def test_valid_council_output(self):
        """정상적인 Council 멤버 출력"""
        output = CouncilMemberOutput(
            score=8.5,
            reasoning="코드 품질이 좋고 테스트가 충분합니다.",
            concerns=["에러 핸들링 보완 필요"],
            approvals=["깔끔한 구조", "명확한 함수명"]
        )
        assert output.score == 8.5
        assert len(output.concerns) == 1
        assert len(output.approvals) == 2

    def test_council_score_bounds(self):
        """점수 범위 검증 (0-10)"""
        with pytest.raises(Exception):
            CouncilMemberOutput(
                score=11,
                reasoning="점수 초과"
            )


class TestDocumentorOutput:
    """DocumentorOutput 모델 테스트"""

    def test_valid_documentor_output(self):
        """정상적인 Documentor 출력"""
        output = DocumentorOutput(
            commit_type="feat",
            commit_message="Add user authentication",
            change_summary="사용자 인증 기능 추가",
            files_affected=["src/auth.py", "src/api/login.py"],
            breaking_change=False
        )
        assert output.commit_type == "feat"
        assert output.breaking_change is False

    def test_documentor_breaking_change(self):
        """Breaking change 플래그 테스트"""
        output = DocumentorOutput(
            commit_type="refactor",
            commit_message="Change API response format",
            change_summary="API 응답 형식 변경",
            files_affected=["src/api/response.py"],
            breaking_change=True
        )
        assert output.breaking_change is True


class TestContractRegistry:
    """CONTRACT_REGISTRY 테스트"""

    def test_registry_contains_all_agents(self):
        """레지스트리에 모든 에이전트 포함 확인"""
        expected_agents = ["coder", "qa", "reviewer", "strategist", "pm", "council", "documentor"]
        for agent in expected_agents:
            assert agent in CONTRACT_REGISTRY

    def test_get_contract_valid(self):
        """get_contract() 정상 동작"""
        assert get_contract("coder") == CoderOutput
        assert get_contract("pm") == PMOutput

    def test_get_contract_invalid(self):
        """get_contract() 없는 에이전트"""
        assert get_contract("unknown_agent") is None


class TestExtractJson:
    """extract_json_from_output() 테스트"""

    def test_extract_from_json_block(self):
        """```json 블록에서 추출"""
        raw = '''
        일부 텍스트
        ```json
        {"key": "value"}
        ```
        더 많은 텍스트
        '''
        result = extract_json_from_output(raw)
        assert result == '{"key": "value"}'

    def test_extract_raw_json(self):
        """순수 JSON 추출"""
        raw = '{"action": "DONE", "summary": "완료"}'
        result = extract_json_from_output(raw)
        assert result == '{"action": "DONE", "summary": "완료"}'

    def test_extract_json_with_text(self):
        """텍스트 사이의 JSON 추출"""
        raw = '응답입니다: {"key": "value"} 끝'
        result = extract_json_from_output(raw)
        assert result == '{"key": "value"}'

    def test_extract_no_json(self):
        """JSON 없는 경우"""
        raw = "이건 JSON이 아닙니다"
        result = extract_json_from_output(raw)
        assert result == "이건 JSON이 아닙니다"


class TestValidateOutput:
    """validate_output() 테스트"""

    def test_validate_valid_coder_output(self):
        """정상 Coder JSON 검증"""
        raw = '''
        {"summary": "버그 수정", "files_changed": ["file.py"], "diff": "--- a\\n+++ b"}
        '''
        success, result, error = validate_output(raw, "coder")
        assert success is True
        assert error is None
        assert isinstance(result, CoderOutput)

    def test_validate_invalid_json(self):
        """잘못된 JSON 검증"""
        raw = "이건 JSON이 아닙니다"
        success, result, error = validate_output(raw, "coder")
        assert success is False
        assert error is not None

    def test_validate_unknown_agent(self):
        """알 수 없는 에이전트는 항상 성공"""
        raw = "아무 텍스트"
        success, result, error = validate_output(raw, "unknown")
        assert success is True
        assert result == "아무 텍스트"

    def test_validate_missing_required_field(self):
        """필수 필드 누락"""
        raw = '{"summary": "요약만"}'
        success, result, error = validate_output(raw, "coder")
        assert success is False
        assert "files_changed" in error or "diff" in error


class TestSchemaPrompt:
    """get_schema_prompt() 테스트"""

    def test_schema_prompt_contains_json(self):
        """스키마 프롬프트에 JSON 포함"""
        prompt = get_schema_prompt("coder")
        assert "```json" in prompt
        assert "summary" in prompt
        assert "files_changed" in prompt

    def test_schema_prompt_unknown_agent(self):
        """알 수 없는 에이전트는 빈 문자열"""
        prompt = get_schema_prompt("unknown")
        assert prompt == ""

    def test_schema_prompt_all_agents(self):
        """모든 에이전트의 스키마 프롬프트 생성"""
        # council은 Config가 없어서 제외
        agents = ["coder", "qa", "reviewer", "strategist", "pm", "documentor"]
        for agent in agents:
            prompt = get_schema_prompt(agent)
            assert len(prompt) > 0
            assert "출력 형식" in prompt


class TestRunWithContract:
    """run_with_contract() 테스트"""

    def test_run_with_contract_no_contract(self):
        """계약 없는 에이전트는 raw string 반환"""
        from src.core.contracts import run_with_contract

        def mock_llm():
            return "plain text response"

        result = run_with_contract(mock_llm, "unknown_agent")
        assert result == "plain text response"

    def test_run_with_contract_valid_json(self):
        """유효한 JSON 응답"""
        from src.core.contracts import run_with_contract

        def mock_llm():
            return '{"summary": "버그 수정", "files_changed": ["file.py"], "diff": "---"}'

        result = run_with_contract(mock_llm, "coder")
        assert result.summary == "버그 수정"

    def test_run_with_contract_retry(self):
        """재시도 로직 테스트"""
        from src.core.contracts import run_with_contract, FormatGateError

        call_count = 0

        def mock_llm():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return "invalid json"
            return '{"summary": "성공", "files_changed": ["f.py"], "diff": "---"}'

        result = run_with_contract(mock_llm, "coder", max_retry=3)
        assert result.summary == "성공"
        assert call_count == 3

    def test_run_with_contract_max_retry_exceeded(self):
        """최대 재시도 초과"""
        from src.core.contracts import run_with_contract, FormatGateError

        def mock_llm():
            return "always invalid"

        with pytest.raises(FormatGateError):
            run_with_contract(mock_llm, "coder", max_retry=2)

    def test_run_with_contract_on_retry_callback(self):
        """on_retry 콜백 테스트"""
        from src.core.contracts import run_with_contract

        retry_errors = []

        def mock_llm():
            return "invalid"

        def on_retry(error):
            retry_errors.append(error)

        try:
            run_with_contract(mock_llm, "coder", max_retry=2, on_retry=on_retry)
        except:
            pass

        assert len(retry_errors) == 2


class TestTaskSpec:
    """TaskSpec 모델 테스트"""

    def test_valid_task_spec(self):
        """정상적인 TaskSpec"""
        task = TaskSpec(
            task_id="T001",
            agent="coder",
            instruction="버그 수정"
        )
        assert task.task_id == "T001"
        assert task.priority == "MEDIUM"  # 기본값

    def test_task_spec_with_context(self):
        """컨텍스트 포함된 TaskSpec"""
        task = TaskSpec(
            task_id="T002",
            agent="qa",
            instruction="테스트 실행",
            context="이전 커밋 참조",
            priority="HIGH"
        )
        assert task.context == "이전 커밋 참조"
        assert task.priority == "HIGH"

    def test_task_spec_invalid_agent(self):
        """잘못된 에이전트 이름"""
        with pytest.raises(Exception):
            TaskSpec(
                task_id="T003",
                agent="invalid_agent",
                instruction="실패할 것"
            )


class TestRisk:
    """Risk 모델 테스트"""

    def test_valid_risk(self):
        """정상적인 Risk"""
        risk = Risk(
            severity="CRITICAL",
            file="src/auth.py",
            line=42,
            issue="SQL Injection",
            fix_suggestion="Prepared statement 사용"
        )
        assert risk.severity == "CRITICAL"
        assert risk.line == 42

    def test_risk_without_optional_fields(self):
        """선택 필드 없는 Risk"""
        risk = Risk(
            severity="LOW",
            file="config.py",
            issue="매직 넘버 사용"
        )
        assert risk.line is None
        assert risk.fix_suggestion is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
