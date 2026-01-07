"""
Hattz Empire - Claude Code CLI Supervisor
Claude Code CLI 호출 + 세션 관리 + 에러 복구

v2.5.3: CLI Semantic Guard 추가
- 코드 기반 의미 검증 (LLM 없이)
- 금지 패턴 블랙리스트 (의미적 NULL 감지)
- Semantic Failure → RetryEscalator 편입

v2.5.2: Retry Escalation 시스템 추가
- 실패 시그니처 해시로 동일 실패 식별
- 3단계 에스컬레이션: Self-repair → Role-switch → Hard Fail
- 동일 prompt+system+temperature 재시도 금지

v2.4.1: Queue 기반 CLI 통제 추가
- CLIQueue: 최대 동시 실행 제한 (기본 2개)
- RateLimiter: 분당 호출 제한 (기본 10회)
- 대기 큐 상태 조회 API

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
import threading
import hashlib
from queue import Queue, Empty
from typing import Optional, Dict, Any, List, Tuple, Callable
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum


# =============================================================================
# Retry Escalation System (v2.5.2)
# =============================================================================

class EscalationLevel(Enum):
    """에스컬레이션 레벨"""
    SELF_REPAIR = 1      # 동일 역할, 에러 피드백으로 재시도
    ROLE_SWITCH = 2      # 다른 역할로 전환 (coder→reviewer 등)
    HARD_FAIL = 3        # 즉시 실패, PM 에스컬레이션


@dataclass
class FailureSignature:
    """
    실패 시그니처 - 동일 실패 식별용

    핵심: 같은 에러가 반복되면 재시도 무의미
    """
    error_type: str           # JSON_PARSE_ERROR, MISSING_FIELD, TIMEOUT, etc.
    missing_fields: tuple     # 누락된 필드들 (정렬된 튜플)
    profile: str              # coder, qa, reviewer, council
    prompt_hash: str          # 프롬프트 앞 500자 해시 (동일 요청 식별)

    def __hash__(self) -> int:
        return hash((self.error_type, self.missing_fields, self.profile, self.prompt_hash))

    def __eq__(self, other) -> bool:
        if not isinstance(other, FailureSignature):
            return False
        return (self.error_type == other.error_type and
                self.missing_fields == other.missing_fields and
                self.profile == other.profile and
                self.prompt_hash == other.prompt_hash)

    def to_dict(self) -> dict:
        return {
            "error_type": self.error_type,
            "missing_fields": list(self.missing_fields),
            "profile": self.profile,
            "prompt_hash": self.prompt_hash[:8]  # 앞 8자만
        }


class RetryEscalator:
    """
    Retry Escalation Manager

    원칙:
    1. 같은 시그니처로 2번 실패하면 에스컬레이션
    2. Self-repair → Role-switch → Hard Fail
    3. 동일 prompt+system 재시도 금지 (변형 필수)
    """

    # 역할 전환 매핑 (Role-switch용)
    ROLE_SWITCH_MAP = {
        "coder": "reviewer",     # 코더 → 리뷰어 (다른 관점)
        "reviewer": "coder",     # 리뷰어 → 코더
        "qa": "coder",           # QA → 코더
        "council": "reviewer",   # 위원회 → 리뷰어
    }

    def __init__(self, max_same_signature: int = 2):
        self.max_same_signature = max_same_signature
        self._failure_history: Dict[FailureSignature, int] = {}
        self._escalation_log: List[Dict] = []
        self._role_switch_used: Dict[str, bool] = {}  # v2.5.5 프로필별 역할 전환 1회 제한
        self._lock = threading.Lock()

    def compute_signature(
        self,
        error_type: str,
        missing_fields: List[str],
        profile: str,
        prompt: str
    ) -> FailureSignature:
        """실패 시그니처 계산"""
        # 프롬프트 해시 (앞 500자 기준)
        prompt_snippet = prompt[:500] if prompt else ""
        prompt_hash = hashlib.md5(prompt_snippet.encode()).hexdigest()

        return FailureSignature(
            error_type=error_type,
            missing_fields=tuple(sorted(missing_fields)) if missing_fields else (),
            profile=profile,
            prompt_hash=prompt_hash
        )

    def record_failure(self, signature: FailureSignature) -> EscalationLevel:
        """
        실패 기록 + 에스컬레이션 레벨 반환

        Returns:
            EscalationLevel - 다음 행동 지시
        """
        with self._lock:
            # 실패 횟수 증가
            count = self._failure_history.get(signature, 0) + 1
            self._failure_history[signature] = count

            # 로그 기록
            self._escalation_log.append({
                "timestamp": time.time(),
                "signature": signature.to_dict(),
                "count": count
            })

            # 에스컬레이션 결정
            if count >= self.max_same_signature + 1:
                level = EscalationLevel.HARD_FAIL
            elif count == self.max_same_signature:
                level = EscalationLevel.ROLE_SWITCH
            else:
                level = EscalationLevel.SELF_REPAIR

            print(f"[RetryEscalator] 실패 기록: {signature.error_type} (count={count}, level={level.name})")
            return level

    def get_escalation_action(
        self,
        level: EscalationLevel,
        current_profile: str,
        original_prompt: str,
        error_message: str
    ) -> Dict[str, Any]:
        """
        에스컬레이션 레벨에 따른 액션 반환

        Returns:
            {
                "action": "retry" | "switch" | "abort",
                "new_profile": str (switch일 때),
                "modified_prompt": str (retry/switch일 때),
                "reason": str
            }
        """
        if level == EscalationLevel.HARD_FAIL:
            return {
                "action": "abort",
                "reason": f"동일 에러 반복 (max={self.max_same_signature}회 초과)",
                "error_type": "ESCALATION_HARD_FAIL"
            }

        elif level == EscalationLevel.ROLE_SWITCH:
            # v2.5.5 역할 전환 1회 제한 체크
            if self._role_switch_used.get(current_profile, False):
                return {
                    "action": "abort",
                    "reason": f"역할 전환 이미 사용됨 (프로필={current_profile}, 1회 제한)",
                    "error_type": "ROLE_SWITCH_EXHAUSTED"
                }

            # 역할 전환 사용 기록
            self._role_switch_used[current_profile] = True
            new_profile = self.ROLE_SWITCH_MAP.get(current_profile, "reviewer")

            # 역할 전환 프롬프트 (다른 관점으로 시도)
            modified_prompt = f"""[ROLE_SWITCH]
