"""
Hattz Empire - Analyst (SINGLE ENGINE: Gemini 3.0 Pro)
대용량 로그 분석 + 시스템 모니터링

Gemini 3.0 Pro의 1M 토큰 컨텍스트를 활용:
- Stream 로그 전체 분석
- 과거 작업 맥락 복원
- 시스템 메트릭 분석
"""
from typing import Any, Optional
from dataclasses import dataclass
from pathlib import Path
import json
import os

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from .base import EngineResponse, APIClient

try:
    from config import get_single_engine, get_system_prompt
    from stream import get_stream, StreamLogger
except ImportError:
    from ..config import get_single_engine, get_system_prompt
    from ..stream import get_stream, StreamLogger


@dataclass
class AnalysisResult:
    """분석 결과"""
    analysis_type: str          # log_summary, task_search, system_status, pattern_analysis
    summary: str                # 요약
    details: list               # 상세 내용
    insights: list              # 인사이트
    recommendations: list       # 권장 사항
    metadata: dict              # 메타데이터 (분석 범위 등)
    confidence: float = 0.9


class Analyst:
    """
    Analyst - Gemini 3.0 Pro 단일 엔진

    사용법:
        analyst = Analyst()

        # 오늘 로그 요약
        result = analyst.summarize_today()

        # 특정 키워드 검색
        result = analyst.search_logs("RSI")

        # 시스템 상태
        result = analyst.system_status()

        # 과거 맥락 복원
        result = analyst.restore_context("어제 뭐했지?")
    """

    def __init__(self):
        self.role = "analyst"
        self.model_config = get_single_engine("analyst")
        self.system_prompt = get_system_prompt("analyst")
        self.stream: StreamLogger = get_stream()

        if not self.model_config:
            raise ValueError("Analyst model config not found")

    def _call_gemini(self, prompt: str) -> EngineResponse:
        """Gemini API 호출"""
        try:
            model = APIClient.get_google(self.model_config.model_id)
            if not model:
                return EngineResponse(content=None, error="Gemini model not available")

            full_prompt = f"{self.system_prompt}\n\n---\n\n{prompt}"
            response = model.generate_content(full_prompt)

            return EngineResponse(
                content=response.text,
                raw_response=response,
                model=self.model_config.model_id
            )
        except Exception as e:
            return EngineResponse(content=None, error=str(e))

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

        return {"summary": content}

    def _format_logs_for_analysis(self, logs: list) -> str:
        """로그를 분석용 텍스트로 변환"""
        lines = []
        for log in logs:
            t = log.get("t", "")[:19]  # ISO format에서 시간까지만
            from_agent = log.get("from_agent", "unknown")
            msg_type = log.get("type", "")
            content = log.get("content", "")

            if isinstance(content, dict):
                content = json.dumps(content, ensure_ascii=False)[:200]
            elif isinstance(content, str):
                content = content[:200]

            lines.append(f"[{t}] {from_agent} ({msg_type}): {content}")

        return "\n".join(lines)

    def summarize_today(self) -> AnalysisResult:
        """
        오늘 로그 요약

        Returns:
            AnalysisResult
        """
        logs = self.stream.read_today()

        if not logs:
            return AnalysisResult(
                analysis_type="log_summary",
                summary="오늘 로그가 없습니다.",
                details=[],
                insights=[],
                recommendations=["새로운 작업을 시작해보세요."],
                metadata={"logs_analyzed": 0},
                confidence=1.0
            )

        log_text = self._format_logs_for_analysis(logs)

        prompt = f"""# 오늘의 로그 분석 요청

## 로그 데이터 ({len(logs)}개 메시지)
{log_text}

## 요청
1. 오늘 진행된 작업들을 요약해주세요
2. 주요 의사결정/결과를 정리해주세요
3. 발견된 패턴이나 인사이트가 있으면 알려주세요

YAML 형식으로 응답해주세요.
"""

        response = self._call_gemini(prompt)

        if response.error:
            return AnalysisResult(
                analysis_type="log_summary",
                summary=f"분석 실패: {response.error}",
                details=[],
                insights=[],
                recommendations=[],
                metadata={"logs_analyzed": len(logs), "error": response.error},
                confidence=0.0
            )

        parsed = self._parse_yaml_response(response.content or "")

        return AnalysisResult(
            analysis_type="log_summary",
            summary=parsed.get("summary", response.content or ""),
            details=parsed.get("details", []),
            insights=parsed.get("insights", []),
            recommendations=parsed.get("recommendations", []),
            metadata={
                "logs_analyzed": len(logs),
                "time_range": f"{logs[0].get('t', '')[:10]} ~ {logs[-1].get('t', '')[:10]}"
            },
            confidence=parsed.get("confidence", 0.85)
        )

    def search_logs(self, keyword: str, date_str: str = None) -> AnalysisResult:
        """
        로그에서 키워드 검색

        Args:
            keyword: 검색할 키워드
            date_str: 검색할 날짜 (YYYY-MM-DD, 없으면 오늘)

        Returns:
            AnalysisResult
        """
        if date_str:
            logs = self.stream.read_date(date_str)
        else:
            logs = self.stream.read_today()

        # 키워드 포함 로그 필터링
        matched_logs = []
        for log in logs:
            content = str(log.get("content", ""))
            if keyword.lower() in content.lower():
                matched_logs.append(log)

        if not matched_logs:
            return AnalysisResult(
                analysis_type="task_search",
                summary=f"'{keyword}' 관련 로그를 찾을 수 없습니다.",
                details=[],
                insights=[],
                recommendations=[],
                metadata={"keyword": keyword, "total_logs": len(logs), "matched": 0},
                confidence=1.0
            )

        log_text = self._format_logs_for_analysis(matched_logs)

        prompt = f"""# 로그 검색 분석 요청

## 검색 키워드: "{keyword}"

## 매칭된 로그 ({len(matched_logs)}개)
{log_text}

## 요청
1. 이 키워드와 관련된 작업들을 정리해주세요
2. 주요 내용을 요약해주세요
3. 관련된 Task ID가 있으면 나열해주세요

YAML 형식으로 응답해주세요.
"""

        response = self._call_gemini(prompt)
        parsed = self._parse_yaml_response(response.content or "")

        return AnalysisResult(
            analysis_type="task_search",
            summary=parsed.get("summary", response.content or ""),
            details=parsed.get("details", []),
            insights=parsed.get("insights", []),
            recommendations=parsed.get("recommendations", []),
            metadata={
                "keyword": keyword,
                "total_logs": len(logs),
                "matched": len(matched_logs)
            },
            confidence=parsed.get("confidence", 0.85)
        )

    def analyze_task(self, task_id: str) -> AnalysisResult:
        """
        특정 Task 분석

        Args:
            task_id: Task ID

        Returns:
            AnalysisResult
        """
        date_str = task_id.split("_")[0]  # "2026-01-02_001" -> "2026-01-02"
        logs = self.stream.find_by_task(task_id, date_str)

        if not logs:
            return AnalysisResult(
                analysis_type="task_search",
                summary=f"Task '{task_id}' 로그를 찾을 수 없습니다.",
                details=[],
                insights=[],
                recommendations=[],
                metadata={"task_id": task_id},
                confidence=1.0
            )

        log_text = self._format_logs_for_analysis(logs)

        prompt = f"""# Task 분석 요청

## Task ID: {task_id}

## 로그 ({len(logs)}개 메시지)
{log_text}

## 요청
1. 이 Task의 목적/목표를 파악해주세요
2. 진행 경과를 요약해주세요
3. 현재 상태 (완료/진행중/실패)를 판단해주세요
4. 관련 에이전트들의 역할을 정리해주세요

YAML 형식으로 응답해주세요.
"""

        response = self._call_gemini(prompt)
        parsed = self._parse_yaml_response(response.content or "")

        return AnalysisResult(
            analysis_type="task_search",
            summary=parsed.get("summary", response.content or ""),
            details=parsed.get("details", []),
            insights=parsed.get("insights", []),
            recommendations=parsed.get("recommendations", []),
            metadata={
                "task_id": task_id,
                "message_count": len(logs),
                "agents": list(set(log.get("from_agent", "").split(".")[0] for log in logs))
            },
            confidence=parsed.get("confidence", 0.85)
        )

    def system_status(self) -> AnalysisResult:
        """
        시스템 상태 분석

        Returns:
            AnalysisResult
        """
        metrics = self._collect_system_metrics()

        prompt = f"""# 시스템 상태 분석 요청

## 수집된 메트릭
```json
{json.dumps(metrics, indent=2, ensure_ascii=False)}
```

## 요청
1. 현재 시스템 상태를 평가해주세요
2. 이상 징후가 있으면 알려주세요
3. 권장 사항이 있으면 제시해주세요

YAML 형식으로 응답해주세요.
"""

        response = self._call_gemini(prompt)
        parsed = self._parse_yaml_response(response.content or "")

        return AnalysisResult(
            analysis_type="system_status",
            summary=parsed.get("summary", response.content or ""),
            details=parsed.get("details", []),
            insights=parsed.get("insights", []),
            recommendations=parsed.get("recommendations", []),
            metadata={"raw_metrics": metrics},
            confidence=parsed.get("confidence", 0.85)
        )

    def _collect_system_metrics(self) -> dict:
        """시스템 메트릭 수집 (psutil 사용)"""
        if not HAS_PSUTIL:
            return {"error": "psutil not installed. Run: pip install psutil"}

        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            metrics = {
                "cpu": {
                    "percent": cpu_percent,
                    "count": psutil.cpu_count()
                },
                "memory": {
                    "total_gb": round(memory.total / (1024**3), 2),
                    "used_gb": round(memory.used / (1024**3), 2),
                    "percent": memory.percent
                },
                "disk": {
                    "total_gb": round(disk.total / (1024**3), 2),
                    "used_gb": round(disk.used / (1024**3), 2),
                    "percent": disk.percent
                }
            }

            # Docker 체크 (가능하면)
            try:
                import subprocess
                result = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}: {{.Status}}"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    containers = result.stdout.strip().split("\n") if result.stdout.strip() else []
                    metrics["docker"] = {"containers": containers}
            except:
                metrics["docker"] = {"status": "not available"}

            return metrics

        except Exception as e:
            return {"error": str(e)}

    def restore_context(self, query: str) -> AnalysisResult:
        """
        과거 맥락 복원 (자연어 질의)

        Args:
            query: "어제 뭐했지?", "RSI 전략 어떻게 됐어?" 등

        Returns:
            AnalysisResult
        """
        # 최근 7일치 로그 수집 (대용량 처리)
        from datetime import datetime, timedelta

        all_logs = []
        for i in range(7):
            date = datetime.now() - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            logs = self.stream.read_date(date_str)
            all_logs.extend(logs)

        if not all_logs:
            return AnalysisResult(
                analysis_type="pattern_analysis",
                summary="분석할 로그가 없습니다.",
                details=[],
                insights=[],
                recommendations=[],
                metadata={"query": query, "logs_analyzed": 0},
                confidence=1.0
            )

        log_text = self._format_logs_for_analysis(all_logs[-1000:])  # 최근 1000개만

        prompt = f"""# 맥락 복원 요청

## 질문
"{query}"

## 최근 로그 (최대 1000개)
{log_text}

## 요청
1. 질문에 대한 답을 로그에서 찾아 정리해주세요
2. 관련된 작업들을 시간순으로 나열해주세요
3. 현재 상태와 다음 단계를 제안해주세요

YAML 형식으로 응답해주세요.
"""

        response = self._call_gemini(prompt)
        parsed = self._parse_yaml_response(response.content or "")

        return AnalysisResult(
            analysis_type="pattern_analysis",
            summary=parsed.get("summary", response.content or ""),
            details=parsed.get("details", []),
            insights=parsed.get("insights", []),
            recommendations=parsed.get("recommendations", []),
            metadata={
                "query": query,
                "logs_analyzed": len(all_logs),
                "days_covered": 7
            },
            confidence=parsed.get("confidence", 0.85)
        )


# =============================================================================
# Singleton
# =============================================================================

_analyst: Optional[Analyst] = None


def get_analyst() -> Analyst:
    """Analyst 싱글톤"""
    global _analyst
    if _analyst is None:
        _analyst = Analyst()
    return _analyst


# =============================================================================
# CLI Test
# =============================================================================

def main():
    """테스트"""
    print("\n" + "="*60)
    print("ANALYST TEST (Single Engine: Gemini 3.0 Pro)")
    print("="*60)

    analyst = Analyst()

    print("\n[1] 오늘 로그 요약...")
    try:
        result = analyst.summarize_today()
        print(f"  Summary: {result.summary[:200]}...")
        print(f"  Logs analyzed: {result.metadata.get('logs_analyzed', 0)}")
    except Exception as e:
        print(f"  Error: {e}")

    print("\n[2] 시스템 상태...")
    try:
        result = analyst.system_status()
        print(f"  Summary: {result.summary[:200]}...")
        print(f"  Metrics: {result.metadata.get('raw_metrics', {})}")
    except Exception as e:
        print(f"  Error: {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
