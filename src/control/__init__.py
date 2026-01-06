"""
Hattz Empire - Control Module (내부통제 시스템)
CEO 완성본

- Constitution: 절대 금지 (헌법)
- Session Rules: 세션별 규정 (JSON 스키마)
- Static Checker: AST + Regex 철옹성 1차 게이트
- Reviewer Prompt: LLM 검토용 프롬프트
- Audit Log: JSONL 감사 추적
- Event Bus: 이벤트 발행
"""

from .constitution import CONSTITUTION_V1
from .rules import (
    SessionRules,
    TradingRules,
    CodeRules,
    QualityRules,
    RulesBlock,
    Mode,
    RiskProfile,
)
from .rules_store import RulesStore
from .static_check import StaticChecker, StaticViolation
from .jsonc_parser import (
    strip_jsonc_comments,
    load_jsonc,
    loads_jsonc,
    load_session_rules_jsonc,
    JsoncRulesStore,
)
from .prompt_injector import (
    InjectedContext,
    build_injected_context,
    make_reviewer_prompt,
    make_worker_context,
)
from .verdict import (
    Violation,
    ReviewVerdict,
    parse_reviewer_output,
)
from .audit_log import AuditLogger
from .event_bus import EventBus

__all__ = [
    # Constitution
    "CONSTITUTION_V1",
    # Rules
    "SessionRules",
    "TradingRules",
    "CodeRules",
    "QualityRules",
    "RulesBlock",
    "Mode",
    "RiskProfile",
    "RulesStore",
    # Static Checker
    "StaticChecker",
    "StaticViolation",
    # JSONC Parser
    "strip_jsonc_comments",
    "load_jsonc",
    "loads_jsonc",
    "load_session_rules_jsonc",
    "JsoncRulesStore",
    # Prompt Injector
    "InjectedContext",
    "build_injected_context",
    "make_reviewer_prompt",
    "make_worker_context",
    # Verdict
    "Violation",
    "ReviewVerdict",
    "parse_reviewer_output",
    # Audit & Event
    "AuditLogger",
    "EventBus",
]
