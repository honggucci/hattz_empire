"""
Hattz Empire - YAML Logger
모든 에이전트 작업 로그를 YAML로 저장

구조:
  logs/
  └── daily/
      └── YYYY/MM/DD/
          ├── excavator_HHMMSS.yaml
          ├── strategist_HHMMSS.yaml
          ├── coder_HHMMSS.yaml
          └── qa_HHMMSS.yaml
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, asdict

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    print("[WARNING] PyYAML not installed. Run: pip install pyyaml")


@dataclass
class LogEntry:
    """로그 엔트리"""
    timestamp: str
    role: str
    engine: str  # engine_1, engine_2, merged
    action: str
    input_data: Any
    output_data: Any
    metadata: dict = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class YAMLLogger:
    """
    YAML 기반 로거

    사용법:
        logger = YAMLLogger()
        logger.log("excavator", "engine_1", "parse", input_data, output_data)
        logger.save_session()
    """

    def __init__(self, base_dir: str = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path(__file__).parent / "logs"

        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "daily").mkdir(exist_ok=True)

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.entries: list[LogEntry] = []
        self.current_role: Optional[str] = None

    def _get_date_path(self) -> Path:
        """오늘 날짜 경로"""
        now = datetime.now()
        date_path = self.base_dir / "daily" / now.strftime("%Y/%m/%d")
        date_path.mkdir(parents=True, exist_ok=True)
        return date_path

    def log(
        self,
        role: str,
        engine: str,
        action: str,
        input_data: Any = None,
        output_data: Any = None,
        metadata: dict = None
    ) -> LogEntry:
        """
        로그 기록

        Args:
            role: excavator, strategist, coder, qa, pm
            engine: engine_1, engine_2, merged
            action: parse, infer, generate, review, etc.
            input_data: 입력 데이터
            output_data: 출력 데이터
            metadata: 추가 메타데이터
        """
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            role=role,
            engine=engine,
            action=action,
            input_data=input_data,
            output_data=output_data,
            metadata=metadata
        )

        self.entries.append(entry)
        self.current_role = role

        # 즉시 파일에 append
        self._append_to_file(entry)

        return entry

    def _append_to_file(self, entry: LogEntry):
        """로그 엔트리를 파일에 추가"""
        if not HAS_YAML:
            return

        date_path = self._get_date_path()
        time_str = datetime.now().strftime("%H%M%S")
        filename = f"{entry.role}_{self.session_id}.yaml"
        filepath = date_path / filename

        # 기존 파일 로드 또는 새로 생성
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {"entries": []}
        else:
            data = {
                "session_id": self.session_id,
                "role": entry.role,
                "started_at": entry.timestamp,
                "entries": []
            }

        data["entries"].append(entry.to_dict())
        data["updated_at"] = entry.timestamp

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def log_dual_engine(
        self,
        role: str,
        action: str,
        input_data: Any,
        engine_1_output: Any,
        engine_2_output: Any,
        merged_output: Any,
        merge_strategy: str
    ):
        """
        듀얼 엔진 로그 (한번에 3개 기록)

        Args:
            role: 역할
            action: 액션
            input_data: 입력
            engine_1_output: 엔진1 출력
            engine_2_output: 엔진2 출력
            merged_output: 병합된 출력
            merge_strategy: 병합 전략
        """
        # Engine 1
        self.log(role, "engine_1", action, input_data, engine_1_output)

        # Engine 2
        self.log(role, "engine_2", action, input_data, engine_2_output)

        # Merged
        self.log(role, "merged", action, {
            "engine_1": engine_1_output,
            "engine_2": engine_2_output,
            "strategy": merge_strategy
        }, merged_output, metadata={"merge_strategy": merge_strategy})

    def save_session_summary(self, summary: dict = None):
        """세션 요약 저장"""
        if not HAS_YAML:
            return

        date_path = self._get_date_path()
        filename = f"session_{self.session_id}_summary.yaml"
        filepath = date_path / filename

        # 역할별 통계
        role_stats = {}
        for entry in self.entries:
            if entry.role not in role_stats:
                role_stats[entry.role] = {"count": 0, "engines": set()}
            role_stats[entry.role]["count"] += 1
            role_stats[entry.role]["engines"].add(entry.engine)

        # set을 list로 변환
        for role in role_stats:
            role_stats[role]["engines"] = list(role_stats[role]["engines"])

        data = {
            "session_id": self.session_id,
            "started_at": self.entries[0].timestamp if self.entries else None,
            "ended_at": datetime.now().isoformat(),
            "total_entries": len(self.entries),
            "role_stats": role_stats,
            "summary": summary or {}
        }

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        return filepath

    def get_session_log(self, role: str = None) -> list[dict]:
        """세션 로그 가져오기"""
        if role:
            return [e.to_dict() for e in self.entries if e.role == role]
        return [e.to_dict() for e in self.entries]

    def get_last_output(self, role: str, engine: str = "merged") -> Any:
        """마지막 출력 가져오기"""
        for entry in reversed(self.entries):
            if entry.role == role and entry.engine == engine:
                return entry.output_data
        return None


# =============================================================================
# Singleton
# =============================================================================

_logger: Optional[YAMLLogger] = None


def get_logger() -> YAMLLogger:
    """로거 싱글톤"""
    global _logger
    if _logger is None:
        _logger = YAMLLogger()
    return _logger


def log(role: str, engine: str, action: str, input_data: Any = None, output_data: Any = None):
    """빠른 로깅"""
    return get_logger().log(role, engine, action, input_data, output_data)


# =============================================================================
# CLI
# =============================================================================

def main():
    """테스트"""
    logger = YAMLLogger()

    # 테스트 로그
    logger.log("excavator", "engine_1", "parse",
               {"input": "RSI 전략 만들어줘"},
               {"keywords": ["RSI", "전략"], "sentiment": "request"})

    logger.log("excavator", "engine_2", "parse",
               {"input": "RSI 전략 만들어줘"},
               {"structure": "feature_request", "domain": "trading"})

    logger.log("excavator", "merged", "parse",
               {"engine_1": "...", "engine_2": "..."},
               {"final": "RSI 기반 매매 전략 개발 요청"})

    summary_path = logger.save_session_summary({"test": True})
    print(f"Summary saved: {summary_path}")


if __name__ == "__main__":
    main()
