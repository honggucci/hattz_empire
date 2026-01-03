"""
Hattz Empire - Circuit Breaker
개소리 루프 / 비용 폭탄 방지 시스템

"무한 루프 돌다가 지갑 터지는 거 방지"
"""
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from difflib import SequenceMatcher


class BreakerState(Enum):
    """서킷 브레이커 상태"""
    CLOSED = "closed"      # 정상 작동
    OPEN = "open"          # 차단됨
    HALF_OPEN = "half_open"  # 테스트 중


@dataclass
class TaskMetrics:
    """태스크별 메트릭"""
    task_id: str
    call_count: int = 0
    escalation_count: int = 0
    total_cost: float = 0.0
    responses: List[str] = field(default_factory=list)
    agent_sequence: List[str] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)


@dataclass
class SessionMetrics:
    """세션별 메트릭"""
    session_id: str
    total_cost: float = 0.0
    task_count: int = 0
    failure_count: int = 0
    start_time: datetime = field(default_factory=datetime.now)


class CircuitBreaker:
    """
    개소리 루프 방지 시스템

    기능:
    1. 호출 횟수 제한
    2. 비용 한도
    3. 반복 응답 감지
    4. 에이전트 핑퐁 감지
    5. CEO 알림 트리거
    """

    # === 제한 설정 ===
    MAX_CALLS_PER_TASK = 10           # 태스크당 최대 호출
    MAX_ESCALATIONS = 3               # 최대 승격 횟수
    MAX_AGENT_PINGPONG = 3            # 에이전트 간 핑퐁 최대

    MAX_COST_PER_TASK = 0.50          # 태스크당 최대 $0.50
    MAX_COST_PER_SESSION = 5.00       # 세션당 최대 $5
    DAILY_BUDGET = 10.00              # 일일 예산 $10

    SIMILARITY_THRESHOLD = 0.85       # 반복 응답 감지 임계값
    IDLE_TIMEOUT_SECONDS = 300        # 5분 무응답 시 자동 종료

    def __init__(self):
        self.state = BreakerState.CLOSED
        self.task_metrics: Dict[str, TaskMetrics] = {}
        self.session_metrics: Dict[str, SessionMetrics] = {}
        self.daily_cost: float = 0.0
        self.daily_reset_time: datetime = datetime.now()
        self.alerts: List[Dict] = []
        self.on_alert: Optional[Callable] = None  # CEO 알림 콜백

    def _get_task_metrics(self, task_id: str) -> TaskMetrics:
        """태스크 메트릭 조회 (없으면 생성)"""
        if task_id not in self.task_metrics:
            self.task_metrics[task_id] = TaskMetrics(task_id=task_id)
        return self.task_metrics[task_id]

    def _get_session_metrics(self, session_id: str) -> SessionMetrics:
        """세션 메트릭 조회 (없으면 생성)"""
        if session_id not in self.session_metrics:
            self.session_metrics[session_id] = SessionMetrics(session_id=session_id)
        return self.session_metrics[session_id]

    def _reset_daily_if_needed(self):
        """일일 리셋 체크"""
        now = datetime.now()
        if now.date() > self.daily_reset_time.date():
            self.daily_cost = 0.0
            self.daily_reset_time = now

    def _check_similarity(self, new_response: str, previous_responses: List[str]) -> float:
        """응답 유사도 체크"""
        if not previous_responses:
            return 0.0

        max_similarity = 0.0
        for prev in previous_responses[-3:]:  # 최근 3개와 비교
            ratio = SequenceMatcher(None, new_response, prev).ratio()
            max_similarity = max(max_similarity, ratio)

        return max_similarity

    def _detect_pingpong(self, agent_sequence: List[str]) -> bool:
        """에이전트 핑퐁 감지 (A→B→A→B 패턴)"""
        if len(agent_sequence) < 4:
            return False

        # 최근 4개 패턴 체크
        recent = agent_sequence[-4:]
        if recent[0] == recent[2] and recent[1] == recent[3] and recent[0] != recent[1]:
            return True

        return False

    def _add_alert(self, level: str, message: str, task_id: str = None, session_id: str = None):
        """알림 추가"""
        alert = {
            "level": level,  # warning, critical, info
            "message": message,
            "task_id": task_id,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
        }
        self.alerts.append(alert)

        # CEO 콜백 호출
        if self.on_alert:
            self.on_alert(alert)

        return alert

    def check_before_call(
        self,
        task_id: str,
        session_id: str,
        agent: str,
        estimated_cost: float = 0.01
    ) -> Dict:
        """
        LLM 호출 전 체크

        Returns:
            {
                "allowed": True/False,
                "reason": "이유",
                "warnings": ["경고 목록"],
                "state": "closed/open/half_open"
            }
        """
        self._reset_daily_if_needed()

        task = self._get_task_metrics(task_id)
        session = self._get_session_metrics(session_id)

        warnings = []

        # 1. 서킷 브레이커 상태 체크
        if self.state == BreakerState.OPEN:
            return {
                "allowed": False,
                "reason": "Circuit breaker OPEN - 시스템 일시 중단",
                "warnings": [],
                "state": self.state.value
            }

        # 2. 호출 횟수 체크
        if task.call_count >= self.MAX_CALLS_PER_TASK:
            self._add_alert("critical", f"태스크 호출 한도 초과: {task.call_count}회", task_id, session_id)
            return {
                "allowed": False,
                "reason": f"태스크당 최대 호출 횟수 초과 ({self.MAX_CALLS_PER_TASK}회)",
                "warnings": [],
                "state": self.state.value
            }

        # 3. 승격 횟수 체크
        if task.escalation_count >= self.MAX_ESCALATIONS:
            self._add_alert("critical", f"승격 한도 초과: {task.escalation_count}회", task_id, session_id)
            return {
                "allowed": False,
                "reason": f"최대 승격 횟수 초과 ({self.MAX_ESCALATIONS}회)",
                "warnings": [],
                "state": self.state.value
            }

        # 4. 비용 체크 - 태스크
        if task.total_cost + estimated_cost > self.MAX_COST_PER_TASK:
            self._add_alert("critical", f"태스크 비용 한도: ${task.total_cost:.4f}", task_id, session_id)
            return {
                "allowed": False,
                "reason": f"태스크 비용 한도 초과 (${self.MAX_COST_PER_TASK})",
                "warnings": [],
                "state": self.state.value
            }

        # 5. 비용 체크 - 세션
        if session.total_cost + estimated_cost > self.MAX_COST_PER_SESSION:
            self._add_alert("critical", f"세션 비용 한도: ${session.total_cost:.4f}", task_id, session_id)
            return {
                "allowed": False,
                "reason": f"세션 비용 한도 초과 (${self.MAX_COST_PER_SESSION})",
                "warnings": [],
                "state": self.state.value
            }

        # 6. 비용 체크 - 일일
        if self.daily_cost + estimated_cost > self.DAILY_BUDGET:
            self.state = BreakerState.OPEN
            self._add_alert("critical", f"일일 예산 소진: ${self.daily_cost:.2f}", task_id, session_id)
            return {
                "allowed": False,
                "reason": f"일일 예산 소진 (${self.DAILY_BUDGET})",
                "warnings": [],
                "state": self.state.value
            }

        # 7. 에이전트 핑퐁 감지
        if self._detect_pingpong(task.agent_sequence + [agent]):
            warnings.append("에이전트 핑퐁 감지 - CEO 확인 권장")
            self._add_alert("warning", "에이전트 핑퐁 감지", task_id, session_id)

        # 8. 경고 레벨 체크
        if task.call_count >= self.MAX_CALLS_PER_TASK * 0.7:
            warnings.append(f"호출 횟수 경고: {task.call_count}/{self.MAX_CALLS_PER_TASK}")

        if task.total_cost >= self.MAX_COST_PER_TASK * 0.5:
            warnings.append(f"비용 경고: ${task.total_cost:.4f}/${self.MAX_COST_PER_TASK}")

        if self.daily_cost >= self.DAILY_BUDGET * 0.8:
            warnings.append(f"일일 예산 경고: ${self.daily_cost:.2f}/${self.DAILY_BUDGET}")

        return {
            "allowed": True,
            "reason": "OK",
            "warnings": warnings,
            "state": self.state.value
        }

    def record_call(
        self,
        task_id: str,
        session_id: str,
        agent: str,
        response: str,
        cost: float,
        is_escalation: bool = False
    ) -> Dict:
        """
        LLM 호출 결과 기록

        Returns:
            {
                "similarity_alert": True/False,
                "pingpong_alert": True/False,
                "cost_warning": True/False
            }
        """
        task = self._get_task_metrics(task_id)
        session = self._get_session_metrics(session_id)

        # 메트릭 업데이트
        task.call_count += 1
        task.total_cost += cost
        task.agent_sequence.append(agent)
        task.last_activity = datetime.now()

        session.total_cost += cost
        self.daily_cost += cost

        if is_escalation:
            task.escalation_count += 1

        alerts = {
            "similarity_alert": False,
            "pingpong_alert": False,
            "cost_warning": False,
        }

        # 반복 응답 감지
        similarity = self._check_similarity(response, task.responses)
        if similarity >= self.SIMILARITY_THRESHOLD:
            alerts["similarity_alert"] = True
            self._add_alert(
                "warning",
                f"반복 응답 감지 (유사도: {similarity:.1%})",
                task_id,
                session_id
            )

        task.responses.append(response[:500])  # 처음 500자만 저장

        # 핑퐁 감지
        if self._detect_pingpong(task.agent_sequence):
            alerts["pingpong_alert"] = True

        # 비용 경고
        if task.total_cost >= self.MAX_COST_PER_TASK * 0.8:
            alerts["cost_warning"] = True

        return alerts

    def force_stop(self, task_id: str, reason: str = "수동 중단"):
        """강제 중단"""
        if task_id in self.task_metrics:
            self._add_alert("info", f"태스크 강제 중단: {reason}", task_id)
            del self.task_metrics[task_id]

    def reset_breaker(self):
        """서킷 브레이커 리셋 (CEO 권한)"""
        self.state = BreakerState.CLOSED
        self._add_alert("info", "Circuit breaker 리셋됨 (CEO)")

    def get_status(self) -> Dict:
        """현재 상태 조회"""
        self._reset_daily_if_needed()

        return {
            "state": self.state.value,
            "daily_cost": f"${self.daily_cost:.4f}",
            "daily_budget": f"${self.DAILY_BUDGET}",
            "daily_usage": f"{(self.daily_cost / self.DAILY_BUDGET * 100):.1f}%",
            "active_tasks": len(self.task_metrics),
            "active_sessions": len(self.session_metrics),
            "recent_alerts": self.alerts[-10:],
        }

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """태스크 상태 조회"""
        if task_id not in self.task_metrics:
            return None

        task = self.task_metrics[task_id]
        return {
            "task_id": task_id,
            "call_count": f"{task.call_count}/{self.MAX_CALLS_PER_TASK}",
            "escalation_count": f"{task.escalation_count}/{self.MAX_ESCALATIONS}",
            "cost": f"${task.total_cost:.4f}/${self.MAX_COST_PER_TASK}",
            "agent_sequence": task.agent_sequence[-5:],
            "duration": str(datetime.now() - task.start_time),
        }


# === 싱글톤 인스턴스 ===
_breaker: Optional[CircuitBreaker] = None


def get_breaker() -> CircuitBreaker:
    """Circuit Breaker 싱글톤"""
    global _breaker
    if _breaker is None:
        _breaker = CircuitBreaker()
    return _breaker


# === 테스트 ===
if __name__ == "__main__":
    breaker = get_breaker()

    print("=== Circuit Breaker 테스트 ===\n")

    # 정상 호출
    for i in range(5):
        result = breaker.check_before_call(
            task_id="test_001",
            session_id="session_001",
            agent="coder",
            estimated_cost=0.05
        )
        print(f"Call {i+1}: {result['allowed']} - {result['reason']}")

        if result["allowed"]:
            breaker.record_call(
                task_id="test_001",
                session_id="session_001",
                agent="coder",
                response=f"응답 {i+1}",
                cost=0.05
            )

    print("\n" + "="*50)
    print(breaker.get_status())

    print("\n" + "="*50)
    print("Task Status:", breaker.get_task_status("test_001"))
