"""
Hattz Empire v2.2 - Jobs API
Worker들이 HTTP로 작업을 가져가고 결과를 제출하는 API

Endpoints:
- GET  /api/jobs/pull   - 대기 중인 작업 가져오기
- POST /api/jobs/push   - 작업 결과 제출
- POST /api/jobs/create - 새 작업 생성 (PM 또는 테스트용)
- GET  /api/jobs/status - 작업 상태 조회

v2.2.1: JSONL 영속화 추가 - 모든 에이전트 대화가 parent_id로 연결되어 저장됨
"""

import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from flask import Blueprint, request, jsonify
from typing import Optional, Dict, Any

# JSONL 저장 경로
CONVERSATIONS_DIR = Path(__file__).parent.parent / "infra" / "conversations" / "stream"

jobs_bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")

# ===========================================================================
# In-Memory Job Queue (Production에서는 Redis나 PostgreSQL 권장)
# ===========================================================================

# 작업 저장소: {job_id: job_data}
_jobs: Dict[str, Dict[str, Any]] = {}

# 작업 결과: {job_id: result_data}
_results: Dict[str, Dict[str, Any]] = {}

# 파이프라인 순서
PIPELINE = ["pm", "coder", "qa", "reviewer"]

# 최대 재작업 횟수
MAX_REWORK_ROUNDS = 2

# 메시지 ID → job_id 매핑 (parent_id 연결용)
_job_to_msg: Dict[str, str] = {}


# ===========================================================================
# JSONL 저장 함수
# ===========================================================================

def _save_to_jsonl(
    msg_id: str,
    from_agent: str,
    to_agent: str,
    msg_type: str,
    content: str,
    parent_id: Optional[str] = None,
    metadata: Optional[Dict] = None
):
    """대화 내용을 JSONL 파일에 저장 (parent_id로 연결)"""
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    file_path = CONVERSATIONS_DIR / f"{today}.jsonl"

    record = {
        "id": msg_id,
        "t": datetime.now().isoformat(),
        "from_agent": from_agent,
        "to_agent": to_agent,
        "type": msg_type,
        "content": content[:10000],  # 최대 10KB
        "metadata": metadata or {}
    }

    if parent_id:
        record["parent_id"] = parent_id

    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[Jobs] Saved to JSONL: {msg_id[:8]} ({from_agent}→{to_agent})")
    return msg_id


# ===========================================================================
# API Endpoints
# ===========================================================================

@jobs_bp.route("/pull", methods=["GET"])
def pull_job():
    """
    워커가 대기 중인 작업 가져가기

    Query params:
    - role: pm | coder | qa | reviewer
    - mode: worker | reviewer
    """
    role = request.args.get("role")
    mode = request.args.get("mode")

    if not role or not mode:
        return jsonify({"error": "role and mode required"}), 400

    # 해당 role/mode의 pending 작업 찾기
    for job_id, job in _jobs.items():
        if (job["role"] == role and
            job["mode"] == mode and
            job["status"] == "pending"):

            # 작업 상태 변경: pending -> processing
            job["status"] = "processing"
            job["started_at"] = datetime.now().isoformat()

            return jsonify({"job": job})

    # 작업 없음
    return jsonify({"job": None})


@jobs_bp.route("/push", methods=["POST"])
def push_result():
    """
    워커가 작업 결과 제출

    Body:
    - job_id: str
    - task_id: str
    - session_id: str
    - role: str
    - mode: str
    - success: bool
    - output: str
    - error: str (optional)
    - verdict: str (optional) - APPROVE | REVISE | HOLD | SHIP
    - rework_count: int
    - worker_id: str
    """
    data = request.json

    job_id = data.get("job_id")
    if not job_id or job_id not in _jobs:
        return jsonify({"error": "Invalid job_id"}), 400

    job = _jobs[job_id]

    # 작업 완료 처리
    job["status"] = "completed" if data.get("success") else "failed"
    job["completed_at"] = datetime.now().isoformat()
    job["worker_id"] = data.get("worker_id")

    # 결과 저장
    _results[job_id] = {
        "success": data.get("success"),
        "output": data.get("output", ""),
        "error": data.get("error"),
        "verdict": data.get("verdict")
    }

    # JSONL 저장 (에이전트 응답)
    output_content = data.get("output", "")
    if data.get("verdict"):
        output_content = f"[VERDICT: {data.get('verdict')}]\n\n{output_content}"

    # parent_id 찾기: 이 job을 생성할 때 저장한 메시지 ID
    parent_msg_id = _job_to_msg.get(job_id)

    # 응답 메시지 저장
    response_msg_id = f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    _save_to_jsonl(
        msg_id=response_msg_id,
        from_agent=f"{job['role']}-{job['mode']}",
        to_agent="pipeline",
        msg_type="response" if job["mode"] == "worker" else "review",
        content=output_content,
        parent_id=parent_msg_id,
        metadata={
            "job_id": job_id,
            "task_id": job["task_id"],
            "verdict": data.get("verdict"),
            "success": data.get("success"),
            "rework_count": job.get("rework_count", 0)
        }
    )

    # 이 응답의 msg_id를 다음 job의 parent로 사용하기 위해 저장
    _job_to_msg[f"response_{job_id}"] = response_msg_id

    # 다음 단계 트리거
    if data.get("success"):
        _trigger_next_stage(
            job=job,
            verdict=data.get("verdict"),
            output=data.get("output", ""),
            rework_count=data.get("rework_count", 0)
        )

    return jsonify({"status": "ok"})


