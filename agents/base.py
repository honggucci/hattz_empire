"""
Hattz Empire - Dual Engine Base Class
모든 듀얼 엔진 에이전트의 베이스
"""
from abc import ABC, abstractmethod
from typing import Any, Optional
from dataclasses import dataclass

# Import 호환성 (패키지/직접 실행 모두 지원)
try:
    from config import (
        DualEngineConfig, ModelConfig,
        get_dual_engine, get_api_key, get_system_prompt
    )
    from stream import get_stream, StreamLogger
except ImportError:
    from ..config import (
        DualEngineConfig, ModelConfig,
        get_dual_engine, get_api_key, get_system_prompt
    )
    from ..stream import get_stream, StreamLogger


@dataclass
class EngineResponse:
    """엔진 응답"""
    content: Any
    raw_response: Any = None
    tokens_used: int = 0
    model: str = ""
    error: Optional[str] = None


@dataclass
class DualEngineResponse:
    """듀얼 엔진 응답"""
    engine_1: EngineResponse
    engine_2: EngineResponse
    merged: Any
    merge_strategy: str
    confidence: float = 0.0


class DualEngineAgent(ABC):
    """
    듀얼 엔진 에이전트 베이스 클래스

    사용법:
        class Excavator(DualEngineAgent):
            def __init__(self):
                super().__init__("excavator")

            def _call_engine(self, model_config, input_data):
                # API 호출 구현
                pass

            def _merge_responses(self, resp1, resp2):
                # 병합 로직 구현
                pass
    """

    def __init__(self, role: str, restore_context: bool = True):
        self.role = role
        self.config: DualEngineConfig = get_dual_engine(role)
        self.stream: StreamLogger = get_stream()

        if not self.config:
            raise ValueError(f"Unknown role: {role}")

        # 시스템 프롬프트 + 이전 세션 컨텍스트 자동 주입
        base_prompt = get_system_prompt(role)
        if restore_context:
            try:
                from ..context_loader import get_context_loader
                context_addition = get_context_loader().build_system_prompt_addition(role)
                self.system_prompt = base_prompt + context_addition
            except Exception:
                self.system_prompt = base_prompt
        else:
            self.system_prompt = base_prompt

    @abstractmethod
    def _call_engine(self, model_config: ModelConfig, input_data: Any) -> EngineResponse:
        """
        개별 엔진 호출 (서브클래스에서 구현)

        Args:
            model_config: 모델 설정
            input_data: 입력 데이터

        Returns:
            EngineResponse
        """
        pass

    @abstractmethod
    def _merge_responses(
        self,
        response_1: EngineResponse,
        response_2: EngineResponse
    ) -> Any:
        """
        두 엔진 응답 병합 (서브클래스에서 구현)

        Args:
            response_1: 엔진1 응답
            response_2: 엔진2 응답

        Returns:
            병합된 결과
        """
        pass

    def process(self, input_data: Any, task_id: str = None) -> DualEngineResponse:
        """
        듀얼 엔진 처리

        Args:
            input_data: 입력 데이터
            task_id: Task ID (추적용)

        Returns:
            DualEngineResponse
        """
        strategy = self.config.merge_strategy

        # Stream 로그: 시작
        self.stream.log(
            f"{self.role}", None, "request",
            input_data, task_id=task_id
        )

        # Engine 1 호출
        resp_1 = self._call_engine(self.config.engine_1, input_data)
        self.stream.log(
            f"{self.role}.engine_1", f"{self.role}.merger", "response",
            resp_1.content if not resp_1.error else {"error": resp_1.error},
            task_id=task_id,
            metadata={"model": self.config.engine_1.model_id}
        )

        # Engine 2 호출
        resp_2 = self._call_engine(self.config.engine_2, input_data)
        self.stream.log(
            f"{self.role}.engine_2", f"{self.role}.merger", "response",
            resp_2.content if not resp_2.error else {"error": resp_2.error},
            task_id=task_id,
            metadata={"model": self.config.engine_2.model_id}
        )

        # 병합 전략에 따라 처리
        if strategy == "consensus":
            merged = self._merge_responses(resp_1, resp_2)
        elif strategy == "primary_fallback":
            # 엔진1 우선, 실패시 엔진2
            merged = resp_1.content if not resp_1.error else resp_2.content
        elif strategy == "parallel":
            # 둘 다 사용 (합집합)
            merged = self._merge_responses(resp_1, resp_2)
        else:
            merged = self._merge_responses(resp_1, resp_2)

        # Stream 로그: 병합 결과
        self.stream.log(
            f"{self.role}.merged", None, "response",
            merged, task_id=task_id,
            metadata={"strategy": strategy}
        )

        return DualEngineResponse(
            engine_1=resp_1,
            engine_2=resp_2,
            merged=merged,
            merge_strategy=strategy
        )

    def process_single(self, input_data: Any, engine: str = "engine_1", task_id: str = None) -> EngineResponse:
        """
        단일 엔진만 사용

        Args:
            input_data: 입력 데이터
            engine: "engine_1" 또는 "engine_2"
            task_id: Task ID (추적용)

        Returns:
            EngineResponse
        """
        if engine == "engine_1":
            model_config = self.config.engine_1
        else:
            model_config = self.config.engine_2

        response = self._call_engine(model_config, input_data)

        self.stream.log(
            f"{self.role}.{engine}", None, "response",
            response.content if not response.error else {"error": response.error},
            task_id=task_id,
            metadata={"model": model_config.model_id}
        )

        return response


