"""
Hattz Empire - Server Logger
장애 대응을 위한 구조화된 로깅 시스템

로그 구조:
  logs/
  ├── server.log           # 전체 로그 (INFO+)
  ├── error.log            # 에러만 (ERROR+)
  └── llm_calls.log        # LLM API 호출 추적

사용법:
    from src.utils.server_logger import logger, log_llm_call, log_error

    # 일반 로그
    logger.info("Server started")
    logger.warning("Rate limit approaching")
    logger.error("API call failed", exc_info=True)

    # LLM 호출 로그
    log_llm_call("coder", "openai", "gpt-5.2", tokens=1500, cost=0.045, success=True)

    # 에러 로그 (자동 스택트레이스)
    log_error("LLM API Error", agent="coder", model="gpt-5.2", error=str(e))
"""
import logging
import json
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler

# 로그 디렉토리
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


# =============================================================================
# 커스텀 포매터 (JSON 구조화)
# =============================================================================

class JsonFormatter(logging.Formatter):
    """JSON 형식 로그 포매터"""

    def format(self, record):
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 추가 필드 (extra로 전달된 것들)
        if hasattr(record, "agent"):
            log_data["agent"] = record.agent
        if hasattr(record, "model"):
            log_data["model"] = record.model
        if hasattr(record, "tokens"):
            log_data["tokens"] = record.tokens
        if hasattr(record, "cost"):
            log_data["cost"] = record.cost
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        if hasattr(record, "session_id"):
            log_data["session_id"] = record.session_id
        if hasattr(record, "error_type"):
            log_data["error_type"] = record.error_type

        # 예외 정보
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class ReadableFormatter(logging.Formatter):
    """사람이 읽기 좋은 포매터 (콘솔용)"""

    def format(self, record):
        # 레벨별 색상 (콘솔용)
        level_colors = {
            "DEBUG": "\033[36m",    # Cyan
            "INFO": "\033[32m",     # Green
            "WARNING": "\033[33m",  # Yellow
            "ERROR": "\033[31m",    # Red
            "CRITICAL": "\033[35m", # Magenta
        }
        reset = "\033[0m"

        color = level_colors.get(record.levelname, "")
        timestamp = datetime.now().strftime("%H:%M:%S")

        # 기본 메시지
        msg = f"{color}[{timestamp}] {record.levelname:8}{reset} {record.getMessage()}"

        # 추가 필드
        extras = []
        if hasattr(record, "agent"):
            extras.append(f"agent={record.agent}")
        if hasattr(record, "model"):
            extras.append(f"model={record.model}")
        if hasattr(record, "tokens"):
            extras.append(f"tokens={record.tokens}")
        if hasattr(record, "cost"):
            extras.append(f"cost=${record.cost:.4f}")
        if hasattr(record, "duration_ms"):
            extras.append(f"time={record.duration_ms}ms")

        if extras:
            msg += f" | {' '.join(extras)}"

        # 예외 정보
        if record.exc_info:
            msg += f"\n{self.formatException(record.exc_info)}"

        return msg


# =============================================================================
# 로거 설정
# =============================================================================

