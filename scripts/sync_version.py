"""
버전 동기화 스크립트

config.py의 VERSION을 기준으로 모든 문서 버전을 동기화합니다.

사용법:
    python scripts/sync_version.py           # 버전 불일치 검사
    python scripts/sync_version.py --fix     # 자동 수정
    python scripts/sync_version.py --bump    # 버전 올리기 (patch)
"""
import re
import sys
from pathlib import Path

# 프로젝트 루트
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import VERSION, VERSION_DATE, VERSION_CODENAME


# 버전 검사 대상 파일들
VERSION_FILES = {
    "CLAUDE.md": r"# Hattz Empire - AI Orchestration System \(v[\d.]+\)",
    "README.md": r"badge/version-v[\d.]+-blue",
    ".claude/agents/GLOBAL_RULES.md": r"# \[GLOBAL RULES\] - 전 에이전트 공통 헌법 \(v[\d.]+\)",
}

# Last Updated 패턴
LAST_UPDATED_PATTERN = r"\*Last Updated: [\d-]+ \| Hattz Empire v[\d.]+ \([^)]+\)\*"


def check_version(filepath: Path, pattern: str) -> tuple[bool, str]:
    """파일의 버전이 config.py와 일치하는지 확인"""
    if not filepath.exists():
        return False, f"[MISSING] {filepath}"

    content = filepath.read_text(encoding="utf-8")
    match = re.search(pattern, content)

    if not match:
        return False, f"[NO PATTERN] {filepath}"

    found = match.group()
    version_match = re.search(r"v?([\d.]+)", found)
    if version_match:
        file_version = version_match.group(1)
        if file_version == VERSION:
            return True, f"[OK] {filepath.name}: v{file_version}"
        else:
            return False, f"[MISMATCH] {filepath.name}: v{file_version} (expected v{VERSION})"

    return False, f"[ERROR] {filepath}"


def fix_version(filepath: Path, pattern: str) -> bool:
    """파일의 버전을 config.py 버전으로 수정"""
    if not filepath.exists():
        return False

    content = filepath.read_text(encoding="utf-8")

    # 버전 패턴 수정
    def replace_version(m):
        old = m.group()
        return re.sub(r"v[\d.]+", f"v{VERSION}", old)

    new_content = re.sub(pattern, replace_version, content)

    # Last Updated 패턴 수정
    new_last_updated = f"*Last Updated: {VERSION_DATE} | Hattz Empire v{VERSION} ({VERSION_CODENAME})*"
    new_content = re.sub(LAST_UPDATED_PATTERN, new_last_updated, new_content)

    if new_content != content:
        filepath.write_text(new_content, encoding="utf-8")
        return True
    return False


def main():
    args = sys.argv[1:]
    do_fix = "--fix" in args
    do_bump = "--bump" in args

    if do_bump:
        print("버전 bump는 config.py를 직접 수정하세요.")
        print(f"현재 버전: {VERSION}")
        return

    print(f"=== Hattz Empire 버전 동기화 ===")
    print(f"기준 버전: v{VERSION} ({VERSION_DATE})")
    print(f"코드명: {VERSION_CODENAME}")
    print()

    all_ok = True
    fixed_count = 0

    for rel_path, pattern in VERSION_FILES.items():
        filepath = ROOT / rel_path
        ok, msg = check_version(filepath, pattern)
        print(msg)

        if not ok:
            all_ok = False
            if do_fix:
                if fix_version(filepath, pattern):
                    print(f"   → 수정 완료")
                    fixed_count += 1

    print()
    if all_ok:
        print("[PASS] All documents version matched")
    elif do_fix:
        print(f"[FIXED] {fixed_count} files updated")
    else:
        print("[FAIL] Version mismatch found. Use --fix to auto-fix")
        sys.exit(1)


if __name__ == "__main__":
    main()
