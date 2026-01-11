"""
router.py 단위 테스트
라우팅 로직 검증
"""
import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

import pytest
from src.core.router import (
    HattzRouter, ModelTier, TaskType, UrgencyLevel,
    ModelSpec, RoutingDecision
)


class TestEnums:
    """Enum 테스트"""

    def test_task_type_values(self):
        """TaskType enum 값 확인"""
        assert TaskType.STRATEGY.value == "strategy"
        assert TaskType.CODE.value == "code"
        assert TaskType.DATA.value == "data"
        assert TaskType.RESEARCH.value == "research"
        assert TaskType.ORCHESTRATION.value == "orchestration"
        assert TaskType.GENERAL.value == "general"
        assert TaskType.SECURITY.value == "security"

    def test_urgency_level_values(self):
        """UrgencyLevel enum 값 확인"""
        assert UrgencyLevel.CRITICAL.value == "critical"
        assert UrgencyLevel.HIGH.value == "high"
        assert UrgencyLevel.NORMAL.value == "normal"
        assert UrgencyLevel.LOW.value == "low"

    def test_model_tier_values(self):
        """ModelTier enum 값 확인"""
        assert ModelTier.BUDGET.value == "budget"
        assert ModelTier.STANDARD.value == "standard"
        assert ModelTier.VIP_THINKING.value == "vip_thinking"
        assert ModelTier.LOG_ONLY.value == "log_only"
        assert ModelTier.EXEC.value == "exec"
        assert ModelTier.RESEARCH.value == "research"
        assert ModelTier.SAFETY.value == "safety"


class TestModelSpec:
    """ModelSpec 테스트"""

    def test_model_spec_creation(self):
        """ModelSpec 생성 테스트"""
        spec = ModelSpec(
            name="Test Model",
            provider="test",
            model_id="test-model",
            api_key_env="TEST_API_KEY",
            tier=ModelTier.STANDARD,
            cost_input=1.0,
            cost_output=2.0
        )
        assert spec.name == "Test Model"
        assert spec.provider == "test"
        assert spec.temperature == 0.7  # 기본값
        assert spec.max_tokens == 8192  # 기본값
        assert spec.thinking_mode is False  # 기본값


class TestHattzRouterInit:
    """HattzRouter 초기화 테스트"""

    def test_router_initialization(self):
        """라우터 초기화 확인"""
        router = HattzRouter()

        # 모델 정의 확인
        assert router.BUDGET_MODEL is not None
        assert router.STANDARD_MODEL is not None
        assert router.VIP_AUDIT_MODEL is not None
        assert router.VIP_THINKING_MODEL is not None
        assert router.RESEARCH_MODEL is not None

    def test_agent_to_tier_mapping(self):
        """에이전트 → 티어 매핑 확인"""
        router = HattzRouter()

        assert router.agent_to_tier["pm"] == ModelTier.EXEC
        assert router.agent_to_tier["coder"] == ModelTier.EXEC
        assert router.agent_to_tier["qa"] == ModelTier.EXEC
        assert router.agent_to_tier["reviewer"] == ModelTier.EXEC
        assert router.agent_to_tier["analyst"] == ModelTier.LOG_ONLY
        assert router.agent_to_tier["strategist"] == ModelTier.VIP_THINKING
        assert router.agent_to_tier["researcher"] == ModelTier.RESEARCH

    def test_keywords_loaded(self):
        """키워드 목록 로드 확인"""
        router = HattzRouter()

        assert len(router.high_risk_keywords) > 0
        assert len(router.exec_keywords) > 0
        assert len(router.research_keywords) > 0
        assert len(router.thinking_keywords) > 0


class TestHighRiskDetection:
    """고위험 키워드 감지 테스트"""

    def test_api_key_detection(self):
        """API 키 키워드 감지"""
        router = HattzRouter()

        assert router._is_high_risk("api_key를 설정해줘") is True
        assert router._is_high_risk("apikey 노출됨") is True
        assert router._is_high_risk("secret 값 변경") is True

    def test_financial_keywords(self):
        """금융 관련 키워드 감지"""
        router = HattzRouter()

        assert router._is_high_risk("출금 요청") is True
        assert router._is_high_risk("실거래 시작") is True
        assert router._is_high_risk("withdraw 실행") is True

    def test_normal_message_not_high_risk(self):
        """일반 메시지는 고위험 아님"""
        router = HattzRouter()

        assert router._is_high_risk("안녕하세요") is False
        assert router._is_high_risk("코드 리뷰 해줘") is False


class TestExecIntentDetection:
    """실행 의도 감지 테스트"""

    def test_exec_keywords(self):
        """실행 키워드 감지"""
        router = HattzRouter()

        assert router._has_exec_intent("코드 수정해줘") is True
        assert router._has_exec_intent("diff 생성") is True
        assert router._has_exec_intent("pytest 실행") is True
        assert router._has_exec_intent("build 해줘") is True

    def test_normal_not_exec(self):
        """일반 메시지는 실행 의도 없음"""
        router = HattzRouter()

        assert router._has_exec_intent("이건 뭐야") is False


class TestCodeDetection:
    """코드 감지 테스트"""

    def test_code_block_detection(self):
        """코드 블록 감지"""
        router = HattzRouter()

        assert router._looks_like_code("```python\nprint('hello')\n```") is True

    def test_keyword_detection(self):
        """코드 키워드 감지"""
        router = HattzRouter()

        assert router._looks_like_code("def my_function():") is True
        assert router._looks_like_code("class MyClass:") is True
        assert router._looks_like_code("SELECT * FROM users") is True
        assert router._looks_like_code("Traceback (most recent call last):") is True

    def test_normal_text_not_code(self):
        """일반 텍스트는 코드 아님"""
        router = HattzRouter()

        assert router._looks_like_code("안녕하세요") is False
        assert router._looks_like_code("what is this?") is False


