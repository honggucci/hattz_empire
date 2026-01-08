"""
Hattz Empire - Chat API (v2.3)
채팅 관련 API 엔드포인트

v2.3 주요 기능:
1. Router Agent: 자동 에이전트 선택 (auto_route=true)
   - CEO 프리픽스: 검색/, 코딩/, 분석/ → 직접 라우팅
   - 키워드 기반 라우팅: PM 병목 해소

2. Hook Chain: 내부통제 시스템
   - PreRunHook: 세션 규정 로드 + rules_hash 계산
   - PreReviewHook: Static Gate (0원 1차 검사)
   - PostReviewHook: 감사 로그 기록

3. TokenCounter: 토큰 사용량 추적
   - 75% 경고, 85% 압축 트리거
   - 세션별 독립 관리

4. Static Gate: 비용 절감
   - API Key 하드코딩, 무한루프 등 LLM 없이 감지
   - 위반 시 즉시 REJECT → LLM 호출 비용 절감

데이터 흐름:
  사용자 입력
    ↓
  [Router Agent] auto_route=true 시 에이전트 자동 선택
    ↓
  [Pre-Run Hook] 세션 규정 로드 + rules_hash 계산
    ↓
  [TokenCounter] 토큰 추적 + 85% 압축 체크
    ↓
  LLM 호출 (PM/Coder/QA 등)
    ↓
  [Static Gate] 하위 에이전트 응답 검사
    ↓
  SSE 스트림으로 클라이언트에 전송
"""
from flask import request, jsonify, Response
from flask_login import login_required
from datetime import datetime
import json
import time
import uuid

from . import chat_bp

# Active streaming requests (for abort functionality)
# stream_id -> is_active
active_streams: dict[str, bool] = {}
from src.core.llm_caller import call_agent, process_call_tags, build_call_results_prompt, mock_agent_response, extract_project_from_message
from src.core.session_state import get_current_session, set_current_session
from src.services.agent_monitor import get_agent_monitor
from src.services.fact_checker import fact_check, format_fact_check_result
from src.services.task_events import emit_progress, emit_stage_change, emit_complete, emit_error
import src.services.database as db
import src.services.executor as executor

# v2.6: Server Logger
from src.utils.server_logger import logger, log_error

# Control Module (Session Rules System)
from src.control import (
    StaticChecker,
    RulesStore,
    AuditLogger,
    EventBus,
)

# Singleton instances for control module
_rules_store = RulesStore()
_audit_logger = AuditLogger()
_event_bus = EventBus()


def get_rules_for_session(session_id: str):
    """세션별 규정 로드 (fallback: dev-default)"""
    try:
        return _rules_store.load(session_id)
    except FileNotFoundError:
        try:
            return _rules_store.load("dev-default")
        except FileNotFoundError:
            return None


def get_event_bus() -> EventBus:
    """싱글톤 EventBus 반환"""
    return _event_bus


def get_audit_logger() -> AuditLogger:
    """싱글톤 AuditLogger 반환"""
    return _audit_logger

# v2.3 Hook Chain System
from src.hooks.chain import create_default_chain, create_minimal_chain
from src.hooks.base import HookContext, HookStage

# v2.3 Router Agent
from src.services.router import quick_route, AgentType

# v2.3 Context Management
from src.context.counter import TokenCounter
from src.context.compactor import Compactor

# v2.5.4 PM Decision Machine
from src.core.decision_machine import (
    get_decision_machine,
    process_pm_output,
    PMDecision,
    DecisionOutput
)

# =============================================================================
# v2.3 세션별 상태 관리
# =============================================================================

# Session-level TokenCounters (session_id -> TokenCounter)
# 각 세션마다 독립적인 토큰 카운터를 유지하여 컨텍스트 윈도우 관리
_session_counters: dict[str, TokenCounter] = {}


def get_token_counter(session_id: str) -> TokenCounter:
    """
    세션별 TokenCounter 가져오기 (없으면 생성)

    Args:
        session_id: 세션 ID

    Returns:
        TokenCounter: 해당 세션의 토큰 카운터

    Note:
        - max_tokens=128000 (Claude 3.5 Sonnet 기준)
        - 75%에서 경고, 85%에서 압축 트리거
    """
    if session_id not in _session_counters:
        _session_counters[session_id] = TokenCounter(
            max_tokens=128000,
            warning_threshold=0.75,
            compaction_threshold=0.85,
        )
    return _session_counters[session_id]


# =============================================================================
# v2.3 Hook Chain 헬퍼 함수
# =============================================================================

def run_pre_run_hook(session_id: str, task: str = "") -> dict:
    """
    PRE_RUN Hook 실행 (세션 규정 로드)

    세션 시작 시 config/session_rules/ 디렉토리에서
    해당 세션의 규정 JSON 파일을 로드하고 rules_hash를 계산합니다.

    Args:
        session_id: 세션 ID (예: "live-trade-btc-001")
        task: 수행할 태스크 설명

    Returns:
        {
            "success": bool,           # 성공 여부
            "session_rules": SessionRules or None,  # 로드된 규정
            "worker_header": str,      # Worker 프롬프트에 주입할 헤더
            "rules_hash": str,         # 감사 추적용 해시 (SHA256)
            "error": str or None       # 에러 메시지
        }

    Note:
        - 규정 파일이 없으면 dev-default 또는 인메모리 기본값 사용
        - create_minimal_chain()은 PreRunHook + StopHook만 포함 (비용 최적화)
    """
    chain = create_minimal_chain()  # 비용 최적화: Static Gate만
    context = HookContext(session_id=session_id, task=task)

    result = chain.run_pre_run(context)

    if result.success and result.results.get("PreRunHook"):
        pre_run_output = result.results["PreRunHook"].output
        return {
            "success": True,
            "session_rules": pre_run_output.get("session_rules"),
            "worker_header": pre_run_output.get("worker_header", ""),
            "rules_hash": pre_run_output.get("rules_hash", ""),
            "error": None
        }

    return {
        "success": False,
        "session_rules": None,
        "worker_header": "",
        "rules_hash": "",
        "error": result.error or "PreRunHook failed"
    }


