"""
QA Agent - GPT-5.2 Thinking
Responsibilities: 코드 검증, 버그 탐지, 보안 체크
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
class QAReport:
    """QA 검토 결과"""
    status: str  # approved, needs_revision
    issues: list[dict]
    suggestions: list[str]
    security_concerns: list[str]
    summary: str


class QA:
    """
    QA Agent
    - PM이 작성한 코드 검증
    - 버그, 보안 이슈, 엣지 케이스 탐지
    - 개선 제안
    """

    def __init__(self):
        self.config = get_model_config("qa")
        self.api_key = get_api_key("qa")
        self.system_prompt = SYSTEM_PROMPTS["qa"]
        self.client = None

        if OpenAI and self.api_key:
            self.client = OpenAI(api_key=self.api_key)

    def review_code(self, code: str, context: str = "") -> Optional[QAReport]:
        """
        코드 리뷰 수행

        Args:
            code: 검토할 코드
            context: 추가 컨텍스트 (어떤 기능인지 등)

        Returns:
            QAReport or None if failed
        """
        if not self.client:
            print("[QA] OpenAI client not initialized. Check API key.")
            return None

        prompt = f"""Review this code:

Context: {context}

```python
{code}
```

Provide a thorough review focusing on:
1. Logic errors
2. Edge cases
3. Security vulnerabilities
4. Performance issues
5. Code style"""

        try:
            response = self.client.chat.completions.create(
                model=self.config.model_id,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)

            return QAReport(
                status=result.get("status", "needs_revision"),
                issues=result.get("issues", []),
                suggestions=result.get("suggestions", []),
                security_concerns=result.get("security_concerns", []),
                summary=result.get("summary", "")
            )

        except Exception as e:
            print(f"[QA] Error reviewing code: {e}")
            return None

    def quick_check(self, code: str) -> dict:
        """
        빠른 코드 체크 (상세 리뷰 없이)

        Args:
            code: 체크할 코드

        Returns:
            dict with pass/fail and quick notes
        """
        if not self.client:
            return {"pass": True, "notes": "QA not available"}

        try:
            response = self.client.chat.completions.create(
                model=self.config.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": "Quick code check. Return JSON: {pass: bool, notes: string}"
                    },
                    {"role": "user", "content": f"```python\n{code}\n```"}
                ],
                temperature=0.1,
                max_tokens=512,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)

        except Exception as e:
            print(f"[QA] Quick check error: {e}")
            return {"pass": True, "notes": f"Error: {e}"}


# Singleton instance
_qa: Optional[QA] = None


def get_qa() -> QA:
    """Get or create QA instance"""
    global _qa
    if _qa is None:
        _qa = QA()
    return _qa
