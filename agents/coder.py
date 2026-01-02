"""
Hattz Empire - Coder (DUAL ENGINE)
클린 코드 생성 + 복잡한 알고리즘 설계

Engine 1: Claude Sonnet 4 (빠른 코드 생성, 클린 코드)
Engine 2: GPT-5.2 Thinking Extended (아키텍처 설계, 복잡한 알고리즘)

Merge Strategy: primary_fallback (Sonnet 우선, 복잡하면 GPT)
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
class CodeOutput:
    """Coder 출력"""
    code: str                     # 생성된 코드
    files: list[dict]             # 파일 목록 [{path, content}]
    dependencies: list[str]       # 필요한 패키지
    complexity: str               # low/medium/high
    notes: list[str]              # 구현 노트
    tests_suggested: list[str]    # 제안된 테스트


class Coder(DualEngineAgent):
    """
    Coder - 코드 생성

    사용법:
        coder = Coder()
        result = coder.generate("RSI 계산 함수 만들어줘")
        print(result.merged.code)
    """

    def __init__(self):
        super().__init__("coder")

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
        lines = ["# Code Request\n"]

        if "task" in data:
            lines.append(f"## Task\n{data['task']}\n")

        if "context" in data:
            lines.append(f"## Context\n{data['context']}\n")

        if "requirements" in data:
            lines.append("## Requirements")
            for r in data["requirements"]:
                lines.append(f"- {r}")
            lines.append("")

        if "existing_code" in data:
            lines.append("## Existing Code")
            lines.append(f"```python\n{data['existing_code']}\n```\n")

        if "style" in data:
            lines.append(f"## Style Guide\n{data['style']}\n")

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

        # YAML 파싱 실패시 코드 블록 추출
        return self._extract_code_blocks(content)

    def _extract_code_blocks(self, content: str) -> dict:
        """코드 블록 추출"""
        result = {"code": "", "files": [], "notes": []}

        # ```python ... ``` 블록 찾기
        code_blocks = []
        start = 0
        while True:
            py_start = content.find("```python", start)
            if py_start == -1:
                break
            py_end = content.find("```", py_start + 9)
            if py_end == -1:
                break
            code_blocks.append(content[py_start + 9:py_end].strip())
            start = py_end + 3

        if code_blocks:
            result["code"] = code_blocks[0]
            for i, block in enumerate(code_blocks):
                result["files"].append({
                    "path": f"code_{i}.py",
                    "content": block
                })

        # 노트 추출 (코드 블록 외의 텍스트)
        notes = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                notes.append(line[1:].strip())
            elif line.startswith("#") and not line.startswith("##"):
                notes.append(line[1:].strip())

        result["notes"] = notes[:5]  # 최대 5개

        return result

    def _merge_responses(
        self,
        response_1: EngineResponse,
        response_2: EngineResponse
    ) -> CodeOutput:
        """
        두 엔진 응답 병합

        Sonnet (속도): 빠른 구현, 클린 코드
        GPT (설계): 아키텍처, 복잡한 로직

        Strategy: primary_fallback
        - 기본: Sonnet 코드 사용
        - Sonnet 실패 또는 복잡한 경우: GPT 사용
        """
        parsed_sonnet = self._parse_yaml_response(response_1.content or "")
        parsed_gpt = self._parse_yaml_response(response_2.content or "")

        # 코드: Sonnet 우선
        code_sonnet = parsed_sonnet.get("code", "")
        code_gpt = parsed_gpt.get("code", "")

        # Sonnet 코드가 있으면 사용, 없으면 GPT
        if code_sonnet and len(code_sonnet) > 50:
            primary_code = code_sonnet
            primary_parsed = parsed_sonnet
        else:
            primary_code = code_gpt
            primary_parsed = parsed_gpt

        # Files
        files_sonnet = parsed_sonnet.get("files", [])
        files_gpt = parsed_gpt.get("files", [])
        files = files_sonnet if files_sonnet else files_gpt

        # Dependencies: 합집합
        deps_sonnet = parsed_sonnet.get("dependencies", [])
        deps_gpt = parsed_gpt.get("dependencies", [])
        dependencies = list(set(deps_sonnet + deps_gpt))

        # Complexity: GPT 판단 우선 (더 분석적)
        complexity = parsed_gpt.get("complexity") or parsed_sonnet.get("complexity", "medium")

        # Notes: 합집합
        notes_sonnet = parsed_sonnet.get("notes", [])
        notes_gpt = parsed_gpt.get("notes", [])
        notes = list(set(notes_sonnet + notes_gpt))

        # Tests: 합집합
        tests_sonnet = parsed_sonnet.get("tests_suggested", [])
        tests_gpt = parsed_gpt.get("tests_suggested", [])
        tests = list(set(tests_sonnet + tests_gpt))

        return CodeOutput(
            code=primary_code,
            files=files,
            dependencies=dependencies,
            complexity=complexity,
            notes=notes,
            tests_suggested=tests
        )

    def generate(
        self,
        task: str,
        context: str = "",
        requirements: list = None,
        existing_code: str = ""
    ) -> CodeOutput:
        """
        코드 생성

        Args:
            task: 구현할 작업
            context: 컨텍스트
            requirements: 요구사항
            existing_code: 기존 코드 (수정/확장시)

        Returns:
            CodeOutput
        """
        input_data = {
            "task": task,
            "context": context,
            "requirements": requirements or [],
        }
        if existing_code:
            input_data["existing_code"] = existing_code

        result = self.process(input_data)
        return result.merged

    def quick_generate(self, task: str, engine: str = "engine_1") -> str:
        """
        빠른 단일 엔진 코드 생성

        Args:
            task: 작업
            engine: "engine_1" (Sonnet) 또는 "engine_2" (GPT)

        Returns:
            생성된 코드
        """
        response = self.process_single(task, engine)
        parsed = self._parse_yaml_response(response.content or "")
        return parsed.get("code", response.content or "")


# =============================================================================
# Singleton
# =============================================================================

_coder: Optional[Coder] = None


def get_coder() -> Coder:
    """Coder 싱글톤"""
    global _coder
    if _coder is None:
        _coder = Coder()
    return _coder


# =============================================================================
# CLI Test
# =============================================================================

def main():
    """테스트"""
    print("\n" + "="*60)
    print("CODER TEST (Dual Engine: Sonnet + GPT-5.2)")
    print("="*60)

    coder = Coder()

    test_task = "RSI 계산 함수 만들어줘"
    test_requirements = [
        "pandas 사용",
        "type hints 필수",
        "docstring 포함"
    ]

    print(f"\n[TASK] {test_task}")
    print(f"[REQUIREMENTS] {test_requirements}")
    print("\n[Processing with dual engine...]")

    try:
        result = coder.generate(test_task, requirements=test_requirements)
        print(f"\n[RESULT]")
        print(f"  Complexity: {result.complexity}")
        print(f"  Dependencies: {result.dependencies}")
        print(f"  Files: {len(result.files)}")
        print(f"  Notes: {result.notes[:2]}...")
        print(f"\n[CODE PREVIEW]")
        print(result.code[:500] + "..." if len(result.code) > 500 else result.code)
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
