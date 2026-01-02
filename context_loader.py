"""
Hattz Empire - Context Loader

세션 복원을 위한 컨텍스트 로더
새 세션 시작시 자동으로 이전 맥락 주입

사용법:
    from hattz_empire.context_loader import ContextLoader

    loader = ContextLoader()

    # 전체 컨텍스트 (PM용)
    context = loader.get_full_context()

    # 역할별 컨텍스트
    context = loader.get_context_for_role("excavator")

    # 특정 Task 컨텍스트
    context = loader.get_task_context("2026-01-02_001")
"""
import json
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

try:
    from .storage.index import get_index, LogIndex
except ImportError:
    from storage.index import get_index, LogIndex


@dataclass
class SessionContext:
    """세션 컨텍스트"""
    summary: str              # 요약
    recent_tasks: list        # 최근 Task 목록
    last_decisions: list      # 최근 의사결정
    pending_items: list       # 미완료 항목
    key_entities: list        # 핵심 키워드/엔티티
    raw_messages: int         # 원본 메시지 수
    time_range: str           # 시간 범위


class ContextLoader:
    """
    컨텍스트 로더

    세션 복원을 위해 MSSQL에서 로그를 조회하고
    각 AI에게 맞는 형태로 컨텍스트 생성
    """

    # 역할별 관심 영역
    ROLE_FOCUS = {
        "excavator": ["ceo", "excavator", "request"],
        "strategist": ["strategist", "strategy", "analysis"],
        "coder": ["coder", "code", "implementation"],
        "qa": ["qa", "test", "review", "issue"],
        "analyst": ["*"],  # 전체
        "pm": ["*"],  # 전체
    }

    def __init__(self):
        self.index: LogIndex = get_index()

    def get_full_context(self, days: int = 7, max_messages: int = 500) -> SessionContext:
        """
        전체 컨텍스트 (PM, Analyst용)

        Args:
            days: 조회할 일수
            max_messages: 최대 메시지 수

        Returns:
            SessionContext
        """
        # 최근 N일 로그 조회
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        messages = []
        for i in range(days):
            date = (end_date - timedelta(days=i)).strftime("%Y-%m-%d")
            day_messages = self.index.search_by_date(date, limit=max_messages // days)
            messages.extend(day_messages)

        if not messages:
            return SessionContext(
                summary="이전 기록이 없습니다.",
                recent_tasks=[],
                last_decisions=[],
                pending_items=[],
                key_entities=[],
                raw_messages=0,
                time_range=""
            )

        # 분석
        return self._analyze_messages(messages, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))

    def get_context_for_role(self, role: str, days: int = 3, max_messages: int = 200) -> SessionContext:
        """
        역할별 컨텍스트

        Args:
            role: 역할 (excavator, strategist, coder, qa, analyst, pm)
            days: 조회할 일수
            max_messages: 최대 메시지 수

        Returns:
            SessionContext
        """
        focus = self.ROLE_FOCUS.get(role, ["*"])

        if "*" in focus:
            return self.get_full_context(days, max_messages)

        # 역할 관련 메시지만 필터링
        messages = []
        for keyword in focus:
            results = self.index.search(keyword, limit=max_messages // len(focus))
            messages.extend(results)

        # 중복 제거
        seen = set()
        unique_messages = []
        for msg in messages:
            if msg["id"] not in seen:
                seen.add(msg["id"])
                unique_messages.append(msg)

        if not unique_messages:
            return SessionContext(
                summary=f"{role} 관련 이전 기록이 없습니다.",
                recent_tasks=[],
                last_decisions=[],
                pending_items=[],
                key_entities=[],
                raw_messages=0,
                time_range=""
            )

        return self._analyze_messages(unique_messages, "", "")

    def get_task_context(self, task_id: str) -> SessionContext:
        """
        특정 Task 컨텍스트

        Args:
            task_id: Task ID

        Returns:
            SessionContext
        """
        messages = self.index.search_by_task(task_id)

        if not messages:
            return SessionContext(
                summary=f"Task {task_id} 기록이 없습니다.",
                recent_tasks=[task_id],
                last_decisions=[],
                pending_items=[],
                key_entities=[],
                raw_messages=0,
                time_range=""
            )

        return self._analyze_messages(messages, "", "", single_task=task_id)

    def _analyze_messages(
        self,
        messages: list,
        start_date: str,
        end_date: str,
        single_task: str = None
    ) -> SessionContext:
        """메시지 분석하여 컨텍스트 생성"""

        # Task 추출
        tasks = {}
        for msg in messages:
            task_id = msg.get("task_id")
            if task_id:
                if task_id not in tasks:
                    tasks[task_id] = {"count": 0, "agents": set(), "last_activity": ""}
                tasks[task_id]["count"] += 1
                tasks[task_id]["agents"].add(msg.get("from_agent", "").split(".")[0])
                tasks[task_id]["last_activity"] = str(msg.get("timestamp", ""))[:19]

        recent_tasks = [
            {"task_id": tid, "messages": info["count"], "agents": list(info["agents"])}
            for tid, info in sorted(tasks.items(), key=lambda x: x[1]["last_activity"], reverse=True)[:5]
        ]

        # 의사결정 추출 (decision, state 타입)
        decisions = []
        for msg in messages:
            if msg.get("msg_type") in ["decision", "state"]:
                decisions.append({
                    "time": str(msg.get("timestamp", ""))[:19],
                    "by": msg.get("from_agent", ""),
                    "content": msg.get("content_preview", "")[:200]
                })
        last_decisions = decisions[:10]

        # 키워드 추출
        all_keywords = []
        for msg in messages:
            keywords = msg.get("keywords", "")
            if keywords:
                all_keywords.extend(keywords.split())

        # 빈도순 정렬
        keyword_freq = {}
        for kw in all_keywords:
            keyword_freq[kw] = keyword_freq.get(kw, 0) + 1
        key_entities = [kw for kw, _ in sorted(keyword_freq.items(), key=lambda x: -x[1])[:20]]

        # 요약 생성
        summary_parts = []
        if single_task:
            summary_parts.append(f"Task {single_task} 분석")
        else:
            summary_parts.append(f"최근 {len(messages)}개 메시지 분석")

        if recent_tasks:
            summary_parts.append(f"활성 Task: {len(recent_tasks)}개")
        if key_entities:
            summary_parts.append(f"주요 키워드: {', '.join(key_entities[:5])}")

        summary = " | ".join(summary_parts)

        # 시간 범위
        if messages:
            times = [str(m.get("timestamp", "")) for m in messages if m.get("timestamp")]
            if times:
                time_range = f"{min(times)[:10]} ~ {max(times)[:10]}"
            else:
                time_range = f"{start_date} ~ {end_date}"
        else:
            time_range = ""

        return SessionContext(
            summary=summary,
            recent_tasks=recent_tasks,
            last_decisions=last_decisions,
            pending_items=[],  # TODO: 미완료 항목 추출 로직
            key_entities=key_entities,
            raw_messages=len(messages),
            time_range=time_range
        )

    def build_system_prompt_addition(self, role: str) -> str:
        """
        시스템 프롬프트에 추가할 컨텍스트 문자열 생성

        Args:
            role: 역할

        Returns:
            시스템 프롬프트에 추가할 문자열
        """
        context = self.get_context_for_role(role)

        if context.raw_messages == 0:
            return ""

        lines = [
            "",
            "# Previous Session Context (자동 복원)",
            f"Time Range: {context.time_range}",
            f"Messages Analyzed: {context.raw_messages}",
            "",
        ]

        if context.recent_tasks:
            lines.append("## Recent Tasks")
            for task in context.recent_tasks[:3]:
                lines.append(f"- {task['task_id']}: {task['messages']} messages, agents: {', '.join(task['agents'])}")
            lines.append("")

        if context.last_decisions:
            lines.append("## Last Decisions")
            for dec in context.last_decisions[:3]:
                lines.append(f"- [{dec['time']}] {dec['by']}: {dec['content'][:100]}...")
            lines.append("")

        if context.key_entities:
            lines.append(f"## Key Topics: {', '.join(context.key_entities[:10])}")
            lines.append("")

        return "\n".join(lines)

    def build_conversation_starter(self, role: str) -> str:
        """
        새 세션 시작시 첫 메시지로 보낼 컨텍스트

        Args:
            role: 역할

        Returns:
            대화 시작 메시지
        """
        context = self.get_context_for_role(role)

        if context.raw_messages == 0:
            return "새로운 세션입니다. 이전 기록이 없습니다."

        lines = [
            "# Session Recovery (세션 복원)",
            "",
            f"이전 세션에서 {context.raw_messages}개의 메시지를 분석했습니다.",
            f"기간: {context.time_range}",
            "",
        ]

        if context.recent_tasks:
            lines.append("## 최근 작업")
            for task in context.recent_tasks:
                lines.append(f"- **{task['task_id']}**: {task['messages']}개 메시지")
            lines.append("")

        if context.key_entities:
            lines.append(f"## 주요 주제")
            lines.append(f"{', '.join(context.key_entities[:10])}")
            lines.append("")

        if context.last_decisions:
            lines.append("## 최근 결정사항")
            for dec in context.last_decisions[:5]:
                lines.append(f"- {dec['content'][:150]}...")
            lines.append("")

        lines.append("---")
        lines.append("이전 맥락을 바탕으로 계속 진행하겠습니다.")

        return "\n".join(lines)


# =============================================================================
# Singleton
# =============================================================================

_loader: Optional[ContextLoader] = None


def get_context_loader() -> ContextLoader:
    """ContextLoader 싱글톤"""
    global _loader
    if _loader is None:
        _loader = ContextLoader()
    return _loader


# =============================================================================
# Quick API
# =============================================================================

def restore_session(role: str = "pm") -> str:
    """세션 복원 (빠른 API)"""
    return get_context_loader().build_conversation_starter(role)


def get_context(role: str = "pm") -> SessionContext:
    """컨텍스트 가져오기"""
    return get_context_loader().get_context_for_role(role)


# =============================================================================
# CLI
# =============================================================================

def main():
    """테스트"""
    print("\n" + "="*60)
    print("CONTEXT LOADER TEST")
    print("="*60)

    loader = ContextLoader()

    print("\n[1] Full Context")
    ctx = loader.get_full_context(days=1)
    print(f"  Summary: {ctx.summary}")
    print(f"  Messages: {ctx.raw_messages}")
    print(f"  Tasks: {len(ctx.recent_tasks)}")
    print(f"  Keywords: {ctx.key_entities[:5]}")

    print("\n[2] Role Context (excavator)")
    ctx = loader.get_context_for_role("excavator")
    print(f"  Summary: {ctx.summary}")

    print("\n[3] System Prompt Addition")
    addition = loader.build_system_prompt_addition("pm")
    print(addition[:500] if addition else "  (empty)")

    print("\n[4] Conversation Starter")
    starter = loader.build_conversation_starter("pm")
    print(starter[:500])

    print("\nDone!")


if __name__ == "__main__":
    main()
