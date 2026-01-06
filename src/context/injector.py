"""
Hattz Empire - Context Injector
CEO 완성본 - Constitution + Session Rules 프롬프트 주입

기능:
1. Constitution (헌법) 주입
2. Session Rules 주입
3. Worker/Reviewer별 컨텍스트 빌드
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from src.control.constitution import CONSTITUTION_V1
from src.control.rules import SessionRules


@dataclass
class InjectedPrompt:
    """주입된 프롬프트"""
    system_prompt: str
    rules_hash: str
    session_id: str
    mode: str
    risk_profile: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class ContextInjector:
    """
    컨텍스트 인젝터

    Worker/Reviewer 프롬프트에 Constitution + Session Rules 주입
    """

    def __init__(
        self,
        session_rules: Optional[SessionRules] = None,
        constitution: str = CONSTITUTION_V1,
    ):
        """
        Args:
            session_rules: 세션 규정 (None이면 기본값 사용)
            constitution: 헌법 텍스트
        """
        self._session_rules = session_rules
        self._constitution = constitution

    def set_session_rules(self, session_rules: SessionRules) -> None:
        """세션 규정 설정"""
        self._session_rules = session_rules

    def build_worker_prompt(
        self,
        role: str,
        task: str,
        additional_context: str = "",
    ) -> InjectedPrompt:
        """
        Worker 프롬프트 빌드

        Args:
            role: Worker 역할 (coder, qa, analyst 등)
            task: 수행할 태스크
            additional_context: 추가 컨텍스트

        Returns:
            InjectedPrompt
        """
        rules = self._session_rules
        if rules is None:
            from src.control.rules import SessionRules
            rules = SessionRules(
                session_id="default",
                mode="dev",
                risk_profile="normal"
            )

        system_prompt = f"""{self._constitution}

[SESSION CONTEXT]
- Session ID: {rules.session_id}
- Mode: {rules.mode}
- Risk Profile: {rules.risk_profile}
- Rules Hash: {rules.rules_hash()}

[RULES SUMMARY]
- Market Order: {rules.rules.trading.market_order}
- Max Leverage: {rules.rules.trading.max_leverage}x
- Secrets Hardcoding: {rules.rules.code.secrets_hardcoding}
- Allow Skip Tests: {rules.rules.quality.allow_skip_tests}
- Max Files Changed: {rules.rules.quality.max_files_changed}

[ROLE]
You are a {role}. Follow the Constitution and Session Rules strictly.

[ADDITIONAL CONTEXT]
{additional_context}

[TASK]
{task}
"""

        return InjectedPrompt(
            system_prompt=system_prompt,
            rules_hash=rules.rules_hash(),
            session_id=rules.session_id,
            mode=rules.mode,
            risk_profile=rules.risk_profile,
            metadata={"role": role}
        )

    def build_reviewer_prompt(
        self,
        worker_output: str,
        task: str,
        diff_summary: str = "",
        test_results: str = "",
        static_report: str = "",
    ) -> InjectedPrompt:
        """
        Reviewer 프롬프트 빌드

        Args:
            worker_output: Worker 출력물
            task: 원래 태스크
            diff_summary: 변경 파일 요약
            test_results: 테스트 결과
            static_report: Static Checker 결과

        Returns:
            InjectedPrompt
        """
        rules = self._session_rules
        if rules is None:
            from src.control.rules import SessionRules
            rules = SessionRules(
                session_id="default",
                mode="dev",
                risk_profile="normal"
            )

        system_prompt = f"""{self._constitution}

[SESSION RULES JSON]
{rules.canonical_json()}

[STATIC GATE REPORT]
{static_report or "No violations found."}

[ROLE]
You are the Reviewer/Gatekeeper. Enforce Constitution + Session Rules.
If any violation exists, output REJECT.

[INPUTS]
- Session ID: {rules.session_id}
- Rules Hash: {rules.rules_hash()}
- Rule Version: {rules.rule_version}
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

        return InjectedPrompt(
            system_prompt=system_prompt,
            rules_hash=rules.rules_hash(),
            session_id=rules.session_id,
            mode=rules.mode,
            risk_profile=rules.risk_profile,
            metadata={"role": "reviewer"}
        )

    def build_router_prompt(
        self,
        user_request: str,
        available_agents: list,
    ) -> InjectedPrompt:
        """
        Router 프롬프트 빌드 (에이전트 라우팅용)

        Args:
            user_request: 사용자 요청
            available_agents: 사용 가능한 에이전트 목록

        Returns:
            InjectedPrompt
        """
        rules = self._session_rules
        if rules is None:
            from src.control.rules import SessionRules
            rules = SessionRules(
                session_id="default",
                mode="dev",
                risk_profile="normal"
            )

        agents_list = "\n".join([f"- {a['name']}: {a['description']}" for a in available_agents])

        system_prompt = f"""[ROUTER AGENT]
You are the Router. Your job is to analyze user requests and route them to the appropriate agent.

[SESSION CONTEXT]
- Mode: {rules.mode}
- Risk Profile: {rules.risk_profile}

[AVAILABLE AGENTS]
{agents_list}

[USER REQUEST]
{user_request}

[OUTPUT FORMAT]
ROUTE_TO: <agent_name>
REASON: <why this agent is appropriate>
TASK_REFRAME: <reframed task for the selected agent>
"""

        return InjectedPrompt(
            system_prompt=system_prompt,
            rules_hash=rules.rules_hash(),
            session_id=rules.session_id,
            mode=rules.mode,
            risk_profile=rules.risk_profile,
            metadata={"role": "router"}
        )
