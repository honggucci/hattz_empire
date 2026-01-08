"""
Hattz Empire - LLM Caller
LLM API 호출 및 에이전트 로직

2026.01.04 업데이트:
- 듀얼 엔진 와이어링 (Writer + Auditor 패턴)
- 위원회 자동 소집 + 모델 할당
- 루프 브레이커 추가

2026.01.07 업데이트:
- Analyst 파일 컨텍스트 주입 (Gemini는 파일시스템 접근 불가)
"""
import os
import time as time_module
import asyncio
import glob as glob_module
from typing import Optional, Tuple, Dict, Any

import sys
from pathlib import Path

# 루트 디렉토리를 path에 추가
root_dir = Path(__file__).parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from config import (
    MODELS, DUAL_ENGINES, SINGLE_ENGINES,
    get_system_prompt, ModelConfig,
    ENFORCE_OUTPUT_CONTRACT, CONTRACT_EXEMPT_AGENTS  # v2.5
)

# v2.6: Server Logger 연동
from src.utils.server_logger import log_llm_call, log_error, logger

# v2.6.1: Flow Monitor 연동 (부트로더 원칙 준수 모니터링)
from src.services.flow_monitor import get_flow_monitor

# v2.5: Output Contract + Format Gate
from src.core.contracts import (
    validate_output,
    get_contract,
    get_schema_prompt,
    extract_json_from_output,
    FormatGateError,
    CONTRACT_REGISTRY
)


# =============================================================================
# Analyst 파일 컨텍스트 수집 (Gemini는 파일시스템 접근 불가)
# =============================================================================

# 프로젝트별 루트 경로 매핑
PROJECT_PATHS = {
    "hattz_empire": Path(__file__).parent.parent.parent,  # 현재 프로젝트
    "wpcn": Path("C:/Users/hahonggu/Desktop/coin_master/projects/wpcn-backtester-cli-noflask"),
}


def collect_project_context(project_name: str, max_files: int = 50, max_chars: int = 30000) -> str:
    """
    프로젝트 파일 구조와 주요 파일 내용을 수집하여 Analyst에게 전달할 컨텍스트 생성

    Args:
        project_name: 프로젝트명 (hattz_empire, wpcn 등)
        max_files: 최대 파일 수
        max_chars: 최대 문자 수

    Returns:
        str: 프로젝트 컨텍스트 문자열
    """
    project_root = PROJECT_PATHS.get(project_name)
    if not project_root or not project_root.exists():
        return f"[ERROR] 프로젝트 '{project_name}' 경로를 찾을 수 없습니다."

    context_parts = []
    context_parts.append(f"# 프로젝트: {project_name}")
    context_parts.append(f"# 경로: {project_root}")
    context_parts.append("")

    # 1. 파일 구조 수집
    context_parts.append("## 파일 구조")
    py_files = list(project_root.glob("**/*.py"))
    md_files = list(project_root.glob("**/*.md"))

    # __pycache__, .git, node_modules 제외
    exclude_dirs = {'__pycache__', '.git', 'node_modules', '.venv', 'venv', '.claude'}
    py_files = [f for f in py_files if not any(d in str(f) for d in exclude_dirs)]
    md_files = [f for f in md_files if not any(d in str(f) for d in exclude_dirs)]

    context_parts.append(f"- Python 파일: {len(py_files)}개")
    context_parts.append(f"- Markdown 파일: {len(md_files)}개")
    context_parts.append("")

    # 2. 디렉토리별 파일 목록
    context_parts.append("## 디렉토리 구조")
    dirs = {}
    for f in py_files[:max_files]:
        rel_path = f.relative_to(project_root)
        parent = str(rel_path.parent)
        if parent not in dirs:
            dirs[parent] = []
        dirs[parent].append(rel_path.name)

    for dir_name, files in sorted(dirs.items()):
        context_parts.append(f"  {dir_name}/")
        for fname in sorted(files)[:10]:  # 디렉토리당 최대 10개
            context_parts.append(f"    - {fname}")
        if len(files) > 10:
            context_parts.append(f"    ... 외 {len(files) - 10}개")
    context_parts.append("")

    # 3. 주요 파일 내용 (CLAUDE.md, README.md, config.py 등)
    context_parts.append("## 주요 파일 내용")
    important_files = [
        "CLAUDE.md", "README.md", "config.py", "app.py",
        "src/core/llm_caller.py", "src/api/chat.py"
    ]

    total_chars = len("\n".join(context_parts))
    for fname in important_files:
        if total_chars >= max_chars:
            context_parts.append(f"\n[TRUNCATED] 최대 {max_chars}자 초과로 중단")
            break

        fpath = project_root / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding='utf-8')
                # 파일당 최대 5000자
                if len(content) > 5000:
                    content = content[:5000] + "\n... (truncated)"
                context_parts.append(f"\n### {fname}")
                context_parts.append("```")
                context_parts.append(content)
                context_parts.append("```")
                total_chars += len(content) + 100
            except Exception as e:
                context_parts.append(f"\n### {fname}")
                context_parts.append(f"[ERROR] 읽기 실패: {e}")

    # 4. 테스트 파일 수 (품질 지표)
    test_files = [f for f in py_files if 'test' in f.name.lower()]
    context_parts.append(f"\n## 테스트 파일: {len(test_files)}개")
    for tf in test_files[:5]:
        context_parts.append(f"  - {tf.relative_to(project_root)}")

    return "\n".join(context_parts)


# =============================================================================
# 듀얼 엔진 + 위원회 설정
# =============================================================================

