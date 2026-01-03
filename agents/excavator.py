"""
Hattz Empire - Thought Excavator (DUAL ENGINE)
CEO 의식의 흐름 → 숨은 의도 발굴 → 선택지 생성

Engine 1: Claude Opus 4.5 (감성/맥락/뉘앙스)
Engine 2: GPT-5.2 Thinking Extended (논리/구조화)
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
class ExcavatorOutput:
    """Excavator 출력"""
    explicit: list[str]           # CEO가 명시적으로 말한 것
    implicit: list[str]           # 추론된 숨은 의도
    questions: list[dict]         # 확인 질문들
    confidence: float             # 신뢰도 (0-1)
    perfectionism_detected: bool  # 완벽주의 감지
    mvp_suggestion: Optional[str] # MVP 제안


class Excavator(DualEngineAgent):
    """
    Thought Excavator - CEO 의도 발굴

    사용법:
        excavator = Excavator()
        result = excavator.excavate("RSI 전략 만들어줘... 근데 좀 복잡하게...")
        print(result.merged)  # ExcavatorOutput
    """

    def __init__(self):
        super().__init__("excavator")

    def _call_engine(self, model_config: ModelConfig, input_data: Any) -> EngineResponse:
        """엔진 호출"""
        if isinstance(input_data, str):
            user_input = input_data
        else:
            user_input = str(input_data)

        return call_llm(model_config, self.system_prompt, user_input)

    def _parse_yaml_response(self, content: str) -> dict:
        """YAML 응답 파싱"""
        if not HAS_YAML or not content:
            return {}

        try:
            # ```yaml ... ``` 블록 추출
            if "```yaml" in content:
                start = content.find("```yaml") + 7
                end = content.find("```", start)
                yaml_str = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                yaml_str = content[start:end].strip()
            else:
                yaml_str = content

            return yaml.safe_load(yaml_str) or {}

        except Exception as e:
            print(f"[Excavator] YAML parse error: {e}")
            return {"raw": content}

    def _merge_responses(
        self,
        response_1: EngineResponse,
        response_2: EngineResponse
    ) -> ExcavatorOutput:
        """
        두 엔진 응답 병합

        Claude (감성): 뉘앙스, 감정, 맥락
        GPT (논리): 구조, 분류, 명확화
        """
        parsed_1 = self._parse_yaml_response(response_1.content or "")
        parsed_2 = self._parse_yaml_response(response_2.content or "")

        # Explicit: 합집합
        explicit_1 = parsed_1.get("explicit", [])
        explicit_2 = parsed_2.get("explicit", [])
        explicit = list(set(explicit_1 + explicit_2))

        # Implicit: 합집합 (둘 다의 추론 포함)
        implicit_1 = parsed_1.get("implicit", [])
        implicit_2 = parsed_2.get("implicit", [])
        implicit = list(set(implicit_1 + implicit_2))

        # Questions: 둘 다에서 수집, 중복 제거
        questions_1 = parsed_1.get("questions", [])
        questions_2 = parsed_2.get("questions", [])
        questions = self._merge_questions(questions_1, questions_2)

        # Confidence: 평균 (둘 다 높아야 높음)
        conf_1 = parsed_1.get("confidence", 0.5)
        conf_2 = parsed_2.get("confidence", 0.5)
        confidence = (conf_1 + conf_2) / 2

        # Perfectionism: OR (하나라도 감지하면)
        perf_1 = parsed_1.get("perfectionism_detected", False)
        perf_2 = parsed_2.get("perfectionism_detected", False)
        perfectionism_detected = perf_1 or perf_2

        # MVP suggestion: 있는 것 사용
        mvp_1 = parsed_1.get("mvp_suggestion")
        mvp_2 = parsed_2.get("mvp_suggestion")
        mvp_suggestion = mvp_1 or mvp_2

        return ExcavatorOutput(
            explicit=explicit,
            implicit=implicit,
            questions=questions,
            confidence=confidence,
            perfectionism_detected=perfectionism_detected,
            mvp_suggestion=mvp_suggestion
        )

    def _merge_questions(self, q1: list, q2: list) -> list:
        """질문 병합 (중복 제거)"""
        seen = set()
        merged = []

        for q in q1 + q2:
            if isinstance(q, dict):
                q_text = q.get("question", "")
                if q_text and q_text not in seen:
                    seen.add(q_text)
                    merged.append(q)

        return merged

    def excavate(self, ceo_input: str) -> ExcavatorOutput:
        """
        CEO 입력에서 의도 발굴

        Args:
            ceo_input: CEO의 한글 입력 (의식의 흐름)

        Returns:
            ExcavatorOutput
        """
        result = self.process(ceo_input)
        return result.merged

    def quick_excavate(self, ceo_input: str, engine: str = "engine_1") -> dict:
        """
        빠른 단일 엔진 발굴 (테스트용)

        Args:
            ceo_input: CEO 입력
            engine: "engine_1" (Claude) 또는 "engine_2" (GPT)

        Returns:
            파싱된 딕셔너리
        """
        response = self.process_single(ceo_input, engine)
        return self._parse_yaml_response(response.content or "")


# =============================================================================
# Singleton
# =============================================================================

_excavator: Optional[Excavator] = None


def get_excavator() -> Excavator:
    """Excavator 싱글톤"""
    global _excavator
    if _excavator is None:
        _excavator = Excavator()
    return _excavator


# =============================================================================
# CLI Test
# =============================================================================

def main():
    """테스트"""
    print("\n" + "="*60)
    print("EXCAVATOR TEST (Dual Engine)")
    print("="*60)

    excavator = Excavator()

    test_input = """
    RSI 전략 만들어줘...
    근데 좀 복잡하게 하고 싶은데...
    아 근데 일단은 간단하게 시작해도 될듯?
    """

    print(f"\n[INPUT]\n{test_input}")
    print("\n[Processing with dual engine...]")

    try:
        result = excavator.excavate(test_input)
        print(f"\n[RESULT]")
        print(f"  Explicit: {result.explicit}")
        print(f"  Implicit: {result.implicit}")
        print(f"  Questions: {len(result.questions)}")
        print(f"  Confidence: {result.confidence}")
        print(f"  Perfectionism: {result.perfectionism_detected}")
        print(f"  MVP: {result.mvp_suggestion}")
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
