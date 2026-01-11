"""
Hattz Empire - Agent Chain Unit Tests
에이전트 체인 오케스트레이터 테스트
"""
import pytest
import sys
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass, field
from typing import List, Optional, Any
from enum import Enum


# =============================================================================
# Mock Classes (agent_chain.py 의존성)
# =============================================================================

class MockTaskType(Enum):
    """Mock TaskType for testing"""
    CODE = "code"
    STRATEGY = "strategy"
    ANALYSIS = "analysis"
    QUESTION = "question"
    UNKNOWN = "unknown"


@dataclass
class MockExcavatorOutput:
    explicit: List[str] = field(default_factory=list)
    implicit: List[str] = field(default_factory=list)
    confidence: float = 0.8
    perfectionism_detected: bool = False
    questions: List[dict] = field(default_factory=list)
    mvp_suggestion: str = ""


@dataclass
class MockCodeOutput:
    code: str = ""
    files: List[str] = field(default_factory=list)
    complexity: str = "low"
    dependencies: List[str] = field(default_factory=list)


@dataclass
class MockQAOutput:
    status: str = "pass"
    issues: List[Any] = field(default_factory=list)
    confidence: float = 0.9
    test_cases: List[Any] = field(default_factory=list)


@dataclass
class MockAnalysisResult:
    analysis_type: str = "log"
    summary: str = "분석 요약"
    insights: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    confidence: float = 0.85


@dataclass
class MockStrategyResult:
    merged: Any = None


@dataclass
class MockChainResult:
    success: bool
    task_type: MockTaskType
    excavation: Optional[MockExcavatorOutput] = None
    code: Optional[MockCodeOutput] = None
    qa_result: Optional[MockQAOutput] = None
    final_response: str = ""
    agents_called: List[str] = field(default_factory=list)
    error: Optional[str] = None


# =============================================================================
# Test: TaskType Enum
# =============================================================================

class TestTaskType:
    """TaskType Enum 테스트"""

    def test_enum_values(self):
        """Enum 값 확인"""
        assert MockTaskType.CODE.value == "code"
        assert MockTaskType.STRATEGY.value == "strategy"
        assert MockTaskType.ANALYSIS.value == "analysis"
        assert MockTaskType.QUESTION.value == "question"
        assert MockTaskType.UNKNOWN.value == "unknown"

    def test_enum_comparison(self):
        """Enum 비교"""
        assert MockTaskType.CODE == MockTaskType.CODE
        assert MockTaskType.CODE != MockTaskType.STRATEGY


# =============================================================================
# Test: ChainResult Dataclass
# =============================================================================

class TestChainResult:
    """ChainResult 데이터클래스 테스트"""

    def test_default_values(self):
        """기본값 확인"""
        result = MockChainResult(success=True, task_type=MockTaskType.CODE)
        assert result.success is True
        assert result.task_type == MockTaskType.CODE
        assert result.excavation is None
        assert result.code is None
        assert result.qa_result is None
        assert result.final_response == ""
        assert result.agents_called == []
        assert result.error is None

    def test_with_all_fields(self):
        """모든 필드 설정"""
        excavation = MockExcavatorOutput(explicit=["req1"], confidence=0.9)
        code = MockCodeOutput(code="def hello(): pass")
        qa = MockQAOutput(status="pass")

        result = MockChainResult(
            success=True,
            task_type=MockTaskType.CODE,
            excavation=excavation,
            code=code,
            qa_result=qa,
            final_response="완료",
            agents_called=["excavator", "coder", "qa"]
        )

        assert result.success is True
        assert result.excavation.confidence == 0.9
        assert "def hello" in result.code.code
        assert result.qa_result.status == "pass"
        assert len(result.agents_called) == 3

    def test_error_result(self):
        """에러 결과"""
        result = MockChainResult(
            success=False,
            task_type=MockTaskType.UNKNOWN,
            error="Something went wrong"
        )

        assert result.success is False
        assert result.error == "Something went wrong"


# =============================================================================
# Test: ExcavatorOutput
# =============================================================================