이전 {current_profile} 역할에서 실패했습니다.
당신은 {new_profile} 관점에서 이 작업을 처리해주세요.

이전 에러: {error_message[:200]}

[ORIGINAL_TASK]
{original_prompt}
[/ORIGINAL_TASK]

반드시 JSON 형식으로 출력하세요."""

            return {
                "action": "switch",
                "new_profile": new_profile,
                "modified_prompt": modified_prompt,
                "reason": f"역할 전환: {current_profile} → {new_profile}"
            }

        else:  # SELF_REPAIR
            # 에러 피드백 포함 재시도 (프롬프트 변형)
            modified_prompt = f"""[ERROR_FEEDBACK]
이전 응답이 형식 오류로 거부되었습니다.

오류 내용: {error_message}

반드시 수정하여 올바른 JSON만 출력하세요.
JSON 외 텍스트 = 즉시 FAIL

[ORIGINAL_TASK]
{original_prompt}
[/ORIGINAL_TASK]"""

            return {
                "action": "retry",
                "modified_prompt": modified_prompt,
                "reason": "에러 피드백 포함 재시도"
            }

    def clear_history(self, profile: str = None):
        """실패 히스토리 초기화 (v2.5.5 역할 전환 상태도 초기화)"""
        with self._lock:
            if profile:
                # 특정 프로필만 초기화
                keys_to_remove = [k for k in self._failure_history if k.profile == profile]
                for k in keys_to_remove:
                    del self._failure_history[k]
                # v2.5.5 역할 전환 상태도 초기화
                if profile in self._role_switch_used:
                    del self._role_switch_used[profile]
            else:
                self._failure_history.clear()
                self._role_switch_used.clear()
            print(f"[RetryEscalator] 히스토리 초기화 (profile={profile or 'all'})")

    def get_stats(self) -> Dict[str, Any]:
        """통계 조회"""
        with self._lock:
            return {
                "total_failures": sum(self._failure_history.values()),
                "unique_signatures": len(self._failure_history),
                "recent_escalations": self._escalation_log[-10:],
                "by_profile": self._count_by_profile()
            }

    def _count_by_profile(self) -> Dict[str, int]:
        result = {}
        for sig, count in self._failure_history.items():
            result[sig.profile] = result.get(sig.profile, 0) + count
        return result


# 싱글톤 인스턴스
_retry_escalator: Optional[RetryEscalator] = None


def get_retry_escalator() -> RetryEscalator:
    """RetryEscalator 싱글톤"""
    global _retry_escalator
    if _retry_escalator is None:
        _retry_escalator = RetryEscalator(max_same_signature=2)
    return _retry_escalator


# =============================================================================
# Semantic Guard (v2.5.3)
# =============================================================================

class SemanticGuard:
    """
    코드 기반 의미 검증 (LLM 없이)

    원칙:
    1. JSON 형식은 통과했지만 의미가 없는 응답 감지
    2. 금지 패턴 블랙리스트로 "의미적 NULL" 감지
    3. 필드별 규칙으로 최소 품질 강제
    4. Semantic Failure도 RetryEscalator로 편입
    """

    # 의미적 NULL 패턴 (이런 표현은 아무 정보도 없음)
    SEMANTIC_NULL_PATTERNS = [
        # 한글 패턴
        r"검토했습니다",
        r"확인했습니다",
        r"문제.*없습니다",
        r"추가.*확인.*필요",
        r"이상.*없음",
        r"정상.*처리",
        r"완료.*되었습니다",
        r"진행.*하겠습니다",
        r"살펴보겠습니다",
        # 영어 패턴
        r"looks good",
        r"no issues",
        r"seems fine",
        r"will proceed",
        r"I have reviewed",
        r"I checked",
        r"everything is fine",
        r"no problems found",
    ]

    # 프로필별 필수 의미 규칙
    SEMANTIC_RULES = {
        "coder": {
            "summary": {
                "min_length": 10,           # 최소 10자
                "require_verb": True,       # 동사 필수 (수정, 추가, 삭제 등)
                "require_target": True,     # 대상 필수 (파일, 함수, 클래스 등)
            },
            "diff": {
                "min_length": 20,           # diff는 최소 20자
                "require_pattern": r"^[-+@]",  # diff 형식 패턴
            },
            "files_changed": {
                "non_empty_if_diff": True,  # diff 있으면 files_changed도 있어야
            }
        },
        "qa": {
            "verdict": {
                "valid_values": ["PASS", "FAIL", "SKIP"],
            },
            "tests": {
                "non_empty_if_pass": True,  # PASS면 tests 있어야
            }
        },
        "reviewer": {
            "verdict": {
                "valid_values": ["APPROVE", "REVISE", "REJECT"],
            },
            "security_score": {
                "range": (0, 10),
            },
            "risks_if_reject": True,  # REJECT면 risks 있어야
        },
        "council": {
            "score": {
                "range": (0, 10),
            },
            "reasoning": {
                "min_length": 20,
            }
        }
    }

    # 동사 패턴 (한글)
    VERB_PATTERNS = [
        r"수정", r"추가", r"삭제", r"변경", r"생성", r"구현", r"적용",
        r"리팩토링", r"개선", r"업데이트", r"fix", r"add", r"remove",
        r"update", r"create", r"implement", r"refactor"
    ]

    # 대상 패턴 (한글)
    TARGET_PATTERNS = [
        r"파일", r"함수", r"클래스", r"메서드", r"모듈", r"변수", r"상수",
        r"API", r"엔드포인트", r"라우트", r"컴포넌트", r"테스트",
        r"file", r"function", r"class", r"method", r"module", r"\.py",
        r"\.js", r"\.ts", r"\.json"
    ]

    def __init__(self):
        self._compiled_null_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.SEMANTIC_NULL_PATTERNS
        ]
        self._compiled_verb_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.VERB_PATTERNS
        ]
        self._compiled_target_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.TARGET_PATTERNS
        ]

    def validate(self, parsed_json: dict, profile: str) -> tuple[bool, str]:
        """
        의미 검증

        Args:
            parsed_json: 파싱된 JSON (형식 검증 통과한 것)
            profile: 프로필 (coder, qa, reviewer, council)

        Returns:
            (valid, error_message)
        """
        # 1. 전체 텍스트에서 의미적 NULL 패턴 검사
        full_text = json.dumps(parsed_json, ensure_ascii=False)
        null_error = self._check_semantic_null(full_text)
        if null_error:
            return False, null_error

        # 2. 프로필별 규칙 검사
        rules = self.SEMANTIC_RULES.get(profile, {})
        for field, field_rules in rules.items():
            value = parsed_json.get(field)
            field_error = self._check_field_rules(field, value, field_rules, parsed_json)
            if field_error:
                return False, field_error

        return True, ""

    def _check_semantic_null(self, text: str) -> Optional[str]:
        """의미적 NULL 패턴 검사"""
        for pattern in self._compiled_null_patterns:
            if pattern.search(text):
                return f"의미적 NULL 감지: '{pattern.pattern}' 패턴 발견. 구체적인 내용 필요"
        return None

    def _check_field_rules(
        self,
        field: str,
        value: Any,
        rules: dict,
        full_json: dict
    ) -> Optional[str]:
        """필드별 규칙 검사"""

        # min_length 검사
        if "min_length" in rules:
            if value is None or len(str(value)) < rules["min_length"]:
                return f"'{field}' 필드 너무 짧음 (최소 {rules['min_length']}자)"

        # require_verb 검사
        if rules.get("require_verb") and value:
            if not any(p.search(str(value)) for p in self._compiled_verb_patterns):
                return f"'{field}' 필드에 동사 없음. 무엇을 했는지 명시 필요 (예: 수정, 추가, 삭제)"

        # require_target 검사
        if rules.get("require_target") and value:
            if not any(p.search(str(value)) for p in self._compiled_target_patterns):
                return f"'{field}' 필드에 대상 없음. 무엇을 변경했는지 명시 필요 (예: 파일, 함수, 클래스)"

        # require_pattern 검사
        if "require_pattern" in rules and value:
            pattern = re.compile(rules["require_pattern"], re.MULTILINE)
            if not pattern.search(str(value)):
                return f"'{field}' 필드 형식 불일치. 예상 패턴: {rules['require_pattern']}"

        # valid_values 검사
        if "valid_values" in rules:
            if value not in rules["valid_values"]:
                return f"'{field}' 값 '{value}'이 유효하지 않음. 허용값: {rules['valid_values']}"

        # range 검사
        if "range" in rules:
            min_val, max_val = rules["range"]
            try:
                num_val = float(value) if value is not None else None
                if num_val is None or num_val < min_val or num_val > max_val:
                    return f"'{field}' 값 {value}이 범위 밖. 허용범위: {min_val}-{max_val}"
            except (TypeError, ValueError):
                return f"'{field}' 값이 숫자가 아님: {value}"

        # non_empty_if_diff 검사 (coder 전용)
        if rules.get("non_empty_if_diff"):
            diff = full_json.get("diff", "")
            if diff and len(diff.strip()) > 0:
                if not value or len(value) == 0:
                    return f"'{field}' 필드가 비어있음. diff 있으면 변경된 파일 목록 필수"

        # non_empty_if_pass 검사 (qa 전용)
        if rules.get("non_empty_if_pass"):
            verdict = full_json.get("verdict", "")
            if verdict == "PASS":
                if not value or len(value) == 0:
                    return f"'{field}' 필드가 비어있음. PASS 판정이면 테스트 결과 필수"

        # risks_if_reject 검사 (reviewer 전용)
        if rules.get("risks_if_reject"):
            verdict = full_json.get("verdict", "")
            if verdict == "REJECT":
                risks = full_json.get("risks", [])
                if not risks or len(risks) == 0:
                    return "REJECT 판정이면 risks 필드에 이유 필수"

        return None

    def get_error_type(self, error_msg: str) -> str:
        """에러 메시지에서 에러 타입 추출"""
        if "의미적 NULL" in error_msg:
            return "SEMANTIC_NULL"
        elif "너무 짧음" in error_msg:
            return "FIELD_TOO_SHORT"
        elif "동사 없음" in error_msg:
            return "MISSING_VERB"
        elif "대상 없음" in error_msg:
            return "MISSING_TARGET"
        elif "유효하지 않음" in error_msg:
            return "INVALID_VALUE"
        elif "범위 밖" in error_msg:
            return "OUT_OF_RANGE"
        elif "비어있음" in error_msg:
            return "EMPTY_REQUIRED_FIELD"
        else:
            return "SEMANTIC_UNKNOWN"


# 싱글톤 인스턴스
_semantic_guard: Optional[SemanticGuard] = None


def get_semantic_guard() -> SemanticGuard:
    """SemanticGuard 싱글톤"""
    global _semantic_guard
    if _semantic_guard is None:
        _semantic_guard = SemanticGuard()
    return _semantic_guard


# =============================================================================
# Configuration
# =============================================================================

CLI_CONFIG = {
    "timeout_seconds": 300,      # 5분 타임아웃
    "max_retries": 2,            # 최대 재시도 횟수
    "context_recovery_limit": 10, # 복구 시 가져올 최근 메시지 수
    "output_max_chars": 50000,   # 출력 최대 길이
    # v2.4.1: Queue 기반 통제
    "max_concurrent": 2,         # 최대 동시 CLI 실행 수
    "queue_max_size": 10,        # 대기 큐 최대 크기
    "rate_limit_calls": 10,      # 분당 최대 호출 수
    "rate_limit_period": 60,     # Rate limit 기간 (초)
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

# v2.4.2: 프로필별 모델 설정 (API 비용 0원 - CLI만 사용)
# PM/coder/excavator = Opus (고품질 라우팅/코드/분석)
# reviewer/qa/council = Sonnet (빠른 검증)
CLI_PROFILE_MODELS = {
    "pm": "claude-opus-4-5-20251101",         # PM 라우팅 = Opus (v2.4.2)
    "coder": "claude-opus-4-5-20251101",      # 코드 작성 = Opus
    "excavator": "claude-opus-4-5-20251101",  # 의도 발굴 = Opus
    "qa": "claude-sonnet-4-5-20250514",       # QA 검증 = Sonnet 4.5
    "reviewer": "claude-sonnet-4-5-20250514", # 리뷰/검토 = Sonnet 4.5
    "council": "claude-sonnet-4-5-20250514",  # 위원회 = Sonnet 4.5 (v2.4.2)
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

# 세션 충돌 에러 패턴 (세션 리셋 후 재시도)
SESSION_CONFLICT_PATTERNS = [
    r"Session ID .* is already in use",
    r"session.*already.*use",
    r"session.*conflict",
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
    queue_wait_time: float = 0.0  # 큐 대기 시간 (초)
    # v2.5: JSON 검증 관련
    parsed_json: Optional[dict] = None  # 파싱된 JSON (검증 통과 시)
    format_warning: Optional[str] = None  # JSON 검증 실패 경고
    # v2.5.2: 에스컬레이션 관련
    escalation_level: Optional[str] = None  # SELF_REPAIR, ROLE_SWITCH, HARD_FAIL
    role_switched: bool = False  # 역할 전환 여부
    original_profile: Optional[str] = None  # 원래 프로필 (전환 시)


@dataclass
class CLITask:
    """큐에 넣을 CLI 태스크"""
    task_id: str
    prompt: str
    profile: str
    system_prompt: str = ""
    session_id: Optional[str] = None
    task_context: str = ""
    callback: Optional[Callable[[CLIResult], None]] = None
    created_at: float = field(default_factory=time.time)


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """분당 호출 제한"""

    def __init__(self, max_calls: int = 10, period: int = 60):
        self.max_calls = max_calls
        self.period = period
        self.calls: List[float] = []
        self._lock = threading.Lock()

    def can_call(self) -> bool:
        """호출 가능 여부 (True면 호출 가능)"""
        with self._lock:
            now = time.time()
            # 기간 내 호출 기록만 유지
            self.calls = [t for t in self.calls if now - t < self.period]

            if len(self.calls) < self.max_calls:
                self.calls.append(now)
                return True
            return False

    def wait_time(self) -> float:
        """다음 호출까지 대기 시간 (초)"""
        with self._lock:
            if len(self.calls) < self.max_calls:
                return 0.0
            oldest = min(self.calls)
            return max(0.0, self.period - (time.time() - oldest))

    def get_status(self) -> Dict[str, Any]:
        """상태 조회"""
        with self._lock:
            now = time.time()
            active_calls = [t for t in self.calls if now - t < self.period]
            return {
                "calls_in_period": len(active_calls),
                "max_calls": self.max_calls,
                "period_seconds": self.period,
                "available": self.max_calls - len(active_calls),
            }


# =============================================================================
# CLI Queue (동시 실행 제한)
# =============================================================================

class CLIQueue:
    """
    CLI 실행 큐

    - 최대 동시 실행 제한 (Semaphore)
    - 대기 큐 (Queue)
    - 워커 스레드가 순차 처리
    """

    def __init__(
        self,
        max_concurrent: int = 2,
        max_queue_size: int = 10,
        rate_limiter: Optional[RateLimiter] = None
    ):
        self.max_concurrent = max_concurrent
        self.semaphore = threading.Semaphore(max_concurrent)
        self.queue: Queue[CLITask] = Queue(maxsize=max_queue_size)
        self.rate_limiter = rate_limiter or RateLimiter()

        self._active_count = 0
        self._total_processed = 0
        self._lock = threading.Lock()
        self._running = True

        # 결과 저장소 (task_id -> CLIResult)
        self._results: Dict[str, CLIResult] = {}
        self._result_events: Dict[str, threading.Event] = {}

        # 워커 스레드 시작
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
        print(f"[CLIQueue] 시작 (max_concurrent={max_concurrent}, max_queue={max_queue_size})")

    def submit(self, task: CLITask, timeout: float = None) -> CLIResult:
        """
        태스크 제출 (동기 - 결과 대기)

        Args:
            task: CLI 태스크
            timeout: 최대 대기 시간 (초)

        Returns:
            CLIResult
        """
        # 결과 이벤트 생성
        event = threading.Event()
        self._result_events[task.task_id] = event

        try:
            # 큐에 추가 (큐가 꽉 차면 대기)
            self.queue.put(task, timeout=timeout or 60)
            print(f"[CLIQueue] 태스크 추가: {task.task_id} (profile={task.profile}, 대기={self.queue.qsize()})")
        except Exception as e:
            return CLIResult(
                success=False,
                output="",
                error=f"큐 추가 실패: {e}",
                aborted=True,
                abort_reason="QUEUE_FULL"
            )

        # 결과 대기
        wait_timeout = timeout or (CLI_CONFIG["timeout_seconds"] + 60)
        if event.wait(timeout=wait_timeout):
            result = self._results.pop(task.task_id, None)
            if result:
                return result

        return CLIResult(
            success=False,
            output="",
            error="결과 대기 타임아웃",
            aborted=True,
            abort_reason="RESULT_TIMEOUT"
        )

    def submit_async(self, task: CLITask) -> str:
        """
        태스크 비동기 제출 (결과 대기 안 함)

        Returns:
            task_id (나중에 get_result로 조회)
        """
        event = threading.Event()
        self._result_events[task.task_id] = event

        try:
            self.queue.put_nowait(task)
            print(f"[CLIQueue] 비동기 태스크 추가: {task.task_id}")
            return task.task_id
        except Exception as e:
            print(f"[CLIQueue] 큐 꽉 참: {e}")
            return ""

    def get_result(self, task_id: str, timeout: float = None) -> Optional[CLIResult]:
        """비동기 태스크 결과 조회"""
        event = self._result_events.get(task_id)
        if not event:
            return None

        if event.wait(timeout=timeout):
            return self._results.pop(task_id, None)
        return None

    def _worker(self):
        """워커 스레드 - 큐에서 태스크 꺼내서 처리"""
        while self._running:
            try:
                task = self.queue.get(timeout=1)
            except Empty:
                continue

            # Rate limit 체크
            while not self.rate_limiter.can_call():
                wait = self.rate_limiter.wait_time()
                print(f"[CLIQueue] Rate limit 대기: {wait:.1f}초")
                time.sleep(min(wait, 5))

            # Semaphore 획득 (동시 실행 제한)
            self.semaphore.acquire()

            with self._lock:
                self._active_count += 1

            queue_wait_time = time.time() - task.created_at

            try:
                print(f"[CLIQueue] 실행 시작: {task.task_id} (대기시간={queue_wait_time:.1f}초)")

                # 실제 CLI 실행
                result = self._execute_task(task)
                result.queue_wait_time = queue_wait_time

                # 결과 저장
                self._results[task.task_id] = result

                # 콜백 호출
                if task.callback:
                    try:
                        task.callback(result)
                    except Exception as e:
                        print(f"[CLIQueue] 콜백 에러: {e}")

                # 이벤트 시그널
                event = self._result_events.get(task.task_id)
                if event:
                    event.set()

                with self._lock:
                    self._total_processed += 1

            finally:
                with self._lock:
                    self._active_count -= 1
                self.semaphore.release()
                self.queue.task_done()

    def _execute_task(self, task: CLITask) -> CLIResult:
        """태스크 실행 (CLISupervisor 사용)"""
        supervisor = CLISupervisor()
        return supervisor.call_cli(
            prompt=task.prompt,
            system_prompt=task.system_prompt,
            profile=task.profile,
            session_id=task.session_id,
            task_context=task.task_context
        )

    def get_status(self) -> Dict[str, Any]:
        """큐 상태 조회"""
        with self._lock:
            return {
                "queue_size": self.queue.qsize(),
                "active_count": self._active_count,
                "max_concurrent": self.max_concurrent,
                "total_processed": self._total_processed,
                "rate_limiter": self.rate_limiter.get_status(),
            }

    def shutdown(self):
        """종료"""
        self._running = False
        self._worker_thread.join(timeout=5)
        print("[CLIQueue] 종료됨")


# 싱글톤 큐 인스턴스
_cli_queue: Optional[CLIQueue] = None

# v2.4.1: 활성 프로세스 추적 (좀비 방지)
_active_processes: Dict[str, subprocess.Popen] = {}
_process_lock = threading.Lock()


def register_process(task_id: str, proc: subprocess.Popen):
    """프로세스 등록"""
    with _process_lock:
        _active_processes[task_id] = proc


def unregister_process(task_id: str):
    """프로세스 해제"""
    with _process_lock:
        _active_processes.pop(task_id, None)


def kill_zombie_processes(timeout_seconds: int = 600) -> List[str]:
    """좀비 프로세스 강제 종료 (기본 10분 초과)"""
    import psutil
    killed = []

    with _process_lock:
        for task_id, proc in list(_active_processes.items()):
            try:
                # 프로세스 정보 조회
                if proc.poll() is not None:
                    # 이미 종료됨
                    del _active_processes[task_id]
                    continue

                p = psutil.Process(proc.pid)
                elapsed = time.time() - p.create_time()

                if elapsed > timeout_seconds:
                    print(f"[CLISupervisor] 좀비 프로세스 발견: {task_id} (PID={proc.pid}, {elapsed:.0f}초 경과)")
                    proc.kill()
                    proc.wait(timeout=5)
                    del _active_processes[task_id]
                    killed.append(task_id)
            except Exception as e:
                print(f"[CLISupervisor] 프로세스 정리 에러: {e}")

    return killed


def get_active_processes() -> Dict[str, Any]:
    """활성 프로세스 상태 조회"""
    import psutil
    result = []

    with _process_lock:
        for task_id, proc in _active_processes.items():
            try:
                if proc.poll() is None:  # 아직 실행 중
                    p = psutil.Process(proc.pid)
                    result.append({
                        "task_id": task_id,
                        "pid": proc.pid,
                        "elapsed": time.time() - p.create_time(),
                        "memory_mb": p.memory_info().rss / 1024 / 1024,
                    })
            except:
                pass

    return {
        "active_count": len(result),
        "processes": result
    }


def kill_session(session_id: str) -> Dict[str, Any]:
    """
    특정 세션의 CLI 프로세스 강제 종료
    v2.4.3: 중단 버튼용
    """
    killed_tasks = []

    with _process_lock:
        for task_id, proc in list(_active_processes.items()):
            if session_id in task_id:
                try:
                    if proc.poll() is None:
                        print(f"[CLI-Supervisor] 세션 강제 종료: {task_id} (PID={proc.pid})")
                        proc.kill()
                        proc.wait(timeout=3)
                        killed_tasks.append(task_id)
                    del _active_processes[task_id]
                except Exception as e:
                    print(f"[CLI-Supervisor] 프로세스 종료 에러: {e}")

    global _session_registry, _committee_session_registry
    keys_to_remove = [k for k in _session_registry if session_id in k]
    for k in keys_to_remove:
        del _session_registry[k]

    committee_keys = [k for k in _committee_session_registry if session_id in k]
    for k in committee_keys:
        del _committee_session_registry[k]

    return {
        "killed": len(killed_tasks) > 0,
        "task_ids": killed_tasks,
        "session_entries_cleared": len(keys_to_remove) + len(committee_keys),
        "message": f"{len(killed_tasks)}개 프로세스 종료됨" if killed_tasks else "활성 프로세스 없음"
    }


def kill_all_cli_processes() -> Dict[str, Any]:
    """모든 CLI 프로세스 강제 종료 (v2.4.3 긴급 중단용)"""
    killed_tasks = []

    with _process_lock:
        for task_id, proc in list(_active_processes.items()):
            try:
                if proc.poll() is None:
                    print(f"[CLI-Supervisor] 전체 종료: {task_id} (PID={proc.pid})")
                    proc.kill()
                    proc.wait(timeout=3)
                    killed_tasks.append(task_id)
                del _active_processes[task_id]
            except Exception as e:
                print(f"[CLI-Supervisor] 프로세스 종료 에러: {e}")

    reset_all_sessions()

    return {
        "killed_count": len(killed_tasks),
        "task_ids": killed_tasks,
        "message": f"전체 {len(killed_tasks)}개 프로세스 종료됨"
    }


def get_cli_queue() -> CLIQueue:
    """CLI 큐 싱글톤"""
    global _cli_queue
    if _cli_queue is None:
        _cli_queue = CLIQueue(
            max_concurrent=CLI_CONFIG["max_concurrent"],
            max_queue_size=CLI_CONFIG["queue_max_size"],
            rate_limiter=RateLimiter(
                max_calls=CLI_CONFIG["rate_limit_calls"],
                period=CLI_CONFIG["rate_limit_period"]
            )
        )
    return _cli_queue


def reset_all_sessions():
    """
    모든 CLI 세션 초기화 (서버 재시작 시 호출)
    v2.4.2: 세션 충돌 방지
    """
    global _session_registry, _committee_session_registry
    _session_registry.clear()
    _committee_session_registry.clear()
    print("[CLI-Supervisor] 모든 세션 초기화 완료")


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
        Claude Code CLI 호출 (v2.5.2: Retry Escalation 적용)

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
        original_prompt = prompt  # 에스컬레이션용 원본 저장
        original_profile = profile
        current_profile = profile
        escalator = get_retry_escalator()

        # 프롬프트 구성
        full_prompt = self._build_prompt(prompt, system_prompt, profile, task_context)

        while self.retry_count <= self.config["max_retries"]:
            try:
                result = self._execute_cli(full_prompt, current_profile)

                # 성공
                if result.success:
                    # v2.5: JSON 출력 검증
                    is_valid, error_msg, parsed = self._validate_json_output(result.output, current_profile)

                    if is_valid:
                        # v2.5.3: JSON 형식 통과 → Semantic Guard 검증
                        semantic_guard = get_semantic_guard()
                        sem_valid, sem_error = semantic_guard.validate(parsed, current_profile)

                        if sem_valid:
                            # 형식 + 의미 모두 통과
                            result.parsed_json = parsed
                            print(f"[CLI-Supervisor] JSON + Semantic 검증 통과 (profile={current_profile})")

                            # 역할 전환 메타데이터 추가
                            if current_profile != original_profile:
                                result.role_switched = True
                                result.original_profile = original_profile

                            # 성공 시 해당 프로필 히스토리 초기화
                            escalator.clear_history(current_profile)
                            return result
                        else:
                            # v2.5.3: Semantic 검증 실패 → RetryEscalator 편입
                            sem_error_type = semantic_guard.get_error_type(sem_error)
                            print(f"[CLI-Supervisor] Semantic 검증 실패: {sem_error}")

                            signature = escalator.compute_signature(
                                error_type=sem_error_type,
                                missing_fields=[],
                                profile=current_profile,
                                prompt=full_prompt
                            )

                            level = escalator.record_failure(signature)
                            action = escalator.get_escalation_action(
                                level=level,
                                current_profile=current_profile,
                                original_prompt=original_prompt,
                                error_message=sem_error
                            )

                            print(f"[CLI-Supervisor] Semantic 에스컬레이션: {level.name} -> {action['action']}")

                            if action["action"] == "abort":
                                return CLIResult(
                                    success=False,
                                    output=result.output,
                                    error=sem_error,
                                    aborted=True,
                                    abort_reason=f"SEMANTIC_{sem_error_type}",
                                    retry_count=self.retry_count,
                                    escalation_level=level.name,
                                    format_warning=sem_error
                                )

                            elif action["action"] == "switch":
                                current_profile = action["new_profile"]
                                full_prompt = self._build_prompt(
                                    action["modified_prompt"],
                                    system_prompt,
                                    current_profile,
                                    task_context
                                )
                                print(f"[CLI-Supervisor] Semantic 역할 전환: {original_profile} → {current_profile}")
                                self.retry_count += 1
                                continue

                            else:  # retry
                                full_prompt = self._build_prompt(
                                    action["modified_prompt"],
                                    system_prompt,
                                    current_profile,
                                    task_context
                                )
                                self.retry_count += 1
                                continue
                    else:
                        # v2.5.2: JSON 검증 실패 - Retry Escalation 적용
                        missing_fields = self._extract_missing_fields(error_msg)
                        error_type = self._classify_error_type(error_msg)

                        signature = escalator.compute_signature(
                            error_type=error_type,
                            missing_fields=missing_fields,
                            profile=current_profile,
                            prompt=full_prompt
                        )

                        level = escalator.record_failure(signature)
                        action = escalator.get_escalation_action(
                            level=level,
                            current_profile=current_profile,
                            original_prompt=original_prompt,
                            error_message=error_msg
                        )

                        print(f"[CLI-Supervisor] 에스컬레이션: {level.name} -> {action['action']}")

                        if action["action"] == "abort":
                            # Hard Fail - 즉시 중단
                            return CLIResult(
                                success=False,
                                output=result.output,
                                error=error_msg,
                                aborted=True,
                                abort_reason=action.get("error_type", "ESCALATION_HARD_FAIL"),
                                retry_count=self.retry_count,
                                escalation_level=level.name,
                                format_warning=error_msg
                            )

                        elif action["action"] == "switch":
                            # Role Switch - 다른 역할로 전환
                            current_profile = action["new_profile"]
                            full_prompt = self._build_prompt(
                                action["modified_prompt"],
                                system_prompt,
                                current_profile,
                                task_context
                            )
                            print(f"[CLI-Supervisor] 역할 전환: {original_profile} → {current_profile}")
                            self.retry_count += 1
                            continue

                        else:  # retry (Self-repair)
                            # 에러 피드백 포함 재시도 (변형된 프롬프트)
                            full_prompt = self._build_prompt(
                                action["modified_prompt"],
                                system_prompt,
                                current_profile,
                                task_context
                            )
                            self.retry_count += 1
                            continue

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

                # 컨텍스트 초과 감지 - 에스컬레이션 없이 요약 후 재시도
                if self._is_context_overflow(result.error or result.output):
                    print(f"[CLI-Supervisor] 컨텍스트 초과 감지, 세션 리셋 + 요약 후 재시도")
                    self.reset_session(current_profile)
                    summarized_prompt = self._summarize_context(full_prompt, session_id)
                    full_prompt = summarized_prompt
                    self.retry_count += 1
                    continue

                # 세션 충돌 에러 - 에스컬레이션 없이 리셋 후 재시도
                if self._is_session_conflict(result.error or result.output or ""):
                    if self.retry_count < self.config["max_retries"]:
                        print(f"[CLI-Supervisor] 세션 충돌 감지! 세션 리셋 후 재시도")
                        self.reset_session(current_profile)
                        self.retry_count += 1
                        time.sleep(1)
                        continue
                    else:
                        return CLIResult(
                            success=False,
                            output="",
                            error="세션 충돌 지속 (재시도 초과)",
                            aborted=True,
                            abort_reason="SESSION_CONFLICT_MAX_RETRIES"
                        )

                # 치명적 에러 - 에스컬레이션 없이 즉시 실패
                if self._is_fatal_error(result.error or ""):
                    return CLIResult(
                        success=False,
                        output="",
                        error=f"치명적 에러: {result.error}",
                        aborted=True,
                        abort_reason="FATAL_ERROR"
                    )

                # 일반 에러 - Retry Escalation 적용
                signature = escalator.compute_signature(
                    error_type="GENERAL_ERROR",
                    missing_fields=[],
                    profile=current_profile,
                    prompt=full_prompt
                )
                level = escalator.record_failure(signature)

                if level == EscalationLevel.HARD_FAIL:
                    return CLIResult(
                        success=False,
                        output=result.output,
                        error=result.error or "반복 실패",
                        aborted=True,
                        abort_reason="ESCALATION_HARD_FAIL",
                        escalation_level=level.name
                    )

                self.retry_count += 1
                time.sleep(2)
                continue

            except subprocess.TimeoutExpired:
                print(f"[CLI-Supervisor] 타임아웃 ({self.config['timeout_seconds']}초)")

                # 타임아웃도 에스컬레이션 적용
                signature = escalator.compute_signature(
                    error_type="TIMEOUT",
                    missing_fields=[],
                    profile=current_profile,
                    prompt=full_prompt
                )
                level = escalator.record_failure(signature)

                if level == EscalationLevel.HARD_FAIL:
                    return CLIResult(
                        success=False,
                        output="",
                        error=f"타임아웃 반복 ({self.config['timeout_seconds']}초)",
                        aborted=True,
                        abort_reason="TIMEOUT_HARD_FAIL",
                        escalation_level=level.name
                    )

                # 태스크 분할 후 재시도
                print("[CLI-Supervisor] 태스크 분할 시도...")
                full_prompt = self._split_task(full_prompt)
                self.retry_count += 1
                continue

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

    def _extract_missing_fields(self, error_msg: str) -> List[str]:
        """에러 메시지에서 누락된 필드 추출"""
        # "필수 필드 누락: ['summary', 'files_changed']" 패턴 파싱
        match = re.search(r"필수 필드 누락:\s*\[([^\]]+)\]", error_msg)
        if match:
            fields_str = match.group(1)
            fields = [f.strip().strip("'\"") for f in fields_str.split(",")]
            return fields
        return []

    def _classify_error_type(self, error_msg: str) -> str:
        """에러 타입 분류"""
        if "JSON 블록 없음" in error_msg:
            return "NO_JSON_BLOCK"
        elif "JSON 파싱 실패" in error_msg:
            return "JSON_PARSE_ERROR"
        elif "필수 필드 누락" in error_msg:
            return "MISSING_FIELD"
        elif "타임아웃" in error_msg or "timeout" in error_msg.lower():
            return "TIMEOUT"
        else:
            return "UNKNOWN"

    def _execute_cli(self, prompt: str, profile: str) -> CLIResult:
        """실제 CLI 실행 (Popen으로 프로세스 추적)"""
        # Claude Code CLI 명령 구성
        cmd = self._build_cli_command(prompt, profile)
        task_id = f"cli_{int(time.time())}_{uuid.uuid4().hex[:6]}"

        print(f"[CLI-Supervisor] 실행 중... (profile: {profile}, task: {task_id})")

        proc = None
        try:
            # Popen으로 프로세스 시작 (추적 가능)
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=self.working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "CLAUDE_CODE_NONINTERACTIVE": "1"}
            )

            # 프로세스 등록 (좀비 추적용)
            register_process(task_id, proc)

            # 타임아웃 대기
            stdout, stderr = proc.communicate(timeout=self.config["timeout_seconds"])

            output = stdout
            if len(output) > self.config["output_max_chars"]:
                output = output[:self.config["output_max_chars"]] + "\n... (출력 잘림)"

            return CLIResult(
                success=proc.returncode == 0,
                output=output,
                error=stderr if proc.returncode != 0 else None,
                exit_code=proc.returncode,
                retry_count=self.retry_count
            )

        except subprocess.TimeoutExpired:
            # 타임아웃 시 프로세스 강제 종료
            if proc:
                print(f"[CLI-Supervisor] 타임아웃 - 프로세스 강제 종료 (PID={proc.pid})")
                proc.kill()
                proc.wait(timeout=5)
            raise

        finally:
            # 프로세스 해제
            unregister_process(task_id)

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
        """
        v2.5: 프로필별 JSON 강제 규칙

        핵심 원칙:
        - 너는 검증기다. 생성자가 아니다.
        - 반드시 JSON만 출력하라.
        - JSON 외 텍스트 출력 시 즉시 실패로 처리된다.
        """
        rules = {
            "coder": """## 출력 형식 (필수 - JSON만)

