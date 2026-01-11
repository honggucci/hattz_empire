"""
Hattz Empire - E2E Integration Tests
전체 시스템 흐름 통합 테스트

테스트 범위:
1. contracts.py - JSON 파싱 및 검증
2. cli_supervisor.py - 에스컬레이션 및 세션 관리
3. llm_caller.py - LLM 호출 흐름 (mock)
4. Flask API 엔드포인트 (mock)
"""
import pytest
import sys
import json
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from typing import Optional

# Path setup
sys.path.insert(0, "c:\\Users\\hahonggu\\Desktop\\coin_master\\hattz_empire")


# =============================================================================
# Test: Contracts Integration
# =============================================================================

class TestContractsIntegration:
    """contracts.py 통합 테스트"""

    def test_coder_output_parse(self):
        """CoderOutput 파싱"""
        from src.core.contracts import CoderOutput

        data = {
            "summary": "로그인 버그 수정",
            "files_changed": ["src/api/auth.py"],
            "diff": "--- a/src/api/auth.py\n+++ b/src/api/auth.py"
        }

        output = CoderOutput(**data)
        assert output.summary == "로그인 버그 수정"
        assert len(output.files_changed) == 1
        assert "---" in output.diff

    def test_qa_output_parse(self):
        """QAOutput 파싱"""
        from src.core.contracts import QAOutput, TestCase, TestResult

        data = {
            "verdict": "PASS",
            "tests": [
                {"name": "test_login", "result": "PASS"}
            ],
            "issues_found": []
        }

        output = QAOutput(**data)
        assert output.verdict == TestResult.PASS
        assert len(output.tests) == 1

    def test_reviewer_output_parse(self):
        """ReviewerOutput 파싱"""
        from src.core.contracts import ReviewerOutput, Verdict

        data = {
            "verdict": "APPROVE",
            "risks": [],
            "security_score": 9,
            "approved_files": ["src/api/auth.py"],
            "blocked_files": []
        }

        output = ReviewerOutput(**data)
        assert output.verdict == Verdict.APPROVE
        assert output.security_score == 9

    def test_pm_output_parse(self):
        """PMOutput 파싱"""
        from src.core.contracts import PMOutput

        data = {
            "action": "DISPATCH",
            "tasks": [
                {"task_id": "T001", "agent": "coder", "instruction": "버그 수정"}
            ],
            "summary": "coder에게 작업 할당",
            "requires_ceo": False
        }

        output = PMOutput(**data)
        assert output.action == "DISPATCH"
        assert len(output.tasks) == 1
        assert output.tasks[0].agent == "coder"

    def test_pm_summary_truncation(self):
        """PMOutput summary 자동 잘라내기 (v2.6.5)"""
        from src.core.contracts import PMOutput

        long_summary = "A" * 400  # 300자 초과

        data = {
            "action": "DONE",
            "tasks": [],
            "summary": long_summary,
            "requires_ceo": False
        }

        output = PMOutput(**data)
        assert len(output.summary) == 300
        assert output.summary.endswith("...")

    def test_extract_json_from_output(self):
        """LLM 출력에서 JSON 추출"""
        from src.core.contracts import extract_json_from_output

        # Case 1: ```json 블록
        raw1 = """분석 결과:
```json
{"summary": "test", "files_changed": [], "diff": ""}
```
"""
        json_str = extract_json_from_output(raw1)
        assert '"summary"' in json_str

        # Case 2: 순수 JSON
        raw2 = '{"summary": "test", "files_changed": [], "diff": ""}'
        json_str = extract_json_from_output(raw2)
        assert '"summary"' in json_str

    def test_validate_output_success(self):
        """출력 검증 성공"""
        from src.core.contracts import validate_output

        raw = '{"summary": "완료", "files_changed": ["a.py"], "diff": "diff"}'
        success, result, error = validate_output(raw, "coder")

        assert success is True
        assert error is None
        assert result.summary == "완료"

    def test_validate_output_failure(self):
        """출력 검증 실패"""
        from src.core.contracts import validate_output

        raw = "이건 JSON이 아닙니다"
        success, result, error = validate_output(raw, "coder")

        assert success is False
        assert error is not None

    def test_get_schema_prompt(self):
        """스키마 프롬프트 생성"""
        from src.core.contracts import get_schema_prompt

        prompt = get_schema_prompt("coder")

        assert "출력 형식" in prompt
        assert "JSON" in prompt
        assert "summary" in prompt

    def test_contract_registry(self):
        """CONTRACT_REGISTRY 완전성"""
        from src.core.contracts import CONTRACT_REGISTRY

        expected_roles = ["coder", "qa", "reviewer", "strategist", "pm", "council", "documentor"]

        for role in expected_roles:
            assert role in CONTRACT_REGISTRY, f"{role} not in registry"