class TestExcavatorOutput:
    """ExcavatorOutput 테스트"""

    def test_default_values(self):
        """기본값"""
        output = MockExcavatorOutput()
        assert output.explicit == []
        assert output.implicit == []
        assert output.confidence == 0.8
        assert output.perfectionism_detected is False
        assert output.questions == []
        assert output.mvp_suggestion == ""

    def test_with_data(self):
        """데이터 포함"""
        output = MockExcavatorOutput(
            explicit=["RSI 계산 함수 구현"],
            implicit=["에러 처리 필요", "테스트 코드 포함"],
            confidence=0.95,
            perfectionism_detected=True,
            mvp_suggestion="기본 RSI만 먼저 구현"
        )

        assert len(output.explicit) == 1
        assert len(output.implicit) == 2
        assert output.confidence == 0.95
        assert output.perfectionism_detected is True

    def test_low_confidence_with_questions(self):
        """낮은 신뢰도 + 질문"""
        output = MockExcavatorOutput(
            confidence=0.3,
            questions=[
                {"question": "어떤 RSI 기간을 원하시나요?", "options": ["14일", "21일"]}
            ]
        )

        assert output.confidence < 0.5
        assert len(output.questions) == 1


# =============================================================================
# Test: CodeOutput
# =============================================================================

class TestCodeOutput:
    """CodeOutput 테스트"""

    def test_default_values(self):
        """기본값"""
        output = MockCodeOutput()
        assert output.code == ""
        assert output.files == []
        assert output.complexity == "low"
        assert output.dependencies == []

    def test_with_code(self):
        """코드 포함"""
        output = MockCodeOutput(
            code="def calculate_rsi(prices, period=14):\n    pass",
            files=["src/indicators/rsi.py"],
            complexity="medium",
            dependencies=["numpy", "pandas"]
        )

        assert "calculate_rsi" in output.code
        assert len(output.files) == 1
        assert output.complexity == "medium"
        assert "numpy" in output.dependencies


# =============================================================================
# Test: QAOutput
# =============================================================================

class TestQAOutput:
    """QAOutput 테스트"""

    def test_default_values(self):
        """기본값"""
        output = MockQAOutput()
        assert output.status == "pass"
        assert output.issues == []
        assert output.confidence == 0.9
        assert output.test_cases == []

    def test_with_issues(self):
        """이슈 포함"""
        @dataclass
        class MockIssue:
            severity: str
            description: str

        output = MockQAOutput(
            status="fail",
            issues=[MockIssue(severity="high", description="Division by zero possible")],
            confidence=0.7
        )

        assert output.status == "fail"
        assert len(output.issues) == 1
        assert output.confidence < 0.9


# =============================================================================
# Test: Task Type Determination Logic
# =============================================================================

class TestTaskTypeDetermination:
    """작업 유형 판단 로직 테스트"""

    def _determine_task_type(self, excavation: MockExcavatorOutput, input_text: str) -> MockTaskType:
        """실제 agent_chain.py의 _determine_task_type 로직 복제"""
        input_lower = input_text.lower()
        explicit_str = " ".join(excavation.explicit).lower()
        implicit_str = " ".join(excavation.implicit).lower()

        code_keywords = [
            "code", "function", "class", "implement", "create", "build", "fix",
            "bug", "error", "refactor", "test", "write", "만들어", "구현", "수정",
            "코드", "함수", "버그", "테스트"
        ]

        strategy_keywords = [
            "strategy", "plan", "decide", "analyze", "compare", "should",
            "전략", "계획", "분석", "비교", "결정", "어떻게"
        ]

        analysis_keywords = [
            "log", "analyze", "metric", "performance", "error rate",
            "로그", "분석", "성능", "에러율", "통계"
        ]

        combined = f"{input_lower} {explicit_str} {implicit_str}"

        code_score = sum(1 for kw in code_keywords if kw in combined)
        strategy_score = sum(1 for kw in strategy_keywords if kw in combined)
        analysis_score = sum(1 for kw in analysis_keywords if kw in combined)

        if code_score > strategy_score and code_score > analysis_score:
            return MockTaskType.CODE
        elif strategy_score > code_score and strategy_score > analysis_score:
            return MockTaskType.STRATEGY
        elif analysis_score > 0:
            return MockTaskType.ANALYSIS
        else:
            return MockTaskType.CODE

    def test_code_task_korean(self):
        """한국어 코드 작업"""
        excavation = MockExcavatorOutput(explicit=["RSI 계산 함수"])
        result = self._determine_task_type(excavation, "RSI 함수 만들어줘")
        assert result == MockTaskType.CODE

    def test_code_task_english(self):
        """영어 코드 작업"""
        excavation = MockExcavatorOutput(explicit=["implement login function"])
        result = self._determine_task_type(excavation, "Create a login function")
        assert result == MockTaskType.CODE

    def test_strategy_task(self):
        """전략 작업"""
        excavation = MockExcavatorOutput(explicit=["아키텍처 결정"])
        result = self._determine_task_type(excavation, "어떻게 아키텍처를 설계할지 전략을 세워줘")
        assert result == MockTaskType.STRATEGY

    def test_analysis_task(self):
        """분석 작업"""
        excavation = MockExcavatorOutput(explicit=["로그 분석"])
        result = self._determine_task_type(excavation, "오늘 로그 분석해줘")
        assert result == MockTaskType.ANALYSIS

    def test_default_to_code(self):
        """기본값은 CODE"""
        excavation = MockExcavatorOutput()
        result = self._determine_task_type(excavation, "뭔가 해줘")
        assert result == MockTaskType.CODE

    def test_bug_fix_is_code(self):
        """버그 수정은 CODE"""
        excavation = MockExcavatorOutput(explicit=["로그인 버그 수정"])
        result = self._determine_task_type(excavation, "로그인 버그 수정해줘")
        assert result == MockTaskType.CODE

    def test_performance_is_analysis(self):
        """성능 분석은 ANALYSIS"""
        excavation = MockExcavatorOutput()
        result = self._determine_task_type(excavation, "performance metric 분석")
        assert result == MockTaskType.ANALYSIS


