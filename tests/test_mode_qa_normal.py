"""
QA Test - v2.6.4 일반 모드 (Normal Mode)

테스트 항목:
1. PM 단독 호출 확인
2. Claude Sonnet 4 사용 확인
3. 빠른 응답 (5-10초)
4. 내부 Writer/Auditor/Stamp 동작 확인 (있다면)
"""
import sys
import io
from pathlib import Path
import time

# Windows console UTF-8 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from src.services.database import create_session
from src.core.llm_caller import call_agent
from config import AGENT_CONFIG, DUAL_ENGINES


def test_normal_mode():
    """일반 모드: PM 단독 호출 테스트"""
    print("=" * 80)
    print("QA Test - 일반 모드 (Normal Mode)")
    print("=" * 80)

    # 세션 생성
    session_id = create_session(name="QA - Normal Mode", project="hattz_empire", agent="pm")
    print(f"Session created: {session_id}\n")

    # 테스트 메시지
    test_message = "프로젝트 상태를 알려줘"
    print(f"Test message: {test_message}\n")

    # PM 호출
    print("[1/3] PM 호출 중...")
    start_time = time.time()

    try:
        response = call_agent(
            message=test_message,
            agent_role='pm',
            use_dual_engine=False,  # PM은 Single Engine
            auto_council=False  # 위원회 불필요
        )

        elapsed = time.time() - start_time

        print(f"\n✅ PM 응답 완료 (소요시간: {elapsed:.1f}초)")
        print(f"응답 길이: {len(response)} chars")
        print(f"응답 미리보기:\n{response[:500]}...\n")

        # 검증
        checks = []

        # Check 1: 응답이 있는가?
        if response and len(response) > 0:
            checks.append(("✅", f"응답 존재 ({len(response)} chars)"))
        else:
            checks.append(("❌", "응답 없음"))

        # Check 2: 응답 속도 (10초 이내)
        if elapsed <= 10:
            checks.append(("✅", f"빠른 응답 ({elapsed:.1f}초 <= 10초)"))
        else:
            checks.append(("⚠️ ", f"느린 응답 ({elapsed:.1f}초 > 10초)"))

        # Check 3: 에러 메시지 포함 여부
        error_keywords = ["error", "exception", "failed", "abort"]
        has_error = any(kw in response.lower() for kw in error_keywords)
        if not has_error:
            checks.append(("✅", "에러 없음"))
        else:
            checks.append(("❌", "에러 메시지 포함"))

        print("\n" + "=" * 80)
        print("검증 결과:")
        print("=" * 80)
        for status, message in checks:
            print(f"{status} {message}")

        all_pass = all(status == "✅" for status, _ in checks)

        print("\n" + "=" * 80)
        if all_pass:
            print("✅ [PASS] 일반 모드 정상 작동")
        else:
            failed = sum(1 for s, _ in checks if s != "✅")
            print(f"❌ [FAIL] {failed}/{len(checks)} 실패")
        print("=" * 80)

        return all_pass

    except Exception as e:
        print(f"\n❌ [ERROR] PM 호출 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pm_engine_config():
    """PM 엔진 설정 확인"""
    print("\n" + "=" * 80)
    print("PM Engine Configuration Check")
    print("=" * 80)

    checks = []

    # Check 1: PM Agent Config 확인
    if "pm" in AGENT_CONFIG:
        pm_config = AGENT_CONFIG["pm"]
        print(f"\nPM Agent Config:")
        print(f"  Provider: {pm_config.get('provider')}")
        print(f"  Model: {pm_config.get('model', 'N/A')}")
        print(f"  Profile: {pm_config.get('profile', 'N/A')}")
        print(f"  Tier: {pm_config.get('tier')}")

        # Claude CLI 사용 확인
        if pm_config.get('provider') == 'claude_cli':
            checks.append(("✅", "Provider: claude_cli"))
        else:
            checks.append(("⚠️ ", f"Provider: {pm_config.get('provider')} (expected: claude_cli)"))

        # Profile 확인
        if pm_config.get('profile') == 'reviewer':
            checks.append(("✅", "Profile: reviewer (Sonnet 4)"))
        else:
            checks.append(("⚠️ ", f"Profile: {pm_config.get('profile')}"))

    else:
        checks.append(("❌", "PM config not found"))

    # Check 2: Dual Engine 확인 (PM은 Single Engine일 수도 있음)
    if "pm" in DUAL_ENGINES:
        print(f"\n⚠️  PM이 Dual Engine으로 설정되어 있습니다:")
        dual_config = DUAL_ENGINES["pm"]
        print(f"  Engine 1: {dual_config.engine_1.name}")
        print(f"  Engine 2: {dual_config.engine_2.name}")
        checks.append(("⚠️ ", "PM은 Dual Engine (비효율적)"))
    else:
        checks.append(("✅", "PM은 Single Engine"))

    print("\n" + "=" * 80)
    print("Configuration Checks:")
    print("=" * 80)
    for status, message in checks:
        print(f"{status} {message}")

    return all(status == "✅" for status, _ in checks)


if __name__ == "__main__":
    print("Starting QA Tests for Normal Mode...\n")

    result1 = test_pm_engine_config()
    print("\n")
    result2 = test_normal_mode()

    print("\n\n" + "=" * 80)
    print("FINAL RESULTS")
    print("=" * 80)
    print(f"Engine Config Test: {'✅ PASS' if result1 else '⚠️  WARNING'}")
    print(f"Normal Mode Test: {'✅ PASS' if result2 else '❌ FAIL'}")
    print("=" * 80)

    if result2:
        print("\n✅ [ALL TESTS PASSED] 일반 모드 정상 작동!")
        sys.exit(0)
    else:
        print("\n❌ [SOME TESTS FAILED] 일반 모드 점검 필요")
        sys.exit(1)