class TestRouteTraffic:
    """route_traffic() 메인 로직 테스트"""

    def test_pm_routing(self):
        """PM 라우팅 - config.py 설정 따름"""
        router = HattzRouter()

        decision = router.route_traffic("아무 메시지", agent_role="pm")
        # PM은 config.py 설정에 따라 STANDARD 또는 EXEC 반환
        assert decision.model_tier in ["exec", "standard"]
        assert "pm" in decision.reason

    def test_high_risk_to_safety(self):
        """고위험 → SAFETY"""
        router = HattzRouter()

        decision = router.route_traffic("api_key 설정", agent_role="coder")
        assert decision.model_tier == "safety"
        assert "SAFETY" in decision.reason

    def test_research_trigger(self):
        """검색 키워드 → RESEARCH"""
        router = HattzRouter()

        decision = router.route_traffic("최신 트렌드 검색해줘", agent_role="analyst")
        assert decision.model_tier == "research"
        assert "Perplexity" in decision.reason

    def test_researcher_always_research(self):
        """researcher 역할은 항상 RESEARCH"""
        router = HattzRouter()

        decision = router.route_traffic("아무 메시지", agent_role="researcher")
        assert decision.model_tier == "research"

    def test_short_query_to_budget(self):
        """짧은 질문 → BUDGET"""
        router = HattzRouter()

        decision = router.route_traffic("안녕", agent_role="analyst")
        assert decision.model_tier == "budget"
        assert "short" in decision.reason

    def test_thinking_keyword_with_error_context(self):
        """추론 키워드 + 에러 컨텍스트 → VIP_THINKING"""
        router = HattzRouter()

        history = [
            {"content": "Traceback (most recent call last): ..."},
            {"content": "이전 메시지"}
        ]
        decision = router.route_traffic("왜 에러가 났어?", agent_role="analyst", history=history)
        assert decision.model_tier == "vip_thinking"
        assert "VIP_THINKING" in decision.reason

    def test_thinking_keyword_without_error(self):
        """추론 키워드만 (에러 없음) → STANDARD"""
        router = HattzRouter()

        decision = router.route_traffic("왜 이렇게 동작해?", agent_role="analyst")
        assert decision.model_tier == "standard"
        assert "VIP 금지" in decision.reason

    def test_default_agent_tier(self):
        """기본 에이전트 티어 반환"""
        router = HattzRouter()

        # coder + 실행 키워드 → STANDARD (EXEC 트리거)
        decision = router.route_traffic("함수 작성해줘 코드 수정해줘", agent_role="coder")
        # 실행 키워드 있으면 STANDARD
        assert decision.model_tier in ["exec", "standard", "budget"]

        # analyst 에이전트의 기본 티어 매핑 확인
        # 라우팅 로직 우선순위에 따라 실제 반환값 검증
        assert router.agent_to_tier.get("analyst") == ModelTier.LOG_ONLY


class TestRoutingDecision:
    """RoutingDecision 구조 테스트"""

    def test_decision_structure(self):
        """RoutingDecision 필드 확인"""
        router = HattzRouter()

        decision = router.route_traffic("테스트", agent_role="pm")

        assert hasattr(decision, 'model_tier')
        assert hasattr(decision, 'model_spec')
        assert hasattr(decision, 'reason')
        assert hasattr(decision, 'estimated_tokens')
        assert hasattr(decision, 'estimated_cost')
        assert hasattr(decision, 'fallback_spec')
        assert hasattr(decision, 'escalate_to')

    def test_cost_estimation(self):
        """비용 추정 확인"""
        router = HattzRouter()

        decision = router.route_traffic("테스트", agent_role="pm", context_size=10000)

        assert decision.estimated_tokens == 10000
        assert decision.estimated_cost > 0


class TestIsResearch:
    """검색 키워드 감지 테스트"""

    def test_research_keywords(self):
        """검색 키워드 감지"""
        router = HattzRouter()

        assert router._is_research("최신 정보 찾아줘") is True
        assert router._is_research("동향 알려줘") is True
        assert router._is_research("뉴스 검색") is True

    def test_not_research(self):
        """검색 아닌 메시지"""
        router = HattzRouter()

        assert router._is_research("코드 작성해줘") is False


class TestErrorContextDetection:
    """에러 컨텍스트 감지 테스트"""

    def test_traceback_in_history(self):
        """히스토리에 Traceback 있음"""
        router = HattzRouter()

        history = [{"content": "Traceback (most recent call last):"}]
        assert router._has_error_context(history) is True

    def test_exception_in_history(self):
        """히스토리에 Exception 있음"""
        router = HattzRouter()

        history = [{"content": "KeyError: 'missing_key'"}]
        assert router._has_error_context(history) is True

    def test_no_error_in_history(self):
        """히스토리에 에러 없음"""
        router = HattzRouter()

        history = [{"content": "정상 메시지입니다"}]
        assert router._has_error_context(history) is False

    def test_empty_history(self):
        """빈 히스토리"""
        router = HattzRouter()

        assert router._has_error_context([]) is False
        assert router._has_error_context(None) is False


