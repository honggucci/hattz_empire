"""
Hattz Empire - Flask Web Interface
다른 LLM처럼 채팅 인터페이스
"""
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
import json
import time
import os
from datetime import datetime
from typing import Generator, Optional
from pathlib import Path
from dotenv import load_dotenv

# .env를 가장 먼저 로드 (override=True로 기존 환경변수 덮어쓰기)
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path, override=True)

from config import (
    MODELS, DUAL_ENGINES, SINGLE_ENGINES, PROJECTS,
    get_system_prompt, CEO_PROFILE, get_api_key, ModelConfig
)
from stream import get_stream, get_tracker
import database as db
import executor
import rag
from auth import init_login, get_user, verify_password, User

# Agent Chain (듀얼 엔진 에이전트 체인)
try:
    from agent_chain import get_chain, ChainResult, TaskType
    AGENT_CHAIN_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Agent chain not available: {e}")
    AGENT_CHAIN_AVAILABLE = False

# =============================================================================
# LLM API Clients
# =============================================================================

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


def call_openai(model_config: ModelConfig, messages: list, system_prompt: str) -> str:
    """OpenAI API 호출"""
    try:
        import openai
        client = openai.OpenAI(api_key=os.getenv(model_config.api_key_env))

        # Thinking Mode: system prompt 강화
        if getattr(model_config, 'thinking_mode', False):
            system_prompt = THINKING_EXTEND_PREFIX + system_prompt

        full_messages = [{"role": "system", "content": system_prompt}]
        full_messages.extend(messages)

        # GPT-5.x 모델은 max_completion_tokens 사용
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
    """Google Gemini API 호출 (Gemini 3 새 SDK 지원)"""
    try:
        # Gemini 3는 새로운 SDK 방식 사용
        if "gemini-3" in model_config.model_id:
            from google import genai
            client = genai.Client(api_key=os.getenv(model_config.api_key_env))

            # 메시지 변환
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
            # Gemini 2.x 이하 기존 방식
            import google.generativeai as genai
            genai.configure(api_key=os.getenv(model_config.api_key_env))

            model = genai.GenerativeModel(
                model_name=model_config.model_id,
                system_instruction=system_prompt
            )

            # 메시지 변환
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

    # Engine 1 호출
    response_1 = call_llm(config.engine_1, messages, system_prompt)

    # Engine 2 호출
    response_2 = call_llm(config.engine_2, messages, system_prompt)

    # 병합 전략
    if config.merge_strategy == "primary_fallback":
        # Primary 응답 사용, 에러면 fallback
        if "[Error]" not in response_1:
            merged = f"""## {config.engine_1.name} (Primary)
{response_1}

---
## {config.engine_2.name} (Review)
{response_2}"""
        else:
            merged = response_2
    elif config.merge_strategy == "parallel":
        # 둘 다 표시
        merged = f"""## {config.engine_1.name}
{response_1}

---
## {config.engine_2.name}
{response_2}"""
    else:  # consensus
        # 둘 다 표시 + 합의점 요청
        merged = f"""## {config.engine_1.name}
{response_1}

---
## {config.engine_2.name}
{response_2}

---
**⚠️ 듀얼 엔진 분석 완료. 두 결과를 비교 검토하세요.**"""

    # 로그 기록
    stream = get_stream()
    stream.log_dual_engine(role, messages[-1]["content"], response_1, response_2, merged)

    return merged

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "hattz-empire-secret-key-2024")

# Flask-Login 초기화
init_login(app)

# 현재 세션 ID (기본값 None, 첫 메시지에서 생성)
current_session_id = None


# =============================================================================
# Authentication Routes
# =============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """로그인 페이지"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)

        if verify_password(username, password):
            user = get_user(username)
            login_user(user, remember=bool(remember))
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            error = "잘못된 사용자명 또는 비밀번호입니다."

    return render_template('login.html', error=error)


@app.route('/logout')
@login_required
def logout():
    """로그아웃"""
    logout_user()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    """메인 채팅 페이지"""
    return render_template('chat.html',
                          models=MODELS,
                          dual_engines=DUAL_ENGINES,
                          single_engines=SINGLE_ENGINES)


