"""
Hattz Empire - Persona Council System
다중 페르소나 위원회 - 같은 모델, 다른 성격

"혼자 결정하면 좆된다"
"""
import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean, stdev


class Verdict(Enum):
    """판정 결과"""
    PASS = "pass"              # 통과
    CONDITIONAL = "conditional"  # 조건부 (수정 후 재심)
    FAIL = "fail"              # 반려
    CEO_REVIEW = "ceo_review"  # CEO 개입 필요


@dataclass
class PersonaConfig:
    """페르소나 설정"""
    id: str
    name: str
    icon: str
    temperature: float
    system_prompt: str


@dataclass
class JudgeScore:
    """심사 점수"""
    persona_id: str
    persona_name: str
    icon: str
    score: float  # 0-10
    reasoning: str
    concerns: List[str] = field(default_factory=list)
    approvals: List[str] = field(default_factory=list)


@dataclass
class CouncilVerdict:
    """위원회 판정 결과"""
    council_type: str
    verdict: Verdict
    average_score: float
    score_std: float  # 표준편차 (의견 분산도)
    judges: List[JudgeScore]
    summary: str
    requires_ceo: bool
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# =============================================================================
# 페르소나 정의
# =============================================================================

PERSONAS: Dict[str, PersonaConfig] = {
    "skeptic": PersonaConfig(
        id="skeptic",
        name="회의론자",
        icon="🤨",
        temperature=0.3,
        system_prompt="""너는 극도로 회의적인 검토자다.

성격:
- 모든 것에 "근거는?" 질문
- 낙관적 전망 즉시 반박
- "이게 정말 최선?" 항상 의심
- 결함 못 찾으면 불안해함

평가 기준:
- 논리적 근거가 있는가?
- 반례가 고려되었는가?
- 숨은 가정은 없는가?

출력 형식 (JSON):
{
    "score": 0-10,
    "reasoning": "판단 이유",
    "concerns": ["우려사항 목록"],
    "approvals": ["긍정적 부분"]
}""",
    ),

    "perfectionist": PersonaConfig(
        id="perfectionist",
        name="완벽주의자",
        icon="🔬",
        temperature=0.2,
        system_prompt="""너는 디테일에 집착하는 완벽주의자다.

성격:
- 오타 하나도 못 참음
- 코드 스타일 일관성 집착
- "이것도 처리해야지" 끊임없이 추가
- 100% 아니면 0%

평가 기준:
- 코드 품질/스타일
- 에러 핸들링 완성도
- 문서화 수준
- 테스트 커버리지

출력 형식 (JSON):
{
    "score": 0-10,
    "reasoning": "판단 이유",
    "concerns": ["우려사항 목록"],
    "approvals": ["긍정적 부분"]
}""",
    ),

    "pragmatist": PersonaConfig(
        id="pragmatist",
        name="현실주의자",
        icon="🎯",
        temperature=0.5,
        system_prompt="""너는 실행 중심 현실주의자다.

성격:
- "일단 되게 해" 마인드
- 80% 완성이면 출시
- 완벽보다 속도
- "나중에 고치면 됨"

평가 기준:
- 당장 동작하는가?
- 핵심 기능이 구현되었는가?
- 치명적 버그가 없는가?
- 시간 대비 효율적인가?

출력 형식 (JSON):
{
    "score": 0-10,
    "reasoning": "판단 이유",
    "concerns": ["우려사항 목록"],
    "approvals": ["긍정적 부분"]
}""",
    ),

    "pessimist": PersonaConfig(
        id="pessimist",
        name="비관론자",
        icon="😰",
        temperature=0.3,
        system_prompt="""너는 최악을 가정하는 비관론자다.

성격:
- "이거 터지면?" 먼저 생각
- 모든 엣지케이스 상상
- 장애 시나리오 전문
- 희망회로 차단

평가 기준:
- 실패 시나리오가 고려되었는가?
- 롤백 가능한가?
- 장애 대응 방안이 있는가?
- 최악의 경우 손실은?

출력 형식 (JSON):
{
    "score": 0-10,
    "reasoning": "판단 이유",
    "concerns": ["우려사항 목록"],
    "approvals": ["긍정적 부분"]
}""",
    ),

    "optimist": PersonaConfig(
        id="optimist",
        name="낙관론자",
        icon="😊",
        temperature=0.7,
        system_prompt="""너는 가능성을 보는 낙관론자다.

성격:
- "이거 되면 대박" 마인드
- 장점 먼저 언급
- 동기부여 담당
- 팀 사기 관리

평가 기준:
- 잠재적 가치가 있는가?
- 성공 시 임팩트는?
- 발전 가능성이 있는가?
- 배울 점이 있는가?

출력 형식 (JSON):
{
    "score": 0-10,
    "reasoning": "판단 이유",
    "concerns": ["우려사항 목록"],
    "approvals": ["긍정적 부분"]
}""",
    ),

    "devils_advocate": PersonaConfig(
        id="devils_advocate",
        name="악마의 변호인",
        icon="😈",
        temperature=0.4,
        system_prompt="""너는 의도적으로 반대하는 악마의 변호인이다.

성격:
- 다수 의견에 무조건 반박
- "반대로 생각하면?" 전문
- 숨은 리스크 발굴
- 그룹씽크 방지

평가 기준:
- 반대 관점에서 문제는?
- 다른 접근법은 없었나?
- 놓친 대안이 있는가?
- 숨은 비용/리스크는?

출력 형식 (JSON):
{
    "score": 0-10,
    "reasoning": "판단 이유",
    "concerns": ["우려사항 목록"],
    "approvals": ["긍정적 부분"]
}""",
    ),

    "security_hawk": PersonaConfig(
        id="security_hawk",
        name="보안 감시자",
        icon="🦅",
        temperature=0.2,
        system_prompt="""너는 보안에 집착하는 감시자다.

성격:
- 모든 입력은 악의적이라 가정
- API 키 노출 극도로 경계
- 인젝션 공격 상상
- 최소 권한 원칙 집착

평가 기준:
- 보안 취약점이 있는가? (OWASP Top 10)
- 민감 정보가 노출되는가?
- 인증/인가가 적절한가?
- 입력 검증이 되어 있는가?

출력 형식 (JSON):
{
    "score": 0-10,
    "reasoning": "판단 이유",
    "concerns": ["우려사항 목록"],
    "approvals": ["긍정적 부분"]
}""",
    ),
}


