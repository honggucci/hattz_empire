"""
Hattz Empire - Scores API
Agent Scorecard API 엔드포인트
"""
from flask import request, jsonify

from . import score_bp
from src.services.agent_scorecard import get_scorecard, FeedbackType, SCORE_RULES


@score_bp.route('/feedback', methods=['POST'])
def submit_feedback():
    """
    CEO 피드백 제출 API

    Request JSON:
    {
        "message_id": "msg_xxx",
        "feedback_type": "ceo_approve" | "ceo_reject" | "ceo_redo",
        "session_id": "session_xxx",
        "note": "선택적 코멘트"
    }
    """
    data = request.json
    message_id = data.get('message_id')
    feedback_type_str = data.get('feedback_type', '')
    session_id = data.get('session_id')
    note = data.get('note', '')

    if not message_id or not feedback_type_str:
        return jsonify({'error': 'message_id and feedback_type required'}), 400

    feedback_map = {
        'ceo_approve': FeedbackType.CEO_APPROVE,
        'ceo_reject': FeedbackType.CEO_REJECT,
        'ceo_redo': FeedbackType.CEO_REDO,
    }

    feedback_type = feedback_map.get(feedback_type_str)
    if not feedback_type:
        return jsonify({'error': f'Unknown feedback_type: {feedback_type_str}'}), 400

    try:
        scorecard = get_scorecard()
        recent_log_id = scorecard.get_recent_log_id(session_id)

        if recent_log_id:
            score_delta = SCORE_RULES.get(feedback_type, 0)
            scorecard.add_feedback(recent_log_id, feedback_type, note)

            return jsonify({
                'status': 'ok',
                'log_id': recent_log_id,
                'feedback': feedback_type_str,
                'score_delta': score_delta
            })
        else:
            return jsonify({
                'status': 'ok',
                'message': 'No logs to update, feedback recorded'
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@score_bp.route('/scores', methods=['GET'])
def get_scores():
    """에이전트/모델 점수 조회 API"""
    role = request.args.get('role')

    try:
        scorecard = get_scorecard()

        if role:
            return jsonify({
                'role': role,
                'summary': scorecard.get_role_summary(role)
            })
        else:
            return jsonify({
                'leaderboard': scorecard.get_leaderboard(),
                'all_scores': scorecard.get_scores()
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@score_bp.route('/scores/best/<role>', methods=['GET'])
def get_best_model(role: str):
    """역할별 최고 점수 모델 조회"""
    try:
        scorecard = get_scorecard()
        best_model = scorecard.get_best_model(role)

        return jsonify({
            'role': role,
            'best_model': best_model,
            'summary': scorecard.get_role_summary(role)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@score_bp.route('/scores/dashboard', methods=['GET'])
def get_dashboard():
    """스코어카드 대시보드 데이터"""
    try:
        scorecard = get_scorecard()

        roles = ['excavator', 'coder', 'strategist', 'qa', 'analyst', 'researcher', 'pm']
        role_summaries = {}
        for role in roles:
            role_summaries[role] = scorecard.get_role_summary(role)

        all_scores = scorecard.get_scores()
        total_tasks = sum(s.get('total_tasks', 0) for s in all_scores.values()) if all_scores else 0

        return jsonify({
            'leaderboard': scorecard.get_leaderboard()[:10],
            'role_summaries': role_summaries,
            'total_logs': len(scorecard.logs),
            'total_tasks': total_tasks,
            'unique_models': len(all_scores)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
