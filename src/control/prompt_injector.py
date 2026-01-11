"""
Hattz Empire - Prompt Injector
CEO 완성본 - Worker/Reviewer에 SESSION CONTEXT 주입
"""
from __future__ import annotations
from dataclasses import dataclass
from .constitution import CONSTITUTION_V1
from .rules import SessionRules


@dataclass(frozen=True)
class InjectedContext:
    constitution: str
    session_rules_json: str
    session_id: str
    rules_hash: str
    rule_version: str


def build_injected_context(session_rules: SessionRules) -> InjectedContext:
    return InjectedContext(
        constitution=CONSTITUTION_V1,
        session_rules_json=session_rules.canonical_json(),
        session_id=session_rules.session_id,
        rules_hash=session_rules.rules_hash(),
        rule_version=session_rules.rule_version,
    )


def make_reviewer_prompt(
    ctx: InjectedContext,
    task: str,
    worker_output: str,
    diff_summary: str = "",
    test_results: str = "",
    static_gate_report: str = "",
) -> str:
    return f"""\
{ctx.constitution}

[SESSION RULES JSON]
{ctx.session_rules_json}

[STATIC GATE REPORT]
{static_gate_report}

[ROLE]
You are the Reviewer/Gatekeeper. Enforce Constitution + Session Rules.
If any violation exists, output REJECT.

[INPUTS]
- Session ID: {ctx.session_id}
- Rules Hash: {ctx.rules_hash}
- Rule Version: {ctx.rule_version}
- Task: {task}
- Worker Output: {worker_output}
- Diff/Files Changed: {diff_summary}
- Test Results: {test_results}

[CHECK ORDER]
1) Safety/Integrity (secrets, live-trade risk, infinite loops, API abuse)
2) Session Rules compliance
3) Change Quality (scope creep, missing rollback, regression risk)

[OUTPUT FORMAT — EXACT]
VERDICT: PASS | REJECT
VIOLATIONS:
- <rule_key or constitution_clause>: <what violated> | evidence: <file/line/log>
REQUIRED_FIXES:
- <actionable fix 1>
- <actionable fix 2>
NOTES:
- <optional>
"""


def make_worker_context(session_rules: SessionRules) -> str:
    """Worker에게 주입할 간단한 컨텍스트"""
    return f"""\
[SESSION CONTEXT]
- Session ID: {session_rules.session_id}
- Mode: {session_rules.mode}
- Risk Profile: {session_rules.risk_profile}
- Rules Hash: {session_rules.rules_hash()}

[RULES SUMMARY]
- Secrets Hardcoding: {session_rules.rules.code.secrets_hardcoding}
- Forbid Infinite Loop: {session_rules.rules.code.forbid_infinite_loop}
- Allow Skip Tests: {session_rules.rules.quality.allow_skip_tests}
- Max Files Changed: {session_rules.rules.quality.max_files_changed}

위 규칙을 준수하여 작업하세요.
"""