def run_static_gate(worker_output: str, session_rules, session_id: str) -> dict:
    """
    Static Gate 실행 (0원 1차 게이트)

    Worker 출력물을 LLM Reviewer에 보내기 전 정적 검사를 수행합니다.
    LLM 호출 없이 명백한 위반을 감지하여 비용을 절감합니다.

    검사 항목:
    - API Key 하드코딩 (OpenAI, AWS, GitHub, Slack, Google)
    - 무한루프 패턴 (while True without break)
    - Sleep in API loop
    - 비밀 정보 노출

    Args:
        worker_output: 검사할 Worker 출력물 (코드)
        session_rules: SessionRules 인스턴스 (Pre-Run Hook에서 로드)
        session_id: 세션 ID (로깅용)

    Returns:
        {
            "passed": bool,        # 검사 통과 여부
            "violations": list,    # 위반 목록 [{key, detail, evidence, line}, ...]
            "should_abort": bool,  # True면 LLM 호출 없이 즉시 REJECT
            "message": str         # 결과 메시지
        }

    Note:
        - 비용: $0 (LLM 호출 없음)
        - 위반 시 should_abort=True → LLM Reviewer 호출 스킵
    """
    if not worker_output or not session_rules:
        return {"passed": True, "violations": [], "should_abort": False, "message": "No output to check"}

    from src.hooks.pre_review import PreReviewHook

    context = HookContext(
        session_id=session_id,
        worker_output=worker_output,
        metadata={"session_rules": session_rules}
    )

    hook = PreReviewHook(session_rules=session_rules)
    result = hook.execute(context)

    if result.should_abort:
        return {
            "passed": False,
            "violations": result.output.get("violations", []),
            "should_abort": True,
            "message": result.abort_reason
        }

    return {
        "passed": True,
        "violations": [],
        "should_abort": False,
        "message": "Static check passed"
    }


# =============================================================================
# v2.3 Router Agent 헬퍼 함수
# =============================================================================

def auto_route_agent(user_message: str, default_agent: str = "pm") -> tuple[str, dict]:
    """
    Router Agent로 자동 에이전트 선택

    사용자 요청을 분석하여 가장 적합한 에이전트를 자동으로 선택합니다.
    PM 병목을 해소하고 응답 속도를 향상시킵니다.

    라우팅 방식:
    1. CEO 프리픽스 (강제 라우팅, confidence=1.0)
       - "검색/" → Researcher
       - "코딩/" → Coder
       - "분석/" → Excavator
       - "최고/" → PM (VIP 모드)

    2. 키워드 기반 (confidence=0.3~0.7)
       - "구현", "만들어", "추가" → Coder
       - "테스트", "검증" → QA
       - "분석", "구조" → Excavator
       - etc.

    Args:
        user_message: 사용자 입력 메시지
        default_agent: 기본 에이전트 (매칭 실패 시)

    Returns:
        (selected_agent: str, route_info: dict)
        - selected_agent: 선택된 에이전트 role
        - route_info: {
            "routed": bool,           # 라우팅 성공 여부
            "selected_agent": str,    # 선택된 에이전트
            "confidence": float,      # 신뢰도 (0.0~1.0)
            "reason": str,            # 선택 이유
            "reframed_task": str,     # 재구성된 태스크
          }

    Note:
        - confidence >= 0.7 일 때만 실제 라우팅 적용
        - 그 외에는 default_agent(PM) 유지
    """
    try:
        decision = quick_route(user_message)

        # AgentType → 실제 에이전트 role 매핑
        agent_mapping = {
            AgentType.PM: "pm",
            AgentType.CODER: "coder",
            AgentType.EXCAVATOR: "excavator",
            AgentType.QA: "qa",
            AgentType.RESEARCHER: "researcher",
            AgentType.STRATEGIST: "strategist",
            AgentType.ANALYST: "analyst",
        }

        selected = agent_mapping.get(decision.agent, default_agent)

        route_info = {
            "routed": True,
            "selected_agent": selected,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "reframed_task": decision.reframed_task,
        }

        print(f"[Router] {user_message[:50]}... → {selected} (confidence: {decision.confidence:.2f})")

        return selected, route_info

    except Exception as e:
        log_error(f"Router failed: {e}", error_type="ROUTER_ERROR")
        return default_agent, {"routed": False, "error": str(e)}


@chat_bp.route('/chat', methods=['POST'])
@login_required
def chat():
    """
    채팅 API (non-streaming)

    Request JSON:
    {
        "message": "사용자 메시지",
        "agent": "pm",
        "mock": false,
        "session_id": "session_xxx"
    }
    """
    data = request.json
    user_message = data.get('message', '')
    agent_role = data.get('agent', 'pm')
    use_mock = data.get('mock', False)
    client_session_id = data.get('session_id')

    if not user_message:
        return jsonify({'error': 'Message required'}), 400

    # [PROJECT: xxx] 태그에서 프로젝트 추출
    current_project, _ = extract_project_from_message(user_message)

    # 세션 관리
    current_session_id = get_current_session()
    if client_session_id:
        current_session_id = client_session_id
        set_current_session(client_session_id)
    elif not current_session_id:
        current_session_id = db.create_session(agent=agent_role, project=current_project)
        set_current_session(current_session_id)

    # DB에 사용자 메시지 저장
    db.add_message(current_session_id, 'user', user_message, agent_role)

    if use_mock:
        response = mock_agent_response(user_message, agent_role)
    else:
        response = call_agent(user_message, agent_role)

    # [CALL:agent] 태그 처리
    agents_called = []
    if executor.has_call_tags(response):
        call_results = process_call_tags(response)
        agents_called = [c['agent'] for c in call_results]

        if call_results:
            followup_prompt = build_call_results_prompt(call_results)
            response = call_agent(followup_prompt, agent_role)

    # DB에 어시스턴트 응답 저장
    db.add_message(current_session_id, 'assistant', response, agent_role)

    result = {
        'response': response,
        'agent': agent_role,
        'timestamp': datetime.now().isoformat(),
        'session_id': current_session_id
    }

    if agents_called:
        result['agents_called'] = agents_called

    return jsonify(result)