# 듀얼 엔진 역할 정의 (Writer + Auditor + Stamp)
# v2.4.3: GPT-5 mini 제거, Stamp = Sonnet 4 통일
# - Opus: "만드는 손" (coder)
# - Sonnet 4: "검열/도장" (auditor, stamp)
# - GPT-5.2 Thinking: "뇌" (strategist/excavator writer)
# - Gemini Flash: "수집기" (researcher writer)
DUAL_ENGINE_ROLES = {
    "coder": {
        "writer": "claude_cli",           # CLI Opus - silent_implementer
        "auditor": "claude_cli",           # CLI Sonnet 4 - devils_advocate_reviewer
        "stamp": "claude_cli",             # CLI Sonnet 4 - strict_verdict_clerk
        "description": "코드 작성 + 리뷰 + 도장",
        "writer_profile": "coder",         # Opus
        "auditor_profile": "reviewer",     # Sonnet 4
        "stamp_profile": "reviewer",       # Sonnet 4
    },
    "strategist": {
        "writer": "gpt_thinking",          # GPT-5.2 Thinking Extended - systems_architect (뇌)
        "auditor": "claude_cli",           # CLI Sonnet 4 - reality_check_cto
        "stamp": "claude_cli",             # CLI Sonnet 4 - strict_verdict_clerk
        "description": "전략 수립 (뇌) + 검증 + 도장",
        "auditor_profile": "reviewer",     # Sonnet 4
        "stamp_profile": "reviewer",       # Sonnet 4
    },
    "qa": {
        "writer": "claude_cli",            # CLI Sonnet 4 - test_designer
        "auditor": "claude_cli",           # CLI Sonnet 4 - breaker_qa
        "stamp": "claude_cli",             # CLI Sonnet 4 - strict_verdict_clerk
        "description": "테스트 생성 + 검증 + 도장",
        "writer_profile": "qa",            # Sonnet 4
        "auditor_profile": "reviewer",     # Sonnet 4
        "stamp_profile": "reviewer",       # Sonnet 4
    },
    "researcher": {
        "writer": "perplexity_sonar",      # Perplexity Sonar Pro - source_harvester (검색 특화)
        "auditor": "claude_cli",           # CLI Sonnet 4 - fact_sentinel
        "stamp": "claude_cli",             # CLI Sonnet 4 - strict_verdict_clerk
        "description": "리서치 (Perplexity) + 팩트체크 + 도장",
        "auditor_profile": "reviewer",     # Sonnet 4
        "stamp_profile": "reviewer",       # Sonnet 4
    },
    "excavator": {
        "writer": "gpt_thinking",          # GPT-5.2 Thinking Extended - requirements_interrogator (뇌)
        "auditor": "claude_cli",           # CLI Sonnet 4 - ambiguity_sniffer_reviewer
        "stamp": "claude_cli",             # CLI Sonnet 4 - strict_verdict_clerk
        "description": "CEO 의도 발굴 (뇌) + 검증 + 도장",
        "auditor_profile": "reviewer",     # Sonnet 4
        "stamp_profile": "reviewer",       # Sonnet 4
    },
}

# VIP_DUAL_ENGINE 삭제됨 (v2.4.4 - CEO 프리픽스 기능 제거)

# 위원회별 모델 할당 - CLI 기반 (Claude Code CLI 사용)
# v2.4: PM 전용 단일 위원회 - 7개 페르소나 전원 참여
COUNCIL_MODEL_MAPPING = {
    "pm": {
        "personas": {
            "skeptic": "cli",           # 🤨 회의론자 - 근거 요구
            "perfectionist": "cli",     # 🔬 완벽주의자 - 디테일 집착
            "pragmatist": "cli",        # 🎯 현실주의자 - 실행 중심
            "pessimist": "cli",         # 😰 비관론자 - 최악 가정
            "optimist": "cli",          # 😊 낙관론자 - 가능성 발견
            "devils_advocate": "cli",   # 😈 악마의 변호인 - 반대 의견
            "security_hawk": "cli",     # 🦅 보안 감시자 - 취약점 탐지
        },
        "tiebreaker": "cli",
        "use_cli": True,  # CLI 사용
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
from src.services import cost_tracker


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
    """Anthropic API → CLI 리다이렉트 (v2.4.3 - API 비용 0원)"""
    from src.services.cli_supervisor import call_claude_cli

    # model_id로 프로필 결정 (opus=coder, sonnet=reviewer)
    profile = "coder" if "opus" in model_config.model_id.lower() else "reviewer"

    return call_claude_cli(messages, system_prompt, profile)


def call_openai(model_config: ModelConfig, messages: list, system_prompt: str) -> tuple[str, int, int]:
    """
    OpenAI API 호출

    GPT-5.2 Extended Thinking 지원:
    - reasoning_effort: "high" or "xhigh" → 실제 reasoning 토큰 사용
    - reasoning_effort가 none이 아니면 temperature/top_p 사용 불가

    Returns:
        (response_text, input_tokens, output_tokens)
    """
    try:
        import openai
        client = openai.OpenAI(api_key=os.getenv(model_config.api_key_env))

        # 프롬프트 주입 (thinking_mode일 때 추가 지침)
        if getattr(model_config, 'thinking_mode', False):
            system_prompt = THINKING_EXTEND_PREFIX + system_prompt

        full_messages = [{"role": "system", "content": system_prompt}]
        full_messages.extend(messages)

        # GPT-5.2 계열: reasoning_effort 지원 + temperature 충돌 방지
        if model_config.model_id.startswith("gpt-5"):
            # reasoning_effort 가져오기 (AGENT_CONFIG에서 설정)
            reasoning_effort = getattr(model_config, 'reasoning_effort', None)

            # reasoning_effort가 설정되어 있으면 (high/xhigh)
            # → temperature/top_p 사용 불가 (OpenAI 제약)
            if reasoning_effort and reasoning_effort != "none":
                print(f"[OpenAI] GPT-5.2 Thinking Extended: reasoning_effort={reasoning_effort}")
                response = client.chat.completions.create(
                    model=model_config.model_id,
                    max_completion_tokens=model_config.max_tokens,
                    reasoning_effort=reasoning_effort,  # ← 실제 Extended Thinking 활성화
                    messages=full_messages
                )
            else:
                # reasoning_effort 없으면 기본 호출 (temperature 사용 안 함)
                response = client.chat.completions.create(
                    model=model_config.model_id,
                    max_completion_tokens=model_config.max_tokens,
                    messages=full_messages
                )
        else:
            # GPT-4 이하: 기존 방식
            response = client.chat.completions.create(
                model=model_config.model_id,
                max_tokens=model_config.max_tokens,
                temperature=model_config.temperature,
                messages=full_messages
            )

        # 토큰 사용량 추출
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        return response.choices[0].message.content, input_tokens, output_tokens
    except Exception as e:
        return f"[OpenAI Error] {str(e)}", 0, 0


def call_google(model_config: ModelConfig, messages: list, system_prompt: str) -> tuple[str, int, int]:
    """
    Google Gemini API 호출

    Returns:
        (response_text, input_tokens, output_tokens)
    """
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

            # Gemini 3 토큰 사용량 추출
            input_tokens = 0
            output_tokens = 0
            if hasattr(response, 'usage_metadata'):
                input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
                output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0

            return response.text, input_tokens, output_tokens
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

            # Gemini 1.5/2.0 토큰 사용량 추출 (근사치)
            input_tokens = 0
            output_tokens = 0
            if hasattr(response, 'usage_metadata'):
                input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
                output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0

            return response.text, input_tokens, output_tokens
    except Exception as e:
        return f"[Google Error] {str(e)}", 0, 0


def call_llm(
    model_config: ModelConfig,
    messages: list,
    system_prompt: str,
    session_id: str = None,
    agent_role: str = None
) -> str:
    """
    LLM 호출 라우터 + 비용 기록

    Args:
        model_config: 모델 설정
        messages: 메시지 리스트
        system_prompt: 시스템 프롬프트
        session_id: 세션 ID (비용 기록용)
        agent_role: 에이전트 역할 (비용 기록용)

    Returns:
        LLM 응답 텍스트
    """
    input_tokens = 0
    output_tokens = 0
    response_text = ""

    if model_config.provider == "anthropic":
        response_text = call_anthropic(model_config, messages, system_prompt)
        # CLI 호출은 토큰 추적 안 함 (무료)
    elif model_config.provider == "openai":
        response_text, input_tokens, output_tokens = call_openai(model_config, messages, system_prompt)
    elif model_config.provider == "google":
        response_text, input_tokens, output_tokens = call_google(model_config, messages, system_prompt)
    elif model_config.provider == "claude_cli":
        # Claude Code CLI provider (EXEC tier) - 무료
        from src.services.cli_supervisor import call_claude_cli
        response_text = call_claude_cli(messages, system_prompt, getattr(model_config, 'profile', 'coder'))
    else:
        return f"[Error] Unknown provider: {model_config.provider}"

    # 비용 기록 (토큰이 있고 에러가 아닌 경우)
    if input_tokens > 0 or output_tokens > 0:
        if not response_text.startswith("[") or not "Error]" in response_text:
            try:
                cost_tracker.record_api_call(
                    session_id=session_id or "unknown",
                    agent_role=agent_role or "unknown",
                    model_id=model_config.model_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens
                )
                print(f"[CostTracker] Recorded: {model_config.model_id} ({input_tokens}in/{output_tokens}out)")
            except Exception as e:
                print(f"[CostTracker] Failed to record: {e}")

    return response_text


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

# Auditor JSON 스키마 (출력 강제용)
AUDITOR_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["APPROVE", "REVISE", "REJECT"]},
        "must_fix": {"type": "array", "items": {"type": "string"}},
        "nice_to_fix": {"type": "array", "items": {"type": "string"}},
        "rewrite_instructions": {"type": "string"},
        "requires_council": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 100}
    },
    "required": ["verdict", "must_fix", "confidence"]
}


