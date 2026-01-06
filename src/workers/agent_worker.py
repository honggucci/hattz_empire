"""
Hattz Empire v2.2 - Agent Worker
Worker-Reviewer Pair Architecture with HTTP Job Queue

핵심 변경:
- SQLite 직접 접근 X → Web API로 /jobs/pull, /jobs/push
- SQLite 락지옥 방지

Usage:
    python -m src.workers.agent_worker --role coder --mode worker
    python -m src.workers.agent_worker --test
"""

import os
import sys
import time
import json
import argparse
import subprocess
import requests
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
from pathlib import Path

# ===========================================================================
# Configuration from Environment
# ===========================================================================

ROLE = os.getenv("ROLE", "unknown")
MODE = os.getenv("MODE", "worker")  # worker | reviewer
LLM = os.getenv("LLM", "claude-cli")
PERSONA = os.getenv("PERSONA", "default")
SUBAGENT = os.getenv("SUBAGENT", "")  # .claude/agents/{SUBAGENT}.md
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "http://localhost:5000")

# Polling 설정
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "2"))
MAX_REWORK_ROUNDS = int(os.getenv("MAX_REWORK_ROUNDS", "2"))

# ===========================================================================
# Data Classes
# ===========================================================================

@dataclass
class Job:
    """작업 단위"""
    id: str
    task_id: str
    session_id: str
    role: str
    mode: str
    prompt: str
    context: str
    rework_count: int = 0


@dataclass
class WorkerResult:
    """워커 실행 결과"""
    success: bool
    output: str
    error: Optional[str] = None
    verdict: Optional[str] = None  # APPROVE | REVISE | HOLD | SHIP


# ===========================================================================
# HTTP Job Queue Client
# ===========================================================================

