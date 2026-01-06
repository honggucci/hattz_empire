"""
Hattz Empire - JSONC Parser
CEO 완성본 - JSON with Comments 파서

기능:
1. // 라인 주석 제거
2. /* */ 블록 주석 제거
3. 후행 쉼표 허용
4. Session Rules JSONC 파일 로드
"""
from __future__ import annotations
import re
import json
from pathlib import Path
from typing import Any, Dict, Union


def strip_jsonc_comments(text: str) -> str:
    """
    JSONC 텍스트에서 주석 제거

    지원:
    - // 라인 주석
    - /* */ 블록 주석
    - 후행 쉼표 (trailing commas)

    Args:
        text: JSONC 텍스트

    Returns:
        순수 JSON 텍스트
    """
    result = []
    i = 0
    in_string = False
    string_char = None

    while i < len(text):
        # 문자열 내부 체크
        if not in_string and text[i] in ('"', "'"):
            in_string = True
            string_char = text[i]
            result.append(text[i])
            i += 1
            continue

        if in_string:
            # 이스케이프 문자 처리
            if text[i] == '\\' and i + 1 < len(text):
                result.append(text[i:i+2])
                i += 2
                continue
            # 문자열 종료
            if text[i] == string_char:
                in_string = False
                string_char = None
            result.append(text[i])
            i += 1
            continue

        # 블록 주석 /* */
        if text[i:i+2] == '/*':
            end = text.find('*/', i + 2)
            if end == -1:
                break  # 주석이 닫히지 않음
            i = end + 2
            continue

        # 라인 주석 //
        if text[i:i+2] == '//':
            end = text.find('\n', i + 2)
            if end == -1:
                break  # 파일 끝
            i = end + 1
            result.append('\n')
            continue

        result.append(text[i])
        i += 1

    json_text = ''.join(result)

    # 후행 쉼표 제거 (,] 또는 ,})
    json_text = re.sub(r',\s*([}\]])', r'\1', json_text)

    return json_text


def load_jsonc(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    JSONC 파일 로드

    Args:
        file_path: JSONC 파일 경로

    Returns:
        파싱된 딕셔너리

    Raises:
        FileNotFoundError: 파일 없음
        json.JSONDecodeError: JSON 파싱 실패
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"JSONC file not found: {path}")

    text = path.read_text(encoding='utf-8')
    clean_json = strip_jsonc_comments(text)

    return json.loads(clean_json)


def loads_jsonc(text: str) -> Dict[str, Any]:
    """
    JSONC 문자열 파싱

    Args:
        text: JSONC 텍스트

    Returns:
        파싱된 딕셔너리
    """
    clean_json = strip_jsonc_comments(text)
    return json.loads(clean_json)


# =============================================================================
# Session Rules JSONC 로더
# =============================================================================

def load_session_rules_jsonc(file_path: Union[str, Path]) -> "SessionRules":
    """
    JSONC 형식의 Session Rules 파일 로드

    Args:
        file_path: JSONC 파일 경로

    Returns:
        SessionRules 객체
    """
    from .rules import SessionRules

    data = load_jsonc(file_path)
    return SessionRules(**data)


class JsoncRulesStore:
    """
    JSONC 지원 Rules Store

    .json과 .jsonc 파일 모두 지원
    """

    def __init__(self, base_dir: str = "config/session_rules"):
        """
        Args:
            base_dir: 규정 파일 디렉토리
        """
        self.base_dir = Path(base_dir)

    def load(self, session_id: str) -> "SessionRules":
        """
        Session Rules 로드

        .jsonc 우선, 없으면 .json 시도

        Args:
            session_id: 세션 ID

        Returns:
            SessionRules 객체

        Raises:
            FileNotFoundError: 파일 없음
        """
        from .rules import SessionRules

        # .jsonc 우선
        jsonc_path = self.base_dir / f"{session_id}.jsonc"
        if jsonc_path.exists():
            return load_session_rules_jsonc(jsonc_path)

        # .json 시도
        json_path = self.base_dir / f"{session_id}.json"
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding='utf-8'))
            return SessionRules(**data)

        raise FileNotFoundError(
            f"Session rules not found: {session_id} "
            f"(tried {jsonc_path} and {json_path})"
        )

    def list_sessions(self) -> list:
        """
        사용 가능한 세션 ID 목록

        Returns:
            세션 ID 리스트
        """
        sessions = set()

        if not self.base_dir.exists():
            return []

        for f in self.base_dir.glob("*.json"):
            sessions.add(f.stem)

        for f in self.base_dir.glob("*.jsonc"):
            sessions.add(f.stem)

        return sorted(sessions)

    def exists(self, session_id: str) -> bool:
        """세션 규정 존재 여부"""
        jsonc_path = self.base_dir / f"{session_id}.jsonc"
        json_path = self.base_dir / f"{session_id}.json"
        return jsonc_path.exists() or json_path.exists()
