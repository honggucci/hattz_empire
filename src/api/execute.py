"""
Hattz Empire - Execute API
파일 읽기/쓰기/명령 실행 API
"""
from flask import request, jsonify

from . import execute_bp
import src.services.executor as executor


@execute_bp.route('', methods=['POST'])
def execute():
    """
    파일 읽기/쓰기/명령 실행 API

    Request JSON:
    {
        "action": "read" | "write" | "run" | "list",
        "target": "파일 경로 또는 명령어",
        "content": "write 액션용 내용 (선택)",
        "cwd": "run 액션용 작업 디렉토리 (선택)"
    }
    """
    data = request.json
    action = data.get('action')
    target = data.get('target')
    content = data.get('content', '')
    cwd = data.get('cwd')

    if not action or not target:
        return jsonify({
            'success': False,
            'error': 'action and target are required'
        }), 400

    result = executor.execute_api(action, target, content, cwd)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code


@execute_bp.route('/batch', methods=['POST'])
def execute_batch():
    """
    여러 명령 일괄 실행 API

    Request JSON:
    {
        "commands": [
            {"action": "read", "target": "path"},
            {"action": "run", "target": "git status"}
        ]
    }
    """
    data = request.json
    commands = data.get('commands', [])

    results = []
    for cmd in commands:
        result = executor.execute_api(
            cmd.get('action'),
            cmd.get('target'),
            cmd.get('content', ''),
            cmd.get('cwd')
        )
        results.append(result)

    return jsonify({
        'results': results,
        'success_count': sum(1 for r in results if r['success']),
        'total_count': len(results)
    })
