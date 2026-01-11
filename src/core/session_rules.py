"""
Hattz Empire - Session Rules System v1.0
세션별 규정 관리 + Reviewer 무기화

CEO 가이드라인에 따른 설계:
1. Constitution (헌법): 절대 금지 - 변경 불가
2. Session Rules (세션 규정): 헌법 안에서 활동 범위 조정
3. Reviewer: Safety → Rules → Quality 순서로 검증
4. Audit Log: rules_hash + violations 기록
"""
import json
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# =============================================================================
# CONSTITUTION (헌법) - 절대 금지, 어떤 세션에서도 우회 불가
# =============================================================================

CONSTITUTION = """
# Hattz Empire Constitution (헌법)
## 절대 금지 사항 - 어떤 세션 규정으로도 우회 불가

### 1. 보안 (Security)
- API 키, 비밀번호, 토큰을 코드에 하드코딩 금지
- 사용자 인증/권한 검사 우회 금지
- SQL 인젝션, XSS, 명령어 삽입 취약점 생성 금지

### 2. 시스템 무결성 (System Integrity)
- 무한 루프로 API 호출 반복 금지
- 로그 삭제/조작 금지
- Circuit Breaker 우회 금지
- 타임아웃 없는 외부 API 호출 금지

### 3. 윤리 (Ethics)
- 불법 활동 지원 금지
- 개인정보 무단 수집/유출 금지
- 시스템 악용 금지

### 위반 시
Constitution 위반은 즉시 REJECT + 관리자 알림
"""


# =============================================================================
# Session Rules Schema
# =============================================================================

@dataclass
class CodeRules:
    """코드 작성 관련 규정"""
    forbid_sleep_in_api_loop: bool = True
    require_rate_limit_guard: bool = True
    secrets_hardcoding: str = "forbid"  # "forbid", "warn"
    require_type_hints: bool = True
    require_docstrings: bool = True
    forbid_print_debug: bool = False  # 개발 중에는 허용


@dataclass
class QualityRules:
    """품질 관련 규정"""
    allow_skip_tests: bool = False
    skip_tests_conditions: List[str] = field(default_factory=list)  # ["docs_only", "comments_only"]
    max_files_changed: int = 12
    require_review_before_merge: bool = True
    max_complexity: int = 15  # Cyclomatic complexity


@dataclass
class SessionRules:
    """세션 규정 전체"""
    session_id: str
    mode: str = "dev"
    risk_profile: str = "normal"
    code: CodeRules = field(default_factory=CodeRules)
    quality: QualityRules = field(default_factory=QualityRules)
    overrides: List[str] = field(default_factory=list)  # 추가 예외 사항
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    created_by: str = "pm"

    def to_json(self) -> str:
        """JSON 문자열로 변환"""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def get_hash(self) -> str:
        """규정의 해시값 생성 (감사 추적용)"""
        json_str = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]

    @classmethod
    def from_json(cls, json_str: str) -> "SessionRules":
        """JSON에서 SessionRules 생성"""
        data = json.loads(json_str)
        return cls(
            session_id=data.get("session_id", "unknown"),
            mode=data.get("mode", "dev"),
            risk_profile=data.get("risk_profile", "normal"),
            code=CodeRules(**data.get("code", {})),
            quality=QualityRules(**{k: v for k, v in data.get("quality", {}).items()
                                   if k in QualityRules.__dataclass_fields__}),
            overrides=data.get("overrides", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
            created_by=data.get("created_by", "pm"),
        )


# =============================================================================
# Preset Rules (사전 정의된 규정)
# =============================================================================

PRESET_RULES = {
    # 개발 모드 (기본)
    "dev": SessionRules(
        session_id="dev",
        mode="dev",
        risk_profile="normal",
        code=CodeRules(
            forbid_sleep_in_api_loop=True,
            require_rate_limit_guard=False,
            forbid_print_debug=False,
        ),
        quality=QualityRules(
            allow_skip_tests=False,
            skip_tests_conditions=["docs_only", "comments_only", "config_only"],
            max_files_changed=20,
            require_review_before_merge=False,
        ),
    ),
}


def get_preset_rules(preset_name: str) -> Optional[SessionRules]:
    """사전 정의된 규정 가져오기"""
    return PRESET_RULES.get(preset_name)


# =============================================================================
# Reviewer Checklist
# =============================================================================

class ViolationSeverity(Enum):
    CRITICAL = "critical"  # Constitution 위반 - 즉시 REJECT
    HIGH = "high"          # 핵심 규정 위반
    MEDIUM = "medium"      # 일반 규정 위반
    LOW = "low"            # 권장 사항 위반


@dataclass
class Violation:
    """규정 위반 항목"""
    rule_key: str           # 위반한 규정 키 (예: "trading.market_order")
    severity: ViolationSeverity
    description: str
    evidence: str           # 파일:라인 또는 구체적 증거
    suggested_fix: str


@dataclass
class ReviewResult:
    """Reviewer 검토 결과"""
    verdict: str            # "PASS", "REJECT"
    violations: List[Violation]
    notes: List[str]
    rules_hash: str
    reviewed_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "violations": [
                {
                    "rule_key": v.rule_key,
                    "severity": v.severity.value,
                    "description": v.description,
                    "evidence": v.evidence,
                    "suggested_fix": v.suggested_fix,
                }
                for v in self.violations
            ],
            "notes": self.notes,
            "rules_hash": self.rules_hash,
            "reviewed_at": self.reviewed_at,
        }


