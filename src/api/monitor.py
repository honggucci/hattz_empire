"""
Hattz Empire - Agent Monitor API v2.2.1
Docker 컨테이너 + Jobs 파이프라인 통합 모니터링

Endpoints:
- GET /api/monitor/docker         - Docker 컨테이너 상태
- GET /api/monitor/pipeline       - Jobs 파이프라인 상태
- GET /api/monitor/dashboard      - 통합 대시보드
- GET /api/monitor/stream         - SSE 실시간 스트림
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
# Docker Container Monitor
# ===========================================================================

CONTAINER_NAMES = {
    "hattz_web": {"role": "Control Tower", "llm": "-", "persona": "DB Owner"},
    "hattz_pm_worker": {"role": "PM", "mode": "worker", "llm": "GPT-5.2", "persona": "Strategist"},
    "hattz_pm_reviewer": {"role": "PM", "mode": "reviewer", "llm": "Claude CLI", "persona": "Skeptic"},
    "hattz_coder_worker": {"role": "Coder", "mode": "worker", "llm": "Claude CLI", "persona": "Implementer"},
    "hattz_coder_reviewer": {"role": "Coder", "mode": "reviewer", "llm": "Claude CLI", "persona": "Devil's Advocate"},
    "hattz_qa_worker": {"role": "QA", "mode": "worker", "llm": "Claude CLI", "persona": "Tester"},
    "hattz_qa_reviewer": {"role": "QA", "mode": "reviewer", "llm": "Claude CLI", "persona": "Breaker"},
    "hattz_reviewer_worker": {"role": "Reviewer", "mode": "worker", "llm": "Gemini 2.5", "persona": "Pragmatist"},
    "hattz_reviewer_reviewer": {"role": "Reviewer", "mode": "reviewer", "llm": "Claude CLI", "persona": "Security Hawk"},
}


def _get_docker_containers():
    """Docker 컨테이너 상태 조회"""
    containers = []

    try:
        # docker ps -a --format json (Windows에서는 shell=True, encoding='utf-8' 필요)
        result = subprocess.run(
            'docker ps -a --format "{{json .}}"',
            capture_output=True,
            text=True,
            timeout=10,
            shell=True,
            encoding='utf-8',
            errors='replace'
        )

        if result.returncode != 0:
            return {"error": f"Docker error: {result.stderr}", "containers": []}

        stdout = result.stdout or ""
        if not stdout.strip():
            return {"containers": [], "total": 0, "running": 0, "healthy": 0}

        for line in stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                container = json.loads(line)
                name = container.get("Names", "")

                # hattz_ 접두사가 있는 컨테이너만
                if not name.startswith("hattz_"):
                    continue

                info = CONTAINER_NAMES.get(name, {})
                status = container.get("Status", "")
                state = container.get("State", "")

                # 상태 파싱
                is_running = state == "running" or "Up" in status
                is_healthy = "(healthy)" in status

                containers.append({
                    "name": name,
                    "short_name": name.replace("hattz_", ""),
                    "status": "running" if is_running else "stopped",
                    "health": "healthy" if is_healthy else ("unhealthy" if is_running else "stopped"),
                    "status_text": status,
                    "image": container.get("Image", ""),
                    "ports": container.get("Ports", "") if isinstance(container.get("Ports"), str) else "",
                    "role": info.get("role", "-"),
                    "mode": info.get("mode", "-"),
                    "llm": info.get("llm", "-"),
                    "persona": info.get("persona", "-"),
                    "created": container.get("CreatedAt", ""),
                })
            except json.JSONDecodeError as e:
                continue

    except subprocess.TimeoutExpired:
        return {"error": "Docker timeout", "containers": []}
    except FileNotFoundError:
        return {"error": "Docker not installed", "containers": []}
    except Exception as e:
        return {"error": str(e), "containers": []}

    # 정렬: web 먼저, 그 다음 role/mode 순
    order = {"web": 0, "pm": 1, "coder": 2, "qa": 3, "reviewer": 4}
    containers.sort(key=lambda x: (
        order.get(x["short_name"].split("_")[0], 99),
        0 if x.get("mode") == "worker" else 1
    ))

    return {
        "containers": containers,
        "total": len(containers),
        "running": sum(1 for c in containers if c["status"] == "running"),
        "healthy": sum(1 for c in containers if c["health"] == "healthy"),
    }


@monitor_bp.route('/docker')
def get_docker_status():
    """Docker 컨테이너 상태"""
    return jsonify(_get_docker_containers())


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
    """대시보드용 전체 상태 (Docker + Pipeline + Agent)"""
    monitor = get_agent_monitor()
    agent_data = monitor.get_dashboard_data()

    # Docker 컨테이너 상태
    docker_data = _get_docker_containers()

    # Pipeline 상태
    pipeline_data = _get_pipeline_status()

    return jsonify({
        # Agent Monitor 기존 데이터
        **agent_data,
        # Docker 컨테이너
        "docker": docker_data,
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