# =============================================================================
# 위원회 유형
# =============================================================================

COUNCIL_TYPES: Dict[str, Dict] = {
    "code": {
        "name": "Code Council",
        "description": "코드 리뷰 위원회",
        "personas": ["skeptic", "perfectionist", "pragmatist"],
        "pass_threshold": 7.0,
        "conditional_threshold": 5.5,
        "max_std_for_auto_pass": 1.5,  # 이 이상이면 CEO 개입
    },
    "strategy": {
        "name": "Strategy Council",
        "description": "전략 검토 위원회",
        "personas": ["pessimist", "optimist", "devils_advocate"],
        "pass_threshold": 7.0,
        "conditional_threshold": 5.5,
        "max_std_for_auto_pass": 1.5,
    },
    "security": {
        "name": "Security Council",
        "description": "보안 감사 위원회",
        "personas": ["security_hawk", "skeptic", "pessimist"],
        "pass_threshold": 8.0,  # 보안은 더 엄격
        "conditional_threshold": 6.0,
        "max_std_for_auto_pass": 1.0,  # 의견 통일 필요
    },
    "deploy": {
        "name": "Deploy Council",
        "description": "배포 승인 위원회",
        "personas": ["security_hawk", "pessimist", "pragmatist", "perfectionist"],
        "pass_threshold": 8.5,  # 배포는 매우 엄격
        "conditional_threshold": 7.0,
        "max_std_for_auto_pass": 0.5,  # 거의 만장일치 필요
        "requires_ceo": True,  # 항상 CEO 확인
    },
    "mvp": {
        "name": "MVP Council",
        "description": "MVP 출시 판단 위원회",
        "personas": ["pragmatist", "optimist", "skeptic"],
        "pass_threshold": 6.5,  # MVP는 좀 더 유연
        "conditional_threshold": 5.0,
        "max_std_for_auto_pass": 2.0,
    },
}