def setup_logger():
    """메인 로거 설정"""
    logger = logging.getLogger("hattz_empire")
    logger.setLevel(logging.DEBUG)

    # 중복 핸들러 방지
    if logger.handlers:
        return logger

    # 1. 콘솔 핸들러 (읽기 좋은 포맷)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(ReadableFormatter())
    logger.addHandler(console_handler)

    # 2. 전체 로그 파일 (JSON, 10MB 로테이션, 5개 보관)
    server_handler = RotatingFileHandler(
        LOG_DIR / "server.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    server_handler.setLevel(logging.INFO)
    server_handler.setFormatter(JsonFormatter())
    logger.addHandler(server_handler)

    # 3. 에러 전용 파일 (JSON, 5MB 로테이션, 10개 보관)
    error_handler = RotatingFileHandler(
        LOG_DIR / "error.log",
        maxBytes=5*1024*1024,  # 5MB
        backupCount=10,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JsonFormatter())
    logger.addHandler(error_handler)

    return logger


# =============================================================================
# LLM 호출 로거
# =============================================================================

def setup_llm_logger():
    """LLM API 호출 전용 로거"""
    llm_logger = logging.getLogger("hattz_empire.llm")
    llm_logger.setLevel(logging.INFO)

    if llm_logger.handlers:
        return llm_logger

    # LLM 호출 전용 파일 (JSON, 20MB 로테이션, 7개 보관)
    llm_handler = RotatingFileHandler(
        LOG_DIR / "llm_calls.log",
        maxBytes=20*1024*1024,  # 20MB
        backupCount=7,
        encoding="utf-8"
    )
    llm_handler.setLevel(logging.INFO)
    llm_handler.setFormatter(JsonFormatter())
    llm_logger.addHandler(llm_handler)

    return llm_logger


# =============================================================================
# 싱글톤 인스턴스
# =============================================================================

logger = setup_logger()
llm_logger = setup_llm_logger()


# =============================================================================
# 헬퍼 함수
# =============================================================================

def log_llm_call(
    agent: str,
    provider: str,
    model: str,
    tokens: int = 0,
    cost: float = 0.0,
    duration_ms: int = 0,
    success: bool = True,
    session_id: str = None,
    error: str = None
):
    """
    LLM API 호출 로그

    Args:
        agent: 에이전트 역할 (coder, qa, pm, etc.)
        provider: API 제공자 (openai, anthropic, google, perplexity)
        model: 모델명 (gpt-5.2, claude-opus-4.5, etc.)
        tokens: 사용 토큰 수
        cost: 비용 (USD)
        duration_ms: 응답 시간 (밀리초)
        success: 성공 여부
        session_id: 세션 ID
        error: 에러 메시지 (실패 시)
    """
    extra = {
        "agent": agent,
        "model": f"{provider}/{model}",
        "tokens": tokens,
        "cost": cost,
        "duration_ms": duration_ms,
    }
    if session_id:
        extra["session_id"] = session_id
    if error:
        extra["error_type"] = error

    if success:
        llm_logger.info(f"LLM call: {agent} -> {model}", extra=extra)
    else:
        llm_logger.error(f"LLM call FAILED: {agent} -> {model}", extra=extra)


def log_error(
    message: str,
    agent: str = None,
    model: str = None,
    session_id: str = None,
    error_type: str = None,
    exc_info: bool = True
):
    """
    에러 로그 (자동 스택트레이스)

    Args:
        message: 에러 메시지
        agent: 에이전트 역할
        model: 모델명
        session_id: 세션 ID
        error_type: 에러 타입 (API_ERROR, TIMEOUT, etc.)
        exc_info: 스택트레이스 포함 여부
    """
    extra = {}
    if agent:
        extra["agent"] = agent
    if model:
        extra["model"] = model
    if session_id:
        extra["session_id"] = session_id
    if error_type:
        extra["error_type"] = error_type

    logger.error(message, extra=extra, exc_info=exc_info)


def log_request(method: str, path: str, status: int, duration_ms: int, session_id: str = None):
    """HTTP 요청 로그"""
    extra = {"duration_ms": duration_ms}
    if session_id:
        extra["session_id"] = session_id

    if status >= 500:
        logger.error(f"{method} {path} -> {status}", extra=extra)
    elif status >= 400:
        logger.warning(f"{method} {path} -> {status}", extra=extra)
    else:
        logger.info(f"{method} {path} -> {status}", extra=extra)


# =============================================================================
# Flask 미들웨어
# =============================================================================

def init_request_logging(app):
    """Flask 앱에 요청 로깅 미들웨어 추가"""
    import time
    from flask import request, g

    @app.before_request
    def before_request():
        g.start_time = time.time()

    @app.after_request
    def after_request(response):
        if hasattr(g, "start_time"):
            duration_ms = int((time.time() - g.start_time) * 1000)
            session_id = request.headers.get("X-Session-ID")

            # 정적 파일 제외
            if not request.path.startswith("/static"):
                log_request(
                    method=request.method,
                    path=request.path,
                    status=response.status_code,
                    duration_ms=duration_ms,
                    session_id=session_id
                )
        return response

    logger.info("Request logging middleware initialized")
