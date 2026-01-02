"""
Hattz Empire - Strategist (DUAL ENGINE)
전략 연구 + 데이터 기반 의사결정

Engine 1: GPT-5.2 Thinking Extended (깊은 논리적 사고)
Engine 2: Gemini 3.0 Pro (대용량 데이터 분석)
"""
from typing import Any, Optional
from dataclasses import dataclass

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from .base import DualEngineAgent, EngineResponse, call_llm
from ..config import ModelConfig, get_system_prompt


@dataclass
class StrategyOutput:
    """Strategist 출력"""
    analysis: dict                # 문제/기회/제약 분석
    strategy: dict                # 전략 방향/단계/리스크
    recommendation: dict          # 권장 행동/신뢰도/근거
    data_insights: list[str]      # 데이터 인사이트 (Gemini)
    logic_chain: list[str]        # 논리 체인 (GPT)


class Strategist(DualEngineAgent):
    """
    Strategist - 전략 연구 및 분석

    사용법:
        strategist = Strategist()
        result = strategist.analyze("RSI 기반 진입 전략 설계")
        print(result.merged)  # StrategyOutput
    """

    def __init__(self):
        super().__init__("strategist")

    def _call_engine(self, model_config: ModelConfig, input_data: Any) -> EngineResponse:
        """엔진 호출"""
        if isinstance(input_data, str):
            user_input = input_data
        elif isinstance(input_data, dict):
            # 구조화된 요청
            user_input = self._format_request(input_data)
        else:
            user_input = str(input_data)

        return call_llm(model_config, self.system_prompt, user_input)

    def _format_request(self, data: dict) -> str:
        """딕셔너리를 프롬프트로 변환"""
        lines = ["# Strategy Request\n"]

        if "task" in data:
            lines.append(f"## Task\n{data['task']}\n")

        if "context" in data:
            lines.append(f"## Context\n{data['context']}\n")

        if "constraints" in data:
            lines.append("## Constraints")
            for c in data["constraints"]:
                lines.append(f"- {c}")
            lines.append("")

        if "goals" in data:
            lines.append("## Goals")
            for g in data["goals"]:
                lines.append(f"- {g}")
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
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                yaml_str = content[start:end].strip()
            else:
                yaml_str = content

            return yaml.safe_load(yaml_str) or {}

        except Exception as e:
            print(f"[Strategist] YAML parse error: {e}")
            return {"raw": content}

    def _merge_responses(
        self,
        response_1: EngineResponse,
        response_2: EngineResponse
    ) -> StrategyOutput:
        """
        두 엔진 응답 병합

        GPT (논리): 프레임워크, 논리 체인, 의사결정 트리
        Gemini (데이터): 패턴, 인사이트, 대용량 분석
        """
        parsed_gpt = self._parse_yaml_response(response_1.content or "")
        parsed_gemini = self._parse_yaml_response(response_2.content or "")

        # Analysis: GPT 우선 (논리적 분석)
        analysis_gpt = parsed_gpt.get("analysis", {})
        analysis_gemini = parsed_gemini.get("analysis", {})
        analysis = {
            "problem": analysis_gpt.get("problem") or analysis_gemini.get("problem", ""),
            "opportunities": list(set(
                analysis_gpt.get("opportunities", []) +
                analysis_gemini.get("opportunities", [])
            )),
            "constraints": list(set(
                analysis_gpt.get("constraints", []) +
                analysis_gemini.get("constraints", [])
            ))
        }

        # Strategy: GPT 우선 (전략 프레임워크)
        strategy_gpt = parsed_gpt.get("strategy", {})
        strategy_gemini = parsed_gemini.get("strategy", {})
        strategy = {
            "approach": strategy_gpt.get("approach") or strategy_gemini.get("approach", ""),
            "steps": strategy_gpt.get("steps", []) or strategy_gemini.get("steps", []),
            "risks": list(set(
                strategy_gpt.get("risks", []) +
                strategy_gemini.get("risks", [])
            ))
        }

        # Recommendation: 신뢰도 높은 쪽 우선
        rec_gpt = parsed_gpt.get("recommendation", {})
        rec_gemini = parsed_gemini.get("recommendation", {})
        conf_gpt = rec_gpt.get("confidence", 0)
        conf_gemini = rec_gemini.get("confidence", 0)

        if conf_gpt >= conf_gemini:
            recommendation = rec_gpt
        else:
            recommendation = rec_gemini

        # 평균 신뢰도
        recommendation["confidence"] = (conf_gpt + conf_gemini) / 2 if conf_gpt and conf_gemini else max(conf_gpt, conf_gemini)

        # Data insights: Gemini에서 추출
        data_insights = parsed_gemini.get("data_insights", [])
        if not data_insights and "insights" in parsed_gemini:
            data_insights = parsed_gemini["insights"]

        # Logic chain: GPT에서 추출
        logic_chain = parsed_gpt.get("logic_chain", [])
        if not logic_chain and "reasoning" in parsed_gpt:
            logic_chain = parsed_gpt["reasoning"]

        return StrategyOutput(
            analysis=analysis,
            strategy=strategy,
            recommendation=recommendation,
            data_insights=data_insights if isinstance(data_insights, list) else [data_insights],
            logic_chain=logic_chain if isinstance(logic_chain, list) else [logic_chain]
        )

    def analyze(self, task: str, context: str = "", constraints: list = None) -> StrategyOutput:
        """
        전략 분석

        Args:
            task: 분석할 작업/문제
            context: 추가 컨텍스트
            constraints: 제약 조건

        Returns:
            StrategyOutput
        """
        input_data = {
            "task": task,
            "context": context,
            "constraints": constraints or []
        }

        result = self.process(input_data)
        return result.merged

    def quick_analyze(self, task: str, engine: str = "engine_1") -> dict:
        """
        빠른 단일 엔진 분석

        Args:
            task: 작업
            engine: "engine_1" (GPT) 또는 "engine_2" (Gemini)

        Returns:
            파싱된 딕셔너리
        """
        response = self.process_single(task, engine)
        return self._parse_yaml_response(response.content or "")


# =============================================================================
# Singleton
# =============================================================================

_strategist: Optional[Strategist] = None


def get_strategist() -> Strategist:
    """Strategist 싱글톤"""
    global _strategist
    if _strategist is None:
        _strategist = Strategist()
    return _strategist


# =============================================================================
# CLI Test
# =============================================================================

def main():
    """테스트"""
    print("\n" + "="*60)
    print("STRATEGIST TEST (Dual Engine: GPT-5.2 + Gemini 3.0)")
    print("="*60)

    strategist = Strategist()

    test_task = "RSI 기반 매매 전략 설계"
    test_context = "비트코인 4시간봉, 변동성 높은 시장"
    test_constraints = ["최대 손실 2%", "승률 60% 이상"]

    print(f"\n[TASK] {test_task}")
    print(f"[CONTEXT] {test_context}")
    print(f"[CONSTRAINTS] {test_constraints}")
    print("\n[Processing with dual engine...]")

    try:
        result = strategist.analyze(test_task, test_context, test_constraints)
        print(f"\n[RESULT]")
        print(f"  Analysis: {result.analysis}")
        print(f"  Strategy: {result.strategy}")
        print(f"  Recommendation: {result.recommendation}")
        print(f"  Data Insights: {result.data_insights[:2]}...")
        print(f"  Logic Chain: {result.logic_chain[:2]}...")
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
