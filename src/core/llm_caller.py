"""
Hattz Empire - LLM Caller
LLM API 호출 및 에이전트 로직

2026.01.04 업데이트:
- 듀얼 엔진 와이어링 (Writer + Auditor 패턴)
- 위원회 자동 소집 + 모델 할당
- 루프 브레이커 추가
"""
import os
import time as time_module
import asyncio
from typing import Optional, Tuple, Dict, Any

import sys
from pathlib import Path

# 루트 디렉토리를 path에 추가
root_dir = Path(__file__).parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from config import (
    MODELS, DUAL_ENGINES, SINGLE_ENGINES,
    get_system_prompt, ModelConfig
)


# =============================================================================
# 듀얼 엔진 + 위원회 설정
# =============================================================================

# 듀얼 엔진 역할 정의 (Writer + Auditor)
DUAL_ENGINE_ROLES = {
    "coder": {
        "writer": "claude_sonnet",      # Sonnet 4 - 빠른 코드 작성
        "auditor": "gpt_5_mini",         # GPT-5 mini - 저렴한 리뷰
        "description": "코드 작성 + 리뷰"
    },
    "strategist": {
        "writer": "gpt_thinking",        # GPT-5.2 Thinking - 전략 수립
        "auditor": "claude_sonnet",      # Sonnet - 전략 검증
        "description": "전략 수립 + 검증"
    },
    "qa": {
        "writer": "gpt_5_mini",          # GPT-5 mini - 빠른 테스트 생성
        "auditor": "claude_sonnet",      # Sonnet - 보안/엣지케이스 검증
        "description": "테스트 생성 + 검증"
    },
    "researcher": {
        "writer": "gemini_flash",        # Gemini 3 Flash - 검색/수집
        "auditor": "gpt_5_mini",         # GPT-5 mini - 팩트체크
        "description": "리서치 + 검증"
    },
    "excavator": {
        "writer": "claude_sonnet",       # Sonnet - 의도 파악
        "auditor": "gpt_5_mini",         # GPT-5 mini - 확인
        "description": "CEO 의도 발굴 + 확인"
    },
}

# VIP 프리픽스용 듀얼 엔진 (VIP Writer + VIP Auditor)
VIP_DUAL_ENGINE = {
    "최고/": {  # Opus 4.5 기반
        "writer": "claude_opus",         # Opus 4.5 - VIP Writer
        "auditor": "claude_sonnet",      # Sonnet 4 - VIP Auditor
        "description": "VIP-AUDIT: Opus + Sonnet 크로스체크"
    },
    "생각/": {  # GPT-5.2 Thinking 기반
        "writer": "gpt_thinking",        # GPT-5.2 Thinking Extended
        "auditor": "claude_opus",        # Opus 4.5 - 크로스체크
        "description": "VIP-THINKING: GPT-5.2 + Opus 크로스체크"
    },
    "검색/": {  # Perplexity 기반
        "writer": "perplexity_sonar",    # Perplexity Sonar Pro
        "auditor": "gpt_5_mini",         # GPT-5 mini - 팩트체크
        "description": "RESEARCH: Perplexity + 팩트체크"
    },
}

# 위원회별 모델 할당 (저렴한 모델 위주, 타이브레이커만 비싼 모델)
COUNCIL_MODEL_MAPPING = {
    "code": {
        "personas": {
            "skeptic": "gpt_5_mini",
            "perfectionist": "claude_haiku",    # Haiku 없으면 4o-mini로 대체
            "pragmatist": "gpt_5_mini",
        },
        "tiebreaker": "claude_sonnet",           # 의견 갈릴 때 Sonnet
    },
    "strategy": {
        "personas": {
            "pessimist": "gpt_5_mini",
            "optimist": "claude_haiku",
            "devils_advocate": "gpt_5_mini",
        },
        "tiebreaker": "gpt_thinking",            # 전략은 GPT-5.2 Thinking
    },
    "security": {
        "personas": {
            "security_hawk": "claude_sonnet",    # 보안은 Sonnet 필수
            "skeptic": "gpt_5_mini",
            "pessimist": "gpt_5_mini",
        },
        "tiebreaker": "claude_opus",             # 보안 최종은 Opus
    },
    "deploy": {
        "personas": {
            "security_hawk": "claude_sonnet",
            "pessimist": "gpt_5_mini",
            "pragmatist": "gpt_5_mini",
            "perfectionist": "claude_haiku",
        },
        "tiebreaker": "claude_opus",             # 배포 최종은 CEO(Opus)
        "requires_ceo": True,
    },
    "mvp": {
        "personas": {
            "pragmatist": "gpt_5_mini",
            "optimist": "gpt_5_mini",
            "skeptic": "claude_haiku",
        },
        "tiebreaker": "claude_sonnet",
    },
}

# 루프 브레이커 설정
LOOP_BREAKER_CONFIG = {
    "MAX_STAGE_RETRY": 2,      # 같은 단계 최대 재시도
    "MAX_TOTAL_STEPS": 8,      # 전체 최대 단계
    "SIMILARITY_THRESHOLD": 0.85,  # 반복 응답 감지 (85% 유사도)
    "ESCALATE_TO_CEO": True,   # 루프 감지시 CEO 에스컬레이션
}

# Haiku 모델 추가 (저렴한 위원회용) - config.py에 이미 있으면 스킵
# 이제 config.py에 claude_haiku가 정의되어 있으므로 이 블록은 폴백용으로만 유지

