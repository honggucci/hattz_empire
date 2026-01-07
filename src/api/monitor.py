"""
Hattz Empire - Agent Monitor API v2.4.1
CLI Queue + 프로세스 모니터링 (Docker 제거)

Endpoints:
- GET /api/monitor/cli            - CLI Queue + 프로세스 상태
- GET /api/monitor/pipeline       - Jobs 파이프라인 상태
- GET /api/monitor/dashboard      - 통합 대시보드
- GET /api/monitor/stream         - SSE 실시간 스트림
- POST /api/monitor/kill-zombie   - 좀비 프로세스 강제 종료
"""
import os
import json
import subprocess
import psutil
from datetime import datetime
from flask import jsonify, request, Response
from src.services.agent_monitor import get_agent_monitor

from . import monitor_bp

# ===========================================================================
# CLI Queue & Process Monitor (v2.4.1)
# ===========================================================================

def _get_cli_status():
    """CLI Queue + 활성 프로세스 상태 조회"""
    from src.services.cli_supervisor import (
        get_queue_status,
        get_active_processes,
        CLI_CONFIG
    )

    queue_status = get_queue_status()
    process_status = get_active_processes()

    return {
        "queue": queue_status,
        "processes": process_status,
        "config": {
            "max_concurrent": CLI_CONFIG["max_concurrent"],
            "queue_max_size": CLI_CONFIG["queue_max_size"],
            "rate_limit_calls": CLI_CONFIG["rate_limit_calls"],
            "rate_limit_period": CLI_CONFIG["rate_limit_period"],
            "timeout_seconds": CLI_CONFIG["timeout_seconds"],
        },
        "health": {
            "queue_healthy": queue_status["queue_size"] < CLI_CONFIG["queue_max_size"],
            "rate_limit_ok": queue_status["rate_limiter"]["available"] > 0,
            "no_zombies": process_status["active_count"] <= CLI_CONFIG["max_concurrent"],
        }
    }


@monitor_bp.route('/cli')
def get_cli_health():
    """CLI Queue + 프로세스 상태"""
    return jsonify(_get_cli_status())


@monitor_bp.route('/kill-zombie', methods=['POST'])
def kill_zombie():
    """좀비 프로세스 강제 종료"""
    from src.services.cli_supervisor import kill_zombie_processes

    timeout = request.json.get('timeout_seconds', 600) if request.json else 600
    killed = kill_zombie_processes(timeout_seconds=timeout)

    return jsonify({
        "killed_count": len(killed),
        "killed_tasks": killed,
        "message": f"{len(killed)}개 좀비 프로세스 종료됨" if killed else "좀비 프로세스 없음"
    })


# ===========================================================================
# Jobs Pipeline Monitor
# ===========================================================================

def _get_pipeline_status():
    """Jobs 파이프라인 상태 조회"""
    from src.api.jobs import _jobs, _results, PIPELINE, MAX_REWORK_ROUNDS

    # 상태별 분류
    pending = []
    in_progress = []
    completed = []
    failed = []

    for job_id, job in _jobs.items():
        result = _results.get(job_id)
        job_info = {
            "id": job_id[:8],
            "full_id": job_id,
            "role": job.get("role"),
            "mode": job.get("mode"),
            "task_id": job.get("task_id", "")[:8],
            "rework_count": job.get("rework_count", 0),
            "created_at": job.get("created_at"),
            "prompt": job.get("prompt", "")[:100],
        }

        if result:
            job_info["verdict"] = result.get("verdict")
            job_info["success"] = result.get("success")
            if result.get("success"):
                completed.append(job_info)
            else:
                job_info["error"] = result.get("error")
                failed.append(job_info)
        elif job.get("status") == "in_progress":
            in_progress.append(job_info)
        else:
            pending.append(job_info)

    # 최신순 정렬
    for lst in [pending, in_progress, completed, failed]:
        lst.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return {
        "pending": pending[:20],
        "in_progress": in_progress[:10],
        "completed": completed[:20],
        "failed": failed[:10],
        "stats": {
            "pending": len(pending),
            "in_progress": len(in_progress),
            "completed": len(completed),
            "failed": len(failed),
            "total": len(_jobs),
        },
        "config": {
            "pipeline": PIPELINE,
            "max_rework": MAX_REWORK_ROUNDS,
        }
    }


@monitor_bp.route('/pipeline')
def get_pipeline_status():
    """Jobs 파이프라인 상태"""
    return jsonify(_get_pipeline_status())


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
    """대시보드용 전체 상태 (CLI + Pipeline + Agent)"""
    monitor = get_agent_monitor()
    agent_data = monitor.get_dashboard_data()

    # CLI Queue + 프로세스 상태
    cli_data = _get_cli_status()

    # Pipeline 상태
    pipeline_data = _get_pipeline_status()

    return jsonify({
        # Agent Monitor 기존 데이터
        **agent_data,
        # CLI Queue + 프로세스
        "cli": cli_data,
        # Jobs 파이프라인
        "pipeline": pipeline_data,
        # 타임스탬프
        "timestamp": datetime.now().isoformat(),
    })


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