@chat_bp.route('/chat/stream', methods=['POST'])
def chat_stream():
    """
    채팅 API (streaming) - 하이브리드 모드 + v2.3 Hook Chain

    v2.3 추가:
    1. Router Agent로 자동 에이전트 선택 (auto_route=true)
    2. Pre-Run Hook으로 세션 규정 로드
    3. TokenCounter로 토큰 사용량 추적 (85% 압축 트리거)
    4. Static Gate로 0원 1차 검사

    하이브리드 모드:
    1. 스트리밍 시작 전 standby 태스크 생성 (LLM 호출 안 함)
    2. 스트리밍 정상 완료 시 standby 취소 (비용 0)
    3. 클라이언트 연결 끊김 시 standby 활성화 → 백그라운드로 계속 실행
    """
    from src.services.background_tasks import create_standby_task, cancel_standby_task, activate_standby_task

    data = request.json
    user_message = data.get('message', '')
    agent_role = data.get('agent', 'pm')
    use_mock = data.get('mock', False)
    client_session_id = data.get('session_id')
    auto_route = data.get('auto_route', False)  # v2.3: 자동 라우팅 활성화

    if not user_message:
        return jsonify({'error': 'Message required'}), 400

    # ===== v2.6.2 Dual Loop: "최고!" / "best!" 프리픽스 감지 =====
    # GPT-5.2 <-> Claude Opus 핑퐁 루프 실행
    dual_loop_prefixes = ["최고!", "최고! ", "best!", "best! ", "BEST!", "BEST! "]
    if any(user_message.startswith(p) for p in dual_loop_prefixes):
        return _handle_dual_loop_stream(data, user_message)

    # [PROJECT: xxx] 태그에서 프로젝트 추출
    current_project, _ = extract_project_from_message(user_message)

    # ===== v2.3 Router Agent =====
    route_info = None
    if auto_route and agent_role == 'pm':
        # PM으로 요청 시에만 자동 라우팅 (다른 에이전트 지정 시 무시)
        routed_agent, route_info = auto_route_agent(user_message, agent_role)
        if route_info.get("routed") and route_info.get("confidence", 0) >= 0.7:
            agent_role = routed_agent

    # 세션 관리
    current_session_id = get_current_session()
    if client_session_id:
        current_session_id = client_session_id
        set_current_session(client_session_id)
    elif not current_session_id:
        current_session_id = db.create_session(agent=agent_role, project=current_project)
        set_current_session(current_session_id)

    # ===== v2.3 TokenCounter =====
    token_counter = get_token_counter(current_session_id)
    token_counter.add('user', user_message)

    # 85% 임계치 체크
    compaction_needed = token_counter.should_compact
    if compaction_needed:
        print(f"[TokenCounter] ⚠️ Session {current_session_id} at {token_counter.usage_ratio:.1%} - compaction needed")

    # ===== v2.3 Pre-Run Hook =====
    session_rules = None
    rules_hash = ""
    try:
        hook_result = run_pre_run_hook(current_session_id, user_message)
        if hook_result["success"]:
            session_rules = hook_result["session_rules"]
            rules_hash = hook_result["rules_hash"]
            print(f"[Hook] Pre-run OK: rules_hash={rules_hash[:16]}...")
        else:
            print(f"[Hook] Pre-run failed: {hook_result['error']}")
    except Exception as e:
        log_error(f"Pre-run hook failed: {e}", session_id=current_session_id, error_type="HOOK_ERROR")

    # DB에 사용자 메시지 저장
    db.add_message(current_session_id, 'user', user_message, agent_role)

    session_id = current_session_id

    # 스트림 ID 생성 (중단용)
    stream_id = str(uuid.uuid4())
    active_streams[stream_id] = True

    # ===== 하이브리드 모드: Standby 태스크 생성 =====
    # Mock 모드가 아닐 때만 standby 생성 (테스트 시 불필요)
    standby_task_id = None
    if not use_mock:
        standby_task_id = create_standby_task(session_id, agent_role, user_message)
        print(f"[Hybrid] Standby task created: {standby_task_id}")

    # 스트리밍 완료 여부 추적
    streaming_completed = False

    # v2.3 Hook 데이터 (generate 내부에서 사용)
    hook_data = {
        "session_rules": session_rules,
        "rules_hash": rules_hash,
        "route_info": route_info,
        "token_counter": token_counter,
        "compaction_needed": compaction_needed,
    }

    def generate():
        try:
            # 첫 번째로 세션 ID와 스트림 ID 전송
            yield f"data: {json.dumps({'session_id': session_id, 'stream_id': stream_id}, ensure_ascii=False)}\n\n"

            # ===== v2.3 메타데이터 전송 =====
            v23_meta = {
                'stage': 'thinking',
                'agent': agent_role,
            }
            # Router 정보 (자동 라우팅 시)
            if hook_data.get("route_info"):
                v23_meta['route_info'] = hook_data["route_info"]
            # Rules hash (감사 추적용)
            if hook_data.get("rules_hash"):
                v23_meta['rules_hash'] = hook_data["rules_hash"][:16] + "..."
            # Token stats
            tc = hook_data.get("token_counter")
            if tc:
                v23_meta['token_stats'] = {
                    'usage_ratio': round(tc.usage_ratio, 3),
                    'total_tokens': tc.total_tokens,
                    'compaction_needed': hook_data.get("compaction_needed", False),
                }

            yield f"data: {json.dumps(v23_meta, ensure_ascii=False)}\n\n"

            # SSE broadcast: thinking stage (cross-device sync)
            emit_stage_change(session_id, 'thinking', agent_role)

            model_meta = None
            if use_mock:
                response = mock_agent_response(user_message, agent_role)
                model_meta = {'model_name': 'Mock', 'tier': 'mock', 'reason': 'Mock mode'}
            else:
                response, model_meta = call_agent(user_message, agent_role, return_meta=True)

            # LLM 호출 후 abort 체크
            if not active_streams.get(stream_id, False):
                yield f"data: {json.dumps({'aborted': True, 'message': 'LLM 호출 후 중단됨'}, ensure_ascii=False)}\n\n"
                return

            # ===== v2.3 TokenCounter: 응답 토큰 추적 =====
            tc = hook_data.get("token_counter")
            if tc:
                tc.add('assistant', response)

            # 모델 정보 전송
            if model_meta:
                yield f"data: {json.dumps({'model_info': model_meta, 'agent': agent_role}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'stage': 'responding', 'agent': agent_role}, ensure_ascii=False)}\n\n"

            # SSE broadcast: responding stage
            emit_stage_change(session_id, 'responding', agent_role)

            words = response.split(' ')
            full_response = []

            # 매 단어마다 abort 체크
            for word in words:
                if not active_streams.get(stream_id, False):
                    # 중단됨 - 지금까지 내용만 저장
                    if full_response:
                        partial = ' '.join(full_response) + ' [응답 중단됨]'
                        db.add_message(session_id, 'assistant', partial, agent_role)
                    yield f"data: {json.dumps({'aborted': True, 'partial': ' '.join(full_response)}, ensure_ascii=False)}\n\n"
                    return

                full_response.append(word)
                yield f"data: {json.dumps({'token': word + ' '}, ensure_ascii=False)}\n\n"
                time.sleep(0.02)

            pm_response = ' '.join(full_response)

            # =================================================================
            # v2.5.4: PM Decision Machine - JSON → 정형화된 의사결정
            # =================================================================
            pm_decision: DecisionOutput = None
            try:
                # PM 응답에서 JSON 추출 시도
                import re
                json_match = re.search(r'\{[\s\S]*\}', pm_response)
                if json_match:
                    pm_json = json.loads(json_match.group(0))
                    pm_decision = process_pm_output(pm_json)

                    # Decision Machine 결과 클라이언트에 전송
                    yield f"data: {json.dumps({'pm_decision': pm_decision.to_dict()}, ensure_ascii=False)}\n\n"
                    print(f"[DecisionMachine] decision={pm_decision.decision.value}, confidence={pm_decision.confidence}")

                    # 낮은 confidence 경고
                    if pm_decision.confidence < 0.7:
                        yield f"data: {json.dumps({'decision_warning': {'message': 'PM 응답 품질 낮음', 'confidence': pm_decision.confidence}}, ensure_ascii=False)}\n\n"

                    # BLOCKED 처리
                    if pm_decision.decision == PMDecision.BLOCKED:
                        yield f"data: {json.dumps({'decision_blocked': {'reason': pm_decision.summary}}, ensure_ascii=False)}\n\n"
                        print(f"[DecisionMachine] BLOCKED: {pm_decision.summary}")

            except json.JSONDecodeError:
                print(f"[DecisionMachine] PM 응답이 JSON 형식이 아님 (CALL 태그 모드일 수 있음)")
            except Exception as e:
                print(f"[DecisionMachine] 처리 오류: {e}")

            # PM 응답 완료 (단, CALL 태그가 있으면 아직 done이 아님)
            yield f"data: {json.dumps({'pm_done': True, 'pm_response': pm_response, 'agent': agent_role, 'model_info': model_meta}, ensure_ascii=False)}\n\n"
            db.add_message(session_id, 'assistant', pm_response, agent_role, model_id=model_meta.get('model_name'))

            # =================================================================
            # 팩트체크: PM 응답의 거짓말/환각 탐지
            # =================================================================
            try:
                fact_result = fact_check(pm_response, use_gemini=True)
                if not fact_result.is_valid:
                    # 거짓말 탐지됨 - 클라이언트에 경고 전송
                    fact_warning = format_fact_check_result(fact_result)
                    yield f"data: {json.dumps({'fact_check': {'valid': False, 'warning': fact_warning, 'hallucinations': fact_result.hallucinations, 'confidence': fact_result.confidence}}, ensure_ascii=False)}\n\n"
                    print(f"[FactChecker] ⚠️ {len(fact_result.hallucinations)} hallucinations detected!")
                else:
                    print(f"[FactChecker] ✅ PM response validated")
            except Exception as e:
                print(f"[FactChecker] Error: {e}")

            # [CALL:agent] 태그 처리
            has_calls = executor.has_call_tags(pm_response)
            call_infos = executor.extract_call_info(pm_response) if has_calls else []
            total_calls = len(call_infos)

            # 디버그 로그 (파일 + 콘솔)
            import logging
            logging.basicConfig(level=logging.DEBUG)
            logger = logging.getLogger(__name__)
            logger.info(f"[CALL] has_call_tags: {has_calls}, extracted: {total_calls}")
            if call_infos:
                for ci in call_infos:
                    logger.info(f"[CALL] -> {ci['agent']}: {ci['message'][:100]}...")
            print(f"[DEBUG] has_call_tags: {has_calls}, total_calls: {total_calls}")

            if has_calls and total_calls > 0:

                # 하위 에이전트 호출 시작 알림
                yield f"data: {json.dumps({'stage': 'delegating', 'total_agents': total_calls, 'agents': [c['agent'] for c in call_infos]}, ensure_ascii=False)}\n\n"

                # SSE broadcast: delegating stage
                emit_progress(session_id, 'delegating', agent_role, 35, total_agents=total_calls)

                call_results = []
                monitor = get_agent_monitor()

                for idx, call_info in enumerate(call_infos):
                    sub_agent = call_info['agent']
                    sub_message = call_info['message']

                    # abort 체크
                    if not active_streams.get(stream_id, False):
                        yield f"data: {json.dumps({'aborted': True, 'message': f'{sub_agent} 호출 전 중단됨'}, ensure_ascii=False)}\n\n"
                        return

                    # 모니터에 작업 등록
                    task_id = monitor.start_task(
                        agent=sub_agent,
                        session_id=session_id,
                        task_type="call",
                        description=sub_message[:200],
                        parent_agent=agent_role,
                        metadata={"progress": f"{idx+1}/{total_calls}"}
                    )

                    # 하위 에이전트 작업 시작 알림
                    yield f"data: {json.dumps({'stage': 'calling', 'sub_agent': sub_agent, 'task_id': task_id, 'progress': f'{idx+1}/{total_calls}', 'message_preview': sub_message[:100]}, ensure_ascii=False)}\n\n"

                    # SSE broadcast: calling sub-agent
                    emit_progress(session_id, 'calling', agent_role, 40 + (idx * 10), sub_agent=sub_agent, total_agents=total_calls)

                    try:
                        # 하위 에이전트 호출 (PM이 [CALL:*] 태그로 호출 → _internal_call=True)
                        sub_response, sub_meta = call_agent(sub_message, sub_agent, auto_execute=True, use_translation=False, return_meta=True, _internal_call=True)

                        # =====================================================
                        # [v2.3 Hook] Static Gate (0원 1차 게이트)
                        # =====================================================
                        static_gate_result = None
                        try:
                            # Pre-Run Hook에서 로드한 session_rules 사용
                            hook_session_rules = hook_data.get("session_rules")
                            if hook_session_rules:
                                static_gate_result = run_static_gate(
                                    worker_output=sub_response,
                                    session_rules=hook_session_rules,
                                    session_id=session_id
                                )

                                # EventBus 발행
                                event_bus = get_event_bus()
                                event_bus.emit_static_check_result(
                                    session_id=session_id,
                                    passed=static_gate_result["passed"],
                                    violations_count=len(static_gate_result.get("violations", [])),
                                    has_critical=static_gate_result.get("should_abort", False),
                                )

                                # Audit 로깅
                                audit_logger = get_audit_logger()
                                audit_logger.log_event(
                                    event_type="static_gate",
                                    session_id=session_id,
                                    data={
                                        "worker_agent": sub_agent,
                                        "passed": static_gate_result["passed"],
                                        "violations": static_gate_result.get("violations", []),
                                        "rules_hash": hook_data.get("rules_hash", ""),
                                    }
                                )

                                if not static_gate_result["passed"]:
                                    # 위반 발견 - 클라이언트에 경고 전송
                                    yield f"data: {json.dumps({'stage': 'static_gate_reject', 'sub_agent': sub_agent, 'violations': static_gate_result.get('violations', [])[:5], 'passed': False, 'message': static_gate_result.get('message', 'Static Gate REJECT')}, ensure_ascii=False)}\n\n"
                                    print(f"[StaticGate] ⚠️ REJECT: {sub_agent} - {static_gate_result.get('message')}")
                                else:
                                    print(f"[StaticGate] ✅ PASS: {sub_agent}")
                            else:
                                # Fallback: 기존 방식
                                rules = get_rules_for_session(session_id)
                                checker = StaticChecker(rules)
                                check_result = checker.check(sub_response, file_type="python")

                                event_bus = get_event_bus()
                                audit_logger = get_audit_logger()

                                event_bus.emit_static_check_result(
                                    session_id=session_id,
                                    passed=check_result.passed,
                                    violations_count=len(check_result.violations),
                                    has_critical=check_result.has_critical(),
                                )

                                audit_logger.log_static_check(
                                    rules=rules,
                                    static_result=check_result,
                                    worker_agent=sub_agent,
                                    original_request=sub_message[:200],
                                )

                                if not check_result.passed:
                                    violations_summary = [
                                        {"rule": v.rule_key, "severity": v.severity.value, "message": v.message}
                                        for v in check_result.violations[:5]
                                    ]
                                    yield f"data: {json.dumps({'stage': 'control_warning', 'sub_agent': sub_agent, 'violations': violations_summary, 'passed': False}, ensure_ascii=False)}\n\n"

                                    # Critical 위반은 응답에 경고 추가
                                    if check_result.has_critical():
                                        sub_response = f"⚠️ [CONTROL WARNING] Constitution 위반 감지됨!\n\n{sub_response}"
                                        print(f"[Control] ⚠️ CRITICAL violation in {sub_agent} response!")
                                else:
                                    print(f"[Control] ✅ {sub_agent} response passed static check")
                        except Exception as ctrl_err:
                            print(f"[StaticGate/Control] Error during check: {ctrl_err}")

                        # 모니터에 완료 등록
                        monitor.complete_task(
                            task_id=task_id,
                            success=True,
                            result_preview=sub_response[:200] if sub_response else None
                        )
                    except Exception as e:
                        # 모니터에 실패 등록
                        monitor.fail_task(task_id=task_id, error_message=str(e))
                        yield f"data: {json.dumps({'stage': 'sub_agent_error', 'sub_agent': sub_agent, 'error': str(e)}, ensure_ascii=False)}\n\n"
                        continue

                    # abort 체크
                    if not active_streams.get(stream_id, False):
                        yield f"data: {json.dumps({'aborted': True, 'message': f'{sub_agent} 호출 후 중단됨'}, ensure_ascii=False)}\n\n"
                        return

                    # 하위 에이전트 완료 알림 (상태만, 내용 없음)
                    yield f"data: {json.dumps({'stage': 'sub_agent_done', 'sub_agent': sub_agent, 'task_id': task_id, 'progress': f'{idx+1}/{total_calls}'}, ensure_ascii=False)}\n\n"

                    # SSE broadcast: sub-agent done
                    emit_progress(session_id, 'sub_agent_done', agent_role, 50 + (idx * 10), sub_agent=sub_agent, total_agents=total_calls)

                    call_results.append({
                        'agent': sub_agent,
                        'message': sub_message,
                        'response': sub_response,
                        'task_id': task_id
                    })

                    # DB에 하위 에이전트 응답 저장 (내부 기록용, 웹에는 표시 안 함)
                    db.add_message(session_id, 'assistant', f"[{sub_agent.upper()}]\n{sub_response}", sub_agent, model_id=sub_meta.get('model_name'), is_internal=True)

                # 모든 하위 에이전트 완료 - PM이 결과 종합
                if call_results:
                    yield f"data: {json.dumps({'stage': 'summarizing', 'agent': agent_role}, ensure_ascii=False)}\n\n"

                    # SSE broadcast: summarizing stage
                    emit_stage_change(session_id, 'summarizing', agent_role)

                    followup_prompt = build_call_results_prompt(call_results)
                    final_response, final_meta = call_agent(followup_prompt, agent_role, return_meta=True)

                    # 최종 응답 스트리밍
                    yield f"data: {json.dumps({'stage': 'final_response', 'agent': agent_role}, ensure_ascii=False)}\n\n"

                    # SSE broadcast: final_response stage
                    emit_stage_change(session_id, 'final_response', agent_role)

                    final_words = final_response.split(' ')
                    for word in final_words:
                        if not active_streams.get(stream_id, False):
                            yield f"data: {json.dumps({'aborted': True, 'message': '최종 응답 중 중단됨'}, ensure_ascii=False)}\n\n"
                            return
                        yield f"data: {json.dumps({'token': word + ' ', 'is_final': True}, ensure_ascii=False)}\n\n"
                        time.sleep(0.02)

                    db.add_message(session_id, 'assistant', final_response, agent_role, model_id=final_meta.get('model_name'))

                    # 모든 작업 완료
                    yield f"data: {json.dumps({'done': True, 'full_response': final_response, 'session_id': session_id, 'model_info': final_meta, 'agents_called': [c['agent'] for c in call_results]}, ensure_ascii=False)}\n\n"

                    # SSE broadcast: complete
                    emit_complete(session_id, agent_role, final_meta)
                else:
                    # CALL 태그는 있었지만 결과가 없음
                    yield f"data: {json.dumps({'done': True, 'full_response': pm_response, 'session_id': session_id, 'model_info': model_meta}, ensure_ascii=False)}\n\n"
                    # SSE broadcast: complete
                    emit_complete(session_id, agent_role, model_meta)
            else:
                # CALL 태그 없음 - PM 응답으로 완료
                yield f"data: {json.dumps({'done': True, 'full_response': pm_response, 'session_id': session_id, 'model_info': model_meta}, ensure_ascii=False)}\n\n"
                # SSE broadcast: complete
                emit_complete(session_id, agent_role, model_meta)

            # ===== 하이브리드 모드: 스트리밍 정상 완료 =====
            nonlocal streaming_completed
            streaming_completed = True

        finally:
            # 스트림 정리
            active_streams.pop(stream_id, None)

            # ===== 하이브리드 모드: Standby 처리 =====
            if standby_task_id:
                if streaming_completed:
                    # 정상 완료 → standby 취소 (비용 0)
                    cancel_standby_task(standby_task_id)
                    print(f"[Hybrid] Standby cancelled (streaming completed): {standby_task_id}")
                else:
                    # 비정상 종료 (연결 끊김) → standby 활성화
                    print(f"[Hybrid] Activating standby (client disconnected): {standby_task_id}")
                    activate_standby_task(standby_task_id)

    return Response(generate(), mimetype='text/event-stream')