def _extract_json_from_text(text: str) -> dict:
    """
    텍스트에서 JSON 객체 추출 (v2.3.3)

    마크다운 코드블록, 순수 JSON 모두 지원
    """
    import json
    import re

    # 1차: ```json ... ``` 블록 찾기
    json_block = re.search(r'```(?:json)?\s*\n?({[\s\S]*?})\s*\n?```', text)
    if json_block:
        try:
            return json.loads(json_block.group(1))
        except json.JSONDecodeError:
            pass

    # 2차: 순수 JSON 객체 찾기 (첫 '{' ~ 마지막 '}')
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # 3차: 실패 시 기본값 반환
    return {
        "verdict": "REVISE",
        "must_fix": ["JSON 파싱 실패 - 원본 텍스트 확인 필요"],
        "nice_to_fix": [],
        "rewrite_instructions": text[:500],
        "requires_council": False,
        "confidence": 0
    }


def dual_engine_write_audit_rewrite(
    role: str,
    messages: list,
    system_prompt: str,
    max_rewrite: int = 3,
    session_id: str = None
) -> Tuple[str, Dict[str, Any]]:
    """
    듀얼 엔진 V3: Write → Audit → Rewrite 패턴 (v2.3.3)

    기존 V2의 "붙여넣기" 방식 대신:
    1. Writer가 초안 작성
    2. Auditor가 JSON으로 verdict 반환
    3. REVISE면 Writer가 피드백 반영하여 재작성 (최대 max_rewrite회)
    4. APPROVE면 초안 그대로 반환
    5. REJECT면 Council 소집 트리거

    Returns:
        (최종 응답, 메타데이터)
    """
    if role not in DUAL_ENGINE_ROLES:
        from src.services.cli_supervisor import CLISupervisor
        cli = CLISupervisor()
        result = cli.call_cli(messages[-1]["content"], system_prompt, "coder")
        return (result.output if result.success else f"[Error] {result.error}"), {"dual": False}

    config = DUAL_ENGINE_ROLES[role]
    writer_key = config["writer"]
    auditor_key = config["auditor"]
    writer_profile = config.get("writer_profile", "coder")
    auditor_profile = config.get("auditor_profile", "reviewer")

    rewrite_count = 0
    audit_history = []
    format_validated = False

    # 1단계: Writer 초안 작성 (v2.5 Format Gate 적용)
    print(f"[Dual-V3] {role} Writer ({writer_key}) 초안 작성 중...")
    draft, writer_name, format_validated = _call_with_contract(
        writer_key, messages, system_prompt, writer_profile, role, session_id=session_id
    )

    if "[Error]" in draft or "[CLI Error]" in draft:
        return draft, {"dual": True, "error": "writer_failed", "version": "v3"}

    # v2.5: Format Gate 경고 표시
    if not format_validated and "[FORMAT_WARNING]" in draft:
        print(f"[Dual-V3] Writer 출력 형식 검증 실패, Auditor에게 전달")
        draft = draft.replace("[FORMAT_WARNING] ", "")

    while rewrite_count < max_rewrite:
        # 2단계: Auditor 리뷰 (JSON 출력 강제) - v2.4.2 강화된 프롬프트
        auditor_prompt = f"""당신은 {role} 작업의 Auditor(감사관)입니다.

## 절대 규칙 (위반 시 즉시 무효)
1. **수정 금지**: "내가 고쳐줄게요" 절대 금지. 오직 판정만.
2. **인용 필수**: 모든 지적은 파일경로/함수명/라인/에러 재현 커맨드로 증거 제시.
   - "느낌상 별로" 같은 감상문 = 즉시 REJECT 처리됨
3. **Lazy Approval**: must_fix는 Severity HIGH만 허용:
   - 보안 취약점 (인증/권한 우회, injection)
   - 데이터 손상/유실 가능성
   - 크래시/무한루프
   - 핵심 경로 테스트 부재
   - 명백한 요구사항 불일치
4. **스타일/취향/변수명** = nice_to_fix로만 (반려 사유 불가)

=== WRITER 결과물 ===
{draft}
======================

**반드시 아래 JSON 형식으로만 응답하세요 (코드블록 없이 순수 JSON):**

{{
  "verdict": "APPROVE | REVISE | REJECT",
  "must_fix": [
    {{
      "severity": "HIGH",
      "issue": "문제 설명",
      "evidence": "파일:라인 또는 재현 커맨드",
      "fix_hint": "수정 방향 (코드 아님)"
    }}
  ],
  "nice_to_fix": ["권장사항 (반려 사유 아님)"],
  "tests_to_add": ["추가할 테스트 케이스명"],
  "evidence": ["검증에 사용한 파일/함수/라인 목록"],
  "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
  "requires_council": false,
  "confidence": 85,
  "rewrite_instructions": "REVISE일 때만: Writer에게 전달할 구체적 지시"
}}

## Verdict 기준
- **APPROVE**: must_fix 없음, 요구사항 충족
- **REVISE**: must_fix 1개 이상 (HIGH severity만)
- **REJECT**: 근본적 설계 결함 또는 요구사항 완전 불일치 → Council 필수
"""

        auditor_messages = messages.copy()
        auditor_messages.append({"role": "assistant", "content": draft})
        auditor_messages.append({"role": "user", "content": auditor_prompt})

        print(f"[Dual-V3] {role} Auditor ({auditor_key}) 리뷰 중...")
        auditor_response, auditor_name = _call_model_or_cli(
            auditor_key, auditor_messages, system_prompt, auditor_profile, session_id, f"{role}_auditor"
        )

        # JSON 파싱
        audit = _extract_json_from_text(auditor_response)
        audit_history.append(audit)

        verdict = audit.get("verdict", "REVISE")
        print(f"[Dual-V3] Auditor verdict: {verdict} (confidence: {audit.get('confidence', 'N/A')})")

        # APPROVE: 초안 그대로 반환
        if verdict == "APPROVE":
            meta = {
                "dual": True,
                "version": "v3",
                "writer_model": writer_name,
                "auditor_model": auditor_name,
                "role": role,
                "verdict": "APPROVE",
                "rewrite_count": rewrite_count,
                "audit_history": audit_history,
                "requires_council": audit.get("requires_council", False),
                "format_validated": format_validated,  # v2.5
            }
            return draft, meta

        # REJECT: Council 트리거와 함께 반환
        if verdict == "REJECT":
            meta = {
                "dual": True,
                "version": "v3",
                "writer_model": writer_name,
                "auditor_model": auditor_name,
                "role": role,
                "verdict": "REJECT",
                "rewrite_count": rewrite_count,
                "audit_history": audit_history,
                "requires_council": True,  # REJECT면 무조건 Council
                "rejection_reason": audit.get("must_fix", []),
                "format_validated": format_validated,  # v2.5
            }
            # REJECT 시에도 draft 반환 (Council에서 검토용)
            return f"""⚠️ **AUDITOR REJECT**

{draft}

---
**Rejection Reasons:**
{chr(10).join(f'- {item}' for item in audit.get('must_fix', []))}
""", meta

        # REVISE: Writer에게 피드백 전달하여 재작성
        rewrite_count += 1
        print(f"[Dual-V3] Rewrite #{rewrite_count}...")

        rewrite_prompt = f"""이전 초안에 대해 Auditor가 다음 수정을 요청했습니다:

**반드시 수정할 항목:**
{chr(10).join(f'- {item}' for item in audit.get('must_fix', []))}

**Auditor 지시사항:**
{audit.get('rewrite_instructions', '위 항목들을 수정해주세요.')}

---

**이전 초안:**
{draft}

---

위 피드백을 반영하여 수정된 버전을 작성해주세요.
"""

        rewrite_messages = messages.copy()
        rewrite_messages.append({"role": "user", "content": rewrite_prompt})

        # v2.5 Format Gate 적용
        draft, writer_name, format_validated = _call_with_contract(
            writer_key, rewrite_messages, system_prompt, writer_profile, role
        )

        if "[Error]" in draft or "[CLI Error]" in draft:
            return draft, {"dual": True, "error": "rewrite_failed", "version": "v3"}

        # v2.5: Format Gate 경고 제거
        if "[FORMAT_WARNING]" in draft:
            draft = draft.replace("[FORMAT_WARNING] ", "")

    # max_rewrite 소진 시 마지막 draft 반환
    meta = {
        "dual": True,
        "version": "v3",
        "writer_model": writer_name,
        "auditor_model": auditor_name,
        "role": role,
        "verdict": "MAX_REWRITE_EXHAUSTED",
        "rewrite_count": rewrite_count,
        "audit_history": audit_history,
        "requires_council": True,  # max_rewrite 소진 시 Council 권장
        "format_validated": format_validated,  # v2.5
    }
    return draft, meta


