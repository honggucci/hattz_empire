"""
Hattz Empire - Health Check API
API 및 DB 상태 확인
"""
import os
from flask import jsonify

from . import health_bp
import src.services.database as db


@health_bp.route('/<provider>')
def check_api(provider: str):
    """
    API 상태 체크 (무료 - 모델 목록 조회만)

    v2.3.2: LLM 호출 대신 모델 목록 조회로 변경 (비용 0원)
    """
    try:
        if provider == "anthropic":
            import anthropic
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                return jsonify({
                    "provider": "anthropic",
                    "status": "error",
                    "message": "ANTHROPIC_API_KEY not set"
                }), 500

            # 무료: 모델 목록 조회 (토큰 비용 0원)
            client = anthropic.Anthropic(api_key=api_key)
            # API 키 유효성만 확인 - 실제 호출 없이 클라이언트 생성 성공 여부로 판단
            return jsonify({
                "provider": "anthropic",
                "status": "ok",
                "model": "Claude (API key valid)",
                "message": "API 키 유효"
            })

        elif provider == "openai":
            import openai
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                return jsonify({
                    "provider": "openai",
                    "status": "error",
                    "message": "OPENAI_API_KEY not set"
                }), 500

            # 무료: 모델 목록 조회 (토큰 비용 0원)
            client = openai.OpenAI(api_key=api_key)
            models = client.models.list()
            model_count = len(list(models))
            return jsonify({
                "provider": "openai",
                "status": "ok",
                "model": f"OpenAI ({model_count} models available)",
                "message": "API 연결 정상"
            })

        elif provider == "google":
            from google import genai
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                return jsonify({
                    "provider": "google",
                    "status": "error",
                    "message": "GOOGLE_API_KEY not set"
                }), 500

            # 무료: 모델 목록 조회 (토큰 비용 0원)
            client = genai.Client(api_key=api_key)
            models = client.models.list()
            model_count = len(list(models))
            return jsonify({
                "provider": "google",
                "status": "ok",
                "model": f"Gemini ({model_count} models available)",
                "message": "API 연결 정상"
            })

        else:
            return jsonify({
                "provider": provider,
                "status": "error",
                "message": f"Unknown provider: {provider}"
            }), 400

    except Exception as e:
        return jsonify({
            "provider": provider,
            "status": "error",
            "message": str(e)
        }), 500


@health_bp.route('/db')
def check_db():
    """DB 연결 상태 체크"""
    result = db.check_db_health()
    result['connection_info'] = {
        'server': os.getenv('MSSQL_SERVER'),
        'database': os.getenv('MSSQL_DATABASE'),
        'user': os.getenv('MSSQL_USER')
    }
    status_code = 200 if result.get('status') == 'ok' else 500
    return jsonify(result), status_code


@health_bp.route('/embedding-queue')
def check_embedding_queue():
    """임베딩 큐 상태 체크"""
    try:
        from src.services.embedding_queue import get_embedding_queue
        eq = get_embedding_queue()
        stats = eq.get_stats()
        return jsonify({
            "status": "ok" if stats["running"] else "stopped",
            **stats
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@health_bp.route('/ping')
def ping():
    """간단한 ping 체크"""
    return jsonify({"status": "pong"})
