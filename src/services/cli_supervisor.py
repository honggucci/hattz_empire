"""
Hattz Empire - Claude Code CLI Supervisor
Claude Code CLI 호출 + 세션 관리 + 에러 복구

v2.1.1 EXEC tier:
- 타임아웃 감지 (기본 5분)
- 컨텍스트 초과 감지 + 자동 요약 재시도
- 에러 발생 시 자동 재시도 (최대 2회)
- 세션 죽으면 DB에서 컨텍스트 복구
- PM에게 ABORT 리포트
"""
import subprocess
import os
import re
import json
import time
import uuid
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from pathlib import Path


# =============================================================================
# Configuration
# =============================================================================

CLI_CONFIG = {
    "timeout_seconds": 300,      # 5분 타임아웃
    "max_retries": 2,            # 최대 재시도 횟수
    "context_recovery_limit": 10, # 복구 시 가져올 최근 메시지 수
    "output_max_chars": 50000,   # 출력 최대 길이
}

# Claude CLI 실행 경로 (Windows PATH 문제 우회)
# 환경에 따라 자동 감지: 1) PATH, 2) node 직접 실행, 3) npm global cmd
def _get_claude_cli_path() -> str:
    """Claude CLI 실행 경로 반환"""
    import shutil
    import os

    # 1. PATH에서 찾기 (제대로 설정된 환경)
    claude_path = shutil.which("claude")
    if claude_path:
        return "claude"

    # npm global 경로
    npm_global = os.path.expanduser("~\\AppData\\Roaming\\npm")
    cli_js = os.path.join(npm_global, "node_modules", "@anthropic-ai", "claude-code", "cli.js")

    # 2. Node.js로 직접 실행 (PATH에 node 없는 경우 대비)
    # Windows에서 가장 신뢰할 수 있는 방식
    node_candidates = [
        shutil.which("node"),
        "C:\\Program Files\\nodejs\\node.exe",
        os.path.expanduser("~\\AppData\\Local\\Programs\\nodejs\\node.exe"),
    ]

    for node_path in node_candidates:
        if node_path and os.path.exists(node_path) and os.path.exists(cli_js):
            return f'"{node_path}" "{cli_js}"'

    # 3. npm global cmd (node가 PATH에 있는 경우만 작동)
    claude_cmd = os.path.join(npm_global, "claude.cmd")
    if os.path.exists(claude_cmd):
        return f'"{claude_cmd}"'

    # Fallback: 그냥 claude
    return "claude"

CLAUDE_CLI_PATH = _get_claude_cli_path()

# v2.4: 프로필별 모델 설정 (API 비용 0원 - CLI만 사용)
# coder/excavator = Opus (고품질 코드/분석)
# reviewer/qa = Sonnet (빠른 검증)
CLI_PROFILE_MODELS = {
    "coder": "claude-opus-4-5-20251101",      # 코드 작성 = Opus
    "excavator": "claude-opus-4-5-20251101",  # 의도 발굴 = Opus
    "qa": "claude-sonnet-4-5-20250514",       # QA 검증 = Sonnet 4.5
    "reviewer": "claude-sonnet-4-5-20250514", # 리뷰/검토 = Sonnet 4.5
    "default": "claude-sonnet-4-5-20250514",  # 기본값 = Sonnet 4.5
}

# 역할별 세션 UUID 저장소 (task_id:role -> session_uuid)
_session_registry: Dict[str, str] = {}

# 위원회 세션 UUID 저장소 (task_id:role:persona -> session_uuid)
# 각 위원회 멤버가 독립된 CLI 세션을 가짐
_committee_session_registry: Dict[str, str] = {}

# 컨텍스트 초과 에러 패턴
CONTEXT_OVERFLOW_PATTERNS = [
    r"context.*(window|length|limit|exceeded)",
    r"maximum.*(context|token)",
    r"too (many|long)",
    r"conversation.*too.*long",
]

# 치명적 에러 패턴 (재시도 불가)
FATAL_ERROR_PATTERNS = [
    r"authentication.*failed",
    r"api.*key.*invalid",
    r"rate.*limit.*exceeded",
    r"quota.*exceeded",
]


