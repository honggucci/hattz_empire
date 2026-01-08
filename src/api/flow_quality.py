"""
Flow Quality API
부트로더 원칙 준수 모니터링 API

Endpoints:
    GET  /flow                         - 대시보드 페이지
    GET  /api/flow/report              - 전체 품질 리포트
    GET  /api/flow/session/<id>        - 세션별 리포트
    POST /api/flow/transition          - PM DFA 상태 전이 기록
    POST /api/flow/escalation          - Retry Escalation 기록
    GET  /api/flow/violations          - 최근 위반 목록
"""
from flask import Blueprint, jsonify, request, render_template
from src.services.flow_monitor import get_flow_monitor

flow_bp = Blueprint('flow', __name__)


# =============================================================================
# 페이지 라우트
# =============================================================================

@flow_bp.route('/flow')
def flow_dashboard():
    """Flow Quality 대시보드 페이지"""
    return render_template('flow.html')


# =============================================================================
# API 라우트
# =============================================================================

@flow_bp.route('/api/flow/report', methods=['GET'])
def get_global_report():
    """
    전체 Flow Quality 리포트

    Returns:
        {
            "total_sessions": int,
            "total_outputs": int,
            "valid_outputs": int,
            "compliance_rate": float,
            "average_quality_score": int,
            "violation_counts": {...},
            "total_violations": int,
            "recent_violations": [...]
        }
    """
    monitor = get_flow_monitor()
    report = monitor.get_global_report()
    return jsonify(report)


@flow_bp.route('/api/flow/session/<session_id>', methods=['GET'])
def get_session_report(session_id: str):
    """
    세션별 Flow Quality 리포트

    Args:
        session_id: 세션 ID

    Returns:
        {
            "session_id": str,
            "started_at": str,
            "total_outputs": int,
            "valid_outputs": int,
            "role_violations": int,
            "contract_violations": int,
            "dfa_violations": int,
            "chatter_violations": int,
            "monotonicity_violations": int,
            "current_state": str,
            "state_history": [...],
            "retry_count": int,
            "escalation_level": str,
            "violations": [...],
            "compliance_rate": float,
            "quality_score": int
        }
    """
    monitor = get_flow_monitor()
    report = monitor.get_session_report(session_id)
    return jsonify(report)


@flow_bp.route('/api/flow/transition', methods=['POST'])
def record_transition():
    """
    PM DFA 상태 전이 기록

    Request Body:
        {
            "session_id": str,
            "from_state": str,  # DISPATCH, RETRY, BLOCKED, ESCALATE, DONE
            "to_state": str
        }

    Returns:
        {
            "valid": bool,
            "from_state": str,
            "to_state": str,
            "violation": str (optional)
        }
    """
    data = request.get_json()
    session_id = data.get('session_id')
    from_state = data.get('from_state')
    to_state = data.get('to_state')

    if not all([session_id, from_state, to_state]):
        return jsonify({"error": "session_id, from_state, to_state required"}), 400

    monitor = get_flow_monitor()
    result = monitor.record_transition(session_id, from_state, to_state)
    return jsonify(result)


@flow_bp.route('/api/flow/escalation', methods=['POST'])
def record_escalation():
    """
    Retry Escalation 기록

    Request Body:
        {
            "session_id": str,
            "level": str  # SELF_REPAIR, ROLE_SWITCH, HARD_FAIL
        }

    Returns:
        {
            "valid": bool,
            "previous_level": str,
            "new_level": str,
            "violation": str (optional)
        }
    """
    data = request.get_json()
    session_id = data.get('session_id')
    level = data.get('level')

    if not all([session_id, level]):
        return jsonify({"error": "session_id, level required"}), 400

    monitor = get_flow_monitor()
    result = monitor.record_escalation(session_id, level)
    return jsonify(result)


@flow_bp.route('/api/flow/violations', methods=['GET'])
def get_violations():
    """
    최근 위반 목록

    Query Params:
        limit: int (default 20)
        session_id: str (optional - filter by session)
        violation_type: str (optional - filter by type)

    Returns:
        {
            "violations": [
                {
                    "timestamp": str,
                    "session_id": str,
                    "agent": str,
                    "violation_type": str,
                    "details": str,
                    "severity": str
                },
                ...
            ],
            "total": int
        }
    """
    limit = request.args.get('limit', 20, type=int)
    session_filter = request.args.get('session_id')
    type_filter = request.args.get('violation_type')

    monitor = get_flow_monitor()
    report = monitor.get_global_report()

    violations = report.get('recent_violations', [])

    # 필터링
    if session_filter:
        violations = [v for v in violations if v.get('session_id') == session_filter]

    if type_filter:
        violations = [v for v in violations if v.get('violation_type') == type_filter]

    # 제한
    violations = violations[:limit]

    return jsonify({
        "violations": violations,
        "total": len(violations)
    })


@flow_bp.route('/api/flow/validate', methods=['POST'])
def validate_output():
    """
    에이전트 출력 검증 (테스트용)

    Request Body:
        {
            "agent": str,
            "output": str,
            "session_id": str (optional)
        }

    Returns:
        {
            "violations": [...],
            "valid": bool
        }
    """
    data = request.get_json()
    agent = data.get('agent')
    output = data.get('output')
    session_id = data.get('session_id', 'test-session')

    if not all([agent, output]):
        return jsonify({"error": "agent, output required"}), 400

    monitor = get_flow_monitor()
    result = monitor.validate_output(agent, output, session_id)
    return jsonify(result)
