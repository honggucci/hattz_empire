"""
Hattz Empire - Flow Quality Monitor (v2.6.1)

부트로더 원칙 준수 여부를 정량적으로 측정하는 시스템.

측정 지표:
1. 역할 침범률 (Role Boundary Violation)
2. JSON 계약 준수율 (Contract Compliance)
3. PM DFA 전이 위반 (State Transition Violation)
4. 잡담/추임새 감지 (Chatter Detection)
5. Retry Escalation 단조성 (Monotonicity)

사용법:
    from src.services.flow_monitor import FlowMonitor, get_flow_monitor

    monitor = get_flow_monitor()

    # 에이전트 출력 검증
    result = monitor.validate_output(agent="coder", output=response)

    # PM 상태 전이 기록
    monitor.record_transition(session_id, from_state="DISPATCH", to_state="RETRY")

    # 세션 품질 리포트
    report = monitor.get_session_report(session_id)
"""
import re
import json
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from enum import Enum
from collections import defaultdict

from src.utils.server_logger import logger


# =============================================================================
# 상수 정의
# =============================================================================

class PMState(Enum):
    """PM DFA 상태"""
    DISPATCH = "DISPATCH"
    RETRY = "RETRY"
    BLOCKED = "BLOCKED"
    ESCALATE = "ESCALATE"
    DONE = "DONE"


class ViolationType(Enum):
    """위반 유형"""
    ROLE_BOUNDARY = "role_boundary"      # 역할 침범
    CONTRACT_FAIL = "contract_fail"       # JSON 계약 위반
    DFA_TRANSITION = "dfa_transition"     # 금지된 상태 전이
    CHATTER = "chatter"                   # 잡담/추임새
    MONOTONICITY = "monotonicity"         # Retry Escalation 단조성 위반


# PM DFA 허용된 전이
ALLOWED_TRANSITIONS = {
    PMState.DISPATCH: {PMState.RETRY, PMState.DONE, PMState.BLOCKED},
    PMState.RETRY: {PMState.DISPATCH, PMState.BLOCKED},
    PMState.BLOCKED: {PMState.ESCALATE},
    PMState.ESCALATE: {PMState.DONE},
    PMState.DONE: set(),  # terminal
}

# 역할별 금지 패턴
ROLE_FORBIDDEN_PATTERNS = {
    "coder": [
        r"(?i)(이렇게 하면|더 좋을|더 나을|best practice|cleaner approach)",  # 전략 언급
        r"(?i)(옵션|대안|alternative|approach)",  # 대안 제시
        r"(?i)(추천|recommend|suggest(?!ed fix))",  # 추천 (suggested fix 제외)
    ],
    "strategist": [
        r"```(python|javascript|typescript|java|go|rust)",  # 코드 블록
        r"(?i)(def |class |function |const |let |var )",  # 코드 패턴
        r"(?i)(\.py|\.js|\.ts|\.java|\.go|\.rs)",  # 파일 확장자
        r"(?i)(import |from .+ import)",  # import 문
    ],
    "qa": [
        r"(?i)(수정|변경|modify|change|fix(?! test))",  # 구현 변경 (fix test 제외)
    ],
    "reviewer": [
        r"(?i)(코드를 수정|implementation|구현)",  # 코드 수정 시도
    ],
    "pm": [
        r"```(python|javascript|typescript)",  # 코드 블록
        r"(?i)(def |class |function )",  # 코드 패턴
        r"(?i)(옵션|대안|리스크|전략)",  # 전략 언급 (PM은 라우팅만)
    ],
}

# 잡담/추임새 패턴
CHATTER_PATTERNS = [
    r"^(?i)(let me|i will|i'll|here is|here's|sure|okay|alright)",
    r"(?i)(안녕|감사|죄송|sorry|thank|please)",
    r"(?i)(도움이 되|helpful|glad to)",
    r"[\U0001F600-\U0001F64F]",  # 이모지
    r"(?i)(great question|good point|excellent)",
]

# Retry Escalation 레벨 순서
ESCALATION_ORDER = ["SELF_REPAIR", "ROLE_SWITCH", "HARD_FAIL"]


# =============================================================================
# 데이터 클래스
# =============================================================================