@jobs_bp.route("/create", methods=["POST"])
def create_job():
    """
    새 작업 생성 (파이프라인 시작점)

    Body:
    - task_id: str (optional - 자동 생성)
    - session_id: str
    - role: str (기본: pm)
    - mode: str (기본: worker)
    - prompt: str
    - context: str (optional)
    """
    data = request.json

    task_id = data.get("task_id") or str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    job = {
        "id": job_id,
        "task_id": task_id,
        "session_id": data.get("session_id", "default"),
        "role": data.get("role", "pm"),
        "mode": data.get("mode", "worker"),
        "prompt": data.get("prompt", ""),
        "context": data.get("context", ""),
        "status": "pending",
        "rework_count": 0,
        "created_at": datetime.now().isoformat()
    }

    _jobs[job_id] = job

    # JSONL 저장 (작업 생성 = 요청 메시지)
    msg_id = f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    _save_to_jsonl(
        msg_id=msg_id,
        from_agent="ceo" if data.get("role", "pm") == "pm" else "pipeline",
        to_agent=f"{data.get('role', 'pm')}-{data.get('mode', 'worker')}",
        msg_type="request",
        content=data.get("prompt", ""),
        metadata={
            "job_id": job_id,
            "task_id": task_id,
            "context": data.get("context", "")
        }
    )

    # job_id → msg_id 매핑 저장 (응답 시 parent_id로 사용)
    _job_to_msg[job_id] = msg_id

    return jsonify({
        "status": "created",
        "job_id": job_id,
        "task_id": task_id,
        "msg_id": msg_id
    })


@jobs_bp.route("/status", methods=["GET"])
def job_status():
    """
    작업 상태 조회

    Query params:
    - job_id: str (optional)
    - task_id: str (optional)
    """
    job_id = request.args.get("job_id")
    task_id = request.args.get("task_id")

    if job_id:
        job = _jobs.get(job_id)
        result = _results.get(job_id)
        return jsonify({
            "job": job,
            "result": result
        })

    if task_id:
        # 해당 task의 모든 작업
        task_jobs = [
            {"job": j, "result": _results.get(j["id"])}
            for j in _jobs.values()
            if j["task_id"] == task_id
        ]
        return jsonify({"jobs": task_jobs})

    # 전체 요약
    return jsonify({
        "total": len(_jobs),
        "pending": len([j for j in _jobs.values() if j["status"] == "pending"]),
        "processing": len([j for j in _jobs.values() if j["status"] == "processing"]),
        "completed": len([j for j in _jobs.values() if j["status"] == "completed"]),
        "failed": len([j for j in _jobs.values() if j["status"] == "failed"])
    })


@jobs_bp.route("/list", methods=["GET"])
def list_jobs():
    """최근 작업 목록"""
    limit = int(request.args.get("limit", 20))

    jobs_list = list(_jobs.values())
    jobs_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return jsonify({
        "jobs": jobs_list[:limit]
    })


# ===========================================================================
# Internal: Pipeline Logic
# ===========================================================================