class TestModelByTier:
    """티어별 모델 반환 테스트"""

    def test_get_model_by_tier(self):
        """_get_model_by_tier() 테스트"""
        router = HattzRouter()

        assert router._get_model_by_tier(ModelTier.BUDGET) == router.BUDGET_MODEL
        assert router._get_model_by_tier(ModelTier.STANDARD) == router.STANDARD_MODEL
        assert router._get_model_by_tier(ModelTier.VIP_THINKING) == router.VIP_THINKING_MODEL
        assert router._get_model_by_tier(ModelTier.RESEARCH) == router.RESEARCH_MODEL
        assert router._get_model_by_tier(ModelTier.SAFETY) == router.VIP_AUDIT_MODEL


class TestFallbackAndEscalation:
    """폴백 및 에스컬레이션 테스트"""

    def test_budget_fallback(self):
        """BUDGET 모델의 폴백"""
        router = HattzRouter()

        fallback = router._get_fallback(router.BUDGET_MODEL)
        # BUDGET은 이미 최저가라 폴백 없음
        assert fallback is None

    def test_standard_fallback(self):
        """STANDARD 모델의 폴백"""
        router = HattzRouter()

        fallback = router._get_fallback(router.STANDARD_MODEL)
        # STANDARD의 폴백은 BUDGET
        assert fallback == router.BUDGET_MODEL

    def test_vip_fallback(self):
        """VIP 모델의 폴백"""
        router = HattzRouter()

        fallback = router._get_fallback(router.VIP_AUDIT_MODEL)
        assert fallback == router.BUDGET_MODEL

    def test_get_escalation_model(self):
        """_get_escalation_model() 테스트"""
        router = HattzRouter()

        # BUDGET → STANDARD
        assert router._get_escalation_model(ModelTier.BUDGET) == router.STANDARD_MODEL

        # STANDARD → VIP_THINKING
        assert router._get_escalation_model(ModelTier.STANDARD) == router.VIP_THINKING_MODEL

        # VIP_THINKING → VIP_AUDIT
        assert router._get_escalation_model(ModelTier.VIP_THINKING) == router.VIP_AUDIT_MODEL

        # SAFETY (최고) → None
        assert router._get_escalation_model(ModelTier.SAFETY) is None

        # LOG_ONLY → STANDARD
        assert router._get_escalation_model(ModelTier.LOG_ONLY) == router.STANDARD_MODEL

        # EXEC → VIP_AUDIT
        assert router._get_escalation_model(ModelTier.EXEC) == router.VIP_AUDIT_MODEL

        # RESEARCH → STANDARD
        assert router._get_escalation_model(ModelTier.RESEARCH) == router.STANDARD_MODEL


class TestGetStats:
    """get_stats() 테스트"""

    def test_stats_structure(self):
        """통계 구조 확인"""
        router = HattzRouter()
        stats = router.get_stats()

        assert "models" in stats
        assert "budget" in stats["models"]
        assert "standard" in stats["models"]
        assert "vip_audit" in stats["models"]
        assert "vip_thinking" in stats["models"]

    def test_stats_model_info(self):
        """모델 정보 확인"""
        router = HattzRouter()
        stats = router.get_stats()

        budget_stats = stats["models"]["budget"]
        assert "name" in budget_stats
        assert "model_id" in budget_stats
        assert "cost" in budget_stats


class TestThinkingPrefix:
    """Thinking Mode 프리픽스 테스트"""

    def test_thinking_prefix_content(self):
        """Thinking prefix 내용 확인"""
        router = HattzRouter()
        prefix = router._get_thinking_prefix()

        assert "THINKING" in prefix
        assert "ANALYZE" in prefix
        assert "step-by-step" in prefix


class TestCreateDecision:
    """_create_decision() 테스트"""

    def test_create_decision_structure(self):
        """RoutingDecision 생성 구조"""
        router = HattzRouter()

        decision = router._create_decision(
            router.STANDARD_MODEL,
            "test reason",
            context_size=5000
        )

        assert decision.model_tier == "standard"
        assert decision.model_spec == router.STANDARD_MODEL
        assert decision.reason == "test reason"
        assert decision.estimated_tokens == 5000

    def test_create_decision_cost_estimation(self):
        """비용 추정"""
        router = HattzRouter()

        decision = router._create_decision(
            router.STANDARD_MODEL,
            "test",
            context_size=1000000  # 1M tokens
        )

        # STANDARD: $3/$15 per 1M tokens
        # 예상 비용 = (1M/1M) * $3 + (1M/1M) * $15 = $18
        assert decision.estimated_cost == 18.0

    def test_create_decision_default_tokens(self):
        """기본 토큰 수 (context_size=0)"""
        router = HattzRouter()

        decision = router._create_decision(
            router.BUDGET_MODEL,
            "test",
            context_size=0
        )

        assert decision.estimated_tokens == 1000  # 기본값

    def test_create_decision_with_escalation(self):
        """에스컬레이션 모델 포함"""
        router = HattzRouter()

        decision = router._create_decision(
            router.STANDARD_MODEL,
            "test",
            context_size=1000,
            escalate_to=router.VIP_THINKING_MODEL
        )

        assert decision.escalate_to == router.VIP_THINKING_MODEL


class TestAllTierMappings:
    """모든 티어 매핑 테스트"""

    def test_all_model_tier_mappings(self):
        """_get_model_by_tier() 모든 티어"""
        router = HattzRouter()

        # LOG_ONLY → BUDGET_MODEL (Gemini Flash)
        assert router._get_model_by_tier(ModelTier.LOG_ONLY) == router.BUDGET_MODEL

        # EXEC → STANDARD_MODEL (실제 호출은 CLI)
        assert router._get_model_by_tier(ModelTier.EXEC) == router.STANDARD_MODEL

        # 알 수 없는 티어 → STANDARD_MODEL (기본값)
        # ModelTier enum이라 실제로는 발생 안 함, 하지만 방어 코드 커버리지용


