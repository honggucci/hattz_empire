"""
Hattz Empire - Static Checker
CEO 완성본 - AST + Regex 철옹성 버전

sleep 감지: time.sleep, asyncio.sleep, from time import sleep
무한루프: while True without break/return
시크릿 패턴: OpenAI, Slack, Google, AWS, GitHub
"""
from __future__ import annotations
import ast
import re
from dataclasses import dataclass
from typing import List, Optional, Iterable
from .rules import CodeRules


@dataclass
class StaticViolation:
    key: str
    detail: str
    evidence: str
    line: Optional[int] = None


_SECRET_PATTERNS = [
    r"sk-[a-zA-Z0-9_\-]{20,}",       # OpenAI (sk-..., sk-proj-...)
    r"sk-proj-[a-zA-Z0-9_\-]{10,}",  # OpenAI Project Key
    r"xox[baprs]-[0-9]{10,}",        # Slack
    r"AIza[0-9A-Za-z\-_]{35}",       # Google
    r"\bAKIA[0-9A-Z]{16}\b",         # AWS Access Key
    r"\bghp_[A-Za-z0-9]{20,}\b",     # GitHub Personal Token
    r"\bgho_[A-Za-z0-9]{20,}\b",     # GitHub OAuth Token
    r"api[_-]?key\s*[=:]\s*['\"][^'\"]{8,}['\"]",  # Generic API_KEY=...
    r"secret[_-]?key\s*[=:]\s*['\"][^'\"]{8,}['\"]",  # SECRET_KEY=...
]


def _regex_hits(patterns: Iterable[str], text: str, max_hits: int = 5) -> List[str]:
    hits: List[str] = []
    for pat in patterns:
        for m in re.finditer(pat, text):
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 40)
            hits.append(text[start:end].replace("\n", "\\n"))
            if len(hits) >= max_hits:
                return hits
    return hits


class StaticChecker:
    def __init__(self, rules: CodeRules):
        self.rules = rules

    def check(self, code: str) -> List[StaticViolation]:
        v: List[StaticViolation] = []

        # 1) 시크릿 하드코딩 검사
        if self.rules.secrets_hardcoding == "forbid":
            hits = _regex_hits(_SECRET_PATTERNS, code)
            for h in hits:
                v.append(StaticViolation(
                    key="code.secrets_hardcoding",
                    detail="Potential hardcoded secret detected.",
                    evidence=h
                ))

        # 2) 루프 안 sleep 검사
        if self.rules.forbid_sleep_in_api_loop:
            ev = self._sleep_in_loop_evidence(code)
            if ev:
                v.append(StaticViolation(
                    key="code.forbid_sleep_in_api_loop",
                    detail="sleep() detected inside a loop (blocking risk in hot loops).",
                    evidence=ev
                ))

        # 3) 무한루프 검사
        if self.rules.forbid_infinite_loop:
            ev = self._infinite_loop_evidence(code)
            if ev:
                v.append(StaticViolation(
                    key="code.forbid_infinite_loop",
                    detail="Possible infinite loop: while True without break/return nearby.",
                    evidence=ev
                ))

        return v

    def _sleep_in_loop_evidence(self, code: str) -> Optional[str]:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return None

        def is_sleep_call(call: ast.Call) -> bool:
            fn = call.func
            if isinstance(fn, ast.Attribute):
                return fn.attr == "sleep"
            if isinstance(fn, ast.Name):
                return fn.id == "sleep"
            return False

        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and is_sleep_call(child):
                        return f"loop@line={getattr(node, 'lineno', '?')}, sleep@line={getattr(child, 'lineno', '?')}"
        return None

    def _infinite_loop_evidence(self, code: str) -> Optional[str]:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return None

        for node in ast.walk(tree):
            if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value is True:
                has_break = any(isinstance(ch, ast.Break) for ch in ast.walk(node))
                has_return = any(isinstance(ch, ast.Return) for ch in ast.walk(node))
                if not has_break and not has_return:
                    return f"while_true@line={getattr(node, 'lineno', '?')}"
        return None