from src.infra.stream import get_stream
from src.core.router import get_router, route_message
from src.services import database as db
from src.services import executor
from src.services import rag
from src.services.agent_scorecard import get_scorecard


# =============================================================================
# LLM API Clients
# =============================================================================

THINKING_EXTEND_PREFIX = """
## THINKING EXTEND MODE ACTIVATED
You are operating in deep reasoning mode. Before providing any answer:

1. ANALYZE: Break down the problem into components
2. QUESTION: Identify assumptions and edge cases
3. EVALUATE: Consider alternative interpretations
4. SYNTHESIZE: Combine insights into coherent response

Do NOT skip reasoning steps. Prioritize correctness over brevity.
Think step-by-step internally before outputting your final structured response.

---

"""


def call_anthropic(model_config: ModelConfig, messages: list, system_prompt: str) -> str:
    """Anthropic API 호출"""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv(model_config.api_key_env))

        response = client.messages.create(
            model=model_config.model_id,
            max_tokens=model_config.max_tokens,
            temperature=model_config.temperature,
            system=system_prompt,
            messages=messages
        )
        return response.content[0].text
    except Exception as e:
        return f"[Anthropic Error] {str(e)}"


def call_openai(model_config: ModelConfig, messages: list, system_prompt: str) -> str:
    """OpenAI API 호출"""
    try:
        import openai
        client = openai.OpenAI(api_key=os.getenv(model_config.api_key_env))

        if getattr(model_config, 'thinking_mode', False):
            system_prompt = THINKING_EXTEND_PREFIX + system_prompt

        full_messages = [{"role": "system", "content": system_prompt}]
        full_messages.extend(messages)

        # GPT-5 계열: temperature 지원 안함, max_completion_tokens 사용
        if model_config.model_id.startswith("gpt-5"):
            response = client.chat.completions.create(
                model=model_config.model_id,
                max_completion_tokens=model_config.max_tokens,
                # GPT-5는 temperature=1만 지원 (파라미터 생략)
                messages=full_messages
            )
        else:
            response = client.chat.completions.create(
                model=model_config.model_id,
                max_tokens=model_config.max_tokens,
                temperature=model_config.temperature,
                messages=full_messages
            )
        return response.choices[0].message.content
    except Exception as e:
        return f"[OpenAI Error] {str(e)}"


def call_google(model_config: ModelConfig, messages: list, system_prompt: str) -> str:
    """Google Gemini API 호출"""
    try:
        if "gemini-3" in model_config.model_id:
            from google import genai
            client = genai.Client(api_key=os.getenv(model_config.api_key_env))

            contents = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

            response = client.models.generate_content(
                model=model_config.model_id,
                contents=contents,
                config={
                    "system_instruction": system_prompt,
                    "temperature": model_config.temperature,
                    "max_output_tokens": model_config.max_tokens,
                }
            )
            return response.text
        else:
            import google.generativeai as genai
            genai.configure(api_key=os.getenv(model_config.api_key_env))

            model = genai.GenerativeModel(
                model_name=model_config.model_id,
                system_instruction=system_prompt
            )

            history = []
            for msg in messages[:-1]:
                role = "user" if msg["role"] == "user" else "model"
                history.append({"role": role, "parts": [msg["content"]]})

            chat = model.start_chat(history=history)
            response = chat.send_message(messages[-1]["content"])
            return response.text
    except Exception as e:
        return f"[Google Error] {str(e)}"


def call_llm(model_config: ModelConfig, messages: list, system_prompt: str) -> str:
    """LLM 호출 라우터"""
    if model_config.provider == "anthropic":
        return call_anthropic(model_config, messages, system_prompt)
    elif model_config.provider == "openai":
        return call_openai(model_config, messages, system_prompt)
    elif model_config.provider == "google":
        return call_google(model_config, messages, system_prompt)
    else:
        return f"[Error] Unknown provider: {model_config.provider}"


def call_dual_engine(role: str, messages: list, system_prompt: str) -> str:
    """듀얼 엔진 호출 및 병합 (레거시 - config.py DUAL_ENGINES 사용)"""
    config = DUAL_ENGINES.get(role)
    if not config:
        return f"[Error] Unknown dual engine role: {role}"

    response_1 = call_llm(config.engine_1, messages, system_prompt)
    response_2 = call_llm(config.engine_2, messages, system_prompt)

    if config.merge_strategy == "primary_fallback":
        if "[Error]" not in response_1:
            merged = f"""## {config.engine_1.name} (Primary)
{response_1}

---
## {config.engine_2.name} (Review)
{response_2}"""
        else:
            merged = response_2
    elif config.merge_strategy == "parallel":
        merged = f"""## {config.engine_1.name}
{response_1}

---
## {config.engine_2.name}
{response_2}"""
    else:
        merged = f"""## {config.engine_1.name}
{response_1}

---
## {config.engine_2.name}
{response_2}

---
**듀얼 엔진 분석 완료. 두 결과를 비교 검토하세요.**"""

    stream = get_stream()
    stream.log_dual_engine(role, messages[-1]["content"], response_1, response_2, merged)

    return merged


# =============================================================================
# 듀얼 엔진 V2 (Writer + Auditor 패턴)
# =============================================================================

