"""
Hattz Empire - QA (DUAL ENGINE)
코드 검증 + 보안 체크 + 테스트 케이스 생성

Engine 1: GPT-5.2 Thinking Extended (엣지케이스 추론, 논리 오류)
Engine 2: Claude Opus 4.5 (보안 취약점, 코드 스멜)

Merge Strategy: parallel (둘 다 실행, 합집합)
"""
from typing import Any, Optional
from dataclasses import dataclass

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from .base import DualEngineAgent, EngineResponse, call_llm

try:
    from config import ModelConfig, get_system_prompt
except ImportError:
    from ..config import ModelConfig, get_system_prompt


@dataclass
class Issue:
    """발견된 이슈"""
    severity: str      # critical, high, medium, low
    type: str          # logic, security, performance, style
    location: str      # file:line
    description: str
    fix_suggestion: str
    engine: str        # 발견한 엔진


@dataclass
class TestCase:
    """테스트 케이스"""
    name: str
    scenario: str
    expected: str
    code: str = ""


@dataclass
class QAOutput:
    """QA 출력"""
    status: str                   # approved, needs_revision, rejected
    issues: list[Issue]           # 발견된 이슈들
    test_cases: list[TestCase]    # 생성된 테스트 케이스
    security_scan: dict           # 보안 스캔 결과
    summary: str                  # 전체 요약
    confidence: float             # 검증 신뢰도


