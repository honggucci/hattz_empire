"""
Hattz Empire - PM Decision Machine (v2.5.4)
PM 출력을 시스템 상태 전이로 변환

핵심 원칙:
- summary는 로그용, 의사결정에 사용 금지
- decision은 enum ONLY
- 인간 흉내 = 시스템 버그
"""
from enum import Enum
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
import re


# =============================================================================
# Decision Enums
# =============================================================================

class PMDecision(str, Enum):
    """PM 의사결정 상태"""
    DISPATCH = "DISPATCH"       # 하위 에이전트에게 작업 분배
    ESCALATE = "ESCALATE"       # CEO 승인 필요
    DONE = "DONE"               # 작업 완료
    BLOCKED = "BLOCKED"         # 진행 불가 (정보 부족 등)
    RETRY = "RETRY"             # 재시도 필요


# =============================================================================
# State Transition Graph (v2.5.5)
# =============================================================================

ALLOWED_TRANSITIONS: Dict[PMDecision, set] = {
    PMDecision.DISPATCH: {PMDecision.RETRY, PMDecision.DONE, PMDecision.BLOCKED},
    PMDecision.RETRY: {PMDecision.DISPATCH, PMDecision.BLOCKED},
    PMDecision.BLOCKED: {PMDecision.ESCALATE},
    PMDecision.ESCALATE: {PMDecision.DONE},
    PMDecision.DONE: set(),  # Terminal state
}

# 금지된 전이 (명시적 문서화)
FORBIDDEN_TRANSITIONS = [
    (PMDecision.DISPATCH, PMDecision.ESCALATE),  # DISPATCH에서 바로 ESCALATE 금지
    (PMDecision.DONE, PMDecision.RETRY),          # DONE은 terminal
    (PMDecision.RETRY, PMDecision.ESCALATE),      # RETRY에서 바로 ESCALATE 금지
    (PMDecision.BLOCKED, PMDecision.DISPATCH),    # BLOCKED는 ESCALATE로만 가능
]


def is_valid_transition(from_state: PMDecision, to_state: PMDecision) -> bool:
    """전이 유효성 검사"""
    allowed = ALLOWED_TRANSITIONS.get(from_state, set())
    return to_state in allowed


def get_forbidden_reason(from_state: PMDecision, to_state: PMDecision) -> Optional[str]:
    """금지된 전이 사유 반환"""
    for forbidden_from, forbidden_to in FORBIDDEN_TRANSITIONS:
        if from_state == forbidden_from and to_state == forbidden_to:
            return f"{from_state.value} -> {to_state.value} 전이 금지"
    if to_state not in ALLOWED_TRANSITIONS.get(from_state, set()):
        return f"{from_state.value}에서 {to_state.value}로 전이 불가"
    return None




class DispatchTarget(str, Enum):
    """디스패치 대상 에이전트"""
    CODER = "coder"
    QA = "qa"
    REVIEWER = "reviewer"
    STRATEGIST = "strategist"
    ANALYST = "analyst"
    RESEARCHER = "researcher"
    EXCAVATOR = "excavator"


class EscalationReason(str, Enum):
    """에스컬레이션 사유"""
    DEPLOY = "deploy"           # 배포/운영 반영
    API_KEY = "api_key"         # 외부 API 키/권한 변경
    PAYMENT = "payment"         # 결제/비용 발생
    DATA_DELETE = "data_delete" # 데이터 삭제
    DEPENDENCY = "dependency"   # 의존성 추가
    SECURITY = "security"       # 보안 민감 변경
    UNCLEAR = "unclear"         # 요구사항 불명확
    RISK = "risk"               # 고위험 작업


# =============================================================================
# Decision Output (정형화된 의사결정)
# =============================================================================

@dataclass
class DecisionOutput:
    """
    PM Decision Machine 출력

    summary는 로그용, decision이 실제 상태 전이
    """
    decision: PMDecision
    targets: List[DispatchTarget]           # DISPATCH 시 대상 에이전트들
    escalation_reason: Optional[EscalationReason] = None  # ESCALATE 시 사유
    summary: str = ""                       # 로그용 (100자 이내)
    confidence: float = 1.0                 # 결정 확신도 (0-1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "targets": [t.value for t in self.targets],
            "escalation_reason": self.escalation_reason.value if self.escalation_reason else None,
            "summary": self.summary[:100],
            "confidence": self.confidence
        }


# =============================================================================
# PM Decision Machine
# =============================================================================