# =============================================================================
# Council 클래스
# =============================================================================

class PersonaCouncil:
    """
    다중 페르소나 위원회

    사용법:
        council = PersonaCouncil()

        # 코드 리뷰 위원회 소집
        verdict = await council.convene(
            council_type="code",
            content="검토할 코드",
            context="추가 컨텍스트"
        )

        if verdict.verdict == Verdict.PASS:
            print("통과!")
        elif verdict.requires_ceo:
            print("CEO 확인 필요")
    """

    def __init__(self, llm_caller: Optional[Callable] = None):
        """
        Args:
            llm_caller: LLM 호출 함수
                        async def llm_caller(system_prompt, user_message, temperature) -> str
        """
        self.llm_caller = llm_caller
        self.history: List[CouncilVerdict] = []

    def set_llm_caller(self, caller: Callable):
        """LLM 호출 함수 설정"""
        self.llm_caller = caller

    async def _call_persona(
        self,
        persona: PersonaConfig,
        content: str,
        context: str = ""
    ) -> JudgeScore:
        """개별 페르소나 호출"""

        user_message = f"""다음 내용을 검토하고 점수를 매겨라.

=== 검토 대상 ===
{content}

=== 컨텍스트 ===
{context if context else "없음"}

=== 응답 형식 ===
반드시 JSON으로만 응답해라:
{{
    "score": 0-10 사이의 숫자,
    "reasoning": "판단 이유 (한글, 2-3문장)",
    "concerns": ["우려사항1", "우려사항2"],
    "approvals": ["긍정적인 점1", "긍정적인 점2"]
}}"""

        if self.llm_caller:
            try:
                response = await self.llm_caller(
                    persona.system_prompt,
                    user_message,
                    persona.temperature
                )
                data = json.loads(response)
            except Exception as e:
                # 파싱 실패 시 기본값
                data = {
                    "score": 5.0,
                    "reasoning": f"응답 파싱 실패: {str(e)}",
                    "concerns": ["응답 형식 오류"],
                    "approvals": []
                }
        else:
            # Mock 응답 (테스트용)
            import random
            data = {
                "score": random.uniform(4, 9),
                "reasoning": f"{persona.name}의 Mock 평가입니다.",
                "concerns": [f"{persona.name} 우려사항"],
                "approvals": [f"{persona.name} 긍정적 평가"]
            }

        return JudgeScore(
            persona_id=persona.id,
            persona_name=persona.name,
            icon=persona.icon,
            score=float(data.get("score", 5.0)),
            reasoning=data.get("reasoning", ""),
            concerns=data.get("concerns", []),
            approvals=data.get("approvals", [])
        )

    def _determine_verdict(
        self,
        council_type: str,
        scores: List[JudgeScore]
    ) -> tuple[Verdict, bool]:
        """판정 결정"""
        config = COUNCIL_TYPES[council_type]

        score_values = [s.score for s in scores]
        avg = mean(score_values)
        std = stdev(score_values) if len(score_values) > 1 else 0

        requires_ceo = config.get("requires_ceo", False)

        # 의견 분산이 크면 CEO 개입
        if std > config["max_std_for_auto_pass"]:
            return Verdict.CEO_REVIEW, True

        # 점수 기준 판정
        if avg >= config["pass_threshold"]:
            return Verdict.PASS, requires_ceo
        elif avg >= config["conditional_threshold"]:
            return Verdict.CONDITIONAL, requires_ceo
        else:
            return Verdict.FAIL, True  # 실패는 항상 CEO 알림

    def _generate_summary(self, verdict: Verdict, judges: List[JudgeScore]) -> str:
        """판정 요약 생성"""
        all_concerns = []
        all_approvals = []

        for j in judges:
            all_concerns.extend(j.concerns)
            all_approvals.extend(j.approvals)

        summary_parts = []

        if verdict == Verdict.PASS:
            summary_parts.append("✅ 위원회 통과")
        elif verdict == Verdict.CONDITIONAL:
            summary_parts.append("⚠️ 조건부 통과 - 수정 후 재심 필요")
        elif verdict == Verdict.FAIL:
            summary_parts.append("❌ 반려 - 전면 재검토 필요")
        elif verdict == Verdict.CEO_REVIEW:
            summary_parts.append("👔 CEO 검토 필요 - 의견 분분")

        if all_concerns:
            summary_parts.append(f"\n주요 우려: {', '.join(all_concerns[:3])}")

        if all_approvals:
            summary_parts.append(f"\n긍정적 평가: {', '.join(all_approvals[:3])}")

        return "".join(summary_parts)

    async def convene(
        self,
        council_type: str,
        content: str,
        context: str = ""
    ) -> CouncilVerdict:
        """
        위원회 소집

        Args:
            council_type: 위원회 유형 (code, strategy, security, deploy, mvp)
            content: 검토 대상 내용
            context: 추가 컨텍스트

        Returns:
            CouncilVerdict: 판정 결과
        """
        if council_type not in COUNCIL_TYPES:
            raise ValueError(f"Unknown council type: {council_type}")

        config = COUNCIL_TYPES[council_type]
        persona_ids = config["personas"]

        # 병렬로 모든 페르소나 호출
        tasks = [
            self._call_persona(PERSONAS[pid], content, context)
            for pid in persona_ids
        ]
        judges = await asyncio.gather(*tasks)

        # 판정
        verdict, requires_ceo = self._determine_verdict(council_type, judges)

        score_values = [j.score for j in judges]
        avg = mean(score_values)
        std = stdev(score_values) if len(score_values) > 1 else 0

        result = CouncilVerdict(
            council_type=council_type,
            verdict=verdict,
            average_score=round(avg, 2),
            score_std=round(std, 2),
            judges=list(judges),
            summary=self._generate_summary(verdict, judges),
            requires_ceo=requires_ceo,
        )

        self.history.append(result)
        return result

    def convene_sync(
        self,
        council_type: str,
        content: str,
        context: str = ""
    ) -> CouncilVerdict:
        """동기 버전 (asyncio.run 래퍼)"""
        return asyncio.run(self.convene(council_type, content, context))

    def get_history(self, limit: int = 10) -> List[CouncilVerdict]:
        """판정 히스토리 조회"""
        return self.history[-limit:]