# =============================================================================
# Test: Response Formatting
# =============================================================================

class TestResponseFormatting:
    """응답 포맷팅 테스트"""

    def _format_questions(self, excavation: MockExcavatorOutput) -> str:
        """질문 포맷팅 (agent_chain.py 로직 복제)"""
        lines = ["## 확인이 필요합니다\n"]
        lines.append(f"신뢰도: {excavation.confidence:.0%}\n")

        if excavation.questions:
            lines.append("### 질문:")
            for i, q in enumerate(excavation.questions, 1):
                question = q.get("question", str(q))
                lines.append(f"{i}. {question}")

                options = q.get("options", [])
                for opt in options:
                    if isinstance(opt, dict):
                        label = opt.get("label", str(opt))
                        desc = opt.get("description", "")
                        lines.append(f"   - **{label}**: {desc}")
                    else:
                        lines.append(f"   - {opt}")

        return "\n".join(lines)

    def _format_excavation(self, excavation: MockExcavatorOutput) -> str:
        """Excavation 결과 포맷팅"""
        lines = ["## 의도 분석 결과\n"]

        if excavation.explicit:
            lines.append("### 명시된 요청:")
            for item in excavation.explicit:
                lines.append(f"- {item}")

        if excavation.implicit:
            lines.append("\n### 추론된 의도:")
            for item in excavation.implicit:
                lines.append(f"- {item}")

        if excavation.perfectionism_detected:
            lines.append("\n⚠️ **완벽주의 감지**: MVP 먼저 시작 권장")

        if excavation.mvp_suggestion:
            lines.append(f"\n### MVP 제안:\n{excavation.mvp_suggestion}")

        return "\n".join(lines)

    def _format_code_response(self, code: MockCodeOutput) -> str:
        """코드 응답 포맷팅"""
        lines = ["## 생성된 코드\n"]

        if code.complexity:
            lines.append(f"**복잡도:** {code.complexity}")

        if code.code:
            lines.append("\n```python")
            lines.append(code.code)
            lines.append("```")

        if code.dependencies:
            lines.append(f"\n**Dependencies:** {', '.join(code.dependencies)}")

        return "\n".join(lines)

    def test_format_questions(self):
        """질문 포맷팅"""
        excavation = MockExcavatorOutput(
            confidence=0.4,
            questions=[
                {"question": "기간은 몇 일로 할까요?", "options": ["14일", "21일"]}
            ]
        )

        result = self._format_questions(excavation)

        assert "확인이 필요합니다" in result
        assert "40%" in result
        assert "기간은" in result
        assert "14일" in result

    def test_format_excavation_explicit(self):
        """Excavation 포맷팅 - 명시적 요청"""
        excavation = MockExcavatorOutput(explicit=["로그인 기능 구현"])

        result = self._format_excavation(excavation)

        assert "의도 분석 결과" in result
        assert "명시된 요청" in result
        assert "로그인 기능" in result

    def test_format_excavation_perfectionism(self):
        """Excavation 포맷팅 - 완벽주의 감지"""
        excavation = MockExcavatorOutput(
            explicit=["전체 시스템 재설계"],
            perfectionism_detected=True,
            mvp_suggestion="핵심 기능만 먼저"
        )

        result = self._format_excavation(excavation)

        assert "완벽주의 감지" in result
        assert "MVP" in result
        assert "핵심 기능" in result

    def test_format_code_response(self):
        """코드 응답 포맷팅"""
        code = MockCodeOutput(
            code="def hello():\n    print('hello')",
            complexity="low",
            dependencies=["sys"]
        )

        result = self._format_code_response(code)

        assert "생성된 코드" in result
        assert "복잡도" in result
        assert "low" in result
        assert "```python" in result
        assert "def hello" in result
        assert "Dependencies" in result