@dataclass
class CLIResult:
    """CLI 실행 결과"""
    success: bool
    output: str
    error: Optional[str] = None
    exit_code: int = 0
    retry_count: int = 0
    context_recovered: bool = False
    aborted: bool = False
    abort_reason: Optional[str] = None


# =============================================================================
# CLI Supervisor Core
# =============================================================================

class CLISupervisor:
    """
    Claude Code CLI 감독자

    기능:
    1. subprocess로 CLI 실행
    2. 타임아웃/에러 감지
    3. 컨텍스트 초과 시 요약 후 재시도
    4. 세션 복구 (DB에서 히스토리 로드)
    5. ABORT 처리
    """

    def __init__(self, working_dir: str = None):
        self.working_dir = working_dir or os.getcwd()
        self.config = CLI_CONFIG
        self.last_error = None
        self.retry_count = 0

    def call_cli(
        self,
        prompt: str,
        system_prompt: str = "",
        profile: str = "coder",
        session_id: str = None,
        task_context: str = ""
    ) -> CLIResult:
        """
        Claude Code CLI 호출

        Args:
            prompt: 사용자 프롬프트
            system_prompt: 시스템 프롬프트
            profile: 에이전트 프로필 (coder/qa/reviewer)
            session_id: 세션 ID (복구용)
            task_context: 추가 컨텍스트

        Returns:
            CLIResult
        """
        self.retry_count = 0

        # 프롬프트 구성
        full_prompt = self._build_prompt(prompt, system_prompt, profile, task_context)

        while self.retry_count <= self.config["max_retries"]:
            try:
                result = self._execute_cli(full_prompt, profile)

                # 성공
                if result.success:
                    return result

                # ABORT 감지
                if self._is_abort(result.output):
                    abort_reason = self._extract_abort_reason(result.output)
                    return CLIResult(
                        success=False,
                        output=result.output,
                        aborted=True,
                        abort_reason=abort_reason,
                        retry_count=self.retry_count
                    )

                # 컨텍스트 초과 감지
                if self._is_context_overflow(result.error or result.output):
                    print(f"[CLI-Supervisor] 컨텍스트 초과 감지, 세션 리셋 + 요약 후 재시도 ({self.retry_count + 1}/{self.config['max_retries']})")

                    # 세션 리셋 (새 UUID로 시작)
                    self.reset_session(profile)

                    # 컨텍스트 요약
                    summarized_prompt = self._summarize_context(full_prompt, session_id)
                    full_prompt = summarized_prompt
                    self.retry_count += 1
                    continue

                # 치명적 에러
                if self._is_fatal_error(result.error or ""):
                    return CLIResult(
                        success=False,
                        output="",
                        error=f"치명적 에러: {result.error}",
                        aborted=True,
                        abort_reason="FATAL_ERROR"
                    )

                # 일반 에러 - 재시도
                if self.retry_count < self.config["max_retries"]:
                    print(f"[CLI-Supervisor] 에러 발생, 재시도 ({self.retry_count + 1}/{self.config['max_retries']})")
                    self.retry_count += 1
                    time.sleep(2)  # 2초 대기 후 재시도
                    continue
                else:
                    return result

            except subprocess.TimeoutExpired:
                print(f"[CLI-Supervisor] 타임아웃 ({self.config['timeout_seconds']}초)")
                if self.retry_count < self.config["max_retries"]:
                    # 타임아웃 시 태스크 분할 시도
                    print("[CLI-Supervisor] 태스크 분할 시도...")
                    full_prompt = self._split_task(full_prompt)
                    self.retry_count += 1
                    continue
                else:
                    return CLIResult(
                        success=False,
                        output="",
                        error=f"타임아웃 ({self.config['timeout_seconds']}초)",
                        aborted=True,
                        abort_reason="TIMEOUT"
                    )

            except Exception as e:
                self.last_error = str(e)
                return CLIResult(
                    success=False,
                    output="",
                    error=str(e),
                    retry_count=self.retry_count
                )

        # 최대 재시도 초과
        return CLIResult(
            success=False,
            output="",
            error="최대 재시도 횟수 초과",
            retry_count=self.retry_count,
            aborted=True,
            abort_reason="MAX_RETRIES_EXCEEDED"
        )

    def _execute_cli(self, prompt: str, profile: str) -> CLIResult:
        """실제 CLI 실행"""
        # Claude Code CLI 명령 구성
        cmd = self._build_cli_command(prompt, profile)

        print(f"[CLI-Supervisor] 실행 중... (profile: {profile})")

        result = subprocess.run(
            cmd,
            shell=True,
            cwd=self.working_dir,
            capture_output=True,
            text=True,
            timeout=self.config["timeout_seconds"],
            env={**os.environ, "CLAUDE_CODE_NONINTERACTIVE": "1"}
        )

        output = result.stdout
        if len(output) > self.config["output_max_chars"]:
            output = output[:self.config["output_max_chars"]] + "\n... (출력 잘림)"

        return CLIResult(
            success=result.returncode == 0,
            output=output,
            error=result.stderr if result.returncode != 0 else None,
            exit_code=result.returncode,
            retry_count=self.retry_count
        )

    def _build_cli_command(self, prompt: str, profile: str) -> str:
        """CLI 명령어 생성"""
        # 프롬프트를 임시 파일로 저장
        import tempfile

        # Windows에서 안전하게 처리
        prompt_file = Path(tempfile.gettempdir()) / f"claude_prompt_{int(time.time())}.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        # Claude Code CLI 명령 (--print 모드: 비대화형)
        # 서브에이전트 사용: .claude/agents/{profile}.md 자동 로드
        # --allowedTools로 프로필별 도구 제한
        # --session-id: 역할별 세션 UUID로 대화 연속성 보장
        # --model: 프로필별 모델 지정 (v2.4)
        allowed_tools = self._get_allowed_tools(profile)
        session_uuid = self._get_or_create_session_uuid(profile)
        model = CLI_PROFILE_MODELS.get(profile, CLI_PROFILE_MODELS["default"])

        cmd = f'{CLAUDE_CLI_PATH} --print --model {model} --session-id {session_uuid} --dangerously-skip-permissions'
        if allowed_tools:
            cmd += f' --allowedTools "{",".join(allowed_tools)}"'
        cmd += f' < "{prompt_file}"'

        print(f"[CLI-Supervisor] CLI: {CLAUDE_CLI_PATH}")
        print(f"[CLI-Supervisor] Model: {model} (profile: {profile})")

        return cmd

    def _get_or_create_session_uuid(self, profile: str, task_id: str = None) -> str:
        """역할별 세션 UUID 반환 (없으면 생성)"""
        global _session_registry

        # 키: task_id가 있으면 task:role, 없으면 role만
        key = f"{task_id}:{profile}" if task_id else profile

        if key not in _session_registry:
            _session_registry[key] = str(uuid.uuid4())
            print(f"[CLI-Supervisor] 새 세션 생성: {key} -> {_session_registry[key][:8]}...")

        return _session_registry[key]

    def reset_session(self, profile: str = None, task_id: str = None):
        """세션 리셋 (컨텍스트 초과 시 호출)"""
        global _session_registry

        if profile:
            key = f"{task_id}:{profile}" if task_id else profile
            if key in _session_registry:
                del _session_registry[key]
                print(f"[CLI-Supervisor] 세션 리셋: {key}")
        else:
            _session_registry.clear()
            print("[CLI-Supervisor] 전체 세션 리셋")

    # =========================================================================
    # Committee Session Management (위원회 세션 관리)
    # =========================================================================

    def get_committee_session_uuid(
        self,
        role: str,
        persona: str,
        task_id: str = None
    ) -> str:
        """
        위원회 멤버별 세션 UUID 반환 (없으면 생성)

        각 위원회 멤버(persona)가 독립된 CLI 세션을 가짐
        예: coder:implementer, coder:devils_advocate, coder:perfectionist
        """
        global _committee_session_registry

        key = f"{task_id}:{role}:{persona}" if task_id else f"{role}:{persona}"

        if key not in _committee_session_registry:
            _committee_session_registry[key] = str(uuid.uuid4())
            print(f"[CLI-Supervisor] 위원회 세션 생성: {key} -> {_committee_session_registry[key][:8]}...")

        return _committee_session_registry[key]

    def reset_committee_session(
        self,
        role: str = None,
        persona: str = None,
        task_id: str = None
    ):
        """위원회 세션 리셋"""
        global _committee_session_registry

        if role and persona:
            key = f"{task_id}:{role}:{persona}" if task_id else f"{role}:{persona}"
            if key in _committee_session_registry:
                del _committee_session_registry[key]
                print(f"[CLI-Supervisor] 위원회 세션 리셋: {key}")
        elif role:
            # 해당 역할의 모든 위원회 세션 리셋
            prefix = f"{task_id}:{role}:" if task_id else f"{role}:"
            keys_to_delete = [k for k in _committee_session_registry if k.startswith(prefix)]
            for k in keys_to_delete:
                del _committee_session_registry[k]
            print(f"[CLI-Supervisor] 역할 {role}의 위원회 세션 리셋: {len(keys_to_delete)}개")
        else:
            _committee_session_registry.clear()
            print("[CLI-Supervisor] 전체 위원회 세션 리셋")

    def call_committee_member(
        self,
        prompt: str,
        role: str,
        persona: str,
        persona_prompt: str,
        task_id: str = None,
        context: str = ""
    ) -> CLIResult:
        """
        위원회 멤버 (개별 CLI 세션)에게 호출

        Args:
            prompt: 검토할 내용
            role: 역할 (coder/qa/reviewer)
            persona: 페르소나 (implementer/devils_advocate/perfectionist 등)
            persona_prompt: 페르소나 프롬프트
            task_id: 태스크 ID
            context: 이전 라운드 컨텍스트
        """
        session_uuid = self.get_committee_session_uuid(role, persona, task_id)

        # 페르소나 프롬프트 + 컨텍스트 + 태스크 구성
        full_prompt = f"""[PERSONA]
{persona_prompt}
[/PERSONA]

"""
        if context:
            full_prompt += f"""[PREVIOUS ROUNDS]
{context}
[/PREVIOUS ROUNDS]

"""
        full_prompt += f"""[TASK]
{prompt}
[/TASK]"""

        # CLI 명령 구성 (페르소나별 독립 세션)
        import tempfile
        prompt_file = Path(tempfile.gettempdir()) / f"claude_committee_{int(time.time())}_{persona}.txt"
        prompt_file.write_text(full_prompt, encoding="utf-8")

        # 프로필별 도구 제한 및 모델 지정 (v2.4)
        allowed_tools = self._get_allowed_tools(role)
        model = CLI_PROFILE_MODELS.get(role, CLI_PROFILE_MODELS["default"])

        cmd = f'{CLAUDE_CLI_PATH} --print --model {model} --session-id {session_uuid} --dangerously-skip-permissions'
        if allowed_tools:
            cmd += f' --allowedTools "{",".join(allowed_tools)}"'
        cmd += f' < "{prompt_file}"'

        print(f"[CLI-Supervisor] 위원회 호출: {role}:{persona} (model: {model}, session: {session_uuid[:8]}...)")

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=self.config["timeout_seconds"],
                env={**os.environ, "CLAUDE_CODE_NONINTERACTIVE": "1"}
            )

            output = result.stdout
            if len(output) > self.config["output_max_chars"]:
                output = output[:self.config["output_max_chars"]] + "\n... (출력 잘림)"

            return CLIResult(
                success=result.returncode == 0,
                output=output,
                error=result.stderr if result.returncode != 0 else None,
                exit_code=result.returncode
            )

        except subprocess.TimeoutExpired:
            return CLIResult(
                success=False,
                output="",
                error=f"위원회 타임아웃 ({self.config['timeout_seconds']}초)",
                aborted=True,
                abort_reason="COMMITTEE_TIMEOUT"
            )
        except Exception as e:
            return CLIResult(
                success=False,
                output="",
                error=str(e)
            )

    def _get_allowed_tools(self, profile: str) -> List[str]:
        """프로필별 허용 도구 반환"""
        tools_map = {
            "coder": ["Edit", "Write", "Read", "Bash", "Glob"],
            "qa": ["Bash", "Read", "Glob"],  # 쓰기 금지
            "reviewer": ["Read", "Glob", "Grep"],  # 읽기 전용
        }
        return tools_map.get(profile, ["Read", "Glob"])

    def _build_prompt(
        self,
        prompt: str,
        system_prompt: str,
        profile: str,
        task_context: str
    ) -> str:
        """프롬프트 구성"""
        parts = []

        # 시스템 프롬프트
        if system_prompt:
            parts.append(f"[SYSTEM]\n{system_prompt}\n[/SYSTEM]\n")

        # 프로필별 규칙
        profile_rules = self._get_profile_rules(profile)
        if profile_rules:
            parts.append(f"[RULES]\n{profile_rules}\n[/RULES]\n")

        # 태스크 컨텍스트
        if task_context:
            parts.append(f"[CONTEXT]\n{task_context}\n[/CONTEXT]\n")

        # 메인 프롬프트
        parts.append(f"[TASK]\n{prompt}\n[/TASK]")

        return "\n".join(parts)

    def _get_profile_rules(self, profile: str) -> str:
        """프로필별 규칙 반환"""
        rules = {
            "coder": """- 출력: unified diff 또는 코드만
- 설명/인사/추임새 금지
- 불가능하면: # ABORT: [이유]
- 주석으로만 짧은 근거""",
            "qa": """- 출력: PASS/FAIL JSON 또는 테스트 코드 diff
- 테스트 실행 결과 포함
- 불가능하면: # ABORT: [이유]""",
            "reviewer": """- 출력: JSON (APPROVE/REQUEST_CHANGES)
- 리스크/보안/품질 점검
- 불가능하면: # ABORT: [이유]"""
        }
        return rules.get(profile, rules["coder"])

    def _is_abort(self, output: str) -> bool:
        """ABORT 태그 감지"""
        return "# ABORT:" in output or "#ABORT:" in output

    def _extract_abort_reason(self, output: str) -> str:
        """ABORT 사유 추출"""
        match = re.search(r'#\s*ABORT:\s*(.+?)(?:\n|$)', output)
        if match:
            return match.group(1).strip()
        return "Unknown reason"

    def _is_context_overflow(self, text: str) -> bool:
        """컨텍스트 초과 에러 감지"""
        text_lower = text.lower()
        for pattern in CONTEXT_OVERFLOW_PATTERNS:
            if re.search(pattern, text_lower):
                return True
        return False

    def _is_fatal_error(self, text: str) -> bool:
        """치명적 에러 감지"""
        text_lower = text.lower()
        for pattern in FATAL_ERROR_PATTERNS:
            if re.search(pattern, text_lower):
                return True
        return False

    def _summarize_context(self, prompt: str, session_id: str = None) -> str:
        """컨텍스트 요약 (Gemini 사용)"""
        try:
            import google.generativeai as genai

            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                # Gemini 없으면 단순 자르기
                return prompt[:10000] + "\n...(컨텍스트 축소됨)"

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")

            summary_prompt = f"""다음 프롬프트를 핵심만 유지하면서 1/3로 요약하세요.
코드/diff가 있으면 그대로 유지하고, 설명 부분만 축소하세요.

원본:
{prompt[:30000]}

요약된 프롬프트 (핵심만):"""

            response = model.generate_content(summary_prompt)
            summarized = response.text

            print(f"[CLI-Supervisor] 컨텍스트 요약 완료: {len(prompt)} → {len(summarized)} chars")
            return summarized

        except Exception as e:
            print(f"[CLI-Supervisor] 요약 실패: {e}, 단순 자르기 적용")
            return prompt[:10000] + "\n...(컨텍스트 축소됨)"

    def _split_task(self, prompt: str) -> str:
        """태스크 분할 (타임아웃 대응)"""
        # 간단한 분할: 첫 번째 작업만 수행하도록 지시
        return f"""다음 태스크가 너무 복잡합니다. 첫 번째 단계만 수행하세요.

{prompt[:8000]}

---
**주의**: 전체 완료하지 말고, 첫 번째 핵심 단계만 diff로 출력하세요.
나머지는 "# TODO: 다음 단계" 주석으로 남기세요."""

    def recover_session(self, session_id: str) -> str:
        """
        세션 복구 (DB에서 최근 메시지 로드)

        Returns:
            복구된 컨텍스트 문자열
        """
        try:
            from src.services import database as db

            messages = db.get_messages(
                session_id,
                limit=self.config["context_recovery_limit"]
            )

            if not messages:
                return ""

            # 컨텍스트 구성
            context_parts = ["[RECOVERED CONTEXT]"]
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")[:500]  # 각 메시지 500자 제한
                context_parts.append(f"[{role.upper()}] {content}")

            context_parts.append("[/RECOVERED CONTEXT]")

            recovered = "\n".join(context_parts)
            print(f"[CLI-Supervisor] 세션 복구: {len(messages)}개 메시지")
            return recovered

        except Exception as e:
            print(f"[CLI-Supervisor] 세션 복구 실패: {e}")
            return ""