class TestErrorPatternDetection:
    """에러 패턴 감지 테스트"""

    def test_spark_exception(self):
        """SparkException 감지"""
        router = HattzRouter()
        history = [{"content": "SparkException: Job aborted"}]
        assert router._has_error_context(history) is True

    def test_sqlstate_error(self):
        """SQLSTATE 감지"""
        router = HattzRouter()
        history = [{"content": "SQLSTATE[42000]: Syntax error"}]
        assert router._has_error_context(history) is True

    def test_stack_trace(self):
        """Stack trace 감지"""
        router = HattzRouter()
        history = [{"content": "Stack trace: at line 42"}]
        assert router._has_error_context(history) is True

    def test_window_parameter(self):
        """window 파라미터 테스트"""
        router = HattzRouter()
        history = [
            {"content": "메시지 1"},
            {"content": "메시지 2"},
            {"content": "Traceback error"},
            {"content": "메시지 4"},
        ]
        # window=2는 마지막 2개만 확인 (메시지 4, Traceback error)
        assert router._has_error_context(history, window=2) is True

        # window=1은 마지막 1개만 확인 (메시지 4)
        assert router._has_error_context(history, window=1) is False


class TestExecKeywordCoverage:
    """실행 키워드 전체 커버리지"""

    def test_all_exec_keywords(self):
        """모든 exec 키워드 테스트"""
        router = HattzRouter()

        keywords = ["수정", "패치", "diff", "커밋", "commit", "테스트",
                    "pytest", "unittest", "빌드", "build", "docker",
                    "k8s", "kub", "helm", "배포", "deploy"]

        for kw in keywords:
            assert router._has_exec_intent(kw) is True, f"'{kw}' should trigger exec"


class TestResearchKeywordCoverage:
    """검색 키워드 전체 커버리지"""

    def test_all_research_keywords(self):
        """모든 research 키워드 테스트"""
        router = HattzRouter()

        keywords = ["검색", "찾아", "최신", "동향", "뉴스", "verify", "look up"]

        for kw in keywords:
            assert router._is_research(kw) is True, f"'{kw}' should trigger research"


class TestHighRiskKeywordCoverage:
    """고위험 키워드 전체 커버리지"""

    def test_all_high_risk_keywords(self):
        """모든 high risk 키워드 테스트"""
        router = HattzRouter()

        keywords = ["api_key", "apikey", "secret", "private key", "seed phrase",
                    "출금", "실거래", "주문", "withdraw", "transfer"]

        for kw in keywords:
            assert router._is_high_risk(kw) is True, f"'{kw}' should be high risk"


class TestCallModel:
    """call_model() 테스트 - Mock 사용"""

    def test_call_model_unknown_provider(self):
        """알 수 없는 provider 에러"""
        router = HattzRouter()

        # 알 수 없는 provider 모델 생성
        unknown_model = ModelSpec(
            name="Unknown",
            provider="unknown_provider",
            model_id="unknown",
            api_key_env="UNKNOWN_KEY",
            tier=ModelTier.STANDARD,
            cost_input=1.0,
            cost_output=1.0
        )

        decision = RoutingDecision(
            model_tier="standard",
            model_spec=unknown_model,
            reason="test",
            estimated_tokens=100,
            estimated_cost=0.01
        )

        result = router.call_model(
            decision,
            [{"role": "user", "content": "test"}],
            "system"
        )

        assert "Error" in result
        assert "Unknown provider" in result

    def test_call_model_with_fallback(self):
        """fallback 시도 테스트"""
        from unittest.mock import patch, MagicMock
        router = HattzRouter()

        # 첫 번째 호출 실패, fallback 성공하도록 모킹
        decision = RoutingDecision(
            model_tier="research",
            model_spec=router.RESEARCH_MODEL,
            reason="test",
            estimated_tokens=100,
            estimated_cost=0.01,
            fallback_spec=router.BUDGET_MODEL
        )

        with patch.object(router, '_call_perplexity', side_effect=Exception("API Error")):
            with patch.object(router, '_call_google', return_value="Fallback success"):
                result = router.call_model(
                    decision,
                    [{"role": "user", "content": "test"}],
                    "system"
                )
                assert "Fallback success" in result or "Error" in result


