"""
Hattz Empire - Session Rules API
세션 규정 관리 API 엔드포인트
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

rules_bp = Blueprint('rules', __name__, url_prefix='/api/rules')


@rules_bp.route('/presets', methods=['GET'])
@login_required
def list_presets():
    """사전 정의된 규정 목록"""
    from src.core.session_rules import PRESET_RULES

    presets = []
    for name, rules in PRESET_RULES.items():
        presets.append({
            "name": name,
            "mode": rules.mode,
            "risk_profile": rules.risk_profile,
            "hash": rules.get_hash(),
            "summary": {
                "market_order": rules.trading.market_order,
                "max_order_usd": rules.trading.max_order_usd,
                "allow_skip_tests": rules.quality.allow_skip_tests,
            }
        })
    return jsonify(presets)


@rules_bp.route('/presets/<preset_name>', methods=['GET'])
@login_required
def get_preset(preset_name: str):
    """특정 사전 정의 규정 상세"""
    from src.core.session_rules import get_preset_rules

    rules = get_preset_rules(preset_name)
    if not rules:
        return jsonify({"error": f"Preset '{preset_name}' not found"}), 404

    return jsonify({
        "name": preset_name,
        "hash": rules.get_hash(),
        "rules": rules.to_json(),
    })


@rules_bp.route('/current/<session_id>', methods=['GET'])
@login_required
def get_current_rules(session_id: str):
    """현재 세션의 활성 규정"""
    from src.core.session_rules import get_current_rules

    rules = get_current_rules(session_id)
    return jsonify({
        "session_id": session_id,
        "hash": rules.get_hash(),
        "mode": rules.mode,
        "risk_profile": rules.risk_profile,
        "rules_json": rules.to_json(),
    })


@rules_bp.route('/validate', methods=['POST'])
@login_required
def validate_rules():
    """규정 JSON 유효성 검사"""
    from src.core.session_rules import SessionRules

    data = request.json
    rules_json = data.get("rules_json", "{}")

    try:
        rules = SessionRules.from_json(rules_json)
        return jsonify({
            "valid": True,
            "hash": rules.get_hash(),
            "parsed": {
                "mode": rules.mode,
                "risk_profile": rules.risk_profile,
                "trading": {
                    "market_order": rules.trading.market_order,
                    "max_order_usd": rules.trading.max_order_usd,
                },
                "quality": {
                    "allow_skip_tests": rules.quality.allow_skip_tests,
                    "max_files_changed": rules.quality.max_files_changed,
                },
            }
        })
    except Exception as e:
        return jsonify({
            "valid": False,
            "error": str(e),
        }), 400


@rules_bp.route('/constitution', methods=['GET'])
@login_required
def get_constitution():
    """헌법 (절대 금지 사항) 조회"""
    from src.core.session_rules import CONSTITUTION

    return jsonify({
        "constitution": CONSTITUTION,
        "note": "Constitution cannot be overridden by any session rules",
    })


@rules_bp.route('/audit', methods=['GET'])
@login_required
def get_audit_logs():
    """감사 로그 조회"""
    from src.services.database import get_db_connection

    session_id = request.args.get("session_id")
    limit = int(request.args.get("limit", 50))

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            if session_id:
                cursor.execute("""
                    SELECT TOP (?) *
                    FROM session_rules_audit
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                """, (limit, session_id))
            else:
                cursor.execute("""
                    SELECT TOP (?) *
                    FROM session_rules_audit
                    ORDER BY created_at DESC
                """, (limit,))

            logs = []
            for row in cursor.fetchall():
                logs.append({
                    "id": row.id,
                    "session_id": row.session_id,
                    "task_id": row.task_id,
                    "rules_hash": row.rules_hash,
                    "rules_mode": row.rules_mode,
                    "verdict": row.verdict,
                    "violation_count": row.violation_count,
                    "critical_count": row.critical_count,
                    "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
                })

            return jsonify({
                "logs": logs,
                "count": len(logs),
            })
    except Exception as e:
        return jsonify({
            "logs": [],
            "error": str(e),
        })


@rules_bp.route('/audit/stats', methods=['GET'])
@login_required
def get_audit_stats():
    """감사 통계"""
    from src.services.database import get_db_connection

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 전체 통계
            cursor.execute("""
                SELECT
                    COUNT(*) as total_reviews,
                    SUM(CASE WHEN verdict = 'PASS' THEN 1 ELSE 0 END) as pass_count,
                    SUM(CASE WHEN verdict = 'REJECT' THEN 1 ELSE 0 END) as reject_count,
                    SUM(critical_count) as total_criticals,
                    SUM(violation_count) as total_violations
                FROM session_rules_audit
            """)
            row = cursor.fetchone()

            if row:
                return jsonify({
                    "total_reviews": row.total_reviews or 0,
                    "pass_count": row.pass_count or 0,
                    "reject_count": row.reject_count or 0,
                    "pass_rate": round((row.pass_count or 0) / max(row.total_reviews or 1, 1) * 100, 1),
                    "total_criticals": row.total_criticals or 0,
                    "total_violations": row.total_violations or 0,
                })
            else:
                return jsonify({
                    "total_reviews": 0,
                    "pass_count": 0,
                    "reject_count": 0,
                    "pass_rate": 0,
                    "total_criticals": 0,
                    "total_violations": 0,
                })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "total_reviews": 0,
        })