반드시 아래 JSON만 출력하라. 다른 텍스트 금지.

```json
{
  "summary": "변경 요약 (3줄 이내)",
  "files_changed": ["path/to/file.py"],
  "diff": "--- a/file.py\\n+++ b/file.py\\n@@ -1,3 +1,4 @@\\n+new line",
  "todo_next": null
}
```

불가능 시:
```json
{"summary": "ABORT: [이유]", "files_changed": [], "diff": "", "todo_next": null}
```

금지: 인사, 설명, 마크다운 헤더, "Let me...", "Here's..."
JSON 외 출력 = 즉시 FAIL""",

            "qa": """## 출력 형식 (필수 - JSON만)

반드시 아래 JSON만 출력하라. 다른 텍스트 금지.

```json
{
  "verdict": "PASS",
  "tests": [{"name": "test_xxx", "result": "PASS", "reason": null}],
  "coverage_summary": "85%",
  "issues_found": []
}
```

verdict: PASS | FAIL | SKIP
불가능 시: {"verdict": "SKIP", "tests": [], "issues_found": ["ABORT: 이유"]}

금지: 설명, 인사, 아키텍처 제안
JSON 외 출력 = 즉시 FAIL""",

            "reviewer": """## 출력 형식 (필수 - JSON만)

반드시 아래 JSON만 출력하라. 다른 텍스트 금지.