@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    """
    채팅 API (non-streaming)

    Request JSON:
    {
        "message": "사용자 메시지",
        "agent": "pm",           # 단일 에이전트 모드
        "mock": false,
        "use_chain": false       # true면 에이전트 체인 사용 (Excavator→Coder→QA)
    }
    """
    global current_session_id
    data = request.json
    user_message = data.get('message', '')
    agent_role = data.get('agent', 'pm')
    use_mock = data.get('mock', False)
    use_chain = data.get('use_chain', False)  # 체인 모드 옵션

    if not user_message:
        return jsonify({'error': 'Message required'}), 400

    # 세션이 없으면 새로 생성
    if not current_session_id:
        current_session_id = db.create_session(agent=agent_role)

    # DB에 사용자 메시지 저장
    db.add_message(current_session_id, 'user', user_message, agent_role)

    # 에이전트 체인 모드
    if use_chain and AGENT_CHAIN_AVAILABLE:
        try:
            chain = get_chain()
            result = chain.process(user_message)
            response = result.final_response
            agents_used = result.agents_called

            # DB에 어시스턴트 응답 저장
            db.add_message(current_session_id, 'assistant', response, 'chain')

            return jsonify({
                'response': response,
                'agent': 'chain',
                'agents_called': agents_used,
                'task_type': result.task_type.value,
                'timestamp': datetime.now().isoformat(),
                'session_id': current_session_id
            })
        except Exception as e:
            print(f"[Chain Error] {e}")
            # 체인 실패시 단일 에이전트로 폴백
            response = _call_agent(user_message, agent_role)
    elif use_mock:
        response = _mock_agent_response(user_message, agent_role)
    else:
        response = _call_agent(user_message, agent_role)

    # DB에 어시스턴트 응답 저장
    db.add_message(current_session_id, 'assistant', response, agent_role)

    return jsonify({
        'response': response,
        'agent': agent_role,
        'timestamp': datetime.now().isoformat(),
        'session_id': current_session_id
    })


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    """채팅 API (streaming)"""
    global current_session_id
    data = request.json
    user_message = data.get('message', '')
    agent_role = data.get('agent', 'pm')
    use_mock = data.get('mock', False)

    if not user_message:
        return jsonify({'error': 'Message required'}), 400

    # 세션이 없으면 새로 생성
    if not current_session_id:
        current_session_id = db.create_session(agent=agent_role)

    # DB에 사용자 메시지 저장
    db.add_message(current_session_id, 'user', user_message, agent_role)

    # 세션 ID를 클로저에서 사용하기 위해 로컬 변수로 복사
    session_id = current_session_id

    def generate() -> Generator[str, None, None]:
        # 실제 LLM 호출 또는 Mock
        if use_mock:
            response = _mock_agent_response(user_message, agent_role)
        else:
            response = _call_agent(user_message, agent_role)

        # 스트리밍 시뮬레이션 (단어 단위) - 실제 스트리밍은 추후 구현
        words = response.split(' ')
        full_response = []

        for word in words:
            full_response.append(word)
            yield f"data: {json.dumps({'token': word + ' '}, ensure_ascii=False)}\n\n"
            time.sleep(0.02)

        # 완료 신호
        yield f"data: {json.dumps({'done': True, 'full_response': ' '.join(full_response)}, ensure_ascii=False)}\n\n"

        # DB에 어시스턴트 응답 저장
        db.add_message(session_id, 'assistant', ' '.join(full_response), agent_role)

    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/history')
def get_history():
    """대화 히스토리 조회 (현재 세션)"""
    global current_session_id
    if not current_session_id:
        return jsonify([])
    messages = db.get_messages(current_session_id)
    return jsonify(messages)


@app.route('/api/history/clear', methods=['POST'])
def clear_history():
    """대화 히스토리 클리어 (새 세션 시작)"""
    global current_session_id
    if current_session_id:
        db.clear_messages(current_session_id)
    current_session_id = None
    return jsonify({'status': 'cleared'})


