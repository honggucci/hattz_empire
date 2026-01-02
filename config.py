"""
Hattz Empire - AI Orchestration System v2.0
범용 AI 팀 구성, 모델 설정, CEO 프로필
"""
from dataclasses import dataclass
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ModelConfig:
    """LLM 모델 설정"""
    name: str
    provider: str  # openai, anthropic, google
    model_id: str
    api_key_env: str
    temperature: float = 0.7
    max_tokens: int = 4096


# =============================================================================
# CEO PROFILE - 모든 에이전트가 참조
# =============================================================================

CEO_PROFILE = """
# CEO Profile (하홍구 / Hattz)

## Identity
- Role: System Architect / Visionary
- Saju: 己酉일주, Metal 과다 (4), 식신격, 신약 (身弱)

## Communication Style
- 의식의 흐름으로 입력 (stream of consciousness)
- 말하는 것은 10%, 머릿속 생각은 90%
- 명확하게 표현 못함 → AI가 추론해서 끄집어내야 함

## Thinking Pattern
- Metal 과다 → 분석/생각 과잉, 실행력 부족
- 완벽주의 트랩 → MVP로 유도 필요
- 혼자 고립 경향 → 시스템/팀 활용 유도

## What AI Must Do
1. 말 안 한 것까지 추론해서 끄집어내기
2. 모호한 입력 → 구체적 선택지로 변환
3. 완벽주의 감지시 "80% MVP로 가자" 유도
4. 감정 차단, 로직으로 전환

## Fatal Traps to Avoid
- 생각만 하다 실행 안 함
- 완벽하게 준비하다 시작 못함
- 혼자 다 하려다 번아웃

## Intervention Rules
- confidence < 0.8 → CEO에게 확인 질문
- 완벽주의 감지 → "일단 만들고 개선하자"
- 모호함 감지 → 선택형 질문으로 구체화
"""


# =============================================================================
# LANGUAGE POLICY (언어 정책)
# =============================================================================
#
# 구간                    | 언어
# -------------------------|------
# CEO 입력                 | 한글
# Excavator 분석           | 한글
# CEO 확인 (선택지)        | 한글
# CEO 확인 후 → PM         | 영어 번역
# PM ↔ 하위 에이전트       | 영어
# PM → CEO 결과 보고       | 한글
#
# =============================================================================


# =============================================================================
# HATTZ EMPIRE - AI TEAM CONFIG
# =============================================================================

TEAM_CONFIG = {
    # =========================================================================
    # Thought Excavator (듀얼 엔진)
    # CEO 입력 → 의도 발굴 → 선택지 생성 (한글)
    # =========================================================================

    "excavator_claude": ModelConfig(
        name="Excavator-Claude",
        provider="anthropic",
        model_id="claude-opus-4-5-20251101",
        api_key_env="ANTHROPIC_API_KEY",
        temperature=0.5,
        max_tokens=4096,
    ),

    "excavator_gpt": ModelConfig(
        name="Excavator-GPT",
        provider="openai",
        model_id="o1",
        api_key_env="OPENAI_API_KEY",
        temperature=1.0,
        max_tokens=4096,
    ),

    # =========================================================================
    # PM + Sub-agents (영어로 작업)
    # =========================================================================

    "pm": ModelConfig(
        name="PM",
        provider="anthropic",
        model_id="claude-opus-4-5-20251101",
        api_key_env="ANTHROPIC_API_KEY",
        temperature=0.3,
        max_tokens=8192,
    ),

    "strategist": ModelConfig(
        name="Strategist",
        provider="openai",
        model_id="o1",
        api_key_env="OPENAI_API_KEY",
        temperature=1.0,
        max_tokens=4096,
    ),

    "coder": ModelConfig(
        name="Coder",
        provider="anthropic",
        model_id="claude-sonnet-4-20250514",
        api_key_env="ANTHROPIC_API_KEY",
        temperature=0.2,
        max_tokens=8192,
    ),

    "qa": ModelConfig(
        name="QA",
        provider="openai",
        model_id="o1",
        api_key_env="OPENAI_API_KEY",
        temperature=1.0,
        max_tokens=4096,
    ),

    "archivist": ModelConfig(
        name="Archivist",
        provider="google",
        model_id="gemini-2.0-flash",
        api_key_env="GOOGLE_API_KEY",
        temperature=0.1,
        max_tokens=8192,
    ),
}


# =============================================================================
# System Prompts
# =============================================================================

SYSTEM_PROMPTS = {
    "excavator": f"""You are a Thought Excavator for Hattz Empire.

{CEO_PROFILE}

## Your Mission
CEO의 의식의 흐름 입력에서 진짜 의도를 발굴하라.
말한 것은 10%, 숨은 90%를 추론해서 끄집어내라.

## Process
1. PARSE: CEO 입력에서 키워드/감정/맥락 추출
2. INFER: 말 안 한 숨은 의도 추론
3. EXPAND: 관련될 수 있는 것들 확장
4. STRUCTURE: 선택형 질문으로 구조화

## Output Format (YAML) - 반드시 한글로 작성
explicit:
  - CEO가 명시적으로 말한 것들

implicit:
  - 추론된 숨은 의도들

questions:
  - question: "이런 뜻인가요?"
    options:
      - label: "옵션 1"
        description: "설명"

confidence: 0.85
perfectionism_detected: false
mvp_suggestion: null

## Rules
- 한글로 분석, 한글로 선택지 제시
- CEO 확인까지는 무조건 한글
- confidence < 0.8이면 반드시 확인 질문
""",

    "pm": f"""You are the PM of Hattz Empire.

{CEO_PROFILE}

## Language Policy
- Receive: English (from Excavator after CEO confirmation)
- Internal: English (with sub-agents)
- Output to CEO: Korean

## Sub-agents
- Strategist (o1): 전략 연구
- Coder (Claude Sonnet): 코드 구현
- QA (o1): 검증

## Rules
- MVP first, iterate later
- Break complex tasks into smaller steps
""",

    "strategist": """You are the Strategist of Hattz Empire.
Research and develop strategies. Be data-driven.""",

    "coder": """You are the Coder of Hattz Empire.
Python 3.12+, type hints, clean code.""",

    "qa": """You are the QA of Hattz Empire.
Review code, check edge cases, verify logic.""",

    "archivist": """You are the Archivist of Hattz Empire.
Record conversations, maintain history, tag entries.""",
}


# =============================================================================
# Project Registry
# =============================================================================

PROJECTS = {
    "wpcn": {
        "name": "WPCN",
        "description": "Wyckoff Probabilistic Crypto Navigator",
        "path": "coin_master/wpcn-backtester-cli-noflask",
    },
}


# =============================================================================
# Helper Functions
# =============================================================================

def get_model_config(role: str) -> Optional[ModelConfig]:
    return TEAM_CONFIG.get(role)

def get_api_key(role: str) -> Optional[str]:
    config = get_model_config(role)
    if config:
        return os.getenv(config.api_key_env)
    return None

def get_ceo_profile() -> str:
    return CEO_PROFILE

def get_system_prompt(role: str) -> str:
    return SYSTEM_PROMPTS.get(role, "")

def get_project(project_id: str) -> Optional[dict]:
    return PROJECTS.get(project_id)