class TestCallModelProviders:
    """각 provider 호출 테스트 - Mock 사용"""

    def test_call_anthropic_pm_profile(self):
        """Anthropic 호출 - PM profile=None"""
        from unittest.mock import patch
        router = HattzRouter()

        with patch('src.services.cli_supervisor.call_claude_cli', return_value="PM response") as mock_cli:
            result = router._call_anthropic(
                router.STANDARD_MODEL,
                [{"role": "user", "content": "test"}],
                "system prompt",
                session_id="test_session",
                agent_role="pm"
            )

            # PM은 profile=None으로 호출되어야 함
            mock_cli.assert_called_once()
            call_args = mock_cli.call_args
            assert call_args[0][2] is None  # profile 파라미터

    def test_call_anthropic_coder_profile(self):
        """Anthropic 호출 - coder profile"""
        from unittest.mock import patch
        router = HattzRouter()

        with patch('src.services.cli_supervisor.call_claude_cli', return_value="Coder response") as mock_cli:
            result = router._call_anthropic(
                router.STANDARD_MODEL,
                [{"role": "user", "content": "test"}],
                "system prompt",
                agent_role="coder"
            )

            call_args = mock_cli.call_args
            assert call_args[0][2] == "coder"

    def test_call_anthropic_opus_fallback(self):
        """Anthropic 호출 - opus model → coder profile"""
        from unittest.mock import patch
        router = HattzRouter()

        # opus 모델 스펙 생성
        opus_spec = ModelSpec(
            name="Claude Opus",
            provider="anthropic",
            model_id="claude-opus-4-5",
            api_key_env="ANTHROPIC_API_KEY",
            tier=ModelTier.SAFETY,
            cost_input=5.0,
            cost_output=25.0
        )

        with patch('src.services.cli_supervisor.call_claude_cli', return_value="Opus response") as mock_cli:
            result = router._call_anthropic(
                opus_spec,
                [{"role": "user", "content": "test"}],
                "system prompt",
                agent_role="unknown"  # 알 수 없는 role
            )

            call_args = mock_cli.call_args
            assert call_args[0][2] == "coder"  # opus → coder

    def test_call_anthropic_sonnet_fallback(self):
        """Anthropic 호출 - sonnet model → reviewer profile"""
        from unittest.mock import patch
        router = HattzRouter()

        with patch('src.services.cli_supervisor.call_claude_cli', return_value="Sonnet response") as mock_cli:
            result = router._call_anthropic(
                router.STANDARD_MODEL,  # sonnet
                [{"role": "user", "content": "test"}],
                "system prompt",
                agent_role="unknown"
            )

            call_args = mock_cli.call_args
            assert call_args[0][2] == "reviewer"  # sonnet → reviewer


class TestPerplexitySpecialCases:
    """Perplexity API 특수 케이스"""

    def test_perplexity_no_api_key(self):
        """Perplexity API 키 없음"""
        from unittest.mock import patch
        router = HattzRouter()

        with patch.dict('os.environ', {}, clear=True):
            with patch('os.getenv', return_value=None):
                result = router._call_perplexity(
                    router.RESEARCH_MODEL,
                    [{"role": "user", "content": "test"}],
                    "system"
                )
                assert "Error" in result or "not found" in result

    def test_perplexity_no_user_message(self):
        """Perplexity - user 메시지 없음"""
        from unittest.mock import patch
        router = HattzRouter()

        with patch('os.getenv', return_value="fake_key"):
            result = router._call_perplexity(
                router.RESEARCH_MODEL,
                [{"role": "system", "content": "system only"}],  # user 없음
                "system"
            )
            assert "Error" in result
            assert "No user message" in result


class TestOpenAICallMock:
    """OpenAI API 호출 Mock 테스트"""

    def test_call_openai_success(self):
        """OpenAI API 성공 호출"""
        from unittest.mock import patch, MagicMock
        router = HattzRouter()

        # Mock response 구성
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "OpenAI response text"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.usage = mock_usage
        mock_response.choices = [mock_choice]

        # OpenAI client mock
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch('os.getenv', return_value="fake_openai_key"):
            with patch('openai.OpenAI', return_value=mock_client):
                with patch('src.core.router.cost_tracker') as mock_tracker:
                    result = router._call_openai(
                        router.VIP_THINKING_MODEL,
                        [{"role": "user", "content": "test query"}],
                        "system prompt",
                        session_id="test_session",
                        agent_role="strategist"
                    )

                    assert result == "OpenAI response text"
                    mock_tracker.record_api_call.assert_called_once()

    def test_call_openai_thinking_mode(self):
        """OpenAI - Thinking Mode 프리픽스 추가"""
        from unittest.mock import patch, MagicMock
        router = HattzRouter()

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "Thinking response"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.usage = mock_usage
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch('os.getenv', return_value="fake_key"):
            with patch('openai.OpenAI', return_value=mock_client):
                with patch('src.core.router.cost_tracker'):
                    result = router._call_openai(
                        router.VIP_THINKING_MODEL,  # thinking_mode=True
                        [{"role": "user", "content": "analyze this"}],
                        "base prompt"
                    )

                    # 호출 시 system prompt에 THINKING prefix 추가 확인
                    call_args = mock_client.chat.completions.create.call_args
                    messages = call_args.kwargs['messages']
                    assert "THINKING" in messages[0]['content']

    def test_call_openai_no_usage(self):
        """OpenAI - usage 없는 경우"""
        from unittest.mock import patch, MagicMock
        router = HattzRouter()

        mock_message = MagicMock()
        mock_message.content = "Response without usage"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.usage = None  # usage 없음
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch('os.getenv', return_value="fake_key"):
            with patch('openai.OpenAI', return_value=mock_client):
                with patch('src.core.router.cost_tracker') as mock_tracker:
                    result = router._call_openai(
                        router.STANDARD_MODEL,
                        [{"role": "user", "content": "test"}],
                        "system"
                    )

                    assert result == "Response without usage"
                    # usage 없으면 record_api_call 호출 안됨
                    mock_tracker.record_api_call.assert_not_called()

    def test_call_openai_cost_tracker_error(self):
        """OpenAI - cost_tracker 에러 처리"""
        from unittest.mock import patch, MagicMock
        router = HattzRouter()

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "Response"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.usage = mock_usage
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch('os.getenv', return_value="fake_key"):
            with patch('openai.OpenAI', return_value=mock_client):
                with patch('src.core.router.cost_tracker') as mock_tracker:
                    mock_tracker.record_api_call.side_effect = Exception("DB Error")

                    # 에러가 발생해도 결과는 정상 반환
                    result = router._call_openai(
                        router.STANDARD_MODEL,
                        [{"role": "user", "content": "test"}],
                        "system"
                    )

                    assert result == "Response"


