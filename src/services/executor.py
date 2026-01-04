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

# =============================================================================
# WPCN Configuration
# =============================================================================
WPCN_BASE_PATH = "C:/Users/hahonggu/Desktop/coin_master/projects/wpcn-backtester-cli-noflask"

# WPCN 지원 명령어
WPCN_COMMANDS = {
    "backtest": "현물 백테스트 실행",
    "futures": "선물 백테스트 실행",
    "optimize": "파라미터 최적화 (Walk-Forward)",
    "status": "최적화 상태 확인",
    "symbols": "지원 심볼 목록",
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
    # 절대 경로로 변환 (상대 경로 '.', '..' 처리)
    path = os.path.abspath(path)
    # .. 경로 탈출 방지 (abspath 이후에도 남아있으면 위험)
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


# =============================================================================
# WPCN Executor Functions
# =============================================================================

def run_wpcn_backtest(symbol: str = "BTC-USDT", timeframe: str = "15m", days: int = 90) -> ExecutionResult:
    """
    WPCN 현물 백테스트 실행

    Args:
        symbol: 거래 심볼 (예: BTC-USDT, ETH-USDT)
        timeframe: 타임프레임 (예: 15m, 1h)
        days: 백테스트 기간 (일)
    """
    try:
        wpcn_path = WPCN_BASE_PATH.replace('/', '\\')
        num_files = days // 30 + 1

        script = f'''
import sys
sys.path.insert(0, r"{wpcn_path}")
import pandas as pd
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

from wpcn._03_common._01_core.types import Theta, BacktestCosts, BacktestConfig
from wpcn._04_execution.broker_sim_mtf import simulate_mtf

# 데이터 로드
data_path = Path(r"{wpcn_path}/data/bronze/binance/futures/{symbol}/{timeframe}")
if not data_path.exists():
    print(f"ERROR: Data not found at {{data_path}}")
    exit(1)

files = sorted(data_path.rglob("*.parquet"))[-{num_files}:]
dfs = [pd.read_parquet(f) for f in files]
df = pd.concat(dfs, ignore_index=True)
df = df.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")

# 설정 (edge_min=0.0으로 Navigation Gate edge 조건 비활성화)
theta = Theta(pivot_lr=3, box_L=50, m_freeze=16, atr_len=14, x_atr=2.0, m_bw=0.02, N_reclaim=8, N_fill=5, F_min=0.3)
costs = BacktestCosts(fee_bps=7.5, slippage_bps=5.0)
cfg = BacktestConfig(initial_equity=10000.0, max_hold_bars=288, conf_min=0.30, edge_min=0.0, confirm_bars=1)

# 백테스트
equity_df, trades_df, signals_df, nav_df = simulate_mtf(
    df=df, theta=theta, costs=costs, cfg=cfg,
    mtf=["15m", "1h", "4h"], spot_mode=True,
    min_score=3.5, min_tf_alignment=2, min_rr_ratio=1.2
)

# 결과
if len(trades_df) > 0:
    final_eq = equity_df["equity"].iloc[-1]
    ret = (final_eq - 10000) / 10000 * 100
    mdd = ((equity_df["equity"].cummax() - equity_df["equity"]) / equity_df["equity"].cummax()).max() * 100
    entry_cnt = len(trades_df[trades_df["type"] == "ENTRY"])
    exit_trades = trades_df[trades_df["type"].isin(["TP1", "TP2", "STOP", "TIME_EXIT"])]
    win_rate = len(exit_trades[exit_trades["pnl_pct"] > 0]) / len(exit_trades) * 100 if len(exit_trades) > 0 else 0
    print(f"=== {symbol} 백테스트 결과 ===")
    print(f"기간: {{df.index.min()}} ~ {{df.index.max()}}")
    print(f"캔들 수: {{len(df):,}}")
    print(f"수익률: {{ret:.2f}}%")
    print(f"MDD: {{mdd:.2f}}%")
    print(f"진입: {{entry_cnt}}회")
    print(f"승률: {{win_rate:.1f}}%")
else:
    print("거래 없음 (신호 조건 미충족)")
'''

        result = subprocess.run(
            ["python", "-c", script],
            capture_output=True,
            text=True,
            timeout=300,  # 5분 타임아웃
            cwd=wpcn_path
        )

        return ExecutionResult(
            success=result.returncode == 0,
            output=result.stdout + (f"\n[STDERR]\n{result.stderr}" if result.stderr else ""),
            error=result.stderr if result.returncode != 0 else None,
            action="wpcn:backtest",
            target=f"{symbol} {timeframe} {days}d"
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            success=False, output="", error="Backtest timed out (5min limit)",
            action="wpcn:backtest", target=f"{symbol} {timeframe}"
        )
    except Exception as e:
        return ExecutionResult(
            success=False, output="", error=str(e),
            action="wpcn:backtest", target=f"{symbol} {timeframe}"
        )


def run_wpcn_optimize(symbol: str = "BTC-USDT", timeframe: str = "15m", optimizer: str = "optuna") -> ExecutionResult:
    """
    WPCN 파라미터 최적화 실행

    Args:
        symbol: 거래 심볼
        timeframe: 타임프레임
        optimizer: 최적화 방식 (random, optuna, bayesian, grid)
    """
    try:
        wpcn_path = WPCN_BASE_PATH.replace('/', '\\')

        result = subprocess.run(
            ["python", "-m", "wpcn._08_tuning.run_tuning",
             "--symbol", symbol, "--timeframe", timeframe, "--optimizer", optimizer],
            capture_output=True,
            text=True,
            timeout=1800,  # 30분 타임아웃
            cwd=wpcn_path
        )

        return ExecutionResult(
            success=result.returncode == 0,
            output=result.stdout + (f"\n[STDERR]\n{result.stderr}" if result.stderr else ""),
            error=result.stderr if result.returncode != 0 else None,
            action="wpcn:optimize",
            target=f"{symbol} {timeframe} ({optimizer})"
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            success=False, output="", error="Optimization timed out (30min limit)",
            action="wpcn:optimize", target=f"{symbol} {timeframe}"
        )
    except Exception as e:
        return ExecutionResult(
            success=False, output="", error=str(e),
            action="wpcn:optimize", target=f"{symbol} {timeframe}"
        )


def run_wpcn_status() -> ExecutionResult:
    """WPCN 시스템 상태 확인"""
    try:
        script = '''
import sys
sys.path.insert(0, r"{wpcn_path}")
from wpcn._08_tuning import get_optuna_status, HAS_OPTUNA
from pathlib import Path
import os

print("=== WPCN 시스템 상태 ===")
print(f"Optuna 설치: {{HAS_OPTUNA}}")
status = get_optuna_status()
print(f"Optuna 버전: {{status.get('optuna_version', 'N/A')}}")

data_path = Path(r"{wpcn_path}/data/bronze/binance/futures")
if data_path.exists():
    symbols = [d.name for d in data_path.iterdir() if d.is_dir()]
    print(f"\\n사용 가능한 심볼: {{len(symbols)}}개")
    for s in symbols[:5]:
        print(f"  - {{s}}")
    if len(symbols) > 5:
        print(f"  ... 외 {{len(symbols) - 5}}개")
else:
    print("데이터 폴더 없음")

results_path = Path(r"{wpcn_path}/results")
if results_path.exists():
    results = sorted(results_path.glob("*.json"), key=os.path.getmtime, reverse=True)[:3]
    if results:
        print(f"\\n최근 최적화 결과:")
        for r in results:
            print(f"  - {{r.name}}")
'''.format(wpcn_path=WPCN_BASE_PATH.replace('/', '\\\\'))

        result = subprocess.run(
            ["python", "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=WPCN_BASE_PATH
        )

        return ExecutionResult(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr if result.returncode != 0 else None,
            action="wpcn:status",
            target="system"
        )
    except Exception as e:
        return ExecutionResult(
            success=False, output="", error=str(e),
            action="wpcn:status", target="system"
        )


def run_wpcn_symbols() -> ExecutionResult:
    """WPCN 지원 심볼 목록"""
    try:
        script = '''
from pathlib import Path

data_path = Path(r"{wpcn_path}/data/bronze/binance/futures")
if data_path.exists():
    symbols = sorted([d.name for d in data_path.iterdir() if d.is_dir()])
    print("=== 지원 심볼 목록 ===")
    for s in symbols:
        sym_path = data_path / s / "15m"
        if sym_path.exists():
            files = list(sym_path.rglob("*.parquet"))
            if files:
                print(f"{{s}}: {{len(files)}}개 파일")
else:
    print("데이터 폴더 없음")
'''.format(wpcn_path=WPCN_BASE_PATH.replace('/', '\\\\'))

        result = subprocess.run(
            ["python", "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=WPCN_BASE_PATH
        )

        return ExecutionResult(
            success=result.returncode == 0,
            output=result.stdout,
            error=result.stderr if result.returncode != 0 else None,
            action="wpcn:symbols",
            target="list"
        )
    except Exception as e:
        return ExecutionResult(
            success=False, output="", error=str(e),
            action="wpcn:symbols", target="list"
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
    # =============================================================================
    # WPCN Commands: [EXEC:wpcn:command:args]
    # =============================================================================
    elif action == "wpcn":
        return execute_wpcn_command(target, content)
    else:
        return ExecutionResult(
            success=False,
            output="",
            error=f"Unknown action: {action}",
            action=action,
            target=target
        )


def execute_wpcn_command(target: str, content: str = "") -> ExecutionResult:
    """
    WPCN 명령어 실행

    지원 형식:
    - [EXEC:wpcn:backtest:BTC-USDT:15m:90]  # 백테스트
    - [EXEC:wpcn:optimize:BTC-USDT:15m:optuna]  # 최적화
    - [EXEC:wpcn:status]  # 상태 확인
    - [EXEC:wpcn:symbols]  # 심볼 목록
    """
    parts = target.split(":")
    command = parts[0].lower() if parts else ""

    if command == "backtest":
        symbol = parts[1] if len(parts) > 1 else "BTC-USDT"
        timeframe = parts[2] if len(parts) > 2 else "15m"
        days = int(parts[3]) if len(parts) > 3 else 90
        return run_wpcn_backtest(symbol, timeframe, days)

    elif command == "optimize":
        symbol = parts[1] if len(parts) > 1 else "BTC-USDT"
        timeframe = parts[2] if len(parts) > 2 else "15m"
        optimizer = parts[3] if len(parts) > 3 else "optuna"
        return run_wpcn_optimize(symbol, timeframe, optimizer)

    elif command == "status":
        return run_wpcn_status()

    elif command == "symbols":
        return run_wpcn_symbols()

    elif command == "help":
        help_text = """=== WPCN 명령어 도움말 ===

[EXEC:wpcn:backtest:심볼:타임프레임:일수]
  예: [EXEC:wpcn:backtest:BTC-USDT:15m:90]
  현물 백테스트 실행

[EXEC:wpcn:optimize:심볼:타임프레임:옵티마이저]
  예: [EXEC:wpcn:optimize:BTC-USDT:15m:optuna]
  옵티마이저: random, optuna, bayesian, grid

[EXEC:wpcn:status]
  시스템 상태 확인

[EXEC:wpcn:symbols]
  지원 심볼 목록
"""
        return ExecutionResult(
            success=True,
            output=help_text,
            action="wpcn:help",
            target="help"
        )

    else:
        return ExecutionResult(
            success=False,
            output="",
            error=f"Unknown WPCN command: {command}. Use [EXEC:wpcn:help] for available commands.",
            action="wpcn",
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


# 대용량 파일 요약 임계값
LARGE_FILE_THRESHOLD = 10000  # 10KB 이상이면 Gemini로 요약


def _summarize_with_gemini(content: str, file_path: str, session_id: str = None) -> str:
    """
    Gemini를 사용해 대용량 파일 요약/통계화

    Gemini 3 Pro는 1M 토큰 컨텍스트로 대용량 처리에 최적
    """
    import time
    start_time = time.time()
    input_chars = len(content)

    try:
        import google.generativeai as genai
        import os

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return f"[요약 불가: GOOGLE_API_KEY 없음]\n원본 크기: {len(content):,} bytes"

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        # 파일 확장자로 타입 판단
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".json":
            prompt = f"""다음은 대용량 JSON 파일입니다. 핵심 통계와 구조를 요약해주세요.

## 요청
1. 전체 구조 (최상위 키, 데이터 타입)
2. 핵심 숫자/통계 (있다면)
3. 주요 발견 사항 (문제점, 패턴 등)
4. 데이터 품질 이슈 (있다면)

## 파일 내용
```json
{content[:500000]}
```

## 출력 형식
간결한 bullet point로 핵심만 요약. 한글로 작성."""
        else:
            prompt = f"""다음은 대용량 파일입니다. 핵심 내용을 요약해주세요.

## 파일: {file_path}
## 크기: {len(content):,} bytes

## 내용
```
{content[:500000]}
```

## 요청
- 핵심 내용 요약
- 주요 통계/숫자
- 발견된 패턴이나 이슈

한글로 간결하게 작성."""

        response = model.generate_content(prompt)
        output_text = response.text

        # 로그 기록 (agent_logs에 Gemini 요약 기록)
        latency_ms = int((time.time() - start_time) * 1000)
        _log_gemini_summarization(
            session_id=session_id,
            task_type="file_summarize",
            input_chars=input_chars,
            output_chars=len(output_text),
            latency_ms=latency_ms,
            file_path=file_path
        )

        return f"""📊 **Gemini 요약** (원본: {len(content):,} bytes)

{output_text}"""

    except ImportError:
        return f"[요약 불가: google-generativeai 미설치]\n원본 크기: {len(content):,} bytes"
    except Exception as e:
        return f"[요약 실패: {str(e)}]\n원본 크기: {len(content):,} bytes\n\n처음 2000자:\n{content[:2000]}"


def _log_gemini_summarization(
    session_id: str,
    task_type: str,
    input_chars: int,
    output_chars: int,
    latency_ms: int,
    file_path: str = None
):
    """Gemini 요약 호출을 agent_logs DB에 기록"""
    try:
        from .agent_scorecard import get_scorecard

        scorecard = get_scorecard()
        if not scorecard._initialized:
            print("[Executor] Scorecard not initialized, skipping log")
            return

        # 토큰 추정 (한글 1자 ≈ 2토큰, 영문 4자 ≈ 1토큰)
        input_tokens = input_chars // 3
        output_tokens = output_chars // 3

        task_summary = f"Gemini 요약: {file_path or 'unknown'}"[:200]

        log_id = scorecard.log_task(
            session_id=session_id or "system",
            task_id=f"gemini_sum_{latency_ms}",
            role="summarizer",
            engine="gemini",
            model="gemini-2.0-flash",
            task_type=task_type,
            task_summary=task_summary,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms
        )
        print(f"[Executor] Gemini summarization logged: {log_id}")
    except Exception as e:
        print(f"[Executor] Failed to log Gemini call: {e}")


def format_results(results: List[ExecutionResult]) -> str:
    """실행 결과를 포맷팅 (대용량은 Gemini로 요약)"""
    if not results:
        return ""

    output = "\n\n---\n## Execution Results\n"

    for i, result in enumerate(results, 1):
        status = "✅" if result.success else "❌"
        output += f"\n### {i}. [{result.action}] {result.target}\n"
        output += f"**Status:** {status} {'Success' if result.success else 'Failed'}\n"

        if result.output:
            content_size = len(result.output)

            if content_size > LARGE_FILE_THRESHOLD:
                # 대용량 파일 → Gemini로 요약
                print(f"[Executor] Large file detected ({content_size:,} bytes), summarizing with Gemini...")
                summarized = _summarize_with_gemini(result.output, result.target)
                output += f"\n{summarized}\n"
            else:
                # 일반 파일 → 그대로 출력
                output += f"```\n{result.output}\n```\n"

        if result.error:
            output += f"**Error:** {result.error}\n"

    return output


# =============================================================================
# [CALL] Tag Parser - PM이 다른 에이전트 호출
# =============================================================================

# CALL 태그 패턴 (줄바꿈 유무 모두 지원)
# 형식 1: [CALL:agent]\n메시지\n[/CALL]
# 형식 2: [CALL:agent] 메시지 (줄바꿈 없이)
CALL_PATTERN = re.compile(
    r'\[CALL:(\w+)\][\s\n]*(.*?)(?=\[/CALL\]|\[CALL:|\Z)',
    re.DOTALL
)

# 호출 가능한 에이전트 목록
CALLABLE_AGENTS = {
    "excavator": "코드 분석 전문가",
    "coder": "코드 작성 전문가",
    "qa": "품질 검증 전문가",
    "qa_logic": "로직 검증 전문가",
    "researcher": "리서치 전문가",
    "strategist": "전략 분석 전문가",
    "analyst": "데이터 분석 전문가",
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