def pull_job() -> Optional[Job]:
    """Web 서버에서 작업 가져오기"""
    try:
        response = requests.get(
            f"{WEB_BASE_URL}/api/jobs/pull",
            params={"role": ROLE, "mode": MODE},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            if data.get("job"):
                j = data["job"]
                return Job(
                    id=j["id"],
                    task_id=j["task_id"],
                    session_id=j["session_id"],
                    role=j["role"],
                    mode=j["mode"],
                    prompt=j["prompt"],
                    context=j.get("context", ""),
                    rework_count=j.get("rework_count", 0)
                )
        return None

    except requests.RequestException as e:
        print(f"[Worker] Pull error: {e}")
        return None


def push_result(job: Job, result: WorkerResult):
    """Web 서버에 결과 제출"""
    try:
        response = requests.post(
            f"{WEB_BASE_URL}/api/jobs/push",
            json={
                "job_id": job.id,
                "task_id": job.task_id,
                "session_id": job.session_id,
                "role": job.role,
                "mode": job.mode,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "verdict": result.verdict,
                "rework_count": job.rework_count,
                "worker_id": f"{ROLE}-{MODE}"
            },
            timeout=30
        )

        if response.status_code != 200:
            print(f"[Worker] Push failed: {response.status_code}")

    except requests.RequestException as e:
        print(f"[Worker] Push error: {e}")


# ===========================================================================
# Persona Prompts (API Worker용)
# ===========================================================================

PERSONA_PROMPTS = {
    "strategist": """You are the STRATEGIST (PM Worker).
Role: Task decomposition, agent orchestration, priority management.
Output: JSON TaskSpec with clear breakdown.""",

    "pragmatist": """You are the PRAGMATIST (Reviewer Worker).
Role: Balance quality vs shipping. Is it good enough?
Output: Risk assessment list only.""",
}


# ===========================================================================
# LLM Callers
# ===========================================================================

def call_claude_cli(prompt: str, context: str = "") -> WorkerResult:
    """Claude CLI with Subagent 호출"""
    import tempfile

    task_spec = f"[TASK]\n{prompt}\n[/TASK]"
    if context:
        task_spec = f"[CONTEXT]\n{context}\n[/CONTEXT]\n\n{task_spec}"

    prompt_file = Path(tempfile.gettempdir()) / f"claude_{ROLE}_{MODE}_{int(time.time())}.txt"
    prompt_file.write_text(task_spec, encoding="utf-8")

    # Subagent 사용 여부
    if SUBAGENT:
        cmd = f'claude agent {SUBAGENT} --print'
    else:
        cmd = f'claude --print'

    cmd += ' --dangerously-skip-permissions'
    cmd += f' < "{prompt_file}"'

    print(f"[Worker] Calling Claude CLI: {ROLE}/{MODE}")
    if SUBAGENT:
        print(f"[Worker] Subagent: {SUBAGENT}")

    try:
        # ANTHROPIC_API_KEY 제거 (구독 사용)
        env = {**os.environ}
        if "ANTHROPIC_API_KEY" in env and not env["ANTHROPIC_API_KEY"]:
            del env["ANTHROPIC_API_KEY"]
        env["CLAUDE_CODE_NONINTERACTIVE"] = "1"

        result = subprocess.run(
            cmd,
            shell=True,
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=300,
            env=env
        )

        output = result.stdout
        verdict = extract_verdict(output)

        return WorkerResult(
            success=result.returncode == 0,
            output=output,
            error=result.stderr if result.returncode != 0 else None,
            verdict=verdict
        )

    except subprocess.TimeoutExpired:
        return WorkerResult(success=False, output="", error="Timeout (300s)")
    except Exception as e:
        return WorkerResult(success=False, output="", error=str(e))


def extract_verdict(output: str) -> Optional[str]:
    """출력에서 Verdict 추출"""
    output_upper = output.upper()

    if "VERDICT:" in output_upper:
        if "APPROVE" in output_upper:
            return "APPROVE"
        elif "REJECT" in output_upper or "REVISE" in output_upper:
            return "REVISE"
        elif "HOLD" in output_upper:
            return "HOLD"
        elif "SHIP" in output_upper:
            return "SHIP"

    for line in output.split("\n"):
        line = line.strip().upper()
        if line in ["APPROVE", "REJECT", "REVISE", "HOLD", "SHIP"]:
            return "APPROVE" if line == "APPROVE" else (
                "REVISE" if line in ["REJECT", "REVISE"] else line
            )

    return None


def call_openai_api(prompt: str, context: str = "") -> WorkerResult:
    """OpenAI API 호출"""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        persona_prompt = PERSONA_PROMPTS.get(PERSONA, "")
        system_message = f"{persona_prompt}\n\nContext: {context}" if context else persona_prompt

        response = client.chat.completions.create(
            model="gpt-4o",  # 또는 gpt-5.2-preview-thinking
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=4096
        )

        return WorkerResult(
            success=True,
            output=response.choices[0].message.content
        )

    except Exception as e:
        return WorkerResult(success=False, output="", error=f"OpenAI error: {e}")


def call_gemini_api(prompt: str, context: str = "") -> WorkerResult:
    """Gemini API 호출"""
    try:
        import google.generativeai as genai

        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        model = genai.GenerativeModel("gemini-2.0-flash")

        persona_prompt = PERSONA_PROMPTS.get(PERSONA, "")
        full_prompt = f"{persona_prompt}\n\nContext: {context}\n\nTask: {prompt}"

        response = model.generate_content(full_prompt)

        return WorkerResult(success=True, output=response.text)

    except Exception as e:
        return WorkerResult(success=False, output="", error=f"Gemini error: {e}")


# ===========================================================================
# Main Worker Loop
# ===========================================================================

def process_job(job: Job) -> WorkerResult:
    """작업 처리"""
    print(f"[Worker] Processing: {job.id[:8]} ({job.role}/{job.mode})")

    if LLM == "claude-cli":
        return call_claude_cli(job.prompt, job.context)
    elif "gpt" in LLM.lower():
        return call_openai_api(job.prompt, job.context)
    elif "gemini" in LLM.lower():
        return call_gemini_api(job.prompt, job.context)
    else:
        return WorkerResult(success=False, output="", error=f"Unknown LLM: {LLM}")


def worker_loop():
    """메인 워커 루프"""
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  HATTZ EMPIRE v2.2 - Agent Worker (HTTP Mode)                ║
╠══════════════════════════════════════════════════════════════╣
║  Role: {ROLE:<12} Mode: {MODE:<12}                         ║
║  LLM: {LLM:<14} Persona: {PERSONA:<14}                     ║
║  Subagent: {SUBAGENT or 'None':<47}  ║
║  Web: {WEB_BASE_URL:<50}  ║
╚══════════════════════════════════════════════════════════════╝
""")

    print(f"[Worker] Starting poll loop (interval: {POLL_INTERVAL}s)")

    while True:
        try:
            job = pull_job()

            if job:
                result = process_job(job)
                push_result(job, result)
                print(f"[Worker] Done: {job.id[:8]} (verdict: {result.verdict})")

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n[Worker] Shutting down...")
            break
        except Exception as e:
            print(f"[Worker] Error: {e}")
            time.sleep(POLL_INTERVAL * 2)


# ===========================================================================
# CLI Entry Point
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="Hattz Empire Agent Worker")
    parser.add_argument("--role", type=str, help="Worker role")
    parser.add_argument("--mode", type=str, help="Worker mode")
    parser.add_argument("--test", action="store_true", help="Test mode")
    args = parser.parse_args()

    global ROLE, MODE
    if args.role:
        ROLE = args.role
    if args.mode:
        MODE = args.mode

    if args.test:
        print(f"[Test] Role={ROLE}, Mode={MODE}, LLM={LLM}")
        print(f"[Test] Subagent={SUBAGENT}")
        print(f"[Test] Web={WEB_BASE_URL}")
        result = call_claude_cli("Say hello and identify yourself.", "")
        print(f"[Test] Success: {result.success}")
        print(f"[Test] Output: {result.output[:500] if result.output else 'empty'}")
        if result.error:
            print(f"[Test] Error: {result.error}")
    else:
        worker_loop()


if __name__ == "__main__":
    main()
