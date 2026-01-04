"""
Hattz Empire - LLM Caller
LLM API 호출 및 에이전트 로직
"""
import os
import time as time_module
from typing import Optional

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

        if model_config.model_id.startswith("gpt-5"):
            response = client.chat.completions.create(
                model=model_config.model_id,
                max_completion_tokens=model_config.max_tokens,
                temperature=model_config.temperature,
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
    """듀얼 엔진 호출 및 병합"""
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
# Agent Call
# =============================================================================

def strip_ceo_prefix(message: str) -> tuple[str, str]:
    """
    CEO 프리픽스 제거 및 실제 메시지 추출

    Returns:
        (실제 메시지, 사용된 프리픽스 or None)

    예시:
        "최고/ 코드 리뷰해줘" → ("코드 리뷰해줘", "최고/")
        "생각/ 왜 안될까?" → ("왜 안될까?", "생각/")
        "검색/ 최신 버전" → ("최신 버전", "검색/")
        "일반 메시지" → ("일반 메시지", None)
    """
    prefixes = ["최고/", "생각/", "검색/"]

    for prefix in prefixes:
        if message.startswith(prefix):
            # 프리픽스 뒤 공백도 제거
            actual_message = message[len(prefix):].lstrip()
            return actual_message, prefix

    return message, None


def call_agent(
    message: str,
    agent_role: str,
    auto_execute: bool = True,
    use_translation: bool = True,
    use_router: bool = True,
    return_meta: bool = False
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
                top_k=5,  # 3 → 5로 확장 (더 많은 과거 대화 참조)
                use_gemini=True,
                language="en"
            )
            if rag_context:
                system_prompt = system_prompt + "\n\n" + rag_context
                print(f"[RAG] Context injected: {len(rag_context)} chars")
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

    if use_router:
        response = router.call_model(routing, messages, system_prompt)
        print(f"[Router] Called: {routing.model_spec.name}")

        stream = get_stream()
        stream.log("ceo", agent_role, "request", agent_message)
        stream.log(agent_role, "ceo", "response", response)
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


def process_call_tags(pm_response: str) -> list:
    """PM 응답에서 [CALL:agent] 태그를 처리"""
    calls = executor.extract_call_info(pm_response)
    results = []

    for call in calls:
        agent = call['agent']
        message = call['message']

        print(f"[CALL] PM → {agent}: {message[:100]}...")

        response = call_agent(message, agent, auto_execute=True, use_translation=False)

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