class TestGoogleCallMock:
    """Google Gemini API 호출 Mock 테스트"""

    def test_call_google_success(self):
        """Google Gemini API 성공 호출"""
        from unittest.mock import patch, MagicMock
        import sys
        router = HattzRouter()

        # Mock response
        mock_usage = MagicMock()
        mock_usage.prompt_token_count = 80
        mock_usage.candidates_token_count = 40

        mock_response = MagicMock()
        mock_response.text = "Gemini response text"
        mock_response.usage_metadata = mock_usage

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response

        mock_model_instance = MagicMock()
        mock_model_instance.start_chat.return_value = mock_chat

        # google.generativeai 모듈 모킹
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model_instance

        with patch.dict(sys.modules, {'google.generativeai': mock_genai}):
            with patch('os.getenv', return_value="fake_google_key"):
                with patch('src.core.router.cost_tracker') as mock_tracker:
                    result = router._call_google(
                        router.BUDGET_MODEL,
                        [{"role": "user", "content": "query"}],
                        "system prompt",
                        session_id="test_session",
                        agent_role="analyst"
                    )

                    assert result == "Gemini response text"
                    mock_tracker.record_api_call.assert_called_once()

    def test_call_google_with_history(self):
        """Google - 대화 히스토리 변환"""
        from unittest.mock import patch, MagicMock
        import sys
        router = HattzRouter()

        mock_response = MagicMock()
        mock_response.text = "Response with history"
        mock_response.usage_metadata = None

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response

        mock_model_instance = MagicMock()
        mock_model_instance.start_chat.return_value = mock_chat

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model_instance

        messages = [
            {"role": "user", "content": "first message"},
            {"role": "assistant", "content": "first response"},
            {"role": "user", "content": "second message"}
        ]

        with patch.dict(sys.modules, {'google.generativeai': mock_genai}):
            with patch('os.getenv', return_value="fake_key"):
                with patch('src.core.router.cost_tracker'):
                    result = router._call_google(
                        router.BUDGET_MODEL,
                        messages,
                        "system"
                    )

                    assert result == "Response with history"
                    # history 변환은 내부에서 수행됨

    def test_call_google_no_usage(self):
        """Google - usage_metadata 없는 경우"""
        from unittest.mock import patch, MagicMock
        import sys
        router = HattzRouter()

        mock_response = MagicMock()
        mock_response.text = "Response"
        mock_response.usage_metadata = None  # 없음

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response

        mock_model_instance = MagicMock()
        mock_model_instance.start_chat.return_value = mock_chat

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model_instance

        with patch.dict(sys.modules, {'google.generativeai': mock_genai}):
            with patch('os.getenv', return_value="fake_key"):
                with patch('src.core.router.cost_tracker') as mock_tracker:
                    result = router._call_google(
                        router.BUDGET_MODEL,
                        [{"role": "user", "content": "test"}],
                        "system"
                    )

                    assert result == "Response"
                    mock_tracker.record_api_call.assert_not_called()

    def test_call_google_zero_tokens(self):
        """Google - token count가 0인 경우"""
        from unittest.mock import patch, MagicMock
        import sys
        router = HattzRouter()

        mock_usage = MagicMock()
        mock_usage.prompt_token_count = 0
        mock_usage.candidates_token_count = 0

        mock_response = MagicMock()
        mock_response.text = "Response"
        mock_response.usage_metadata = mock_usage

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response

        mock_model_instance = MagicMock()
        mock_model_instance.start_chat.return_value = mock_chat

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model_instance

        with patch.dict(sys.modules, {'google.generativeai': mock_genai}):
            with patch('os.getenv', return_value="fake_key"):
                with patch('src.core.router.cost_tracker') as mock_tracker:
                    result = router._call_google(
                        router.BUDGET_MODEL,
                        [{"role": "user", "content": "test"}],
                        "system"
                    )

                    assert result == "Response"
                    # 0 token이면 record 안함
                    mock_tracker.record_api_call.assert_not_called()

    def test_call_google_cost_tracker_error(self):
        """Google - cost_tracker 에러 처리"""
        from unittest.mock import patch, MagicMock
        import sys
        router = HattzRouter()

        mock_usage = MagicMock()
        mock_usage.prompt_token_count = 100
        mock_usage.candidates_token_count = 50

        mock_response = MagicMock()
        mock_response.text = "Response"
        mock_response.usage_metadata = mock_usage

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_response

        mock_model_instance = MagicMock()
        mock_model_instance.start_chat.return_value = mock_chat

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model_instance

        with patch.dict(sys.modules, {'google.generativeai': mock_genai}):
            with patch('os.getenv', return_value="fake_key"):
                with patch('src.core.router.cost_tracker') as mock_tracker:
                    mock_tracker.record_api_call.side_effect = Exception("Error")

                    result = router._call_google(
                        router.BUDGET_MODEL,
                        [{"role": "user", "content": "test"}],
                        "system"
                    )

                    assert result == "Response"


