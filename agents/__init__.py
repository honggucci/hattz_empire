"""
Hattz Empire - AI Agents (Dual Engine + Single Engine)

듀얼 엔진: 각 역할에 최적화된 두 AI가 협업
싱글 엔진: 특수 역할 (Analyst - Gemini 3 Flash)
"""

# Base
from .base import (
    DualEngineAgent,
    EngineResponse,
    DualEngineResponse,
    APIClient,
    call_llm,
)

# Excavator (Claude Opus + GPT-5.2)
from .excavator import (
    Excavator,
    ExcavatorOutput,
    get_excavator,
)

# Strategist (GPT-5.2 + Gemini 3 Flash)
from .strategist import (
    Strategist,
    StrategyOutput,
    get_strategist,
)

# Coder (Opus + GPT-5.2)
from .coder import (
    Coder,
    CodeOutput,
    get_coder,
)

# QA (GPT-5.2 + Opus)
from .qa_dual import (
    QA,
    QAOutput,
    Issue,
    TestCase,
    get_qa,
)

# Analyst (Gemini 3 Flash - Single Engine)
from .analyst import (
    Analyst,
    AnalysisResult,
    get_analyst,
)

# Researcher (Gemini 3 Flash + Claude Opus)
from .researcher import (
    Researcher,
    ResearchOutput,
    ResearchFinding,
    WebSource,
    get_researcher,
)

# Documentor (Gemini 3 Flash + GPT-5-mini) - 산출물/문서 작성
from .documentor import (
    Documentor,
    DocumentResult,
    get_documentor,
)

__all__ = [
    # Base
    "DualEngineAgent",
    "EngineResponse",
    "DualEngineResponse",
    "APIClient",
    "call_llm",

    # Excavator
    "Excavator",
    "ExcavatorOutput",
    "get_excavator",

    # Strategist
    "Strategist",
    "StrategyOutput",
    "get_strategist",

    # Coder
    "Coder",
    "CodeOutput",
    "get_coder",

    # QA
    "QA",
    "QAOutput",
    "Issue",
    "TestCase",
    "get_qa",

    # Analyst
    "Analyst",
    "AnalysisResult",
    "get_analyst",

    # Researcher
    "Researcher",
    "ResearchOutput",
    "ResearchFinding",
    "WebSource",
    "get_researcher",

    # Documentor
    "Documentor",
    "DocumentResult",
    "get_documentor",
]
