"""
Hattz Empire - Researcher (DUAL ENGINE)
외부 데이터 검색 + 웹 리서치 + API 연동

Engine 1: Gemini 3.0 Pro (대용량 웹 데이터 처리, 검색 결과 분석)
Engine 2: Claude Opus 4.5 (정보 검증, 팩트체크, 요약)

Merge Strategy: consensus (둘의 분석 종합)
"""
from typing import Any, Optional
from dataclasses import dataclass
import re

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

from .base import DualEngineAgent, EngineResponse, call_llm

try:
    from config import ModelConfig, get_system_prompt
except ImportError:
    from ..config import ModelConfig, get_system_prompt


@dataclass
class WebSource:
    """웹 소스 정보"""
    url: str
    title: str
    snippet: str
    reliability: str  # high, medium, low, unknown


@dataclass
class ResearchFinding:
    """리서치 발견"""
    topic: str
    summary: str
    sources: list[WebSource]
    confidence: float
    contradictions: list[str]  # 상충되는 정보


@dataclass
class ResearchOutput:
    """Researcher 출력"""
    query: str                    # 원래 검색 쿼리
    findings: list[ResearchFinding]
    key_insights: list[str]       # 핵심 인사이트
    data_points: list[dict]       # 수집된 데이터 포인트
    sources_used: list[WebSource]
    warnings: list[str]           # 신뢰도 경고
    summary: str                  # 전체 요약
    confidence: float


