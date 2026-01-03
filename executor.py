"""
Hattz Empire - Executor Layer
에이전트가 실제로 파일을 읽고, 수정하고, 명령어를 실행할 수 있게 해주는 모듈
"""
import os
import subprocess
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


# =============================================================================
# Security Configuration
# =============================================================================

# 허용된 명령어 화이트리스트
ALLOWED_COMMANDS = {
    # Git
    "git status", "git diff", "git log", "git add", "git commit", "git push",
    "git pull", "git branch", "git checkout", "git merge", "git stash",

    # Python
    "python", "python3", "pip", "pip3", "pytest", "mypy", "black", "flake8",

    # Node.js
    "npm", "npx", "node", "yarn", "pnpm",

    # 기본 유틸
    "ls", "dir", "cat", "type", "echo", "cd", "pwd",
}

# 금지된 패턴 (보안 위험)
BLOCKED_PATTERNS = [
    r"rm\s+-rf",
    r"del\s+/[sS]",
    r"format\s+",
    r":(){ :|:& };:",  # Fork bomb
    r">\s*/dev/",
    r"curl.*\|.*sh",
    r"wget.*\|.*sh",
]

# 프로젝트 베이스 경로 (이 경로 밖은 접근 금지)
ALLOWED_BASE_PATHS = [
    r"C:\Users\hahonggu\Desktop\coin_master",
    "C:/Users/hahonggu/Desktop/coin_master",
    r"D:\Projects",
    "D:/Projects",
]


@dataclass
class ExecutionResult:
    """실행 결과"""
    success: bool
    output: str
    error: Optional[str] = None
    action: str = ""
    target: str = ""


# =============================================================================
# Path Security
# =============================================================================

def is_path_allowed(path: str) -> bool:
    """경로가 허용된 베이스 경로 내에 있는지 확인"""
    # 경로 정규화 (슬래시 통일 + 소문자 - Windows는 대소문자 구분 안함)
    abs_path = os.path.abspath(path).replace('\\', '/').lower()
    for base in ALLOWED_BASE_PATHS:
        normalized_base = base.replace('\\', '/').lower()
        if abs_path.startswith(normalized_base):
            return True
    return False


def sanitize_path(path: str) -> str:
    """경로 정규화 및 위험 패턴 제거"""
    # .. 경로 탈출 방지
    path = os.path.normpath(path)
    if ".." in path:
        raise ValueError(f"Path traversal detected: {path}")
    return path


# =============================================================================
# Command Security
# =============================================================================

def is_command_allowed(command: str) -> bool:
    """명령어가 화이트리스트에 있는지 확인"""
    # 금지 패턴 체크
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False

    # 첫 번째 명령어 추출
    cmd_parts = command.strip().split()
    if not cmd_parts:
        return False

    first_cmd = cmd_parts[0].lower()

    # 직접 허용된 명령어
    for allowed in ALLOWED_COMMANDS:
        if first_cmd == allowed or command.lower().startswith(allowed):
            return True

    return False


# =============================================================================
# Executor Functions
# =============================================================================

def read_file(file_path: str) -> ExecutionResult:
    """파일 읽기"""
    try:
        path = sanitize_path(file_path)

        if not is_path_allowed(path):
            return ExecutionResult(
                success=False,
                output="",
                error=f"Access denied: {path} is outside allowed directories",
                action="read",
                target=path
            )

        if not os.path.exists(path):
            return ExecutionResult(
                success=False,
                output="",
                error=f"File not found: {path}",
                action="read",
                target=path
            )

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        return ExecutionResult(
            success=True,
            output=content,
            action="read",
            target=path
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            output="",
            error=str(e),
            action="read",
            target=file_path
        )


def write_file(file_path: str, content: str) -> ExecutionResult:
    """파일 쓰기"""
    try:
        path = sanitize_path(file_path)

        if not is_path_allowed(path):
            return ExecutionResult(
                success=False,
                output="",
                error=f"Access denied: {path} is outside allowed directories",
                action="write",
                target=path
            )

        # 디렉토리가 없으면 생성
        os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

        return ExecutionResult(
            success=True,
            output=f"Successfully wrote {len(content)} bytes to {path}",
            action="write",
            target=path
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            output="",
            error=str(e),
            action="write",
            target=file_path
        )


def run_command(command: str, cwd: Optional[str] = None) -> ExecutionResult:
    """명령어 실행"""
    try:
        if not is_command_allowed(command):
            return ExecutionResult(
                success=False,
                output="",
                error=f"Command not allowed: {command}",
                action="run",
                target=command
            )

        # cwd 검증
        if cwd:
            cwd = sanitize_path(cwd)
            if not is_path_allowed(cwd):
                return ExecutionResult(
                    success=False,
                    output="",
                    error=f"Working directory not allowed: {cwd}",
                    action="run",
                    target=command
                )

        # 명령어 실행
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60  # 60초 타임아웃
        )

        output = result.stdout
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr}"

        return ExecutionResult(
            success=result.returncode == 0,
            output=output,
            error=result.stderr if result.returncode != 0 else None,
            action="run",
            target=command
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            success=False,
            output="",
            error="Command timed out (60s limit)",
            action="run",
            target=command
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            output="",
            error=str(e),
            action="run",
            target=command
        )