def call_dual_engine_v2(
    role: str,
    messages: list,
    system_prompt: str
) -> Tuple[str, Dict[str, Any]]:
    """
    듀얼 엔진 V2: Writer + Auditor 패턴

    1단계: Writer가 초안 작성
    2단계: Auditor가 리뷰 및 수정 제안
    3단계: 의견 불일치시 병합 또는 위원회 소집

    Returns:
        (최종 응답, 메타데이터)
    """
    if role not in DUAL_ENGINE_ROLES:
        # 듀얼 엔진 역할이 아니면 단일 엔진으로 폴백
        return call_llm(MODELS.get("claude_sonnet", MODELS["claude_opus"]), messages, system_prompt), {"dual": False}

    config = DUAL_ENGINE_ROLES[role]
    writer_model = MODELS.get(config["writer"], MODELS["claude_sonnet"])
    auditor_model = MODELS.get(config["auditor"], MODELS["gpt_5_mini"])

    # 1단계: Writer 초안 작성
    print(f"[Dual-V2] {role} Writer ({writer_model.name}) 작업 중...")
    writer_response = call_llm(writer_model, messages, system_prompt)

    if "[Error]" in writer_response:
        return writer_response, {"dual": True, "error": "writer_failed"}

    # 2단계: Auditor 리뷰
    auditor_prompt = f"""당신은 {role} 작업의 Auditor(감사관)입니다.

Writer가 작성한 다음 결과물을 검토하세요:

=== WRITER 결과물 ===
{writer_response}
======================

검토 기준:
1. 논리적 오류/버그 확인
2. 누락된 엣지케이스 확인
3. 보안 취약점 확인
4. 개선 제안

출력 형식:
```yaml
verdict: "approve/revise/reject"
issues:
  - severity: "critical/high/medium/low"
    description: "문제 설명"
    fix: "수정 제안"
improvements:
  - "개선 사항 1"
  - "개선 사항 2"
final_comment: "최종 코멘트"
```
"""

    auditor_messages = messages.copy()
    auditor_messages.append({"role": "assistant", "content": writer_response})
    auditor_messages.append({"role": "user", "content": auditor_prompt})

    print(f"[Dual-V2] {role} Auditor ({auditor_model.name}) 리뷰 중...")
    auditor_response = call_llm(auditor_model, auditor_messages, system_prompt)

    # 결과 병합
    merged_response = f"""## 📝 Writer ({writer_model.name})
{writer_response}

---

## 🔍 Auditor ({auditor_model.name})
{auditor_response}

---
✅ **듀얼 엔진 검토 완료** ({config['description']})
"""

    # 메타데이터
    meta = {
        "dual": True,
        "writer_model": writer_model.name,
        "auditor_model": auditor_model.name,
        "role": role,
        "description": config["description"],
    }

    # 로그
    stream = get_stream()
    stream.log_dual_engine(role, messages[-1]["content"], writer_response, auditor_response, merged_response)

    return merged_response, meta


def call_vip_dual_engine(
    prefix: str,
    messages: list,
    system_prompt: str
) -> Tuple[str, Dict[str, Any]]:
    """
    VIP 듀얼 엔진: CEO 프리픽스 기반 VIP Writer + Auditor 패턴

    - 최고/ : Opus + Sonnet 크로스체크
    - 생각/ : GPT-5.2 Thinking + Opus 크로스체크
    - 검색/ : Perplexity + 4o-mini 팩트체크

    Returns:
        (최종 응답, 메타데이터)
    """
    if prefix not in VIP_DUAL_ENGINE:
        # VIP 프리픽스가 아니면 기본 모델로 폴백
        return call_llm(MODELS.get("claude_opus", list(MODELS.values())[0]), messages, system_prompt), {"dual": False, "vip": False}

    config = VIP_DUAL_ENGINE[prefix]
    writer_model = MODELS.get(config["writer"])
    auditor_model = MODELS.get(config["auditor"])

    if not writer_model:
        print(f"[VIP-Dual] Writer 모델 {config['writer']} 없음, 폴백")
        writer_model = MODELS.get("claude_opus", list(MODELS.values())[0])

    if not auditor_model:
        print(f"[VIP-Dual] Auditor 모델 {config['auditor']} 없음, 폴백")
        auditor_model = MODELS.get("claude_sonnet", MODELS.get("gpt_5_mini"))

    # 1단계: VIP Writer 작업
    print(f"[VIP-Dual] VIP Writer ({writer_model.name}) 작업 중...")
    writer_response = call_llm(writer_model, messages, system_prompt)

    if "[Error]" in writer_response:
        return writer_response, {"dual": True, "vip": True, "error": "writer_failed"}

    # 2단계: VIP Auditor 크로스체크
    auditor_prompt = f"""당신은 VIP 레벨의 Auditor(감사관)입니다.

다른 VIP 모델이 작성한 다음 결과물을 크로스체크하세요:

=== VIP WRITER 결과물 ===
{writer_response}
=========================

VIP 레벨 검토 기준:
1. 논리적 완결성 및 정확도
2. 누락된 관점/엣지케이스
3. CEO 의사결정에 미치는 영향
4. 리스크 요소 확인
5. 개선/보완 제안

출력 형식:
```yaml
verdict: "approve/revise/escalate"
confidence: 0-100
key_findings:
  - "핵심 발견 1"
  - "핵심 발견 2"
concerns:
  - severity: "critical/high/medium/low"
    description: "우려 사항"
recommendations:
  - "권장 사항 1"
  - "권장 사항 2"
final_assessment: "최종 평가 (2-3문장)"
```
"""

    auditor_messages = messages.copy()
    auditor_messages.append({"role": "assistant", "content": writer_response})
    auditor_messages.append({"role": "user", "content": auditor_prompt})

    print(f"[VIP-Dual] VIP Auditor ({auditor_model.name}) 크로스체크 중...")
    auditor_response = call_llm(auditor_model, auditor_messages, system_prompt)

    # 결과 병합
    merged_response = f"""## 📝 VIP Writer ({writer_model.name})
{writer_response}

---

## 🔍 VIP Auditor ({auditor_model.name})
{auditor_response}

---
✅ **VIP 듀얼 엔진 검토 완료** ({config['description']})
"""

    # 메타데이터
    meta = {
        "dual": True,
        "vip": True,
        "prefix": prefix,
        "writer_model": writer_model.name,
        "auditor_model": auditor_model.name,
        "description": config["description"],
    }

    # 로그
    stream = get_stream()
    stream.log_dual_engine(f"VIP-{prefix}", messages[-1]["content"], writer_response, auditor_response, merged_response)

    return merged_response, meta