# =============================================================================
# Public API
# =============================================================================

# 싱글톤 인스턴스
_supervisor: Optional[CLISupervisor] = None


def get_supervisor() -> CLISupervisor:
    """CLISupervisor 싱글톤"""
    global _supervisor
    if _supervisor is None:
        _supervisor = CLISupervisor()
    return _supervisor


def call_claude_cli(
    messages: List[Dict[str, str]],
    system_prompt: str = "",
    profile: str = "coder",
    session_id: str = None
) -> str:
    """
    Claude Code CLI 호출 (llm_caller에서 사용)

    Args:
        messages: 메시지 리스트 [{"role": "user", "content": "..."}]
        system_prompt: 시스템 프롬프트
        profile: 프로필 (coder/qa/reviewer)
        session_id: 세션 ID

    Returns:
        응답 문자열
    """
    supervisor = get_supervisor()

    # 마지막 사용자 메시지 추출
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break

    if not user_message:
        return "# ABORT: 사용자 메시지 없음"

    # 이전 대화 컨텍스트 구성 (최근 5개, 각 1000자)
    context_parts = []
    recent_messages = messages[-6:-1] if len(messages) > 5 else messages[:-1]

    for msg in recent_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")[:1000]
        context_parts.append(f"[{role.upper()}]\n{content}\n[/{role.upper()}]")

    task_context = "\n\n".join(context_parts) if context_parts else ""

    # DB에서 추가 컨텍스트 보강 (세션 ID 있으면)
    if session_id and len(context_parts) < 3:
        try:
            recovered = supervisor.recover_session(session_id)
            if recovered:
                task_context = recovered + "\n\n" + task_context
        except Exception:
            pass

    # CLI 호출
    result = supervisor.call_cli(
        prompt=user_message,
        system_prompt=system_prompt,
        profile=profile,
        session_id=session_id,
        task_context=task_context
    )

    # 결과 처리
    if result.success:
        return result.output

    if result.aborted:
        return f"""# ABORT: {result.abort_reason}

---
**CLI Supervisor 보고**:
- 재시도 횟수: {result.retry_count}
- 컨텍스트 복구: {result.context_recovered}
- 에러: {result.error or 'N/A'}

PM에게 태스크 재정의 또는 분할을 요청하세요."""

    # 에러 응답
    return f"""# ABORT: CLI 실행 실패

**에러**: {result.error}
**Exit Code**: {result.exit_code}
**재시도 횟수**: {result.retry_count}

출력:
{result.output[:2000] if result.output else '(없음)'}"""


