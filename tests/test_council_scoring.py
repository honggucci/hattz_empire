"""
Council 점수 검증 테스트

Council이 제대로 점수를 주는지 3가지 케이스로 확인:
1. 완벽한 코드 → 높은 점수 (80+)
2. 버그 있는 코드 → 낮은 점수 (50-)
3. 애매한 코드 → 중간 점수 (50-80)
"""
import asyncio
import sys
from pathlib import Path

# 루트 경로 추가
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from src.infra.council import get_council


async def test_council():
    print("=" * 80)
    print("Council 점수 검증 테스트")
    print("=" * 80)

    council = get_council(session_id="test-council", project="hattz_empire")

    # =========================================================================
    # 테스트 1: 완벽한 코드 (80+ 기대)
    # =========================================================================
    print("\n[TEST 1] 완벽한 코드 - 기대 점수: 80+")
    print("-" * 80)

    perfect_code = """
```python
from functools import lru_cache

@lru_cache(maxsize=None)
def fibonacci(n: int) -> int:
    '''
    피보나치 수열을 메모이제이션으로 계산

    Args:
        n: 음이 아닌 정수

    Returns:
        n번째 피보나치 수

    Raises:
        ValueError: n이 음수일 때
    '''
    if n < 0:
        raise ValueError("n must be non-negative")
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

# 테스트 케이스
assert fibonacci(0) == 0
assert fibonacci(1) == 1
assert fibonacci(10) == 55
```
"""

    verdict1 = await council.convene(
        council_type="pm",
        content=perfect_code,
        context="Task: Create a fibonacci function with memoization and tests"
    )

    print(f"평균 점수: {verdict1.average_score:.1f}/10")
    print(f"판정: {verdict1.verdict.value}")
    print(f"요약: {verdict1.summary}")
    print(f"\n개별 페르소나 점수:")
    for judge in verdict1.judges:
        print(f"  {judge.icon} {judge.persona_name}: {judge.score}/10 - {judge.reasoning[:60]}...")

    # =========================================================================
    # 테스트 2: 버그 있는 코드 (50- 기대)
    # =========================================================================
    print("\n\n[TEST 2] 버그 있는 코드 - 기대 점수: 50-")
    print("-" * 80)

    buggy_code = """
```python
def fibonacci(n):
    # 메모이제이션 없음 (성능 문제)
    # 예외 처리 없음 (보안 문제)
    # 타입 힌트 없음
    # 테스트 없음
    return fibonacci(n-1) + fibonacci(n-2)  # n=0,1일 때 무한 재귀!
```
"""

    verdict2 = await council.convene(
        council_type="pm",
        content=buggy_code,
        context="Task: Create a fibonacci function with memoization and tests"
    )

    print(f"평균 점수: {verdict2.average_score:.1f}/10")
    print(f"판정: {verdict2.verdict.value}")
    print(f"요약: {verdict2.summary}")
    print(f"\n개별 페르소나 점수:")
    for judge in verdict2.judges:
        print(f"  {judge.icon} {judge.persona_name}: {judge.score}/10 - {judge.reasoning[:60]}...")

    # =========================================================================
    # 테스트 3: 애매한 코드 (50-80 기대)
    # =========================================================================
    print("\n\n[TEST 3] 애매한 코드 - 기대 점수: 50-80")
    print("-" * 80)

    mediocre_code = """
```python
def fibonacci(n):
    # 메모이제이션은 있음 (좋음)
    # 하지만 예외 처리 없음 (나쁨)
    # 타입 힌트 없음 (나쁨)
    # 테스트 없음 (나쁨)
    cache = {}

    def fib(x):
        if x in cache:
            return cache[x]
        if x <= 1:
            return x
        cache[x] = fib(x-1) + fib(x-2)
        return cache[x]

    return fib(n)
```
"""

    verdict3 = await council.convene(
        council_type="pm",
        content=mediocre_code,
        context="Task: Create a fibonacci function with memoization and tests"
    )

    print(f"평균 점수: {verdict3.average_score:.1f}/10")
    print(f"판정: {verdict3.verdict.value}")
    print(f"요약: {verdict3.summary}")
    print(f"\n개별 페르소나 점수:")
    for judge in verdict3.judges:
        print(f"  {judge.icon} {judge.persona_name}: {judge.score}/10 - {judge.reasoning[:60]}...")

    # =========================================================================
    # 결과 요약
    # =========================================================================
    print("\n\n" + "=" * 80)
    print("테스트 결과 요약")
    print("=" * 80)
    print(f"완벽한 코드: {verdict1.average_score:.1f}/10 (기대: 80+) - {'[PASS]' if verdict1.average_score >= 8.0 else '[FAIL]'}")
    print(f"버그 있는 코드: {verdict2.average_score:.1f}/10 (기대: 50-) - {'[PASS]' if verdict2.average_score < 5.0 else '[FAIL]'}")
    print(f"애매한 코드: {verdict3.average_score:.1f}/10 (기대: 50-80) - {'[PASS]' if 5.0 <= verdict3.average_score < 8.0 else '[FAIL]'}")

    # 전체 판정
    all_pass = (
        verdict1.average_score >= 8.0 and
        verdict2.average_score < 5.0 and
        5.0 <= verdict3.average_score < 8.0
    )

    print("\n" + "=" * 80)
    if all_pass:
        print("[SUCCESS] Council이 제대로 점수를 줍니다! Dual Loop에 통합 가능합니다.")
    else:
        print("[FAILURE] Council 점수가 이상합니다. 페르소나 프롬프트 점검 필요.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_council())