def _call_model_or_cli(
    model_key: str,
    messages: list,
    system_prompt: str,
    profile: str = "coder",
    session_id: str = None,
    agent_role: str = None
) -> Tuple[str, str]:
    """
    모델 또는 CLI 호출 헬퍼 함수

    Args:
        model_key: 모델 키 ("claude_cli" 또는 MODELS 키)
        messages: 메시지 리스트
        system_prompt: 시스템 프롬프트
        profile: CLI 프로필 (coder/qa/reviewer)
        session_id: 세션 ID (비용 추적용)
        agent_role: 에이전트 역할 (비용 추적용)

    Returns:
        (응답, 모델명)
    """
    if model_key == "claude_cli":
        from src.services.cli_supervisor import CLISupervisor
        cli = CLISupervisor()
        # 메시지에서 마지막 user 메시지 추출
        user_message = messages[-1]["content"] if messages else ""
        result = cli.call_cli(
            prompt=user_message,
            system_prompt=system_prompt,
            profile=profile,
            task_context=f"Dual Engine: {profile}"
        )
        if result.success:
            return result.output, f"Claude CLI ({profile})"
        else:
            return f"[CLI Error] {result.error or result.abort_reason}", f"Claude CLI ({profile})"
    else:
        model = MODELS.get(model_key, MODELS.get("gpt_5_mini"))
        return call_llm(model, messages, system_prompt, session_id, agent_role), model.name