class PMDecisionMachine:
    """
    PM 출력 → 시스템 상태 전이 변환기

    원칙:
    1. PM JSON → DecisionOutput 변환
    2. summary는 검증만 (의사결정에 사용 금지)
    3. 불확실하면 BLOCKED 반환
    """

    # 에스컬레이션 트리거 키워드
    ESCALATION_KEYWORDS = {
        EscalationReason.DEPLOY: ["배포", "deploy", "production", "운영", "릴리즈", "release"],
        EscalationReason.API_KEY: ["api key", "api_key", "apikey", "토큰", "token", "credential", "인증키"],
        EscalationReason.PAYMENT: ["결제", "payment", "billing", "요금", "cost", "비용 발생"],
        EscalationReason.DATA_DELETE: ["삭제", "delete", "drop", "truncate", "remove 데이터"],
        EscalationReason.DEPENDENCY: ["pip install", "npm install", "의존성", "dependency", "패키지 추가"],
        EscalationReason.SECURITY: ["보안", "security", "인증", "auth", "권한", "permission"],
    }

    # 에이전트 매핑 키워드
    AGENT_KEYWORDS = {
        DispatchTarget.CODER: ["구현", "수정", "코드", "fix", "implement", "refactor", "버그"],
        DispatchTarget.QA: ["테스트", "검증", "test", "verify", "qa", "재현"],
        DispatchTarget.REVIEWER: ["리뷰", "review", "검토", "approve", "보안 검토"],
        DispatchTarget.STRATEGIST: ["전략", "strategy", "분석", "설계", "아키텍처", "원인 분석"],
        DispatchTarget.ANALYST: ["로그", "log", "요약", "압축", "대용량"],
        DispatchTarget.RESEARCHER: ["검색", "search", "최신", "문서", "공식 문서", "리서치"],
        DispatchTarget.EXCAVATOR: ["요구사항", "requirement", "불명확", "모순", "clarify"],
    }

    # 의미 없는 summary 패턴 (SemanticGuard와 동일)
    NULL_PATTERNS = [
        r"검토했습니다",
        r"확인했습니다",
        r"진행하겠습니다",
        r"처리하겠습니다",
        r"looks good",
        r"will proceed",
        r"I will",
    ]

    def __init__(self):
        self._compiled_null_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.NULL_PATTERNS
        ]

    def process(self, pm_output: Dict[str, Any]) -> DecisionOutput:
        """
        PM JSON 출력 → DecisionOutput 변환

        Args:
            pm_output: PM의 JSON 출력 (action, tasks, summary, requires_ceo)

        Returns:
            DecisionOutput - 정형화된 의사결정
        """
        action = pm_output.get("action", "").upper()
        tasks = pm_output.get("tasks", [])
        summary = pm_output.get("summary", "")
        requires_ceo = pm_output.get("requires_ceo", False)

        # 1. summary 검증 (의미적 NULL 감지)
        summary_valid, summary_warning = self._validate_summary(summary)
        if not summary_valid:
            # summary가 의미 없으면 confidence 감소
            confidence = 0.5
        else:
            confidence = 1.0

        # 2. action → decision 변환
        if action == "ESCALATE" or requires_ceo:
            return self._build_escalate_decision(summary, tasks, confidence)

        elif action == "DISPATCH":
            return self._build_dispatch_decision(tasks, summary, confidence)

        elif action == "DONE":
            return DecisionOutput(
                decision=PMDecision.DONE,
                targets=[],
                summary=summary,
                confidence=confidence
            )

        else:
            # 알 수 없는 action → BLOCKED
            return DecisionOutput(
                decision=PMDecision.BLOCKED,
                targets=[],
                summary=f"Unknown action: {action}",
                confidence=0.0
            )

    def _validate_summary(self, summary: str) -> Tuple[bool, str]:
        """summary 유효성 검사"""
        if not summary or len(summary.strip()) < 5:
            return False, "summary 너무 짧음"

        for pattern in self._compiled_null_patterns:
            if pattern.search(summary):
                return False, f"의미 없는 summary: {pattern.pattern}"

        return True, ""

    def _build_escalate_decision(
        self,
        summary: str,
        tasks: List[Dict],
        confidence: float
    ) -> DecisionOutput:
        """ESCALATE 결정 생성"""
        # 에스컬레이션 사유 추론
        reason = self._infer_escalation_reason(summary, tasks)

        return DecisionOutput(
            decision=PMDecision.ESCALATE,
            targets=[],
            escalation_reason=reason,
            summary=summary,
            confidence=confidence
        )

    def _build_dispatch_decision(
        self,
        tasks: List[Dict],
        summary: str,
        confidence: float
    ) -> DecisionOutput:
        """DISPATCH 결정 생성"""
        if not tasks:
            # tasks 없는 DISPATCH → BLOCKED
            return DecisionOutput(
                decision=PMDecision.BLOCKED,
                targets=[],
                summary="DISPATCH인데 tasks 없음",
                confidence=0.0
            )

        # 대상 에이전트 추출
        targets = []
        for task in tasks:
            agent = task.get("agent", "").lower()
            try:
                target = DispatchTarget(agent)
                if target not in targets:
                    targets.append(target)
            except ValueError:
                # 알 수 없는 에이전트 무시
                pass

        if not targets:
            # 유효한 타겟 없음 → BLOCKED
            return DecisionOutput(
                decision=PMDecision.BLOCKED,
                targets=[],
                summary="유효한 에이전트 없음",
                confidence=0.0
            )

        return DecisionOutput(
            decision=PMDecision.DISPATCH,
            targets=targets,
            summary=summary,
            confidence=confidence
        )

    def _infer_escalation_reason(
        self,
        summary: str,
        tasks: List[Dict]
    ) -> EscalationReason:
        """에스컬레이션 사유 추론"""
        full_text = summary.lower()
        for task in tasks:
            full_text += " " + task.get("instruction", "").lower()
            full_text += " " + task.get("context", "").lower()

        for reason, keywords in self.ESCALATION_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in full_text:
                    return reason

        # 기본값: UNCLEAR
        return EscalationReason.UNCLEAR

    def infer_agent_from_prompt(self, prompt: str) -> Optional[DispatchTarget]:
        """
        프롬프트에서 적합한 에이전트 추론

        PM 없이 직접 라우팅 시 사용
        """
        prompt_lower = prompt.lower()

        # 점수 계산
        scores: Dict[DispatchTarget, int] = {}
        for agent, keywords in self.AGENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in prompt_lower)
            if score > 0:
                scores[agent] = score

        if not scores:
            return None

        # 최고 점수 에이전트 반환
        return max(scores, key=scores.get)

    def should_escalate(self, prompt: str) -> Tuple[bool, Optional[EscalationReason]]:
        """
        프롬프트가 에스컬레이션 대상인지 확인

        CEO 직접 입력 시 자동 감지용
        """
        prompt_lower = prompt.lower()

        for reason, keywords in self.ESCALATION_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in prompt_lower:
                    return True, reason

        return False, None


