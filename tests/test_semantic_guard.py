"""
Semantic Guard 단위 테스트 (v2.5.3)

SemanticGuard 클래스를 인라인으로 복사하여 독립적으로 테스트
(config.py 의존성 회피)
"""
import pytest
import re
import json
from typing import Optional, Any


# =============================================================================
# SemanticGuard 클래스 (cli_supervisor.py에서 복사)
# =============================================================================

class SemanticGuard:
    """코드 기반 의미 검증 (LLM 없이)"""

    SEMANTIC_NULL_PATTERNS = [
        r"검토했습니다", r"확인했습니다", r"문제.*없습니다",
        r"추가.*확인.*필요", r"이상.*없음", r"정상.*처리",
        r"완료.*되었습니다", r"진행.*하겠습니다", r"살펴보겠습니다",
        r"looks good", r"no issues", r"seems fine", r"will proceed",
        r"I have reviewed", r"I checked", r"everything is fine", r"no problems found",
    ]

    SEMANTIC_RULES = {
        "coder": {
            "summary": {"min_length": 10, "require_verb": True, "require_target": True},
            "diff": {"min_length": 20, "require_pattern": r"^[-+@]"},
            "files_changed": {"non_empty_if_diff": True}
        },
        "qa": {
            "verdict": {"valid_values": ["PASS", "FAIL", "SKIP"]},
            "tests": {"non_empty_if_pass": True}
        },
        "reviewer": {
            "verdict": {"valid_values": ["APPROVE", "REVISE", "REJECT"]},
            "security_score": {"range": (0, 10)},
            "risks_if_reject": True,
        },
        "council": {
            "score": {"range": (0, 10)},
            "reasoning": {"min_length": 20}
        }
    }

    VERB_PATTERNS = [
        r"수정", r"추가", r"삭제", r"변경", r"생성", r"구현", r"적용",
        r"리팩토링", r"개선", r"업데이트", r"fix", r"add", r"remove",
        r"update", r"create", r"implement", r"refactor"
    ]

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

    def validate(self, parsed_json: dict, profile: str) -> tuple:
        full_text = json.dumps(parsed_json, ensure_ascii=False)
        null_error = self._check_semantic_null(full_text)
        if null_error:
            return False, null_error

        rules = self.SEMANTIC_RULES.get(profile, {})
        for field, field_rules in rules.items():
            value = parsed_json.get(field)
            field_error = self._check_field_rules(field, value, field_rules, parsed_json)
            if field_error:
                return False, field_error

        return True, ""

    def _check_semantic_null(self, text: str) -> Optional[str]:
        for pattern in self._compiled_null_patterns:
            if pattern.search(text):
                return f"의미적 NULL 감지: '{pattern.pattern}' 패턴 발견"
        return None

    def _check_field_rules(self, field: str, value: Any, rules: dict, full_json: dict) -> Optional[str]:
        if "min_length" in rules:
            if value is None or len(str(value)) < rules["min_length"]:
                return f"'{field}' 필드 너무 짧음 (최소 {rules['min_length']}자)"

        if rules.get("require_verb") and value:
            if not any(p.search(str(value)) for p in self._compiled_verb_patterns):
                return f"'{field}' 필드에 동사 없음"

        if rules.get("require_target") and value:
            if not any(p.search(str(value)) for p in self._compiled_target_patterns):
                return f"'{field}' 필드에 대상 없음"

        if "require_pattern" in rules and value:
            pattern = re.compile(rules["require_pattern"], re.MULTILINE)
            if not pattern.search(str(value)):
                return f"'{field}' 필드 형식 불일치"

        if "valid_values" in rules:
            if value not in rules["valid_values"]:
                return f"'{field}' 값 '{value}'이 유효하지 않음"

        if "range" in rules:
            min_val, max_val = rules["range"]
            try:
                num_val = float(value) if value is not None else None
                if num_val is None or num_val < min_val or num_val > max_val:
                    return f"'{field}' 값 {value}이 범위 밖"
            except (TypeError, ValueError):
                return f"'{field}' 값이 숫자가 아님"

        if rules.get("non_empty_if_diff"):
            diff = full_json.get("diff", "")
            if diff and len(diff.strip()) > 0:
                if not value or len(value) == 0:
                    return f"'{field}' 필드가 비어있음"

        if rules.get("non_empty_if_pass"):
            verdict = full_json.get("verdict", "")
            if verdict == "PASS":
                if not value or len(value) == 0:
                    return f"'{field}' 필드가 비어있음"

        if rules.get("risks_if_reject"):
            verdict = full_json.get("verdict", "")
            if verdict == "REJECT":
                risks = full_json.get("risks", [])
                if not risks or len(risks) == 0:
                    return "REJECT면 risks 필수"

        return None

    def get_error_type(self, error_msg: str) -> str:
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


