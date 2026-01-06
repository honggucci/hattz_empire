"""
Hattz Empire - Session API
세션 관리 API 엔드포인트

v2.2.5: RLS (Row Level Security) 추가
- test 계정은 project='test' 세션만 조회/접근 가능
- admin 계정은 모든 세션 접근 가능
"""
from flask import request, jsonify
from flask_login import current_user

from . import session_bp
from src.core.session_state import get_current_session, set_current_session
import src.services.database as db


def get_user_allowed_projects():
    """현재 사용자의 접근 가능 프로젝트 목록 반환 (RLS용)"""
    if current_user.is_authenticated:
        return current_user.allowed_projects  # None이면 모든 프로젝트
    return []  # 비로그인: 접근 불가


def check_session_access(session_data):
    """세션 접근 권한 확인 (RLS)"""
    if not session_data:
        return False
    allowed = get_user_allowed_projects()
    if allowed is None:  # admin: 모든 프로젝트 접근 가능
        return True
    return session_data.get('project') in allowed


@session_bp.route('', methods=['GET'])
def list_sessions():
    """세션 목록 조회 (RLS 적용)"""
    allowed = get_user_allowed_projects()
    sessions = db.list_sessions(limit=50, allowed_projects=allowed)
    return jsonify(sessions)


@session_bp.route('', methods=['POST'])
def create_session():
    """새 세션 생성"""
    data = request.json or {}
    name = data.get('name')
    project = data.get('project')
    agent = data.get('agent', 'pm')

    # RLS: 제한된 사용자는 허용된 프로젝트에만 세션 생성 가능
    allowed = get_user_allowed_projects()
    if allowed is not None and project and project not in allowed:
        return jsonify({'error': 'Access denied: project not allowed'}), 403

    session_id = db.create_session(name=name, project=project, agent=agent)
    set_current_session(session_id)

    return jsonify({
        'session_id': session_id,
        'status': 'created'
    })


@session_bp.route('/<session_id>', methods=['GET'])
def get_session(session_id: str):
    """세션 상세 조회 (RLS 적용)"""
    session_data = db.get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Session not found'}), 404
    if not check_session_access(session_data):
        return jsonify({'error': 'Access denied'}), 403
    return jsonify(session_data)


@session_bp.route('/<session_id>', methods=['PUT'])
def update_session(session_id: str):
    """세션 업데이트 (RLS 적용)"""
    session_data = db.get_session(session_id)
    if not check_session_access(session_data):
        return jsonify({'error': 'Access denied'}), 403

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
    """세션 삭제 (RLS 적용)"""
    session_data = db.get_session(session_id)
    if not check_session_access(session_data):
        return jsonify({'error': 'Access denied'}), 403

    current_session_id = get_current_session()
    success = db.delete_session(session_id)
    if success:
        if current_session_id == session_id:
            set_current_session(None)
        return jsonify({'status': 'deleted'})
    return jsonify({'error': 'Session not found'}), 404


@session_bp.route('/<session_id>/messages', methods=['GET'])
def get_session_messages(session_id: str):
    """세션 메시지 목록 조회 (RLS 적용)"""
    session_data = db.get_session(session_id)
    if not check_session_access(session_data):
        return jsonify({'error': 'Access denied'}), 403

    messages = db.get_messages(session_id, limit=100)
    return jsonify(messages)


@session_bp.route('/<session_id>/switch', methods=['POST'])
def switch_session(session_id: str):
    """현재 세션 전환 (RLS 적용)"""
    session_data = db.get_session(session_id)
    if not session_data:
        return jsonify({'error': 'Session not found'}), 404
    if not check_session_access(session_data):
        return jsonify({'error': 'Access denied'}), 403

    set_current_session(session_id)
    messages = db.get_messages(session_id)
    return jsonify({
        'session': session_data,
        'messages': messages
    })


@session_bp.route('/current', methods=['GET'])
def get_current():
    """현재 활성 세션 조회 (RLS 적용)"""
    current_session_id = get_current_session()
    if not current_session_id:
        return jsonify({'session': None, 'messages': []})

    session_data = db.get_session(current_session_id)

    # RLS 체크: 현재 세션이 접근 불가하면 초기화
    if not check_session_access(session_data):
        set_current_session(None)
        return jsonify({'session': None, 'messages': []})

    messages = db.get_messages(current_session_id) if session_data else []
    return jsonify({
        'session': session_data,
        'messages': messages
    })
