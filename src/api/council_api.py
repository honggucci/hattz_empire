"""
Hattz Empire - Council API (v2.3.1)
Persona Council 위원회 API

v2.3.1: 위원회 판정을 DB에 저장하고 임베딩
- session_id, project 파라미터로 저장 컨텍스트 설정
- 모든 페르소나 판정 + 최종 verdict가 DB에 기록됨
"""
from flask import request, jsonify

from . import council_bp
from src.infra.council import get_council, COUNCIL_TYPES, PERSONAS


@council_bp.route('/types', methods=['GET'])
def get_types():
    """위원회 유형 목록 조회"""
    types = []
    for key, config in COUNCIL_TYPES.items():
        types.append({
            'id': key,
            'name': config['name'],
            'description': config['description'],
            'personas': config['personas'],
            'pass_threshold': config['pass_threshold'],
        })
    return jsonify({'council_types': types})


@council_bp.route('/personas', methods=['GET'])
def get_personas():
    """페르소나 목록 조회"""
    personas = []
    for key, config in PERSONAS.items():
        personas.append({
            'id': config.id,
            'name': config.name,
            'icon': config.icon,
            'temperature': config.temperature,
        })
    return jsonify({'personas': personas})


@council_bp.route('/convene', methods=['POST'])
def convene():
    """
    위원회 소집 API

    Request JSON:
    {
        "council_type": "code",
        "content": "검토할 내용",
        "context": "추가 컨텍스트 (선택)",
        "session_id": "세션 ID (선택, DB 저장용)",
        "project": "프로젝트명 (선택, 임베딩 필터링용)"
    }
    """
    data = request.json
    council_type = data.get('council_type', 'code')
    content = data.get('content', '')
    context = data.get('context', '')
    session_id = data.get('session_id')  # v2.3.1: DB 저장용
    project = data.get('project')  # v2.3.1: 임베딩 필터링용

    if not content:
        return jsonify({'error': 'content required'}), 400

    if council_type not in COUNCIL_TYPES:
        return jsonify({'error': f'Unknown council type: {council_type}'}), 400

    # v2.3.1: session_id 전달 시 DB에 저장됨
    council = get_council(session_id=session_id, project=project)
    verdict = council.convene_sync(council_type, content, context)

    return jsonify({
        'council_type': verdict.council_type,
        'verdict': verdict.verdict.value,
        'average_score': verdict.average_score,
        'score_std': verdict.score_std,
        'judges': [
            {
                'persona_id': j.persona_id,
                'persona_name': j.persona_name,
                'icon': j.icon,
                'score': j.score,
                'reasoning': j.reasoning,
                'concerns': j.concerns,
                'approvals': j.approvals,
            }
            for j in verdict.judges
        ],
        'summary': verdict.summary,
        'requires_ceo': verdict.requires_ceo,
        'timestamp': verdict.timestamp,
    })


@council_bp.route('/history', methods=['GET'])
def get_history():
    """위원회 판정 히스토리 조회"""
    limit = request.args.get('limit', 10, type=int)
    council = get_council()
    history = council.get_history(limit)

    return jsonify({
        'history': [
            {
                'council_type': v.council_type,
                'verdict': v.verdict.value,
                'average_score': v.average_score,
                'requires_ceo': v.requires_ceo,
                'timestamp': v.timestamp,
            }
            for v in history
        ],
        'total': len(history)
    })
