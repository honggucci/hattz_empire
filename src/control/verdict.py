"""
Hattz Empire - Verdict Parser
CEO 완성본 - Reviewer 출력 파싱
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List


@dataclass
class Violation:
    key: str
    detail: str


@dataclass
class ReviewVerdict:
    verdict: str  # PASS | REJECT
    violations: List[Violation]
    required_fixes: List[str]
    notes: List[str]


_VERDICT_RE = re.compile(r"^VERDICT:\s*(PASS|REJECT)\s*$", re.MULTILINE)


def parse_reviewer_output(text: str) -> ReviewVerdict:
    m = _VERDICT_RE.search(text)
    verdict = m.group(1) if m else "REJECT"

    def extract_section(header: str) -> str:
        pattern = rf"{header}:\s*(.*?)(?:\n[A-Z_ ]+:\s*|$)"
        mm = re.search(pattern, text, flags=re.DOTALL)
        return (mm.group(1).strip() if mm else "")

    violations_block = extract_section("VIOLATIONS")
    fixes_block = extract_section("REQUIRED_FIXES")
    notes_block = extract_section("NOTES")

    violations: List[Violation] = []
    for line in [ln.strip("- ").strip() for ln in violations_block.splitlines() if ln.strip()]:
        if ":" in line:
            k, d = line.split(":", 1)
            violations.append(Violation(k.strip(), d.strip()))
        else:
            violations.append(Violation("unknown", line))

    required_fixes = [ln.strip("- ").strip() for ln in fixes_block.splitlines() if ln.strip()]
    notes = [ln.strip("- ").strip() for ln in notes_block.splitlines() if ln.strip()]

    return ReviewVerdict(verdict=verdict, violations=violations, required_fixes=required_fixes, notes=notes)
