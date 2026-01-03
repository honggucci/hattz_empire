"""
Hattz Empire - Circuit Breaker API
Circuit Breaker 상태 관리 API
"""
from flask import request, jsonify
from flask_login import login_required

from . import breaker_bp
from src.infra.circuit_breaker import get_breaker


@breaker_bp.route('/status', methods=['GET'])
def status():
    """Circuit Breaker 상태 조회"""
    breaker = get_breaker()
    return jsonify(breaker.get_status())


@breaker_bp.route('/task/<task_id>', methods=['GET'])
def task_status(task_id: str):
    """태스크별 브레이커 상태 조회"""
    breaker = get_breaker()
    status = breaker.get_task_status(task_id)
    if not status:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(status)


@breaker_bp.route('/reset', methods=['POST'])
@login_required
def reset():
    """Circuit Breaker 리셋 (CEO 권한)"""
    breaker = get_breaker()
    breaker.reset_breaker()
    return jsonify({'status': 'reset', 'state': breaker.state.value})


@breaker_bp.route('/stop/<task_id>', methods=['POST'])
def force_stop(task_id: str):
    """태스크 강제 중단"""
    data = request.json or {}
    reason = data.get('reason', '수동 중단')

    breaker = get_breaker()
    breaker.force_stop(task_id, reason)
    return jsonify({'status': 'stopped', 'task_id': task_id, 'reason': reason})