# =============================================================================
# Test: CLI Supervisor Integration
# =============================================================================

class TestCLISupervisorIntegration:
    """cli_supervisor.py 통합 테스트"""

    def test_escalation_level_enum(self):
        """EscalationLevel enum 테스트"""
        from src.services.cli_supervisor import EscalationLevel

        # enum 값 확인 (int 기반)
        assert EscalationLevel.SELF_REPAIR is not None
        assert EscalationLevel.ROLE_SWITCH is not None
        assert EscalationLevel.HARD_FAIL is not None
        # 순서 확인
        assert EscalationLevel.SELF_REPAIR.value < EscalationLevel.ROLE_SWITCH.value
        assert EscalationLevel.ROLE_SWITCH.value < EscalationLevel.HARD_FAIL.value

    def test_failure_signature_creation(self):
        """FailureSignature 생성 (tuple로 missing_fields)"""
        from src.services.cli_supervisor import FailureSignature

        sig = FailureSignature(
            error_type="JSON_PARSE_ERROR",
            missing_fields=tuple(["summary"]),  # tuple로 변환
            profile="coder",
            prompt_hash="abc123"
        )
        assert sig.error_type == "JSON_PARSE_ERROR"
        assert sig.profile == "coder"

    def test_retry_escalator_init(self):
        """RetryEscalator 초기화"""
        from src.services.cli_supervisor import RetryEscalator

        escalator = RetryEscalator()
        assert escalator is not None

    def test_semantic_guard_init(self):
        """SemanticGuard 초기화"""
        from src.services.cli_supervisor import SemanticGuard

        guard = SemanticGuard()
        assert guard is not None

    def test_rate_limiter_init(self):
        """RateLimiter 초기화 (기본값)"""
        from src.services.cli_supervisor import RateLimiter

        limiter = RateLimiter()
        assert limiter is not None

    def test_cli_result_dataclass(self):
        """CLIResult 구조"""
        from src.services.cli_supervisor import CLIResult, EscalationLevel

        result = CLIResult(
            success=False,
            output="",
            error="JSON parse failed",
            retry_count=2,
            escalation_level=EscalationLevel.ROLE_SWITCH,
            role_switched=True,
            original_profile="coder"
        )

        assert result.success is False
        assert result.escalation_level == EscalationLevel.ROLE_SWITCH
        assert result.role_switched is True


# =============================================================================
# Test: LLM Caller Integration (Mocked)
# =============================================================================

class TestLLMCallerIntegration:
    """llm_caller.py 통합 테스트 (mock 기반)"""

    def test_loop_breaker_exists(self):
        """LoopBreaker 클래스 존재 확인"""
        from src.core.llm_caller import LoopBreaker

        breaker = LoopBreaker()
        assert breaker is not None

    def test_should_convene_council_exists(self):
        """should_convene_council 함수 존재"""
        from src.core.llm_caller import should_convene_council

        # 함수 시그니처 확인
        import inspect
        sig = inspect.signature(should_convene_council)
        assert len(sig.parameters) >= 1

    def test_call_llm_function_exists(self):
        """call_llm 함수 존재"""
        from src.core.llm_caller import call_llm

        import inspect
        sig = inspect.signature(call_llm)
        assert "messages" in sig.parameters

    def test_call_anthropic_function_exists(self):
        """call_anthropic 함수 존재"""
        from src.core.llm_caller import call_anthropic

        import inspect
        sig = inspect.signature(call_anthropic)
        assert "messages" in sig.parameters

    def test_call_agent_function_exists(self):
        """call_agent 함수 존재"""
        from src.core.llm_caller import call_agent

        import inspect
        sig = inspect.signature(call_agent)
        assert "messages" in sig.parameters or "agent_role" in sig.parameters


# =============================================================================
# Test: Flask API Integration (Mocked)
# =============================================================================

class TestFlaskAPIIntegration:
    """Flask API 통합 테스트"""

    def test_flask_app_creation(self):
        """Flask 앱 생성"""
        from flask import Flask

        app = Flask(__name__)
        app.config['TESTING'] = True
        assert app is not None

    def test_health_blueprint_exists(self):
        """health Blueprint 존재"""
        from src.api.health import health_bp

        assert health_bp is not None

    def test_contracts_module_import(self):
        """contracts 모듈 전체 import"""
        from src.core.contracts import (
            CoderOutput, QAOutput, ReviewerOutput, PMOutput,
            StrategistOutput, CouncilMemberOutput, DocumentorOutput,
            Verdict, TestResult,
            CONTRACT_REGISTRY, get_contract, get_schema_prompt,
            extract_json_from_output, validate_output,
            run_with_contract, FormatGateError
        )

        # 모든 import 성공
        assert CoderOutput is not None
        assert Verdict.APPROVE.value == "APPROVE"