@chat_bp.route('/chat/abort', methods=['POST'])
def abort_stream():
    """스트리밍 중단 API (v2.4.3: CLI 프로세스 강제 종료 추가)"""
    data = request.json
    stream_id = data.get('stream_id')
    session_id = data.get('session_id')
    kill_cli = data.get('kill_cli', True)

    if not stream_id:
        return jsonify({'error': 'stream_id required'}), 400

    result = {'stream_id': stream_id, 'stream_aborted': False, 'cli_killed': None}

    if stream_id in active_streams:
        active_streams[stream_id] = False
        result['stream_aborted'] = True

    if kill_cli and session_id:
        try:
            from src.services.cli_supervisor import kill_session
            cli_result = kill_session(session_id)
            result['cli_killed'] = cli_result
            print(f"[Abort] CLI 종료: {cli_result}")
        except Exception as e:
            result['cli_error'] = str(e)

    if result['stream_aborted'] or result.get('cli_killed', {}).get('killed'):
        result['status'] = 'aborted'
        result['message'] = '중단 완료'
        return jsonify(result)
    else:
        result['status'] = 'not_found'
        result['message'] = '스트림/CLI 없음'
        return jsonify(result), 404


@chat_bp.route('/chat/kill-all', methods=['POST'])
@login_required
def kill_all_cli():
    """모든 CLI 프로세스 강제 종료 (v2.4.3 긴급용)"""
    try:
        from src.services.cli_supervisor import kill_all_cli_processes
        result = kill_all_cli_processes()
        return jsonify({'status': 'success', **result})
    except Exception as e:
        log_error(f"Kill all CLI failed: {e}", error_type="CLI_ERROR")
        return jsonify({'status': 'error', 'error': str(e)}), 500


