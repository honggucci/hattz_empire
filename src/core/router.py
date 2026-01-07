"""
HattzRouter - Traffic Control System for AI Model Routing (v2.1 통장 보호)

v2.1 핵심 변경:
- 키워드만으로 VIP 태우지 않는다. 상황(에러/코드/실행요청)을 보고 라우팅
- PM/Excavator는 STANDARD (GPT-5.2 pro medium) - 뇌는 싸구려 금지
- Coder/QA/Reviewer는 EXEC (Claude Code CLI) - 실행부대
- Analyst/Documentor는 LOG_ONLY (Gemini Flash) - 요약만, 판단 금지

티어 구조 (v2.1):
- BUDGET: GPT-5 mini - 짧은 질의응답
- STANDARD: GPT-5.2 pro (medium) - PM/Excavator 기본
- VIP_THINKING: GPT-5.2 pro (high) - 에러 컨텍스트 + 원인 분석
- LOG_ONLY: Gemini Flash - 로그/표 요약 전용
- EXEC: Claude Code CLI - 레포 수정/명령 실행
- RESEARCH: Perplexity Sonar Pro - 최신/검색
- SAFETY: Claude Opus 4.5 - 고위험 감사

에스컬레이션 로직:
- 실패 시 자동 상위 티어 승격
- 고위험 키워드 감지 시 SAFETY 강제
- "왜" 같은 단어 하나로 VIP 태우지 않음 (에러 컨텍스트 필수)
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
    """모델 티어 v2.1 (비용순)"""
    BUDGET = "budget"           # 최저가 (GPT-5 mini) - 짧은 질의
    STANDARD = "standard"       # 표준 (GPT-5.2 pro medium) - PM/Excavator
    VIP_THINKING = "vip_thinking"  # 추론 (GPT-5.2 pro high) - 에러+원인 분석
    LOG_ONLY = "log_only"       # 로그 전용 (Gemini Flash) - 요약만, 판단 금지
    EXEC = "exec"               # 실행부대 (Claude Code CLI) - 레포 수정
    RESEARCH = "research"       # 검색 전용 (Perplexity)
    SAFETY = "safety"           # 고위험 감지 (VIP-AUDIT)


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

        # VIP-AUDIT (SAFETY): Claude Opus 4.5 - 감사/리뷰 ($5/$25)
        self.VIP_AUDIT_MODEL = ModelSpec(
            name="Claude Opus 4.5",
            provider="anthropic",
            model_id="claude-opus-4-5-20251101",
            api_key_env="ANTHROPIC_API_KEY",
            tier=ModelTier.SAFETY,
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
            tier=ModelTier.VIP_THINKING,
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
        # 에이전트 역할 → 기본 티어 매핑 (v2.1)
        # =====================================================================
        self.agent_to_tier = {
            # SAFETY - PM은 Opus 4.5 (똑똑한 라우터 필요)
            "pm": ModelTier.SAFETY,           # PM은 뇌다. Opus 4.5 사용
            "excavator": ModelTier.STANDARD,  # 의도 정제 (요구사항/제약/수용기준)

            # VIP_THINKING - 깊은 추론 (GPT-5.2 pro high) - 조건부만
            "strategist": ModelTier.VIP_THINKING,  # 에러 컨텍스트 있을 때만

            # LOG_ONLY - 눈 역할 (Gemini Flash) - 요약만, 판단 금지
            "analyst": ModelTier.LOG_ONLY,    # 로그/표 요약 전용
            "documentor": ModelTier.LOG_ONLY, # 문서 정리 전용

            # EXEC - 실행부대 (Claude Code CLI)
            "coder": ModelTier.EXEC,          # 코드/패치만 생성
            "qa": ModelTier.EXEC,             # 테스트/재현/검증
            "reviewer": ModelTier.EXEC,       # 코드리뷰/리스크

            # RESEARCH - 트리거 기반 (Perplexity)
            "researcher": ModelTier.RESEARCH,

            # SAFETY - 고위험 (VIP-AUDIT)
            "security": ModelTier.SAFETY,
        }

        # =====================================================================
        # 고위험 키워드 (SAFETY 강제) - v2.1
        # =====================================================================
        self.high_risk_keywords = [
            "api_key", "apikey", "secret", "private key", "seed phrase",
            "출금", "실거래", "주문", "withdraw", "transfer",
        ]

        # =====================================================================
        # 실행 키워드 (EXEC 트리거) - v2.1
        # =====================================================================
        self.exec_keywords = [
            "수정", "패치", "diff", "커밋", "commit", "테스트", "pytest", "unittest",
            "빌드", "build", "docker", "k8s", "kub", "helm", "배포", "deploy",
        ]

        # =====================================================================
        # 검색 키워드 (RESEARCH 트리거) - v2.1
        # =====================================================================
        self.research_keywords = [
            "검색", "찾아", "최신", "동향", "뉴스", "verify", "look up",
        ]

        # =====================================================================
        # 추론 필요 키워드 (VIP_THINKING 조건부) - v2.1
        # =====================================================================
        self.thinking_keywords = [
            "왜", "원인", "분석", "why", "reason", "root cause", "디버그", "debug",
        ]

        # =====================================================================
        # 에러 패턴 (히스토리 체크용) - v2.1
        # =====================================================================
        self.error_pattern = re.compile(
            r"(Traceback|Exception|Error|SparkException|KeyError|Stack trace|SQLSTATE)",
            re.IGNORECASE
        )

    # =========================================================================
    # 라우팅 로직
    # =========================================================================

    def route_traffic(
        self,
        message: str,
        agent_role: str = "pm",
        context_size: int = 0,
        history: list = None
    ) -> RoutingDecision:
        """
        메시지 + 역할 기반 라우팅 (v2.1)

        우선순위 (v2.1 - 키워드만으로 VIP 태우지 않는다):
        0. CEO 프리픽스 (최고/, 검색/, 생각/) → 강제 라우팅
        1. 고위험 키워드 → SAFETY (security 에이전트)
        2. 검색 키워드 → RESEARCH (Perplexity)
        3. 실행 의도/코드 감지 → EXEC (Claude Code CLI)
        4. 짧은 단순 질문 (<20자, 코드 없음) → BUDGET
        5. 추론 키워드 + 에러 컨텍스트 → VIP_THINKING
        6. 추론 키워드만 (에러 없음) → STANDARD (VIP 금지)
        7. 에이전트 기본 티어

        Args:
            message: 사용자 메시지
            agent_role: 에이전트 역할
            context_size: 컨텍스트 크기 (토큰)
            history: 최근 대화 히스토리 (에러 맥락 체크용)
        """
        msg = (message or "").strip()
        msg_lower = msg.lower()

        # 1. 고위험 체크 → SAFETY 강제
        if self._is_high_risk(msg_lower):
            return self._create_decision(
                self.VIP_AUDIT_MODEL,
                "risk_keyword_detected → SAFETY",
                context_size,
                escalate_to=None
            )

        # 2. 검색 키워드 체크 → RESEARCH
        if self._is_research(msg_lower) or agent_role == "researcher":
            return self._create_decision(
                self.RESEARCH_MODEL,
                "research_trigger → Perplexity",
                context_size,
                escalate_to=self.STANDARD_MODEL
            )

        # 3. 실행 의도/코드 감지 → EXEC (Claude Code CLI)
        if self._looks_like_code(msg) or self._has_exec_intent(msg_lower):
            return self._create_decision(
                self.STANDARD_MODEL,  # EXEC는 Claude CLI로 처리, 여기서는 STANDARD 반환
                "execution_intent_or_code → EXEC (Claude CLI)",
                context_size,
                escalate_to=self.VIP_AUDIT_MODEL
            )

        # 4. 추론 키워드 체크 (맥락 기반) - v2.1 핵심 로직
        #    ※ 짧은 질문 체크보다 먼저! "왜?" + 에러 컨텍스트면 VIP 태워야 함
        has_vip_kw = any(kw.lower() in msg_lower for kw in self.thinking_keywords)
        has_error_ctx = self._has_error_context(history)

        if has_vip_kw and has_error_ctx:
            # 키워드 + 에러 컨텍스트 → VIP_THINKING
            return self._create_decision(
                self.VIP_THINKING_MODEL,
                "vip_keyword_with_error_context → VIP_THINKING",
                context_size,
                escalate_to=self.VIP_AUDIT_MODEL
            )

        # 5. 추론 키워드만 (에러 없음) → STANDARD (VIP 승격 금지!)
        if has_vip_kw:
            return self._create_decision(
                self.STANDARD_MODEL,
                "vip_keyword_without_error_context → STANDARD (VIP 금지)",
                context_size,
                escalate_to=self.VIP_THINKING_MODEL
            )

        # 6. 짧은 단순 질문 (<20자, 코드 없음) → BUDGET
        #    ※ VIP 키워드 체크 후에! "왜?" 같은 건 이미 위에서 처리됨
        if len(msg) < 20 and not self._looks_like_code(msg):
            return self._create_decision(
                self.BUDGET_MODEL,
                "short_simple_query → BUDGET",
                context_size,
                escalate_to=self.STANDARD_MODEL
            )

        # 7. 에이전트 기본 티어
        tier = self.agent_to_tier.get(agent_role, ModelTier.STANDARD)
        model = self._get_model_by_tier(tier)

        return self._create_decision(
            model,
            f"default → agent '{agent_role}' → {tier.value}",
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

    def _is_high_risk(self, message: str) -> bool:
        """고위험 키워드 체크 (v2.1)"""
        return any(kw.lower() in message for kw in self.high_risk_keywords)

    def _has_exec_intent(self, message: str) -> bool:
        """실행 의도 체크 (v2.1) - EXEC 트리거"""
        return any(kw.lower() in message for kw in self.exec_keywords)

    def _looks_like_code(self, message: str) -> bool:
        """코드 포함 여부 체크 (v2.1)"""
        if "```" in message:
            return True
        return bool(re.search(r"\b(def|class|SELECT|INSERT|UPDATE|Traceback|Exception)\b", message))

    def _has_error_context(self, history: list = None, window: int = 2) -> bool:
        """
        에러 컨텍스트 체크 (v2.1)
        최근 히스토리에서 실제 에러/예외가 있는지 확인
        """
        if not history:
            return False
        recent = "\n".join(str(h) for h in history[-window:])
        return bool(self.error_pattern.search(recent))

    def _is_research(self, message: str) -> bool:
        """검색 필요 여부 체크 (v2.1)"""
        return any(kw in message for kw in self.research_keywords)

    def _get_model_by_tier(self, tier: ModelTier) -> ModelSpec:
        """티어별 기본 모델 (v2.1)"""
        tier_to_model = {
            ModelTier.BUDGET: self.BUDGET_MODEL,
            ModelTier.STANDARD: self.STANDARD_MODEL,
            ModelTier.VIP_THINKING: self.VIP_THINKING_MODEL,
            ModelTier.LOG_ONLY: self.BUDGET_MODEL,     # Gemini Flash
            ModelTier.EXEC: self.STANDARD_MODEL,       # Claude CLI (실제 호출은 별도)
            ModelTier.RESEARCH: self.RESEARCH_MODEL,
            ModelTier.SAFETY: self.VIP_AUDIT_MODEL,
        }
        return tier_to_model.get(tier, self.STANDARD_MODEL)

    def _get_escalation_model(self, tier: ModelTier) -> Optional[ModelSpec]:
        """실패 시 승격 모델 (v2.1)"""
        escalation = {
            ModelTier.BUDGET: self.STANDARD_MODEL,
            ModelTier.STANDARD: self.VIP_THINKING_MODEL,
            ModelTier.VIP_THINKING: self.VIP_AUDIT_MODEL,
            ModelTier.LOG_ONLY: self.STANDARD_MODEL,
            ModelTier.EXEC: self.VIP_AUDIT_MODEL,
            ModelTier.RESEARCH: self.STANDARD_MODEL,
            ModelTier.SAFETY: None,  # 최고 티어
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
        """Anthropic API → CLI 리다이렉트 (v2.4.3 - API 비용 0원)"""
        from src.services.cli_supervisor import call_claude_cli

        # model_id로 프로필 결정 (opus=coder, sonnet=reviewer)
        profile = "coder" if "opus" in spec.model_id.lower() else "reviewer"

        return call_claude_cli(messages, system_prompt, profile)

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

        # Perplexity는 user/assistant 교대 필수
        # 가장 단순하게: system + 마지막 user 메시지만 사용
        last_user_msg = None
        for msg in messages:
            if msg["role"] == "user":
                last_user_msg = msg

        if last_user_msg:
            full_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": last_user_msg["content"]}
            ]
        else:
            # user 메시지가 없으면 에러
            return "[Error] No user message found for Perplexity"

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