def list_files(directory: str, pattern: str = "*") -> ExecutionResult:
    """디렉토리 파일 목록"""
    try:
        path = sanitize_path(directory)

        if not is_path_allowed(path):
            return ExecutionResult(
                success=False,
                output="",
                error=f"Access denied: {path} is outside allowed directories",
                action="list",
                target=path
            )

        if not os.path.isdir(path):
            return ExecutionResult(
                success=False,
                output="",
                error=f"Not a directory: {path}",
                action="list",
                target=path
            )

        # 디렉토리 내 파일/폴더 목록
        items = []
        for item in os.listdir(path):
            full_path = os.path.join(path, item)
            if os.path.isdir(full_path):
                items.append(f"[DIR] {item}/")
            else:
                items.append(f"      {item}")

        return ExecutionResult(
            success=True,
            output="\n".join(sorted(items)),
            action="list",
            target=path
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            output="",
            error=str(e),
            action="list",
            target=directory
        )


# =============================================================================
# [EXEC] Tag Parser
# =============================================================================

EXEC_PATTERN = re.compile(
    r'\[EXEC:(\w+)(?::([^\]]+))?\](?:\n```(?:\w+)?\n(.*?)\n```)?',
    re.DOTALL
)


def parse_exec_tags(text: str) -> List[Dict[str, Any]]:
    """
    AI 응답에서 [EXEC] 태그 파싱

    지원 형식:
    - [EXEC:read:path/to/file.py]
    - [EXEC:write:path/to/file.py]
      ```python
      content here
      ```
    - [EXEC:run:git status]
    - [EXEC:list:directory/path]
    """
    exec_commands = []

    for match in EXEC_PATTERN.finditer(text):
        action = match.group(1).lower()
        target = match.group(2) or ""
        content = match.group(3) or ""

        exec_commands.append({
            "action": action,
            "target": target.strip(),
            "content": content.strip(),
            "raw": match.group(0)
        })

    return exec_commands


def execute_command(cmd: Dict[str, Any]) -> ExecutionResult:
    """단일 [EXEC] 명령 실행"""
    action = cmd["action"]
    target = cmd["target"]
    content = cmd.get("content", "")

    if action == "read":
        return read_file(target)
    elif action == "write":
        return write_file(target, content)
    elif action == "run":
        return run_command(target)
    elif action == "list":
        return list_files(target)
    else:
        return ExecutionResult(
            success=False,
            output="",
            error=f"Unknown action: {action}",
            action=action,
            target=target
        )


def execute_all(text: str) -> List[ExecutionResult]:
    """
    AI 응답의 모든 [EXEC] 태그 실행

    Returns:
        List of ExecutionResult
    """
    commands = parse_exec_tags(text)
    results = []

    for cmd in commands:
        result = execute_command(cmd)
        results.append(result)

    return results


def format_results(results: List[ExecutionResult]) -> str:
    """실행 결과를 포맷팅"""
    if not results:
        return ""

    output = "\n\n---\n## Execution Results\n"

    for i, result in enumerate(results, 1):
        status = "" if result.success else ""
        output += f"\n### {i}. [{result.action}] {result.target}\n"
        output += f"**Status:** {status} {'Success' if result.success else 'Failed'}\n"

        if result.output:
            # 긴 출력은 truncate
            display_output = result.output[:2000]
            if len(result.output) > 2000:
                display_output += f"\n... (truncated, {len(result.output)} total chars)"
            output += f"```\n{display_output}\n```\n"

        if result.error:
            output += f"**Error:** {result.error}\n"

    return output


# =============================================================================
# [CALL] Tag Parser - PM이 다른 에이전트 호출
# =============================================================================

CALL_PATTERN = re.compile(
    r'\[CALL:(\w+)\]\s*\n(.*?)(?=\[/CALL\]|\[CALL:|\Z)',
    re.DOTALL
)

# 호출 가능한 에이전트 목록
CALLABLE_AGENTS = {
    "excavator": "코드 분석 전문가",
    "coder": "코드 작성 전문가",
    "qa": "품질 검증 전문가",
    "researcher": "리서치 전문가",
}


@dataclass
class CallRequest:
    """에이전트 호출 요청"""
    agent: str
    message: str
    raw: str


def parse_call_tags(text: str) -> List[CallRequest]:
    """
    PM 응답에서 [CALL:agent] 태그 파싱

    지원 형식:
    - [CALL:excavator]
      분석할 내용...
      [/CALL]
    - [CALL:coder]
      구현할 내용...
      [/CALL]
    """
    calls = []

    for match in CALL_PATTERN.finditer(text):
        agent = match.group(1).lower()
        message = match.group(2).strip()

        if agent in CALLABLE_AGENTS:
            calls.append(CallRequest(
                agent=agent,
                message=message,
                raw=match.group(0)
            ))

    return calls


def has_call_tags(text: str) -> bool:
    """텍스트에 [CALL:] 태그가 있는지 확인"""
    return bool(CALL_PATTERN.search(text))


def extract_call_info(text: str) -> List[Dict[str, str]]:
    """
    [CALL:] 태그 정보 추출 (API 응답용)

    Returns:
        List of {agent: str, message: str}
    """
    calls = parse_call_tags(text)
    return [{"agent": c.agent, "message": c.message} for c in calls]


# =============================================================================
# Main Executor Function (for API endpoint)
# =============================================================================

def execute_api(action: str, target: str, content: str = "", cwd: str = None) -> Dict[str, Any]:
    """
    API 엔드포인트용 실행 함수

    Args:
        action: read, write, run, list
        target: 파일 경로 또는 명령어
        content: write 액션용 내용
        cwd: run 액션용 작업 디렉토리

    Returns:
        Dict with success, output, error
    """
    if action == "read":
        result = read_file(target)
    elif action == "write":
        result = write_file(target, content)
    elif action == "run":
        result = run_command(target, cwd)
    elif action == "list":
        result = list_files(target)
    else:
        result = ExecutionResult(
            success=False,
            output="",
            error=f"Unknown action: {action}",
            action=action,
            target=target
        )

    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "action": result.action,
        "target": result.target
    }