# =============================================================================
# 위원회 호출 (Council Integration)
# =============================================================================

async def call_council_llm(
    system_prompt: str,
    user_message: str,
    temperature: float,
    persona_id: str = None,
    council_type: str = None
) -> str:
    """
    위원회 페르소나용 LLM 호출

    COUNCIL_MODEL_MAPPING에 따라 적절한 모델 선택
    """
    # 모델 선택 로직
    model_key = "gpt_5_mini"  # 기본값

    if council_type and persona_id:
        mapping = COUNCIL_MODEL_MAPPING.get(council_type, {})
        personas = mapping.get("personas", {})
        model_key = personas.get(persona_id, "gpt_5_mini")

    model_config = MODELS.get(model_key)
    if not model_config:
        model_config = MODELS["gpt_5_mini"] if "gpt_5_mini" in MODELS else list(MODELS.values())[0]

    # temperature 오버라이드
    original_temp = model_config.temperature
    model_config.temperature = temperature

    messages = [{"role": "user", "content": user_message}]
    response = call_llm(model_config, messages, system_prompt)

    # temperature 복원
    model_config.temperature = original_temp

    return response


def init_council_with_llm():
    """위원회에 LLM Caller 주입"""
    from src.infra.council import get_council

    council = get_council()

    async def council_llm_caller(
        system_prompt: str,
        user_message: str,
        temperature: float,
        persona_id: str = None,
        council_type: str = None
    ) -> str:
        """위원회 LLM 호출 (모델 매핑 지원)"""
        # 모델 선택 로직
        model_key = "gpt_5_mini"  # 기본값

        if council_type and persona_id:
            mapping = COUNCIL_MODEL_MAPPING.get(council_type, {})
            personas = mapping.get("personas", {})
            model_key = personas.get(persona_id, "gpt_5_mini")

        model_config = MODELS.get(model_key)
        if not model_config:
            model_config = MODELS.get("gpt_5_mini", list(MODELS.values())[0])

        print(f"[Council] {persona_id} → {model_config.name}")

        # 동기 호출을 비동기로 래핑
        def sync_call():
            # temperature 오버라이드
            original_temp = model_config.temperature
            model_config.temperature = temperature

            messages = [{"role": "user", "content": user_message}]
            response = call_llm(model_config, messages, system_prompt)

            # temperature 복원
            model_config.temperature = original_temp
            return response

        return await asyncio.get_event_loop().run_in_executor(None, sync_call)

    council.set_llm_caller(council_llm_caller)
    print("[Council] LLM Caller 주입 완료 (모델 매핑 활성화)")
    return council


def should_convene_council(agent_role: str, response: str, context: Dict = None) -> Optional[str]:
    """
    위원회 자동 소집 조건 판단

    Returns:
        위원회 유형 또는 None
    """
    context = context or {}

    # 1. 전략 변경 감지
    strategy_keywords = ["전략", "strategy", "방향", "decision", "결정", "plan"]
    if agent_role == "strategist" or any(kw in response.lower() for kw in strategy_keywords):
        if len(response) > 500:  # 긴 전략 응답
            return "strategy"

    # 2. 코드 패치 감지
    code_keywords = ["```python", "```javascript", "```typescript", "def ", "class ", "function "]
    if agent_role == "coder" or any(kw in response for kw in code_keywords):
        if "def " in response or "class " in response:
            return "code"

    # 3. 보안 관련 감지
    security_keywords = ["password", "api_key", "secret", "token", "auth", "보안", "취약점"]
    if any(kw in response.lower() for kw in security_keywords):
        return "security"

    # 4. 배포 관련 감지
    deploy_keywords = ["deploy", "배포", "production", "release", "push"]
    if any(kw in response.lower() for kw in deploy_keywords):
        return "deploy"

    # 5. 듀얼 엔진 의견 불일치 감지 (Auditor가 reject 판정)
    if "verdict: reject" in response.lower() or "verdict: revise" in response.lower():
        if agent_role == "coder":
            return "code"
        elif agent_role == "strategist":
            return "strategy"

    return None


async def convene_council_async(
    council_type: str,
    content: str,
    context: str = ""
) -> Dict:
    """
    비동기 위원회 소집

    Returns:
        판정 결과 딕셔너리
    """
    from src.infra.council import get_council, Verdict

    council = get_council()

    # LLM Caller가 설정되지 않았으면 초기화
    if council.llm_caller is None:
        init_council_with_llm()

    print(f"[Council] {council_type.upper()} 위원회 소집 중...")
    verdict = await council.convene(council_type, content, context)

    result = {
        "council_type": council_type,
        "verdict": verdict.verdict.value,
        "average_score": verdict.average_score,
        "score_std": verdict.score_std,
        "requires_ceo": verdict.requires_ceo,
        "summary": verdict.summary,
        "judges": [
            {
                "persona": j.persona_name,
                "icon": j.icon,
                "score": j.score,
                "reasoning": j.reasoning,
            }
            for j in verdict.judges
        ]
    }

    print(f"[Council] 판정: {verdict.verdict.value} (평균 {verdict.average_score}/10)")
    return result


