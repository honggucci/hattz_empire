"""
Secretary Agent - GPT-5.2 Instant
Responsibilities: 생각 정리 + 한글→영어 번역 + 구조화
"""
import json
from typing import Optional
from dataclasses import dataclass

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from ..config import get_model_config, get_api_key, SYSTEM_PROMPTS


@dataclass
class StructuredRequest:
    """Secretary가 정리한 요청서"""
    request_type: str  # feature, bugfix, refactor, question
    summary: str
    requirements: list[str]
    context: str
    priority: str  # high, medium, low
    related_modules: list[str]
    original_korean: str


class Secretary:
    """
    Secretary Agent
    - CEO의 두서없는 한글 생각을 정리
    - 영어로 번역하여 토큰 비용 절감
    - 구조화된 요청서 생성
    """

    def __init__(self):
        self.config = get_model_config("secretary")
        self.api_key = get_api_key("secretary")
        self.system_prompt = SYSTEM_PROMPTS["secretary"]
        self.client = None

        if OpenAI and self.api_key:
            self.client = OpenAI(api_key=self.api_key)

    def process(self, korean_input: str) -> Optional[StructuredRequest]:
        """
        한글 입력을 받아 구조화된 영어 요청서로 변환

        Args:
            korean_input: CEO의 한글 생각/요청

        Returns:
            StructuredRequest or None if failed
        """
        if not self.client:
            print("[Secretary] OpenAI client not initialized. Check API key.")
            return None

        try:
            response = self.client.chat.completions.create(
                model=self.config.model_id,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": korean_input}
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)

            return StructuredRequest(
                request_type=result.get("request_type", "question"),
                summary=result.get("summary", ""),
                requirements=result.get("requirements", []),
                context=result.get("context", ""),
                priority=result.get("priority", "medium"),
                related_modules=result.get("related_modules", []),
                original_korean=korean_input
            )

        except Exception as e:
            print(f"[Secretary] Error processing request: {e}")
            return None

    def quick_translate(self, korean_text: str) -> str:
        """
        빠른 한글→영어 번역 (정리 없이)

        Args:
            korean_text: 번역할 한글 텍스트

        Returns:
            English translation
        """
        if not self.client:
            return korean_text

        try:
            response = self.client.chat.completions.create(
                model=self.config.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": "Translate Korean to English. Keep technical terms accurate. Be concise."
                    },
                    {"role": "user", "content": korean_text}
                ],
                temperature=0.3,
                max_tokens=1024
            )
            return response.choices[0].message.content

        except Exception as e:
            print(f"[Secretary] Translation error: {e}")
            return korean_text


# Singleton instance
_secretary: Optional[Secretary] = None


def get_secretary() -> Secretary:
    """Get or create Secretary instance"""
    global _secretary
    if _secretary is None:
        _secretary = Secretary()
    return _secretary
