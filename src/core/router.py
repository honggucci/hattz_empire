"""
HattzRouter - Traffic Control System for AI Model Routing (v2.0 Budget Optimized)

비용 최적화 3단 변속기:
- BUDGET: Gemini 2.0 Flash ($0.10/$0.40) - 80% 일반 작업
- STANDARD: Claude Sonnet 4 ($3/$15) - 15% 코딩/분석
- VIP: Opus 4.5 / GPT-5.2 Thinking Extend ($5~$20) - 5% 감사/고난도
- RESEARCH: Perplexity Sonar Pro ($3/$15) - 트리거 기반 검색

에스컬레이션 로직:
- 실패 시 자동 상위 티어 승격
- 고위험 키워드 감지 시 VIP 강제
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any, List
import re
import os


class TaskType(Enum):
    """작업 유형 분류"""
    STRATEGY = "strategy"       # 전략, 의사결정
    CODE = "code"               # 코딩, 구현
    DATA = "data"               # 데이터 분석, 로그
    RESEARCH = "research"       # 실시간 검색, 리서치
    ORCHESTRATION = "orchestration"  # PM 오케스트레이션
    GENERAL = "general"         # 일반 작업
    SECURITY = "security"       # 보안/키/권한 (항상 VIP)


class UrgencyLevel(Enum):
    """긴급도 레벨"""
    CRITICAL = "critical"       # 즉시 처리 (장애, 긴급 버그)
    HIGH = "high"               # 높음 (오늘 내 처리)
    NORMAL = "normal"           # 보통
    LOW = "low"                 # 낮음 (백그라운드)


class ModelTier(Enum):
    """모델 티어 (비용순)"""
    BUDGET = "budget"           # 최저가 (Gemini Flash)
    STANDARD = "standard"       # 표준 (Sonnet)
    VIP = "vip"                 # 고급 (Opus/Thinking)
    RESEARCH = "research"       # 검색 전용 (Perplexity)


@dataclass
class ModelSpec:
    """모델 스펙"""
    name: str
    provider: str  # anthropic, openai, google, perplexity
    model_id: str
    api_key_env: str
    tier: ModelTier
    cost_input: float   # $ per 1M tokens
    cost_output: float  # $ per 1M tokens
    temperature: float = 0.7
    max_tokens: int = 8192
    thinking_mode: bool = False


@dataclass
class RoutingDecision:
    """라우팅 결정 결과"""
    model_tier: str             # "budget", "standard", "vip", "research"
    model_spec: ModelSpec       # 실제 모델 스펙
    reason: str                 # 라우팅 이유
    estimated_tokens: int       # 예상 토큰 수
    estimated_cost: float       # 예상 비용 ($)
    fallback_spec: Optional[ModelSpec] = None  # 폴백 모델
    escalate_to: Optional[ModelSpec] = None    # 실패 시 승격 모델


class HattzRouter:
    """
    Traffic Control System v2.0 - 비용 최적화 라우팅

    원칙:
    1. 기본은 최저가 (Gemini Flash)
    2. 코딩은 Sonnet (가성비 최고)
    3. VIP는 감사/추론에만 (Opus/Thinking)
    4. 검색은 Perplexity (트리거 기반)
    """

    def __init__(self):
        # =====================================================================
        # 모델 정의 (비용순 정렬)
        # =====================================================================

        # BUDGET: Gemini 2.0 Flash - 최저가 ($0.10/$0.40)
        self.BUDGET_MODEL = ModelSpec(
            name="Gemini 2.0 Flash",
            provider="google",
            model_id="gemini-2.0-flash",
            api_key_env="GOOGLE_API_KEY",
            tier=ModelTier.BUDGET,
            cost_input=0.10,
            cost_output=0.40,
            temperature=0.7,
            max_tokens=8192,
        )

        # STANDARD: Claude Sonnet 4 - 코딩 메인 ($3/$15)
        self.STANDARD_MODEL = ModelSpec(
            name="Claude Sonnet 4",
            provider="anthropic",
            model_id="claude-sonnet-4-20250514",
            api_key_env="ANTHROPIC_API_KEY",
            tier=ModelTier.STANDARD,
            cost_input=3.0,
            cost_output=15.0,
            temperature=0.5,
            max_tokens=8192,
        )

        # VIP-AUDIT: Claude Opus 4.5 - 감사/리뷰 ($5/$25)
        self.VIP_AUDIT_MODEL = ModelSpec(
            name="Claude Opus 4.5",
            provider="anthropic",
            model_id="claude-opus-4-5-20251101",
            api_key_env="ANTHROPIC_API_KEY",
            tier=ModelTier.VIP,
            cost_input=5.0,
            cost_output=25.0,
            temperature=0.3,
            max_tokens=8192,
        )

        # VIP-THINKING: GPT-5.2 Thinking Extend - 추론/원인분석
        self.VIP_THINKING_MODEL = ModelSpec(
            name="GPT-5.2 Thinking Extend",
            provider="openai",
            model_id="gpt-5.2-thinking-extend",
            api_key_env="OPENAI_API_KEY",
            tier=ModelTier.VIP,
            cost_input=5.0,
            cost_output=20.0,
            temperature=0.2,
            max_tokens=32768,
            thinking_mode=True,
        )

        # RESEARCH: Perplexity Sonar Pro - 검색 전용 ($3/$15)
        self.RESEARCH_MODEL = ModelSpec(
            name="Perplexity Sonar Pro",
            provider="perplexity",
            model_id="sonar-pro",
            api_key_env="PERPLEXITY_API_KEY",
            tier=ModelTier.RESEARCH,
            cost_input=3.0,
            cost_output=15.0,
            temperature=0.3,
            max_tokens=8192,
        )

        # =====================================================================
        # 컨텍스트 임계값
        # =====================================================================
        self.LARGE_CONTEXT_THRESHOLD = 50000    # 50K → Budget (긴 컨텍스트)
        self.MEDIUM_CONTEXT_THRESHOLD = 10000

        # =====================================================================
        # 에이전트 역할 → 기본 티어 매핑
        # =====================================================================
        self.agent_to_tier = {
            # BUDGET (80%) - 일반 작업
            "pm": ModelTier.BUDGET,           # PM 기본은 싼 모델
            "analyst": ModelTier.BUDGET,      # 로그 분석
            "documentor": ModelTier.BUDGET,   # 문서화

            # STANDARD (15%) - 코딩/정제
            "coder": ModelTier.STANDARD,      # 코드 수정
            "excavator": ModelTier.STANDARD,  # 의도 정제
            "qa": ModelTier.STANDARD,         # QA 기본
            "strategist": ModelTier.STANDARD, # 전략 초안

            # RESEARCH - 트리거 기반
            "researcher": ModelTier.RESEARCH, # Perplexity 전용
        }

        # =====================================================================
        # 고위험 키워드 (VIP 강제 승격)
        # =====================================================================
        self.high_risk_keywords = [
            # 보안/금융
            "api_key", "secret", "password", "credential", "token",
            "주문", "order", "거래", "trade", "balance", "잔고",
            "출금", "withdraw", "입금", "deposit", "transfer",

            # 실거래
            "live", "production", "배포", "deploy", "release",
            "실거래", "실매매", "real", "prod",

            # 리스크
            "손실", "loss", "risk", "위험", "레버리지", "leverage",
            "청산", "liquidation", "margin",
        ]

        # =====================================================================
        # 추론 필요 키워드 (Thinking 승격)
        # =====================================================================
        self.thinking_keywords = [
            "왜", "why", "원인", "cause", "이유", "reason",
            "분석해", "analyze", "추론", "infer", "논리", "logic",
            "버그 원인", "root cause", "디버그", "debug",
            "실패 원인", "failure", "괴리", "discrepancy",
        ]

    # =========================================================================
    # 라우팅 로직
    # =========================================================================

    def route_traffic(
        self,
        message: str,
        agent_role: str = "pm",
        context_size: int = 0
    ) -> RoutingDecision:
        """
        메시지 + 역할 기반 라우팅

        우선순위:
        0. CEO 프리픽스 (최고/, 검색/) → VIP/Research 강제
        1. 고위험 키워드 → VIP (Opus)
        2. 추론 키워드 → VIP (Thinking)
        3. 검색 키워드 → Research (Perplexity)
        4. 대용량 컨텍스트 → Budget (Gemini Flash)
        5. 에이전트 기본 티어
        """
        message_lower = message.lower()

        # 0. CEO 프리픽스 체크 (최우선)
        prefix_result = self._check_ceo_prefix(message)
        if prefix_result:
            return prefix_result

        # 1. 고위험 체크 → VIP-AUDIT 강제
        if self._is_high_risk(message_lower):
            return self._create_decision(
                self.VIP_AUDIT_MODEL,
                f"High-risk keywords detected → VIP audit",
                context_size,
                escalate_to=None  # 이미 최고 티어
            )

        # 2. 추론 필요 체크 → VIP-THINKING
        if self._needs_thinking(message_lower):
            return self._create_decision(
                self.VIP_THINKING_MODEL,
                f"Reasoning required → Thinking mode",
                context_size,
                escalate_to=self.VIP_AUDIT_MODEL
            )

        # 3. 검색 키워드 체크 → RESEARCH
        if self._is_research(message_lower) or agent_role == "researcher":
            return self._create_decision(
                self.RESEARCH_MODEL,
                f"Research/search required → Perplexity",
                context_size,
                escalate_to=self.STANDARD_MODEL
            )

        # 4. 대용량 컨텍스트 → BUDGET (긴 컨텍스트 처리)
        if context_size >= self.LARGE_CONTEXT_THRESHOLD:
            return self._create_decision(
                self.BUDGET_MODEL,
                f"Large context ({context_size:,} tokens) → Budget model",
                context_size,
                escalate_to=self.STANDARD_MODEL
            )

        # 5. 에이전트 기본 티어
        tier = self.agent_to_tier.get(agent_role, ModelTier.BUDGET)
        model = self._get_model_by_tier(tier)

        return self._create_decision(
            model,
            f"Agent role '{agent_role}' → {tier.value} tier",
            context_size,
            escalate_to=self._get_escalation_model(tier)
        )

    def _create_decision(
        self,
        model: ModelSpec,
        reason: str,
        context_size: int,
        escalate_to: Optional[ModelSpec] = None
    ) -> RoutingDecision:
        """라우팅 결정 생성"""
        # 비용 추정 (input + output 가정: 1:1 비율)
        tokens = context_size or 1000
        estimated_cost = (
            (tokens / 1_000_000) * model.cost_input +
            (tokens / 1_000_000) * model.cost_output
        )

        return RoutingDecision(
            model_tier=model.tier.value,
            model_spec=model,
            reason=reason,
            estimated_tokens=tokens,
            estimated_cost=estimated_cost,
            fallback_spec=self._get_fallback(model),
            escalate_to=escalate_to
        )

    def _check_ceo_prefix(self, message: str) -> Optional[RoutingDecision]:
        """
        CEO 프리픽스 체크 - VIP 모델 강제 호출

        프리픽스:
        - 최고/ : VIP-AUDIT (Opus 4.5) 강제 호출
        - 생각/ : VIP-THINKING (GPT-5.2 Thinking Extend) 강제 호출
        - 검색/ : RESEARCH (Perplexity) 강제 호출

        예시:
        - "최고/ 이 코드 리뷰해줘" → Opus 4.5 사용
        - "생각/ 왜 이게 안될까?" → GPT-5.2 Thinking Extend 사용
        - "검색/ 최신 파이썬 버전" → Perplexity 사용
        """
        # VIP-AUDIT 강제 (최고/)
        if message.startswith("최고/") or message.startswith("최고/ "):
            return self._create_decision(
                self.VIP_AUDIT_MODEL,
                "CEO prefix '최고/' → VIP-AUDIT (Opus 4.5) 강제",
                0,
                escalate_to=None  # 이미 최고 티어
            )

        # VIP-THINKING 강제 (생각/)
        if message.startswith("생각/") or message.startswith("생각/ "):
            return self._create_decision(
                self.VIP_THINKING_MODEL,
                "CEO prefix '생각/' → VIP-THINKING 강제",
                0,
                escalate_to=self.VIP_AUDIT_MODEL
            )

        # RESEARCH 강제 (검색/)
        if message.startswith("검색/") or message.startswith("검색/ "):
            return self._create_decision(
                self.RESEARCH_MODEL,
                "CEO prefix '검색/' → RESEARCH (Perplexity) 강제",
                0,
                escalate_to=self.STANDARD_MODEL
            )

        return None

    def _is_high_risk(self, message: str) -> bool:
        """고위험 키워드 체크"""
        return any(kw in message for kw in self.high_risk_keywords)

    def _needs_thinking(self, message: str) -> bool:
        """추론 필요 여부 체크"""
        return any(kw in message for kw in self.thinking_keywords)

    def _is_research(self, message: str) -> bool:
        """검색 필요 여부 체크"""
        research_keywords = [
            "검색", "search", "찾아", "find", "알아봐", "조사",
            "최신", "latest", "뉴스", "news", "트렌드", "trend",
            "동향", "현황", "실시간", "api 변경", "breaking change",
        ]
        return any(kw in message for kw in research_keywords)

    def _get_model_by_tier(self, tier: ModelTier) -> ModelSpec:
        """티어별 기본 모델"""
        tier_to_model = {
            ModelTier.BUDGET: self.BUDGET_MODEL,
            ModelTier.STANDARD: self.STANDARD_MODEL,
            ModelTier.VIP: self.VIP_AUDIT_MODEL,
            ModelTier.RESEARCH: self.RESEARCH_MODEL,
        }
        return tier_to_model.get(tier, self.BUDGET_MODEL)

    def _get_escalation_model(self, tier: ModelTier) -> Optional[ModelSpec]:
        """실패 시 승격 모델"""
        escalation = {
            ModelTier.BUDGET: self.STANDARD_MODEL,
            ModelTier.STANDARD: self.VIP_AUDIT_MODEL,
            ModelTier.VIP: None,  # 최고 티어
            ModelTier.RESEARCH: self.STANDARD_MODEL,
        }
        return escalation.get(tier)

    def _get_fallback(self, model: ModelSpec) -> Optional[ModelSpec]:
        """폴백 모델 (에러 시)"""
        # 항상 Budget으로 폴백 (최소 동작 보장)
        if model.tier != ModelTier.BUDGET:
            return self.BUDGET_MODEL
        return None

    # =========================================================================
    # 모델 호출
    # =========================================================================

    def call_model(
        self,
        routing: RoutingDecision,
        messages: list,
        system_prompt: str
    ) -> str:
        """라우팅 결정에 따라 모델 호출"""
        spec = routing.model_spec

        try:
            if spec.provider == "anthropic":
                return self._call_anthropic(spec, messages, system_prompt)
            elif spec.provider == "openai":
                return self._call_openai(spec, messages, system_prompt)
            elif spec.provider == "google":
                return self._call_google(spec, messages, system_prompt)
            elif spec.provider == "perplexity":
                return self._call_perplexity(spec, messages, system_prompt)
            else:
                return f"[Error] Unknown provider: {spec.provider}"

        except Exception as e:
            print(f"[Router] {spec.name} failed: {e}")

            # 폴백 시도
            if routing.fallback_spec:
                print(f"[Router] Trying fallback: {routing.fallback_spec.name}")
                fallback_routing = RoutingDecision(
                    model_tier="fallback",
                    model_spec=routing.fallback_spec,
                    reason=f"Fallback from {spec.name}",
                    estimated_tokens=routing.estimated_tokens,
                    estimated_cost=0
                )
                return self.call_model(fallback_routing, messages, system_prompt)

            return f"[Error] {spec.provider}: {str(e)}"

    def _call_anthropic(self, spec: ModelSpec, messages: list, system_prompt: str) -> str:
        """Anthropic API 호출"""
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv(spec.api_key_env))

        response = client.messages.create(
            model=spec.model_id,
            max_tokens=spec.max_tokens,
            temperature=spec.temperature,
            system=system_prompt,
            messages=messages
        )
        return response.content[0].text

    def _call_openai(self, spec: ModelSpec, messages: list, system_prompt: str) -> str:
        """OpenAI API 호출"""
        import openai
        client = openai.OpenAI(api_key=os.getenv(spec.api_key_env))

        # Thinking Mode 프리픽스
        if spec.thinking_mode:
            system_prompt = self._get_thinking_prefix() + system_prompt

        full_messages = [{"role": "system", "content": system_prompt}]
        full_messages.extend(messages)

        response = client.chat.completions.create(
            model=spec.model_id,
            max_tokens=spec.max_tokens,
            temperature=spec.temperature,
            messages=full_messages
        )
        return response.choices[0].message.content

    def _call_google(self, spec: ModelSpec, messages: list, system_prompt: str) -> str:
        """Google Gemini API 호출"""
        import google.generativeai as genai
        genai.configure(api_key=os.getenv(spec.api_key_env))

        model = genai.GenerativeModel(
            model_name=spec.model_id,
            system_instruction=system_prompt
        )

        # 대화 히스토리 변환
        history = []
        for msg in messages[:-1]:
            role = "user" if msg["role"] == "user" else "model"
            history.append({"role": role, "parts": [msg["content"]]})

        chat = model.start_chat(history=history)
        response = chat.send_message(messages[-1]["content"])
        return response.text

    def _call_perplexity(self, spec: ModelSpec, messages: list, system_prompt: str) -> str:
        """Perplexity API 호출 (실시간 검색)"""
        import requests

        api_key = os.getenv(spec.api_key_env)
        if not api_key:
            return f"[Error] Perplexity API key not found"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        full_messages = [{"role": "system", "content": system_prompt}]
        full_messages.extend(messages)

        payload = {
            "model": spec.model_id,
            "messages": full_messages,
            "temperature": spec.temperature,
            "max_tokens": spec.max_tokens,
        }

        response = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers=headers,
            json=payload,
            timeout=120
        )

        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # 인용 정보 추가
            citations = data.get("citations", [])
            if citations:
                content += "\n\n---\n**Sources:**\n"
                for i, cite in enumerate(citations, 1):
                    content += f"{i}. {cite}\n"

            return content
        else:
            return f"[Perplexity Error] {response.status_code}: {response.text}"

    def _get_thinking_prefix(self) -> str:
        """Thinking Mode 프리픽스"""
        return """