@app.route('/api/agents')
def get_agents():
    """사용 가능한 에이전트 목록"""
    agents = []

    # 듀얼 엔진
    for role, config in DUAL_ENGINES.items():
        agents.append({
            'role': role,
            'type': 'dual',
            'description': config.description,
            'engines': [config.engine_1.name, config.engine_2.name],
            'strategy': config.merge_strategy
        })

    # 단일 엔진
    for role, config in SINGLE_ENGINES.items():
        agents.append({
            'role': role,
            'type': 'single',
            'description': f'{role.upper()} - {config.name}',
            'engines': [config.name],
            'strategy': 'single'
        })

    return jsonify(agents)


@app.route('/api/system-prompt/<role>')
def get_agent_prompt(role: str):
    """에이전트 시스템 프롬프트 조회"""
    prompt = get_system_prompt(role)
    if not prompt:
        return jsonify({'error': f'Unknown role: {role}'}), 404
    return jsonify({'role': role, 'prompt': prompt})


@app.route('/api/projects')
def get_projects():
    """프로젝트 목록 조회"""
    projects = []
    for project_id, config in PROJECTS.items():
        projects.append({
            'id': project_id,
            'name': config['name'],
            'description': config['description'],
            'path': config['path']
        })
    return jsonify(projects)


# =============================================================================
# Session API Endpoints
# =============================================================================

@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    """세션 목록 조회"""
    sessions = db.list_sessions(limit=50)
    return jsonify(sessions)


@app.route('/api/sessions', methods=['POST'])
def create_session():
    """새 세션 생성"""
    global current_session_id
    data = request.json or {}
    name = data.get('name')
    project = data.get('project')
    agent = data.get('agent', 'pm')

    session_id = db.create_session(name=name, project=project, agent=agent)
    current_session_id = session_id

    return jsonify({
        'session_id': session_id,
        'status': 'created'
    })


@app.route('/api/sessions/<session_id>', methods=['GET'])
def get_session(session_id: str):
    """세션 상세 조회"""
    session_data = db.get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify(session_data)


@app.route('/api/sessions/<session_id>', methods=['PUT'])
def update_session(session_id: str):
    """세션 업데이트"""
    data = request.json or {}
    success = db.update_session(
        session_id,
        name=data.get('name'),
        project=data.get('project'),
        agent=data.get('agent')
    )
    if success:
        return jsonify({'status': 'updated'})
    return jsonify({'error': 'Session not found'}), 404


@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id: str):
    """세션 삭제"""
    global current_session_id
    success = db.delete_session(session_id)
    if success:
        if current_session_id == session_id:
            current_session_id = None
        return jsonify({'status': 'deleted'})
    return jsonify({'error': 'Session not found'}), 404


@app.route('/api/sessions/<session_id>/messages', methods=['GET'])
def get_session_messages(session_id: str):
    """세션 메시지 목록 조회"""
    messages = db.get_messages(session_id, limit=100)
    return jsonify(messages)


@app.route('/api/sessions/<session_id>/switch', methods=['POST'])
def switch_session(session_id: str):
    """현재 세션 전환"""
    global current_session_id
    session_data = db.get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Session not found'}), 404

    current_session_id = session_id
    messages = db.get_messages(session_id)
    return jsonify({
        'session': session_data,
        'messages': messages
    })


@app.route('/api/sessions/current', methods=['GET'])
def get_current_session():
    """현재 활성 세션 조회"""
    global current_session_id
    if not current_session_id:
        return jsonify({'session': None, 'messages': []})

    session_data = db.get_session(current_session_id)
    messages = db.get_messages(current_session_id) if session_data else []
    return jsonify({
        'session': session_data,
        'messages': messages
    })