@chat_bp.route('/chat/background', methods=['POST'])
@login_required
def chat_background():
    """
    백그라운드 채팅 API - 클라이언트 연결 끊어도 서버에서 계속 실행

    Request JSON:
    {
        "message": "사용자 메시지",
        "agent": "pm",
        "session_id": "session_xxx"
    }

    Response:
    {
        "task_id": "bg_xxx",
        "status": "started",
        "message": "백그라운드 작업이 시작되었습니다"
    }
    """
    from src.services.background_tasks import start_chat_background
    from src.core.llm_caller import extract_project_from_message

    data = request.json
    user_message = data.get('message', '')
    agent_role = data.get('agent', 'pm')
    client_session_id = data.get('session_id')

    if not user_message:
        return jsonify({'error': 'Message required'}), 400

    # [PROJECT: xxx] 태그에서 프로젝트 추출
    current_project, _ = extract_project_from_message(user_message)

    # 세션 관리
    current_session_id = get_current_session()
    if client_session_id:
        current_session_id = client_session_id
        set_current_session(client_session_id)
    elif not current_session_id:
        current_session_id = db.create_session(agent=agent_role, project=current_project)
        set_current_session(current_session_id)

    # DB에 사용자 메시지 저장
    db.add_message(current_session_id, 'user', user_message, agent_role)

    # 백그라운드 작업 시작
    task_id = start_chat_background(current_session_id, agent_role, user_message)

    return jsonify({
        'task_id': task_id,
        'session_id': current_session_id,
        'status': 'started',
        'message': '백그라운드 작업이 시작되었습니다. 폰을 꺼도 서버에서 계속 실행됩니다.'
    })


