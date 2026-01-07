"""
Hattz Empire - Output Contracts (v2.5)
LLM 출력 형식 강제 + 형식 게이트

핵심 원칙:
- LLM은 자유가 없다
- Pydantic = 회사 양식
- 파싱 실패 = 즉시 재시도 (PM까지 안 감)
- "응답 형식 오류"라는 말 자체가 사라져야 함
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from enum import Enum
import json
import re


# =============================================================================
# Verdict Enums
# =============================================================================

class Verdict(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


# =============================================================================
# CODER Output Contract
# =============================================================================

class CoderOutput(BaseModel):
    """코더 출력 계약 - diff + 변경 요약"""
    summary: str = Field(..., description="변경 요약, 3줄 이내", max_length=500)
    files_changed: List[str] = Field(..., description="변경된 파일 경로 목록")
    diff: str = Field(..., description="unified diff 형식")
    todo_next: Optional[str] = Field(None, description="다음 단계 힌트 (선택)")

    class Config:
        json_schema_extra = {
            "example": {
                "summary": "로그인 API 버그 수정",
                "files_changed": ["src/api/auth.py"],
                "diff": "--- a/src/api/auth.py\n+++ b/src/api/auth.py\n@@ -10,3 +10,4 @@\n+    return jsonify({'ok': True})",
                "todo_next": None
            }
        }


# =============================================================================
# QA Output Contract
# =============================================================================

class TestCase(BaseModel):
    """개별 테스트 케이스"""
    name: str = Field(..., description="테스트 이름")
    result: TestResult
    reason: Optional[str] = Field(None, description="실패 시 이유")


class QAOutput(BaseModel):
    """QA 출력 계약 - 테스트 결과 + 커버리지"""
    verdict: TestResult = Field(..., description="전체 판정: PASS/FAIL/SKIP")
    tests: List[TestCase] = Field(..., description="개별 테스트 결과")
    coverage_summary: Optional[str] = Field(None, description="커버리지 요약")
    issues_found: List[str] = Field(default_factory=list, description="발견된 이슈 목록")

    class Config:
        json_schema_extra = {
            "example": {
                "verdict": "PASS",
                "tests": [
                    {"name": "test_login", "result": "PASS", "reason": None},
                    {"name": "test_logout", "result": "PASS", "reason": None}
                ],
                "coverage_summary": "85% (34/40 lines)",
                "issues_found": []
            }
        }


# =============================================================================
# REVIEWER Output Contract
# =============================================================================

class Risk(BaseModel):
    """리스크 항목"""
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    file: str
    line: Optional[int] = None
    issue: str
    fix_suggestion: Optional[str] = None


class ReviewerOutput(BaseModel):
    """리뷰어 출력 계약 - 승인/거부 + 리스크 목록"""
    verdict: Verdict = Field(..., description="APPROVE/REVISE/REJECT")
    risks: List[Risk] = Field(default_factory=list, description="발견된 리스크")
    security_score: int = Field(..., ge=0, le=10, description="보안 점수 0-10")
    approved_files: List[str] = Field(default_factory=list)
    blocked_files: List[str] = Field(default_factory=list)

    class Config:
        json_schema_extra = {
            "example": {
                "verdict": "APPROVE",
                "risks": [],
                "security_score": 9,
                "approved_files": ["src/api/auth.py"],
                "blocked_files": []
            }
        }


# =============================================================================
# STRATEGIST Output Contract
# =============================================================================

class Option(BaseModel):
    """전략 옵션"""
    name: str
    pros: List[str]
    cons: List[str]
    effort: Literal["LOW", "MEDIUM", "HIGH"]
    risk: Literal["LOW", "MEDIUM", "HIGH"]


class StrategistOutput(BaseModel):
    """전략가 출력 계약 - 옵션 분석 + 추천"""
    problem_summary: str = Field(..., description="문제 요약, 2문장 이내")
    options: List[Option] = Field(..., min_length=2, max_length=4)
    recommendation: str = Field(..., description="추천 옵션 이름")
    reasoning: str = Field(..., description="추천 이유, 3문장 이내")

    class Config:
        json_schema_extra = {
            "example": {
                "problem_summary": "인증 시스템 리팩토링 필요",
                "options": [
                    {"name": "JWT 도입", "pros": ["확장성"], "cons": ["복잡도"], "effort": "MEDIUM", "risk": "LOW"},
                    {"name": "세션 유지", "pros": ["단순"], "cons": ["확장 한계"], "effort": "LOW", "risk": "LOW"}
                ],
                "recommendation": "JWT 도입",
                "reasoning": "확장성이 중요하므로 JWT를 추천합니다."
            }
        }


# =============================================================================
# PM Output Contract
# =============================================================================

class TaskSpec(BaseModel):
    """PM이 생성하는 태스크 스펙"""
    task_id: str = Field(..., description="태스크 ID")
    agent: Literal["coder", "qa", "reviewer", "strategist", "analyst", "researcher"]
    instruction: str = Field(..., description="에이전트에게 전달할 지시")
    context: Optional[str] = Field(None, description="추가 컨텍스트")
    priority: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"


class PMOutput(BaseModel):
    """
    PM 출력 계약 - 라우팅 결정 + 태스크 생성

    v2.5.1: 필드 축소 + 길이 제한
    - PM은 판단만, 설명은 짧게
    - summary 100자 제한 (시인 되는 거 방지)
    """
    action: Literal["DISPATCH", "ESCALATE", "DONE"] = Field(..., description="다음 액션")
    tasks: List[TaskSpec] = Field(default_factory=list, description="생성된 태스크 목록 (DISPATCH일 때)")
    summary: str = Field(..., description="CEO 보고 요약 (100자 이내)", max_length=100)
    requires_ceo: bool = Field(False, description="CEO 승인 필요 여부")

    class Config:
        json_schema_extra = {
            "example": {
                "action": "DISPATCH",
                "tasks": [
                    {"task_id": "T001", "agent": "coder", "instruction": "로그인 버그 수정", "priority": "HIGH"}
                ],
                "summary": "coder에게 로그인 버그 수정 할당",
                "requires_ceo": False
            }
        }


# =============================================================================
# COUNCIL Output Contract (위원회 개별 멤버)
# =============================================================================

class CouncilMemberOutput(BaseModel):
    """위원회 멤버 출력 계약"""
    score: float = Field(..., ge=0, le=10, description="점수 0-10")
    reasoning: str = Field(..., description="판단 이유, 2-3문장")
    concerns: List[str] = Field(default_factory=list, description="우려사항")
    approvals: List[str] = Field(default_factory=list, description="긍정적인 점")


# =============================================================================
# DOCUMENTOR Output Contract (문서화)
# =============================================================================

class DocumentorOutput(BaseModel):
    """문서 작성자 출력 계약 - 커밋 메시지 + 변경 요약"""
    commit_type: Literal["feat", "fix", "docs", "refactor", "test", "chore"]
    commit_message: str = Field(..., description="한 줄 커밋 메시지, 50자 이내")
    change_summary: str = Field(..., description="변경 사항 요약, 3문장 이내")
    files_affected: List[str] = Field(..., description="영향받은 파일 목록")
    breaking_change: bool = Field(False, description="하위 호환성 깨지는 변경인지")

    class Config:
        json_schema_extra = {
            "example": {
                "commit_type": "feat",
                "commit_message": "Add FormatGate to enforce output contracts",
                "change_summary": "LLM 출력 형식 검증 게이트 추가. 실패 시 재시도 또는 예외 발생.",
                "files_affected": ["src/core/contracts.py", "src/core/llm_caller.py"],
                "breaking_change": False
            }
        }


# =============================================================================
# Contract Registry
# =============================================================================

CONTRACT_REGISTRY = {
    "coder": CoderOutput,
    "qa": QAOutput,
    "reviewer": ReviewerOutput,
    "strategist": StrategistOutput,
    "pm": PMOutput,
    "council": CouncilMemberOutput,
    "documentor": DocumentorOutput,
}


def get_contract(agent_role: str) -> type[BaseModel]:
    """에이전트 역할에 맞는 계약 반환"""
    return CONTRACT_REGISTRY.get(agent_role)


def get_schema_prompt(agent_role: str) -> str:
    """에이전트에게 주입할 스키마 프롬프트 생성"""
    contract = get_contract(agent_role)
    if not contract:
        return ""

    schema = contract.model_json_schema()
    example = contract.Config.json_schema_extra.get("example", {}) if hasattr(contract.Config, "json_schema_extra") else {}

    return f"""## 출력 형식 (필수)