class Researcher(DualEngineAgent):
    """
    Researcher - 외부 데이터 검색 및 분석

    사용법:
        researcher = Researcher()
        result = researcher.research("비트코인 최근 동향")
        print(result.merged.summary)
    """

    def __init__(self):
        super().__init__("researcher")

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
        lines = ["# Research Request\n"]

        if "query" in data:
            lines.append(f"## Query\n{data['query']}\n")

        if "context" in data:
            lines.append(f"## Context\n{data['context']}\n")

        if "web_results" in data:
            lines.append("## Web Search Results")
            for i, result in enumerate(data["web_results"], 1):
                lines.append(f"\n### Result {i}")
                lines.append(f"- Title: {result.get('title', 'N/A')}")
                lines.append(f"- URL: {result.get('url', 'N/A')}")
                lines.append(f"- Snippet: {result.get('snippet', 'N/A')}")
            lines.append("")

        if "focus_areas" in data:
            lines.append("## Focus Areas")
            for area in data["focus_areas"]:
                lines.append(f"- {area}")
            lines.append("")

        if "verify_claims" in data:
            lines.append("## Claims to Verify")
            for claim in data["verify_claims"]:
                lines.append(f"- {claim}")
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

        return self._extract_research_structure(content)

    def _extract_research_structure(self, content: str) -> dict:
        """리서치 구조 추출"""
        result = {
            "findings": [],
            "key_insights": [],
            "warnings": [],
            "summary": ""
        }

        lines = content.split("\n")
        current_section = None

        for line in lines:
            line_stripped = line.strip()

            # 섹션 감지
            if "insight" in line_stripped.lower() or "발견" in line_stripped:
                current_section = "insights"
            elif "warning" in line_stripped.lower() or "주의" in line_stripped:
                current_section = "warnings"
            elif "summary" in line_stripped.lower() or "요약" in line_stripped:
                current_section = "summary"

            # 불릿 포인트 추출
            if line_stripped.startswith("-") or line_stripped.startswith("•"):
                item = line_stripped[1:].strip()
                if current_section == "insights":
                    result["key_insights"].append(item)
                elif current_section == "warnings":
                    result["warnings"].append(item)

        # 요약 추출 (마지막 문단)
        paragraphs = content.split("\n\n")
        if paragraphs:
            result["summary"] = paragraphs[-1].strip()[:500]

        return result

    def _search_web(self, query: str, num_results: int = 5) -> list[dict]:
        """
        웹 검색 (실제 구현 필요)
        현재는 시뮬레이션 - 실제로는 Google Custom Search API 등 사용
        """
        if not HAS_REQUESTS:
            return [{
                "title": f"[시뮬레이션] {query} 관련 결과",
                "url": "https://example.com",
                "snippet": f"{query}에 대한 검색 결과입니다. 실제 API 연동 필요."
            }]

        # TODO: 실제 검색 API 연동
        # Google Custom Search API, Bing Search API, 또는 SerpAPI 등
        return [{
            "title": f"[검색 결과] {query}",
            "url": "https://search-pending.com",
            "snippet": f"외부 검색 API 연동 필요. Query: {query}"
        }]

    def _fetch_url(self, url: str) -> Optional[str]:
        """URL에서 컨텐츠 가져오기"""
        if not HAS_REQUESTS:
            return None

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            if HAS_BS4:
                soup = BeautifulSoup(response.text, "html.parser")
                # 스크립트, 스타일 제거
                for script in soup(["script", "style"]):
                    script.decompose()
                text = soup.get_text()
                # 공백 정리
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = '\n'.join(chunk for chunk in chunks if chunk)
                return text[:10000]  # 최대 10000자
            else:
                return response.text[:10000]

        except Exception as e:
            return f"[ERROR] Failed to fetch {url}: {str(e)}"

    def _merge_responses(
        self,
        response_1: EngineResponse,
        response_2: EngineResponse
    ) -> ResearchOutput:
        """
        두 엔진 응답 병합

        Gemini (검색): 대용량 데이터 처리, 패턴 발견
        Opus (검증): 팩트체크, 신뢰도 평가, 요약
        """
        parsed_gemini = self._parse_yaml_response(response_1.content or "")
        parsed_opus = self._parse_yaml_response(response_2.content or "")

        # Findings 병합
        findings = []

        gemini_findings = parsed_gemini.get("findings", [])
        for f in gemini_findings:
            if isinstance(f, dict):
                sources = []
                for s in f.get("sources", []):
                    if isinstance(s, dict):
                        sources.append(WebSource(
                            url=s.get("url", ""),
                            title=s.get("title", ""),
                            snippet=s.get("snippet", ""),
                            reliability=s.get("reliability", "unknown")
                        ))
                findings.append(ResearchFinding(
                    topic=f.get("topic", ""),
                    summary=f.get("summary", ""),
                    sources=sources,
                    confidence=f.get("confidence", 0.5),
                    contradictions=f.get("contradictions", [])
                ))

        # Key Insights 합집합
        insights_gemini = parsed_gemini.get("key_insights", [])
        insights_opus = parsed_opus.get("key_insights", [])
        key_insights = list(set(insights_gemini + insights_opus))

        # Data Points
        data_gemini = parsed_gemini.get("data_points", [])
        data_opus = parsed_opus.get("data_points", [])
        data_points = data_gemini + data_opus

        # Sources
        sources_used = []
        for f in findings:
            sources_used.extend(f.sources)

        # Warnings (Opus 검증 결과 우선)
        warnings_gemini = parsed_gemini.get("warnings", [])
        warnings_opus = parsed_opus.get("warnings", [])
        warnings = list(set(warnings_opus + warnings_gemini))

        # Summary (Opus 요약 우선)
        summary_opus = parsed_opus.get("summary", "")
        summary_gemini = parsed_gemini.get("summary", "")
        summary = summary_opus if summary_opus else summary_gemini

        # Confidence
        conf_gemini = parsed_gemini.get("confidence", 0.5)
        conf_opus = parsed_opus.get("confidence", 0.5)
        confidence = (conf_gemini + conf_opus) / 2

        # 경고가 많으면 confidence 낮춤
        if len(warnings) > 3:
            confidence *= 0.8

        return ResearchOutput(
            query="",  # 나중에 채워짐
            findings=findings,
            key_insights=key_insights,
            data_points=data_points,
            sources_used=sources_used,
            warnings=warnings,
            summary=summary if summary else "[분석 결과 없음]",
            confidence=confidence
        )

    def research(
        self,
        query: str,
        context: str = "",
        focus_areas: list = None,
        verify_claims: list = None,
        search_web: bool = True
    ) -> ResearchOutput:
        """
        외부 데이터 리서치

        Args:
            query: 검색/연구 쿼리
            context: 추가 컨텍스트
            focus_areas: 집중할 영역
            verify_claims: 검증할 주장들
            search_web: 웹 검색 수행 여부

        Returns:
            ResearchOutput
        """
        input_data = {
            "query": query,
            "context": context,
            "focus_areas": focus_areas or ["accuracy", "recency", "reliability"],
            "verify_claims": verify_claims or []
        }

        # 웹 검색 수행
        if search_web:
            web_results = self._search_web(query)
            input_data["web_results"] = web_results

        result = self.process(input_data)
        output = result.merged
        output.query = query

        return output

    def verify_info(self, claim: str, sources: list[str] = None) -> dict:
        """
        정보 검증

        Args:
            claim: 검증할 주장
            sources: 확인할 소스 URL들

        Returns:
            검증 결과 딕셔너리
        """
        input_data = {
            "query": f"팩트체크: {claim}",
            "verify_claims": [claim],
            "context": "이 주장의 진위를 검증하라. 근거와 함께 판정하라."
        }

        if sources:
            web_results = []
            for url in sources[:5]:  # 최대 5개
                content = self._fetch_url(url)
                if content:
                    web_results.append({
                        "url": url,
                        "title": url.split("/")[-1],
                        "snippet": content[:500]
                    })
            input_data["web_results"] = web_results

        result = self.process(input_data)
        parsed = self._parse_yaml_response(
            result.engine_2.content or ""  # Opus 검증 결과 사용
        )

        return {
            "claim": claim,
            "verdict": parsed.get("verdict", "unverified"),
            "confidence": parsed.get("confidence", 0.5),
            "evidence": parsed.get("evidence", []),
            "warnings": parsed.get("warnings", [])
        }

    def quick_search(self, query: str, engine: str = "engine_1") -> str:
        """
        빠른 단일 엔진 검색

        Args:
            query: 검색 쿼리
            engine: "engine_1" (Gemini) 또는 "engine_2" (Opus)

        Returns:
            검색 결과 텍스트
        """
        web_results = self._search_web(query)
        input_data = {
            "query": query,
            "web_results": web_results
        }
        formatted = self._format_request(input_data)

        response = self.process_single(formatted, engine)
        return response.content or "[검색 결과 없음]"


# =============================================================================
# Singleton
# =============================================================================

_researcher: Optional[Researcher] = None


def get_researcher() -> Researcher:
    """Researcher 싱글톤"""
    global _researcher
    if _researcher is None:
        _researcher = Researcher()
    return _researcher


# =============================================================================
# CLI Test
# =============================================================================

def main():
    """테스트"""
    print("\n" + "="*60)
    print("RESEARCHER TEST (Dual Engine: Gemini + Opus)")
    print("="*60)

    researcher = Researcher()

    test_query = "비트코인 2026년 전망"

    print(f"\n[QUERY] {test_query}")
    print("\n[Processing with dual engine...]")

    try:
        result = researcher.research(test_query)
        print(f"\n[RESULT]")
        print(f"  Confidence: {result.confidence}")
        print(f"  Findings: {len(result.findings)}")
        print(f"  Key Insights: {len(result.key_insights)}")
        for insight in result.key_insights[:3]:
            print(f"    - {insight[:60]}...")
        print(f"  Warnings: {len(result.warnings)}")
        for warning in result.warnings[:2]:
            print(f"    ⚠️ {warning[:60]}...")
        print(f"\n[SUMMARY]")
        print(f"  {result.summary[:300]}...")
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