@chat_bp.route('/chat/background/<task_id>', methods=['GET'])
@login_required
def get_background_task(task_id: str):
    """백그라운드 작업 상태 조회"""
    from src.services.background_tasks import get_task

    task = get_task(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404

    return jsonify(task)


@chat_bp.route('/chat/background/pending', methods=['GET'])
@login_required
def get_pending_results():
    """
    완료되었지만 아직 표시되지 않은 백그라운드 채팅 결과 조회

    재접속 시 이 API를 호출하여 놓친 결과를 가져옴
    """
    from src.services.background_tasks import get_unshown_completed_tasks, mark_result_shown
    import json as json_module

    current_session_id = get_current_session()
    if not current_session_id:
        return jsonify({'tasks': []})

    tasks = get_unshown_completed_tasks(current_session_id)

    # 결과 파싱 및 DB에 응답 저장
    results = []
    for task in tasks:
        try:
            if task.get('result'):
                result_data = json_module.loads(task['result'])
                response = result_data.get('response', '')
                model_info = result_data.get('model_info')
                agent = result_data.get('agent', task.get('agent_role', 'pm'))

                # DB에 어시스턴트 응답 저장 (아직 저장되지 않은 경우)
                db.add_message(task['session_id'], 'assistant', response, agent)

                results.append({
                    'task_id': task['id'],
                    'response': response,
                    'model_info': model_info,
                    'agent': agent,
                    'completed_at': task.get('completed_at'),
                    'original_message': task.get('message')
                })

                # 결과 확인됨 표시
                mark_result_shown(task['id'])
        except Exception as e:
            print(f"[BackgroundChat] Parse error for {task['id']}: {e}")

    return jsonify({
        'tasks': results,
        'count': len(results)
    })


@chat_bp.route('/history')
def get_history():
    """대화 히스토리 조회"""
    current_session_id = get_current_session()
    if not current_session_id:
        return jsonify([])
    messages = db.get_messages(current_session_id)
    return jsonify(messages)


@chat_bp.route('/history/clear', methods=['POST'])
def clear_history():
    """대화 히스토리 클리어"""
    current_session_id = get_current_session()
    if current_session_id:
        db.clear_messages(current_session_id)
    set_current_session(None)
    return jsonify({'status': 'cleared'})


@chat_bp.route('/agents')
def get_agents():
    """사용 가능한 에이전트 목록"""
    from config import DUAL_ENGINES, SINGLE_ENGINES

    agents = []

    for role, config in DUAL_ENGINES.items():
        agents.append({
            'role': role,
            'type': 'dual',
            'description': config.description,
            'engines': [config.engine_1.name, config.engine_2.name],
            'strategy': config.merge_strategy
        })

    for role, config in SINGLE_ENGINES.items():
        agents.append({
            'role': role,
            'type': 'single',
            'description': f'{role.upper()} - {config.name}',
            'engines': [config.name],
            'strategy': 'single'
        })

    return jsonify(agents)


@chat_bp.route('/system-prompt/<role>')
def get_agent_prompt(role: str):
    """에이전트 시스템 프롬프트 조회"""
    from config import get_system_prompt
    prompt = get_system_prompt(role)
    if not prompt:
        return jsonify({'error': f'Unknown role: {role}'}), 404
    return jsonify({'role': role, 'prompt': prompt})


@chat_bp.route('/projects')
def get_projects():
    """프로젝트 목록 조회 (사용자 권한에 따라 필터링)"""
    from config import PROJECTS
    from flask_login import current_user

    projects = []
    for project_id, config in PROJECTS.items():
        # 사용자의 allowed_projects 확인
        if current_user.is_authenticated:
            if not current_user.can_access_project(project_id):
                continue  # 접근 권한 없는 프로젝트 제외

        projects.append({
            'id': project_id,
            'name': config['name'],
            'description': config['description'],
            'path': config['path']
        })
    return jsonify(projects)


@chat_bp.route('/projects/<project_id>/files')
def get_project_files(project_id: str):
    """프로젝트 파일 목록 조회"""
    import glob
    import os
    from config import PROJECTS

    project = PROJECTS.get(project_id)
    if not project:
        return jsonify({'error': f'Unknown project: {project_id}'}), 404

    path = project['path']
    if not os.path.exists(path):
        return jsonify({'error': f'Project path not found: {path}'}), 404

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
        'files': files[:100]
    })