def _call_with_contract(
    model_key: str,
    messages: list,
    system_prompt: str,
    profile: str,
    agent_role: str,
    max_retry: int = 3,
    session_id: str = None
) -> Tuple[str, str, bool]:
    """
    v2.5 Format Gate: LLM 호출 + Output Contract 검증

    Args:
        model_key: 모델 키
        messages: 메시지 리스트
        system_prompt: 시스템 프롬프트
        profile: CLI 프로필
        agent_role: 에이전트 역할 (coder, qa, reviewer 등)
        max_retry: 최대 재시도 횟수
        session_id: 세션 ID (비용 추적용)

    Returns:
        (응답, 모델명, 검증성공여부)
    """
    contract = get_contract(agent_role)

    # Contract가 없는 역할은 기존 방식으로 처리
    if not contract:
        response, model_name = _call_model_or_cli(model_key, messages, system_prompt, profile, session_id, agent_role)
        return response, model_name, True

    # Schema 프롬프트를 시스템 프롬프트에 주입
    schema_prompt = get_schema_prompt(agent_role)
    enhanced_prompt = f"{system_prompt}\n\n{schema_prompt}"

    last_error = None

    for attempt in range(max_retry):
        response, model_name = _call_model_or_cli(model_key, messages, enhanced_prompt, profile, session_id, agent_role)

        # 에러 응답은 검증 스킵
        if "[Error]" in response or "[CLI Error]" in response:
            return response, model_name, False

        # Output Contract 검증
        success, validated, error = validate_output(response, agent_role)

        if success:
            print(f"[FormatGate] {agent_role} 검증 성공 (attempt {attempt + 1})")
            # Pydantic 모델을 JSON 문자열로 반환
            if hasattr(validated, 'model_dump_json'):
                return validated.model_dump_json(indent=2), model_name, True
            return response, model_name, True

        # 검증 실패 시 에러 메시지로 재시도
        last_error = error
        print(f"[FormatGate] {agent_role} 검증 실패 ({attempt + 1}/{max_retry}): {error[:100]}")

        if attempt < max_retry - 1:
            # 에러 피드백을 포함한 재시도 메시지
            retry_prompt = f"""이전 응답이 형식 오류로 거부되었습니다.

**오류 내용:**
{error}

**올바른 형식으로 다시 응답해주세요.**

{schema_prompt}"""
            messages = messages.copy()
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": retry_prompt})

    # 최대 재시도 초과 - 원본 응답 반환 + 경고
    print(f"[FormatGate] {agent_role} 최대 재시도 초과, 원본 응답 사용")
    return f"[FORMAT_WARNING] {response}", model_name, False


def call_dual_engine_v2(
    role: str,
    messages: list,
    system_prompt: str
) -> Tuple[str, Dict[str, Any]]:
    """
    듀얼 엔진 V2: Writer + Auditor 패턴
    v2.4: Claude CLI 지원 추가

    1단계: Writer가 초안 작성 (API 또는 CLI)
    2단계: Auditor가 리뷰 및 수정 제안 (API 또는 CLI)
    3단계: 의견 불일치시 병합 또는 위원회 소집

    Returns:
        (최종 응답, 메타데이터)
    """
    if role not in DUAL_ENGINE_ROLES:
        # 듀얼 엔진 역할이 아니면 CLI로 폴백
        from src.services.cli_supervisor import CLISupervisor
        cli = CLISupervisor()
        result = cli.call_cli(messages[-1]["content"], system_prompt, "coder")
        return (result.output if result.success else f"[Error] {result.error}"), {"dual": False}

    config = DUAL_ENGINE_ROLES[role]
    writer_key = config["writer"]
    auditor_key = config["auditor"]
    writer_profile = config.get("writer_profile", "coder")
    auditor_profile = config.get("auditor_profile", "reviewer")

    # 1단계: Writer 초안 작성
    print(f"[Dual-V2] {role} Writer ({writer_key}) 작업 중...")
    writer_response, writer_name = _call_model_or_cli(writer_key, messages, system_prompt, writer_profile)

    if "[Error]" in writer_response or "[CLI Error]" in writer_response:
        return writer_response, {"dual": True, "error": "writer_failed"}

    # 2단계: Auditor 리뷰 - v2.4.2 강화된 프롬프트
    auditor_prompt = f"""당신은 {role} 작업의 Auditor(감사관)입니다.

## 절대 규칙 (위반 시 즉시 무효)
1. **수정 금지**: "내가 고쳐줄게요" 절대 금지. 오직 판정만.
2. **인용 필수**: 모든 지적은 파일경로/함수명/라인/에러 재현 커맨드로 증거 제시.
3. **Lazy Approval**: must_fix는 Severity HIGH만 허용:
   - 보안 취약점, 데이터 손상, 크래시, 테스트 부재, 요구사항 불일치
4. **스타일/취향** = nice_to_fix로만 (반려 사유 불가)

=== WRITER 결과물 ===
{writer_response}
======================

**반드시 아래 JSON 형식으로만 응답 (코드블록 없이):**

{{
  "verdict": "APPROVE | REVISE | REJECT",
  "must_fix": [{{"severity": "HIGH", "issue": "문제", "evidence": "파일:라인", "fix_hint": "방향"}}],
  "nice_to_fix": ["권장사항"],
  "evidence": ["검증한 파일/함수 목록"],
  "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
  "requires_council": false,
  "confidence": 85
}}
"""

    auditor_messages = messages.copy()
    auditor_messages.append({"role": "assistant", "content": writer_response})
    auditor_messages.append({"role": "user", "content": auditor_prompt})

    print(f"[Dual-V2] {role} Auditor ({auditor_key}) 리뷰 중...")
    auditor_response, auditor_name = _call_model_or_cli(auditor_key, auditor_messages, system_prompt, auditor_profile)

    # 결과 병합
    merged_response = f"""## 📝 Writer ({writer_name})
{writer_response}

---

## 🔍 Auditor ({auditor_name})
{auditor_response}

---
✅ **듀얼 엔진 검토 완료** ({config['description']})
"""

    # 메타데이터
    meta = {
        "dual": True,
        "writer_model": writer_name,
        "auditor_model": auditor_name,
        "role": role,
        "description": config["description"],
    }

    # 로그
    stream = get_stream()
    stream.log_dual_engine(role, messages[-1]["content"], writer_response, auditor_response, merged_response)

    return merged_response, meta


