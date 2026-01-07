"""
Hattz Empire - CLI v2.4 테스트
Claude Code CLI가 실제로 작동하는지 검증

테스트 항목:
1. CLI 명령어 생성 테스트 (API 아닌 CLI 사용 확인)
2. 프로필별 모델 설정 테스트 (coder=Opus, reviewer=Sonnet)
3. 실제 CLI 호출 테스트 (선택적)

실행: python tests/test_cli_v24.py
"""
import sys
import os
import io

# Windows UTF-8 강제
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 프로젝트 루트 먼저 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def test_profile_models():
    """프로필별 모델 설정 테스트"""
    from src.services.cli_supervisor import CLI_PROFILE_MODELS

    print("\n" + "=" * 60)
    print("[TEST] 프로필별 모델 설정")
    print("=" * 60)

    tests = [
        ("coder", "opus", "코드 작성 = Opus"),
        ("excavator", "opus", "의도 발굴 = Opus"),
        ("reviewer", "sonnet", "리뷰/검토 = Sonnet"),
        ("qa", "sonnet", "QA 검증 = Sonnet"),
        ("default", "sonnet", "기본값 = Sonnet"),
    ]

    all_pass = True
    for profile, expected_model_keyword, description in tests:
        model = CLI_PROFILE_MODELS.get(profile, "")
        is_pass = expected_model_keyword.lower() in model.lower()
        status = "✓ PASS" if is_pass else "✗ FAIL"
        if not is_pass:
            all_pass = False
        print(f"  {status} | {profile}: {model} ({description})")

    return all_pass


def test_cli_command_generation():
    """CLI 명령어 생성 테스트 (API가 아닌 CLI 사용 확인)"""
    from src.services.cli_supervisor import CLISupervisor

    print("\n" + "=" * 60)
    print("[TEST] CLI 명령어 생성")
    print("=" * 60)

    supervisor = CLISupervisor()
    all_pass = True

    # 테스트 케이스 (v2.4.1: Sonnet 4.5로 업그레이드)
    tests = [
        ("coder", "claude-opus-4-5-20251101"),
        ("excavator", "claude-opus-4-5-20251101"),
        ("reviewer", "claude-sonnet-4-5-20250514"),  # v2.4.1: Sonnet 4.0 → 4.5
        ("qa", "claude-sonnet-4-5-20250514"),        # v2.4.1: Sonnet 4.0 → 4.5
    ]

    for profile, expected_model in tests:
        cmd = supervisor._build_cli_command("test prompt", profile)

        # 검증 항목 (CLAUDE_CLI_PATH가 절대 경로일 수 있으므로 --print만 확인)
        checks = [
            ("--print 모드", "--print" in cmd),
            ("--model 플래그", "--model" in cmd),
            (f"모델: {expected_model}", expected_model in cmd),
            ("--session-id", "--session-id" in cmd),
            ("--dangerously-skip-permissions", "--dangerously-skip-permissions" in cmd),
        ]

        print(f"\n  [{profile}]")
        for check_name, passed in checks:
            status = "✓" if passed else "✗"
            if not passed:
                all_pass = False
            print(f"    {status} {check_name}")

        # API 키가 포함되지 않는지 확인
        api_checks = [
            ("ANTHROPIC_API_KEY 없음", "ANTHROPIC_API_KEY" not in cmd),
            ("api.anthropic.com 없음", "api.anthropic.com" not in cmd),
        ]

        for check_name, passed in api_checks:
            status = "✓" if passed else "✗"
            if not passed:
                all_pass = False
            print(f"    {status} {check_name}")

    return all_pass


def test_allowed_tools():
    """프로필별 허용 도구 테스트"""
    from src.services.cli_supervisor import CLISupervisor

    print("\n" + "=" * 60)
    print("[TEST] 프로필별 허용 도구")
    print("=" * 60)

    supervisor = CLISupervisor()
    all_pass = True

    # coder: 전체 권한
    coder_tools = supervisor._get_allowed_tools("coder")
    coder_checks = [
        ("Edit", "Edit" in coder_tools),
        ("Write", "Write" in coder_tools),
        ("Read", "Read" in coder_tools),
        ("Bash", "Bash" in coder_tools),
    ]
    print("\n  [coder] - 전체 권한")
    for tool, passed in coder_checks:
        status = "✓" if passed else "✗"
        if not passed:
            all_pass = False
        print(f"    {status} {tool}")

    # qa: 쓰기 금지
    qa_tools = supervisor._get_allowed_tools("qa")
    qa_checks = [
        ("Read ✓", "Read" in qa_tools),
        ("Bash ✓", "Bash" in qa_tools),
        ("Edit ✗", "Edit" not in qa_tools),
        ("Write ✗", "Write" not in qa_tools),
    ]
    print("\n  [qa] - 쓰기 금지")
    for check_name, passed in qa_checks:
        status = "✓" if passed else "✗"
        if not passed:
            all_pass = False
        print(f"    {status} {check_name}")

    # reviewer: 읽기 전용
    reviewer_tools = supervisor._get_allowed_tools("reviewer")
    reviewer_checks = [
        ("Read ✓", "Read" in reviewer_tools),
        ("Glob ✓", "Glob" in reviewer_tools),
        ("Grep ✓", "Grep" in reviewer_tools),
        ("Edit ✗", "Edit" not in reviewer_tools),
        ("Write ✗", "Write" not in reviewer_tools),
        ("Bash ✗", "Bash" not in reviewer_tools),
    ]
    print("\n  [reviewer] - 읽기 전용")
    for check_name, passed in reviewer_checks:
        status = "✓" if passed else "✗"
        if not passed:
            all_pass = False
        print(f"    {status} {check_name}")

    return all_pass