# =============================================================================
# Reviewer Prompt Template
# =============================================================================

def build_reviewer_prompt(
    task: str,
    worker_output: str,
    session_rules: SessionRules,
    diff_summary: str = "",
    test_results: str = "",
) -> str:
    """
    Reviewer용 프롬프트 생성

    CEO 가이드라인:
    1. Safety/Integrity (secrets, live-trade risk, infinite loops, API abuse)
    2. Session Rules compliance
    3. Change Quality (scope creep, missing rollback, regression risk)
    """
    rules_json = session_rules.to_json()
    rules_hash = session_rules.get_hash()

    return f"""[ROLE]
You are the Reviewer/Gatekeeper. You must enforce Constitution + Session Rules.
If any violation exists, you must output REJECT.

[CONSTITUTION]
{CONSTITUTION}

[SESSION RULES (JSON)]
{rules_json}

Rules Hash: {rules_hash}

[TASK]
{task}

[WORKER OUTPUT]
{worker_output}

[DIFF/FILES CHANGED]
{diff_summary if diff_summary else "(not provided)"}

[TEST RESULTS]
{test_results if test_results else "(not provided)"}

[CHECK ORDER - MUST FOLLOW]
1) Safety/Integrity (secrets, infinite loops, API abuse)
   - API keys hardcoded? → CRITICAL REJECT
   - Infinite loop without break? → CRITICAL REJECT

2) Session Rules compliance
   - Check each rule in the JSON
   - mode={session_rules.mode}, risk_profile={session_rules.risk_profile}
   - code.secrets_hardcoding={session_rules.code.secrets_hardcoding}
   - quality.allow_skip_tests={session_rules.quality.allow_skip_tests}

3) Change Quality (scope creep, missing rollback, regression risk)
   - Files changed > max_files_changed ({session_rules.quality.max_files_changed})? → HIGH
   - Logic change without tests (unless skip allowed)? → MEDIUM

[OUTPUT FORMAT — MUST FOLLOW EXACTLY]
```json
{{
  "verdict": "PASS" | "REJECT",
  "violations": [
    {{
      "rule_key": "code.secrets_hardcoding" | "constitution.secrets" | etc,
      "severity": "critical" | "high" | "medium" | "low",
      "description": "What was violated",
      "evidence": "file:line or specific evidence",
      "suggested_fix": "How to fix"
    }}
  ],
  "notes": [
    "Optional observations"
  ],
  "rules_hash": "{rules_hash}"
}}
```

CRITICAL/HIGH violations → REJECT
Only LOW violations → may PASS with warnings
Empty violations → PASS
"""


# =============================================================================
# Audit Log Functions
# =============================================================================

def create_audit_log(
    session_id: str,
    task_id: str,
    rules: SessionRules,
    review_result: ReviewResult,
    agent_role: str = "reviewer",
) -> Dict[str, Any]:
    """감사 로그 생성 (DB 저장용)"""
    return {
        "session_id": session_id,
        "task_id": task_id,
        "rules_hash": rules.get_hash(),
        "rules_mode": rules.mode,
        "rules_risk_profile": rules.risk_profile,
        "verdict": review_result.verdict,
        "violation_count": len(review_result.violations),
        "critical_count": sum(1 for v in review_result.violations
                              if v.severity == ViolationSeverity.CRITICAL),
        "violations_json": json.dumps(review_result.to_dict()["violations"], ensure_ascii=False),
        "agent_role": agent_role,
        "reviewed_at": review_result.reviewed_at,
    }