@chat_bp.route('/translate', methods=['POST'])
def translate():
    """번역 API"""
    import src.services.rag as rag

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
# v2.3.2 Jobs API - 브라우저 닫아도 백그라운드에서 계속 실행
# =============================================================================

# 진행 중인 Chat Jobs 저장소 (In-memory, Production에서는 Redis 권장)
_chat_jobs: dict[str, dict] = {}


@chat_bp.route('/chat/submit', methods=['POST'])
@login_required
def submit_chat_job():
    """
    채팅 작업 제출 API (Jobs API 모드)

    브라우저가 닫혀도 백그라운드에서 계속 실행됩니다.
    결과는 /api/chat/job/<job_id>로 폴링하여 확인합니다.

    Request JSON:
    {
        "message": "사용자 메시지",
        "agent": "pm",
        "session_id": "session_xxx",
        "project": "hattz_empire"
    }

    Response:
    {
        "job_id": "chat_xxx",
        "session_id": "session_xxx",
        "status": "pending",
        "message": "작업이 큐에 등록되었습니다"
    }
    """
    import threading

    data = request.json
    user_message = data.get('message', '')
    agent_role = data.get('agent', 'pm')
    client_session_id = data.get('session_id')
    project = data.get('project')

    if not user_message:
        return jsonify({'error': 'Message required'}), 400

    # 세션 관리
    current_session_id = client_session_id
    if not current_session_id:
        current_session_id = db.create_session(agent=agent_role, project=project)

    set_current_session(current_session_id)

    # DB에 사용자 메시지 저장
    db.add_message(current_session_id, 'user', user_message, agent_role)

    # Job ID 생성
    job_id = f"chat_{uuid.uuid4().hex[:12]}"

    # Job 초기화
    _chat_jobs[job_id] = {
        'id': job_id,
        'session_id': current_session_id,
        'agent': agent_role,
        'message': user_message,
        'project': project,
        'status': 'pending',
        'stage': 'waiting',
        'created_at': datetime.now().isoformat(),
        'response': None,
        'model_info': None,
        'error': None,
    }

    # 백그라운드 스레드로 실행
    def run_chat_job():
        try:
            _execute_chat_job(job_id)
        except Exception as e:
            print(f"[ChatJob] Error in {job_id}: {e}")
            _chat_jobs[job_id]['status'] = 'failed'
            _chat_jobs[job_id]['error'] = str(e)

    thread = threading.Thread(target=run_chat_job, daemon=True)
    thread.start()

    return jsonify({
        'job_id': job_id,
        'session_id': current_session_id,
        'status': 'pending',
        'message': '작업이 큐에 등록되었습니다. 브라우저를 닫아도 백그라운드에서 계속 실행됩니다.'
    })


def _execute_chat_job(job_id: str):
    """
    백그라운드에서 채팅 작업 실행

    기존 chat_stream()의 로직을 동기 방식으로 실행합니다.
    """
    job = _chat_jobs.get(job_id)
    if not job:
        return

    session_id = job['session_id']
    agent_role = job['agent']
    user_message = job['message']

    try:
        # Stage: thinking
        job['status'] = 'processing'
        job['stage'] = 'thinking'

        # v2.3 Pre-Run Hook
        session_rules = None
        rules_hash = ""
        try:
            hook_result = run_pre_run_hook(session_id, user_message)
            if hook_result["success"]:
                session_rules = hook_result["session_rules"]
                rules_hash = hook_result["rules_hash"]
        except Exception as e:
            print(f"[ChatJob] Pre-run error: {e}")

        # LLM 호출
        response, model_meta = call_agent(user_message, agent_role, return_meta=True)

        job['stage'] = 'responding'

        # [CALL:agent] 태그 처리
        has_calls = executor.has_call_tags(response)
        call_infos = executor.extract_call_info(response) if has_calls else []

        if has_calls and call_infos:
            job['stage'] = 'delegating'

            call_results = []
            for idx, call_info in enumerate(call_infos):
                sub_agent = call_info['agent']
                sub_message = call_info['message']

                job['stage'] = 'calling'
                job['sub_agent'] = sub_agent
                job['status_message'] = f'{sub_agent.upper()} 호출 중 ({idx+1}/{len(call_infos)})'

                try:
                    # 하위 에이전트 호출 (PM이 [CALL:*] 태그로 호출 → _internal_call=True)
                    sub_response, sub_meta = call_agent(sub_message, sub_agent, auto_execute=True, use_translation=False, return_meta=True, _internal_call=True)

                    # Static Gate 검사
                    if session_rules:
                        static_result = run_static_gate(sub_response, session_rules, session_id)
                        if not static_result["passed"]:
                            print(f"[ChatJob] Static Gate REJECT: {sub_agent}")

                    call_results.append({
                        'agent': sub_agent,
                        'message': sub_message,
                        'response': sub_response,
                    })

                    # DB에 하위 에이전트 응답 저장
                    db.add_message(session_id, 'assistant', f"[{sub_agent.upper()}]\n{sub_response}", sub_agent, model_id=sub_meta.get('model_name'), is_internal=True)

                except Exception as e:
                    print(f"[ChatJob] Sub-agent error {sub_agent}: {e}")

            # 결과 종합
            if call_results:
                job['stage'] = 'summarizing'
                job['status_message'] = 'PM이 결과를 종합하고 있습니다...'

                followup_prompt = build_call_results_prompt(call_results)
                final_response, final_meta = call_agent(followup_prompt, agent_role, return_meta=True)

                # 최종 응답 저장
                db.add_message(session_id, 'assistant', final_response, agent_role, model_id=final_meta.get('model_name'))

                job['response'] = final_response
                job['model_info'] = final_meta
            else:
                # CALL은 있었지만 결과 없음
                db.add_message(session_id, 'assistant', response, agent_role, model_id=model_meta.get('model_name'))
                job['response'] = response
                job['model_info'] = model_meta
        else:
            # CALL 태그 없음 - PM 응답만
            db.add_message(session_id, 'assistant', response, agent_role, model_id=model_meta.get('model_name'))
            job['response'] = response
            job['model_info'] = model_meta

        # 완료
        job['status'] = 'completed'
        job['stage'] = 'done'
        job['completed_at'] = datetime.now().isoformat()

        print(f"[ChatJob] Completed: {job_id}")

    except Exception as e:
        job['status'] = 'failed'
        job['error'] = str(e)
        job['completed_at'] = datetime.now().isoformat()
        print(f"[ChatJob] Failed: {job_id} - {e}")