def convene_council_sync(council_type: str, content: str, context: str = "") -> Dict:
    """동기 버전 위원회 소집"""
    return asyncio.run(convene_council_async(council_type, content, context))


# =============================================================================
# 루프 브레이커 (Loop Breaker)
# =============================================================================

class LoopBreaker:
    """
    에이전트 루프 감지 및 차단

    - MAX_STAGE_RETRY: 같은 단계 최대 재시도
    - MAX_TOTAL_STEPS: 전체 최대 단계
    - 반복 응답 감지 (유사도 기반)
    - CEO 에스컬레이션
    """

    def __init__(self):
        self.step_count = 0
        self.stage_retries: Dict[str, int] = {}
        self.response_history: list = []
        self.is_broken = False
        self.break_reason = None

    def reset(self):
        """브레이커 초기화"""
        self.step_count = 0
        self.stage_retries = {}
        self.response_history = []
        self.is_broken = False
        self.break_reason = None

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """두 텍스트의 유사도 계산 (간단한 Jaccard)"""
        if not text1 or not text2:
            return 0.0

        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def check_and_update(self, stage: str, response: str) -> Tuple[bool, Optional[str]]:
        """
        루프 체크 및 상태 업데이트

        Args:
            stage: 현재 단계 (예: "coder", "qa", "strategist")
            response: 에이전트 응답

        Returns:
            (should_break, break_reason): 중단해야 하면 True와 사유
        """
        config = LOOP_BREAKER_CONFIG

        # 1. 전체 단계 수 체크
        self.step_count += 1
        if self.step_count > config["MAX_TOTAL_STEPS"]:
            self.is_broken = True
            self.break_reason = f"MAX_TOTAL_STEPS 초과 ({self.step_count}/{config['MAX_TOTAL_STEPS']})"
            return True, self.break_reason

        # 2. 같은 단계 재시도 체크
        self.stage_retries[stage] = self.stage_retries.get(stage, 0) + 1
        if self.stage_retries[stage] > config["MAX_STAGE_RETRY"]:
            self.is_broken = True
            self.break_reason = f"MAX_STAGE_RETRY 초과: {stage} ({self.stage_retries[stage]}회)"
            return True, self.break_reason

        # 3. 반복 응답 감지
        for prev_response in self.response_history[-3:]:  # 최근 3개와 비교
            similarity = self._calculate_similarity(response, prev_response)
            if similarity > config["SIMILARITY_THRESHOLD"]:
                self.is_broken = True
                self.break_reason = f"반복 응답 감지 (유사도: {similarity:.2%})"
                return True, self.break_reason

        # 4. 응답 히스토리 저장
        self.response_history.append(response[:1000])  # 처음 1000자만

        return False, None

    def get_escalation_message(self) -> str:
        """CEO 에스컬레이션 메시지 생성"""
        return f"""
⚠️ **루프 브레이커 발동**

**사유**: {self.break_reason}
**진행 단계**: {self.step_count}회
**단계별 재시도**: {dict(self.stage_retries)}

---

**권장 조치**:
1. 현재 작업을 수동으로 검토하세요
2. 요청을 더 명확하게 재정의하세요
3. 작업 범위를 축소하세요

**자동 조치**: 루프가 중단되었습니다.
"""

    def should_escalate_to_ceo(self) -> bool:
        """CEO 에스컬레이션 필요 여부"""
        return self.is_broken and LOOP_BREAKER_CONFIG.get("ESCALATE_TO_CEO", True)


# 싱글톤 인스턴스
_loop_breaker: Optional[LoopBreaker] = None


def get_loop_breaker() -> LoopBreaker:
    """LoopBreaker 싱글톤"""
    global _loop_breaker
    if _loop_breaker is None:
        _loop_breaker = LoopBreaker()
    return _loop_breaker


def check_loop(stage: str, response: str) -> Tuple[bool, Optional[str]]:
    """루프 체크 헬퍼 함수"""
    return get_loop_breaker().check_and_update(stage, response)


# =============================================================================
# Agent Call
# =============================================================================

def strip_ceo_prefix(message: str) -> tuple[str, str]:
    """
    CEO 프리픽스 제거 및 실제 메시지 추출
    [PROJECT: xxx] 래퍼가 있어도 올바르게 처리

    Returns:
        (실제 메시지, 사용된 프리픽스 or None)

    예시:
        "최고/ 코드 리뷰해줘" → ("코드 리뷰해줘", "최고/")
        "[PROJECT: test]\n최고/ 리뷰해줘" → ("[PROJECT: test]\n리뷰해줘", "최고/")
        "생각/ 왜 안될까?" → ("왜 안될까?", "생각/")
        "검색/ 최신 버전" → ("최신 버전", "검색/")
        "일반 메시지" → ("일반 메시지", None)
    """
    prefixes = ["최고/", "생각/", "검색/"]

    # Case 1: 직접 프리픽스로 시작하는 경우
    for prefix in prefixes:
        if message.startswith(prefix):
            actual_message = message[len(prefix):].lstrip()
            return actual_message, prefix

    # Case 2: [PROJECT: xxx]\n 래퍼가 있는 경우
    if message.startswith("[PROJECT:"):
        lines = message.split("\n", 1)
        if len(lines) > 1:
            project_line = lines[0]  # "[PROJECT: xxx]"
            content_line = lines[1]   # "최고/ 실제 메시지"

            for prefix in prefixes:
                if content_line.startswith(prefix):
                    # 프리픽스 제거 후 [PROJECT:] 유지
                    actual_content = content_line[len(prefix):].lstrip()
                    return f"{project_line}\n{actual_content}", prefix

    return message, None


