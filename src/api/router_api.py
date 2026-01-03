"""
Hattz Empire - Router API
HattzRouter 라우팅 분석 API
"""
from flask import request, jsonify

from . import router_bp
from src.core.router import get_router, route_message


@router_bp.route('/analyze', methods=['POST'])
def analyze():
    """
    메시지 라우팅 분석 API

    Request JSON:
    {
        "message": "분석할 메시지",
        "agent": "pm"
    }
    """
    data = request.json
    message = data.get('message', '')
    agent = data.get('agent', 'pm')

    if not message:
        return jsonify({'error': 'message required'}), 400

    try:
        routing = route_message(message, agent)
        return jsonify({
            'model_tier': routing.model_tier,
            'model_id': routing.model_id,
            'reason': routing.reason,
            'estimated_tokens': routing.estimated_tokens,
            'fallback_model': routing.fallback_model
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@router_bp.route('/stats', methods=['GET'])
def stats():
    """라우터 설정 통계"""
    try:
        router = get_router()
        return jsonify(router.get_stats())
    except Exception as e:
        return jsonify({'error': str(e)}), 500
