"""
Hattz Empire - Agent Monitor API
에이전트 작업 모니터링 API 엔드포인트
"""
import os
import psutil
from flask import jsonify, request
from src.services.agent_monitor import get_agent_monitor

from . import monitor_bp


@monitor_bp.route('/processes')
def get_processes():
    """현재 실행 중인 Python/Flask 프로세스 목록"""
    current_pid = os.getpid()
    processes = []

    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'memory_info', 'cpu_percent']):
        try:
            if proc.info['name'] and 'python' in proc.info['name'].lower():
                cmdline = proc.info['cmdline'] or []
                cmdline_str = ' '.join(cmdline) if cmdline else ''

                # Flask/app.py 관련 프로세스인지 확인
                is_flask = 'app.py' in cmdline_str or 'flask' in cmdline_str.lower()
                is_current = proc.info['pid'] == current_pid

                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'cmdline': cmdline_str[:200],  # 너무 길면 자르기
                    'is_flask': is_flask,
                    'is_current': is_current,
                    'memory_mb': round(proc.info['memory_info'].rss / 1024 / 1024, 1) if proc.info['memory_info'] else 0,
                    'cpu_percent': proc.cpu_percent(interval=0.1),
                    'create_time': proc.info['create_time']
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 현재 프로세스가 먼저 오도록 정렬
    processes.sort(key=lambda x: (not x['is_current'], not x['is_flask'], -x['create_time']))

    return jsonify({
        'current_pid': current_pid,
        'python_processes': processes,
        'total_count': len(processes),
        'flask_count': sum(1 for p in processes if p['is_flask'])
    })


@monitor_bp.route('/dashboard')
def get_dashboard():
    """대시보드용 전체 상태"""
    monitor = get_agent_monitor()
    return jsonify(monitor.get_dashboard_data())


@monitor_bp.route('/active')
def get_active_tasks():
    """현재 활성 작업 목록"""
    agent = request.args.get('agent')
    monitor = get_agent_monitor()
    tasks = monitor.get_active_tasks(agent=agent)
    return jsonify({
        "active_count": len(tasks),
        "tasks": tasks
    })


@monitor_bp.route('/agents')
def get_agents_status():
    """전체 에이전트 상태"""
    monitor = get_agent_monitor()
    return jsonify(monitor.get_all_agents_status())


@monitor_bp.route('/session/<session_id>')
def get_session_tasks(session_id: str):
    """세션별 작업 목록"""
    limit = request.args.get('limit', 20, type=int)
    monitor = get_agent_monitor()
    tasks = monitor.get_session_tasks(session_id, limit=limit)
    return jsonify({
        "session_id": session_id,
        "task_count": len(tasks),
        "tasks": tasks
    })


@monitor_bp.route('/task/<task_id>')
def get_task(task_id: str):
    """특정 작업 상세 조회"""
    monitor = get_agent_monitor()
    task = monitor.get_task(task_id)
    if task:
        return jsonify(task)
    return jsonify({"error": "Task not found"}), 404


@monitor_bp.route('/stream')
def stream_status():
    """SSE 실시간 상태 스트림"""
    from flask import Response
    import json
    import time

    def generate():
        monitor = get_agent_monitor()
        last_data = None

        while True:
            data = monitor.get_dashboard_data()
            data_json = json.dumps(data, ensure_ascii=False)

            # 변경사항 있을 때만 전송
            if data_json != last_data:
                yield f"data: {data_json}\n\n"
                last_data = data_json

            time.sleep(1)  # 1초마다 체크

    return Response(generate(), mimetype='text/event-stream')