def _trigger_next_stage(
    job: Dict[str, Any],
    verdict: Optional[str],
    output: str,
    rework_count: int
):
    """
    다음 단계 트리거

    Worker 완료 -> Reviewer 작업 생성
    Reviewer APPROVE/SHIP -> 다음 레이어
    Reviewer REVISE/HOLD -> 재작업 (최대 MAX_REWORK_ROUNDS)
    """
    role = job["role"]
    mode = job["mode"]
    task_id = job["task_id"]
    session_id = job["session_id"]
    job_id = job["id"]
    original_prompt = job.get("context") or job["prompt"]

    if mode == "worker":
        # Worker 완료 -> 같은 레이어 Reviewer
        _create_job(
            task_id=task_id,
            session_id=session_id,
            role=role,
            mode="reviewer",
            prompt=f"Review this output:\n\n{output}",
            context=f"Original task: {original_prompt}",
            rework_count=rework_count,
            parent_job_id=job_id
        )

    elif mode == "reviewer":
        if verdict in ["APPROVE", "SHIP"]:
            # 다음 레이어로
            next_role = _get_next_role(role)

            if next_role:
                _create_job(
                    task_id=task_id,
                    session_id=session_id,
                    role=next_role,
                    mode="worker",
                    prompt=original_prompt,
                    context=f"Approved from {role}:\n{output[:2000]}",
                    rework_count=0,
                    parent_job_id=job_id
                )
            else:
                # 파이프라인 완료 - 완료 메시지 저장
                complete_msg_id = f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
                _save_to_jsonl(
                    msg_id=complete_msg_id,
                    from_agent="pipeline",
                    to_agent="ceo",
                    msg_type="complete",
                    content=f"Pipeline completed for task: {task_id}\n\nFinal output:\n{output[:5000]}",
                    parent_id=_job_to_msg.get(f"response_{job_id}"),
                    metadata={"task_id": task_id, "final_verdict": verdict}
                )
                print(f"[Jobs] Pipeline complete: {task_id}")

        elif verdict in ["REVISE", "REJECT", "HOLD"]:
            if rework_count >= MAX_REWORK_ROUNDS:
                # CEO 개입 필요
                _create_job(
                    task_id=task_id,
                    session_id=session_id,
                    role="ceo",
                    mode="intervention",
                    prompt=f"[ESCALATION] Max rework exceeded for {role}\n\nFeedback:\n{output}",
                    context=original_prompt,
                    rework_count=rework_count,
                    parent_job_id=job_id
                )
                print(f"[Jobs] Escalated to CEO: {task_id}")
            else:
                # 재작업
                _create_job(
                    task_id=task_id,
                    session_id=session_id,
                    role=role,
                    mode="worker",
                    prompt=f"{original_prompt}\n\n[REVISION FEEDBACK]\n{output}",
                    context="Rework based on feedback",
                    rework_count=rework_count + 1,
                    parent_job_id=job_id
                )


def _create_job(
    task_id: str,
    session_id: str,
    role: str,
    mode: str,
    prompt: str,
    context: str,
    rework_count: int,
    parent_job_id: Optional[str] = None
):
    """내부용 작업 생성 (파이프라인 자동 생성)"""
    job_id = str(uuid.uuid4())

    job = {
        "id": job_id,
        "task_id": task_id,
        "session_id": session_id,
        "role": role,
        "mode": mode,
        "prompt": prompt,
        "context": context,
        "status": "pending",
        "rework_count": rework_count,
        "created_at": datetime.now().isoformat()
    }

    _jobs[job_id] = job

    # JSONL 저장 (파이프라인 내부 요청)
    msg_id = f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    # parent_id: 이전 job의 응답 메시지 ID
    parent_msg_id = _job_to_msg.get(f"response_{parent_job_id}") if parent_job_id else None

    _save_to_jsonl(
        msg_id=msg_id,
        from_agent="pipeline",
        to_agent=f"{role}-{mode}",
        msg_type="request",
        content=prompt,
        parent_id=parent_msg_id,
        metadata={
            "job_id": job_id,
            "task_id": task_id,
            "rework_count": rework_count,
            "context": context[:500] if context else ""
        }
    )

    # job_id → msg_id 매핑
    _job_to_msg[job_id] = msg_id

    print(f"[Jobs] Created: {role}/{mode} ({job_id[:8]})")


def _get_next_role(current_role: str) -> Optional[str]:
    """다음 레이어 역할"""
    try:
        idx = PIPELINE.index(current_role)
        if idx < len(PIPELINE) - 1:
            return PIPELINE[idx + 1]
    except ValueError:
        pass
    return None
