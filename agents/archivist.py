"""
Archivist Agent - Gemini 3 Pro
Responsibilities: 대화 백업, 히스토리 검색, 프로젝트 메모리
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

try:
    import google.generativeai as genai
except ImportError:
    genai = None

from ..config import get_model_config, get_api_key, SYSTEM_PROMPTS


@dataclass
class ConversationEntry:
    """대화 기록 엔트리"""
    timestamp: str
    participants: list[str]
    topics: list[str]
    content: str
    decisions: list[str]
    action_items: list[str]


class Archivist:
    """
    Archivist Agent
    - 모든 대화 백업 (1M 토큰 컨텍스트!)
    - 히스토리 검색
    - 프로젝트 메모리 유지
    """

    def __init__(self, sessions_dir: str = None):
        self.config = get_model_config("archivist")
        self.api_key = get_api_key("archivist")
        self.system_prompt = SYSTEM_PROMPTS["archivist"]

        # Sessions directory
        if sessions_dir:
            self.sessions_dir = Path(sessions_dir)
        else:
            self.sessions_dir = Path(__file__).parent.parent / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Gemini
        self.model = None
        if genai and self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(self.config.model_id)

        # In-memory conversation history
        self.history: list[ConversationEntry] = []
        self._load_history()

    def _load_history(self):
        """Load existing history from files"""
        for file in sorted(self.sessions_dir.glob("*.json")):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for entry in data:
                            self.history.append(ConversationEntry(**entry))
                    elif isinstance(data, dict):
                        self.history.append(ConversationEntry(**data))
            except Exception as e:
                print(f"[Archivist] Error loading {file}: {e}")

    def record(
        self,
        content: str,
        participants: list[str],
        topics: list[str] = None,
        decisions: list[str] = None,
        action_items: list[str] = None
    ) -> ConversationEntry:
        """
        대화 기록 저장

        Args:
            content: 대화 내용
            participants: 참여자 목록 (e.g., ["CEO", "PM", "Secretary"])
            topics: 주제 태그
            decisions: 결정사항
            action_items: 할 일

        Returns:
            ConversationEntry
        """
        entry = ConversationEntry(
            timestamp=datetime.now().isoformat(),
            participants=participants,
            topics=topics or [],
            content=content,
            decisions=decisions or [],
            action_items=action_items or []
        )

        self.history.append(entry)
        self._save_entry(entry)

        return entry

    def _save_entry(self, entry: ConversationEntry):
        """Save entry to file"""
        date_str = datetime.now().strftime("%Y%m%d")
        time_str = datetime.now().strftime("%H%M%S")
        filename = f"session_{date_str}_{time_str}.json"

        filepath = self.sessions_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(asdict(entry), f, ensure_ascii=False, indent=2)

    def search(self, query: str, limit: int = 5) -> list[ConversationEntry]:
        """
        히스토리 검색

        Args:
            query: 검색어
            limit: 최대 결과 수

        Returns:
            관련 대화 목록
        """
        if not self.model:
            # Fallback: simple keyword search
            results = []
            query_lower = query.lower()
            for entry in reversed(self.history):
                if (query_lower in entry.content.lower() or
                    any(query_lower in t.lower() for t in entry.topics)):
                    results.append(entry)
                    if len(results) >= limit:
                        break
            return results

        # Use Gemini for semantic search
        try:
            history_text = "\n\n".join([
                f"[{e.timestamp}] Topics: {e.topics}\n{e.content[:500]}"
                for e in self.history[-100:]  # Last 100 entries
            ])

            prompt = f"""Search the conversation history for: "{query}"

History:
{history_text}

Return the indices (0-based) of the {limit} most relevant entries as JSON array."""

            response = self.model.generate_content(prompt)
            indices = json.loads(response.text)

            return [self.history[-(100-i)] for i in indices if i < len(self.history)]

        except Exception as e:
            print(f"[Archivist] Search error: {e}")
            return []

    def summarize_recent(self, hours: int = 24) -> str:
        """
        최근 대화 요약

        Args:
            hours: 몇 시간 이내의 대화

        Returns:
            요약 텍스트
        """
        if not self.model:
            return "Archivist not available"

        cutoff = datetime.now().timestamp() - (hours * 3600)
        recent = [
            e for e in self.history
            if datetime.fromisoformat(e.timestamp).timestamp() > cutoff
        ]

        if not recent:
            return "No recent conversations found."

        content = "\n\n".join([
            f"[{e.timestamp}]\nTopics: {e.topics}\nDecisions: {e.decisions}\n{e.content[:1000]}"
            for e in recent
        ])

        try:
            prompt = f"""Summarize these conversations:

{content}

Include:
1. Key topics discussed
2. Important decisions made
3. Pending action items"""

            response = self.model.generate_content(prompt)
            return response.text

        except Exception as e:
            return f"Summary error: {e}"

    def get_context(self, tokens: int = 10000) -> str:
        """
        현재 컨텍스트 가져오기 (PM에게 전달용)

        Args:
            tokens: 대략적인 토큰 제한

        Returns:
            컨텍스트 문자열
        """
        # Rough estimate: 4 chars per token
        char_limit = tokens * 4
        context_parts = []
        current_chars = 0

        for entry in reversed(self.history):
            entry_text = f"[{entry.timestamp}] {entry.topics}: {entry.content}"
            if current_chars + len(entry_text) > char_limit:
                break
            context_parts.insert(0, entry_text)
            current_chars += len(entry_text)

        return "\n\n".join(context_parts)


# Singleton instance
_archivist: Optional[Archivist] = None


def get_archivist() -> Archivist:
    """Get or create Archivist instance"""
    global _archivist
    if _archivist is None:
        _archivist = Archivist()
    return _archivist