반드시 아래 JSON 스키마만 출력하라.
설명, 마크다운, 주석, 여분 텍스트 금지.

### 스키마
```json
{json.dumps(schema, ensure_ascii=False, indent=2)}
```

### 예시
```json
{json.dumps(example, ensure_ascii=False, indent=2)}
```

규칙:
- JSON만 출력
- 스키마 필드 정확히 매칭
- 누락/추가 필드 금지
"""


# =============================================================================
# Format Gate (핵심)
# =============================================================================

def extract_json_from_output(raw: str) -> str:
    """LLM 출력에서 JSON 부분만 추출"""
    # 1. ```json ... ``` 블록 찾기
    json_block = re.search(r'```json\s*([\s\S]*?)\s*```', raw)
    if json_block:
        return json_block.group(1).strip()

    # 2. { ... } 찾기
    brace_match = re.search(r'\{[\s\S]*\}', raw)
    if brace_match:
        return brace_match.group(0).strip()

    # 3. 그대로 반환
    return raw.strip()


def run_with_contract(
    llm_call: callable,
    agent_role: str,
    max_retry: int = 3,
    on_retry: callable = None
) -> BaseModel:
    """
    형식 게이트: LLM 호출 + 계약 검증

    Args:
        llm_call: LLM 호출 함수 (str 반환)
        agent_role: 에이전트 역할
        max_retry: 최대 재시도 횟수
        on_retry: 재시도 시 호출할 콜백 (error_msg를 받음)

    Returns:
        검증된 Pydantic 모델

    Raises:
        FormatGateError: 최대 재시도 초과 시
    """
    contract = get_contract(agent_role)
    if not contract:
        # 계약 없는 에이전트는 raw string 반환
        return llm_call()

    last_error = None

    for attempt in range(max_retry):
        raw = llm_call()

        try:
            # JSON 추출
            json_str = extract_json_from_output(raw)

            # Pydantic 검증
            validated = contract.model_validate_json(json_str)
            return validated

        except Exception as e:
            last_error = str(e)
            print(f"[FormatGate] 파싱 실패 ({attempt + 1}/{max_retry}): {last_error[:100]}")

            if on_retry:
                on_retry(last_error)

    raise FormatGateError(f"FORMAT_GATE_FAIL ({agent_role}): {last_error}")


class FormatGateError(Exception):
    """형식 게이트 실패 예외"""
    pass


# =============================================================================
# Validation Helper
# =============================================================================

def validate_output(raw: str, agent_role: str) -> tuple[bool, BaseModel | str, str | None]:
    """
    출력 검증 헬퍼

    Returns:
        (success, validated_or_raw, error_message)
    """
    contract = get_contract(agent_role)
    if not contract:
        return True, raw, None

    try:
        json_str = extract_json_from_output(raw)
        validated = contract.model_validate_json(json_str)
        return True, validated, None
    except Exception as e:
        return False, raw, str(e)


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    print("=== Output Contract Test ===\n")

    # CODER 테스트
    coder_json = '''
    {
        "summary": "로그인 버그 수정",
        "files_changed": ["src/api/auth.py"],
        "diff": "--- a/src/api/auth.py\\n+++ b/src/api/auth.py\\n@@ -10,3 +10,4 @@\\n+    return jsonify({'ok': True})"
    }
    '''
    success, result, error = validate_output(coder_json, "coder")
    print(f"CODER: success={success}, error={error}")
    if success:
        print(f"  summary: {result.summary}")

    # QA 테스트
    qa_json = '''
    {
        "verdict": "PASS",
        "tests": [
            {"name": "test_login", "result": "PASS"}
        ],
        "issues_found": []
    }
    '''
    success, result, error = validate_output(qa_json, "qa")
    print(f"QA: success={success}, error={error}")

    # 잘못된 형식 테스트
    bad_json = "이건 JSON이 아닙니다"
    success, result, error = validate_output(bad_json, "coder")
    print(f"BAD: success={success}, error={error[:50]}...")

    print("\n=== Schema Prompt ===")
    print(get_schema_prompt("coder")[:500])