def recover_and_continue(session_id: str, new_prompt: str, profile: str = "coder") -> str:
    """
    세션 복구 후 계속 작업

    CLI 세션이 죽었을 때 호출
    """
    supervisor = get_supervisor()

    # 세션 복구
    recovered_context = supervisor.recover_session(session_id)

    # 복구된 컨텍스트와 함께 새 프롬프트 실행
    result = supervisor.call_cli(
        prompt=new_prompt,
        profile=profile,
        session_id=session_id,
        task_context=recovered_context
    )

    if result.success:
        return result.output
    else:
        return f"# ABORT: 세션 복구 후에도 실패\n{result.error}"


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    # 테스트
    print("=== CLI Supervisor 테스트 ===")

    supervisor = CLISupervisor()

    # 간단한 테스트 (실제 CLI 없이)
    test_prompt = "print('Hello World')"

    print(f"프롬프트 빌드 테스트:")
    built = supervisor._build_prompt(
        prompt=test_prompt,
        system_prompt="You are a coder.",
        profile="coder",
        task_context="이전 대화 내용..."
    )
    print(built[:500])

    print("\n=== 프로필 규칙 ===")
    for profile in ["coder", "qa", "reviewer"]:
        print(f"\n[{profile}]")
        print(supervisor._get_profile_rules(profile))
