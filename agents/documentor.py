"""
Hattz Empire - Documentor (DUAL ENGINE: Gemini 3.0 Pro + GPT-4o-mini)
산출물/문서 작성 전문 에이전트

비용 효율적인 조합:
- Engine 1 (Gemini): 대용량 컨텍스트, 구조화, 초안 작성
- Engine 2 (GPT-4o-mini): 저렴한 수정/보완/포맷팅
"""
from typing import Any, Optional
from dataclasses import dataclass

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from .base import (
    DualEngineAgent, EngineResponse, DualEngineResponse,
    ModelConfig, call_llm
)

try:
    from config import get_system_prompt, get_dual_engine
except ImportError:
    from ..config import get_system_prompt, get_dual_engine


@dataclass
class DocumentResult:
    """문서 작성 결과"""
    doc_type: str           # readme, spec, report, changelog, api_doc
    title: str              # 문서 제목
    content: str            # 문서 내용
    format: str             # markdown, yaml, json
    sections: list          # 섹션 목록
    metadata: dict          # 메타데이터
    engine_used: str        # 사용된 엔진


class Documentor(DualEngineAgent):
    """
    Documentor - 산출물/문서 작성 전문가

    Engine 1 (Gemini 3.0 Pro):
      - 대용량 컨텍스트 활용 (1M tokens)
      - 전체 코드베이스 분석 후 문서화
      - 구조화된 초안 작성

    Engine 2 (GPT-4o-mini):
      - 저렴한 비용 ($0.15/1M input, $0.60/1M output)
      - 빠른 수정/보완
      - 포맷팅/다듬기

    사용법:
        documentor = Documentor()

        # README 생성
        result = documentor.create_readme(project_info)

        # API 문서 생성
        result = documentor.create_api_doc(code_content)

        # 변경 로그 생성
        result = documentor.create_changelog(git_log)

        # 커스텀 문서
        result = documentor.create_document(doc_type, content, requirements)
    """

    def __init__(self):
        super().__init__("documentor")

    def _call_engine(self, model_config: ModelConfig, input_data: Any) -> EngineResponse:
        """개별 엔진 호출"""
        if isinstance(input_data, dict):
            prompt = input_data.get("prompt", str(input_data))
        else:
            prompt = str(input_data)

        return call_llm(model_config, self.system_prompt, prompt)

    def _merge_responses(
        self,
        response_1: EngineResponse,
        response_2: EngineResponse
    ) -> str:
        """
        primary_fallback 전략:
        - Gemini 응답이 있으면 사용
        - 없거나 에러면 GPT-4o-mini 응답 사용
        """
        if response_1.content and not response_1.error:
            return response_1.content
        elif response_2.content and not response_2.error:
            return response_2.content
        else:
            return f"Error: Engine 1 - {response_1.error}, Engine 2 - {response_2.error}"

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

        return {"content": content}

    def create_readme(self, project_info: dict, task_id: str = None) -> DocumentResult:
        """
        README.md 생성

        Args:
            project_info: {
                "name": "프로젝트명",
                "description": "설명",
                "structure": "폴더 구조",
                "features": ["기능1", "기능2"],
                "tech_stack": ["Python", "Flask"],
                "code_samples": "주요 코드 샘플"
            }
            task_id: Task ID

        Returns:
            DocumentResult
        """
        prompt = f"""# README.md 생성 요청

## 프로젝트 정보
{yaml.dump(project_info, allow_unicode=True) if HAS_YAML else str(project_info)}

## 요청
위 정보를 바탕으로 전문적인 README.md를 작성해주세요.

## 포함해야 할 섹션
1. 프로젝트 제목 + 한 줄 설명
2. 주요 기능 (Features)
3. 기술 스택 (Tech Stack)
4. 설치 방법 (Installation)
5. 사용법 (Usage)
6. 프로젝트 구조 (Project Structure)
7. 라이선스 (License)

## 출력 형식
Markdown으로 직접 작성해주세요 (YAML 아님).
```markdown
# 프로젝트명
...
```
"""

        # primary_fallback: Gemini 먼저 시도
        response = self.process_single({"prompt": prompt}, engine="engine_1", task_id=task_id)

        if response.error:
            # fallback to GPT-4o-mini
            response = self.process_single({"prompt": prompt}, engine="engine_2", task_id=task_id)
            engine_used = "gpt-4o-mini"
        else:
            engine_used = "gemini-3-pro"

        content = response.content or ""

        # markdown 코드블록 추출
        if "```markdown" in content:
            start = content.find("```markdown") + 11
            end = content.find("```", start)
            content = content[start:end].strip()

        return DocumentResult(
            doc_type="readme",
            title=project_info.get("name", "README"),
            content=content,
            format="markdown",
            sections=["Features", "Tech Stack", "Installation", "Usage", "Structure", "License"],
            metadata={"project_info": project_info},
            engine_used=engine_used
        )

    def create_api_doc(self, code_content: str, api_name: str = "API", task_id: str = None) -> DocumentResult:
        """
        API 문서 생성

        Args:
            code_content: API 코드 (endpoints, functions)
            api_name: API 이름
            task_id: Task ID

        Returns:
            DocumentResult
        """
        prompt = f"""# API 문서 생성 요청

## API 이름: {api_name}

## 코드
```python
{code_content[:10000]}
```

## 요청
위 코드를 분석하여 API 문서를 작성해주세요.

## 포함해야 할 내용
1. API 개요
2. 엔드포인트 목록 (있는 경우)
3. 각 함수/메서드 설명
   - 파라미터 (타입, 설명)
   - 반환값 (타입, 설명)
   - 예외
4. 사용 예시
5. 에러 코드 (해당시)

## 출력 형식
Markdown으로 직접 작성해주세요.
"""

        response = self.process_single({"prompt": prompt}, engine="engine_1", task_id=task_id)

        if response.error:
            response = self.process_single({"prompt": prompt}, engine="engine_2", task_id=task_id)
            engine_used = "gpt-4o-mini"
        else:
            engine_used = "gemini-3-pro"

        return DocumentResult(
            doc_type="api_doc",
            title=f"{api_name} Documentation",
            content=response.content or "",
            format="markdown",
            sections=["Overview", "Endpoints", "Functions", "Examples", "Errors"],
            metadata={"api_name": api_name},
            engine_used=engine_used
        )

    def create_changelog(self, git_log: str, version: str = "latest", task_id: str = None) -> DocumentResult:
        """
        CHANGELOG 생성

        Args:
            git_log: git log 출력 (--oneline or detailed)
            version: 버전 번호
            task_id: Task ID

        Returns:
            DocumentResult
        """
        prompt = f"""# CHANGELOG 생성 요청

## 버전: {version}

## Git 로그
```
{git_log[:8000]}
```

## 요청
위 git 로그를 분석하여 CHANGELOG.md를 작성해주세요.

## 형식 (Keep a Changelog 스타일)
```markdown
# Changelog

## [{version}] - YYYY-MM-DD

### Added
- 새로운 기능들

### Changed
- 변경된 기능들

### Fixed
- 수정된 버그들

### Removed
- 제거된 기능들
```

## 규칙
- 커밋 메시지를 분석하여 카테고리 분류
- 사용자 관점에서 이해하기 쉽게 작성
- 불필요한 내부 변경사항은 생략
"""

        # GPT-4o-mini가 이런 구조화 작업에 효율적
        response = self.process_single({"prompt": prompt}, engine="engine_2", task_id=task_id)

        if response.error:
            response = self.process_single({"prompt": prompt}, engine="engine_1", task_id=task_id)
            engine_used = "gemini-3-pro"
        else:
            engine_used = "gpt-4o-mini"

        return DocumentResult(
            doc_type="changelog",
            title=f"CHANGELOG - {version}",
            content=response.content or "",
            format="markdown",
            sections=["Added", "Changed", "Fixed", "Removed"],
            metadata={"version": version},
            engine_used=engine_used
        )

    def create_spec(self, requirements: str, spec_type: str = "technical", task_id: str = None) -> DocumentResult:
        """
        기술 스펙/기획 문서 생성

        Args:
            requirements: 요구사항 설명
            spec_type: "technical" | "product" | "api"
            task_id: Task ID

        Returns:
            DocumentResult
        """
        if spec_type == "technical":
            template = """
## 포함해야 할 섹션
1. 개요 (Overview)
2. 목표 (Goals)
3. 비목표 (Non-Goals)
4. 기술 설계 (Technical Design)
   - 아키텍처
   - 데이터 모델
   - API 설계
5. 구현 계획 (Implementation Plan)
6. 테스트 전략 (Test Strategy)
7. 리스크 및 대응 (Risks & Mitigations)
8. 타임라인 (Timeline) - 마일스톤만
"""
        elif spec_type == "product":
            template = """
## 포함해야 할 섹션
1. 배경 (Background)
2. 문제 정의 (Problem Statement)
3. 목표 사용자 (Target Users)
4. 주요 기능 (Key Features)
5. 사용자 플로우 (User Flow)
6. 성공 지표 (Success Metrics)
7. 향후 계획 (Future Considerations)
"""
        else:
            template = """
## 포함해야 할 섹션
1. API 개요
2. 인증 (Authentication)
3. 엔드포인트 (Endpoints)
4. 요청/응답 형식
5. 에러 핸들링
6. 예시
"""

        prompt = f"""# 스펙 문서 생성 요청

## 유형: {spec_type}

## 요구사항
{requirements}

{template}

## 출력 형식
Markdown으로 직접 작성해주세요.
전문적이고 구체적으로 작성하되, 과도한 장황함은 피해주세요.
"""

        # Gemini가 대용량 분석에 적합
        response = self.process_single({"prompt": prompt}, engine="engine_1", task_id=task_id)

        if response.error:
            response = self.process_single({"prompt": prompt}, engine="engine_2", task_id=task_id)
            engine_used = "gpt-4o-mini"
        else:
            engine_used = "gemini-3-pro"

        return DocumentResult(
            doc_type="spec",
            title=f"{spec_type.upper()} Specification",
            content=response.content or "",
            format="markdown",
            sections=[],
            metadata={"spec_type": spec_type, "requirements": requirements[:500]},
            engine_used=engine_used
        )

    def create_document(
        self,
        doc_type: str,
        content: str,
        requirements: str = "",
        task_id: str = None
    ) -> DocumentResult:
        """
        범용 문서 생성

        Args:
            doc_type: 문서 유형 (자유 형식)
            content: 문서화할 내용
            requirements: 추가 요구사항
            task_id: Task ID

        Returns:
            DocumentResult
        """
        prompt = f"""# 문서 생성 요청

## 문서 유형: {doc_type}

## 내용
{content[:15000]}

## 요구사항
{requirements if requirements else "전문적이고 명확하게 작성해주세요."}

## 출력 형식
Markdown으로 직접 작성해주세요.
"""

        # 듀얼 엔진 사용 (primary_fallback)
        result = self.process({"prompt": prompt}, task_id=task_id)

        return DocumentResult(
            doc_type=doc_type,
            title=doc_type,
            content=result.merged or "",
            format="markdown",
            sections=[],
            metadata={"requirements": requirements[:200]},
            engine_used="dual"
        )

    def polish_document(self, document: str, style: str = "professional", task_id: str = None) -> DocumentResult:
        """
        문서 다듬기 (GPT-4o-mini 사용 - 저렴)

        Args:
            document: 다듬을 문서
            style: "professional" | "casual" | "technical"
            task_id: Task ID

        Returns:
            DocumentResult
        """
        prompt = f"""# 문서 다듬기 요청

## 스타일: {style}

## 원본 문서
{document[:12000]}

## 요청
위 문서를 다음 기준으로 다듬어주세요:
1. 문법/맞춤법 교정
2. 문장 흐름 개선
3. 일관된 톤 유지 ({style})
4. 불필요한 반복 제거
5. 명확성 향상

원본 구조와 내용은 유지하면서 품질만 개선해주세요.

## 출력
다듬어진 문서를 직접 출력해주세요.
"""

        # GPT-4o-mini가 이런 작업에 비용 효율적
        response = self.process_single({"prompt": prompt}, engine="engine_2", task_id=task_id)

        return DocumentResult(
            doc_type="polished",
            title="Polished Document",
            content=response.content or document,
            format="markdown",
            sections=[],
            metadata={"style": style, "original_length": len(document)},
            engine_used="gpt-4o-mini"
        )


# =============================================================================
# Singleton
# =============================================================================

_documentor: Optional[Documentor] = None


def get_documentor() -> Documentor:
    """Documentor 싱글톤"""
    global _documentor
    if _documentor is None:
        _documentor = Documentor()
    return _documentor


# =============================================================================
# CLI Test
# =============================================================================

def main():
    """테스트"""
    print("\n" + "="*60)
    print("DOCUMENTOR TEST (Dual Engine: Gemini 3 Pro + GPT-4o-mini)")
    print("="*60)

    documentor = Documentor()

    print("\n[1] README 생성 테스트...")
    try:
        result = documentor.create_readme({
            "name": "Test Project",
            "description": "A test project for documentor",
            "features": ["Feature 1", "Feature 2"],
            "tech_stack": ["Python", "Flask"]
        })
        print(f"  Engine used: {result.engine_used}")
        print(f"  Content length: {len(result.content)} chars")
        print(f"  First 200 chars: {result.content[:200]}...")
    except Exception as e:
        print(f"  Error: {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