@dataclass
class Violation:
    """위반 기록"""
    timestamp: str
    session_id: str
    agent: str
    violation_type: ViolationType
    details: str
    severity: str = "WARNING"  # WARNING, ERROR, CRITICAL

    def to_dict(self) -> dict:
        d = asdict(self)
        d["violation_type"] = self.violation_type.value
        return d


@dataclass
class SessionMetrics:
    """세션별 품질 지표"""
    session_id: str
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 카운터
    total_outputs: int = 0
    valid_outputs: int = 0

    # 위반 카운터
    role_violations: int = 0
    contract_violations: int = 0
    dfa_violations: int = 0
    chatter_violations: int = 0
    monotonicity_violations: int = 0

    # PM 상태 추적
    current_state: str = "DISPATCH"
    state_history: List[str] = field(default_factory=list)
    retry_count: int = 0
    escalation_level: str = "SELF_REPAIR"

    # 상세 위반 기록
    violations: List[Violation] = field(default_factory=list)

    def get_compliance_rate(self) -> float:
        """준수율 계산"""
        if self.total_outputs == 0:
            return 1.0
        return self.valid_outputs / self.total_outputs

    def get_quality_score(self) -> int:
        """품질 점수 (0-100)"""
        if self.total_outputs == 0:
            return 100

        # 기본 점수 100에서 위반 시 감점
        score = 100
        total_violations = (
            self.role_violations * 10 +      # 역할 침범: -10점
            self.contract_violations * 5 +    # 계약 위반: -5점
            self.dfa_violations * 15 +        # DFA 위반: -15점
            self.chatter_violations * 2 +     # 잡담: -2점
            self.monotonicity_violations * 20 # 단조성 위반: -20점
        )

        # 출력 수 대비 위반 비율로 감점
        violation_rate = total_violations / max(self.total_outputs, 1)
        score -= min(violation_rate * 100, 100)

        return max(0, int(score))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["violations"] = [v.to_dict() if isinstance(v, Violation) else v for v in self.violations]
        d["compliance_rate"] = self.get_compliance_rate()
        d["quality_score"] = self.get_quality_score()
        return d


# =============================================================================
# Flow Monitor 클래스
# =============================================================================