# call_vip_dual_engine 삭제됨 (v2.4.4 - CEO 프리픽스 기능 제거)


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
    위원회 페르소나용 CLI 호출 (v2.3.2: API → CLI 전환)

    모든 위원회 멤버가 Claude Code CLI를 사용
    """
    from src.services.cli_supervisor import CLISupervisor

    print(f"[Council-CLI] {persona_id} → Claude Code CLI")

    cli_supervisor = CLISupervisor()

    # CLI 호출 (reviewer 프로필 - 읽기 전용)
    result = cli_supervisor.call_cli(
        prompt=user_message,
        system_prompt=system_prompt,
        profile="reviewer",
        task_context=f"Council: {council_type}, Persona: {persona_id}"
    )

    if result.success:
        return result.output
    else:
        error_msg = result.error or result.abort_reason or "CLI 호출 실패"
        print(f"[Council-CLI] Error: {error_msg}")
        return f"[CLI ERROR] {error_msg}"


def init_council_with_llm():
    """위원회에 CLI Caller 주입 (v2.3.2: API → CLI 전환)"""
    from src.infra.council import get_council, reset_council
    from src.services.cli_supervisor import CLISupervisor

    # 항상 싱글톤 리셋 후 새로 생성 (llm_caller 확실히 설정)
    reset_council()
    council = get_council()

    cli_supervisor = CLISupervisor()

    async def council_cli_caller(
        system_prompt: str,
        user_message: str,
        temperature: float,
        persona_id: str = None,
        council_type: str = None
    ) -> str:
        """위원회 CLI 호출 (Claude Code CLI 사용)"""
        print(f"[Council-CLI] {persona_id} → Claude Code CLI")

        # 동기 CLI 호출을 비동기로 래핑
        def sync_cli_call():
            # CLI 프로필 결정 (v2.4.2: 위원회는 council 프로필 사용)
            profile = "council"

            # CLI 호출
            result = cli_supervisor.call_cli(
                prompt=user_message,
                system_prompt=system_prompt,
                profile=profile,
                task_context=f"Council: {council_type}, Persona: {persona_id}"
            )

            if result.success:
                # v2.4.2: None 체크 추가
                return result.output or "[CLI ERROR] 빈 출력"
            else:
                # CLI 실패 시 에러 메시지 반환
                error_msg = result.error or result.abort_reason or "CLI 호출 실패"
                print(f"[Council-CLI] Error: {error_msg}")
                return f"[CLI ERROR] {error_msg}"

        return await asyncio.get_event_loop().run_in_executor(None, sync_cli_call)

    council.set_llm_caller(council_cli_caller)
    print("[Council] CLI Caller 주입 완료 (Claude Code CLI 사용)")
    return council


def should_convene_council(
    agent_role: str,
    response: str,
    context: Dict = None,
    dual_meta: Dict = None
) -> Optional[str]:
    """
    위원회 자동 소집 조건 판단 (v2.3.3 - JSON 기반)

    PM만 위원회 소집 가능. 다른 에이전트는 위원회 불필요.

    v2.3.3 변경:
    - 문자열 탐지 대신 dual_meta의 requires_council 필드 우선 사용
    - 문자열 탐지는 폴백으로만 사용

    Args:
        agent_role: 에이전트 역할
        response: 에이전트 응답
        context: 추가 컨텍스트
        dual_meta: 듀얼 엔진 메타데이터 (requires_council 필드 포함)

    Returns:
        "pm" 또는 None
    """
    # PM만 위원회 소집 가능
    if agent_role != "pm":
        return None

    context = context or {}
    dual_meta = dual_meta or {}

    # =========================================================================
    # 1순위: dual_meta의 requires_council 필드 (JSON 기반)
    # =========================================================================
    if dual_meta.get("requires_council") is True:
        print(f"[Council] JSON 기반 트리거: requires_council=True (verdict: {dual_meta.get('verdict', 'N/A')})")
        return "pm"

    # REJECT verdict면 무조건 Council
    if dual_meta.get("verdict") == "REJECT":
        print("[Council] JSON 기반 트리거: verdict=REJECT")
        return "pm"

    # MAX_REWRITE_EXHAUSTED면 Council 권장
    if dual_meta.get("verdict") == "MAX_REWRITE_EXHAUSTED":
        print("[Council] JSON 기반 트리거: MAX_REWRITE_EXHAUSTED")
        return "pm"

    # =========================================================================
    # 2순위: audit_history에서 requires_council 체크
    # =========================================================================
    audit_history = dual_meta.get("audit_history", [])
    for audit in audit_history:
        if audit.get("requires_council") is True:
            print(f"[Council] audit_history 트리거: requires_council=True")
            return "pm"

    # =========================================================================
    # 3순위: 문자열 탐지 (폴백 - 레거시 호환)
    # =========================================================================
    # 중요한 의사결정 감지 (전략/방향/결정)
    decision_keywords = ["전략", "strategy", "방향", "decision", "결정", "plan", "아키텍처", "architecture"]
    if any(kw in response.lower() for kw in decision_keywords):
        if len(response) > 500:  # 긴 응답일 때만
            print("[Council] 문자열 탐지 트리거: decision keywords")
            return "pm"

    # 리스크 관련 감지
    risk_keywords = ["risk", "리스크", "위험", "주의", "경고", "warning", "critical"]
    if any(kw in response.lower() for kw in risk_keywords):
        # 단순 언급이 아닌 실제 경고인지 확인 (문맥 체크)
        risk_patterns = ["⚠️", "❌", "🚨", "REJECT", "HOLD", "critical issue"]
        if any(p in response for p in risk_patterns):
            print("[Council] 문자열 탐지 트리거: risk patterns")
            return "pm"

    return None


def _determine_trigger_source(dual_meta: Dict) -> str:
    """
    dual_meta에서 Council 트리거 소스 결정 (v2.3.3)

    Returns:
        트리거 소스 문자열
    """
    if not dual_meta:
        return "manual"

    verdict = dual_meta.get("verdict", "")

    if verdict == "REJECT":
        return "json_verdict_reject"
    elif verdict == "MAX_REWRITE_EXHAUSTED":
        return "json_verdict_max_rewrite"
    elif dual_meta.get("requires_council") is True:
        return "json_requires_council"

    # audit_history에서 requires_council 확인
    audit_history = dual_meta.get("audit_history", [])
    for audit in audit_history:
        if audit.get("requires_council") is True:
            return "json_requires_council"

    return "keyword_detection"


async def convene_council_async(
    council_type: str,
    content: str,
    context: str = "",
    trigger_source: str = "manual",
    original_verdict_json: Dict = None
) -> Dict:
    """
    비동기 위원회 소집 (v2.3.3 - JSON 기반 트리거 지원)

    Args:
        council_type: 위원회 유형
        content: 검토 대상 내용
        context: 추가 컨텍스트
        trigger_source: 트리거 소스
            - "manual": 수동 소집
            - "json_requires_council": JSON requires_council=True
            - "json_verdict_reject": JSON verdict=REJECT
            - "json_verdict_max_rewrite": MAX_REWRITE_EXHAUSTED
        original_verdict_json: 트리거된 원본 JSON verdict

    Returns:
        판정 결과 딕셔너리
    """
    from src.infra.council import get_council, Verdict

    council = get_council()

    # LLM Caller가 설정되지 않았으면 초기화
    if council.llm_caller is None:
        init_council_with_llm()

    print(f"[Council] {council_type.upper()} 위원회 소집 중... (trigger: {trigger_source})")
    verdict = await council.convene(
        council_type,
        content,
        context,
        trigger_source=trigger_source,
        original_verdict_json=original_verdict_json
    )

    result = {
        "council_type": council_type,
        "verdict": verdict.verdict.value,
        "average_score": verdict.average_score,
        "score_std": verdict.score_std,
        "requires_ceo": verdict.requires_ceo,
        "summary": verdict.summary,
        "trigger_source": verdict.trigger_source,
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


def convene_council_sync(
    council_type: str,
    content: str,
    context: str = "",
    trigger_source: str = "manual",
    original_verdict_json: Dict = None
) -> Dict:
    """동기 버전 위원회 소집"""
    return asyncio.run(convene_council_async(
        council_type, content, context, trigger_source, original_verdict_json
    ))


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
    _internal_call: bool = False,   # v2.3.3: PM 내부 호출 플래그 (하위 에이전트 호출용)
) -> str | tuple[str, dict]:
    """
    실제 LLM 호출 + [EXEC] 태그 자동 실행 + RAG 컨텍스트 주입 + 번역 + 스코어카드 로깅

    v2.3.3 변경:
    - CEO는 PM만 호출 가능. 하위 에이전트(coder/qa/strategist 등)는 PM이 호출.
    - _internal_call=True면 PM이 하위 에이전트를 호출하는 것이므로 허용.

    v2.4.4 변경:
    - CEO 프리픽스 기능 제거 (최고/, 생각/, 검색/)
    - PM은 Opus 4.5로 고정 (SAFETY 티어)

    Args:
        return_meta: True이면 (response, meta_dict) 튜플 반환
        _internal_call: True면 PM 내부 호출 (하위 에이전트 허용)

    Returns:
        str 또는 (str, dict): response 또는 (response, model_meta)
    """
    from src.core.session_state import get_current_session

    # =========================================================================
    # v2.3.3: CEO → PM만 허용. 하위 에이전트 직접 호출 차단.
    # =========================================================================
    ALLOWED_CEO_AGENTS = ["pm"]  # CEO가 직접 호출 가능한 에이전트
    SUB_AGENTS = ["coder", "qa", "strategist", "analyst", "researcher", "excavator"]

    if not _internal_call and agent_role in SUB_AGENTS:
        print(f"[BLOCKED] CEO → {agent_role} 직접 호출 차단. PM을 통해 호출하세요.")
        error_msg = f"""❌ **직접 호출 차단됨**