```json
{
  "verdict": "APPROVE",
  "risks": [],
  "security_score": 10,
  "approved_files": [],
  "blocked_files": []
}
```

verdict: APPROVE | REVISE | REJECT
risks: [{severity, file, line, issue, fix_suggestion}]

금지: 코드 수정, 스타일 불평, 인사, 설명
JSON 외 출력 = 즉시 FAIL""",

            "council": """## 출력 형식 (필수 - JSON만)

반드시 아래 JSON만 출력하라. 다른 텍스트 금지.

```json
{
  "score": 7.5,
  "reasoning": "판단 이유 (2-3문장)",
  "concerns": ["우려사항"],
  "approvals": ["긍정적인 점"]
}
```

score: 0-10 (소수점 가능)

금지: 설명, 인사
JSON 외 출력 = 즉시 FAIL"""
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

    def _validate_json_output(self, output: str, profile: str) -> tuple[bool, str, dict]:
        """
        v2.5: CLI 출력 JSON 검증

        Args:
            output: CLI 출력
            profile: 프로필 (coder, qa, reviewer, council)

        Returns:
            (valid, error_message, parsed_json)
        """
        import json as json_module

        # 1. JSON 블록 추출 (```json ... ``` 또는 { ... })
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', output)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # { ... } 찾기
            brace_match = re.search(r'\{[\s\S]*\}', output)
            if brace_match:
                json_str = brace_match.group(0).strip()
            else:
                return False, "JSON 블록 없음", {}

        # 2. JSON 파싱
        try:
            parsed = json_module.loads(json_str)
        except json_module.JSONDecodeError as e:
            return False, f"JSON 파싱 실패: {e}", {}

        # 3. 프로필별 필수 필드 검증
        required_fields = {
            "coder": ["summary", "files_changed", "diff"],
            "qa": ["verdict", "tests"],
            "reviewer": ["verdict", "security_score"],
            "council": ["score", "reasoning"]
        }

        fields = required_fields.get(profile, [])
        missing = [f for f in fields if f not in parsed]
        if missing:
            return False, f"필수 필드 누락: {missing}", parsed

        return True, "", parsed

    def _is_valid_cli_output(self, output: str, profile: str) -> bool:
        """
        v2.5: CLI 출력이 유효한 JSON인지 빠른 체크

        Returns:
            True if valid JSON output
        """
        valid, _, _ = self._validate_json_output(output, profile)
        return valid

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

    def _is_session_conflict(self, text: str) -> bool:
        """세션 충돌 에러 감지 (v2.4.2)"""
        for pattern in SESSION_CONFLICT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
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
# Queue-based API (v2.4.1)
# =============================================================================

def call_cli_queued(
    messages: List[Dict[str, str]],
    system_prompt: str = "",
    profile: str = "coder",
    session_id: str = None,
    use_queue: bool = True
) -> str:
    """
    Queue를 통한 CLI 호출 (동시 실행 제한)

    Args:
        messages: 메시지 리스트
        system_prompt: 시스템 프롬프트
        profile: 프로필
        session_id: 세션 ID
        use_queue: False면 직접 호출 (기존 방식)

    Returns:
        응답 문자열
    """
    if not use_queue:
        return call_claude_cli(messages, system_prompt, profile, session_id)

    # 마지막 사용자 메시지 추출
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break

    if not user_message:
        return "# ABORT: 사용자 메시지 없음"

    # 컨텍스트 구성
    context_parts = []
    recent_messages = messages[-6:-1] if len(messages) > 5 else messages[:-1]
    for msg in recent_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")[:1000]
        context_parts.append(f"[{role.upper()}]\n{content}\n[/{role.upper()}]")
    task_context = "\n\n".join(context_parts) if context_parts else ""

    # 태스크 생성
    task = CLITask(
        task_id=f"cli_{int(time.time())}_{uuid.uuid4().hex[:8]}",
        prompt=user_message,
        profile=profile,
        system_prompt=system_prompt,
        session_id=session_id,
        task_context=task_context
    )

    # 큐에 제출 (결과 대기)
    queue = get_cli_queue()
    result = queue.submit(task)

    # 결과 처리
    if result.success:
        return result.output

    if result.aborted:
        return f"""# ABORT: {result.abort_reason}

---
**CLI Queue 보고**:
- 큐 대기 시간: {result.queue_wait_time:.1f}초
- 재시도 횟수: {result.retry_count}
- 에러: {result.error or 'N/A'}

PM에게 태스크 재정의 또는 분할을 요청하세요."""

    return f"""# ABORT: CLI 실행 실패

**에러**: {result.error}
**Exit Code**: {result.exit_code}

출력:
{result.output[:2000] if result.output else '(없음)'}"""


def get_queue_status() -> Dict[str, Any]:
    """CLI 큐 상태 조회"""
    queue = get_cli_queue()
    return queue.get_status()


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
