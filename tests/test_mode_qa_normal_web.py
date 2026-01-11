"""
QA Test - 일반 모드 (Normal Mode) - Web Endpoint

실제 Flask 웹 엔드포인트를 테스트 (/api/chat with mode='normal')
Claude Sonnet 4 단독 호출 확인
"""
import sys
import io
import time
import requests
import json
from pathlib import Path

# Windows console UTF-8 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from src.services.database import create_session


def test_normal_mode_web():
    """일반 모드 Web Endpoint 테스트"""
    print("=" * 80)
    print("QA Test - 일반 모드 (Normal Mode) - Web Endpoint")
    print("=" * 80)

    # 세션 생성
    session_id = create_session(name="QA - Normal Mode (Web)", project="hattz_empire", agent="normal")
    print(f"Session created: {session_id}\n")

    # 테스트 메시지
    test_message = "프로젝트 상태를 알려줘"
    print(f"Test message: {test_message}\n")

    # Flask 서버 URL
    url = "http://localhost:5000/api/chat"

    # 요청 payload
    payload = {
        "message": test_message,
        "mode": "normal",  # v2.6.4 Mode system
        "session_id": session_id
    }

    print("[1/3] Flask 서버로 요청 전송 (mode=normal)...")
    start_time = time.time()

    try:
        # SSE 스트림 요청
        response = requests.post(url, json=payload, stream=True, timeout=60)
        response.raise_for_status()

        full_response = ""
        events = []

        # SSE 스트림 파싱
        for line in response.iter_lines(decode_unicode=True):
            if line.startswith("data: "):
                data_str = line[6:]  # "data: " 제거
                try:
                    event = json.loads(data_str)
                    events.append(event)

                    # 메시지 내용 수집
                    if event.get("type") == "message":
                        full_response += event.get("content", "")

                    # 진행 상황 출력
                    if event.get("type") == "normal_start":
                        print(f"  🔄 {event.get('message')}")
                    elif event.get("done"):
                        print("  ✅ 응답 완료")
                        break

                except json.JSONDecodeError:
                    pass

        elapsed = time.time() - start_time

        print(f"\n✅ 응답 수신 완료 (소요시간: {elapsed:.1f}초)")
        print(f"응답 길이: {len(full_response)} chars")
        print(f"응답 미리보기:\n{full_response[:500]}...\n")

        # 검증
        checks = []

        # Check 1: 응답 존재
        if full_response and len(full_response) > 0:
            checks.append(("✅", f"응답 존재 ({len(full_response)} chars)"))
        else:
            checks.append(("❌", "응답 없음"))

        # Check 2: 응답 속도 (10초 이내)
        if elapsed <= 10:
            checks.append(("✅", f"빠른 응답 ({elapsed:.1f}초 <= 10초)"))
        else:
            checks.append(("⚠️ ", f"느린 응답 ({elapsed:.1f}초 > 10초)"))

        # Check 3: 에러 메시지 없음
        error_keywords = ["ABORT", "ERROR", "FAIL", "exception", "traceback"]
        has_error = any(kw.upper() in full_response.upper() for kw in error_keywords)
        if not has_error:
            checks.append(("✅", "에러 메시지 없음"))
        else:
            checks.append(("❌", "에러 메시지 포함"))

        # Check 4: 정상 대화 패턴
        if len(full_response) > 20 and not has_error:
            checks.append(("✅", "정상 대화 응답"))
        else:
            checks.append(("❌", "비정상 응답 패턴"))

        # 결과 출력
        print("\n" + "=" * 80)
        print("검증 결과:")
        print("=" * 80)
        for status, message in checks:
            print(f"{status} {message}")

        # 전체 판정
        all_pass = all(status == "✅" for status, _ in checks)

        print("\n" + "=" * 80)
        if all_pass:
            print("🎉 [ALL CHECKS PASSED] 일반 모드 정상 작동!")
            print("=" * 80)
            return True
        else:
            failed_count = sum(1 for status, _ in checks if status == "❌")
            print(f"❌ [FAIL] {failed_count}/{len(checks)} 실패")
            print("=" * 80)
            return False

    except requests.exceptions.RequestException as e:
        print(f"\n❌ [ERROR] 웹 요청 실패: {e}")
        return False
    except Exception as e:
        print(f"\n❌ [ERROR] 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("Starting Normal Mode QA Test (Web Endpoint)...\n")

    result = test_normal_mode_web()

    print("\n\n" + "=" * 80)
    print("FINAL RESULTS")
    print("=" * 80)
    print(f"Normal Mode (Web) Test: {'✅ PASS' if result else '❌ FAIL'}")
    print("=" * 80)

    if result:
        print("\n🎉 [TEST PASSED] 일반 모드 웹 엔드포인트 정상 작동!")
        sys.exit(0)
    else:
        print("\n❌ [TEST FAILED] 일반 모드 점검 필요")
        sys.exit(1)