CEO는 하위 에이전트(`{agent_role}`)를 직접 호출할 수 없습니다.

**올바른 흐름:**
1. CEO → PM에게 요청
2. PM이 TaskSpec 생성 → 하위 에이전트에 위임

**예시:**
- ❌ "코더야 버그 수정해" (직접 호출)
- ✅ "버그 수정해줘" (PM이 coder에게 위임)
"""
        if return_meta:
            return error_msg, {"blocked": True, "reason": "direct_subagent_call"}
        return error_msg

    current_session_id = get_current_session()
    start_time = time_module.time()

    # 디버그: 입력 메시지 확인
    import sys
    sys.stderr.write(f"[DEBUG-INPUT] message[:50]={message[:50] if len(message) > 50 else message}\n")
    sys.stderr.write(f"[DEBUG-INPUT] agent_role={agent_role}, _internal_call={_internal_call}\n")
    sys.stderr.flush()

    # [PROJECT: xxx] 태그에서 프로젝트 추출
    current_project, message_without_project = extract_project_from_message(message)
    if current_project:
        print(f"[Project] Detected: {current_project}")

    router = get_router()
    routing = route_message(message, agent_role)

    # 모델 메타 정보 수집
    model_meta = {
        'model_name': routing.model_spec.name,
        'model_id': routing.model_spec.model_id,
        'tier': routing.model_tier,
        'reason': routing.reason,
        'provider': routing.model_spec.provider,
    }

    print(f"[Router] {agent_role} → {routing.model_tier.upper()} ({routing.model_spec.name})")
    print(f"[Router] Reason: {routing.reason}")

    system_prompt = get_system_prompt(agent_role)
    if not system_prompt:
        return f"[Error] Unknown agent role: {agent_role}"

    # 메시지 처리
    agent_message = message
    if use_translation and rag.is_korean(message):
        agent_message = rag.translate_for_agent(message)
        print(f"[Translate] CEO→Agent: {len(message)}자 → {len(agent_message)}자")

    # =========================================================================
    # v2.5: 에이전트별 RAG 컨텍스트 주입 (agent_filter 활용)
    # - PM: 전체 검색 (agent_filter=None)
    # - Coder/QA/Strategist: 에이전트별 필터링 (관련 컨텍스트만)
    # =========================================================================
    RAG_ENABLED_AGENTS = ["pm", "coder", "qa", "strategist", "researcher"]

    if agent_role in RAG_ENABLED_AGENTS:
        try:
            # PM은 전체 검색, 나머지는 에이전트별 필터
            agent_filter = None if agent_role == "pm" else agent_role
            top_k = 5 if agent_role == "pm" else 3  # PM은 더 많은 컨텍스트

            rag_context = rag.build_context(
                agent_message,
                project=current_project,
                agent_filter=agent_filter,
                top_k=top_k,
                use_gemini=True,
                language="en",
                session_id=current_session_id
            )
            if rag_context:
                system_prompt = system_prompt + "\n\n" + rag_context
                filter_info = f"agent={agent_filter}" if agent_filter else "all"
                print(f"[RAG] Context injected ({current_project or 'all'}, {filter_info}): {len(rag_context)} chars")
        except Exception as e:
            print(f"[RAG] Context injection failed: {e}")

    # =========================================================================
    # v2.4.1: Analyst 파일 컨텍스트 주입 (Gemini는 파일시스템 접근 불가)
    # =========================================================================
    if agent_role == "analyst" and current_project:
        try:
            project_context = collect_project_context(current_project)
            if project_context and not project_context.startswith("[ERROR]"):
                agent_message = f"""## 프로젝트 파일 컨텍스트 (자동 수집)

{project_context}

---

## 분석 요청

{agent_message}"""
                print(f"[Analyst] 프로젝트 컨텍스트 주입: {len(project_context)} chars")
            else:
                print(f"[Analyst] 프로젝트 컨텍스트 수집 실패: {project_context}")
        except Exception as e:
            print(f"[Analyst] 컨텍스트 주입 실패: {e}")

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

    # =========================================================================
    # 듀얼 엔진 V3 사용 (Write → Audit → Rewrite 패턴)
    # =========================================================================
    if use_dual_engine and agent_role in DUAL_ENGINE_ROLES:
        print(f"[Dual-V3] {agent_role} Write-Audit-Rewrite 패턴 활성화")
        response, dual_meta = dual_engine_write_audit_rewrite(agent_role, messages, system_prompt, session_id=current_session_id)

        # 위원회 자동 소집 체크 (dual_meta 전달) + FAIL 시 재수정 루프
        MAX_COUNCIL_RETRY = 2  # 위원회 재수정 최대 횟수
        council_retry = 0

        if auto_council:
            council_type = should_convene_council(agent_role, response, dual_meta=dual_meta)

            while council_type and council_retry < MAX_COUNCIL_RETRY:
                # v2.3.3: trigger_source 결정
                trigger_source = _determine_trigger_source(dual_meta)
                print(f"[Council] 자동 소집 트리거: {council_type} (source: {trigger_source}, retry: {council_retry})")
                try:
                    council_result = convene_council_sync(
                        council_type, response, agent_message,
                        trigger_source=trigger_source,
                        original_verdict_json=dual_meta.get("audit_history", [{}])[-1] if dual_meta.get("audit_history") else None
                    )
                    model_meta['council'] = council_result

                    # v2.4: FAIL이면 재수정 요청
                    if council_result['verdict'] == 'fail' and council_retry < MAX_COUNCIL_RETRY - 1:
                        council_retry += 1
                        print(f"[Council] FAIL - 재수정 요청 ({council_retry}/{MAX_COUNCIL_RETRY})")

                        # 위원회 피드백으로 재수정 요청
                        concerns = [j.get('reasoning', '')[:200] for j in council_result['judges'] if j.get('score', 10) < 7]
                        feedback = "\n".join(concerns[:3]) if concerns else council_result['summary']

                        rewrite_prompt = f"""위원회에서 다음 문제를 지적했습니다:

{feedback}

위 피드백을 반영하여 응답을 수정해주세요."""

                        rewrite_messages = messages.copy()
                        rewrite_messages.append({"role": "assistant", "content": response})
                        rewrite_messages.append({"role": "user", "content": rewrite_prompt})

                        # 재수정 호출
                        response, dual_meta = dual_engine_write_audit_rewrite(agent_role, rewrite_messages, system_prompt, session_id=current_session_id)
                        council_type = should_convene_council(agent_role, response, dual_meta=dual_meta)
                        continue

                    # PASS 또는 최대 재시도 도달 - 결과 추가하고 종료
                    response += f"""

---

## 🏛️ {council_type.upper()} 위원회 판정

{council_result['summary']}

**상세 점수:**
"""
                    for judge in council_result['judges']:
                        response += f"- {judge['icon']} {judge['persona']}: {judge['score']}/10 - {judge['reasoning'][:100]}...\n"
                    break

                except Exception as e:
                    print(f"[Council] 소집 실패: {e}")
                    break

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
    # v2.4: SINGLE_ENGINES에서 "claude_cli" 문자열 지원
    # =========================================================================
    else:
        if agent_role in DUAL_ENGINES:
            response = call_dual_engine(agent_role, messages, system_prompt)
        else:
            model_config = SINGLE_ENGINES.get(agent_role)
            if model_config:
                # v2.4: claude_cli 문자열인 경우 CLI 호출
                if model_config == "claude_cli":
                    from config import CLI_PROFILES
                    profile = CLI_PROFILES.get(agent_role, "reviewer")
                    response, _ = _call_model_or_cli("claude_cli", messages, system_prompt, profile, current_session_id, agent_role)
                else:
                    response = call_llm(model_config, messages, system_prompt, current_session_id, agent_role)
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

        # v2.6: Server Logger에 LLM 호출 기록
        log_llm_call(
            agent=agent_role,
            provider=model_meta.get('provider', 'unknown'),
            model=model_name,
            tokens=model_meta.get('input_tokens', 0) + model_meta.get('output_tokens', 0),
            cost=model_meta.get('cost', 0.0),
            duration_ms=elapsed_ms,
            success=True,
            session_id=current_session_id
        )
    except Exception as e:
        print(f"[Scorecard] Error: {e}")
        log_error(f"Scorecard logging failed: {e}", agent=agent_role, exc_info=False)

    # =========================================================================
    # v2.6.1: Flow Monitor - 부트로더 원칙 준수 모니터링
    # - 역할 침범, 잡담, JSON 계약 검증
    # =========================================================================
    flow_monitor = get_flow_monitor()
    flow_result = flow_monitor.validate_output(agent_role, response, current_session_id or "no_session")
    model_meta['flow_monitor'] = flow_result

    if flow_result['violations']:
        print(f"[FlowMonitor] WARN {agent_role} violation {len(flow_result['violations'])}건: {flow_result['violations'][:2]}")
    else:
        print(f"[FlowMonitor] OK {agent_role} output validated")

    # =========================================================================
    # v2.5: Output Contract 검증 (형식 게이트)
    # - CONTRACT_EXEMPT_AGENTS: Perplexity, Gemini 등 JSON 강제 불가 에이전트 제외
    # - ENFORCE_OUTPUT_CONTRACT: True면 Fail Fast, False면 Soft Landing
    # - ABORT 메시지는 Contract 검증 건너뜀
    # =========================================================================
    is_abort_response = response.strip().startswith("# ABORT:")
    if agent_role in CONTRACT_REGISTRY and agent_role not in CONTRACT_EXEMPT_AGENTS and not is_abort_response:
        success, validated_or_raw, error_msg = validate_output(response, agent_role)
        if success:
            print(f"[FormatGate] OK {agent_role} output validated")
            model_meta['format_validated'] = True
            model_meta['validated_output'] = validated_or_raw.model_dump() if hasattr(validated_or_raw, 'model_dump') else None
        else:
            print(f"[FormatGate] FAIL {agent_role} format error: {error_msg[:100]}")
            model_meta['format_validated'] = False
            model_meta['format_error'] = error_msg

            # Fail Fast 모드: 환경변수 ENFORCE_OUTPUT_CONTRACT=true 시 예외 발생
            if ENFORCE_OUTPUT_CONTRACT:
                raise FormatGateError(
                    f"[{agent_role}] Output Contract 위반: {error_msg[:200]}"
                )
    elif is_abort_response:
        print(f"[FormatGate] SKIP {agent_role} - ABORT response")

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
                print(f"[LoopBreaker] STOP loop detected: {break_reason}")
                escalation_msg = get_loop_breaker().get_escalation_message()

                results.append({
                    'agent': 'loop_breaker',
                    'message': break_reason,
                    'response': escalation_msg,
                    'is_break': True
                })

                # CEO 에스컬레이션
                if get_loop_breaker().should_escalate_to_ceo():
                    print("[LoopBreaker] WARN CEO escalation required")

                break  # 더 이상 에이전트 호출하지 않음

        print(f"[CALL] PM → {agent}: {message[:100]}...")

        # PM이 서브에이전트 호출 시 _internal_call=True (CEO 직접 호출 차단 우회)
        response = call_agent(message, agent, auto_execute=True, use_translation=False, _internal_call=True)

        # 응답 기반 루프 체크
        if use_loop_breaker:
            should_break, break_reason = check_loop(f"{agent}_response", response)
            if should_break:
                print(f"[LoopBreaker] STOP repeated response: {break_reason}")
                response += f"\n\n---\n\n**[LoopBreaker Warning]**: {break_reason}"

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
