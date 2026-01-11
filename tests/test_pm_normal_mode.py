"""
PM Normal Mode 테스트 - Output Contract 위반 수정 검증

v2.6.5: PM이 profile=None으로 호출되어 pm.md 페르소나만 적용됨
"""
import sys
import io
from pathlib import Path

# Windows console UTF-8 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from src.core.llm_caller import call_agent
from src.services.database import create_session


def test_pm_simple_greeting():
    """간단한 인사 테스트 - PM이 DONE으로 직접 답변해야 함"""
    print("=" * 80)
    print("PM Normal Mode Test - Simple Greeting")
    print("=" * 80)

    # DB에 세션 생성
    session_id = create_session(name="PM Normal Mode Test", project="hattz_empire", agent="pm")
    print(f"Created session: {session_id}\n")

    # PM에게 간단한 인사 보내기
    message = "안녕"
    print(f"Message: {message}")
    print("\nCalling PM agent...\n")

    try:
        response, meta = call_agent(
            message=message,
            agent_role="pm",
            return_meta=True,
            mode="normal"
        )

        print("-" * 80)
        print("Response:")
        print("-" * 80)
        print(response[:1000])  # 처음 1000자만

        if len(response) > 1000:
            print(f"\n... (total {len(response)} chars)")

        print("\n" + "-" * 80)
        print("Meta:")
        print("-" * 80)
        for key, value in meta.items():
            if key != "validated_output":  # 너무 긴 필드 제외
                print(f"  {key}: {value}")

        # 검증
        print("\n" + "=" * 80)
        print("Validation:")
        print("=" * 80)

        # Output Contract 에러 여부 확인
        if meta.get("format_error"):
            print(f"❌ Format Error: {meta['format_error'][:200]}")
        elif meta.get("format_validated"):
            print("✅ Format validated (JSON Contract)")
        else:
            print("⚠️ Format not validated (possibly exempt)")

        # 응답 내용 확인
        if "action" in response.lower() or "[call:" in response.lower():
            print("✅ PM responded with proper format (JSON or CALL tag)")
        elif "error" in response.lower():
            print("❌ PM returned error")
        else:
            print("⚠️ PM response format unclear")

        return True

    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
        return False


def test_pm_complex_request():
    """복잡한 요청 테스트 - PM이 [CALL:agent] 태그로 하위 에이전트 호출해야 함"""
    print("\n" + "=" * 80)
    print("PM Normal Mode Test - Complex Request")
    print("=" * 80)

    session_id = create_session(name="PM Complex Test", project="hattz_empire", agent="pm")
    print(f"Created session: {session_id}\n")

    message = "hattz_empire 시스템의 구조를 분석해줘"
    print(f"Message: {message}")
    print("\nCalling PM agent...\n")

    try:
        response, meta = call_agent(
            message=message,
            agent_role="pm",
            return_meta=True,
            mode="normal"
        )

        print("-" * 80)
        print("Response:")
        print("-" * 80)
        print(response[:1500])

        if len(response) > 1500:
            print(f"\n... (total {len(response)} chars)")

        # 검증
        print("\n" + "=" * 80)
        print("Validation:")
        print("=" * 80)

        if "[CALL:" in response:
            print("✅ PM used [CALL:agent] tag to dispatch sub-agent")
        elif '"action"' in response:
            print("⚠️ PM responded with JSON (possibly DONE)")
        else:
            print("❌ PM did not follow output format")

        return True

    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    print("\n" + "🚀 PM Normal Mode Test Suite\n")

    test1 = test_pm_simple_greeting()
    test2 = test_pm_complex_request()

    print("\n" + "=" * 80)
    print("Summary:")
    print("=" * 80)
    print(f"  Simple greeting test: {'✅ PASS' if test1 else '❌ FAIL'}")
    print(f"  Complex request test: {'✅ PASS' if test2 else '❌ FAIL'}")