def save_audit_log(audit_log: Dict[str, Any]) -> bool:
    """감사 로그 DB 저장"""
    try:
        from src.services.database import get_db_connection

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 테이블 생성 (없으면)
            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'session_rules_audit')
                BEGIN
                    CREATE TABLE session_rules_audit (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        session_id VARCHAR(50),
                        task_id VARCHAR(100),
                        rules_hash VARCHAR(32),
                        rules_mode VARCHAR(20),
                        rules_risk_profile VARCHAR(20),
                        verdict VARCHAR(10),
                        violation_count INT DEFAULT 0,
                        critical_count INT DEFAULT 0,
                        violations_json NVARCHAR(MAX),
                        agent_role VARCHAR(30),
                        reviewed_at DATETIME,
                        created_at DATETIME DEFAULT GETDATE()
                    )
                END
            """)

            # 로그 삽입
            cursor.execute("""
                INSERT INTO session_rules_audit
                (session_id, task_id, rules_hash, rules_mode, rules_risk_profile,
                 verdict, violation_count, critical_count, violations_json,
                 agent_role, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                audit_log["session_id"],
                audit_log["task_id"],
                audit_log["rules_hash"],
                audit_log["rules_mode"],
                audit_log["rules_risk_profile"],
                audit_log["verdict"],
                audit_log["violation_count"],
                audit_log["critical_count"],
                audit_log["violations_json"],
                audit_log["agent_role"],
                audit_log["reviewed_at"],
            ))
            conn.commit()
            return True
    except Exception as e:
        print(f"[SessionRules] Audit log save failed: {e}")
        return False


# =============================================================================
# Helper Functions
# =============================================================================

def get_current_rules(session_id: str) -> SessionRules:
    """
    현재 세션의 규정 가져오기

    TODO: DB에서 세션별 규정 조회
    현재는 기본 dev 규정 반환
    """
    return get_preset_rules("dev")


def parse_reviewer_output(output: str) -> Optional[ReviewResult]:
    """
    Reviewer 출력에서 ReviewResult 파싱

    JSON 블록을 찾아 파싱
    """
    import re

    # JSON 블록 찾기
    json_patterns = [
        r'```json\s*(\{.*?\})\s*```',  # markdown code block
        r'(\{[^{}]*"verdict"[^{}]*\})',  # inline JSON (간단한 경우)
    ]

    for pattern in json_patterns:
        match = re.search(pattern, output, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                violations = [
                    Violation(
                        rule_key=v.get("rule_key", "unknown"),
                        severity=ViolationSeverity(v.get("severity", "medium")),
                        description=v.get("description", ""),
                        evidence=v.get("evidence", ""),
                        suggested_fix=v.get("suggested_fix", ""),
                    )
                    for v in data.get("violations", [])
                ]
                return ReviewResult(
                    verdict=data.get("verdict", "REJECT"),
                    violations=violations,
                    notes=data.get("notes", []),
                    rules_hash=data.get("rules_hash", ""),
                )
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"[SessionRules] Parse error: {e}")
                continue

    # Fallback: 텍스트에서 PASS/REJECT 찾기
    if "PASS" in output.upper() and "REJECT" not in output.upper():
        return ReviewResult(
            verdict="PASS",
            violations=[],
            notes=["Parsed from text (no JSON found)"],
            rules_hash="",
        )
    elif "REJECT" in output.upper():
        return ReviewResult(
            verdict="REJECT",
            violations=[
                Violation(
                    rule_key="unknown",
                    severity=ViolationSeverity.HIGH,
                    description="Rejection reason not parsed",
                    evidence="See raw output",
                    suggested_fix="Check reviewer output",
                )
            ],
            notes=["Parsed from text (no JSON found)"],
            rules_hash="",
        )

    return None


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    # 테스트: 규정 생성 및 프롬프트 생성
    rules = get_preset_rules("live_strict")
    print(f"Rules Hash: {rules.get_hash()}")
    print(f"Rules JSON:\n{rules.to_json()}")

    prompt = build_reviewer_prompt(
        task="Add market order function",
        worker_output="def execute_market_order(symbol, qty): ...",
        session_rules=rules,
    )
    print(f"\nReviewer Prompt (first 1000 chars):\n{prompt[:1000]}...")