def extract_project_from_message(message: str) -> tuple[str, str]:
    """
    [PROJECT: xxx] 태그에서 프로젝트명 추출

    Returns:
        (project_name, message_without_project_tag)

    예시:
        "[PROJECT: test]\n안녕" → ("test", "안녕")
        "그냥 메시지" → (None, "그냥 메시지")
    """
    import re
    match = re.match(r'\[PROJECT:\s*([^\]]+)\]\s*\n?(.*)', message, re.DOTALL)
    if match:
        project = match.group(1).strip()
        remaining = match.group(2).strip()
        return project, remaining
    return None, message


def call_agent(
    message: str,
    agent_role: str,
    auto_execute: bool = True,
    use_translation: bool = True,
    use_router: bool = True,
    return_meta: bool = False,
    use_dual_engine: bool = True,   # 듀얼 엔진 사용 여부
    auto_council: bool = True,      # 위원회 자동 소집 여부
) -> str | tuple[str, dict]:
    """
    실제 LLM 호출 + [EXEC] 태그 자동 실행 + RAG 컨텍스트 주입 + 번역 + 스코어카드 로깅

    CEO 프리픽스 지원:
    - 최고/ : VIP-AUDIT (Opus 4.5) 강제
    - 생각/ : VIP-THINKING (GPT-5.2 Thinking Extend) 강제
    - 검색/ : RESEARCH (Perplexity) 강제

    Args:
        return_meta: True이면 (response, meta_dict) 튜플 반환

    Returns:
        str 또는 (str, dict): response 또는 (response, model_meta)
    """
    from src.core.session_state import get_current_session

    current_session_id = get_current_session()
    start_time = time_module.time()

    # 디버그: 입력 메시지 확인
    import sys
    sys.stderr.write(f"[DEBUG-INPUT] message[:50]={message[:50] if len(message) > 50 else message}\n")
    sys.stderr.write(f"[DEBUG-INPUT] message.startswith('최고/')={message.startswith('최고/')}\n")
    sys.stderr.flush()

    # [PROJECT: xxx] 태그에서 프로젝트 추출
    current_project, message_without_project = extract_project_from_message(message)
    if current_project:
        print(f"[Project] Detected: {current_project}")

    # CEO 프리픽스 체크 (라우팅용 원본 유지)
    actual_message, used_prefix = strip_ceo_prefix(message)

    router = get_router()
    routing = route_message(message, agent_role)  # 프리픽스 포함된 원본으로 라우팅

    # 모델 메타 정보 수집
    model_meta = {
        'model_name': routing.model_spec.name,
        'model_id': routing.model_spec.model_id,
        'tier': routing.model_tier,
        'reason': routing.reason,
        'provider': routing.model_spec.provider,
        'ceo_prefix': used_prefix,
    }

    # 프리픽스 사용 시 로그 표시
    if used_prefix:
        print(f"[CEO Prefix] '{used_prefix}' detected → VIP mode activated")

    print(f"[Router] {agent_role} → {routing.model_tier.upper()} ({routing.model_spec.name})")
    print(f"[Router] Reason: {routing.reason}")

    system_prompt = get_system_prompt(agent_role)
    if not system_prompt:
        return f"[Error] Unknown agent role: {agent_role}"

    # 프리픽스 제거된 실제 메시지 사용
    agent_message = actual_message
    if use_translation and rag.is_korean(actual_message):
        agent_message = rag.translate_for_agent(actual_message)
        print(f"[Translate] CEO→Agent: {len(actual_message)}자 → {len(agent_message)}자")

    if agent_role == "pm":
        try:
            rag_context = rag.build_context(
                agent_message,
                project=current_project,  # 프로젝트별 RAG 필터링
                top_k=5,
                use_gemini=True,
                language="en"
            )
            if rag_context:
                system_prompt = system_prompt + "\n\n" + rag_context
                print(f"[RAG] Context injected ({current_project or 'all'}): {len(rag_context)} chars")
        except Exception as e:
            print(f"[RAG] Context injection failed: {e}")

    messages = []
    if current_session_id:
        db_messages = db.get_messages(current_session_id)
        for msg in db_messages:
            if msg.get('agent') == agent_role:
                messages.append({
                    "role": msg['role'],
                    "content": msg['content']
                })

    messages.append({"role": "user", "content": agent_message})

    # 듀얼 엔진 메타데이터
    dual_meta = {"dual": False}
    council_result = None

    # 디버그: VIP 조건 체크 (flush=True로 즉시 출력, stderr로도 출력)
    import sys
    debug_msg = f"[DEBUG-VIP] use_dual_engine={use_dual_engine}, used_prefix='{used_prefix}', prefix_in_dict={used_prefix in VIP_DUAL_ENGINE if used_prefix else 'N/A'}"
    print(debug_msg, flush=True)
    sys.stderr.write(debug_msg + "\n")
    sys.stderr.flush()

    debug_msg2 = f"[DEBUG-VIP] VIP_DUAL_ENGINE keys: {list(VIP_DUAL_ENGINE.keys())}"
    print(debug_msg2, flush=True)
    sys.stderr.write(debug_msg2 + "\n")
    sys.stderr.flush()

    # =========================================================================
    # VIP 듀얼 엔진 모드 (CEO 프리픽스 사용 시)
    # =========================================================================
    if use_dual_engine and used_prefix and used_prefix in VIP_DUAL_ENGINE:
        print(f"[VIP-Dual] {used_prefix} VIP 듀얼 엔진 모드 활성화")
        response, dual_meta = call_vip_dual_engine(used_prefix, messages, system_prompt)

        # VIP 모드에서도 위원회 자동 소집 체크
        if auto_council:
            council_type = should_convene_council(agent_role, response)
            if council_type:
                print(f"[Council] VIP 자동 소집 트리거: {council_type}")
                try:
                    council_result = convene_council_sync(council_type, response, agent_message)
                    model_meta['council'] = council_result

                    # 위원회 결과를 응답에 추가
                    response += f"""

---

## 🏛️ {council_type.upper()} 위원회 판정

{council_result['summary']}

**상세 점수:**
"""
                    for judge in council_result['judges']:
                        response += f"- {judge['icon']} {judge['persona']}: {judge['score']}/10 - {judge['reasoning'][:100]}...\n"

                except Exception as e:
                    print(f"[Council] 소집 실패: {e}")

        stream = get_stream()
        stream.log("ceo", agent_role, "request", agent_message)
        stream.log(agent_role, "ceo", "response", response)

    # =========================================================================
    # 일반 듀얼 엔진 V2 사용 (use_dual_engine=True이고 역할이 지원되는 경우)
    # =========================================================================
    elif use_dual_engine and agent_role in DUAL_ENGINE_ROLES and not used_prefix:
        print(f"[Dual-V2] {agent_role} 듀얼 엔진 모드 활성화")
        response, dual_meta = call_dual_engine_v2(agent_role, messages, system_prompt)

        # 위원회 자동 소집 체크
        if auto_council:
            council_type = should_convene_council(agent_role, response)
            if council_type:
                print(f"[Council] 자동 소집 트리거: {council_type}")
                try:
                    council_result = convene_council_sync(council_type, response, agent_message)
                    model_meta['council'] = council_result

                    # 위원회 결과를 응답에 추가
                    response += f"""

---

## 🏛️ {council_type.upper()} 위원회 판정

{council_result['summary']}

**상세 점수:**
"""
                    for judge in council_result['judges']:
                        response += f"- {judge['icon']} {judge['persona']}: {judge['score']}/10 - {judge['reasoning'][:100]}...\n"

                except Exception as e:
                    print(f"[Council] 소집 실패: {e}")

        stream = get_stream()
        stream.log("ceo", agent_role, "request", agent_message)
        stream.log(agent_role, "ceo", "response", response)

    # =========================================================================
    # 레거시 라우터 모드 (듀얼 엔진 비활성화 시)
    # =========================================================================
    elif use_router:
        response = router.call_model(routing, messages, system_prompt)
        print(f"[Router] Called: {routing.model_spec.name}")

        stream = get_stream()
        stream.log("ceo", agent_role, "request", agent_message)
        stream.log(agent_role, "ceo", "response", response)

        # 라우터 모드에서도 위원회 자동 소집 체크
        if auto_council:
            council_type = should_convene_council(agent_role, response)
            if council_type:
                print(f"[Council] 자동 소집 트리거: {council_type}")
                try:
                    council_result = convene_council_sync(council_type, response, agent_message)
                    model_meta['council'] = council_result

                    response += f"""

---

## 🏛️ {council_type.upper()} 위원회 판정

{council_result['summary']}
"""
                except Exception as e:
                    print(f"[Council] 소집 실패: {e}")

    # =========================================================================
    # 레거시 모드 (use_router=False)
    # =========================================================================
    else:
        if agent_role in DUAL_ENGINES:
            response = call_dual_engine(agent_role, messages, system_prompt)
        else:
            model_config = SINGLE_ENGINES.get(agent_role)
            if model_config:
                response = call_llm(model_config, messages, system_prompt)
                stream = get_stream()
                stream.log("ceo", agent_role, "request", agent_message)
                stream.log(agent_role, "ceo", "response", response)
            else:
                return f"[Error] No engine configured for: {agent_role}"

    # 듀얼 엔진 메타 정보 병합
    model_meta['dual_engine'] = dual_meta

    if auto_execute and agent_role in ["coder", "pm"]:
        exec_results = executor.execute_all(response)
        if exec_results:
            exec_output = executor.format_results(exec_results)

            if agent_role == "pm":
                followup_prompt = f"""## EXEC 실행 결과

다음은 방금 요청한 명령어들의 실행 결과입니다:

{exec_output}

---

위 실행 결과를 분석하여 CEO에게 보고해주세요:
1. 핵심 발견 사항 (이모지 포함)
2. 다음 액션 제안 (있다면)
3. 주의점이나 리스크 (있다면)

간결하게 한글로 보고해주세요."""

                analysis_response = call_agent(
                    followup_prompt,
                    agent_role,
                    auto_execute=False,
                    use_translation=False
                )
                response += f"\n\n---\n\n## EXEC 결과 분석\n\n{analysis_response}"
            else:
                response += exec_output

    if use_translation and not rag.is_korean(response):
        response = rag.translate_for_ceo(response)
        print(f"[Translate] Agent→CEO: 한국어로 번역 완료")

    try:
        elapsed_ms = int((time_module.time() - start_time) * 1000)
        scorecard = get_scorecard()

        if use_router:
            model_name = routing.model_spec.model_id
            engine_type = f"router_{routing.model_tier}"
        elif agent_role in DUAL_ENGINES:
            model_name = DUAL_ENGINES[agent_role].engine_1.model_id
            engine_type = "dual"
        elif agent_role in SINGLE_ENGINES:
            model_name = SINGLE_ENGINES[agent_role].model_id
            engine_type = "single"
        else:
            model_name = "unknown"
            engine_type = "unknown"

        task_type_map = {
            'excavator': 'analysis',
            'coder': 'code',
            'strategist': 'strategy',
            'qa': 'test',
            'analyst': 'analysis',
            'researcher': 'research',
            'pm': 'orchestration'
        }

        scorecard.log_task(
            session_id=current_session_id or "no_session",
            task_id=f"task_{int(time_module.time())}",
            role=agent_role,
            engine=engine_type,
            model=model_name,
            task_type=task_type_map.get(agent_role, 'general'),
            task_summary=message[:100],
            input_tokens=len(message.split()) * 2,
            output_tokens=len(response.split()) * 2,
            latency_ms=elapsed_ms
        )
        print(f"[Scorecard] Logged: {agent_role} → {model_name} ({elapsed_ms}ms)")

        # 메타 정보에 추가 데이터 업데이트
        model_meta['latency_ms'] = elapsed_ms
    except Exception as e:
        print(f"[Scorecard] Error: {e}")

    if return_meta:
        return response, model_meta
    return response


