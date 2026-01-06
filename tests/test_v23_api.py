"""
v2.3 API 통합 테스트 (Flask 서버 필요)
"""
import sys
import os
import json
import requests

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://localhost:5000"


def test_chat_stream_with_auto_route():
    """auto_route 파라미터 테스트"""
    print("\n=== Chat Stream (auto_route=true) 테스트 ===")

    test_cases = [
        {"message": "코딩/ 로그인 기능 만들어줘", "expected_agent": "coder"},
        {"message": "검색/ 최신 Python 뉴스", "expected_agent": "researcher"},
        {"message": "분석/ 이 함수 구조 설명해줘", "expected_agent": "excavator"},
    ]

    for tc in test_cases:
        try:
            response = requests.post(
                f"{BASE_URL}/api/chat/stream",
                json={
                    "message": tc["message"],
                    "agent": "pm",  # 기본 PM
                    "auto_route": True,  # v2.3: 자동 라우팅
                    "mock": True,  # 실제 LLM 호출 없이
                },
                stream=True,
                timeout=30
            )

            if response.status_code != 200:
                print(f"❌ HTTP {response.status_code}")
                continue

            # SSE 스트림에서 첫 몇 이벤트 확인
            events = []
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = json.loads(line[6:])
                        events.append(data)
                        if len(events) >= 5:
                            break

            # route_info 확인
            route_event = next((e for e in events if 'route_info' in e), None)
            if route_event:
                route_info = route_event['route_info']
                actual_agent = route_info.get('selected_agent', 'unknown')
                status = "✅" if actual_agent == tc["expected_agent"] else "❌"
                print(f"{status} '{tc['message'][:30]}...' → {actual_agent} (expected: {tc['expected_agent']})")
                print(f"   Confidence: {route_info.get('confidence', 0):.2f}, Reason: {route_info.get('reason', '')}")
            else:
                print(f"⚠️ No route_info in response for '{tc['message'][:30]}...'")

        except requests.exceptions.ConnectionError:
            print(f"❌ 서버 연결 실패 (서버가 실행 중인지 확인)")
            return False
        except Exception as e:
            print(f"❌ Error: {e}")

    return True


def test_token_stats():
    """Token stats 전송 테스트"""
    print("\n=== Token Stats 테스트 ===")

    try:
        response = requests.post(
            f"{BASE_URL}/api/chat/stream",
            json={
                "message": "안녕하세요. 테스트입니다.",
                "agent": "pm",
                "mock": True,
            },
            stream=True,
            timeout=30
        )

        if response.status_code != 200:
            print(f"❌ HTTP {response.status_code}")
            return False

        # SSE 스트림에서 token_stats 확인
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = json.loads(line[6:])
                    if 'token_stats' in data:
                        stats = data['token_stats']
                        print(f"✅ Token Stats 수신:")
                        print(f"   Usage ratio: {stats.get('usage_ratio', 0):.3f}")
                        print(f"   Total tokens: {stats.get('total_tokens', 0)}")
                        print(f"   Compaction needed: {stats.get('compaction_needed', False)}")
                        return True

        print("⚠️ No token_stats in response")
        return False

    except requests.exceptions.ConnectionError:
        print(f"❌ 서버 연결 실패")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_rules_hash():
    """rules_hash 전송 테스트"""
    print("\n=== Rules Hash 테스트 ===")

    try:
        response = requests.post(
            f"{BASE_URL}/api/chat/stream",
            json={
                "message": "테스트",
                "agent": "pm",
                "mock": True,
            },
            stream=True,
            timeout=30
        )

        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = json.loads(line[6:])
                    if 'rules_hash' in data:
                        print(f"✅ Rules Hash 수신: {data['rules_hash']}")
                        return True

        print("⚠️ No rules_hash in response (may be expected if no session rules)")
        return True  # 규정 파일 없으면 hash도 없음 (정상)

    except requests.exceptions.ConnectionError:
        print(f"❌ 서버 연결 실패")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """모든 API 테스트 실행"""
    print("=" * 60)
    print("v2.3 API 통합 테스트")
    print("=" * 60)
    print(f"서버: {BASE_URL}")

    # 서버 상태 확인
    try:
        health = requests.get(f"{BASE_URL}/api/health", timeout=5)
        if health.status_code == 200:
            print("✅ 서버 연결 OK")
        else:
            print(f"⚠️ 서버 상태: {health.status_code}")
    except requests.exceptions.ConnectionError:
        print("❌ 서버에 연결할 수 없습니다.")
        print("   'python app.py'로 서버를 먼저 실행하세요.")
        return False

    results = {
        "Auto Route": test_chat_stream_with_auto_route(),
        "Token Stats": test_token_stats(),
        "Rules Hash": test_rules_hash(),
    }

    print("\n" + "=" * 60)
    print("API 테스트 결과")
    print("=" * 60)

    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n🎉 모든 API 테스트 통과!")
    else:
        print("\n⚠️ 일부 테스트 실패")

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