# =============================================================================
# Test: Analysis Response
# =============================================================================

class TestAnalysisResponse:
    """분석 응답 테스트"""

    def _format_analysis_response(self, result: MockAnalysisResult) -> str:
        """분석 결과 포맷팅"""
        lines = [f"## 분석 결과 ({result.analysis_type})\n"]
        lines.append(f"### 요약\n{result.summary}\n")

        if result.insights:
            lines.append("### 인사이트")
            for insight in result.insights:
                lines.append(f"- {insight}")

        if result.recommendations:
            lines.append("\n### 권장사항")
            for rec in result.recommendations:
                lines.append(f"- {rec}")

        lines.append(f"\n_신뢰도: {result.confidence:.0%}_")
        return "\n".join(lines)

    def test_format_analysis_full(self):
        """분석 응답 전체"""
        result = MockAnalysisResult(
            analysis_type="log",
            summary="오늘 에러가 10건 발생",
            insights=["피크 시간대에 집중", "DB 연결 이슈"],
            recommendations=["커넥션 풀 확대", "모니터링 추가"],
            confidence=0.9
        )

        formatted = self._format_analysis_response(result)

        assert "분석 결과 (log)" in formatted
        assert "오늘 에러가 10건" in formatted
        assert "인사이트" in formatted
        assert "피크 시간대" in formatted
        assert "권장사항" in formatted
        assert "커넥션 풀" in formatted
        assert "90%" in formatted

    def test_format_analysis_minimal(self):
        """분석 응답 최소"""
        result = MockAnalysisResult(
            analysis_type="status",
            summary="시스템 정상"
        )

        formatted = self._format_analysis_response(result)

        assert "분석 결과 (status)" in formatted
        assert "시스템 정상" in formatted
        assert "85%" in formatted  # 기본 신뢰도


# =============================================================================
# Test: Code Task Builder
# =============================================================================

class TestCodeTaskBuilder:
    """코드 태스크 빌더 테스트"""

    def _build_code_task(self, excavation: MockExcavatorOutput, input_text: str) -> str:
        """Coder용 작업 설명 생성"""
        lines = [f"# Task: {input_text[:200]}"]

        if excavation.explicit:
            lines.append("\n## Explicit Requirements:")
            for req in excavation.explicit:
                lines.append(f"- {req}")

        if excavation.implicit:
            lines.append("\n## Implicit Requirements (inferred):")
            for req in excavation.implicit:
                lines.append(f"- {req}")

        if excavation.mvp_suggestion:
            lines.append(f"\n## MVP Suggestion:\n{excavation.mvp_suggestion}")

        return "\n".join(lines)

    def test_build_code_task_simple(self):
        """간단한 태스크"""
        excavation = MockExcavatorOutput(explicit=["로그인 함수 구현"])
        result = self._build_code_task(excavation, "로그인 기능 만들어줘")

        assert "# Task:" in result
        assert "로그인 기능" in result
        assert "Explicit Requirements" in result
        assert "로그인 함수 구현" in result

    def test_build_code_task_with_implicit(self):
        """암묵적 요구사항 포함"""
        excavation = MockExcavatorOutput(
            explicit=["RSI 계산"],
            implicit=["에러 처리", "타입 힌트"]
        )
        result = self._build_code_task(excavation, "RSI 함수")

        assert "Explicit Requirements" in result
        assert "Implicit Requirements" in result
        assert "에러 처리" in result
        assert "타입 힌트" in result

    def test_build_code_task_with_mvp(self):
        """MVP 제안 포함"""
        excavation = MockExcavatorOutput(
            explicit=["전체 트레이딩 시스템"],
            mvp_suggestion="주문 기능만 먼저 구현"
        )
        result = self._build_code_task(excavation, "트레이딩 시스템")

        assert "MVP Suggestion" in result
        assert "주문 기능만" in result


