"""
Hattz Empire - Chat API
채팅 관련 API 엔드포인트
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

# Control Module (Session Rules System)
from src.control import (
    get_rules_for_session,
    StaticChecker,
    get_event_bus,
    get_audit_logger,
)


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
    채팅 API (streaming) - 하이브리드 모드

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

    def generate():
        try:
            # 첫 번째로 세션 ID와 스트림 ID 전송
            yield f"data: {json.dumps({'session_id': session_id, 'stream_id': stream_id}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'stage': 'thinking', 'agent': agent_role}, ensure_ascii=False)}\n\n"

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

            # PM 응답 완료 (단, CALL 태그가 있으면 아직 done이 아님)
            yield f"data: {json.dumps({'pm_done': True, 'pm_response': pm_response, 'agent': agent_role, 'model_info': model_meta}, ensure_ascii=False)}\n\n"
            db.add_message(session_id, 'assistant', pm_response, agent_role)

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
                        # 하위 에이전트 호출
                        sub_response, sub_meta = call_agent(sub_message, sub_agent, auto_execute=True, use_translation=False, return_meta=True)

                        # =====================================================
                        # [Control] 정적 검사 (Constitution + Session Rules)
                        # =====================================================
                        try:
                            rules = get_rules_for_session(session_id)
                            checker = StaticChecker(rules)
                            check_result = checker.check(sub_response, file_type="python")

                            event_bus = get_event_bus()
                            audit_logger = get_audit_logger()

                            # EventBus로 검토 이벤트 발행
                            event_bus.emit_static_check_result(
                                session_id=session_id,
                                passed=check_result.passed,
                                violations_count=len(check_result.violations),
                                has_critical=check_result.has_critical(),
                            )

                            # Audit 로깅
                            audit_logger.log_static_check(
                                rules=rules,
                                static_result=check_result,
                                worker_agent=sub_agent,
                                original_request=sub_message[:200],
                            )

                            if not check_result.passed:
                                # 위반 발견 - 클라이언트에 경고 전송
                                violations_summary = [
                                    {"rule": v.rule_key, "severity": v.severity.value, "message": v.message}
                                    for v in check_result.violations[:5]  # 최대 5개
                                ]
                                yield f"data: {json.dumps({'stage': 'control_warning', 'sub_agent': sub_agent, 'violations': violations_summary, 'passed': False}, ensure_ascii=False)}\n\n"

                                # Critical 위반은 응답에 경고 추가
                                if check_result.has_critical():
                                    sub_response = f"⚠️ [CONTROL WARNING] Constitution 위반 감지됨!\n\n{sub_response}"
                                    print(f"[Control] ⚠️ CRITICAL violation in {sub_agent} response!")
                            else:
                                print(f"[Control] ✅ {sub_agent} response passed static check")
                        except Exception as ctrl_err:
                            print(f"[Control] Error during static check: {ctrl_err}")

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
                    db.add_message(session_id, 'assistant', f"[{sub_agent.upper()}]\n{sub_response}", sub_agent, is_internal=True)

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

                    db.add_message(session_id, 'assistant', final_response, agent_role)

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
    """스트리밍 중단 API"""
    data = request.json
    stream_id = data.get('stream_id')

    if not stream_id:
        return jsonify({'error': 'stream_id required'}), 400

    if stream_id in active_streams:
        active_streams[stream_id] = False
        return jsonify({
            'status': 'aborted',
            'stream_id': stream_id,
            'message': '스트림 중단 요청됨'
        })
    else:
        return jsonify({
            'status': 'not_found',
            'stream_id': stream_id,
            'message': '스트림을 찾을 수 없음 (이미 종료되었거나 존재하지 않음)'
        }), 404


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
