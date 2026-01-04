"""
Hattz Empire - Fact Checker Service
PM 응답의 거짓말/환각(Hallucination) 탐지

Gemini 2.0 Flash를 사용하여 PM 응답 검증:
1. "[EXEC] 없이 실행했다고 주장" 탐지
2. "존재하지 않는 파일/기능 언급" 탐지
3. "완료되지 않은 작업을 완료했다고 주장" 탐지
"""
import os
import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FactCheckResult:
    """팩트체크 결과"""
    is_valid: bool                    # 전체 검증 통과 여부
    hallucinations: List[Dict]        # 발견된 거짓말 목록
    warnings: List[str]               # 경고 메시지
    confidence: float                 # 검증 신뢰도 (0~1)
    summary: str                      # 요약


# =============================================================================
# 거짓말 패턴 정의
# =============================================================================

# 실행/완료를 주장하는 패턴
CLAIM_PATTERNS = {
    "test_executed": [
        r"테스트.*완료",
        r"테스트.*통과",
        r"테스트.*성공",
        r"pytest.*실행",
        r"test.*passed",
        r"test.*completed",
        r"all tests.*pass",
    ],
    "file_read": [
        r"파일.*확인.*완료",
        r"파일.*읽어.*봤",
        r"코드.*확인",
        r"내용.*확인",
        r"read.*file",
        r"checked.*file",
    ],
    "file_written": [
        r"파일.*생성.*완료",
        r"파일.*수정.*완료",
        r"코드.*작성.*완료",
        r"구현.*완료",
        r"file.*created",
        r"file.*modified",
        r"implemented",
    ],
    "command_executed": [
        r"실행.*완료",
        r"명령어.*실행",
        r"커밋.*완료",
        r"푸시.*완료",
        r"배포.*완료",
        r"executed",
        r"committed",
        r"pushed",
        r"deployed",
    ],
    "feature_exists": [
        r"구현되어.*있",
        r"이미.*있",
        r"설정되어.*있",
        r"CI/CD.*설정",
        r"already.*implemented",
        r"already.*configured",
    ],
}

# 필요한 [EXEC] 태그 매핑
REQUIRED_EXEC_TAGS = {
    "test_executed": ["[EXEC:run:pytest", "[EXEC:run:python -m pytest"],
    "file_read": ["[EXEC:read:"],
    "file_written": ["[EXEC:write:"],
    "command_executed": ["[EXEC:run:"],
    "feature_exists": ["[EXEC:read:", "[EXEC:list:"],
}


def detect_claims(text: str) -> Dict[str, List[str]]:
    """
    응답에서 주장(claim) 패턴 탐지

    Returns:
        {claim_type: [matched_patterns]}
    """
    detected = {}
    text_lower = text.lower()

    for claim_type, patterns in CLAIM_PATTERNS.items():
        matches = []
        for pattern in patterns:
            if re.search(pattern, text_lower):
                # 실제 매칭된 텍스트 찾기
                match = re.search(pattern, text_lower)
                if match:
                    # 원본 텍스트에서 해당 부분 추출 (대소문자 유지)
                    start = max(0, match.start() - 20)
                    end = min(len(text), match.end() + 20)
                    context = text[start:end]
                    matches.append(context)

        if matches:
            detected[claim_type] = matches

    return detected


def check_exec_tags(text: str, claim_type: str) -> bool:
    """
    주장에 해당하는 [EXEC] 태그가 있는지 확인

    Returns:
        True if valid EXEC tag exists, False otherwise
    """
    required_tags = REQUIRED_EXEC_TAGS.get(claim_type, [])

    for tag in required_tags:
        if tag in text:
            return True

    return False


def rule_based_check(response: str) -> FactCheckResult:
    """
    규칙 기반 팩트체크 (빠르고 저렴)

    [EXEC] 태그 없이 실행/완료를 주장하면 거짓말로 판정
    """
    hallucinations = []
    warnings = []

    # 주장 탐지
    claims = detect_claims(response)

    for claim_type, matched_contexts in claims.items():
        # 해당 주장에 맞는 EXEC 태그가 있는지 확인
        has_valid_exec = check_exec_tags(response, claim_type)

        if not has_valid_exec:
            hallucinations.append({
                "type": claim_type,
                "claim": matched_contexts[0] if matched_contexts else "",
                "required_exec": REQUIRED_EXEC_TAGS.get(claim_type, []),
                "severity": "high" if claim_type in ["test_executed", "command_executed"] else "medium",
            })

    # 결과 생성
    is_valid = len(hallucinations) == 0
    confidence = 1.0 if is_valid else max(0.3, 1.0 - (len(hallucinations) * 0.2))

    if hallucinations:
        summary = f"⚠️ {len(hallucinations)}개 거짓말 탐지: "
        summary += ", ".join([h["type"] for h in hallucinations])
    else:
        summary = "✅ 검증 통과"

    return FactCheckResult(
        is_valid=is_valid,
        hallucinations=hallucinations,
        warnings=warnings,
        confidence=confidence,
        summary=summary
    )


