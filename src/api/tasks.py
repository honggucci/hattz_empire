"""
Hattz Empire - Background Tasks API
백그라운드 작업 API
"""
from flask import request, jsonify

from . import task_bp
from src.core.llm_caller import call_agent
import src.services.database as db
import src.services.background_tasks as bg


@task_bp.route('/task/start', methods=['POST'])
def start():
    """
    백그라운드 작업 시작 API

    Request JSON:
    {
        "message": "분석해줘",
        "agent": "pm",
        "session_id": "session_xxx"
    }
    """
    data = request.json
    message = data.get('message', '')
    agent_role = data.get('agent', 'pm')
    session_id = data.get('session_id')

    if not message:
        return jsonify({'error': 'message required'}), 400

    if not session_id:
        session_id = db.create_session(agent=agent_role)

    task_id = bg.create_task(session_id, agent_role, message)
    db.add_message(session_id, 'user', message, agent_role)

    def worker(msg: str, role: str, progress_cb):
        progress_cb(10, "thinking")
        response = call_agent(msg, role)
        progress_cb(90, "finalizing")
        db.add_message(session_id, 'assistant', response, role)
        return response

    bg.start_task(task_id, worker)

    return jsonify({
        'task_id': task_id,
        'status': 'running',
        'session_id': session_id
    })


@task_bp.route('/task/<task_id>', methods=['GET'])
def get_status(task_id: str):
    """작업 상태 조회 API"""
    task = bg.get_task(task_id)

    if not task:
        return jsonify({'error': 'Task not found'}), 404

    return jsonify(task)


@task_bp.route('/tasks', methods=['GET'])
def get_session_tasks():
    """현재 세션의 모든 백그라운드 작업 조회"""
    session_id = request.args.get('session_id')

    if not session_id:
        return jsonify({'error': 'session_id required'}), 400

    tasks = bg.get_tasks_by_session(session_id)

    return jsonify({
        'tasks': tasks,
        'total': len(tasks)
    })


@task_bp.route('/task/<task_id>/cancel', methods=['POST'])
def cancel(task_id: str):
    """작업 취소 API"""
    success = bg.cancel_task(task_id)

    if success:
        return jsonify({'status': 'cancelled', 'task_id': task_id})
    else:
        return jsonify({'error': 'Cannot cancel task'}), 400


@task_bp.route('/tasks/unshown', methods=['GET'])
def get_unshown():
    """
    완료되었지만 아직 확인하지 않은 작업 조회 API
    페이지 로드 시 호출하여 미확인 결과 표시
    """
    session_id = request.args.get('session_id')

    if not session_id:
        return jsonify({'error': 'session_id required'}), 400

    tasks = bg.get_unshown_completed_tasks(session_id)

    return jsonify({
        'tasks': tasks,
        'total': len(tasks)
    })


@task_bp.route('/task/<task_id>/shown', methods=['POST'])
def mark_shown(task_id: str):
    """작업 결과를 확인했음을 표시"""
    success = bg.mark_result_shown(task_id)

    if success:
        return jsonify({'status': 'marked', 'task_id': task_id})
    else:
        return jsonify({'error': 'Failed to mark'}), 400
