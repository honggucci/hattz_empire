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
    """API 상태 체크"""
    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            response = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}]
            )
            return jsonify({
                "provider": "anthropic",
                "status": "ok",
                "model": "Claude Opus 4.5",
                "message": "API 연결 정상"
            })

        elif provider == "openai":
            import openai
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = client.chat.completions.create(
                model="gpt-5-mini",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}]
            )
            return jsonify({
                "provider": "openai",
                "status": "ok",
                "model": "GPT-5.2 Thinking",
                "message": "API 연결 정상"
            })

        elif provider == "google":
            from google import genai
            client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents="ping"
            )
            return jsonify({
                "provider": "google",
                "status": "ok",
                "model": "Gemini 3 Pro",
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