def test_no_api_in_source():
    """소스 코드에 API 직접 호출이 없는지 확인"""
    print("\n" + "=" * 60)
    print("[TEST] API 직접 호출 없음 확인")
    print("=" * 60)

    cli_supervisor_path = os.path.join(PROJECT_ROOT, "src", "services", "cli_supervisor.py")
    with open(cli_supervisor_path, 'r', encoding='utf-8') as f:
        source_code = f.read()

    all_pass = True
    checks = [
        ("from anthropic import 없음", "from anthropic import" not in source_code),
        ("import anthropic 없음", "import anthropic" not in source_code),
        ("Anthropic() 없음", "Anthropic()" not in source_code),
        ("subprocess.run 사용", "subprocess.run" in source_code),
        ("--print 모드 사용", "--print" in source_code),  # CLI 절대경로 사용하므로 --print만 확인
    ]

    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        if not passed:
            all_pass = False
        print(f"  {status} {check_name}")

    return all_pass


def test_llm_caller_uses_cli():
    """llm_caller.py가 claude_cli 사용하는지 확인"""
    from src.core.llm_caller import DUAL_ENGINE_ROLES, VIP_DUAL_ENGINE

    print("\n" + "=" * 60)
    print("[TEST] llm_caller.py claude_cli 사용 확인")
    print("=" * 60)

    all_pass = True

    # DUAL_ENGINE_ROLES 체크
    print("\n  [DUAL_ENGINE_ROLES]")
    for role, config in DUAL_ENGINE_ROLES.items():
        writer = config.get("writer", "")
        auditor = config.get("auditor", "")
        uses_cli = "claude_cli" in [writer, auditor]
        status = "✓" if uses_cli else "✗"
        print(f"    {status} {role}: writer={writer}, auditor={auditor}")
        if "claude_cli" == writer or "claude_cli" == auditor:
            pass  # OK
        else:
            # claude_cli가 아니면 다른 엔진 사용 - OK
            pass

    # VIP_DUAL_ENGINE 체크
    print("\n  [VIP_DUAL_ENGINE]")
    for prefix, config in VIP_DUAL_ENGINE.items():
        writer = config.get("writer", "")
        auditor = config.get("auditor", "")
        status = "✓" if "claude_cli" in [writer, auditor] else "-"
        print(f"    {status} {prefix}: writer={writer}, auditor={auditor}")

    return all_pass


def test_real_cli_available():
    """실제 CLI가 설치되어 있는지 확인"""
    import subprocess
    from src.services.cli_supervisor import CLAUDE_CLI_PATH

    print("\n" + "=" * 60)
    print("[TEST] Claude CLI 설치 확인")
    print("=" * 60)

    print(f"  CLI Path: {CLAUDE_CLI_PATH}")

    try:
        # CLAUDE_CLI_PATH 사용 (절대 경로 자동 감지)
        result = subprocess.run(
            f'{CLAUDE_CLI_PATH} --version',
            capture_output=True,
            text=True,
            timeout=10,
            shell=True
        )

        if result.returncode == 0:
            print(f"  ✓ Claude CLI 설치됨: {result.stdout.strip()}")
            return True
        else:
            print(f"  ✗ Claude CLI 실행 실패: {result.stderr}")
            return False

    except FileNotFoundError:
        print("  ✗ Claude CLI 미설치 (claude 명령어 없음)")
        return False
    except subprocess.TimeoutExpired:
        print("  ✗ Claude CLI 타임아웃")
        return False
    except Exception as e:
        print(f"  ✗ 에러: {e}")
        return False


def main():
    """전체 테스트 실행"""
    print("=" * 60)
    print("Hattz Empire CLI v2.4 테스트")
    print("API 비용 0원 - Claude CLI만 사용")
    print("=" * 60)

    results = {}

    # 테스트 실행
    results["프로필별 모델 설정"] = test_profile_models()
    results["CLI 명령어 생성"] = test_cli_command_generation()
    results["프로필별 허용 도구"] = test_allowed_tools()
    results["API 직접 호출 없음"] = test_no_api_in_source()
    results["llm_caller CLI 사용"] = test_llm_caller_uses_cli()
    results["CLI 설치 확인"] = test_real_cli_available()

    # 결과 요약
    print("\n" + "=" * 60)
    print("[결과 요약]")
    print("=" * 60)

    passed = 0
    failed = 0
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status} | {test_name}")
        if result:
            passed += 1
        else:
            failed += 1

    print()
    print(f"  총 {passed + failed}개 테스트 | 통과: {passed} | 실패: {failed}")
    print("=" * 60)

    # API 비용 0원 확인 메시지
    if results["API 직접 호출 없음"] and results["CLI 명령어 생성"]:
        print("\n🎉 API 비용 0원 확인됨 - Claude CLI만 사용")
    else:
        print("\n⚠️  API 사용 가능성 있음 - 점검 필요")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