# =============================================================================
# Test: Full Code Response
# =============================================================================

class TestFullCodeResponse:
    """전체 코드 응답 테스트"""

    @dataclass
    class MockIssue:
        severity: str
        description: str

    def _format_full_code_response(self, code: MockCodeOutput, qa: MockQAOutput) -> str:
        """코드 + QA 결과 포맷팅"""
        lines = ["## 코드 생성 및 검증 완료\n"]

        lines.append(f"### 복잡도: {code.complexity}")

        if code.code:
            lines.append("\n```python")
            lines.append(code.code)
            lines.append("```")

        lines.append(f"\n### QA 검증 결과: **{qa.status.upper()}**")
        lines.append(f"신뢰도: {qa.confidence:.0%}")

        if qa.issues:
            lines.append(f"\n**발견된 이슈 ({len(qa.issues)}개):**")
            for issue in qa.issues[:5]:
                lines.append(f"- [{issue.severity}] {issue.description[:100]}")

        if qa.test_cases:
            lines.append(f"\n**제안된 테스트 ({len(qa.test_cases)}개)**")

        if code.dependencies:
            lines.append(f"\n**Dependencies:** {', '.join(code.dependencies)}")

        return "\n".join(lines)

    def test_format_full_response_pass(self):
        """통과 응답"""
        code = MockCodeOutput(
            code="def calc(): pass",
            complexity="low",
            dependencies=["numpy"]
        )
        qa = MockQAOutput(status="pass", confidence=0.95)

        result = self._format_full_code_response(code, qa)

        assert "코드 생성 및 검증 완료" in result
        assert "복잡도: low" in result
        assert "def calc" in result
        assert "QA 검증 결과: **PASS**" in result
        assert "95%" in result
        assert "Dependencies" in result

    def test_format_full_response_with_issues(self):
        """이슈 포함 응답"""
        code = MockCodeOutput(code="def risky(): pass", complexity="high")
        qa = MockQAOutput(
            status="fail",
            confidence=0.6,
            issues=[self.MockIssue(severity="high", description="Null pointer risk")]
        )

        result = self._format_full_code_response(code, qa)

        assert "QA 검증 결과: **FAIL**" in result
        assert "발견된 이슈 (1개)" in result
        assert "[high]" in result
        assert "Null pointer" in result


# =============================================================================
# Test: Singleton
# =============================================================================

class TestSingleton:
    """싱글톤 패턴 테스트 (로직만)"""

    def test_singleton_behavior(self):
        """싱글톤 동작 확인 (mock)"""
        _chain = None

        def get_chain():
            nonlocal _chain
            if _chain is None:
                _chain = object()  # Mock AgentChain
            return _chain

        chain1 = get_chain()
        chain2 = get_chain()

        assert chain1 is chain2


# =============================================================================
# Test: Error Handling
# =============================================================================

class TestErrorHandling:
    """에러 처리 테스트"""

    def test_error_result_structure(self):
        """에러 결과 구조"""
        result = MockChainResult(
            success=False,
            task_type=MockTaskType.UNKNOWN,
            error="Import error: agents module not found",
            agents_called=["excavator"]
        )

        assert result.success is False
        assert result.task_type == MockTaskType.UNKNOWN
        assert "Import error" in result.error
        assert "excavator" in result.agents_called

    def test_partial_chain_failure(self):
        """부분 체인 실패"""
        result = MockChainResult(
            success=False,
            task_type=MockTaskType.CODE,
            excavation=MockExcavatorOutput(explicit=["기능 구현"]),
            error="Coder timeout",
            agents_called=["excavator", "coder"]
        )

        assert result.success is False
        assert result.excavation is not None
        assert result.code is None
        assert "timeout" in result.error.lower()


# =============================================================================
# Test: Korean Input Processing
# =============================================================================

