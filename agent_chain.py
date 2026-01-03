"""
Hattz Empire - Agent Chain Orchestrator
에이전트 간 자동 체인 호출 (Excavator → PM → Coder → QA)
"""
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
import json

from agents import (
    get_excavator, get_coder, get_qa, get_strategist, get_analyst,
    ExcavatorOutput, CodeOutput, QAOutput
)
from stream import get_stream
import rag


class TaskType(Enum):
    """작업 유형"""
    CODE = "code"           # 코드 작성/수정
    STRATEGY = "strategy"   # 전략 분석/결정
    ANALYSIS = "analysis"   # 로그/데이터 분석
    QUESTION = "question"   # 질문/확인
    UNKNOWN = "unknown"


@dataclass
class ChainResult:
    """체인 실행 결과"""
    success: bool
    task_type: TaskType
    excavation: Optional[ExcavatorOutput] = None
    code: Optional[CodeOutput] = None
    qa_result: Optional[QAOutput] = None
    final_response: str = ""
    agents_called: List[str] = field(default_factory=list)
    error: Optional[str] = None


class AgentChain:
    """
    에이전트 체인 오케스트레이터

    CEO 입력을 분석하고 적절한 에이전트 체인을 자동 실행

    체인 패턴:
    1. 코드 작업: Excavator → Coder → QA
    2. 전략 작업: Excavator → Strategist
    3. 분석 작업: Analyst (단독)
    4. 질문/확인: Excavator → (CEO 응답 대기)
    """

    def __init__(self):
        self.stream = get_stream()
        self._excavator = None
        self._coder = None
        self._qa = None
        self._strategist = None
        self._analyst = None

    @property
    def excavator(self):
        if self._excavator is None:
            self._excavator = get_excavator()
        return self._excavator

    @property
    def coder(self):
        if self._coder is None:
            self._coder = get_coder()
        return self._coder

    @property
    def qa(self):
        if self._qa is None:
            self._qa = get_qa()
        return self._qa

    @property
    def strategist(self):
        if self._strategist is None:
            self._strategist = get_strategist()
        return self._strategist

    @property
    def analyst(self):
        if self._analyst is None:
            self._analyst = get_analyst()
        return self._analyst

    def process(self, ceo_input: str, task_id: str = None) -> ChainResult:
        """
        CEO 입력 처리 (전체 체인 실행)

        Args:
            ceo_input: CEO 한글 입력
            task_id: 작업 ID (추적용)

        Returns:
            ChainResult
        """
        agents_called = []

        # 번역 (한글 → 영어)
        if rag.is_korean(ceo_input):
            english_input = rag.translate_for_agent(ceo_input)
        else:
            english_input = ceo_input

        self.stream.log("chain", None, "request", ceo_input, task_id=task_id)

        try:
            # Step 1: Excavator - 의도 발굴
            print("[Chain] Step 1: Excavator analyzing intent...")
            excavation = self.excavator.excavate(english_input)
            agents_called.append("excavator")

            self.stream.log(
                "excavator", "chain", "response",
                {
                    "explicit": excavation.explicit,
                    "implicit": excavation.implicit,
                    "confidence": excavation.confidence,
                    "perfectionism": excavation.perfectionism_detected
                },
                task_id=task_id
            )

            # 신뢰도 낮으면 질문 반환
            if excavation.confidence < 0.5 and excavation.questions:
                return ChainResult(
                    success=True,
                    task_type=TaskType.QUESTION,
                    excavation=excavation,
                    final_response=self._format_questions(excavation),
                    agents_called=agents_called
                )

            # Step 2: 작업 유형 판단
            task_type = self._determine_task_type(excavation, english_input)
            print(f"[Chain] Task type determined: {task_type.value}")

            # Step 3: 유형별 체인 실행
            if task_type == TaskType.CODE:
                return self._run_code_chain(excavation, english_input, agents_called, task_id)
            elif task_type == TaskType.STRATEGY:
                return self._run_strategy_chain(excavation, english_input, agents_called, task_id)
            elif task_type == TaskType.ANALYSIS:
                return self._run_analysis_chain(english_input, agents_called, task_id)
            else:
                # UNKNOWN - Excavation 결과만 반환
                return ChainResult(
                    success=True,
                    task_type=task_type,
                    excavation=excavation,
                    final_response=self._format_excavation(excavation),
                    agents_called=agents_called
                )

        except Exception as e:
            self.stream.log("chain", None, "error", str(e), task_id=task_id)
            return ChainResult(
                success=False,
                task_type=TaskType.UNKNOWN,
                error=str(e),
                agents_called=agents_called
            )

    def _determine_task_type(self, excavation: ExcavatorOutput, input_text: str) -> TaskType:
        """작업 유형 판단"""
        input_lower = input_text.lower()
        explicit_str = " ".join(excavation.explicit).lower()
        implicit_str = " ".join(excavation.implicit).lower()

        # 코드 관련 키워드
        code_keywords = [
            "code", "function", "class", "implement", "create", "build", "fix",
            "bug", "error", "refactor", "test", "write", "만들어", "구현", "수정",
            "코드", "함수", "버그", "테스트"
        ]

        # 전략 관련 키워드
        strategy_keywords = [
            "strategy", "plan", "decide", "analyze", "compare", "should",
            "전략", "계획", "분석", "비교", "결정", "어떻게"
        ]

        # 분석 관련 키워드
        analysis_keywords = [
            "log", "analyze", "metric", "performance", "error rate",
            "로그", "분석", "성능", "에러율", "통계"
        ]

        combined = f"{input_lower} {explicit_str} {implicit_str}"

        code_score = sum(1 for kw in code_keywords if kw in combined)
        strategy_score = sum(1 for kw in strategy_keywords if kw in combined)
        analysis_score = sum(1 for kw in analysis_keywords if kw in combined)

        if code_score > strategy_score and code_score > analysis_score:
            return TaskType.CODE
        elif strategy_score > code_score and strategy_score > analysis_score:
            return TaskType.STRATEGY
        elif analysis_score > 0:
            return TaskType.ANALYSIS
        else:
            return TaskType.CODE  # 기본값은 코드

    def _run_code_chain(
        self,
        excavation: ExcavatorOutput,
        input_text: str,
        agents_called: List[str],
        task_id: str
    ) -> ChainResult:
        """코드 체인: Coder → QA"""

        # Coder 호출
        print("[Chain] Step 2: Coder generating code...")
        task_description = self._build_code_task(excavation, input_text)
        code_output = self.coder.generate(
            task=task_description,
            requirements=excavation.explicit
        )
        agents_called.append("coder")

        self.stream.log(
            "coder", "chain", "response",
            {
                "code_length": len(code_output.code),
                "files": len(code_output.files),
                "complexity": code_output.complexity
            },
            task_id=task_id
        )

        # 코드가 없으면 여기서 종료
        if not code_output.code or len(code_output.code) < 50:
            return ChainResult(
                success=True,
                task_type=TaskType.CODE,
                excavation=excavation,
                code=code_output,
                final_response=self._format_code_response(code_output),
                agents_called=agents_called
            )

        # QA 호출
        print("[Chain] Step 3: QA reviewing code...")
        qa_output = self.qa.review(
            code=code_output.code,
            context=task_description
        )
        agents_called.append("qa")

        self.stream.log(
            "qa", "chain", "response",
            {
                "status": qa_output.status,
                "issues": len(qa_output.issues),
                "confidence": qa_output.confidence
            },
            task_id=task_id
        )

        # 결과 조합
        final_response = self._format_full_code_response(code_output, qa_output)

        return ChainResult(
            success=True,
            task_type=TaskType.CODE,
            excavation=excavation,
            code=code_output,
            qa_result=qa_output,
            final_response=final_response,
            agents_called=agents_called
        )

    def _run_strategy_chain(
        self,
        excavation: ExcavatorOutput,
        input_text: str,
        agents_called: List[str],
        task_id: str
    ) -> ChainResult:
        """전략 체인: Strategist"""

        print("[Chain] Step 2: Strategist analyzing...")
        strategy_result = self.strategist.process(input_text)
        agents_called.append("strategist")

        self.stream.log(
            "strategist", "chain", "response",
            {"merged": str(strategy_result.merged)[:500]},
            task_id=task_id
        )

        return ChainResult(
            success=True,
            task_type=TaskType.STRATEGY,
            excavation=excavation,
            final_response=self._format_strategy_response(strategy_result.merged),
            agents_called=agents_called
        )

    def _run_analysis_chain(
        self,
        input_text: str,
        agents_called: List[str],
        task_id: str
    ) -> ChainResult:
        """분석 체인: Analyst (단독)"""

        print("[Chain] Running Analyst...")

        # 분석 유형 결정
        input_lower = input_text.lower()

        try:
            if any(kw in input_lower for kw in ["log", "로그", "오늘", "today"]):
                analysis_result = self.analyst.summarize_today()
            elif any(kw in input_lower for kw in ["system", "시스템", "status", "상태"]):
                analysis_result = self.analyst.system_status()
            else:
                # 맥락 복원 (기본)
                analysis_result = self.analyst.restore_context(input_text)

            agents_called.append("analyst")

            self.stream.log(
                "analyst", "chain", "response",
                {"result": analysis_result.summary[:500]},
                task_id=task_id
            )

            return ChainResult(
                success=True,
                task_type=TaskType.ANALYSIS,
                final_response=self._format_analysis_response(analysis_result),
                agents_called=agents_called
            )
        except Exception as e:
            return ChainResult(
                success=False,
                task_type=TaskType.ANALYSIS,
                error=str(e),
                agents_called=agents_called
            )

    def _format_analysis_response(self, result) -> str:
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

    def _build_code_task(self, excavation: ExcavatorOutput, input_text: str) -> str:
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

    def _format_questions(self, excavation: ExcavatorOutput) -> str:
        """질문 포맷팅 (한국어)"""
        lines = ["## 확인이 필요합니다\n"]
        lines.append(f"신뢰도: {excavation.confidence:.0%}\n")

        if excavation.questions:
            lines.append("### 질문:")
            for i, q in enumerate(excavation.questions, 1):
                question = q.get("question", str(q))
                lines.append(f"{i}. {question}")

                options = q.get("options", [])
                for opt in options:
                    label = opt.get("label", str(opt))
                    desc = opt.get("description", "")
                    lines.append(f"   - **{label}**: {desc}")

        return "\n".join(lines)

    def _format_excavation(self, excavation: ExcavatorOutput) -> str:
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

    def _format_code_response(self, code: CodeOutput) -> str:
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

    def _format_full_code_response(self, code: CodeOutput, qa: QAOutput) -> str:
        """코드 + QA 결과 포맷팅"""
        lines = ["## 코드 생성 및 검증 완료\n"]

        # Code section
        lines.append(f"### 복잡도: {code.complexity}")

        if code.code:
            lines.append("\n```python")
            lines.append(code.code)
            lines.append("```")

        # QA section
        lines.append(f"\n### QA 검증 결과: **{qa.status.upper()}**")
        lines.append(f"신뢰도: {qa.confidence:.0%}")

        if qa.issues:
            lines.append(f"\n**발견된 이슈 ({len(qa.issues)}개):**")
            for issue in qa.issues[:5]:  # 최대 5개
                lines.append(f"- [{issue.severity}] {issue.description[:100]}")

        if qa.test_cases:
            lines.append(f"\n**제안된 테스트 ({len(qa.test_cases)}개)**")

        if code.dependencies:
            lines.append(f"\n**Dependencies:** {', '.join(code.dependencies)}")

        return "\n".join(lines)

    def _format_strategy_response(self, strategy: Any) -> str:
        """전략 응답 포맷팅"""
        if hasattr(strategy, '__dict__'):
            return f"## 전략 분석 결과\n\n{json.dumps(strategy.__dict__, indent=2, ensure_ascii=False, default=str)}"
        return f"## 전략 분석 결과\n\n{str(strategy)}"


# =============================================================================
# Singleton
# =============================================================================

_chain: Optional[AgentChain] = None


def get_chain() -> AgentChain:
    """AgentChain 싱글톤"""
    global _chain
    if _chain is None:
        _chain = AgentChain()
    return _chain


# =============================================================================
# CLI Test
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("AGENT CHAIN TEST")
    print("=" * 60)

    chain = AgentChain()

    test_input = "RSI 계산 함수 만들어줘"
    print(f"\n[INPUT] {test_input}")
    print("\n[Processing...]")

    result = chain.process(test_input)

    print(f"\n[RESULT]")
    print(f"  Success: {result.success}")
    print(f"  Task Type: {result.task_type.value}")
    print(f"  Agents Called: {result.agents_called}")
    print(f"\n[RESPONSE]\n{result.final_response[:500]}...")