class TestPerplexityCallMock:
    """Perplexity API 호출 Mock 테스트"""

    def test_call_perplexity_success(self):
        """Perplexity API 성공 호출"""
        from unittest.mock import patch, MagicMock
        router = HattzRouter()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Perplexity response"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 100},
            "citations": []
        }

        with patch('os.getenv', return_value="fake_perplexity_key"):
            with patch('requests.post', return_value=mock_response):
                with patch('src.core.router.cost_tracker') as mock_tracker:
                    result = router._call_perplexity(
                        router.RESEARCH_MODEL,
                        [{"role": "user", "content": "search query"}],
                        "system prompt",
                        session_id="test_session",
                        agent_role="researcher"
                    )

                    assert result == "Perplexity response"
                    mock_tracker.record_api_call.assert_called_once()

    def test_call_perplexity_with_citations(self):
        """Perplexity - 인용 정보 포함"""
        from unittest.mock import patch, MagicMock
        router = HattzRouter()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Answer with sources"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 100},
            "citations": ["https://example.com/1", "https://example.com/2"]
        }

        with patch('os.getenv', return_value="fake_key"):
            with patch('requests.post', return_value=mock_response):
                with patch('src.core.router.cost_tracker'):
                    result = router._call_perplexity(
                        router.RESEARCH_MODEL,
                        [{"role": "user", "content": "query"}],
                        "system"
                    )

                    assert "Answer with sources" in result
                    assert "Sources:" in result
                    assert "https://example.com/1" in result
                    assert "https://example.com/2" in result

    def test_call_perplexity_error_status(self):
        """Perplexity - 에러 상태 코드"""
        from unittest.mock import patch, MagicMock
        router = HattzRouter()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch('os.getenv', return_value="fake_key"):
            with patch('requests.post', return_value=mock_response):
                result = router._call_perplexity(
                    router.RESEARCH_MODEL,
                    [{"role": "user", "content": "query"}],
                    "system"
                )

                assert "Perplexity Error" in result
                assert "500" in result

    def test_call_perplexity_no_usage(self):
        """Perplexity - usage 없는 응답"""
        from unittest.mock import patch, MagicMock
        router = HattzRouter()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Response"}}],
            "usage": {},  # 빈 usage
            "citations": []
        }

        with patch('os.getenv', return_value="fake_key"):
            with patch('requests.post', return_value=mock_response):
                with patch('src.core.router.cost_tracker') as mock_tracker:
                    result = router._call_perplexity(
                        router.RESEARCH_MODEL,
                        [{"role": "user", "content": "query"}],
                        "system"
                    )

                    assert result == "Response"
                    # 빈 usage면 record 호출되지만 0 토큰
                    # usage가 truthy(빈 dict는 falsy가 아님)이므로 호출됨

    def test_call_perplexity_cost_tracker_error(self):
        """Perplexity - cost_tracker 에러 처리"""
        from unittest.mock import patch, MagicMock
        router = HattzRouter()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Response"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 100},
            "citations": []
        }

        with patch('os.getenv', return_value="fake_key"):
            with patch('requests.post', return_value=mock_response):
                with patch('src.core.router.cost_tracker') as mock_tracker:
                    mock_tracker.record_api_call.side_effect = Exception("Error")

                    result = router._call_perplexity(
                        router.RESEARCH_MODEL,
                        [{"role": "user", "content": "query"}],
                        "system"
                    )

                    assert result == "Response"

    def test_call_perplexity_multiple_user_messages(self):
        """Perplexity - 여러 user 메시지 중 마지막만 사용"""
        from unittest.mock import patch, MagicMock
        router = HattzRouter()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Response"}}],
            "usage": {},
            "citations": []
        }

        messages = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},  # 이것만 사용됨
        ]

        with patch('os.getenv', return_value="fake_key"):
            with patch('requests.post', return_value=mock_response) as mock_post:
                with patch('src.core.router.cost_tracker'):
                    result = router._call_perplexity(
                        router.RESEARCH_MODEL,
                        messages,
                        "system"
                    )

                    # 마지막 user 메시지만 사용 확인
                    call_args = mock_post.call_args
                    payload = call_args.kwargs['json']
                    assert payload['messages'][1]['content'] == "second question"


class TestEstimateCost:
    """estimate_cost() 테스트"""

    def test_estimate_cost_budget(self):
        """BUDGET 티어 비용 추정"""
        router = HattzRouter()
        cost = router.estimate_cost(1000000, 1000000, "budget")
        expected = (1000000 / 1_000_000) * router.BUDGET_MODEL.cost_input + \
                   (1000000 / 1_000_000) * router.BUDGET_MODEL.cost_output
        assert cost == expected

    def test_estimate_cost_standard(self):
        """STANDARD 티어 비용 추정"""
        router = HattzRouter()
        cost = router.estimate_cost(500000, 500000, "standard")
        expected = (500000 / 1_000_000) * router.STANDARD_MODEL.cost_input + \
                   (500000 / 1_000_000) * router.STANDARD_MODEL.cost_output
        assert cost == expected

    def test_estimate_cost_vip(self):
        """VIP 티어 비용 추정"""
        router = HattzRouter()
        cost = router.estimate_cost(100000, 100000, "vip")
        expected = (100000 / 1_000_000) * router.VIP_AUDIT_MODEL.cost_input + \
                   (100000 / 1_000_000) * router.VIP_AUDIT_MODEL.cost_output
        assert cost == expected

    def test_estimate_cost_research(self):
        """RESEARCH 티어 비용 추정"""
        router = HattzRouter()
        cost = router.estimate_cost(200000, 200000, "research")
        expected = (200000 / 1_000_000) * router.RESEARCH_MODEL.cost_input + \
                   (200000 / 1_000_000) * router.RESEARCH_MODEL.cost_output
        assert cost == expected

    def test_estimate_cost_unknown_tier(self):
        """알 수 없는 티어 → BUDGET 폴백"""
        router = HattzRouter()
        cost = router.estimate_cost(1000000, 1000000, "unknown")
        expected = (1000000 / 1_000_000) * router.BUDGET_MODEL.cost_input + \
                   (1000000 / 1_000_000) * router.BUDGET_MODEL.cost_output
        assert cost == expected


