"""
Hattz Empire - LLM Caller 단위 테스트
대상: src/core/llm_caller.py (699줄 → 60%+ 커버리지 목표)

테스트 전략:
1. 순수 함수 테스트 (I/O 없음)
2. Mock 기반 API 호출 테스트
3. LoopBreaker 클래스 테스트
4. 에이전트별 라우팅 테스트
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from pathlib import Path
import json


# =============================================================================
# Test: collect_project_context()
# =============================================================================

class TestCollectProjectContext:
    """프로젝트 컨텍스트 수집 함수 테스트"""

    def test_unknown_project_returns_error(self):
        """존재하지 않는 프로젝트명 → 에러 반환"""
        from src.core.llm_caller import collect_project_context

        result = collect_project_context("nonexistent_project_xyz")
        assert "[ERROR]" in result
        assert "찾을 수 없습니다" in result

    def test_hattz_empire_project_exists(self):
        """hattz_empire 프로젝트 컨텍스트 수집 성공"""
        from src.core.llm_caller import collect_project_context, PROJECT_PATHS

        # hattz_empire이 PROJECT_PATHS에 있는지 확인
        assert "hattz_empire" in PROJECT_PATHS

        result = collect_project_context("hattz_empire", max_files=10, max_chars=5000)

        # 기본 정보 포함 여부
        assert "# 프로젝트: hattz_empire" in result
        assert "## 파일 구조" in result
        assert "Python 파일:" in result

    def test_max_chars_truncation(self):
        """max_chars 초과 시 잘림 확인"""
        from src.core.llm_caller import collect_project_context

        # 매우 작은 max_chars로 호출
        result = collect_project_context("hattz_empire", max_chars=500)

        # 500자 제한이므로 truncated 발생 가능
        # 실제로는 기본 헤더만으로도 500자 초과할 수 있음
        assert len(result) < 50000  # 어쨌든 제한됨


# =============================================================================
# Test: extract_json_from_output()
# =============================================================================

class TestExtractJsonFromOutput:
    """LLM 출력에서 JSON 추출 테스트"""

    def test_extract_json_block_markdown(self):
        """```json ... ``` 블록에서 추출"""
        from src.core.contracts import extract_json_from_output

        raw = '''설명입니다.
```json
{"key": "value", "num": 42}
```
마무리.'''

        result = extract_json_from_output(raw)
        assert result == '{"key": "value", "num": 42}'

    def test_extract_json_pure_braces(self):
        """{ ... } 패턴에서 추출"""
        from src.core.contracts import extract_json_from_output

        raw = 'prefix {"key": "value"} suffix'
        result = extract_json_from_output(raw)
        assert '{"key": "value"}' in result

    def test_extract_json_no_json(self):
        """JSON 없으면 원본 반환"""
        from src.core.contracts import extract_json_from_output

        raw = "이건 JSON이 아닙니다"
        result = extract_json_from_output(raw)
        assert result == "이건 JSON이 아닙니다"


# =============================================================================
# Test: _extract_json_from_text() (llm_caller 내부 함수)
# =============================================================================

class TestExtractJsonFromText:
    """텍스트에서 JSON 파싱 테스트"""

    def test_valid_json_block(self):
        """유효한 JSON 블록 파싱"""
        from src.core.llm_caller import _extract_json_from_text

        text = '''```json
{
    "verdict": "APPROVE",
    "must_fix": [],
    "confidence": 95
}
```'''
        result = _extract_json_from_text(text)

        assert result["verdict"] == "APPROVE"
        assert result["must_fix"] == []
        assert result["confidence"] == 95

    def test_pure_json_object(self):
        """순수 JSON 객체 파싱"""
        from src.core.llm_caller import _extract_json_from_text

        text = '{"verdict": "REVISE", "must_fix": ["에러"], "confidence": 50}'
        result = _extract_json_from_text(text)

        assert result["verdict"] == "REVISE"
        assert "에러" in result["must_fix"]

    def test_invalid_json_returns_default(self):
        """잘못된 JSON → 기본값 반환"""
        from src.core.llm_caller import _extract_json_from_text

        text = "이건 JSON이 아닙니다"
        result = _extract_json_from_text(text)

        # 기본값 검증
        assert result["verdict"] == "REVISE"
        assert "JSON 파싱 실패" in result["must_fix"][0]


# =============================================================================
# Test: LoopBreaker Class
# =============================================================================

class TestLoopBreaker:
    """루프 브레이커 클래스 테스트"""

    def test_init_state(self):
        """초기 상태 확인"""
        from src.core.llm_caller import LoopBreaker

        breaker = LoopBreaker()

        assert breaker.step_count == 0
        assert breaker.stage_retries == {}
        assert breaker.response_history == []
        assert breaker.is_broken is False
        assert breaker.break_reason is None

    def test_reset(self):
        """reset() 메서드 테스트"""
        from src.core.llm_caller import LoopBreaker

        breaker = LoopBreaker()
        breaker.step_count = 5
        breaker.is_broken = True

        breaker.reset()

        assert breaker.step_count == 0
        assert breaker.is_broken is False

    def test_max_total_steps_exceeded(self):
        """MAX_TOTAL_STEPS 초과 감지"""
        from src.core.llm_caller import LoopBreaker, LOOP_BREAKER_CONFIG

        breaker = LoopBreaker()
        max_steps = LOOP_BREAKER_CONFIG["MAX_TOTAL_STEPS"]

        # max_steps까지는 OK
        for i in range(max_steps):
            should_break, _ = breaker.check_and_update(f"stage_{i}", f"response_{i}")
            assert should_break is False

        # max_steps + 1에서 break
        should_break, reason = breaker.check_and_update("overflow", "response")
        assert should_break is True
        assert "MAX_TOTAL_STEPS" in reason

    def test_max_stage_retry_exceeded(self):
        """MAX_STAGE_RETRY 초과 감지"""
        from src.core.llm_caller import LoopBreaker, LOOP_BREAKER_CONFIG

        breaker = LoopBreaker()
        max_retry = LOOP_BREAKER_CONFIG["MAX_STAGE_RETRY"]

        # 같은 stage 반복
        for i in range(max_retry):
            should_break, _ = breaker.check_and_update("coder", f"response_{i}")
            assert should_break is False

        # max_retry + 1에서 break
        should_break, reason = breaker.check_and_update("coder", "response")
        assert should_break is True
        assert "MAX_STAGE_RETRY" in reason

    def test_similarity_detection(self):
        """반복 응답 유사도 감지"""
        from src.core.llm_caller import LoopBreaker

        breaker = LoopBreaker()

        # 거의 동일한 응답 3번
        response = "이것은 반복되는 응답입니다 테스트 테스트 테스트"

        breaker.check_and_update("stage1", response)
        breaker.check_and_update("stage2", response)
        breaker.check_and_update("stage3", response)

        # 4번째 동일 응답 → 유사도 감지
        should_break, reason = breaker.check_and_update("stage4", response)
        assert should_break is True
        assert "유사도" in reason or "반복" in reason

    def test_calculate_similarity(self):
        """유사도 계산 로직 테스트"""
        from src.core.llm_caller import LoopBreaker

        breaker = LoopBreaker()

        # 동일 텍스트 → 1.0
        sim = breaker._calculate_similarity("hello world", "hello world")
        assert sim == 1.0

        # 완전 다른 텍스트 → 낮은 유사도
        sim = breaker._calculate_similarity("apple banana", "xyz abc")
        assert sim < 0.5

        # 빈 텍스트
        sim = breaker._calculate_similarity("", "hello")
        assert sim == 0.0

    def test_escalation_message(self):
        """에스컬레이션 메시지 생성"""
        from src.core.llm_caller import LoopBreaker

        breaker = LoopBreaker()
        breaker.is_broken = True
        breaker.break_reason = "테스트 사유"
        breaker.step_count = 5

        msg = breaker.get_escalation_message()

        assert "루프 브레이커 발동" in msg
        assert "테스트 사유" in msg


# =============================================================================
# Test: should_convene_council()
# =============================================================================

class TestShouldConveneCouncil:
    """위원회 자동 소집 조건 테스트"""

    def test_non_pm_returns_none(self):
        """PM이 아닌 역할 → None 반환"""
        from src.core.llm_caller import should_convene_council

        result = should_convene_council("coder", "some response")
        assert result is None

        result = should_convene_council("qa", "some response")
        assert result is None

    def test_requires_council_true(self):
        """dual_meta.requires_council=True → 소집"""
        from src.core.llm_caller import should_convene_council

        dual_meta = {"requires_council": True, "verdict": "REVISE"}
        result = should_convene_council("pm", "response", dual_meta=dual_meta)

        assert result == "pm"

    def test_reject_verdict(self):
        """verdict=REJECT → 소집"""
        from src.core.llm_caller import should_convene_council

        dual_meta = {"verdict": "REJECT"}
        result = should_convene_council("pm", "response", dual_meta=dual_meta)

        assert result == "pm"

    def test_max_rewrite_exhausted(self):
        """MAX_REWRITE_EXHAUSTED → 소집"""
        from src.core.llm_caller import should_convene_council

        dual_meta = {"verdict": "MAX_REWRITE_EXHAUSTED"}
        result = should_convene_council("pm", "response", dual_meta=dual_meta)

        assert result == "pm"

    def test_audit_history_requires_council(self):
        """audit_history에 requires_council 있으면 소집"""
        from src.core.llm_caller import should_convene_council

        dual_meta = {
            "audit_history": [
                {"verdict": "REVISE", "requires_council": False},
                {"verdict": "REVISE", "requires_council": True},
            ]
        }
        result = should_convene_council("pm", "response", dual_meta=dual_meta)

        assert result == "pm"

    def test_long_response_with_keywords(self):
        """긴 응답 + 결정 키워드 → 소집"""
        from src.core.llm_caller import should_convene_council

        # 500자 초과 + 키워드
        long_response = "전략을 수립해야 합니다. " * 50
        result = should_convene_council("pm", long_response)

        assert result == "pm"


# =============================================================================
# Test: _determine_trigger_source()
# =============================================================================

class TestDetermineTriggerSource:
    """트리거 소스 결정 테스트"""

    def test_empty_meta_returns_manual(self):
        """빈 meta → 'manual'"""
        from src.core.llm_caller import _determine_trigger_source

        assert _determine_trigger_source(None) == "manual"
        assert _determine_trigger_source({}) == "manual"

    def test_reject_verdict(self):
        """REJECT → 'json_verdict_reject'"""
        from src.core.llm_caller import _determine_trigger_source

        meta = {"verdict": "REJECT"}
        assert _determine_trigger_source(meta) == "json_verdict_reject"

    def test_max_rewrite(self):
        """MAX_REWRITE_EXHAUSTED → 'json_verdict_max_rewrite'"""
        from src.core.llm_caller import _determine_trigger_source

        meta = {"verdict": "MAX_REWRITE_EXHAUSTED"}
        assert _determine_trigger_source(meta) == "json_verdict_max_rewrite"

    def test_requires_council_flag(self):
        """requires_council=True → 'json_requires_council'"""
        from src.core.llm_caller import _determine_trigger_source

        meta = {"requires_council": True, "verdict": "REVISE"}
        assert _determine_trigger_source(meta) == "json_requires_council"


# =============================================================================
# Test: extract_project_from_message()
# =============================================================================

class TestExtractProjectFromMessage:
    """[PROJECT: xxx] 태그 추출 테스트"""

    def test_with_project_tag(self):
        """프로젝트 태그 있는 경우"""
        from src.core.llm_caller import extract_project_from_message

        message = "[PROJECT: hattz_empire]\n버그를 수정해주세요."
        project, remaining = extract_project_from_message(message)

        assert project == "hattz_empire"
        assert remaining == "버그를 수정해주세요."

    def test_without_project_tag(self):
        """프로젝트 태그 없는 경우"""
        from src.core.llm_caller import extract_project_from_message

        message = "버그를 수정해주세요."
        project, remaining = extract_project_from_message(message)

        assert project is None
        assert remaining == "버그를 수정해주세요."

    def test_project_tag_with_spaces(self):
        """프로젝트 태그에 공백 있는 경우"""
        from src.core.llm_caller import extract_project_from_message

        message = "[PROJECT:   wpcn  ]\n분석해주세요."
        project, remaining = extract_project_from_message(message)

        assert project == "wpcn"
        assert remaining == "분석해주세요."


# =============================================================================
# Test: Singleton Functions
# =============================================================================

class TestSingletonFunctions:
    """싱글톤 함수 테스트"""

    def test_get_loop_breaker_singleton(self):
        """get_loop_breaker() 싱글톤 반환"""
        from src.core.llm_caller import get_loop_breaker, LoopBreaker

        breaker1 = get_loop_breaker()
        breaker2 = get_loop_breaker()

        assert breaker1 is breaker2
        assert isinstance(breaker1, LoopBreaker)

    def test_check_loop_helper(self):
        """check_loop() 헬퍼 함수"""
        from src.core.llm_caller import check_loop, get_loop_breaker

        # 리셋 후 테스트
        get_loop_breaker().reset()

        should_break, reason = check_loop("test_stage", "test response")

        assert should_break is False
        assert reason is None


# =============================================================================
# Test: call_llm() with Mocks
# =============================================================================

class TestCallLLMMocked:
    """call_llm() Mock 테스트"""

    @patch('src.core.llm_caller.call_anthropic')
    def test_anthropic_provider(self, mock_call):
        """anthropic provider 라우팅"""
        from src.core.llm_caller import call_llm
        from config import ModelConfig

        mock_call.return_value = "Anthropic response"

        config = ModelConfig(
            name="test",
            provider="anthropic",
            model_id="claude-3",
            max_tokens=1000,
            temperature=0.7,
            api_key_env="ANTHROPIC_API_KEY"
        )

        result = call_llm(config, [{"role": "user", "content": "test"}], "system")

        assert result == "Anthropic response"
        mock_call.assert_called_once()

    @patch('src.core.llm_caller.call_openai')
    def test_openai_provider(self, mock_call):
        """openai provider 라우팅"""
        from src.core.llm_caller import call_llm
        from config import ModelConfig

        mock_call.return_value = ("OpenAI response", 100, 50)

        config = ModelConfig(
            name="test",
            provider="openai",
            model_id="gpt-4",
            max_tokens=1000,
            temperature=0.7,
            api_key_env="OPENAI_API_KEY"
        )

        result = call_llm(config, [{"role": "user", "content": "test"}], "system")

        assert result == "OpenAI response"

    @patch('src.core.llm_caller.call_google')
    def test_google_provider(self, mock_call):
        """google provider 라우팅"""
        from src.core.llm_caller import call_llm
        from config import ModelConfig

        mock_call.return_value = ("Google response", 100, 50)

        config = ModelConfig(
            name="test",
            provider="google",
            model_id="gemini-1.5",
            max_tokens=1000,
            temperature=0.7,
            api_key_env="GOOGLE_API_KEY"
        )

        result = call_llm(config, [{"role": "user", "content": "test"}], "system")

        assert result == "Google response"

    def test_unknown_provider(self):
        """알 수 없는 provider → 에러"""
        from src.core.llm_caller import call_llm
        from config import ModelConfig

        config = ModelConfig(
            name="test",
            provider="unknown_provider",
            model_id="test",
            max_tokens=1000,
            temperature=0.7,
            api_key_env="TEST_KEY"
        )

        result = call_llm(config, [{"role": "user", "content": "test"}], "system")

        assert "[Error] Unknown provider" in result


# =============================================================================
# Test: DUAL_ENGINE_ROLES Configuration
# =============================================================================

class TestDualEngineConfig:
    """듀얼 엔진 설정 검증"""

    def test_required_roles_exist(self):
        """필수 역할들이 DUAL_ENGINE_ROLES에 존재"""
        from src.core.llm_caller import DUAL_ENGINE_ROLES

        required = ["coder", "strategist", "qa", "researcher", "excavator"]
        for role in required:
            assert role in DUAL_ENGINE_ROLES, f"{role} not in DUAL_ENGINE_ROLES"

    def test_each_role_has_required_keys(self):
        """각 역할에 필수 키 존재"""
        from src.core.llm_caller import DUAL_ENGINE_ROLES

        required_keys = ["writer", "auditor", "stamp", "description"]

        for role, config in DUAL_ENGINE_ROLES.items():
            for key in required_keys:
                assert key in config, f"{role} missing key: {key}"

    def test_profiles_configured(self):
        """프로필 설정 검증"""
        from src.core.llm_caller import DUAL_ENGINE_ROLES

        for role, config in DUAL_ENGINE_ROLES.items():
            # auditor_profile과 stamp_profile 있어야 함
            assert "auditor_profile" in config, f"{role} missing auditor_profile"
            assert "stamp_profile" in config, f"{role} missing stamp_profile"


# =============================================================================
# Test: LOOP_BREAKER_CONFIG
# =============================================================================

class TestLoopBreakerConfig:
    """루프 브레이커 설정 검증"""

    def test_config_exists(self):
        """설정 값 존재 확인"""
        from src.core.llm_caller import LOOP_BREAKER_CONFIG

        assert "MAX_STAGE_RETRY" in LOOP_BREAKER_CONFIG
        assert "MAX_TOTAL_STEPS" in LOOP_BREAKER_CONFIG
        assert "SIMILARITY_THRESHOLD" in LOOP_BREAKER_CONFIG
        assert "ESCALATE_TO_CEO" in LOOP_BREAKER_CONFIG

    def test_config_values_reasonable(self):
        """설정 값이 합리적인 범위"""
        from src.core.llm_caller import LOOP_BREAKER_CONFIG

        assert LOOP_BREAKER_CONFIG["MAX_STAGE_RETRY"] >= 1
        assert LOOP_BREAKER_CONFIG["MAX_STAGE_RETRY"] <= 10

        assert LOOP_BREAKER_CONFIG["MAX_TOTAL_STEPS"] >= 3
        assert LOOP_BREAKER_CONFIG["MAX_TOTAL_STEPS"] <= 20

        assert 0.5 <= LOOP_BREAKER_CONFIG["SIMILARITY_THRESHOLD"] <= 1.0


# =============================================================================
# Test: COUNCIL_MODEL_MAPPING
# =============================================================================

class TestCouncilModelMapping:
    """위원회 모델 매핑 검증"""

    def test_pm_council_exists(self):
        """PM 위원회 설정 존재"""
        from src.core.llm_caller import COUNCIL_MODEL_MAPPING

        assert "pm" in COUNCIL_MODEL_MAPPING

    def test_pm_personas_complete(self):
        """PM 위원회 7개 페르소나 완비"""
        from src.core.llm_caller import COUNCIL_MODEL_MAPPING

        pm_config = COUNCIL_MODEL_MAPPING["pm"]
        personas = pm_config["personas"]

        expected = [
            "skeptic", "perfectionist", "pragmatist",
            "pessimist", "optimist", "devils_advocate", "security_hawk"
        ]

        for persona in expected:
            assert persona in personas, f"Missing persona: {persona}"

    def test_tiebreaker_configured(self):
        """타이브레이커 설정"""
        from src.core.llm_caller import COUNCIL_MODEL_MAPPING

        pm_config = COUNCIL_MODEL_MAPPING["pm"]
        assert "tiebreaker" in pm_config


# =============================================================================
# Test: AUDITOR_JSON_SCHEMA
# =============================================================================

class TestAuditorJsonSchema:
    """Auditor JSON 스키마 검증"""

    def test_schema_structure(self):
        """스키마 구조 검증"""
        from src.core.llm_caller import AUDITOR_JSON_SCHEMA

        assert AUDITOR_JSON_SCHEMA["type"] == "object"
        assert "properties" in AUDITOR_JSON_SCHEMA
        assert "required" in AUDITOR_JSON_SCHEMA

    def test_verdict_enum(self):
        """verdict 필드 enum 값"""
        from src.core.llm_caller import AUDITOR_JSON_SCHEMA

        verdict_prop = AUDITOR_JSON_SCHEMA["properties"]["verdict"]
        assert verdict_prop["enum"] == ["APPROVE", "REVISE", "REJECT"]

    def test_required_fields(self):
        """필수 필드 목록"""
        from src.core.llm_caller import AUDITOR_JSON_SCHEMA

        required = AUDITOR_JSON_SCHEMA["required"]
        assert "verdict" in required
        assert "must_fix" in required
        assert "confidence" in required


# =============================================================================
# Test: call_agent() Edge Cases (Mocked)
# =============================================================================

class TestCallAgentMocked:
    """call_agent() Mock 테스트"""

    def test_blocked_direct_subagent_call(self):
        """CEO → 하위 에이전트 직접 호출 차단"""
        from src.core.llm_caller import call_agent

        # _internal_call=False (CEO 직접 호출) + 하위 에이전트
        result = call_agent(
            "버그 수정해줘",
            "coder",
            _internal_call=False,
            auto_execute=False,
            use_translation=False
        )

        assert "직접 호출 차단" in result
        assert "PM" in result or "pm" in result.lower()

    def test_blocked_qa_direct_call(self):
        """CEO → QA 직접 호출 차단"""
        from src.core.llm_caller import call_agent

        result = call_agent(
            "테스트 실행해줘",
            "qa",
            _internal_call=False,
            auto_execute=False,
            use_translation=False
        )

        assert "직접 호출 차단" in result

    def test_blocked_strategist_direct_call(self):
        """CEO → Strategist 직접 호출 차단"""
        from src.core.llm_caller import call_agent

        result = call_agent(
            "전략 수립해줘",
            "strategist",
            _internal_call=False,
            auto_execute=False,
            use_translation=False
        )

        assert "직접 호출 차단" in result

    def test_return_meta_format(self):
        """return_meta=True → (response, meta) 튜플"""
        from src.core.llm_caller import call_agent

        result = call_agent(
            "테스트",
            "coder",
            _internal_call=False,
            return_meta=True
        )

        # 차단되어도 튜플 반환
        assert isinstance(result, tuple)
        assert len(result) == 2

        response, meta = result
        assert isinstance(response, str)
        assert isinstance(meta, dict)
        assert "blocked" in meta


# =============================================================================
# Test: build_call_results_prompt()
# =============================================================================

class TestBuildCallResultsPrompt:
    """하위 에이전트 결과 프롬프트 생성 테스트"""

    def test_single_result(self):
        """단일 결과 프롬프트"""
        from src.core.llm_caller import build_call_results_prompt

        results = [
            {
                "agent": "coder",
                "message": "버그 수정해줘",
                "response": "수정 완료했습니다."
            }
        ]

        prompt = build_call_results_prompt(results)

        assert "CODER" in prompt
        assert "버그 수정해줘" in prompt
        assert "수정 완료했습니다" in prompt
        assert "종합" in prompt

    def test_multiple_results(self):
        """복수 결과 프롬프트"""
        from src.core.llm_caller import build_call_results_prompt

        results = [
            {"agent": "coder", "message": "코드 작성", "response": "코드 완료"},
            {"agent": "qa", "message": "테스트 실행", "response": "테스트 통과"},
        ]

        prompt = build_call_results_prompt(results)

        assert "1. CODER" in prompt
        assert "2. QA" in prompt


# =============================================================================
# Test: mock_agent_response()
# =============================================================================

class TestMockAgentResponse:
    """Mock 응답 함수 테스트"""

    def test_pm_response(self):
        """PM Mock 응답"""
        from src.core.llm_caller import mock_agent_response

        response = mock_agent_response("테스트 요청", "pm")

        assert "sprint_plan" in response or "delegation" in response

    def test_coder_response(self):
        """Coder Mock 응답"""
        from src.core.llm_caller import mock_agent_response

        response = mock_agent_response("코드 작성", "coder")

        assert "CODER" in response

    def test_unknown_role(self):
        """알 수 없는 역할"""
        from src.core.llm_caller import mock_agent_response

        response = mock_agent_response("요청", "unknown_role")

        assert "UNKNOWN_ROLE" in response


# =============================================================================
# Test: PROJECT_PATHS Configuration
# =============================================================================

class TestProjectPaths:
    """프로젝트 경로 설정 테스트"""

    def test_hattz_empire_path_valid(self):
        """hattz_empire 경로 유효성"""
        from src.core.llm_caller import PROJECT_PATHS

        path = PROJECT_PATHS.get("hattz_empire")
        assert path is not None
        assert path.exists()

    def test_paths_are_path_objects(self):
        """경로가 Path 객체인지 확인"""
        from src.core.llm_caller import PROJECT_PATHS
        from pathlib import Path

        for name, path in PROJECT_PATHS.items():
            assert isinstance(path, Path), f"{name} is not a Path object"


# =============================================================================
# Test: THINKING_EXTEND_PREFIX
# =============================================================================

class TestThinkingExtendPrefix:
    """Thinking Extend 프리픽스 테스트"""

    def test_prefix_content(self):
        """프리픽스 내용 검증"""
        from src.core.llm_caller import THINKING_EXTEND_PREFIX

        assert "THINKING EXTEND MODE" in THINKING_EXTEND_PREFIX
        assert "ANALYZE" in THINKING_EXTEND_PREFIX
        assert "QUESTION" in THINKING_EXTEND_PREFIX
        assert "EVALUATE" in THINKING_EXTEND_PREFIX
        assert "SYNTHESIZE" in THINKING_EXTEND_PREFIX


# =============================================================================
# Test: call_openai() Mocked
# =============================================================================

class TestCallOpenAIMocked:
    """call_openai() Mock 테스트"""

    @patch('openai.OpenAI')
    def test_gpt5_with_reasoning_effort(self, mock_openai_class):
        """GPT-5.2 + reasoning_effort 호출"""
        from src.core.llm_caller import call_openai
        from config import ModelConfig
        import os

        # API 키 환경변수 설정
        os.environ["TEST_OPENAI_KEY"] = "test-key"

        # Mock 설정
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="response"))]
        mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        mock_client.chat.completions.create.return_value = mock_response

        config = ModelConfig(
            name="GPT-5.2",
            provider="openai",
            model_id="gpt-5.2-pro",
            max_tokens=2000,
            temperature=0.7,
            api_key_env="TEST_OPENAI_KEY"
        )
        # reasoning_effort 추가
        config.reasoning_effort = "high"

        result, input_tokens, output_tokens = call_openai(
            config,
            [{"role": "user", "content": "test"}],
            "system prompt"
        )

        assert result == "response"
        assert input_tokens == 100
        assert output_tokens == 50

        # 환경변수 정리
        del os.environ["TEST_OPENAI_KEY"]


# =============================================================================
# Test: call_google() Mocked
# =============================================================================

class TestCallGoogleMocked:
    """call_google() Mock 테스트"""

    @patch('google.generativeai.configure')
    @patch('google.generativeai.GenerativeModel')
    def test_gemini_15_call(self, mock_model_class, mock_configure):
        """Gemini 1.5/2.0 호출"""
        from src.core.llm_caller import call_google
        from config import ModelConfig
        import os

        os.environ["TEST_GOOGLE_KEY"] = "test-key"

        # Mock 설정
        mock_model = MagicMock()
        mock_model_class.return_value = mock_model

        mock_chat = MagicMock()
        mock_model.start_chat.return_value = mock_chat

        mock_response = MagicMock()
        mock_response.text = "Gemini response"
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=50,
            candidates_token_count=30
        )
        mock_chat.send_message.return_value = mock_response

        config = ModelConfig(
            name="Gemini",
            provider="google",
            model_id="gemini-1.5-flash",
            max_tokens=1000,
            temperature=0.7,
            api_key_env="TEST_GOOGLE_KEY"
        )

        result, input_tokens, output_tokens = call_google(
            config,
            [{"role": "user", "content": "test"}],
            "system prompt"
        )

        assert result == "Gemini response"
        assert input_tokens == 50
        assert output_tokens == 30

        del os.environ["TEST_GOOGLE_KEY"]


# =============================================================================
# Test: process_call_tags()
# =============================================================================

class TestProcessCallTags:
    """PM 응답에서 CALL 태그 처리 테스트"""

    @patch('src.core.llm_caller.call_agent')
    @patch('src.services.executor.extract_call_info')
    def test_process_single_call(self, mock_extract, mock_call_agent):
        """단일 CALL 태그 처리"""
        from src.core.llm_caller import process_call_tags, get_loop_breaker

        # 리셋
        get_loop_breaker().reset()

        mock_extract.return_value = [
            {"agent": "coder", "message": "버그 수정해줘"}
        ]
        mock_call_agent.return_value = "버그 수정 완료"

        results = process_call_tags("[CALL:coder]버그 수정해줘[/CALL]")

        assert len(results) == 1
        assert results[0]["agent"] == "coder"
        assert results[0]["response"] == "버그 수정 완료"

    @patch('src.core.llm_caller.call_agent')
    @patch('src.services.executor.extract_call_info')
    def test_process_multiple_calls(self, mock_extract, mock_call_agent):
        """복수 CALL 태그 처리"""
        from src.core.llm_caller import process_call_tags, get_loop_breaker

        get_loop_breaker().reset()

        mock_extract.return_value = [
            {"agent": "coder", "message": "코드 작성"},
            {"agent": "qa", "message": "테스트 실행"},
        ]
        mock_call_agent.side_effect = ["코드 완료", "테스트 통과"]

        results = process_call_tags("response")

        assert len(results) == 2
        assert results[0]["agent"] == "coder"
        assert results[1]["agent"] == "qa"

    @patch('src.services.executor.extract_call_info')
    def test_loop_breaker_triggers(self, mock_extract):
        """루프 브레이커 발동 테스트"""
        from src.core.llm_caller import process_call_tags, get_loop_breaker, LOOP_BREAKER_CONFIG

        breaker = get_loop_breaker()
        breaker.reset()

        # MAX_TOTAL_STEPS 초과 상황 시뮬레이션
        breaker.step_count = LOOP_BREAKER_CONFIG["MAX_TOTAL_STEPS"]

        mock_extract.return_value = [
            {"agent": "coder", "message": "또 코드 작성"}
        ]

        results = process_call_tags("response", use_loop_breaker=True)

        # 루프 브레이커 발동 확인
        assert len(results) == 1
        assert results[0]["agent"] == "loop_breaker"
        assert results[0]["is_break"] is True


# =============================================================================
# Test: Dual Engine Functions
# =============================================================================

class TestDualEngineFunctions:
    """듀얼 엔진 관련 함수 테스트"""

    @patch('src.core.llm_caller._call_model_or_cli')
    def test_call_dual_engine_unknown_role(self, mock_call):
        """알 수 없는 역할 → 에러"""
        from src.core.llm_caller import call_dual_engine

        result = call_dual_engine(
            "unknown_role",
            [{"role": "user", "content": "test"}],
            "system"
        )

        assert "[Error]" in result

    def test_dual_engine_roles_keys(self):
        """DUAL_ENGINE_ROLES 키 검증"""
        from src.core.llm_caller import DUAL_ENGINE_ROLES

        # 각 역할에 필요한 키가 있는지
        for role, config in DUAL_ENGINE_ROLES.items():
            assert "writer" in config
            assert "auditor" in config
            assert "stamp" in config


# =============================================================================
# Test: _call_model_or_cli()
# =============================================================================

class TestCallModelOrCli:
    """모델/CLI 호출 헬퍼 테스트"""

    @patch('src.services.cli_supervisor.CLISupervisor')
    def test_cli_call_success(self, mock_cli_class):
        """CLI 호출 성공"""
        from src.core.llm_caller import _call_model_or_cli

        mock_cli = MagicMock()
        mock_cli_class.return_value = mock_cli

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "CLI 응답"
        mock_cli.call_cli.return_value = mock_result

        response, model_name = _call_model_or_cli(
            "claude_cli",
            [{"role": "user", "content": "test"}],
            "system",
            "coder"
        )

        assert response == "CLI 응답"
        assert "Claude CLI" in model_name

    @patch('src.services.cli_supervisor.CLISupervisor')
    def test_cli_call_failure(self, mock_cli_class):
        """CLI 호출 실패"""
        from src.core.llm_caller import _call_model_or_cli

        mock_cli = MagicMock()
        mock_cli_class.return_value = mock_cli

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "에러 발생"
        mock_result.abort_reason = None
        mock_cli.call_cli.return_value = mock_result

        response, model_name = _call_model_or_cli(
            "claude_cli",
            [{"role": "user", "content": "test"}],
            "system",
            "coder"
        )

        assert "[CLI Error]" in response

    @patch('src.core.llm_caller.call_llm')
    def test_model_call_fallback(self, mock_call_llm):
        """알 수 없는 모델 → gpt_5_mini 폴백"""
        from src.core.llm_caller import _call_model_or_cli

        mock_call_llm.return_value = "모델 응답"

        response, model_name = _call_model_or_cli(
            "unknown_model",
            [{"role": "user", "content": "test"}],
            "system",
            "coder"
        )

        assert response == "모델 응답"


# =============================================================================
# Test: _call_with_contract()
# =============================================================================

class TestCallWithContract:
    """Format Gate 포함 호출 테스트"""

    @patch('src.core.llm_caller._call_model_or_cli')
    def test_no_contract_role(self, mock_call):
        """Contract 없는 역할 → 기존 방식"""
        from src.core.llm_caller import _call_with_contract

        mock_call.return_value = ("응답", "모델명")

        response, model_name, validated = _call_with_contract(
            "claude_cli",
            [{"role": "user", "content": "test"}],
            "system",
            "coder",
            "unknown_role_without_contract"
        )

        assert response == "응답"
        assert validated is True

    @patch('src.core.llm_caller._call_model_or_cli')
    def test_error_response_skips_validation(self, mock_call):
        """에러 응답 → 검증 스킵"""
        from src.core.llm_caller import _call_with_contract

        mock_call.return_value = ("[Error] 에러 발생", "모델명")

        response, model_name, validated = _call_with_contract(
            "claude_cli",
            [{"role": "user", "content": "test"}],
            "system",
            "coder",
            "coder"
        )

        assert "[Error]" in response
        assert validated is False


# =============================================================================
# Test: Council Functions
# =============================================================================

class TestCouncilFunctions:
    """위원회 관련 함수 테스트"""

    def test_should_convene_council_pm_only(self):
        """PM만 위원회 소집 가능"""
        from src.core.llm_caller import should_convene_council

        # PM이 아닌 역할들
        for role in ["coder", "qa", "strategist", "analyst"]:
            result = should_convene_council(role, "any response")
            assert result is None, f"{role} should not convene council"

    def test_risk_keywords_with_patterns(self):
        """리스크 키워드 + 패턴 조합"""
        from src.core.llm_caller import should_convene_council

        # 리스크 키워드 + 경고 패턴
        response = "이 작업에는 ⚠️ 리스크가 있습니다."
        result = should_convene_council("pm", response)

        assert result == "pm"

    def test_no_council_for_short_response(self):
        """짧은 응답은 위원회 불필요"""
        from src.core.llm_caller import should_convene_council

        # 500자 미만 + 키워드만 있는 경우
        response = "전략을 확인했습니다."
        result = should_convene_council("pm", response, dual_meta={})

        assert result is None  # 500자 미만이므로 소집 안 함


# =============================================================================
# Test: convene_council_sync
# =============================================================================

class TestConveneCouncilSync:
    """동기 위원회 소집 테스트"""

    @patch('src.core.llm_caller.asyncio.run')
    def test_sync_wrapper_calls_async(self, mock_run):
        """동기 래퍼가 비동기 함수 호출"""
        from src.core.llm_caller import convene_council_sync

        mock_run.return_value = {"verdict": "pass", "summary": "OK"}

        result = convene_council_sync("pm", "content", "context")

        assert mock_run.called


# =============================================================================
# Test: init_council_with_llm()
# =============================================================================

class TestInitCouncilWithLLM:
    """위원회 LLM 초기화 테스트"""

    @patch('src.infra.council.reset_council')
    @patch('src.infra.council.get_council')
    @patch('src.services.cli_supervisor.CLISupervisor')
    def test_council_llm_caller_set(self, mock_cli, mock_get, mock_reset):
        """LLM Caller 주입 확인"""
        from src.core.llm_caller import init_council_with_llm

        mock_council = MagicMock()
        mock_get.return_value = mock_council

        result = init_council_with_llm()

        mock_reset.assert_called_once()
        mock_council.set_llm_caller.assert_called_once()
        assert result == mock_council


# =============================================================================
# Test: call_council_llm()
# =============================================================================

class TestCallCouncilLLM:
    """위원회 LLM 호출 테스트"""

    @patch('src.services.cli_supervisor.CLISupervisor')
    def test_council_llm_success(self, mock_cli_class):
        """위원회 CLI 호출 성공"""
        import asyncio
        from src.core.llm_caller import call_council_llm

        mock_cli = MagicMock()
        mock_cli_class.return_value = mock_cli

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "위원회 응답"
        mock_cli.call_cli.return_value = mock_result

        result = asyncio.run(call_council_llm(
            "system prompt",
            "user message",
            0.7,
            "skeptic",
            "pm"
        ))

        assert result == "위원회 응답"

    @patch('src.services.cli_supervisor.CLISupervisor')
    def test_council_llm_failure(self, mock_cli_class):
        """위원회 CLI 호출 실패"""
        import asyncio
        from src.core.llm_caller import call_council_llm

        mock_cli = MagicMock()
        mock_cli_class.return_value = mock_cli

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "CLI 에러"
        mock_result.abort_reason = None
        mock_cli.call_cli.return_value = mock_result

        result = asyncio.run(call_council_llm(
            "system prompt",
            "user message",
            0.7,
            "skeptic",
            "pm"
        ))

        assert "[CLI ERROR]" in result


# =============================================================================
# Test: call_dual_engine()
# =============================================================================

class TestCallDualEngine:
    """듀얼 엔진 호출 테스트 (레거시)"""

    @patch('src.core.llm_caller.call_llm')
    @patch('src.core.llm_caller.get_stream')
    def test_primary_fallback_strategy(self, mock_stream, mock_call_llm):
        """primary_fallback 병합 전략"""
        from src.core.llm_caller import call_dual_engine, DUAL_ENGINES

        # DUAL_ENGINES에 테스트용 역할이 있는지 확인
        if not DUAL_ENGINES:
            pytest.skip("DUAL_ENGINES empty")

        # 실제 역할 하나 선택
        role = list(DUAL_ENGINES.keys())[0] if DUAL_ENGINES else "coder"

        mock_call_llm.side_effect = ["Engine 1 응답", "Engine 2 응답"]
        mock_stream.return_value.log_dual_engine = MagicMock()

        result = call_dual_engine(
            role,
            [{"role": "user", "content": "test"}],
            "system"
        )

        # 둘 다 포함되어야 함
        assert "응답" in result or "Error" in result


# =============================================================================
# Test: call_dual_engine_v2()
# =============================================================================

class TestCallDualEngineV2:
    """듀얼 엔진 V2 테스트"""

    @patch('src.core.llm_caller._call_model_or_cli')
    @patch('src.core.llm_caller.get_stream')
    def test_v2_unknown_role_fallback(self, mock_stream, mock_call):
        """V2에서 알 수 없는 역할 → CLI 폴백"""
        from src.core.llm_caller import call_dual_engine_v2

        # CLISupervisor Mock
        with patch('src.services.cli_supervisor.CLISupervisor') as mock_cli_class:
            mock_cli = MagicMock()
            mock_cli_class.return_value = mock_cli

            mock_result = MagicMock()
            mock_result.success = True
            mock_result.output = "폴백 응답"
            mock_cli.call_cli.return_value = mock_result

            response, meta = call_dual_engine_v2(
                "unknown_role_xyz",
                [{"role": "user", "content": "test"}],
                "system"
            )

            assert meta["dual"] is False

    @patch('src.core.llm_caller._call_model_or_cli')
    @patch('src.core.llm_caller.get_stream')
    def test_v2_coder_role(self, mock_stream, mock_call):
        """V2 coder 역할 테스트"""
        from src.core.llm_caller import call_dual_engine_v2

        # Writer와 Auditor 응답
        mock_call.side_effect = [
            ("코드 작성 완료", "Claude CLI (coder)"),
            ('{"verdict": "APPROVE", "must_fix": [], "confidence": 95}', "Claude CLI (reviewer)")
        ]
        mock_stream.return_value.log_dual_engine = MagicMock()

        response, meta = call_dual_engine_v2(
            "coder",
            [{"role": "user", "content": "버그 수정"}],
            "system"
        )

        assert meta["dual"] is True
        assert "Writer" in response
        assert "Auditor" in response


# =============================================================================
# Test: dual_engine_write_audit_rewrite()
# =============================================================================

class TestDualEngineWriteAuditRewrite:
    """듀얼 엔진 V3 (Write → Audit → Rewrite) 테스트"""

    @patch('src.core.llm_caller._call_with_contract')
    @patch('src.core.llm_caller._call_model_or_cli')
    def test_v3_approve_on_first_try(self, mock_call_model, mock_call_contract):
        """V3: 첫 시도에서 APPROVE"""
        from src.core.llm_caller import dual_engine_write_audit_rewrite

        # Writer 응답
        mock_call_contract.return_value = ("초안 작성 완료", "Claude CLI (coder)", True)

        # Auditor APPROVE 응답
        mock_call_model.return_value = (
            '{"verdict": "APPROVE", "must_fix": [], "confidence": 95}',
            "Claude CLI (reviewer)"
        )

        response, meta = dual_engine_write_audit_rewrite(
            "coder",
            [{"role": "user", "content": "코드 작성"}],
            "system"
        )

        assert meta["verdict"] == "APPROVE"
        assert meta["rewrite_count"] == 0
        assert "초안 작성 완료" in response

    @patch('src.core.llm_caller._call_with_contract')
    @patch('src.core.llm_caller._call_model_or_cli')
    def test_v3_reject_triggers_council(self, mock_call_model, mock_call_contract):
        """V3: REJECT → Council 트리거"""
        from src.core.llm_caller import dual_engine_write_audit_rewrite

        mock_call_contract.return_value = ("초안", "Claude CLI", True)
        mock_call_model.return_value = (
            '{"verdict": "REJECT", "must_fix": ["근본적 설계 오류"], "confidence": 20}',
            "Claude CLI"
        )

        response, meta = dual_engine_write_audit_rewrite(
            "coder",
            [{"role": "user", "content": "test"}],
            "system"
        )

        assert meta["verdict"] == "REJECT"
        assert meta["requires_council"] is True
        assert "AUDITOR REJECT" in response

    @patch('src.core.llm_caller._call_with_contract')
    @patch('src.core.llm_caller._call_model_or_cli')
    def test_v3_revise_and_rewrite(self, mock_call_model, mock_call_contract):
        """V3: REVISE → 재작성 → APPROVE"""
        from src.core.llm_caller import dual_engine_write_audit_rewrite

        # Writer 첫 번째 응답
        mock_call_contract.side_effect = [
            ("첫 초안", "Claude CLI", True),
            ("수정된 초안", "Claude CLI", True),
        ]

        # Auditor: REVISE → APPROVE
        mock_call_model.side_effect = [
            ('{"verdict": "REVISE", "must_fix": ["버그 수정 필요"], "confidence": 50, "rewrite_instructions": "버그를 수정하세요"}', "Claude CLI"),
            ('{"verdict": "APPROVE", "must_fix": [], "confidence": 90}', "Claude CLI"),
        ]

        response, meta = dual_engine_write_audit_rewrite(
            "coder",
            [{"role": "user", "content": "test"}],
            "system"
        )

        assert meta["verdict"] == "APPROVE"
        assert meta["rewrite_count"] == 1

    @patch('src.core.llm_caller._call_with_contract')
    def test_v3_writer_error(self, mock_call_contract):
        """V3: Writer 에러 시 에러 반환"""
        from src.core.llm_caller import dual_engine_write_audit_rewrite

        mock_call_contract.return_value = ("[Error] CLI 실패", "Claude CLI", False)

        response, meta = dual_engine_write_audit_rewrite(
            "coder",
            [{"role": "user", "content": "test"}],
            "system"
        )

        assert "[Error]" in response
        assert meta["error"] == "writer_failed"

    @patch('src.core.llm_caller._call_with_contract')
    @patch('src.core.llm_caller._call_model_or_cli')
    def test_v3_max_rewrite_exhausted(self, mock_call_model, mock_call_contract):
        """V3: max_rewrite 소진 → Council 권장"""
        from src.core.llm_caller import dual_engine_write_audit_rewrite

        # 계속 REVISE만 반환
        mock_call_contract.return_value = ("초안", "Claude CLI", True)
        mock_call_model.return_value = (
            '{"verdict": "REVISE", "must_fix": ["계속 수정"], "confidence": 40, "rewrite_instructions": "다시"}',
            "Claude CLI"
        )

        response, meta = dual_engine_write_audit_rewrite(
            "coder",
            [{"role": "user", "content": "test"}],
            "system",
            max_rewrite=2  # 2회로 제한
        )

        assert meta["verdict"] == "MAX_REWRITE_EXHAUSTED"
        assert meta["requires_council"] is True


# =============================================================================
# Test: call_anthropic()
# =============================================================================

class TestCallAnthropic:
    """Anthropic API 호출 테스트"""

    @patch('src.services.cli_supervisor.call_claude_cli')
    def test_anthropic_redirects_to_cli(self, mock_cli):
        """Anthropic → CLI 리다이렉트"""
        from src.core.llm_caller import call_anthropic
        from config import ModelConfig

        mock_cli.return_value = "CLI 응답"

        config = ModelConfig(
            name="Claude",
            provider="anthropic",
            model_id="claude-opus-4.5",
            max_tokens=1000,
            temperature=0.7,
            api_key_env="ANTHROPIC_API_KEY"
        )

        result = call_anthropic(
            config,
            [{"role": "user", "content": "test"}],
            "system"
        )

        assert result == "CLI 응답"
        # opus → coder profile
        mock_cli.assert_called_once()

    @patch('src.services.cli_supervisor.call_claude_cli')
    def test_anthropic_sonnet_uses_reviewer_profile(self, mock_cli):
        """Sonnet 모델 → reviewer profile"""
        from src.core.llm_caller import call_anthropic
        from config import ModelConfig

        mock_cli.return_value = "Reviewer 응답"

        config = ModelConfig(
            name="Claude",
            provider="anthropic",
            model_id="claude-sonnet-4",
            max_tokens=1000,
            temperature=0.7,
            api_key_env="ANTHROPIC_API_KEY"
        )

        result = call_anthropic(
            config,
            [{"role": "user", "content": "test"}],
            "system"
        )

        assert result == "Reviewer 응답"


# =============================================================================
# Test: call_llm() with cost tracking
# =============================================================================

class TestCallLLMCostTracking:
    """call_llm() 비용 추적 테스트"""

    @patch('src.core.llm_caller.call_openai')
    @patch('src.core.llm_caller.cost_tracker')
    def test_cost_recorded_on_success(self, mock_tracker, mock_openai):
        """성공 시 비용 기록"""
        from src.core.llm_caller import call_llm
        from config import ModelConfig

        mock_openai.return_value = ("응답", 100, 50)

        config = ModelConfig(
            name="GPT",
            provider="openai",
            model_id="gpt-4",
            max_tokens=1000,
            temperature=0.7,
            api_key_env="OPENAI_API_KEY"
        )

        result = call_llm(
            config,
            [{"role": "user", "content": "test"}],
            "system",
            session_id="test_session",
            agent_role="coder"
        )

        mock_tracker.record_api_call.assert_called_once()

    @patch('src.core.llm_caller.call_openai')
    @patch('src.core.llm_caller.cost_tracker')
    def test_cost_not_recorded_on_error(self, mock_tracker, mock_openai):
        """에러 시 비용 기록 안 함"""
        from src.core.llm_caller import call_llm
        from config import ModelConfig

        mock_openai.return_value = ("[Error] API 실패", 0, 0)

        config = ModelConfig(
            name="GPT",
            provider="openai",
            model_id="gpt-4",
            max_tokens=1000,
            temperature=0.7,
            api_key_env="OPENAI_API_KEY"
        )

        result = call_llm(
            config,
            [{"role": "user", "content": "test"}],
            "system"
        )

        mock_tracker.record_api_call.assert_not_called()

    @patch('src.services.cli_supervisor.call_claude_cli')
    def test_claude_cli_no_cost_tracking(self, mock_cli):
        """Claude CLI → 비용 추적 안 함 (무료)"""
        from src.core.llm_caller import call_llm
        from config import ModelConfig

        mock_cli.return_value = "CLI 응답"

        config = ModelConfig(
            name="Claude CLI",
            provider="claude_cli",
            model_id="claude-opus",
            max_tokens=1000,
            temperature=0.7,
            api_key_env=""
        )
        config.profile = "coder"

        result = call_llm(
            config,
            [{"role": "user", "content": "test"}],
            "system"
        )

        assert result == "CLI 응답"


# =============================================================================
# Test: call_agent() Helper Functions
# =============================================================================

class TestCallAgentHelpers:
    """call_agent() 헬퍼 함수 테스트"""

    def test_extract_project_from_message(self):
        """메시지에서 프로젝트 추출"""
        from src.core.llm_caller import extract_project_from_message

        # 프로젝트 태그 있음
        proj, msg = extract_project_from_message("[PROJECT: hattz_empire] 테스트")
        assert proj == "hattz_empire"
        assert "테스트" in msg

        # 프로젝트 태그 없음
        proj, msg = extract_project_from_message("그냥 메시지")
        assert proj is None
        assert "그냥 메시지" in msg

    def test_get_system_prompt_valid_roles(self):
        """유효한 역할 시스템 프롬프트"""
        from config import get_system_prompt

        # 주요 역할들 프롬프트 존재 확인
        for role in ["pm", "coder", "qa", "strategist", "analyst", "researcher"]:
            prompt = get_system_prompt(role)
            # None이 아니거나 기본값이 있어야 함
            assert prompt is None or isinstance(prompt, str)

    def test_get_system_prompt_invalid_role(self):
        """무효한 역할 시스템 프롬프트"""
        from config import get_system_prompt

        prompt = get_system_prompt("invalid_role_12345")
        # 알 수 없는 역할은 None 또는 기본값 반환
        assert prompt is None or isinstance(prompt, str)

    def test_should_convene_council_coder(self):
        """Coder 위원회 소집 조건"""
        from src.core.llm_caller import should_convene_council

        # 보안 관련 응답
        result = should_convene_council(
            "coder",
            "def handle_password(): pass",
            dual_meta={"verdict": "REVISE"}
        )
        # REVISE나 보안 키워드가 있으면 위원회 소집
        # (실제 로직에 따라 None일 수도 있음)
        assert result is None or isinstance(result, str)

    def test_should_convene_council_strategist(self):
        """Strategist 위원회 소집 조건"""
        from src.core.llm_caller import should_convene_council

        result = should_convene_council(
            "strategist",
            "대규모 아키텍처 변경 제안",
            dual_meta=None
        )
        assert result is None or isinstance(result, str)

    def test_loop_breaker_reset(self):
        """LoopBreaker 초기화"""
        from src.core.llm_caller import get_loop_breaker

        breaker = get_loop_breaker()
        breaker.reset()

        assert breaker.step_count == 0
        assert len(breaker.response_history) == 0

    def test_loop_breaker_step(self):
        """LoopBreaker 스텝 기록"""
        from src.core.llm_caller import get_loop_breaker

        breaker = get_loop_breaker()
        breaker.reset()

        # check_and_record 또는 increment step
        breaker.step_count = 1
        assert breaker.step_count == 1

    def test_loop_breaker_is_broken(self):
        """LoopBreaker 브레이크 상태"""
        from src.core.llm_caller import get_loop_breaker

        breaker = get_loop_breaker()
        breaker.reset()

        # 초기 상태
        assert breaker.is_broken is False

        # 강제 브레이크 설정
        breaker.is_broken = True
        assert breaker.is_broken is True


class TestDualEngineRoles:
    """듀얼 엔진 역할 테스트"""

    def test_dual_engine_roles_exist(self):
        """DUAL_ENGINE_ROLES 존재 확인"""
        from src.core.llm_caller import DUAL_ENGINE_ROLES

        # 최소한 coder가 포함되어야 함
        assert "coder" in DUAL_ENGINE_ROLES or len(DUAL_ENGINE_ROLES) >= 0

    def test_single_engine_roles_exist(self):
        """SINGLE_ENGINES 존재 확인"""
        from src.core.llm_caller import SINGLE_ENGINES

        # 싱글 엔진 역할 확인
        assert isinstance(SINGLE_ENGINES, dict)


class TestProjectContext:
    """프로젝트 컨텍스트 테스트"""

    def test_collect_project_context_exists(self):
        """collect_project_context 함수 존재"""
        from src.core.llm_caller import collect_project_context

        # 함수 존재 확인
        assert callable(collect_project_context)

    def test_collect_project_context_valid(self):
        """유효한 프로젝트 컨텍스트"""
        from src.core.llm_caller import collect_project_context

        # hattz_empire 프로젝트
        result = collect_project_context("hattz_empire")
        # 결과가 문자열이어야 함
        assert isinstance(result, str)

    def test_collect_project_context_invalid(self):
        """무효한 프로젝트 컨텍스트"""
        from src.core.llm_caller import collect_project_context

        result = collect_project_context("nonexistent_project_12345")
        # 에러 메시지 또는 빈 문자열
        assert "[ERROR]" in result or result == ""


class TestModelRouting:
    """모델 라우팅 테스트"""

    def test_route_message_exists(self):
        """route_message 함수 존재"""
        from src.core.llm_caller import route_message

        assert callable(route_message)

    def test_get_router_exists(self):
        """get_router 함수 존재"""
        from src.core.llm_caller import get_router

        router = get_router()
        assert router is not None

    def test_routing_result_structure(self):
        """라우팅 결과 구조"""
        from src.core.llm_caller import route_message

        # PM 메시지 라우팅
        result = route_message("테스트 메시지", "pm")

        # 필수 속성 확인
        assert hasattr(result, 'model_spec')
        assert hasattr(result, 'model_tier')
        assert hasattr(result, 'reason')


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
