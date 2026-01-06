"""
Hattz Empire - Session Rules (Pydantic 스키마)
CEO 완성본
"""
from __future__ import annotations
import json
import hashlib
from typing import Literal, Optional, List
from pydantic import BaseModel, Field

Mode = Literal["live", "paper", "backtest", "dev"]
RiskProfile = Literal["strict", "normal", "fast"]


class TradingRules(BaseModel):
    market_order: Literal["forbid", "allow"] = "forbid"
    max_order_usd: Optional[float] = None
    max_leverage: Optional[float] = 1
    entry_limit_pct_below_last: Optional[float] = None
    forbid_short: Optional[bool] = None
    forbid_new_positions: Optional[bool] = None


class CodeRules(BaseModel):
    forbid_sleep_in_api_loop: bool = True
    require_rate_limit_guard: bool = True
    secrets_hardcoding: Literal["forbid", "warn", "allow"] = "forbid"
    forbid_infinite_loop: bool = True


class QualityRules(BaseModel):
    allow_skip_tests: bool = False
    max_files_changed: Optional[int] = 12
    require_diff_summary: bool = True


class RulesBlock(BaseModel):
    trading: TradingRules = Field(default_factory=TradingRules)
    code: CodeRules = Field(default_factory=CodeRules)
    quality: QualityRules = Field(default_factory=QualityRules)


class SessionRules(BaseModel):
    session_id: str
    mode: Mode
    risk_profile: RiskProfile = "normal"
    rule_version: str = "v1"
    rules: RulesBlock = Field(default_factory=RulesBlock)
    overrides: List[str] = Field(default_factory=list)

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, sort_keys=True)

    def rules_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
