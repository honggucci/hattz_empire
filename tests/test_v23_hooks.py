"""
v2.3 Hook Chain 통합 테스트
"""
import sys
import os

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.hooks.chain import create_default_chain, create_minimal_chain
from src.hooks.base import HookContext, HookStage
from src.hooks.pre_review import PreReviewHook
from src.context.counter import TokenCounter, estimate_tokens
from src.services.router import quick_route, AgentType


def test_router_agent():
    """Router Agent 테스트"""
    print("\n=== Router Agent 테스트 ===")

    test_cases = [
        ("이 버그 좀 고쳐줘", AgentType.CODER),
        ("코드 구조 분석해줘", AgentType.EXCAVATOR),
        ("테스트 작성해줘", AgentType.QA),
        ("최신 React 문서 검색해줘", AgentType.RESEARCHER),
        ("검색/ 비트코인 가격", AgentType.RESEARCHER),  # CEO 프리픽스
        ("코딩/ 로그인 기능 구현", AgentType.CODER),  # CEO 프리픽스
        ("분석/ 이 함수 뭐하는 거야", AgentType.EXCAVATOR),  # CEO 프리픽스
        ("안녕하세요", AgentType.PM),  # 매칭 안 됨 → PM
    ]

    passed = 0
    for message, expected in test_cases:
        decision = quick_route(message)
        status = "✅" if decision.agent == expected else "❌"
        if decision.agent == expected:
            passed += 1
        print(f"{status} '{message[:30]}...' → {decision.agent.value} (expected: {expected.value}, conf: {decision.confidence:.2f})")

    print(f"\n결과: {passed}/{len(test_cases)} 통과")
    return passed == len(test_cases)


def test_token_counter():
    """TokenCounter 테스트"""
    print("\n=== TokenCounter 테스트 ===")

    counter = TokenCounter(
        max_tokens=1000,
        warning_threshold=0.75,
        compaction_threshold=0.85,
    )

    # 토큰 추가
    counter.add('user', '안녕하세요. 테스트 메시지입니다.')
    counter.add('assistant', 'Hello, this is a test response with some code.')

    stats = counter.get_stats()
    print(f"Total tokens: {stats['total_tokens']}")
    print(f"Usage ratio: {stats['usage_ratio']:.2%}")
    print(f"Should warn: {stats['should_warn']}")
    print(f"Should compact: {stats['should_compact']}")
    print(f"By role: {stats['by_role']}")

    # 임계치 테스트
    while counter.usage_ratio < 0.90:
        counter.add('user', '추가 메시지 ' * 50)

    print(f"\n압축 임계치 도달 후:")
    print(f"Usage ratio: {counter.usage_ratio:.2%}")
    print(f"Should compact: {counter.should_compact}")

    return counter.should_compact


def test_static_gate():
    """Static Gate 테스트"""
    print("\n=== Static Gate 테스트 ===")

    # 위반 케이스: API 키 포함
    bad_code = '''
def connect_api():
    api_key = "sk-proj-abc123xyz"  # OpenAI API Key
    return requests.get(url, headers={"Authorization": api_key})
'''

    # 정상 케이스
    good_code = '''
def connect_api():
    api_key = os.environ.get("OPENAI_API_KEY")
    return requests.get(url, headers={"Authorization": api_key})
'''

    # 무한루프 케이스
    loop_code = '''
def infinite():
    while True:
        print("loop")
'''

    violations = PreReviewHook.quick_check(bad_code)
    print(f"Bad code violations: {len(violations)}")
    for v in violations:
        print(f"  - {v['key']}: {v['detail']}")

    violations_good = PreReviewHook.quick_check(good_code)
    print(f"Good code violations: {len(violations_good)}")

    violations_loop = PreReviewHook.quick_check(loop_code)
    print(f"Loop code violations: {len(violations_loop)}")
    for v in violations_loop:
        print(f"  - {v['key']}: {v['detail']}")

    return len(violations) > 0 and len(violations_good) == 0


def test_hook_chain():
    """Hook Chain 테스트"""
    print("\n=== Hook Chain 테스트 ===")

    # Minimal Chain 테스트
    chain = create_minimal_chain()
    print(f"Minimal chain hooks:")
    for stage in HookStage:
        hooks = chain.get_hooks(stage)
        if hooks:
            print(f"  {stage.value}: {[h.name for h in hooks]}")

    # PRE_RUN 테스트 (세션 규정 로드)
    context = HookContext(session_id="test-session-001", task="테스트 태스크")
    result = chain.run_pre_run(context)
    print(f"\nPRE_RUN result: {result}")
    if result.success and result.results.get("PreRunHook"):
        output = result.results["PreRunHook"].output
        print(f"  - Using default: {output.get('using_default', False)}")
        print(f"  - Using inmemory: {output.get('using_inmemory_default', False)}")
        print(f"  - Rules hash: {output.get('rules_hash', '')[:16]}...")

    return result.success


def test_estimate_tokens():
    """토큰 추정 테스트"""
    print("\n=== 토큰 추정 테스트 ===")

    test_cases = [
        ("Hello, world!", 4),  # 영문
        ("안녕하세요", 4),  # 한글
        ("def foo():\n    return 1", 7),  # 코드
        ("", 0),  # 빈 문자열
    ]

    for text, expected_approx in test_cases:
        tokens = estimate_tokens(text)
        print(f"'{text[:20]}...' → {tokens} tokens (approx {expected_approx})")

    return True


def main():
    """모든 테스트 실행"""
    print("=" * 60)
    print("v2.3 Hook Chain 통합 테스트")
    print("=" * 60)

    results = {
        "Router Agent": test_router_agent(),
        "TokenCounter": test_token_counter(),
        "Static Gate": test_static_gate(),
        "Hook Chain": test_hook_chain(),
        "Token Estimation": test_estimate_tokens(),
    }

    print("\n" + "=" * 60)
    print("테스트 결과 요약")
    print("=" * 60)

    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n🎉 모든 테스트 통과!")
    else:
        print("\n⚠️ 일부 테스트 실패")

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