class FlowMonitor:
    """부트로더 원칙 준수 모니터"""

    def __init__(self):
        self._sessions: Dict[str, SessionMetrics] = {}
        self._global_violations: List[Violation] = []

    def _get_session(self, session_id: str) -> SessionMetrics:
        """세션 메트릭스 가져오기 (없으면 생성)"""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionMetrics(session_id=session_id)
        return self._sessions[session_id]

    def _add_violation(
        self,
        session_id: str,
        agent: str,
        violation_type: ViolationType,
        details: str,
        severity: str = "WARNING"
    ) -> Violation:
        """위반 기록 추가"""
        violation = Violation(
            timestamp=datetime.now().isoformat(),
            session_id=session_id,
            agent=agent,
            violation_type=violation_type,
            details=details,
            severity=severity
        )

        session = self._get_session(session_id)
        session.violations.append(violation)
        self._global_violations.append(violation)

        # 카운터 업데이트
        if violation_type == ViolationType.ROLE_BOUNDARY:
            session.role_violations += 1
        elif violation_type == ViolationType.CONTRACT_FAIL:
            session.contract_violations += 1
        elif violation_type == ViolationType.DFA_TRANSITION:
            session.dfa_violations += 1
        elif violation_type == ViolationType.CHATTER:
            session.chatter_violations += 1
        elif violation_type == ViolationType.MONOTONICITY:
            session.monotonicity_violations += 1

        # 로그 기록
        logger.warning(
            f"[FlowMonitor] {violation_type.value}: {details}",
            extra={"agent": agent, "session_id": session_id}
        )

        return violation

    # =========================================================================
    # 검증 메서드
    # =========================================================================

    def validate_output(
        self,
        agent: str,
        output: str,
        session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        에이전트 출력 검증

        Returns:
            {
                "valid": bool,
                "violations": List[str],
                "quality_score": int
            }
        """
        session = self._get_session(session_id)
        session.total_outputs += 1

        violations = []

        # 1. 역할 침범 검사
        role_violations = self._check_role_boundary(agent, output)
        for detail in role_violations:
            self._add_violation(session_id, agent, ViolationType.ROLE_BOUNDARY, detail)
            violations.append(f"[ROLE] {detail}")

        # 2. 잡담 검사
        chatter_violations = self._check_chatter(output)
        for detail in chatter_violations:
            self._add_violation(session_id, agent, ViolationType.CHATTER, detail)
            violations.append(f"[CHATTER] {detail}")

        # 3. JSON 계약 검사 (해당 에이전트만)
        if agent in ["coder", "strategist", "qa", "excavator"]:
            contract_ok = self._check_json_contract(agent, output)
            if not contract_ok:
                self._add_violation(
                    session_id, agent, ViolationType.CONTRACT_FAIL,
                    "Output is not valid JSON"
                )
                violations.append("[CONTRACT] Output is not valid JSON")

        # 유효 출력 카운트
        if not violations:
            session.valid_outputs += 1

        return {
            "valid": len(violations) == 0,
            "violations": violations,
            "quality_score": session.get_quality_score(),
            "compliance_rate": session.get_compliance_rate()
        }

    def _check_role_boundary(self, agent: str, output: str) -> List[str]:
        """역할 경계 검사"""
        violations = []
        patterns = ROLE_FORBIDDEN_PATTERNS.get(agent, [])

        for pattern in patterns:
            matches = re.findall(pattern, output)
            if matches:
                violations.append(f"{agent} used forbidden pattern: {matches[0]}")

        return violations

    def _check_chatter(self, output: str) -> List[str]:
        """잡담/추임새 검사"""
        violations = []

        # 첫 100자만 검사 (시작 부분 잡담)
        start = output[:100]

        for pattern in CHATTER_PATTERNS:
            if re.search(pattern, start):
                match = re.search(pattern, start)
                violations.append(f"Chatter detected: '{match.group()[:20]}'")
                break  # 하나만 보고

        return violations

    def _check_json_contract(self, agent: str, output: str) -> bool:
        """JSON 계약 검사"""
        # JSON 블록 추출 시도
        json_match = re.search(r'```json\s*(.*?)\s*```', output, re.DOTALL)
        if json_match:
            try:
                json.loads(json_match.group(1))
                return True
            except json.JSONDecodeError:
                return False

        # 전체가 JSON인 경우
        try:
            json.loads(output.strip())
            return True
        except json.JSONDecodeError:
            pass

        # JSON이 없거나 파싱 실패
        return False

    # =========================================================================
    # PM DFA 추적
    # =========================================================================

    def record_transition(
        self,
        session_id: str,
        from_state: str,
        to_state: str
    ) -> Dict[str, Any]:
        """
        PM 상태 전이 기록 및 검증

        Returns:
            {
                "valid": bool,
                "violation": str or None,
                "current_state": str
            }
        """
        session = self._get_session(session_id)

        try:
            from_s = PMState(from_state)
            to_s = PMState(to_state)
        except ValueError as e:
            return {"valid": False, "violation": f"Invalid state: {e}", "current_state": session.current_state}

        # 전이 검증
        allowed = ALLOWED_TRANSITIONS.get(from_s, set())

        if to_s not in allowed:
            violation_msg = f"Forbidden transition: {from_state} -> {to_state}"
            self._add_violation(
                session_id, "pm", ViolationType.DFA_TRANSITION,
                violation_msg, severity="CRITICAL"
            )
            return {"valid": False, "violation": violation_msg, "current_state": session.current_state}

        # 상태 업데이트
        session.state_history.append(f"{from_state}->{to_state}")
        session.current_state = to_state

        # RETRY 카운트
        if to_s == PMState.RETRY:
            session.retry_count += 1
            if session.retry_count > 2:
                self._add_violation(
                    session_id, "pm", ViolationType.DFA_TRANSITION,
                    f"RETRY count exceeded: {session.retry_count} > 2"
                )

        logger.info(f"[FlowMonitor] State transition: {from_state} -> {to_state}")

        return {"valid": True, "violation": None, "current_state": to_state}

    def record_escalation(
        self,
        session_id: str,
        new_level: str
    ) -> Dict[str, Any]:
        """
        Retry Escalation 레벨 기록 및 단조성 검증

        SELF_REPAIR -> ROLE_SWITCH -> HARD_FAIL (단조 증가만 허용)
        """
        session = self._get_session(session_id)

        if new_level not in ESCALATION_ORDER:
            return {"valid": False, "violation": f"Invalid escalation level: {new_level}"}

        current_idx = ESCALATION_ORDER.index(session.escalation_level)
        new_idx = ESCALATION_ORDER.index(new_level)

        # 단조성 검사 (같거나 증가만 허용)
        if new_idx < current_idx:
            violation_msg = f"Monotonicity violation: {session.escalation_level} -> {new_level}"
            self._add_violation(
                session_id, "pm", ViolationType.MONOTONICITY,
                violation_msg, severity="CRITICAL"
            )
            return {"valid": False, "violation": violation_msg}

        session.escalation_level = new_level
        logger.info(f"[FlowMonitor] Escalation: {new_level}")

        return {"valid": True, "violation": None, "current_level": new_level}

    # =========================================================================
    # 리포트
    # =========================================================================

    def get_session_report(self, session_id: str) -> Dict[str, Any]:
        """세션 품질 리포트"""
        session = self._get_session(session_id)
        return session.to_dict()

    def get_global_report(self) -> Dict[str, Any]:
        """전체 품질 리포트"""
        total_outputs = sum(s.total_outputs for s in self._sessions.values())
        valid_outputs = sum(s.valid_outputs for s in self._sessions.values())

        violation_counts = defaultdict(int)
        for v in self._global_violations:
            violation_counts[v.violation_type.value] += 1

        avg_score = 0
        if self._sessions:
            avg_score = sum(s.get_quality_score() for s in self._sessions.values()) / len(self._sessions)

        return {
            "total_sessions": len(self._sessions),
            "total_outputs": total_outputs,
            "valid_outputs": valid_outputs,
            "compliance_rate": valid_outputs / max(total_outputs, 1),
            "average_quality_score": int(avg_score),
            "violation_counts": dict(violation_counts),
            "total_violations": len(self._global_violations),
            "recent_violations": [v.to_dict() for v in self._global_violations[-10:]]
        }

    def get_violations_by_agent(self) -> Dict[str, int]:
        """에이전트별 위반 카운트"""
        counts = defaultdict(int)
        for v in self._global_violations:
            counts[v.agent] += 1
        return dict(counts)


# =============================================================================
# 싱글톤
# =============================================================================

_monitor: Optional[FlowMonitor] = None


def get_flow_monitor() -> FlowMonitor:
    """FlowMonitor 싱글톤"""
    global _monitor
    if _monitor is None:
        _monitor = FlowMonitor()
    return _monitor


# =============================================================================
# CLI 테스트
# =============================================================================

if __name__ == "__main__":
    monitor = FlowMonitor()

    # 테스트 1: 정상 출력
    print("=== Test 1: Valid Output ===")
    result = monitor.validate_output(
        agent="coder",
        output='{"status": "success", "diff": "..."}',
        session_id="test_001"
    )
    print(f"Valid: {result['valid']}, Score: {result['quality_score']}")

    # 테스트 2: 역할 침범
    print("\n=== Test 2: Role Violation ===")
    result = monitor.validate_output(
        agent="coder",
        output='이렇게 하면 더 좋을 것 같습니다. best practice를 따르세요.',
        session_id="test_001"
    )
    print(f"Valid: {result['valid']}, Violations: {result['violations']}")

    # 테스트 3: 잡담
    print("\n=== Test 3: Chatter ===")
    result = monitor.validate_output(
        agent="pm",
        output='Let me help you with that! Here is the solution...',
        session_id="test_001"
    )
    print(f"Valid: {result['valid']}, Violations: {result['violations']}")

    # 테스트 4: DFA 전이
    print("\n=== Test 4: DFA Transition ===")
    result = monitor.record_transition("test_001", "DISPATCH", "RETRY")
    print(f"Valid: {result['valid']}")

    result = monitor.record_transition("test_001", "RETRY", "ESCALATE")  # 금지!
    print(f"Valid: {result['valid']}, Violation: {result.get('violation')}")

    # 리포트
    print("\n=== Session Report ===")
    report = monitor.get_session_report("test_001")
    print(f"Quality Score: {report['quality_score']}")
    print(f"Compliance Rate: {report['compliance_rate']:.2%}")
    print(f"Violations: {len(report['violations'])}")