@chat_bp.route('/chat/job/<job_id>', methods=['GET'])
@login_required
def get_chat_job(job_id: str):
    """
    채팅 작업 상태 조회 API (Long Polling 지원)

    Query params:
    - wait: true면 Long Polling (최대 30초 대기)
    - timeout: 대기 시간 (초, 기본 30, 최대 60)

    Long Polling:
    - 작업이 완료/실패될 때까지 응답을 보류
    - 완료되면 즉시 응답
    - timeout 도달 시 현재 상태 반환

    Response:
    {
        "id": "chat_xxx",
        "status": "processing|completed|failed",
        "stage": "thinking|responding|delegating|calling|summarizing|done",
        "response": "AI 응답 (완료 시)",
        "model_info": {...},
        "error": "에러 메시지 (실패 시)"
    }
    """
    job = _chat_jobs.get(job_id)

    if not job:
        return jsonify({'error': 'Job not found'}), 404

    # Long Polling 처리
    use_long_poll = request.args.get('wait', 'false').lower() == 'true'
    timeout = min(int(request.args.get('timeout', 30)), 60)  # 최대 60초

    if use_long_poll and job['status'] not in ('completed', 'failed'):
        # 완료될 때까지 대기 (0.5초 간격 체크)
        import time
        start_time = time.time()
        last_stage = job.get('stage')

        while time.time() - start_time < timeout:
            job = _chat_jobs.get(job_id)
            if not job:
                return jsonify({'error': 'Job not found'}), 404

            # 완료/실패 시 즉시 반환
            if job['status'] in ('completed', 'failed'):
                break

            # stage 변경 시에도 반환 (진행 상황 업데이트)
            current_stage = job.get('stage')
            if current_stage != last_stage:
                last_stage = current_stage
                break

            time.sleep(0.5)  # 0.5초 대기

    return jsonify({
        'id': job['id'],
        'session_id': job['session_id'],
        'status': job['status'],
        'stage': job.get('stage', 'waiting'),
        'sub_agent': job.get('sub_agent'),
        'status_message': job.get('status_message', ''),
        'response': job.get('response'),
        'model_info': job.get('model_info'),
        'error': job.get('error'),
        'created_at': job.get('created_at'),
        'completed_at': job.get('completed_at'),
    })


@chat_bp.route('/chat/jobs', methods=['GET'])
@login_required
def list_chat_jobs():
    """
    현재 세션의 채팅 작업 목록 조회

    Query params:
    - session_id: 세션 ID (optional)
    - status: 상태 필터 (pending|processing|completed|failed)
    """
    session_id = request.args.get('session_id') or get_current_session()
    status_filter = request.args.get('status')

    jobs = []
    for job in _chat_jobs.values():
        if session_id and job['session_id'] != session_id:
            continue
        if status_filter and job['status'] != status_filter:
            continue
        jobs.append({
            'id': job['id'],
            'status': job['status'],
            'stage': job.get('stage'),
            'created_at': job.get('created_at'),
            'completed_at': job.get('completed_at'),
        })

    # 최신순 정렬
    jobs.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    return jsonify({
        'jobs': jobs[:20],  # 최근 20개만
        'total': len(jobs)
    })


# =============================================================================
# v2.6.2 Dual Loop Handler
# =============================================================================

def _handle_dual_loop_stream(data: dict, user_message: str) -> Response:
    """
    "최고!" 프리픽스로 시작하는 요청을 Dual Loop로 처리

    GPT-5.2 (Strategist/Reviewer) <-> Claude Opus (Coder) 핑퐁 루프

    흐름:
    1. GPT-5.2 Strategist: 설계/분석/방향 제시
    2. Claude Opus Coder: 구현/코드 작성
    3. GPT-5.2 Reviewer: 리뷰/승인 여부 결정
    4. APPROVE -> 완료, REVISE -> 다음 iteration (최대 5회)
    """
    from src.services.dual_loop import run_dual_loop

    client_session_id = data.get('session_id')

    # 프리픽스 제거 ("최고!" / "best!")
    task = user_message
    for prefix in ["최고! ", "최고!", "best! ", "best!", "BEST! ", "BEST!"]:
        if task.startswith(prefix):
            task = task[len(prefix):].strip()
            break

    # [PROJECT: xxx] 태그에서 프로젝트 추출
    current_project, task = extract_project_from_message(task)

    # 세션 관리
    current_session_id = get_current_session()
    if client_session_id:
        current_session_id = client_session_id
        set_current_session(client_session_id)
    elif not current_session_id:
        current_session_id = db.create_session(agent='dual_loop', project=current_project)
        set_current_session(current_session_id)

    # DB에 사용자 메시지 저장
    db.add_message(current_session_id, 'user', user_message, 'dual_loop')

    def generate():
        """SSE 스트림으로 Dual Loop 진행 상황 전송"""
        try:
            # 시작 알림
            yield f"data: {json.dumps({'type': 'dual_loop_start', 'task': task[:100]})}\n\n"

            final_result = None

            for event in run_dual_loop(task, current_session_id, current_project):
                stage = event.get('stage', '')
                iteration = event.get('iteration', 0)
                content = event.get('content', '')

                # 진행 상황 전송
                sse_event = {
                    'type': 'dual_loop_progress',
                    'stage': stage,
                    'iteration': iteration,
                    'content': content[:500] if len(content) > 500 else content,
                }

                if 'verdict' in event:
                    sse_event['verdict'] = event['verdict']

                yield f"data: {json.dumps(sse_event, ensure_ascii=False)}\n\n"

                # 완료/중단 시 최종 결과 저장
                if stage in ['complete', 'abort', 'max_iterations', 'error']:
                    final_result = event

            # 최종 결과 전송
            if final_result:
                final_content = final_result.get('content', '')

                # DB에 최종 결과 저장
                db.add_message(
                    current_session_id,
                    'assistant',
                    final_content,
                    'dual_loop'
                )

                yield f"data: {json.dumps({'type': 'dual_loop_complete', 'result': final_result}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            error_msg = f"Dual Loop error: {str(e)}"
            log_error(error_msg, session_id=current_session_id, error_type="DUAL_LOOP_ERROR")
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

    return Response(generate(), mimetype='text/event-stream')