## THINKING EXTEND MODE ACTIVATED
You are operating in deep reasoning mode. Before answering:

1. ANALYZE: Break down the problem
2. QUESTION: Identify edge cases
3. EVALUATE: Consider alternatives
4. SYNTHESIZE: Form coherent response

Prioritize correctness over brevity. Think step-by-step.

---

"""

    # =========================================================================
    # 유틸리티
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """라우터 설정 통계"""
        return {
            "models": {
                "budget": {
                    "name": self.BUDGET_MODEL.name,
                    "model_id": self.BUDGET_MODEL.model_id,
                    "cost": f"${self.BUDGET_MODEL.cost_input}/${self.BUDGET_MODEL.cost_output} per 1M"
                },
                "standard": {
                    "name": self.STANDARD_MODEL.name,
                    "model_id": self.STANDARD_MODEL.model_id,
                    "cost": f"${self.STANDARD_MODEL.cost_input}/${self.STANDARD_MODEL.cost_output} per 1M"
                },
                "vip_audit": {
                    "name": self.VIP_AUDIT_MODEL.name,
                    "model_id": self.VIP_AUDIT_MODEL.model_id,
                    "cost": f"${self.VIP_AUDIT_MODEL.cost_input}/${self.VIP_AUDIT_MODEL.cost_output} per 1M"
                },
                "vip_thinking": {
                    "name": self.VIP_THINKING_MODEL.name,
                    "model_id": self.VIP_THINKING_MODEL.model_id,
                    "cost": f"${self.VIP_THINKING_MODEL.cost_input}/${self.VIP_THINKING_MODEL.cost_output} per 1M"
                },
                "research": {
                    "name": self.RESEARCH_MODEL.name,
                    "model_id": self.RESEARCH_MODEL.model_id,
                    "cost": f"${self.RESEARCH_MODEL.cost_input}/${self.RESEARCH_MODEL.cost_output} per 1M"
                },
            },
            "agent_tiers": {
                role: tier.value
                for role, tier in self.agent_to_tier.items()
            },
            "high_risk_keywords": len(self.high_risk_keywords),
            "thinking_keywords": len(self.thinking_keywords),
        }

    def estimate_cost(self, input_tokens: int, output_tokens: int, tier: str) -> float:
        """비용 추정"""
        model = {
            "budget": self.BUDGET_MODEL,
            "standard": self.STANDARD_MODEL,
            "vip": self.VIP_AUDIT_MODEL,
            "research": self.RESEARCH_MODEL,
        }.get(tier, self.BUDGET_MODEL)

        return (
            (input_tokens / 1_000_000) * model.cost_input +
            (output_tokens / 1_000_000) * model.cost_output
        )


# =============================================================================
# 싱글톤
# =============================================================================

_router: Optional[HattzRouter] = None


def get_router() -> HattzRouter:
    """HattzRouter 싱글톤"""
    global _router
    if _router is None:
        _router = HattzRouter()
    return _router


def route_message(message: str, agent_role: str = "pm") -> RoutingDecision:
    """메시지 라우팅 (단축 함수)"""
    return get_router().route_traffic(message, agent_role)


def route_and_call(
    message: str,
    agent_role: str,
    messages: list,
    system_prompt: str
) -> tuple[RoutingDecision, str]:
    """라우팅 + 모델 호출"""
    router = get_router()
    routing = router.route_traffic(message, agent_role)
    response = router.call_model(routing, messages, system_prompt)
    return routing, response


# =============================================================================
# 테스트
# =============================================================================

if __name__ == "__main__":
    import json

    router = HattzRouter()

    print("=" * 70)
    print("HattzRouter v2.0 - Budget Optimized Traffic Control")
    print("=" * 70)

    test_cases = [
        # 일반 작업 → BUDGET
        ("안녕하세요", "pm"),
        ("로그 분석해줘", "analyst"),

        # 코딩 → STANDARD
        ("버그 수정해", "coder"),
        ("코드 리뷰해줘", "qa"),

        # 고위험 → VIP
        ("api_key 설정 변경해", "coder"),
        ("실거래 주문 로직 수정", "pm"),

        # 추론 → THINKING
        ("왜 테스트가 실패하는지 분석해", "coder"),
        ("버그 원인 찾아줘", "qa"),

        # 검색 → RESEARCH
        ("ccxt 최신 버전 변경사항 검색해", "researcher"),
        ("바이낸스 API 변경 알아봐", "pm"),
    ]

    print("\n[Test Cases]\n")
    for message, role in test_cases:
        decision = router.route_traffic(message, role)
        print(f"[{role}] {message}")
        print(f"  → Tier: {decision.model_tier}")
        print(f"  → Model: {decision.model_spec.name}")
        print(f"  → Cost: ${decision.estimated_cost:.6f}")
        print(f"  → Reason: {decision.reason}")
        print()

    print("=" * 70)
    print("Router Configuration:")
    print(json.dumps(router.get_stats(), indent=2, ensure_ascii=False))