# =============================================================================
# 싱글톤
# =============================================================================

_decision_machine: Optional[PMDecisionMachine] = None


def get_decision_machine() -> PMDecisionMachine:
    """PMDecisionMachine 싱글톤"""
    global _decision_machine
    if _decision_machine is None:
        _decision_machine = PMDecisionMachine()
    return _decision_machine


# =============================================================================
# 헬퍼 함수
# =============================================================================

def process_pm_output(pm_json: Dict[str, Any]) -> DecisionOutput:
    """PM JSON 출력 처리 (편의 함수)"""
    return get_decision_machine().process(pm_json)


def infer_agent(prompt: str) -> Optional[str]:
    """프롬프트에서 에이전트 추론 (편의 함수)"""
    agent = get_decision_machine().infer_agent_from_prompt(prompt)
    return agent.value if agent else None


def check_escalation(prompt: str) -> Tuple[bool, Optional[str]]:
    """에스컬레이션 필요 여부 확인 (편의 함수)"""
    needs, reason = get_decision_machine().should_escalate(prompt)
    return needs, reason.value if reason else None


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    print("=== PM Decision Machine Test ===\n")

    machine = PMDecisionMachine()

    # 1. DISPATCH 테스트
    pm_output1 = {
        "action": "DISPATCH",
        "tasks": [
            {"task_id": "T001", "agent": "coder", "instruction": "로그인 버그 수정", "priority": "HIGH"}
        ],
        "summary": "coder에게 로그인 버그 수정 할당",
        "requires_ceo": False
    }
    result1 = machine.process(pm_output1)
    print(f"1. DISPATCH: {result1.to_dict()}")

    # 2. ESCALATE 테스트
    pm_output2 = {
        "action": "ESCALATE",
        "tasks": [],
        "summary": "프로덕션 배포 승인 필요",
        "requires_ceo": True
    }
    result2 = machine.process(pm_output2)
    print(f"2. ESCALATE: {result2.to_dict()}")

    # 3. 의미 없는 summary 테스트
    pm_output3 = {
        "action": "DISPATCH",
        "tasks": [{"task_id": "T002", "agent": "qa", "instruction": "테스트"}],
        "summary": "확인했습니다. 진행하겠습니다.",
        "requires_ceo": False
    }
    result3 = machine.process(pm_output3)
    print(f"3. 의미없는 summary: {result3.to_dict()} (confidence={result3.confidence})")

    # 4. 에이전트 추론 테스트
    print("\n=== 에이전트 추론 ===")
    test_prompts = [
        "로그인 버그를 수정해줘",
        "이 코드 리뷰해줘",
        "테스트 케이스 작성해줘",
        "아키텍처 분석해줘",
        "최신 문서 검색해줘",
    ]
    for prompt in test_prompts:
        agent = machine.infer_agent_from_prompt(prompt)
        print(f"  '{prompt}' -> {agent.value if agent else 'None'}")

    # 5. 에스컬레이션 감지 테스트
    print("\n=== 에스컬레이션 감지 ===")
    esc_prompts = [
        "프로덕션에 배포해줘",
        "API 키 변경해줘",
        "pip install requests 해줘",
        "코드 수정해줘",
    ]
    for prompt in esc_prompts:
        needs, reason = machine.should_escalate(prompt)
        print(f"  '{prompt}' -> needs={needs}, reason={reason}")

    print("\n=== Done ===")