def process_call_tags(pm_response: str, use_loop_breaker: bool = True) -> list:
    """
    PM 응답에서 [CALL:agent] 태그를 처리

    Args:
        pm_response: PM 응답 텍스트
        use_loop_breaker: 루프 브레이커 사용 여부

    Returns:
        에이전트 호출 결과 리스트
    """
    calls = executor.extract_call_info(pm_response)
    results = []

    # 루프 브레이커 초기화 (새 태스크 시작)
    if use_loop_breaker:
        loop_breaker = get_loop_breaker()
        # 새 PM 호출이면 리셋하지 않음 (연속 작업 추적)

    for call in calls:
        agent = call['agent']
        message = call['message']

        # 루프 브레이커 체크
        if use_loop_breaker:
            should_break, break_reason = check_loop(agent, message)
            if should_break:
                print(f"[LoopBreaker] 🛑 루프 감지: {break_reason}")
                escalation_msg = get_loop_breaker().get_escalation_message()

                results.append({
                    'agent': 'loop_breaker',
                    'message': break_reason,
                    'response': escalation_msg,
                    'is_break': True
                })

                # CEO 에스컬레이션
                if get_loop_breaker().should_escalate_to_ceo():
                    print("[LoopBreaker] ⚠️ CEO 에스컬레이션 필요")

                break  # 더 이상 에이전트 호출하지 않음

        print(f"[CALL] PM → {agent}: {message[:100]}...")

        response = call_agent(message, agent, auto_execute=True, use_translation=False)

        # 응답 기반 루프 체크
        if use_loop_breaker:
            should_break, break_reason = check_loop(f"{agent}_response", response)
            if should_break:
                print(f"[LoopBreaker] 🛑 반복 응답 감지: {break_reason}")
                response += f"\n\n---\n\n⚠️ **루프 브레이커 경고**: {break_reason}"

        results.append({
            'agent': agent,
            'message': message,
            'response': response
        })

        print(f"[CALL] {agent} 완료: {len(response)}자")

    return results


