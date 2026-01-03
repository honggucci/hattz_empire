"""
Hattz Empire - Agent Scorecard System
에이전트/LLM 성능 추적 및 동적 라우팅을 위한 점수 시스템

목적:
- 각 에이전트/LLM의 성능 추적
- 자동 검증 (코드 실행, 테스트 통과)
- CEO 피드백 수집
- 점수 기반 동적 라우팅 (성능 낮으면 다른 LLM으로 교체)

저장소: MSSQL agent_logs 테이블
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal
from enum import Enum
import subprocess
import tempfile
import os

# DB 함수 import
try:
    from . import database as db
    HAS_DB = True
except ImportError:
    HAS_DB = False


class TaskResult(Enum):
    """작업 결과"""
    SUCCESS = "success"           # 성공
    PARTIAL = "partial"           # 부분 성공
    FAILURE = "failure"           # 실패
    ERROR = "error"               # 에러 발생
    PENDING = "pending"           # 평가 대기중
    REJECTED = "rejected"         # CEO가 거부


class FeedbackType(Enum):
    """피드백 유형"""
    AUTO_CODE_PASS = "auto_code_pass"      # 코드 자동 실행 성공
    AUTO_CODE_FAIL = "auto_code_fail"      # 코드 자동 실행 실패
    AUTO_TEST_PASS = "auto_test_pass"      # 테스트 자동 통과
    AUTO_TEST_FAIL = "auto_test_fail"      # 테스트 자동 실패
    CEO_APPROVE = "ceo_approve"            # CEO 승인 (👍)
    CEO_REJECT = "ceo_reject"              # CEO 거부 (👎)
    CEO_REDO = "ceo_redo"                  # CEO 재작업 요청
    FOLLOW_UP_SUCCESS = "follow_up_ok"     # 후속 작업 성공
    FOLLOW_UP_FAIL = "follow_up_fail"      # 후속 작업 실패


@dataclass
class AgentLog:
    """에이전트 활동 로그"""
    id: str                                # 고유 ID
    timestamp: datetime                    # 시간
    session_id: str                        # 세션 ID
    task_id: str                           # 작업 ID

    # 에이전트 정보
    role: str                              # excavator, coder, qa, strategist, researcher
    engine: str                            # engine_1, engine_2, merged
    model: str                             # claude-opus-4-5, gpt-5.2, gemini-3-pro

    # 작업 정보
    task_type: str                         # code, strategy, analysis, research
    task_summary: str                      # 작업 요약 (100자)
    input_tokens: int = 0                  # 입력 토큰
    output_tokens: int = 0                 # 출력 토큰
    latency_ms: int = 0                    # 응답 시간 (ms)
    cost_usd: float = 0.0                  # 비용 ($)

    # 결과
    result: TaskResult = TaskResult.PENDING
    result_code: Optional[str] = None      # 에러 코드 등

    # 피드백
    feedback: Optional[FeedbackType] = None
    feedback_timestamp: Optional[datetime] = None
    feedback_note: Optional[str] = None    # CEO 코멘트

    # 점수 (계산됨)
    score_delta: int = 0                   # 이 작업으로 인한 점수 변화

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "task_id": self.task_id,
            "role": self.role,
            "engine": self.engine,
            "model": self.model,
            "task_type": self.task_type,
            "task_summary": self.task_summary,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "result": self.result.value,
            "result_code": self.result_code,
            "feedback": self.feedback.value if self.feedback else None,
            "feedback_timestamp": self.feedback_timestamp.isoformat() if self.feedback_timestamp else None,
            "feedback_note": self.feedback_note,
            "score_delta": self.score_delta,
        }


@dataclass
class ModelScore:
    """모델별 누적 점수"""
    model: str
    role: str

    # 점수
    total_score: int = 100                 # 시작 점수 100

    # 통계
    total_tasks: int = 0
    success_count: int = 0
    failure_count: int = 0
    error_count: int = 0

    # CEO 피드백
    ceo_approve_count: int = 0
    ceo_reject_count: int = 0

    # 자동 검증
    auto_pass_count: int = 0
    auto_fail_count: int = 0

    # 비용
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return self.success_count / self.total_tasks

    @property
    def ceo_approval_rate(self) -> float:
        total = self.ceo_approve_count + self.ceo_reject_count
        if total == 0:
            return 0.0
        return self.ceo_approve_count / total

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "role": self.role,
            "total_score": self.total_score,
            "total_tasks": self.total_tasks,
            "success_rate": f"{self.success_rate:.1%}",
            "ceo_approval_rate": f"{self.ceo_approval_rate:.1%}",
            "total_cost_usd": f"${self.total_cost_usd:.4f}",
            "avg_latency_ms": f"{self.avg_latency_ms:.0f}ms",
        }


# =============================================================================
# Score Calculation Rules
# =============================================================================

SCORE_RULES = {
    # 자동 검증
    FeedbackType.AUTO_CODE_PASS: +10,
    FeedbackType.AUTO_CODE_FAIL: -15,
    FeedbackType.AUTO_TEST_PASS: +15,
    FeedbackType.AUTO_TEST_FAIL: -20,

    # CEO 피드백 (가장 중요)
    FeedbackType.CEO_APPROVE: +20,
    FeedbackType.CEO_REJECT: -25,
    FeedbackType.CEO_REDO: -10,

    # 후속 작업
    FeedbackType.FOLLOW_UP_SUCCESS: +15,
    FeedbackType.FOLLOW_UP_FAIL: -15,
}

# 모델 가격 (per 1K tokens, 2026.01 기준)
MODEL_PRICING = {
    "claude-opus-4-5-20251101": {"input": 0.015, "output": 0.075},
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "gpt-5.2": {"input": 0.010, "output": 0.030},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},  # 저렴!
    "gemini-3-pro-preview": {"input": 0.00125, "output": 0.005},
}


# =============================================================================
# Agent Scorecard Manager (DB-based)
# =============================================================================

class AgentScorecard:
    """에이전트 점수 관리자 (MSSQL 기반)"""

    def __init__(self):
        """초기화 - DB 테이블 생성"""
        self._initialized = False
        if HAS_DB:
            try:
                db.create_agent_logs_table()
                self._initialized = True
            except Exception as e:
                print(f"[Scorecard] DB init error: {e}")

    @property
    def logs(self) -> list:
        """로그 목록 (DB에서 조회)"""
        if not HAS_DB or not self._initialized:
            return []
        try:
            return db.get_agent_logs(limit=100)
        except:
            return []

    def log_task(
        self,
        session_id: str,
        task_id: str,
        role: str,
        engine: str,
        model: str,
        task_type: str,
        task_summary: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
    ) -> str:
        """새 작업 로그 생성 (DB 저장)"""
        log_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{role}_{engine}"

        # 비용 계산
        pricing = MODEL_PRICING.get(model, {"input": 0.01, "output": 0.03})
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1000

        if HAS_DB and self._initialized:
            try:
                db.add_agent_log(
                    log_id=log_id,
                    session_id=session_id,
                    task_id=task_id,
                    role=role,
                    engine=engine,
                    model=model,
                    task_type=task_type,
                    task_summary=task_summary[:200],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    cost_usd=cost,
                    result="pending"
                )
            except Exception as e:
                print(f"[Scorecard] DB log error: {e}")

        return log_id

    def add_feedback(
        self,
        log_id: str,
        feedback: FeedbackType,
        note: Optional[str] = None
    ) -> bool:
        """피드백 추가 (DB 업데이트)"""
        score_delta = SCORE_RULES.get(feedback, 0)

        # 결과 결정
        if feedback in [FeedbackType.CEO_APPROVE, FeedbackType.AUTO_CODE_PASS, FeedbackType.AUTO_TEST_PASS]:
            result = "success"
        elif feedback in [FeedbackType.CEO_REJECT, FeedbackType.AUTO_CODE_FAIL, FeedbackType.AUTO_TEST_FAIL]:
            result = "failure"
        elif feedback == FeedbackType.CEO_REDO:
            result = "partial"
        else:
            result = None

        if HAS_DB and self._initialized:
            try:
                return db.add_agent_feedback(
                    log_id=log_id,
                    feedback=feedback.value,
                    score_delta=score_delta,
                    note=note,
                    result=result
                )
            except Exception as e:
                print(f"[Scorecard] DB feedback error: {e}")
                return False
        return False

    def get_scores(self) -> dict:
        """모든 점수 조회 (DB 집계)"""
        if not HAS_DB or not self._initialized:
            return {}

        try:
            scores = db.get_model_scores()
            return {f"{s['model']}:{s['role']}": s for s in scores}
        except Exception as e:
            print(f"[Scorecard] DB scores error: {e}")
            return {}

    def get_best_model(self, role: str) -> Optional[str]:
        """역할별 최고 점수 모델 반환 (동적 라우팅용)"""
        if not HAS_DB or not self._initialized:
            return None

        try:
            return db.get_best_model_for_role(role)
        except:
            return None

    def get_leaderboard(self) -> list[dict]:
        """전체 리더보드 (DB 집계)"""
        if not HAS_DB or not self._initialized:
            return []

        try:
            return db.get_model_scores()
        except:
            return []

    def get_role_summary(self, role: str) -> dict:
        """역할별 요약"""
        scores = self.get_leaderboard()
        role_scores = [s for s in scores if s.get("role") == role]

        return {
            "role": role,
            "models": sorted(
                role_scores,
                key=lambda x: x.get("total_score", 0),
                reverse=True
            )
        }

    def get_recent_log_id(self, session_id: Optional[str] = None) -> Optional[str]:
        """가장 최근 로그 ID 조회"""
        if not HAS_DB or not self._initialized:
            return None

        try:
            return db.get_recent_log_id(session_id)
        except:
            return None


# =============================================================================
# Code Validator (자동 검증)
# =============================================================================

class CodeValidator:
    """코드 자동 검증기"""

    @staticmethod
    def validate_python(code: str, timeout: int = 10) -> tuple[bool, str]:
        """
        Python 코드 검증 (syntax + dry-run)

        Returns:
            (success: bool, message: str)
        """
        # 1. Syntax Check
        try:
            compile(code, "<string>", "exec")
        except SyntaxError as e:
            return False, f"SyntaxError: {e}"

        # 2. Dry-run in sandbox
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                encoding="utf-8"
            ) as f:
                # 위험한 import 체크
                dangerous = ["os.system", "subprocess", "eval(", "exec(", "__import__"]
                for d in dangerous:
                    if d in code:
                        return False, f"Dangerous code detected: {d}"

                f.write(code)
                temp_path = f.name

            # 실행 (timeout 적용)
            result = subprocess.run(
                ["python", temp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tempfile.gettempdir()
            )

            # 정리
            os.unlink(temp_path)

            if result.returncode == 0:
                return True, "Code executed successfully"
            else:
                return False, f"RuntimeError: {result.stderr[:500]}"

        except subprocess.TimeoutExpired:
            return False, f"Timeout: Code took longer than {timeout}s"
        except Exception as e:
            return False, f"ValidationError: {str(e)}"

    @staticmethod
    def validate_syntax_only(code: str) -> tuple[bool, str]:
        """문법만 체크 (실행 안 함)"""
        try:
            compile(code, "<string>", "exec")
            return True, "Syntax OK"
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}: {e.msg}"


# =============================================================================
# Singleton
# =============================================================================

_scorecard: Optional[AgentScorecard] = None


def get_scorecard() -> AgentScorecard:
    """Scorecard 싱글톤"""
    global _scorecard
    if _scorecard is None:
        _scorecard = AgentScorecard()
    return _scorecard


def get_validator() -> CodeValidator:
    """Validator 인스턴스"""
    return CodeValidator()


# =============================================================================
# CLI Test
# =============================================================================

def main():
    """테스트"""
    print("=" * 60)
    print("AGENT SCORECARD TEST")
    print("=" * 60)

    scorecard = AgentScorecard(log_dir="logs/test_scores")

    # 테스트 로그 생성
    log1 = scorecard.log_task(
        session_id="test_001",
        task_id="task_001",
        role="coder",
        engine="engine_1",
        model="claude-opus-4-5-20251101",
        task_type="code",
        task_summary="RSI 계산 함수 구현",
        input_tokens=500,
        output_tokens=1000,
        latency_ms=2500,
    )
    print(f"\n[LOG] Created: {log1.id}")

    # 피드백 추가
    scorecard.add_feedback(log1.id, FeedbackType.AUTO_CODE_PASS)
    scorecard.add_feedback(log1.id, FeedbackType.CEO_APPROVE, "잘했어!")

    # 점수 확인
    print("\n[LEADERBOARD]")
    for entry in scorecard.get_leaderboard():
        print(f"  {entry['model']}:{entry['role']} = {entry['total_score']} pts")

    # 코드 검증 테스트
    print("\n[CODE VALIDATOR]")
    validator = CodeValidator()

    good_code = "print('Hello, World!')"
    bad_code = "print('Hello"

    ok, msg = validator.validate_python(good_code)
    print(f"  Good code: {ok} - {msg}")

    ok, msg = validator.validate_syntax_only(bad_code)
    print(f"  Bad code: {ok} - {msg}")


if __name__ == "__main__":
    main()