@app.route('/api/health/<provider>')
def check_api_health(provider: str):
    """API 상태 체크"""
    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            response = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}]
            )
            return jsonify({
                "provider": "anthropic",
                "status": "ok",
                "model": "Claude Opus 4.5",
                "message": "API 연결 정상"
            })

        elif provider == "openai":
            import openai
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}]
            )
            return jsonify({
                "provider": "openai",
                "status": "ok",
                "model": "GPT-5.2 Thinking",
                "message": "API 연결 정상"
            })

        elif provider == "google":
            from google import genai
            client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents="ping"
            )
            return jsonify({
                "provider": "google",
                "status": "ok",
                "model": "Gemini 3 Pro",
                "message": "API 연결 정상"
            })

        else:
            return jsonify({
                "provider": provider,
                "status": "error",
                "message": f"Unknown provider: {provider}"
            }), 400

    except Exception as e:
        return jsonify({
            "provider": provider,
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/health/db')
def check_db_health():
    """DB 연결 상태 체크"""
    result = db.check_db_health()
    # 디버깅: 연결 문자열 정보 추가
    result['connection_info'] = {
        'server': os.getenv('MSSQL_SERVER'),
        'database': os.getenv('MSSQL_DATABASE'),
        'user': os.getenv('MSSQL_USER')
    }
    status_code = 200 if result.get('status') == 'ok' else 500
    return jsonify(result), status_code


# =============================================================================
# Executor API Endpoints
# =============================================================================

@app.route('/api/execute', methods=['POST'])
def execute():
    """
    파일 읽기/쓰기/명령 실행 API

    Request JSON:
    {
        "action": "read" | "write" | "run" | "list",
        "target": "파일 경로 또는 명령어",
        "content": "write 액션용 내용 (선택)",
        "cwd": "run 액션용 작업 디렉토리 (선택)"
    }
    """
    data = request.json
    action = data.get('action')
    target = data.get('target')
    content = data.get('content', '')
    cwd = data.get('cwd')

    if not action or not target:
        return jsonify({
            'success': False,
            'error': 'action and target are required'
        }), 400

    result = executor.execute_api(action, target, content, cwd)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code


@app.route('/api/execute/batch', methods=['POST'])
def execute_batch():
    """
    여러 명령 일괄 실행 API

    Request JSON:
    {
        "commands": [
            {"action": "read", "target": "path"},
            {"action": "run", "target": "git status"}
        ]
    }
    """
    data = request.json
    commands = data.get('commands', [])

    results = []
    for cmd in commands:
        result = executor.execute_api(
            cmd.get('action'),
            cmd.get('target'),
            cmd.get('content', ''),
            cmd.get('cwd')
        )
        results.append(result)

    return jsonify({
        'results': results,
        'success_count': sum(1 for r in results if r['success']),
        'total_count': len(results)
    })


# =============================================================================
# RAG API Endpoints
# =============================================================================

@app.route('/api/rag/search', methods=['POST'])
def rag_search():
    """
    RAG 검색 API

    Request JSON:
    {
        "query": "검색 쿼리",
        "source_types": ["log", "message"],  // 선택, 없으면 전체
        "top_k": 5  // 선택
    }
    """
    data = request.json
    query = data.get('query', '')
    source_types = data.get('source_types')
    top_k = data.get('top_k', 5)

    if not query:
        return jsonify({'error': 'query is required'}), 400

    try:
        result = rag.search(query, source_types=source_types, top_k=top_k)
        return jsonify({
            'query': result.query,
            'total': result.total,
            'documents': [
                {
                    'id': doc.id,
                    'content': doc.content[:500],  # 요약
                    'score': round(doc.score, 3),
                    'metadata': doc.metadata
                }
                for doc in result.documents
            ]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/rag/index', methods=['POST'])
def rag_index():
    """
    RAG 인덱싱 트리거

    Request JSON:
    {
        "source": "logs" | "messages" | "all",
        "limit": 100
    }
    """
    data = request.json
    source = data.get('source', 'all')
    limit = data.get('limit', 100)

    try:
        result = {}

        if source in ['logs', 'all']:
            result['logs_indexed'] = rag.index_logs_from_db(limit=limit)

        if source in ['messages', 'all']:
            result['messages_indexed'] = rag.index_messages_from_db(limit=limit)

        result['stats'] = rag.get_stats()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/rag/stats')
def rag_stats():
    """RAG 인덱스 통계"""
    try:
        return jsonify(rag.get_stats())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/rag/context', methods=['POST'])
def rag_context():
    """
    RAG 컨텍스트 빌드 (PM 프롬프트 주입용)

    Request JSON:
    {
        "query": "쿼리",
        "top_k": 3
    }
    """
    data = request.json
    query = data.get('query', '')
    top_k = data.get('top_k', 3)

    if not query:
        return jsonify({'error': 'query is required'}), 400

    try:
        context = rag.build_context(query, top_k=top_k)
        return jsonify({
            'query': query,
            'context': context,
            'context_length': len(context)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/translate', methods=['POST'])
def translate():
    """
    번역 API

    Request JSON:
    {
        "text": "번역할 텍스트",
        "target": "en" | "ko",
        "source": "auto" | "en" | "ko"  // 선택
    }
    """
    data = request.json
    text = data.get('text', '')
    target_lang = data.get('target', 'en')
    source_lang = data.get('source', 'auto')

    if not text:
        return jsonify({'error': 'text is required'}), 400

    try:
        translated = rag.translate_message(text, target_lang, source_lang)
        return jsonify({
            'original': text,
            'translated': translated,
            'target': target_lang,
            'is_korean_original': rag.is_korean(text)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Agent Chain API
# =============================================================================

@app.route('/api/chain', methods=['POST'])
def agent_chain():
    """
    에이전트 체인 API (Excavator → Coder → QA 자동 실행)

    Request JSON:
    {
        "message": "CEO 입력",
        "task_id": "optional task id"
    }
    """
    global current_session_id

    if not AGENT_CHAIN_AVAILABLE:
        return jsonify({'error': 'Agent chain not available'}), 500

    data = request.json
    user_message = data.get('message', '')
    task_id = data.get('task_id')

    if not user_message:
        return jsonify({'error': 'message is required'}), 400

    # 세션 생성
    if not current_session_id:
        current_session_id = db.create_session(agent='chain')

    # DB에 사용자 메시지 저장
    db.add_message(current_session_id, 'user', user_message, 'chain')

    try:
        chain = get_chain()
        result = chain.process(user_message, task_id=task_id)

        # 응답 구성
        response_data = {
            'success': result.success,
            'task_type': result.task_type.value,
            'agents_called': result.agents_called,
            'response': result.final_response,
            'session_id': current_session_id
        }

        # 추가 정보
        if result.excavation:
            response_data['excavation'] = {
                'explicit': result.excavation.explicit,
                'implicit': result.excavation.implicit,
                'confidence': result.excavation.confidence,
                'perfectionism': result.excavation.perfectionism_detected
            }

        if result.code:
            response_data['code'] = {
                'code': result.code.code[:2000] if result.code.code else '',
                'complexity': result.code.complexity,
                'dependencies': result.code.dependencies
            }

        if result.qa_result:
            response_data['qa'] = {
                'status': result.qa_result.status,
                'issues_count': len(result.qa_result.issues),
                'confidence': result.qa_result.confidence
            }

        if result.error:
            response_data['error'] = result.error

        # DB에 응답 저장
        db.add_message(current_session_id, 'assistant', result.final_response, 'chain')

        return jsonify(response_data)

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'session_id': current_session_id
        }), 500


@app.route('/api/chain/status')
def chain_status():
    """에이전트 체인 상태 확인"""
    return jsonify({
        'available': AGENT_CHAIN_AVAILABLE,
        'agents': ['excavator', 'coder', 'qa', 'strategist', 'analyst'] if AGENT_CHAIN_AVAILABLE else []
    })


@app.route('/api/projects/<project_id>/files')
def get_project_files(project_id: str):
    """프로젝트 파일 목록 조회"""
    import glob

    project = PROJECTS.get(project_id)
    if not project:
        return jsonify({'error': f'Unknown project: {project_id}'}), 404

    path = project['path']
    if not os.path.exists(path):
        return jsonify({'error': f'Project path not found: {path}'}), 404

    # Python 파일 목록
    files = []
    for ext in ['**/*.py', '**/*.js', '**/*.ts', '**/*.jsx', '**/*.tsx']:
        for f in glob.glob(os.path.join(path, ext), recursive=True):
            rel_path = os.path.relpath(f, path)
            if not any(skip in rel_path for skip in ['node_modules', '__pycache__', '.git', 'venv']):
                files.append({
                    'path': f,
                    'relative': rel_path,
                    'name': os.path.basename(f)
                })

    return jsonify({
        'project': project_id,
        'files': files[:100]  # 최대 100개
    })


def _call_agent(
    message: str,
    agent_role: str,
    auto_execute: bool = True,
    use_translation: bool = True
) -> str:
    """
    실제 LLM 호출 + [EXEC] 태그 자동 실행 + RAG 컨텍스트 주입 + 번역

    Args:
        message: 사용자 메시지
        agent_role: 에이전트 역할
        auto_execute: [EXEC] 태그 자동 실행 여부
        use_translation: 번역 레이어 사용 여부
    """
    global current_session_id
    system_prompt = get_system_prompt(agent_role)
    if not system_prompt:
        return f"[Error] Unknown agent role: {agent_role}"

    # 번역: CEO 입력(한국어) → 에이전트(영어)
    agent_message = message
    if use_translation and rag.is_korean(message):
        agent_message = rag.translate_for_agent(message)
        print(f"[Translate] CEO→Agent: {len(message)}자 → {len(agent_message)}자")

    # PM 에이전트에 RAG 컨텍스트 주입 (Gemini 요약 포함)
    if agent_role == "pm":
        try:
            # 에이전트에겐 영어 컨텍스트 제공
            rag_context = rag.build_context(
                agent_message,
                top_k=3,
                use_gemini=True,
                language="en"  # 에이전트 내부는 영어
            )
            if rag_context:
                system_prompt = system_prompt + "\n\n" + rag_context
        except Exception as e:
            print(f"[RAG] Context injection failed: {e}")

    # DB에서 대화 히스토리 조회 후 LLM 형식으로 변환
    messages = []
    if current_session_id:
        db_messages = db.get_messages(current_session_id)
        for msg in db_messages:
            if msg.get('agent') == agent_role:
                messages.append({
                    "role": msg['role'],
                    "content": msg['content']
                })

    # 현재 메시지 추가 (번역된 버전)
    messages.append({"role": "user", "content": agent_message})

    # 듀얼 엔진 여부 확인
    if agent_role in DUAL_ENGINES:
        response = call_dual_engine(agent_role, messages, system_prompt)
    else:
        # 단일 엔진
        model_config = SINGLE_ENGINES.get(agent_role)
        if model_config:
            response = call_llm(model_config, messages, system_prompt)
            # 로그 기록
            stream = get_stream()
            stream.log("ceo", agent_role, "request", agent_message)
            stream.log(agent_role, "ceo", "response", response)
        else:
            return f"[Error] No engine configured for: {agent_role}"

    # [EXEC] 태그 자동 실행 (coder, pm 등 실행 가능한 에이전트)
    if auto_execute and agent_role in ["coder", "pm"]:
        exec_results = executor.execute_all(response)
        if exec_results:
            response += executor.format_results(exec_results)

    # 번역: 에이전트 응답(영어) → CEO(한국어)
    if use_translation and not rag.is_korean(response):
        response = rag.translate_for_ceo(response)
        print(f"[Translate] Agent→CEO: 한국어로 번역 완료")

    return response


def _mock_agent_response(message: str, agent_role: str) -> str:
    """Mock 응답 (실제 LLM 연결 전 테스트용)"""

    responses = {
        'excavator': f"""```yaml
explicit:
  - "{message}"

implicit:
  - 아직 말 안 한 숨은 의도가 있을 수 있음
  - 추가 컨텍스트 필요

questions:
  - question: "이게 정확히 어떤 맥락인가요?"
    options:
      - label: "옵션 A"
        description: "설명 A"
      - label: "옵션 B"
        description: "설명 B"

red_flags:
  - "입력이 모호함 - 구체화 필요"

confidence: 0.6
perfectionism_detected: false
mvp_suggestion: "일단 핵심만 먼저"
```

⚠️ **Detective + Skeptic 분석 결과**
- 입력만으로는 확신 불가
- 추가 질문 필요""",

        'strategist': f"""```yaml
analysis:
  problem: "{message}"
  opportunities: ["기회 분석 필요"]
  constraints: ["제약 조건 분석 필요"]
  hidden_risks: ["숨은 리스크 분석 필요"]

counter_arguments:
  - argument: "이게 왜 실패할 수 있는지 분석 필요"
    mitigation: "대응책 수립 필요"

strategy:
  decision: "결정안 수립 필요"
  rationale:
    - "데이터 수집 후 근거 제시"
  metrics:
    - "측정 지표 정의 필요"
  rollback_condition: "실패 조건 정의 필요"

confidence: 0.5
```

⚠️ **Pragmatist + Skeptic 분석**
- 희망회로 금지
- 데이터 기반 의사결정 필요""",

        'coder': f"""```yaml
design_summary: |
  요청: {message}
  설계 분석 필요

implementation:
  files_created: []
  files_modified: []
  dependencies: []

edge_cases_handled: []

potential_failures:
  - scenario: "분석 필요"
    mitigation: "방어 코드 필요"

tests:
  - name: "테스트 케이스 정의 필요"
    type: "unit"
    scenario: "시나리오 정의 필요"

code_review:
  complexity: "분석 필요"
  test_coverage: "분석 필요"
```

⚠️ **Perfectionist + Pragmatist 스탠스**
- "깔끔하게, 근데 끝내자"
- 요구사항 구체화 필요""",

        'qa_logic': f"""```yaml
review_result:
  status: "needs_revision"
  confidence: 0.5

logic_issues:
  - severity: "medium"
    location: "분석 필요"
    description: "입력만으로는 검증 불가"
    reproduction: "코드 필요"
    fix_suggestion: "구현 후 재검토"

edge_cases_missing:
  - case: "엣지케이스 분석 필요"
    impact: "분석 필요"

summary: "코드 제출 후 검토 가능"
```

⚠️ **Skeptic + Perfectionist 스탠스**
- "이거 테스트 안 해봤지?"
- 코드 제출 필요""",

        'qa_security': f"""```yaml
security_verdict:
  status: "pending_review"
  confidence: 0.0

vulnerabilities: []

secrets_exposed: []

attack_surface:
  - entry_point: "분석 필요"
    risk_level: "분석 필요"
    protection_needed: "분석 필요"

summary: "코드 제출 후 보안 검토 가능"
```

⚠️ **Pessimist + Devil's Advocate 스탠스**
- "해커 입장에서 볼게"
- 코드 제출 필요""",

        'pm': f"""```yaml
sprint_plan:
  do:
    - "요청 분석: {message}"
    - "세부 태스크 분해"
    - "에이전트 할당"
  dont:
    - "희망회로 금지"
    - "뜬구름 계획 금지"
  success_criteria:
    - "구체적 산출물 정의 필요"
  risks:
    - risk: "요구사항 모호"
      mitigation: "Excavator 통해 구체화"
  rollback_if: "실패 조건 정의 필요"

delegation:
  - agent: "excavator"
    task: "CEO 의도 발굴"
    deadline: "즉시"
```

⚠️ **Pragmatist + Skeptic 스탠스**
- "일정 맞출 수 있다고? 근거 대봐"
- 구체화 필요""",

        'analyst': f"""```yaml
analysis_type: "initial_scan"

findings:
  - finding: "입력 분석: {message}"
    evidence: []
    confidence: 0.5

anomalies: []

patterns: []

recommendations:
  - action: "로그/데이터 제공 필요"
    priority: "P1"
    rationale: "분석 대상 없음"

metadata:
  logs_analyzed: 0
  time_range: "N/A"
  confidence: 0.0
```

⚠️ **Detective + Skeptic 스탠스**
- "근거 없는 분석은 무효"
- 데이터 제공 필요"""
    }

    return responses.get(agent_role, f"""**{agent_role.upper()}** 에이전트 응답 (Mock)

요청: {message}

⚠️ 실제 LLM 연결 필요
- config.py의 API 키 설정 확인
- 에이전트별 LLM 호출 구현 필요""")


if __name__ == '__main__':
    print("\n" + "="*60)
    print("HATTZ EMPIRE - Web Interface")
    print("="*60)
    print("http://localhost:5000")
    print("="*60 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