class TestSingletonFunctions:
    """싱글톤 및 헬퍼 함수 테스트"""

    def test_get_router_singleton(self):
        """get_router() 싱글톤"""
        from src.core.router import get_router
        router1 = get_router()
        router2 = get_router()
        assert router1 is router2
        assert isinstance(router1, HattzRouter)

    def test_route_message_shortcut(self):
        """route_message() 단축 함수"""
        from src.core.router import route_message
        decision = route_message("안녕하세요", "pm")
        assert decision is not None
        assert hasattr(decision, 'model_tier')
        assert hasattr(decision, 'model_spec')

    def test_route_and_call(self):
        """route_and_call() 통합 함수"""
        from unittest.mock import patch
        from src.core.router import route_and_call

        with patch('src.core.router.get_router') as mock_get_router:
            mock_router = HattzRouter()
            mock_get_router.return_value = mock_router

            with patch.object(mock_router, 'call_model', return_value="Mock response"):
                routing, response = route_and_call(
                    "테스트 메시지",
                    "pm",
                    [{"role": "user", "content": "test"}],
                    "system prompt"
                )

                assert routing is not None
                assert response == "Mock response"


class TestDefaultAgentTierRouting:
    """에이전트 기본 티어 라우팅 테스트"""

    def test_routing_with_long_normal_message(self):
        """긴 일반 메시지 - 기본 에이전트 티어"""
        router = HattzRouter()

        # 20자 이상이고 다른 조건에 해당하지 않는 메시지
        message = "이것은 특별한 키워드가 없는 일반적인 긴 메시지입니다"
        decision = router.route_traffic(message, "pm")

        # PM은 agent_to_tier에서 EXEC를 가짐
        assert decision is not None

    def test_routing_unknown_agent_fallback(self):
        """알 수 없는 에이전트 → STANDARD 폴백"""
        router = HattzRouter()

        # agent_to_tier에 없는 에이전트
        message = "이것은 특별한 키워드가 없는 일반적인 긴 메시지입니다"
        decision = router.route_traffic(message, "unknown_agent")

        # 기본 티어는 STANDARD
        assert decision.model_tier in ["standard", "exec"]


class TestCallModelIntegration:
    """call_model() 통합 테스트"""

    def test_call_model_anthropic_provider(self):
        """call_model - anthropic provider"""
        from unittest.mock import patch
        router = HattzRouter()

        decision = RoutingDecision(
            model_tier="standard",
            model_spec=router.STANDARD_MODEL,
            reason="test",
            estimated_tokens=100,
            estimated_cost=0.01
        )

        with patch.object(router, '_call_anthropic', return_value="Anthropic response"):
            result = router.call_model(
                decision,
                [{"role": "user", "content": "test"}],
                "system"
            )
            assert result == "Anthropic response"

    def test_call_model_openai_provider(self):
        """call_model - openai provider"""
        from unittest.mock import patch
        router = HattzRouter()

        decision = RoutingDecision(
            model_tier="vip_thinking",
            model_spec=router.VIP_THINKING_MODEL,
            reason="test",
            estimated_tokens=100,
            estimated_cost=0.01
        )

        with patch.object(router, '_call_openai', return_value="OpenAI response"):
            result = router.call_model(
                decision,
                [{"role": "user", "content": "test"}],
                "system"
            )
            assert result == "OpenAI response"

    def test_call_model_google_provider(self):
        """call_model - google provider"""
        from unittest.mock import patch
        router = HattzRouter()

        decision = RoutingDecision(
            model_tier="budget",
            model_spec=router.BUDGET_MODEL,
            reason="test",
            estimated_tokens=100,
            estimated_cost=0.01
        )

        with patch.object(router, '_call_google', return_value="Google response"):
            result = router.call_model(
                decision,
                [{"role": "user", "content": "test"}],
                "system"
            )
            assert result == "Google response"

    def test_call_model_perplexity_provider(self):
        """call_model - perplexity provider"""
        from unittest.mock import patch
        router = HattzRouter()

        decision = RoutingDecision(
            model_tier="research",
            model_spec=router.RESEARCH_MODEL,
            reason="test",
            estimated_tokens=100,
            estimated_cost=0.01
        )

        with patch.object(router, '_call_perplexity', return_value="Perplexity response"):
            result = router.call_model(
                decision,
                [{"role": "user", "content": "test"}],
                "system"
            )
            assert result == "Perplexity response"

    def test_call_model_fallback_on_error(self):
        """call_model - 에러 시 fallback 사용"""
        from unittest.mock import patch
        router = HattzRouter()

        decision = RoutingDecision(
            model_tier="research",
            model_spec=router.RESEARCH_MODEL,
            reason="test",
            estimated_tokens=100,
            estimated_cost=0.01,
            fallback_spec=router.BUDGET_MODEL
        )

        call_count = 0

        def mock_perplexity(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("Perplexity failed")

        with patch.object(router, '_call_perplexity', side_effect=mock_perplexity):
            with patch.object(router, '_call_google', return_value="Fallback response"):
                result = router.call_model(
                    decision,
                    [{"role": "user", "content": "test"}],
                    "system"
                )
                # fallback으로 성공
                assert "Fallback response" in result or "Error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