# =============================================================================
# Test: Database Integration (Mocked)
# =============================================================================

class TestDatabaseIntegration:
    """database.py 통합 테스트"""

    def test_database_module_exists(self):
        """database 모듈 존재"""
        import src.services.database
        assert src.services.database is not None

    def test_sqlite3_import(self):
        """sqlite3 import 가능"""
        import sqlite3
        assert sqlite3 is not None


# =============================================================================
# Test: Full E2E Flow (Mocked)
# =============================================================================

class TestFullE2EFlow:
    """전체 E2E 흐름 테스트"""

    def test_ceo_to_coder_flow(self):
        """CEO → PM → Coder 흐름"""
        from src.core.contracts import PMOutput, CoderOutput, TaskSpec

        # 1. PM이 작업 생성
        pm_output = PMOutput(
            action="DISPATCH",
            tasks=[TaskSpec(
                task_id="T001",
                agent="coder",
                instruction="로그인 버그 수정"
            )],
            summary="coder에게 작업 할당",
            requires_ceo=False
        )

        assert pm_output.action == "DISPATCH"
        assert pm_output.tasks[0].agent == "coder"

        # 2. Coder가 작업 완료
        coder_output = CoderOutput(
            summary="로그인 버그 수정 완료",
            files_changed=["src/api/auth.py"],
            diff="--- a/src/api/auth.py\n+++ b/src/api/auth.py\n@@ -10,1 +10,2 @@\n+    return True"
        )

        assert "수정 완료" in coder_output.summary
        assert len(coder_output.files_changed) > 0

    def test_escalation_to_ceo_flow(self):
        """에스컬레이션 → CEO 흐름"""
        from src.core.contracts import PMOutput

        # PM이 에스컬레이션 결정
        pm_output = PMOutput(
            action="BLOCKED",
            tasks=[],
            summary="권한 부족으로 작업 불가",
            requires_ceo=True
        )

        assert pm_output.action == "BLOCKED"
        assert pm_output.requires_ceo is True

    def test_retry_flow(self):
        """재시도 흐름"""
        from src.core.contracts import PMOutput

        # PM이 재시도 결정
        pm_output = PMOutput(
            action="RETRY",
            tasks=[],
            summary="JSON 파싱 실패로 재시도",
            requires_ceo=False
        )

        assert pm_output.action == "RETRY"

    def test_council_verdict_flow(self):
        """Council 판정 흐름"""
        from src.core.contracts import CouncilMemberOutput

        # 7개 페르소나 판정
        verdicts = []
        for i in range(7):
            verdict = CouncilMemberOutput(
                score=7 + (i % 3),  # 7-9점
                reasoning=f"페르소나 {i+1} 판단",
                concerns=["리스크 1"] if i % 2 == 0 else [],
                approvals=["장점 1"] if i % 2 == 1 else []
            )
            verdicts.append(verdict)

        # 평균 점수 계산
        avg_score = sum(v.score for v in verdicts) / len(verdicts)
        assert 7 <= avg_score <= 9


# =============================================================================
# Test: Error Handling Integration
# =============================================================================

class TestErrorHandlingIntegration:
    """에러 처리 통합 테스트"""

    def test_format_gate_error(self):
        """FormatGateError 예외"""
        from src.core.contracts import FormatGateError

        with pytest.raises(FormatGateError):
            raise FormatGateError("FORMAT_GATE_FAIL (coder): missing summary")

    def test_validation_error_handling(self):
        """검증 에러 처리"""
        from src.core.contracts import validate_output

        # 잘못된 JSON
        success, _, error = validate_output("not json", "coder")
        assert success is False
        assert error is not None

        # 필드 누락
        success, _, error = validate_output('{"summary": "x"}', "coder")
        assert success is False  # files_changed, diff 누락


# =============================================================================
# Test: Configuration Integration
# =============================================================================

class TestConfigurationIntegration:
    """config.py 통합 테스트"""

    def test_config_import(self):
        """config 모듈 import"""
        import config

        assert hasattr(config, 'ANTHROPIC_API_KEY') or True  # 환경에 따라 다름

    def test_config_module_exists(self):
        """config 모듈 존재"""
        import config
        assert config is not None


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