# =============================================================================
# 테스트 클래스
# =============================================================================

class TestSemanticGuard:
    """SemanticGuard 테스트"""

    def setup_method(self):
        self.guard = SemanticGuard()

    # =========================================================================
    # Semantic NULL 패턴 테스트
    # =========================================================================

    def test_semantic_null_korean(self):
        """한글 의미적 NULL 감지"""
        bad_output = {"summary": "검토했습니다", "diff": "", "files_changed": []}
        valid, error = self.guard.validate(bad_output, "coder")
        assert not valid
        assert "의미적 NULL" in error

    def test_semantic_null_english(self):
        """영어 의미적 NULL 감지"""
        bad_output = {"verdict": "APPROVE", "risks": [], "security_score": 9,
                      "reasoning": "looks good, no issues found"}
        valid, error = self.guard.validate(bad_output, "reviewer")
        assert not valid
        assert "의미적 NULL" in error

    def test_semantic_null_pass_good_content(self):
        """의미 있는 내용은 통과"""
        good_output = {
            "summary": "로그인 함수의 토큰 검증 로직을 수정함",
            "diff": "--- a/auth.py\n+++ b/auth.py\n@@ -10,3 +10,4 @@\n+    return True",
            "files_changed": ["auth.py"]
        }
        valid, error = self.guard.validate(good_output, "coder")
        assert valid, f"에러: {error}"

    # =========================================================================
    # CODER 프로필 테스트
    # =========================================================================

    def test_coder_summary_too_short(self):
        """coder summary 최소 길이"""
        bad_output = {"summary": "fix", "diff": "", "files_changed": []}
        valid, error = self.guard.validate(bad_output, "coder")
        assert not valid
        assert "너무 짧음" in error

    def test_coder_summary_no_verb(self):
        """coder summary에 동사 없음"""
        bad_output = {
            "summary": "auth.py 파일 내용 검토",
            "diff": "",
            "files_changed": []
        }
        valid, error = self.guard.validate(bad_output, "coder")
        # 의미적 NULL이 먼저 걸리거나 동사 없음이 걸림
        assert not valid

    def test_coder_diff_has_files_required(self):
        """coder diff 있으면 files_changed 필수"""
        bad_output = {
            "summary": "auth.py 로그인 함수를 수정함",
            "diff": "--- a/auth.py\n+++ b/auth.py\n@@ -1,3 +1,4 @@\n+pass",
            "files_changed": []  # 비어있음!
        }
        valid, error = self.guard.validate(bad_output, "coder")
        assert not valid
        assert "비어있음" in error

    def test_coder_valid_output(self):
        """정상 coder 출력"""
        good_output = {
            "summary": "auth.py 파일의 로그인 함수를 수정함",
            "diff": "--- a/auth.py\n+++ b/auth.py\n@@ -10,3 +10,4 @@\n+    return jwt",
            "files_changed": ["auth.py"]
        }
        valid, error = self.guard.validate(good_output, "coder")
        assert valid, f"에러: {error}"

    # =========================================================================
    # QA 프로필 테스트
    # =========================================================================

    def test_qa_invalid_verdict(self):
        """qa 잘못된 verdict"""
        bad_output = {"verdict": "OK", "tests": []}
        valid, error = self.guard.validate(bad_output, "qa")
        assert not valid
        assert "유효하지 않음" in error

    def test_qa_pass_needs_tests(self):
        """qa PASS면 tests 필수"""
        bad_output = {"verdict": "PASS", "tests": []}
        valid, error = self.guard.validate(bad_output, "qa")
        assert not valid
        assert "비어있음" in error

    def test_qa_valid_output(self):
        """정상 qa 출력"""
        good_output = {
            "verdict": "PASS",
            "tests": [{"name": "test_login", "result": "PASS"}],
            "issues_found": []
        }
        valid, error = self.guard.validate(good_output, "qa")
        assert valid, f"에러: {error}"

    # =========================================================================
    # REVIEWER 프로필 테스트
    # =========================================================================

    def test_reviewer_invalid_verdict(self):
        """reviewer 잘못된 verdict"""
        bad_output = {"verdict": "LGTM", "risks": [], "security_score": 8}
        valid, error = self.guard.validate(bad_output, "reviewer")
        assert not valid
        assert "유효하지 않음" in error

    def test_reviewer_score_out_of_range(self):
        """reviewer security_score 범위 초과"""
        bad_output = {"verdict": "APPROVE", "risks": [], "security_score": 15}
        valid, error = self.guard.validate(bad_output, "reviewer")
        assert not valid
        assert "범위 밖" in error

    def test_reviewer_reject_needs_risks(self):
        """reviewer REJECT면 risks 필수"""
        bad_output = {
            "verdict": "REJECT",
            "risks": [],
            "security_score": 3
        }
        valid, error = self.guard.validate(bad_output, "reviewer")
        assert not valid
        assert "필수" in error

    def test_reviewer_valid_output(self):
        """정상 reviewer 출력"""
        good_output = {
            "verdict": "APPROVE",
            "risks": [],
            "security_score": 9,
            "approved_files": ["auth.py"],
            "blocked_files": []
        }
        valid, error = self.guard.validate(good_output, "reviewer")
        assert valid, f"에러: {error}"

    # =========================================================================
    # COUNCIL 프로필 테스트
    # =========================================================================

    def test_council_score_range(self):
        """council score 범위 검사"""
        bad_output = {"score": -1, "reasoning": "이것은 적절한 판단 근거입니다."}
        valid, error = self.guard.validate(bad_output, "council")
        assert not valid
        assert "범위 밖" in error

    def test_council_reasoning_too_short(self):
        """council reasoning 최소 길이"""
        bad_output = {"score": 7, "reasoning": "좋음"}
        valid, error = self.guard.validate(bad_output, "council")
        assert not valid
        assert "너무 짧음" in error

    def test_council_valid_output(self):
        """정상 council 출력"""
        good_output = {
            "score": 8.5,
            "reasoning": "코드 품질이 우수하고 보안 이슈가 없습니다. 테스트 커버리지도 적절합니다.",
            "concerns": [],
            "approvals": ["코드 품질 양호"]
        }
        valid, error = self.guard.validate(good_output, "council")
        assert valid, f"에러: {error}"

    # =========================================================================
    # 에러 타입 분류 테스트
    # =========================================================================

    def test_get_error_type_semantic_null(self):
        """에러 타입: SEMANTIC_NULL"""
        error_type = self.guard.get_error_type("의미적 NULL 감지: 'looks good' 패턴")
        assert error_type == "SEMANTIC_NULL"

    def test_get_error_type_field_too_short(self):
        """에러 타입: FIELD_TOO_SHORT"""
        error_type = self.guard.get_error_type("'summary' 필드 너무 짧음")
        assert error_type == "FIELD_TOO_SHORT"

    def test_get_error_type_missing_verb(self):
        """에러 타입: MISSING_VERB"""
        error_type = self.guard.get_error_type("'summary' 필드에 동사 없음")
        assert error_type == "MISSING_VERB"

    def test_get_error_type_invalid_value(self):
        """에러 타입: INVALID_VALUE"""
        error_type = self.guard.get_error_type("'verdict' 값 'OK'이 유효하지 않음")
        assert error_type == "INVALID_VALUE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