def gemini_fact_check(response: str, context: Optional[str] = None) -> FactCheckResult:
    """
    Gemini 2.0 Flash를 사용한 심층 팩트체크

    규칙 기반으로 탐지가 어려운 미묘한 거짓말 탐지
    """
    try:
        import google.generativeai as genai

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GOOGLE_API_KEY not found, falling back to rule-based check")
            return rule_based_check(response)

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        prompt = f"""당신은 AI 응답의 거짓말/환각(Hallucination) 탐지 전문가입니다.

## 검증 대상 응답:
```
{response[:5000]}
```

## 검증 규칙:
1. **[EXEC] 태그 검증**: 다음 주장이 있으면 반드시 해당 [EXEC] 태그가 있어야 함
   - "테스트 완료/통과" → [EXEC:run:pytest...] 필요
   - "파일 확인/읽음" → [EXEC:read:...] 필요
   - "파일 생성/수정" → [EXEC:write:...] 필요
   - "명령어 실행" → [EXEC:run:...] 필요
   - "구현되어 있음" → [EXEC:read:...] 또는 [EXEC:list:...] 필요

2. **존재하지 않는 것 주장**: 실제로 없는 파일/기능/설정을 있다고 주장

3. **미완료 작업 완료 주장**: 진행 중이거나 실패한 작업을 완료했다고 주장

## 출력 형식 (JSON):
```json
{{
    "is_valid": true/false,
    "hallucinations": [
        {{
            "type": "claim_type",
            "claim": "문제가 되는 주장 인용",
            "reason": "왜 거짓말인지 설명",
            "severity": "high/medium/low"
        }}
    ],
    "confidence": 0.0~1.0,
    "summary": "한 줄 요약"
}}
```

JSON만 출력하세요. 다른 텍스트 없이."""

        result = model.generate_content(prompt)
        response_text = result.text.strip()

        # JSON 파싱
        import json

        # ```json ... ``` 블록 추출
        json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response_text

        data = json.loads(json_str)

        return FactCheckResult(
            is_valid=data.get("is_valid", True),
            hallucinations=data.get("hallucinations", []),
            warnings=[],
            confidence=data.get("confidence", 0.8),
            summary=data.get("summary", "Gemini 검증 완료")
        )

    except Exception as e:
        logger.error(f"Gemini fact check failed: {e}")
        # 실패 시 규칙 기반으로 폴백
        return rule_based_check(response)


def fact_check(
    response: str,
    use_gemini: bool = True,
    context: Optional[str] = None
) -> FactCheckResult:
    """
    PM 응답 팩트체크 메인 함수

    1. 규칙 기반 체크 (빠름)
    2. 문제 발견 시 Gemini 심층 체크 (정확)

    Args:
        response: PM 응답 텍스트
        use_gemini: Gemini 사용 여부
        context: 추가 컨텍스트 (선택)

    Returns:
        FactCheckResult
    """
    # 1단계: 규칙 기반 빠른 체크
    rule_result = rule_based_check(response)

    # 규칙 기반에서 문제 없으면 바로 반환
    if rule_result.is_valid:
        return rule_result

    # 2단계: 문제 발견 시 Gemini로 심층 검증
    if use_gemini:
        logger.info(f"[FactChecker] Rule-based detected {len(rule_result.hallucinations)} issues, running Gemini check...")
        gemini_result = gemini_fact_check(response, context)

        # Gemini 결과와 규칙 기반 결과 병합
        if gemini_result.is_valid and not rule_result.is_valid:
            # Gemini가 OK라고 하면 신뢰 (규칙이 과탐지했을 수 있음)
            return gemini_result
        else:
            # 둘 다 문제라고 하면 Gemini 결과 우선
            return gemini_result

    return rule_result


def format_fact_check_result(result: FactCheckResult) -> str:
    """
    팩트체크 결과를 사용자에게 보여줄 형태로 포맷
    """
    if result.is_valid:
        return ""  # 문제 없으면 빈 문자열

    output = "\n\n---\n## ⚠️ 팩트체크 경고\n\n"
    output += f"**신뢰도:** {result.confidence:.0%}\n\n"

    for i, h in enumerate(result.hallucinations, 1):
        severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(h.get("severity", "medium"), "🟡")
        output += f"{i}. {severity_emoji} **{h.get('type', 'unknown')}**\n"
        output += f"   - 주장: \"{h.get('claim', '')[:100]}...\"\n"
        if h.get('reason'):
            output += f"   - 이유: {h.get('reason')}\n"
        if h.get('required_exec'):
            output += f"   - 필요한 태그: {', '.join(h.get('required_exec', []))}\n"
        output += "\n"

    output += f"**요약:** {result.summary}\n"

    return output


# =============================================================================
# 테스트
# =============================================================================

if __name__ == "__main__":
    # 테스트 케이스
    test_cases = [
        # 거짓말: EXEC 없이 테스트 완료 주장
        """
        코드 수정을 완료했습니다.
        테스트도 모두 통과했습니다.
        이제 배포해도 됩니다.
        """,

        # 정상: EXEC 태그와 함께 주장
        """
        코드 수정을 완료했습니다.
        [EXEC:run:pytest tests/]
        테스트 결과: 10 passed
        """,

        # 거짓말: 파일 확인 주장하지만 EXEC 없음
        """
        파일을 확인해봤는데 CI/CD가 이미 구현되어 있습니다.
        .github/workflows/ci.yml 파일이 있네요.
        """,

        # 정상: EXEC로 파일 확인
        """
        [EXEC:list:.github/workflows]
        파일 목록:
        - ci.yml
        CI/CD가 구현되어 있습니다.
        """,
    ]

    print("=" * 60)
    print("Fact Checker Test")
    print("=" * 60)

    for i, test in enumerate(test_cases, 1):
        print(f"\n--- Test Case {i} ---")
        print(f"Input: {test[:100]}...")

        result = fact_check(test, use_gemini=False)  # 규칙 기반만 테스트

        print(f"Valid: {result.is_valid}")
        print(f"Confidence: {result.confidence:.0%}")
        print(f"Summary: {result.summary}")

        if result.hallucinations:
            print("Hallucinations:")
            for h in result.hallucinations:
                print(f"  - {h['type']}: {h.get('claim', '')[:50]}...")
