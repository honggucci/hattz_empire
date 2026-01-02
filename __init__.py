"""
QWAS AI Team
Multi-LLM orchestration system for QWAS trading bot development

Team Composition (v1.2):
- Secretary (GPT-5.2 Instant): 생각 정리 + 한글→영어 번역
- PM (Claude Opus 4.5): 코드 작성, 아키텍처, 작업 관리
- QA (GPT-5.2 Thinking): 코드 검증, 버그 탐지
- Archivist (Gemini 3 Pro): 대화 백업, 히스토리 (1M 토큰)
"""
from .config import TEAM_CONFIG, get_model_config, get_api_key
from .orchestrator import Orchestrator, WorkflowResult

__version__ = "1.2.0"
__all__ = [
    "TEAM_CONFIG",
    "get_model_config",
    "get_api_key",
    "Orchestrator",
    "WorkflowResult",
]