# =============================================================================
# 싱글톤
# =============================================================================

_council: Optional[PersonaCouncil] = None


def get_council() -> PersonaCouncil:
    """Council 싱글톤"""
    global _council
    if _council is None:
        _council = PersonaCouncil()
    return _council


# =============================================================================
# 테스트
# =============================================================================

if __name__ == "__main__":
    import asyncio

    async def test():
        council = get_council()

        print("=" * 60)
        print("PERSONA COUNCIL 테스트")
        print("=" * 60)

        # 코드 리뷰 테스트
        print("\n[Code Council 소집]")
        verdict = await council.convene(
            council_type="code",
            content="""
def calculate_profit(buy_price, sell_price):
    return sell_price - buy_price
""",
            context="간단한 수익 계산 함수"
        )

        print(f"\n결과: {verdict.verdict.value}")
        print(f"평균 점수: {verdict.average_score}/10")
        print(f"편차: {verdict.score_std}")
        print(f"CEO 필요: {verdict.requires_ceo}")

        print("\n[심사위원 상세]")
        for judge in verdict.judges:
            print(f"  {judge.icon} {judge.persona_name}: {judge.score}/10")
            print(f"     이유: {judge.reasoning}")

        print(f"\n{verdict.summary}")

        # 전략 위원회 테스트
        print("\n" + "=" * 60)
        print("[Strategy Council 소집]")
        verdict2 = await council.convene(
            council_type="strategy",
            content="비트코인 레버리지 10배로 올인하자",
            context="투자 전략 제안"
        )

        print(f"\n결과: {verdict2.verdict.value}")
        print(f"평균 점수: {verdict2.average_score}/10")

        for judge in verdict2.judges:
            print(f"  {judge.icon} {judge.persona_name}: {judge.score}/10")

        print(f"\n{verdict2.summary}")

    asyncio.run(test())