class APIClient:
    """
    API 클라이언트 팩토리

    각 프로바이더별 클라이언트 생성
    """

    _openai_client = None
    _anthropic_client = None
    _google_model = None

    @classmethod
    def get_openai(cls):
        """OpenAI 클라이언트"""
        if cls._openai_client is None:
            try:
                from openai import OpenAI
                import os
                cls._openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            except ImportError:
                print("[ERROR] openai not installed. Run: pip install openai")
                return None
        return cls._openai_client

    @classmethod
    def get_anthropic(cls):
        """Anthropic 클라이언트"""
        if cls._anthropic_client is None:
            try:
                from anthropic import Anthropic
                import os
                cls._anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            except ImportError:
                print("[ERROR] anthropic not installed. Run: pip install anthropic")
                return None
        return cls._anthropic_client

    @classmethod
    def get_google(cls, model_id: str):
        """Google Gemini 모델"""
        try:
            import google.generativeai as genai
            import os
            genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
            return genai.GenerativeModel(model_id)
        except ImportError:
            print("[ERROR] google-generativeai not installed. Run: pip install google-generativeai")
            return None


def call_llm(model_config: ModelConfig, system_prompt: str, user_input: str) -> EngineResponse:
    """
    범용 LLM 호출 함수

    Args:
        model_config: 모델 설정
        system_prompt: 시스템 프롬프트
        user_input: 사용자 입력

    Returns:
        EngineResponse
    """
    provider = model_config.provider

    try:
        if provider == "openai":
            client = APIClient.get_openai()
            if not client:
                return EngineResponse(content=None, error="OpenAI client not available")

            response = client.chat.completions.create(
                model=model_config.model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input}
                ],
                temperature=model_config.temperature,
                max_tokens=model_config.max_tokens
            )

            return EngineResponse(
                content=response.choices[0].message.content,
                raw_response=response,
                tokens_used=response.usage.total_tokens if response.usage else 0,
                model=model_config.model_id
            )

        elif provider == "anthropic":
            client = APIClient.get_anthropic()
            if not client:
                return EngineResponse(content=None, error="Anthropic client not available")

            response = client.messages.create(
                model=model_config.model_id,
                system=system_prompt,
                messages=[{"role": "user", "content": user_input}],
                temperature=model_config.temperature,
                max_tokens=model_config.max_tokens
            )

            return EngineResponse(
                content=response.content[0].text,
                raw_response=response,
                tokens_used=response.usage.input_tokens + response.usage.output_tokens if response.usage else 0,
                model=model_config.model_id
            )

        elif provider == "google":
            model = APIClient.get_google(model_config.model_id)
            if not model:
                return EngineResponse(content=None, error="Google model not available")

            full_prompt = f"{system_prompt}\n\n---\n\n{user_input}"
            response = model.generate_content(full_prompt)

            return EngineResponse(
                content=response.text,
                raw_response=response,
                model=model_config.model_id
            )

        else:
            return EngineResponse(content=None, error=f"Unknown provider: {provider}")

    except Exception as e:
        return EngineResponse(content=None, error=str(e))
