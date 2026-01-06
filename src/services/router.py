"""
Hattz Empire - Router Agent (v2.3)
CEO 완성본 - PM 병목 해소를 위한 자동 태스크 라우팅

v2.3 핵심 개선사항:
1. PM 병목 해소: 단순 요청은 PM 경유 없이 직접 라우팅
2. 응답 속도 향상: 키워드 기반 빠른 라우팅 (0ms)
3. CEO 제어권: 프리픽스로 강제 라우팅 가능

라우팅 방식:
┌──────────────────────────────────────────────────────────────┐
│  1. CEO 프리픽스 (강제, confidence=1.0)                     │
│     - "검색/" → Researcher                                  │
│     - "코딩/" → Coder                                       │
│     - "분석/" → Excavator                                   │
│     - "최고/" → PM (VIP 모드)                               │
├──────────────────────────────────────────────────────────────┤
│  2. 키워드 기반 (confidence=0.3~0.7)                        │
│     - "구현", "만들어" → Coder                              │
│     - "테스트", "검증" → QA                                 │
│     - "분석", "구조" → Excavator                            │
│     - "검색", "조사" → Researcher                           │
├──────────────────────────────────────────────────────────────┤
│  3. LLM 기반 (fallback, confidence varies)                  │
│     - 키워드 매칭 실패 시 LLM으로 의도 분석                 │
│     - 비용 발생하므로 최후 수단                             │
└──────────────────────────────────────────────────────────────┘

사용 예시:
```python
from src.services.router import quick_route, AgentType

decision = quick_route("코딩/ 로그인 기능 만들어줘")
# → AgentType.CODER, confidence=1.0

decision = quick_route("이 버그 좀 고쳐줘")
# → AgentType.CODER, confidence=0.4 (키워드 "고쳐")
```

연동 파일:
- src/api/chat.py: auto_route_agent()
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum


class AgentType(str, Enum):
    """에이전트 타입"""
    PM = "pm"                    # 프로젝트 매니저 (복합 태스크)
    CODER = "coder"             # 코드 작성
    EXCAVATOR = "excavator"     # 코드 분석/탐색
    QA = "qa"                   # 품질 검증
    RESEARCHER = "researcher"   # 리서치
    STRATEGIST = "strategist"   # 전략 분석
    ANALYST = "analyst"         # 데이터 분석


@dataclass
class AgentInfo:
    """에이전트 정보"""
    type: AgentType
    name: str
    description: str
    keywords: List[str]
    priority: int = 0  # 높을수록 우선


@dataclass
class RouteDecision:
    """라우팅 결정"""
    agent: AgentType
    confidence: float  # 0.0 ~ 1.0
    reason: str
    reframed_task: str
    is_multi_agent: bool = False
    sub_tasks: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Agent Registry
# =============================================================================

AGENT_REGISTRY: Dict[AgentType, AgentInfo] = {
    AgentType.CODER: AgentInfo(
        type=AgentType.CODER,
        name="Coder",
        description="코드 작성, 구현, 버그 수정 전문가",
        keywords=["구현", "코딩", "작성", "만들어", "추가", "수정", "버그", "fix", "implement", "create", "add", "write"],
        priority=10
    ),
    AgentType.EXCAVATOR: AgentInfo(
        type=AgentType.EXCAVATOR,
        name="Excavator",
        description="코드 분석, 탐색, 이해 전문가",
        keywords=["분석", "찾아", "어디", "뭐야", "설명", "이해", "구조", "analyze", "find", "where", "what", "explain"],
        priority=9
    ),
    AgentType.QA: AgentInfo(
        type=AgentType.QA,
        name="QA",
        description="테스트, 품질 검증, 코드 리뷰 전문가",
        keywords=["테스트", "검증", "확인", "리뷰", "test", "verify", "check", "review", "quality", "unittest", "pytest", "테스트 작성", "테스트 코드"],
        priority=11  # Coder보다 높게 - "테스트 작성"은 QA로 라우팅
    ),
    AgentType.RESEARCHER: AgentInfo(
        type=AgentType.RESEARCHER,
        name="Researcher",
        description="정보 수집, 리서치, 문서화 전문가",
        keywords=["검색", "조사", "알아봐", "찾아봐", "research", "search", "lookup", "documentation"],
        priority=7
    ),
    AgentType.ANALYST: AgentInfo(
        type=AgentType.ANALYST,
        name="Analyst",
        description="데이터 분석, 통계, 시각화 전문가",
        keywords=["데이터", "통계", "분석해", "그래프", "차트", "data", "statistics", "chart", "visualize"],
        priority=6
    ),
    AgentType.STRATEGIST: AgentInfo(
        type=AgentType.STRATEGIST,
        name="Strategist",
        description="전략 수립, 아키텍처, 설계 전문가",
        keywords=["전략", "설계", "아키텍처", "계획", "strategy", "design", "architecture", "plan"],
        priority=5
    ),
    AgentType.PM: AgentInfo(
        type=AgentType.PM,
        name="PM",
        description="복합 태스크 조율, 프로젝트 관리",
        keywords=["프로젝트", "전체", "여러", "복합", "project", "overall", "multiple", "coordinate"],
        priority=1  # 낮은 우선순위 (다른 것에 매칭 안 되면 PM)
    ),
}


class Router:
    """
    태스크 라우터

    사용자 요청을 분석하여 적절한 에이전트로 라우팅
    """

    def __init__(
        self,
        llm_router: Optional[Callable[[str], str]] = None,
        use_llm_fallback: bool = True,
    ):
        """
        Args:
            llm_router: LLM 기반 라우팅 함수 (없으면 키워드만 사용)
            use_llm_fallback: 키워드 매칭 실패 시 LLM 사용 여부
        """
        self.llm_router = llm_router
        self.use_llm_fallback = use_llm_fallback

    def route(self, user_request: str) -> RouteDecision:
        """
        태스크 라우팅

        Args:
            user_request: 사용자 요청

        Returns:
            RouteDecision
        """
        # 1) CEO 프리픽스 체크 (강제 라우팅)
        forced = self._check_forced_routing(user_request)
        if forced:
            return forced

        # 2) 키워드 기반 라우팅
        keyword_result = self._keyword_routing(user_request)
        if keyword_result.confidence >= 0.7:
            return keyword_result

        # 3) LLM 기반 라우팅 (키워드 실패 시)
        if self.llm_router and self.use_llm_fallback:
            llm_result = self._llm_routing(user_request)
            if llm_result.confidence > keyword_result.confidence:
                return llm_result

        # 4) 기본값: PM
        if keyword_result.confidence < 0.3:
            return RouteDecision(
                agent=AgentType.PM,
                confidence=0.5,
                reason="No clear match, routing to PM for coordination",
                reframed_task=user_request
            )

        return keyword_result

    def _check_forced_routing(self, request: str) -> Optional[RouteDecision]:
        """CEO 프리픽스로 강제 라우팅 체크"""
        # 최고/ → PM (VIP)
        if request.startswith("최고/"):
            return RouteDecision(
                agent=AgentType.PM,
                confidence=1.0,
                reason="CEO prefix: 최고/ → VIP mode",
                reframed_task=request[3:].strip()
            )

        # 검색/ → RESEARCHER
        if request.startswith("검색/"):
            return RouteDecision(
                agent=AgentType.RESEARCHER,
                confidence=1.0,
                reason="CEO prefix: 검색/ → Researcher",
                reframed_task=request[3:].strip()
            )

        # 코딩/ → CODER
        if request.startswith("코딩/"):
            return RouteDecision(
                agent=AgentType.CODER,
                confidence=1.0,
                reason="CEO prefix: 코딩/ → Coder",
                reframed_task=request[3:].strip()
            )

        # 분석/ → EXCAVATOR
        if request.startswith("분석/"):
            return RouteDecision(
                agent=AgentType.EXCAVATOR,
                confidence=1.0,
                reason="CEO prefix: 분석/ → Excavator",
                reframed_task=request[3:].strip()
            )

        return None

    def _keyword_routing(self, request: str) -> RouteDecision:
        """키워드 기반 라우팅"""
        request_lower = request.lower()
        scores: Dict[AgentType, float] = {}

        for agent_type, info in AGENT_REGISTRY.items():
            score = 0.0
            matched_keywords = []

            for keyword in info.keywords:
                if keyword.lower() in request_lower:
                    score += 1.0
                    matched_keywords.append(keyword)

            # 우선순위 보너스
            if score > 0:
                score += info.priority * 0.1

            scores[agent_type] = score
            if matched_keywords:
                scores[agent_type] = score

        if not scores or max(scores.values()) == 0:
            return RouteDecision(
                agent=AgentType.PM,
                confidence=0.2,
                reason="No keyword matches",
                reframed_task=request
            )

        best_agent = max(scores, key=scores.get)
        best_score = scores[best_agent]

        # Confidence 계산 (최대 1.0)
        confidence = min(1.0, best_score / 5.0)

        return RouteDecision(
            agent=best_agent,
            confidence=confidence,
            reason=f"Keyword match: {AGENT_REGISTRY[best_agent].name}",
            reframed_task=request
        )

    def _llm_routing(self, request: str) -> RouteDecision:
        """LLM 기반 라우팅"""
        try:
            agents_list = "\n".join([
                f"- {info.name}: {info.description}"
                for info in AGENT_REGISTRY.values()
            ])

            prompt = f"""Analyze this user request and select the most appropriate agent.

