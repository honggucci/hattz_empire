"""
Hattz Empire - Session API
세션 관리 API 엔드포인트
"""
from flask import request, jsonify

from . import session_bp
from src.core.session_state import get_current_session, set_current_session
import src.services.database as db


@session_bp.route('', methods=['GET'])
def list_sessions():
    """세션 목록 조회"""
    sessions = db.list_sessions(limit=50)
    return jsonify(sessions)


@session_bp.route('', methods=['POST'])
def create_session():
    """새 세션 생성"""
    data = request.json or {}
    name = data.get('name')
    project = data.get('project')
    agent = data.get('agent', 'pm')

    session_id = db.create_session(name=name, project=project, agent=agent)
    set_current_session(session_id)

    return jsonify({
        'session_id': session_id,
        'status': 'created'
    })


@session_bp.route('/<session_id>', methods=['GET'])
def get_session(session_id: str):
    """세션 상세 조회"""
    session_data = db.get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify(session_data)


@session_bp.route('/<session_id>', methods=['PUT'])
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


@session_bp.route('/<session_id>', methods=['DELETE'])
def delete_session(session_id: str):
    """세션 삭제"""
    current_session_id = get_current_session()
    success = db.delete_session(session_id)
    if success:
        if current_session_id == session_id:
            set_current_session(None)
        return jsonify({'status': 'deleted'})
    return jsonify({'error': 'Session not found'}), 404


@session_bp.route('/<session_id>/messages', methods=['GET'])
def get_session_messages(session_id: str):
    """세션 메시지 목록 조회"""
    messages = db.get_messages(session_id, limit=100)
    return jsonify(messages)


@session_bp.route('/<session_id>/switch', methods=['POST'])
def switch_session(session_id: str):
    """현재 세션 전환"""
    session_data = db.get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Session not found'}), 404

    set_current_session(session_id)
    messages = db.get_messages(session_id)
    return jsonify({
        'session': session_data,
        'messages': messages
    })


@session_bp.route('/current', methods=['GET'])
def get_current():
    """현재 활성 세션 조회"""
    current_session_id = get_current_session()
    if not current_session_id:
        return jsonify({'session': None, 'messages': []})

    session_data = db.get_session(current_session_id)
    messages = db.get_messages(current_session_id) if session_data else []
    return jsonify({
        'session': session_data,
        'messages': messages
    })