class TestKoreanInput:
    """한국어 입력 처리 테스트"""

    def test_korean_code_keywords(self):
        """한국어 코드 키워드"""
        code_keywords_korean = ["만들어", "구현", "수정", "코드", "함수", "버그", "테스트"]

        test_inputs = [
            "함수 만들어줘",
            "버그 수정해줘",
            "코드 구현해줘",
            "테스트 추가해줘"
        ]

        for inp in test_inputs:
            matches = [kw for kw in code_keywords_korean if kw in inp]
            assert len(matches) > 0, f"'{inp}'에서 키워드 감지 실패"

    def test_korean_strategy_keywords(self):
        """한국어 전략 키워드"""
        strategy_keywords_korean = ["전략", "계획", "분석", "비교", "결정", "어떻게"]

        test_inputs = [
            "전략을 세워줘",
            "어떻게 할지 분석해줘",
            "두 방법을 비교해줘"
        ]

        for inp in test_inputs:
            matches = [kw for kw in strategy_keywords_korean if kw in inp]
            assert len(matches) > 0, f"'{inp}'에서 키워드 감지 실패"


# =============================================================================
# Test: Integration Scenarios (Mock)
# =============================================================================

class TestIntegrationScenarios:
    """통합 시나리오 테스트 (Mock 기반)"""

    def test_code_chain_flow(self):
        """코드 체인 흐름: Excavator → Coder → QA"""
        # Excavator 결과
        excavation = MockExcavatorOutput(
            explicit=["로그인 API 구현"],
            implicit=["JWT 사용", "에러 처리"],
            confidence=0.9
        )

        # Coder 결과
        code = MockCodeOutput(
            code="def login(user, pw): return jwt.encode(...)",
            files=["src/api/auth.py"],
            complexity="medium"
        )

        # QA 결과
        qa = MockQAOutput(status="pass", confidence=0.95)

        # 체인 결과 조합
        result = MockChainResult(
            success=True,
            task_type=MockTaskType.CODE,
            excavation=excavation,
            code=code,
            qa_result=qa,
            agents_called=["excavator", "coder", "qa"],
            final_response="코드 생성 및 검증 완료"
        )

        assert result.success
        assert len(result.agents_called) == 3
        assert result.qa_result.status == "pass"

    def test_question_flow(self):
        """질문 흐름: 낮은 신뢰도"""
        excavation = MockExcavatorOutput(
            confidence=0.3,
            questions=[{"question": "어떤 DB를 사용하시나요?"}]
        )

        # 신뢰도 낮으면 질문 반환
        result = MockChainResult(
            success=True,
            task_type=MockTaskType.QUESTION,
            excavation=excavation,
            agents_called=["excavator"],
            final_response="확인이 필요합니다"
        )

        assert result.success
        assert result.task_type == MockTaskType.QUESTION
        assert len(result.agents_called) == 1  # Excavator만

    def test_analysis_chain_flow(self):
        """분석 체인 흐름: Analyst 단독"""
        analysis = MockAnalysisResult(
            analysis_type="log",
            summary="오늘 에러 5건",
            confidence=0.85
        )

        result = MockChainResult(
            success=True,
            task_type=MockTaskType.ANALYSIS,
            agents_called=["analyst"],
            final_response=f"분석 완료: {analysis.summary}"
        )

        assert result.success
        assert result.task_type == MockTaskType.ANALYSIS
        assert "analyst" in result.agents_called


# =============================================================================
# Test: Edge Cases
# =============================================================================

class TestEdgeCases:
    """엣지 케이스 테스트"""

    def test_empty_excavation(self):
        """빈 Excavation"""
        excavation = MockExcavatorOutput()

        assert excavation.explicit == []
        assert excavation.implicit == []
        assert excavation.confidence == 0.8

    def test_very_long_input(self):
        """매우 긴 입력"""
        long_input = "기능 구현해줘 " * 1000

        # _build_code_task는 200자로 잘라냄
        truncated = long_input[:200]
        assert len(truncated) == 200

    def test_special_characters_in_code(self):
        """특수 문자가 포함된 코드"""
        code = MockCodeOutput(
            code="def calc(x, y):\n    return x + y  # 덧셈\n"
        )

        assert "# 덧셈" in code.code
        assert "\n" in code.code

    def test_unicode_in_response(self):
        """유니코드 응답"""
        result = MockChainResult(
            success=True,
            task_type=MockTaskType.CODE,
            final_response="## 완료 ✅\n코드가 생성되었습니다."
        )

        assert "✅" in result.final_response


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