[AVAILABLE AGENTS]
{agents_list}

[USER REQUEST]
{request}

[OUTPUT FORMAT]
AGENT: <agent_name>
CONFIDENCE: <0.0-1.0>
REASON: <why this agent>
REFRAMED_TASK: <clarified task for the agent>"""

            response = self.llm_router(prompt)
            return self._parse_llm_response(response, request)

        except Exception as e:
            return RouteDecision(
                agent=AgentType.PM,
                confidence=0.3,
                reason=f"LLM routing failed: {e}",
                reframed_task=request
            )

    def _parse_llm_response(self, response: str, original_request: str) -> RouteDecision:
        """LLM 응답 파싱"""
        lines = response.strip().split('\n')
        agent_name = ""
        confidence = 0.5
        reason = ""
        reframed = original_request

        for line in lines:
            if line.startswith("AGENT:"):
                agent_name = line.split(":", 1)[1].strip().lower()
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                except ValueError:
                    confidence = 0.5
            elif line.startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()
            elif line.startswith("REFRAMED_TASK:"):
                reframed = line.split(":", 1)[1].strip()

        # agent_name을 AgentType으로 변환
        agent_type = AgentType.PM
        for at, info in AGENT_REGISTRY.items():
            if info.name.lower() == agent_name or at.value == agent_name:
                agent_type = at
                break

        return RouteDecision(
            agent=agent_type,
            confidence=confidence,
            reason=reason or "LLM decision",
            reframed_task=reframed
        )

    def detect_multi_agent_task(self, request: str) -> Optional[List[Dict[str, Any]]]:
        """
        복합 태스크 감지 및 분해

        Returns:
            None: 단일 에이전트 태스크
            List: 분해된 서브태스크 목록
        """
        # 복합 태스크 패턴
        patterns = [
            r"(먼저|그리고|그 다음|마지막으로)",
            r"(\d+\.\s+.*\n)+",
            r"(하고|한 후|완료되면)",
        ]

        for pattern in patterns:
            if re.search(pattern, request, re.IGNORECASE):
                # 복합 태스크로 판단 → PM에게 분해 위임
                return None  # PM이 처리

        return None  # 단일 태스크


# =============================================================================
# Convenience Functions
# =============================================================================

def quick_route(request: str) -> RouteDecision:
    """빠른 라우팅 (키워드만)"""
    router = Router(use_llm_fallback=False)
    return router.route(request)


def get_agent_info(agent_type: AgentType) -> AgentInfo:
    """에이전트 정보 조회"""
    return AGENT_REGISTRY.get(agent_type)


def list_agents() -> List[AgentInfo]:
    """모든 에이전트 목록"""
    return list(AGENT_REGISTRY.values())