class QA(DualEngineAgent):
    """
    QA - 코드 품질 검증

    사용법:
        qa = QA()
        result = qa.review(code, context="RSI 계산 함수")
        print(result.merged.status)
        for issue in result.merged.issues:
            print(f"[{issue.severity}] {issue.description}")
    """

    def __init__(self):
        super().__init__("qa")

    def _call_engine(self, model_config: ModelConfig, input_data: Any) -> EngineResponse:
        """엔진 호출"""
        if isinstance(input_data, str):
            user_input = input_data
        elif isinstance(input_data, dict):
            user_input = self._format_request(input_data)
        else:
            user_input = str(input_data)

        return call_llm(model_config, self.system_prompt, user_input)

    def _format_request(self, data: dict) -> str:
        """딕셔너리를 프롬프트로 변환"""
        lines = ["# Code Review Request\n"]

        if "code" in data:
            lines.append("## Code to Review")
            lines.append(f"```python\n{data['code']}\n```\n")

        if "context" in data:
            lines.append(f"## Context\n{data['context']}\n")

        if "focus_areas" in data:
            lines.append("## Focus Areas")
            for area in data["focus_areas"]:
                lines.append(f"- {area}")
            lines.append("")

        return "\n".join(lines)

    def _parse_yaml_response(self, content: str) -> dict:
        """YAML 응답 파싱"""
        if not HAS_YAML or not content:
            return {}

        try:
            if "```yaml" in content:
                start = content.find("```yaml") + 7
                end = content.find("```", start)
                yaml_str = content[start:end].strip()
                return yaml.safe_load(yaml_str) or {}
        except:
            pass

        # YAML 실패시 구조 추출 시도
        return self._extract_review_structure(content)

    def _extract_review_structure(self, content: str) -> dict:
        """리뷰 구조 추출"""
        result = {
            "status": "needs_revision",
            "issues": [],
            "test_cases": [],
            "summary": ""
        }

        content_lower = content.lower()

        # Status 추출
        if "approved" in content_lower and "not" not in content_lower[:content_lower.find("approved")]:
            result["status"] = "approved"
        elif "rejected" in content_lower:
            result["status"] = "rejected"

        # Issues 추출 (간단한 휴리스틱)
        lines = content.split("\n")
        for line in lines:
            line_lower = line.lower()
            if any(kw in line_lower for kw in ["critical", "high", "medium", "low", "issue", "bug", "error"]):
                severity = "medium"
                if "critical" in line_lower:
                    severity = "critical"
                elif "high" in line_lower:
                    severity = "high"
                elif "low" in line_lower:
                    severity = "low"

                result["issues"].append({
                    "severity": severity,
                    "description": line.strip(),
                    "type": "logic"
                })

        return result

    def _merge_responses(
        self,
        response_1: EngineResponse,
        response_2: EngineResponse
    ) -> QAOutput:
        """
        두 엔진 응답 병합 (parallel - 합집합)

        GPT (논리): 엣지케이스, 논리 오류, 테스트 케이스
        Opus (보안): 보안 취약점, 코드 스멜, best practices
        """
        parsed_gpt = self._parse_yaml_response(response_1.content or "")
        parsed_opus = self._parse_yaml_response(response_2.content or "")

        # Status: 더 엄격한 쪽 (rejected > needs_revision > approved)
        status_priority = {"rejected": 3, "needs_revision": 2, "approved": 1}
        status_gpt = parsed_gpt.get("review_result", {}).get("status") or parsed_gpt.get("status", "needs_revision")
        status_opus = parsed_opus.get("review_result", {}).get("status") or parsed_opus.get("status", "needs_revision")

        if status_priority.get(status_gpt, 0) >= status_priority.get(status_opus, 0):
            final_status = status_gpt
        else:
            final_status = status_opus

        # Issues: 합집합 (둘 다의 이슈 포함)
        issues = []

        # GPT issues
        gpt_issues = parsed_gpt.get("issues", [])
        for issue in gpt_issues:
            if isinstance(issue, dict):
                issues.append(Issue(
                    severity=issue.get("severity", "medium"),
                    type=issue.get("type", "logic"),
                    location=issue.get("location", "unknown"),
                    description=issue.get("description", ""),
                    fix_suggestion=issue.get("fix_suggestion", ""),
                    engine="GPT-5.2"
                ))

        # Opus issues
        opus_issues = parsed_opus.get("issues", [])
        for issue in opus_issues:
            if isinstance(issue, dict):
                issues.append(Issue(
                    severity=issue.get("severity", "medium"),
                    type=issue.get("type", "security"),
                    location=issue.get("location", "unknown"),
                    description=issue.get("description", ""),
                    fix_suggestion=issue.get("fix_suggestion", ""),
                    engine="Claude Opus"
                ))

        # Test cases: 합집합
        test_cases = []

        gpt_tests = parsed_gpt.get("test_cases", [])
        for tc in gpt_tests:
            if isinstance(tc, dict):
                test_cases.append(TestCase(
                    name=tc.get("name", "test"),
                    scenario=tc.get("scenario", ""),
                    expected=tc.get("expected", ""),
                    code=tc.get("code", "")
                ))

        opus_tests = parsed_opus.get("test_cases", [])
        for tc in opus_tests:
            if isinstance(tc, dict):
                test_cases.append(TestCase(
                    name=tc.get("name", "test"),
                    scenario=tc.get("scenario", ""),
                    expected=tc.get("expected", ""),
                    code=tc.get("code", "")
                ))

        # Security scan: Opus 우선 (보안 전문)
        security_opus = parsed_opus.get("security_scan", {})
        security_gpt = parsed_gpt.get("security_scan", {})
        security_scan = {
            "vulnerabilities": list(set(
                security_opus.get("vulnerabilities", []) +
                security_gpt.get("vulnerabilities", [])
            )),
            "recommendations": list(set(
                security_opus.get("recommendations", []) +
                security_gpt.get("recommendations", [])
            ))
        }

        # Summary: 둘 다 합침
        summary_gpt = parsed_gpt.get("summary", "")
        summary_opus = parsed_opus.get("summary", "")
        summary = f"[GPT] {summary_gpt}\n[Opus] {summary_opus}".strip()

        # Confidence: critical 이슈 없으면 높음
        critical_count = sum(1 for i in issues if i.severity == "critical")
        high_count = sum(1 for i in issues if i.severity == "high")

        if critical_count > 0:
            confidence = 0.3
        elif high_count > 0:
            confidence = 0.6
        elif len(issues) > 5:
            confidence = 0.7
        else:
            confidence = 0.9

        return QAOutput(
            status=final_status,
            issues=issues,
            test_cases=test_cases,
            security_scan=security_scan,
            summary=summary,
            confidence=confidence
        )

    def review(
        self,
        code: str,
        context: str = "",
        focus_areas: list = None
    ) -> QAOutput:
        """
        코드 리뷰

        Args:
            code: 리뷰할 코드
            context: 컨텍스트 (무슨 기능인지)
            focus_areas: 집중할 영역 (security, performance, logic 등)

        Returns:
            QAOutput
        """
        input_data = {
            "code": code,
            "context": context,
            "focus_areas": focus_areas or ["logic", "security", "performance"]
        }

        result = self.process(input_data)
        return result.merged

    def quick_review(self, code: str, engine: str = "engine_1") -> dict:
        """
        빠른 단일 엔진 리뷰

        Args:
            code: 코드
            engine: "engine_1" (GPT) 또는 "engine_2" (Opus)

        Returns:
            파싱된 딕셔너리
        """
        response = self.process_single(code, engine)
        return self._parse_yaml_response(response.content or "")


# =============================================================================
# Singleton
# =============================================================================

_qa: Optional[QA] = None


def get_qa() -> QA:
    """QA 싱글톤"""
    global _qa
    if _qa is None:
        _qa = QA()
    return _qa


# =============================================================================
# CLI Test
# =============================================================================

def main():
    """테스트"""
    print("\n" + "="*60)
    print("QA TEST (Dual Engine: GPT-5.2 + Opus)")
    print("="*60)

    qa = QA()

    test_code = '''
def calculate_rsi(prices: list, period: int = 14) -> float:
    """Calculate RSI"""
    if len(prices) < period:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi
'''

    print(f"\n[CODE TO REVIEW]")
    print(test_code[:300] + "...")
    print("\n[Processing with dual engine...]")

    try:
        result = qa.review(test_code, context="RSI calculation function")
        print(f"\n[RESULT]")
        print(f"  Status: {result.status}")
        print(f"  Confidence: {result.confidence}")
        print(f"  Issues Found: {len(result.issues)}")
        for issue in result.issues[:3]:
            print(f"    [{issue.severity}] {issue.description[:50]}...")
        print(f"  Test Cases: {len(result.test_cases)}")
        print(f"  Security: {result.security_scan}")
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