def build_call_results_prompt(call_results: list) -> str:
    """하위 에이전트 결과를 PM에게 전달할 프롬프트 생성"""
    prompt = "하위 에이전트들의 실행 결과입니다. 이 결과를 종합하여 CEO에게 보고해주세요.\n\n"

    for i, result in enumerate(call_results, 1):
        prompt += f"## {i}. {result['agent'].upper()} 응답\n"
        prompt += f"**요청:** {result['message'][:200]}...\n\n"
        prompt += f"**결과:**\n{result['response']}\n\n"
        prompt += "---\n\n"

    prompt += "위 결과들을 종합하여 CEO에게 한글로 보고해주세요."
    return prompt


def mock_agent_response(message: str, agent_role: str) -> str:
    """Mock 응답 (테스트용)"""
    responses = {
        'pm': f"""```yaml
sprint_plan:
  do:
    - "요청 분석: {message}"
    - "세부 태스크 분해"
    - "에이전트 할당"
  dont:
    - "희망회로 금지"
    - "뜬구름 계획 금지"

delegation:
  - agent: "excavator"
    task: "CEO 의도 발굴"
```

**Pragmatist + Skeptic 스탠스** - 구체화 필요""",

        'coder': f"**CODER** Mock 응답 - 요청: {message}",
        'excavator': f"**EXCAVATOR** Mock 응답 - 요청: {message}",
        'strategist': f"**STRATEGIST** Mock 응답 - 요청: {message}",
        'qa': f"**QA** Mock 응답 - 요청: {message}",
        'analyst': f"**ANALYST** Mock 응답 - 요청: {message}",
        'researcher': f"**RESEARCHER** Mock 응답 - 요청: {message}",
    }

    return responses.get(agent_role, f"**{agent_role.upper()}** Mock 응답 - 요청: {message}")
