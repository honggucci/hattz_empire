"""
Hattz Empire - RAG API
RAG 검색/인덱싱 API
"""
from flask import request, jsonify

from . import rag_bp
import src.services.rag as rag


@rag_bp.route('/search', methods=['POST'])
def search():
    """
    RAG 검색 API

    Request JSON:
    {
        "query": "검색 쿼리",
        "source_types": ["log", "message"],
        "top_k": 5
    }
    """
    data = request.json
    query = data.get('query', '')
    source_types = data.get('source_types')
    top_k = data.get('top_k', 5)

    if not query:
        return jsonify({'error': 'query is required'}), 400

    try:
        result = rag.search(query, source_types=source_types, top_k=top_k)
        return jsonify({
            'query': result.query,
            'total': result.total,
            'documents': [
                {
                    'id': doc.id,
                    'content': doc.content[:500],
                    'score': round(doc.score, 3),
                    'metadata': doc.metadata
                }
                for doc in result.documents
            ]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@rag_bp.route('/index', methods=['POST'])
def index():
    """
    RAG 인덱싱 트리거

    Request JSON:
    {
        "source": "logs" | "messages" | "all",
        "limit": 100
    }
    """
    data = request.json
    source = data.get('source', 'all')
    limit = data.get('limit', 100)

    try:
        result = {}

        if source in ['logs', 'all']:
            result['logs_indexed'] = rag.index_logs_from_db(limit=limit)

        if source in ['messages', 'all']:
            result['messages_indexed'] = rag.index_messages_from_db(limit=limit)

        result['stats'] = rag.get_stats()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@rag_bp.route('/stats')
def stats():
    """RAG 인덱스 통계"""
    try:
        return jsonify(rag.get_stats())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@rag_bp.route('/context', methods=['POST'])
def context():
    """
    RAG 컨텍스트 빌드

    Request JSON:
    {
        "query": "쿼리",
        "top_k": 3
    }
    """
    data = request.json
    query = data.get('query', '')
    top_k = data.get('top_k', 3)

    if not query:
        return jsonify({'error': 'query is required'}), 400

    try:
        ctx = rag.build_context(query, top_k=top_k)
        return jsonify({
            'query': query,
            'context': ctx,
            'context_length': len(ctx)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
